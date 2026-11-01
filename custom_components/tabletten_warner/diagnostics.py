"""Diagnostics for the Tabletten-Warner integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from . import TablettenWarnerConfigEntry
from .const import CONF_ESCALATION_SERVICES, CONF_NOTIFY_SERVICES, CONF_USER_ID

TO_REDACT = {CONF_NOTIFY_SERVICES, CONF_ESCALATION_SERVICES, CONF_USER_ID, "user_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: TablettenWarnerConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    manager = entry.runtime_data
    now = dt_util.utcnow()
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "medications": {
            med.id: {
                "name": med.name,
                "times": [t.isoformat() for t in med.times],
                "weekdays": med.weekdays,
                "paused": manager.is_paused(med.id),
                "status": manager.medication_status(med.id, now).value,
                "next_dose": (n.isoformat() if (n := manager.next_dose(med.id, now)) else None),
            }
            for med in manager.medications.values()
        },
        "open_doses": [r.as_dict() for r in manager.history.open_doses()],
        "recent_doses": async_redact_data(
            [r.as_dict() for r in manager.history.records()[-50:]], TO_REDACT
        ),
    }
