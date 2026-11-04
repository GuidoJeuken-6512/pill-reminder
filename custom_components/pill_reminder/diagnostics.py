"""Diagnostics for the Pill Reminder integration.

Diagnostics files are often pasted into public issues, so everything that
identifies a person (names, Home Assistant user ids, phones) and all health
data (medication names, dosages) is redacted. Schedules, states and counts
stay, as they are what is needed to debug the integration.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from . import PillReminderConfigEntry
from .const import (
    CONF_DOSAGE,
    CONF_ESCALATION_SERVICES,
    CONF_NAME,
    CONF_NOTIFY_SERVICES,
    CONF_PERSON_NAME,
    CONF_USER_ID,
)

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
    }
