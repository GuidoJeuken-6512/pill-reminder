"""Calendar of all doses (past and planned) of a person."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import TablettenWarnerConfigEntry
from .entity import PersonEntity
from .models import DoseRecord, DoseStatus

PARALLEL_UPDATES = 0

EVENT_LENGTH = timedelta(minutes=15)

STATUS_ICONS = {
    DoseStatus.SCHEDULED: "🕒",
    DoseStatus.DUE: "🔔",
    DoseStatus.SNOOZED: "💤",
    DoseStatus.TAKEN: "✅",
    DoseStatus.MISSED: "❌",
    DoseStatus.SKIPPED: "⏭️",
    DoseStatus.PAUSED: "⏸️",
}

# Event descriptions are plain text, so they use their own small text table
# (like the phone notifications), chosen by the HA system language.
TEXTS: dict[str, dict[str, str]] = {
    "de": {
        "dosage": "Dosis: {value}",
        "scheduled": "Geplant: {value}",
        "status": "Status: {value}",
        "taken_at": "Eingenommen um {value}",
        "late": " ({minutes} Min. später)",
        "early": " ({minutes} Min. früher)",
        "on_time": " (pünktlich)",
        "reminders": "Erinnerungen: {value}",
        "escalated": "Eskaliert: ja",
        "source": "Bestätigt über: {value}",
        "scheduled_status": "geplant",
        "due": "fällig",
        "snoozed": "verschoben",
        "taken": "eingenommen",
        "missed": "verpasst",
        "skipped": "übersprungen",
        "paused": "pausiert",
        "button": "Button",
        "notification": "Handy-Benachrichtigung",
        "service": "Service",
        "automatic": "automatisch",
    },
    "en": {
        "dosage": "Dosage: {value}",
        "scheduled": "Scheduled: {value}",
        "status": "Status: {value}",
        "taken_at": "Taken at {value}",
        "late": " ({minutes} min late)",
        "early": " ({minutes} min early)",
        "on_time": " (on time)",
        "reminders": "Reminders: {value}",
        "escalated": "Escalated: yes",
        "source": "Confirmed via: {value}",
        "scheduled_status": "scheduled",
        "due": "due",
        "snoozed": "snoozed",
        "taken": "taken",
        "missed": "missed",
        "skipped": "skipped",
        "paused": "paused",
        "button": "button",
        "notification": "phone notification",
        "service": "service",
        "automatic": "automatic",
    },
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TablettenWarnerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the calendar."""
    async_add_entities([DoseCalendar(entry.runtime_data, "doses")])


class DoseCalendar(PersonEntity, CalendarEntity):
    """All doses of a person as calendar events."""

    _attr_event: CalendarEvent | None = None

    @property
    def event(self) -> CalendarEvent | None:
        """Current or next event."""
        return self._attr_event

    def _texts(self) -> dict[str, str]:
        language = (self.hass.config.language or "en").split("-")[0]
        return TEXTS.get(language, TEXTS["en"])

    def _to_event(self, record: DoseRecord) -> CalendarEvent:
        texts = self._texts()
        start = dt_util.as_local(record.scheduled)
        end = start + EVENT_LENGTH
        status_key = "scheduled_status" if record.status == DoseStatus.SCHEDULED else record.status
        lines: list[str] = []

        med = self.manager.medications.get(record.medication_id)
        if med and med.dosage:
            lines.append(texts["dosage"].format(value=med.dosage))
        lines.append(texts["scheduled"].format(value=start.strftime("%H:%M")))
        lines.append(texts["status"].format(value=texts[status_key]))

        if record.status == DoseStatus.TAKEN and record.resolved_at:
            taken = dt_util.as_local(record.resolved_at)
            delay = round((taken - start).total_seconds() / 60)
            line = texts["taken_at"].format(value=taken.strftime("%H:%M"))
            if delay > 0:
                line += texts["late"].format(minutes=delay)
            elif delay < 0:
                line += texts["early"].format(minutes=-delay)
            else:
                line += texts["on_time"]
            lines.append(line)
            # Show the delay as event length (at least the default length).
            end = max(end, taken)

        if record.reminders_sent:
            lines.append(texts["reminders"].format(value=record.reminders_sent))
        if record.escalated:
            lines.append(texts["escalated"])
        if record.is_resolved and record.source:
            lines.append(texts["source"].format(value=texts.get(record.source, record.source)))

        return CalendarEvent(
            start=start,
            end=end,
            summary=f"{STATUS_ICONS[record.status]} {record.medication_name}",
            description="\n".join(lines),
            uid=record.id,
        )

    def _update_from_manager(self) -> None:
        now = dt_util.utcnow()
        open_doses = [
            r
            for r in self.manager.history.open_doses()
            if r.medication_id in self.manager.medications
        ]
        if open_doses:
            self._attr_event = self._to_event(open_doses[0])
            return
        upcoming = self.manager.upcoming(now, now + timedelta(days=8))
        nxt = min(upcoming, key=lambda r: r.scheduled, default=None)
        self._attr_event = self._to_event(nxt) if nxt else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return doses in a time range."""
        start = dt_util.as_utc(start_date)
        end = dt_util.as_utc(end_date)
        records = self.manager.history.records(start=start, end=end)
        records += self.manager.upcoming(start, end)
        return [self._to_event(r) for r in sorted(records, key=lambda r: r.scheduled)]
