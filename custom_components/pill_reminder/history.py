"""Persistent dose history and statistics for the Pill Reminder integration."""

from __future__ import annotations

import csv
from datetime import date, datetime, timedelta
import io
import logging
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN, EXPORT_DIR, STORAGE_VERSION
from .models import DoseRecord, DoseStatus

_LOGGER = logging.getLogger(__name__)

SAVE_DELAY = 5

CSV_FIELDS = [
    "id",
    "medication_id",
    "medication_name",
    "scheduled",
    "status",
    "resolved_at",
    "delay_minutes",
    "reminders_sent",
    "escalated",
    "source",
    "user_id",
]


class DoseHistory:
    """Store all doses of one person and compute statistics from them."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the history."""
        self.hass = hass
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}", private=True
        )
        self._doses: dict[str, DoseRecord] = {}
        self.paused_medications: set[str] = set()

    async def async_load(self) -> None:
        """Load history from disk."""
        data = await self._store.async_load() or {}
        for raw in data.get("doses", []):
            try:
                record = DoseRecord.from_dict(raw)
            except (KeyError, ValueError) as err:
                _LOGGER.warning("Skipping invalid dose record %s: %s", raw, err)
                continue
            self._doses[record.id] = record
        self.paused_medications = set(data.get("paused", []))

    def _data_to_save(self) -> dict[str, Any]:
        return {
            "doses": [record.as_dict() for record in self._doses.values()],
            "paused": sorted(self.paused_medications),
        }

    def async_schedule_save(self) -> None:
        """Save soon (debounced)."""
        self._store.async_delay_save(self._data_to_save, SAVE_DELAY)

    async def async_save_now(self) -> None:
        """Save immediately (on unload)."""
        await self._store.async_save(self._data_to_save())

    async def async_remove(self) -> None:
        """Delete the stored file (entry removed)."""
        await self._store.async_remove()

    # ------------------------------------------------------------------ access

    def get(self, dose_id: str) -> DoseRecord | None:
        """Return a dose by id."""
        return self._doses.get(dose_id)

    def upsert(self, record: DoseRecord) -> None:
        """Insert or update a dose and schedule a save."""
        self._doses[record.id] = record
        self.async_schedule_save()

    def remove_medication(self, medication_id: str) -> None:
        """Forget a deleted medication's pause flag (history is kept)."""
        self.paused_medications.discard(medication_id)
        self.async_schedule_save()

    def open_doses(self, medication_id: str | None = None) -> list[DoseRecord]:
        """Return all doses waiting for acknowledgement, oldest first."""
        return sorted(
            (
                r
                for r in self._doses.values()
                if r.is_open and (medication_id is None or r.medication_id == medication_id)
            ),
            key=lambda r: r.scheduled,
        )

    def records(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        medication_id: str | None = None,
        statuses: set[DoseStatus] | None = None,
    ) -> list[DoseRecord]:
        """Return doses filtered by scheduled time, medication and status."""
        result = [
            r
            for r in self._doses.values()
            if (start is None or r.scheduled >= start)
            and (end is None or r.scheduled < end)
            and (medication_id is None or r.medication_id == medication_id)
            and (statuses is None or r.status in statuses)
        ]
        result.sort(key=lambda r: r.scheduled)
        return result

    def last_taken(self, medication_id: str | None = None) -> DoseRecord | None:
        """Return the most recently taken dose."""
        taken = self.records(medication_id=medication_id, statuses={DoseStatus.TAKEN})
        return max(taken, key=lambda r: r.resolved_at or r.scheduled, default=None)

    def purge(self, retention_days: int, now: datetime) -> int:
        """Delete resolved doses older than the retention period."""
        cutoff = now - timedelta(days=retention_days)
        old = [
            dose_id for dose_id, r in self._doses.items() if r.is_resolved and r.scheduled < cutoff
        ]
        for dose_id in old:
            del self._doses[dose_id]
        if old:
            self.async_schedule_save()
        return len(old)

    # -------------------------------------------------------------- statistics

    def adherence(self, now: datetime, days: int, medication_id: str | None = None) -> float | None:
        """Share of taken doses among taken + missed in the last `days` days.

        Skipped and paused doses are excluded on purpose: they were a decision,
        not a forgotten intake. Returns None when there is nothing to rate yet.
        """
        start = now - timedelta(days=days)
        taken = missed = 0
        for r in self.records(start=start, end=now, medication_id=medication_id):
            if r.status == DoseStatus.TAKEN:
                taken += 1
            elif r.status == DoseStatus.MISSED:
                missed += 1
        if taken + missed == 0:
            return None
        return round(taken / (taken + missed) * 100, 1)

    def streak(self, now: datetime, medication_id: str | None = None) -> int:
        """Number of consecutive days (up to today) without a missed dose.

        A day counts when at least one dose was taken and none was missed.
        Days without resolved doses (e.g. no schedule) do not break the streak.
        """
        by_day: dict[date, set[DoseStatus]] = {}
        for r in self.records(end=now, medication_id=medication_id):
            if r.is_resolved:
                by_day.setdefault(dt_util.as_local(r.scheduled).date(), set()).add(r.status)
        if not by_day:
            return 0
        first = min(by_day)
        day = dt_util.as_local(now).date()
        count = 0
        while day >= first:
            statuses = by_day.get(day)
            if statuses:
                if DoseStatus.MISSED in statuses:
                    break
                if DoseStatus.TAKEN in statuses:
                    count += 1
            day -= timedelta(days=1)
        return count

    # ------------------------------------------------------------------ export

    def to_csv(self, records: list[DoseRecord]) -> str:
        """Render records as CSV (semicolon separated, Excel friendly)."""
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS, delimiter=";")
        writer.writeheader()
        for r in records:
            delay = (
                round((r.resolved_at - r.scheduled).total_seconds() / 60)
                if r.resolved_at and r.status == DoseStatus.TAKEN
                else ""
            )
            writer.writerow(
                {
                    "id": r.id,
                    "medication_id": r.medication_id,
                    "medication_name": r.medication_name,
                    "scheduled": dt_util.as_local(r.scheduled).isoformat(),
                    "status": r.status.value,
                    "resolved_at": (
                        dt_util.as_local(r.resolved_at).isoformat() if r.resolved_at else ""
                    ),
                    "delay_minutes": delay,
                    "reminders_sent": r.reminders_sent,
                    "escalated": r.escalated,
                    "source": r.source or "",
                    "user_id": r.user_id or "",
                }
            )
        return buffer.getvalue()

    async def async_export_csv(self, filename: str, records: list[DoseRecord]) -> str:
        """Write records as CSV into <config>/pill_reminder/ and return the path."""
        content = self.to_csv(records)
        path = Path(self.hass.config.path(EXPORT_DIR, filename))

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8-sig")

        await self.hass.async_add_executor_job(_write)
        return str(path)
