"""Persistent body measurements of one person (weight, waist, ...)."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
import io
import logging
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util, ulid as ulid_util

from .const import DOMAIN, EXPORT_DIR, STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)

SAVE_DELAY = 2

CSV_FIELDS = ["id", "metric", "value", "measured_at", "source"]


def storage_key(entry_id: str) -> str:
    """Storage file of a person's measurements (doses are stored separately)."""
    return f"{DOMAIN}.{entry_id}.measurements"


@dataclass(frozen=True, slots=True)
class Measurement:
    """One measured value."""

    id: str
    metric: str
    value: float
    measured_at: datetime  # UTC
    source: str

    def as_dict(self) -> dict[str, Any]:
        """Serialize."""
        return {
            "id": self.id,
            "metric": self.metric,
            "value": self.value,
            "measured_at": self.measured_at.isoformat(),
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Measurement:
        """Deserialize."""
        measured_at = dt_util.parse_datetime(raw["measured_at"])
        if measured_at is None:
            raise ValueError("invalid measured_at")
        return cls(
            id=str(raw["id"]),
            metric=str(raw["metric"]),
            value=float(raw["value"]),
            measured_at=dt_util.as_utc(measured_at),
            source=str(raw.get("source") or ""),
        )


@dataclass(slots=True)
class ReminderState:
    """Reminders sent for the current slot of one measurement type."""

    slot: datetime
    count: int
    sent: datetime

    def as_dict(self) -> dict[str, Any]:
        """Serialize."""
        return {"slot": self.slot.isoformat(), "count": self.count, "sent": self.sent.isoformat()}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ReminderState:
        """Deserialize."""
        slot = dt_util.parse_datetime(raw["slot"])
        sent = dt_util.parse_datetime(raw["sent"])
        if slot is None or sent is None:
            raise ValueError("invalid reminder state")
        return cls(slot=slot, count=int(raw["count"]), sent=sent)


class MeasurementStore:
    """All measurements of one person, sorted by time."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize."""
        self.hass = hass
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, storage_key(entry_id), private=True
        )
        self._measurements: list[Measurement] = []
        self.reminders: dict[str, ReminderState] = {}

    async def async_load(self) -> None:
        """Load from disk."""
        data = await self._store.async_load() or {}
        for raw in data.get("measurements", []):
            try:
                self._measurements.append(Measurement.from_dict(raw))
            except (KeyError, TypeError, ValueError) as err:
                # No value in the log: it is health data.
                _LOGGER.warning("Skipping invalid measurement %s: %s", raw.get("id"), err)
        self._measurements.sort(key=lambda m: m.measured_at)
        for metric, raw in data.get("reminders", {}).items():
            try:
                self.reminders[metric] = ReminderState.from_dict(raw)
            except (KeyError, TypeError, ValueError):
                continue

    def _data_to_save(self) -> dict[str, Any]:
        return {
            "measurements": [m.as_dict() for m in self._measurements],
            "reminders": {k: v.as_dict() for k, v in self.reminders.items()},
        }

    def async_schedule_save(self) -> None:
        """Save soon (debounced)."""
        self._store.async_delay_save(self._data_to_save, SAVE_DELAY)

    async def async_save_now(self) -> None:
        """Save immediately (on unload)."""
        await self._store.async_save(self._data_to_save())

    async def async_remove(self) -> None:
        """Delete the stored file (person removed)."""
        await self._store.async_remove()

    # ------------------------------------------------------------------ access

    def add(self, metric: str, value: float, measured_at: datetime, source: str) -> Measurement:
        """Store a new measurement."""
        measurement = Measurement(
            id=ulid_util.ulid_now(),
            metric=metric,
            value=value,
            measured_at=dt_util.as_utc(measured_at),
            source=source,
        )
        self._measurements.append(measurement)
        self._measurements.sort(key=lambda m: m.measured_at)
        self.async_schedule_save()
        return measurement

    def remove(self, ids: set[str]) -> list[Measurement]:
        """Delete measurements by id and return them."""
        removed = [m for m in self._measurements if m.id in ids]
        if removed:
            self._measurements = [m for m in self._measurements if m.id not in ids]
            self.async_schedule_save()
        return removed

    def measurements(
        self,
        metric: str | None = None,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Measurement]:
        """Measurements filtered by type and time (start inclusive, end exclusive)."""
        return [
            m
            for m in self._measurements
            if (metric is None or m.metric == metric)
            and (start is None or m.measured_at >= start)
            and (end is None or m.measured_at < end)
        ]

    def latest(self, metric: str) -> Measurement | None:
        """Most recent measurement of a type."""
        return next((m for m in reversed(self._measurements) if m.metric == metric), None)

    def on_day(self, metric: str, day: date) -> list[Measurement]:
        """Measurements of a type on a local calendar day."""
        return [
            m for m in self.measurements(metric) if dt_util.as_local(m.measured_at).date() == day
        ]

    def daily(self, metric: str) -> list[tuple[datetime, float]]:
        """One point per local day: the last measurement of that day."""
        by_day: dict[date, Measurement] = {}
        for m in self.measurements(metric):
            by_day[dt_util.as_local(m.measured_at).date()] = m
        return [(m.measured_at, m.value) for _, m in sorted(by_day.items())]

    # ------------------------------------------------------------------ export

    @staticmethod
    def to_csv(measurements: list[Measurement]) -> str:
        """Render measurements as CSV (semicolon separated, Excel friendly)."""
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS, delimiter=";")
        writer.writeheader()
        for m in measurements:
            writer.writerow(
                {
                    "id": m.id,
                    "metric": m.metric,
                    "value": m.value,
                    "measured_at": dt_util.as_local(m.measured_at).isoformat(),
                    "source": m.source,
                }
            )
        return buffer.getvalue()

    async def async_export_csv(self, filename: str, measurements: list[Measurement]) -> str:
        """Write measurements as CSV into <config>/pill_reminder/ and return the path."""
        content = self.to_csv(measurements)
        path = Path(self.hass.config.path(EXPORT_DIR, filename))

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8-sig")

        await self.hass.async_add_executor_job(_write)
        return str(path)
