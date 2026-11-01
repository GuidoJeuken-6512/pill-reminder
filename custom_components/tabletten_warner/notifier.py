"""Sending and clearing notifications for the Tabletten-Warner integration."""

from __future__ import annotations

from collections.abc import Iterable
import logging
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .const import (
    ACTION_SEPARATOR,
    ACTION_SNOOZE,
    ACTION_TAKEN,
    DOMAIN,
    NOTIFICATION_CHANNEL,
)
from .models import DoseRecord, Medication

_LOGGER = logging.getLogger(__name__)

# Entity based notify actions: they need a target entity and accept no `data`,
# so they cannot carry the action buttons of the Companion App.
UNSUPPORTED_NOTIFY_SERVICES = frozenset({"send_message", "persistent_notification"})

# Notification texts. They are sent to phones, so they cannot use the
# frontend translation system; the language follows the HA system language.
TEXTS: dict[str, dict[str, str]] = {
    "de": {
        "title": "💊 Zeit für {medication}",
        "message": "{person}, bitte {medication}{dosage} einnehmen (geplant {time}).",
        "repeat": " Erinnerung {count}.",
        "taken": "Eingenommen",
        "snooze": "Später ({minutes} Min.)",
        "escalation_title": "⚠️ {person}: {medication} nicht bestätigt",
        "escalation_message": (
            "{person} hat {medication} (geplant {time}) nach {count} Erinnerungen "
            "noch nicht als eingenommen bestätigt."
        ),
        "missed_title": "❌ {medication} verpasst",
        "missed_message": "{person} hat {medication} (geplant {time}) nicht eingenommen.",
    },
    "en": {
        "title": "💊 Time for {medication}",
        "message": "{person}, please take {medication}{dosage} (scheduled {time}).",
        "repeat": " Reminder {count}.",
        "taken": "Taken",
        "snooze": "Later ({minutes} min)",
        "escalation_title": "⚠️ {person}: {medication} not confirmed",
        "escalation_message": (
            "{person} has not confirmed {medication} (scheduled {time}) after {count} reminders."
        ),
        "missed_title": "❌ {medication} missed",
        "missed_message": "{person} did not take {medication} (scheduled {time}).",
    },
}


def action_id(action: str, dose_id: str) -> str:
    """Build the action identifier sent to the Companion App."""
    return f"{action}{ACTION_SEPARATOR}{dose_id}"


def parse_action(value: str) -> tuple[str, str] | None:
    """Split an action identifier into (action, dose_id)."""
    action, sep, dose_id = value.partition(ACTION_SEPARATOR)
    if not sep or action not in (ACTION_TAKEN, ACTION_SNOOZE) or not dose_id:
        return None
    return action, dose_id


class Notifier:
    """Send reminders for one person."""

    def __init__(self, hass: HomeAssistant, person: str) -> None:
        """Initialize the notifier."""
        self.hass = hass
        self.person = person

    def _texts(self) -> dict[str, str]:
        language = (self.hass.config.language or "en").split("-")[0]
        return TEXTS.get(language, TEXTS["en"])

    def _format(self, key: str, record: DoseRecord, med: Medication, **extra: Any) -> str:
        return self._texts()[key].format(
            person=self.person,
            medication=med.name,
            dosage=f" ({med.dosage})" if med.dosage else "",
            time=dt_util.as_local(record.scheduled).strftime("%H:%M"),
            **extra,
        )

    @staticmethod
    def tag(record: DoseRecord) -> str:
        """Notification tag, so repeated reminders replace each other."""
        return f"{DOMAIN}_{record.id}"

    async def _async_notify(
        self, services: Iterable[str], title: str, message: str, data: dict[str, Any]
    ) -> None:
        for service in services:
            service = service.removeprefix("notify.")
            if service in UNSUPPORTED_NOTIFY_SERVICES:
                _LOGGER.warning(
                    "notify.%s cannot deliver push notifications with buttons; "
                    "select a notify.mobile_app_… service instead",
                    service,
                )
                continue
            if not self.hass.services.has_service("notify", service):
                _LOGGER.warning("Notify service notify.%s does not exist", service)
                continue
            try:
                await self.hass.services.async_call(
                    "notify",
                    service,
                    {"title": title, "message": message, "data": data},
                    blocking=True,
                )
            except (HomeAssistantError, ValueError) as err:
                _LOGGER.warning("Sending notification via notify.%s failed: %s", service, err)

    async def async_send_reminder(
        self,
        services: list[str],
        record: DoseRecord,
        med: Medication,
        *,
        snooze_minutes: int,
        time_sensitive: bool,
        persistent: bool,
    ) -> None:
        """Send an actionable reminder to the person's phones."""
        texts = self._texts()
        title = self._format("title", record, med)
        message = self._format("message", record, med)
        if record.reminders_sent > 1:
            message += texts["repeat"].format(count=record.reminders_sent)

        data: dict[str, Any] = {
            "tag": self.tag(record),
            "group": DOMAIN,
            "actions": [
                {"action": action_id(ACTION_TAKEN, record.id), "title": texts["taken"]},
                {
                    "action": action_id(ACTION_SNOOZE, record.id),
                    "title": texts["snooze"].format(minutes=snooze_minutes),
                },
            ],
            # Android
            "channel": NOTIFICATION_CHANNEL,
            "importance": "high",
            "priority": "high",
            "ttl": 0,
            "sticky": "true",
        }
        if time_sensitive:
            # iOS: break through Focus modes
            data["push"] = {"interruption-level": "time-sensitive"}

        await self._async_notify(services, title, message, data)

        if persistent:
            persistent_notification.async_create(
                self.hass, message, title=title, notification_id=self.tag(record)
            )

    async def async_send_escalation(
        self, services: list[str], record: DoseRecord, med: Medication
    ) -> None:
        """Inform the escalation contact(s)."""
        await self._async_notify(
            services,
            self._format("escalation_title", record, med),
            self._format("escalation_message", record, med, count=record.reminders_sent),
            {"tag": f"{self.tag(record)}_escalation", "group": DOMAIN},
        )

    async def async_send_missed(
        self, services: list[str], record: DoseRecord, med: Medication
    ) -> None:
        """Inform about a missed dose."""
        await self._async_notify(
            services,
            self._format("missed_title", record, med),
            self._format("missed_message", record, med),
            {"tag": f"{self.tag(record)}_missed", "group": DOMAIN},
        )

    async def async_clear(
        self, services: list[str], record: DoseRecord, escalation_services: list[str]
    ) -> None:
        """Remove the reminder from all phones (and the frontend)."""
        await self._async_notify(services, "", "clear_notification", {"tag": self.tag(record)})
        if record.escalated and escalation_services:
            await self._async_notify(
                escalation_services,
                "",
                "clear_notification",
                {"tag": f"{self.tag(record)}_escalation"},
            )
        persistent_notification.async_dismiss(self.hass, self.tag(record))
