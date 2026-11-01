"""Describe Pill Reminder events in the logbook."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.logbook import (
    LOGBOOK_ENTRY_ENTITY_ID,
    LOGBOOK_ENTRY_MESSAGE,
    LOGBOOK_ENTRY_NAME,
    LazyEventPartialState,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_MEDICATION,
    ATTR_PERSON,
    ATTR_REMINDERS_SENT,
    ATTR_SCHEDULED,
    ATTR_SOURCE,
    DOMAIN,
    EVENT_DOSE_DUE,
    EVENT_DOSE_MISSED,
    EVENT_DOSE_SKIPPED,
    EVENT_DOSE_SNOOZED,
    EVENT_DOSE_TAKEN,
    EVENT_ESCALATED,
    EVENT_REMINDER_SENT,
)

MESSAGES = {
    "de": {
        EVENT_DOSE_DUE: "{medication} ({time}) ist fällig",
        EVENT_DOSE_TAKEN: "hat {medication} ({time}) eingenommen [{source}]",
        EVENT_DOSE_MISSED: "hat {medication} ({time}) NICHT eingenommen",
        EVENT_DOSE_SKIPPED: "hat {medication} ({time}) übersprungen",
        EVENT_DOSE_SNOOZED: "hat die Erinnerung für {medication} ({time}) verschoben",
        EVENT_REMINDER_SENT: "Erinnerung {count} für {medication} ({time}) gesendet",
        EVENT_ESCALATED: "Eskalation: {medication} ({time}) nach {count} Erinnerungen unbestätigt",
    },
    "en": {
        EVENT_DOSE_DUE: "{medication} ({time}) is due",
        EVENT_DOSE_TAKEN: "took {medication} ({time}) [{source}]",
        EVENT_DOSE_MISSED: "did NOT take {medication} ({time})",
        EVENT_DOSE_SKIPPED: "skipped {medication} ({time})",
        EVENT_DOSE_SNOOZED: "snoozed the reminder for {medication} ({time})",
        EVENT_REMINDER_SENT: "sent reminder {count} for {medication} ({time})",
        EVENT_ESCALATED: "escalated: {medication} ({time}) unconfirmed after {count} reminders",
    },
}


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[
        [str, str, Callable[[LazyEventPartialState], dict[str, Any]]], None
    ],
) -> None:
    """Describe logbook events."""
    language = (hass.config.language or "en").split("-")[0]
    messages = MESSAGES.get(language, MESSAGES["en"])

    @callback
    def describe(event: LazyEventPartialState) -> dict[str, Any]:
        data = event.data
        scheduled = dt_util.parse_datetime(data.get(ATTR_SCHEDULED) or "")
        return {
            LOGBOOK_ENTRY_NAME: data.get(ATTR_PERSON, "Pill Reminder"),
            LOGBOOK_ENTRY_ENTITY_ID: data.get("entity_id"),
            LOGBOOK_ENTRY_MESSAGE: messages[event.event_type].format(
                medication=data.get(ATTR_MEDICATION, "?"),
                time=dt_util.as_local(scheduled).strftime("%H:%M") if scheduled else "?",
                source=data.get(ATTR_SOURCE) or "-",
                count=data.get(ATTR_REMINDERS_SENT, 0),
            ),
        }

    for event_type in messages:
        async_describe_event(DOMAIN, event_type, describe)
