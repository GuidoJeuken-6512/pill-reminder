"""Diagnostics for the Pill Reminder integration.

Diagnostics files are often pasted into public issues, so everything that
identifies a person (names, Home Assistant user ids, phones) and all health
data (medication names, dosages, height, measured values) is redacted or left
out. Schedules, states, counts and timestamps stay, as they are what is needed
to debug the integration.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from . import PillReminderConfigEntry
from .const import (
    CONF_DOSAGE,
    CONF_ESCALATION_SERVICES,
    CONF_HEIGHT,
    CONF_NAME,
    CONF_NOTIFY_SERVICES,
    CONF_PERSON_NAME,
    CONF_USER_ID,
)
from .scheduler import ReminderManager

TO_REDACT = {
    # person
    CONF_PERSON_NAME,
    CONF_USER_ID,
    "title",  # config entry and subentry titles are the person / medication name
    "unique_id",  # the HA user id or the slugified person name
    # phones / escalation contacts
    CONF_NOTIFY_SERVICES,
    CONF_ESCALATION_SERVICES,
    # health data
    CONF_NAME,
    CONF_DOSAGE,
    "medication_name",
    CONF_HEIGHT,
    "value",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: PillReminderConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    manager = entry.runtime_data
    now = dt_util.utcnow()
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        # Keyed by the (random) subentry id only; no names or dosages.
        "medications": {
            med.id: {
                "times": [t.isoformat() for t in med.times],
                "weekdays": med.weekdays,
                "paused": manager.is_paused(med.id),
                "status": manager.medication_status(med.id, now).value,
                "next_dose": (n.isoformat() if (n := manager.next_dose(med.id, now)) else None),
            }
            for med in manager.medications.values()
        },
        "open_doses": async_redact_data(
            [r.as_dict() for r in manager.history.open_doses()], TO_REDACT
        ),
        "recent_doses": async_redact_data(
            [r.as_dict() for r in manager.history.records()[-50:]], TO_REDACT
        ),
        "measurements": async_redact_data(_measurements(manager, now), TO_REDACT),
    }


def _measurements(manager: ReminderManager, now: datetime) -> dict[str, Any]:
    """Reminder settings and counts per measurement type; no values, no height."""
    body = manager.body
    result: dict[str, Any] = {
        "height_set": body.height is not None,
        "repeat_interval_minutes": (
            body.repeat_interval.total_seconds() / 60 if body.repeat_interval else 0
        ),
    }
    for sub_id, tracked in body.tracked.items():
        key = tracked.metric.key
        latest = body.latest(key)
        state = body.store.reminders.get(key)
        result[key] = {
            "subentry_id": sub_id,
            "reminder_enabled": tracked.reminder_enabled,
            "reminder_time": tracked.reminder_time.isoformat(),
            "weekdays": list(tracked.weekdays),
            "due": body.is_due(sub_id),
            "next_reminder": (n.isoformat() if (n := tracked.next_slot(now)) else None),
            "count": len(body.store.measurements(key)),
            "last_measured": latest.measured_at.isoformat() if latest else None,
            "last_reminder": state.as_dict() if state else None,
        }
    return result
