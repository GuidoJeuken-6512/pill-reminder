"""Data models for the Tabletten-Warner integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from typing import Any

from homeassistant.config_entries import ConfigSubentry
from homeassistant.util import dt as dt_util

from .const import (
    ALL_WEEKDAYS,
    CONF_CREATED_AT,
    CONF_DOSAGE,
    CONF_EARLY_MINUTES,
    CONF_LATE_MINUTES,
    CONF_NAME,
    CONF_TIMES,
    CONF_WEEKDAYS,
    DEFAULT_EARLY_MINUTES,
    DEFAULT_LATE_MINUTES,
)


class DoseStatus(StrEnum):
    """Status of a single scheduled dose."""

    SCHEDULED = "scheduled"
    DUE = "due"
    SNOOZED = "snoozed"
    TAKEN = "taken"
    MISSED = "missed"
    SKIPPED = "skipped"
    PAUSED = "paused"


OPEN_STATES = frozenset({DoseStatus.DUE, DoseStatus.SNOOZED})
RESOLVED_STATES = frozenset(
    {DoseStatus.TAKEN, DoseStatus.MISSED, DoseStatus.SKIPPED, DoseStatus.PAUSED}
)


def parse_time(value: str) -> time:
    """Parse 'HH:MM' or 'HH:MM:SS' into a time object."""
    parsed = dt_util.parse_time(value.strip())
    if parsed is None:
        raise ValueError(f"Invalid time: {value}")
    return parsed.replace(second=0, microsecond=0)


@dataclass(slots=True)
class Medication:
    """A medication with its schedule (one config subentry)."""

    id: str
    name: str
    dosage: str
    times: list[time]
    weekdays: list[int]
    early: timedelta
    late: timedelta
    created_at: datetime | None

    @classmethod
    def from_subentry(cls, subentry: ConfigSubentry) -> Medication:
        """Build a medication from its config subentry."""
        data = subentry.data
        created = data.get(CONF_CREATED_AT)
        return cls(
            id=subentry.subentry_id,
            name=data.get(CONF_NAME) or subentry.title,
            dosage=data.get(CONF_DOSAGE, ""),
            times=sorted({parse_time(t) for t in data.get(CONF_TIMES, [])}),
            weekdays=[int(d) for d in data.get(CONF_WEEKDAYS, ALL_WEEKDAYS)],
            early=timedelta(minutes=data.get(CONF_EARLY_MINUTES, DEFAULT_EARLY_MINUTES)),
            late=timedelta(minutes=data.get(CONF_LATE_MINUTES, DEFAULT_LATE_MINUTES)),
            created_at=dt_util.parse_datetime(created) if created else None,
        )

    def slots_on(self, day: date) -> list[datetime]:
        """Return the scheduled datetimes (UTC) for a local calendar day."""
        if day.weekday() not in self.weekdays:
            return []
        tz = dt_util.get_default_time_zone()
        return [dt_util.as_utc(datetime.combine(day, slot, tzinfo=tz)) for slot in self.times]

    def slots_between(self, start: datetime, end: datetime) -> list[datetime]:
        """Return all scheduled datetimes in [start, end)."""
        day = dt_util.as_local(start).date()
        last = dt_util.as_local(end).date()
        result: list[datetime] = []
        while day <= last:
            result.extend(s for s in self.slots_on(day) if start <= s < end)
            day += timedelta(days=1)
        return result

    def next_slot(self, after: datetime) -> datetime | None:
        """Return the first scheduled datetime strictly after `after`."""
        if not self.times or not self.weekdays:
            return None
        day = dt_util.as_local(after).date()
        for _ in range(9):
            for slot in self.slots_on(day):
                if slot > after:
                    return slot
            day += timedelta(days=1)
        return None


def dose_id_for(medication_id: str, scheduled: datetime) -> str:
    """Stable id of a dose: medication + scheduled UTC minute."""
    return f"{medication_id}_{dt_util.as_utc(scheduled).strftime('%Y%m%dT%H%M')}"


@dataclass(slots=True)
class DoseRecord:
    """One scheduled intake and what happened to it."""

    id: str
    medication_id: str
    medication_name: str
    scheduled: datetime
    status: DoseStatus = DoseStatus.SCHEDULED
    resolved_at: datetime | None = None
    reminders_sent: int = 0
    escalated: bool = False
    snoozed_until: datetime | None = None
    source: str | None = None
    user_id: str | None = None

    @property
    def is_open(self) -> bool:
        """Return True while the dose waits for acknowledgement."""
        return self.status in OPEN_STATES

    @property
    def is_resolved(self) -> bool:
        """Return True once the dose has a final status."""
        return self.status in RESOLVED_STATES

    def as_dict(self) -> dict[str, Any]:
        """Serialize for storage and service responses."""
        return {
            "id": self.id,
            "medication_id": self.medication_id,
            "medication_name": self.medication_name,
            "scheduled": self.scheduled.isoformat(),
            "status": self.status.value,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "reminders_sent": self.reminders_sent,
            "escalated": self.escalated,
            "snoozed_until": (self.snoozed_until.isoformat() if self.snoozed_until else None),
            "source": self.source,
            "user_id": self.user_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DoseRecord:
        """Deserialize from storage."""

        def _dt(key: str) -> datetime | None:
            value = data.get(key)
            return dt_util.parse_datetime(value) if value else None

        scheduled = _dt("scheduled")
        if scheduled is None:
            raise ValueError("Dose record without scheduled time")
        return cls(
            id=data["id"],
            medication_id=data["medication_id"],
            medication_name=data.get("medication_name", ""),
            scheduled=scheduled,
            status=DoseStatus(data.get("status", DoseStatus.SCHEDULED)),
            resolved_at=_dt("resolved_at"),
            reminders_sent=int(data.get("reminders_sent", 0)),
            escalated=bool(data.get("escalated", False)),
            snoozed_until=_dt("snoozed_until"),
            source=data.get("source"),
            user_id=data.get("user_id"),
        )
