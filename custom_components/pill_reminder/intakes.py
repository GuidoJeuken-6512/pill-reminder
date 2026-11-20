"""Persistent intakes of on-demand medications (e.g. migraine medication)."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta
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

CSV_FIELDS = ["id", "medication_id", "medication_name", "taken_at", "source", "user_id"]


def storage_key(entry_id: str) -> str:
    """Storage file of a person's on-demand intakes (doses are stored separately)."""
    return f"{DOMAIN}.{entry_id}.intakes"


@dataclass(frozen=True, slots=True)
class Intake:
    """One intake of an on-demand medication."""

    id: str
    medication_id: str
    medication_name: str
    taken_at: datetime  # UTC
    source: str
    user_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Serialize for storage and service responses."""
        return {
            "id": self.id,
            "medication_id": self.medication_id,
            "medication_name": self.medication_name,
            "taken_at": self.taken_at.isoformat(),
            "source": self.source,
            "user_id": self.user_id,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Intake:
        """Deserialize."""
        taken_at = dt_util.parse_datetime(raw["taken_at"])
        if taken_at is None:
            raise ValueError("invalid taken_at")
        return cls(
            id=str(raw["id"]),
            medication_id=str(raw["medication_id"]),
            medication_name=str(raw.get("medication_name") or ""),
            taken_at=dt_util.as_utc(taken_at),
            source=str(raw.get("source") or ""),
            user_id=raw.get("user_id"),
        )


def intake_days(intakes: list[Intake]) -> int:
    """Number of distinct local calendar days with at least one intake."""
    return len({dt_util.as_local(i.taken_at).date() for i in intakes})


def day_window(now: datetime) -> tuple[datetime, datetime]:
    """Start and end (UTC) of the local day of `now`."""
    start = dt_util.start_of_local_day(dt_util.as_local(now))
    return dt_util.as_utc(start), dt_util.as_utc(start + timedelta(days=1))


def _month_start(day: date) -> datetime:
    return dt_util.start_of_local_day(day.replace(day=1))


def month_window(now: datetime, offset: int = 0) -> tuple[datetime, datetime]:
    """Start and end (UTC) of the local calendar month of `now`, shifted by `offset` months."""
    local = dt_util.as_local(now).date()
    index = local.year * 12 + local.month - 1 + offset
    first = date(index // 12, index % 12 + 1, 1)
    following = date((index + 1) // 12, (index + 1) % 12 + 1, 1)
    return dt_util.as_utc(_month_start(first)), dt_util.as_utc(_month_start(following))


class IntakeStore:
    """All on-demand intakes of one person, sorted by time."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize."""
        self.hass = hass
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, storage_key(entry_id), private=True
        )
        self._intakes: list[Intake] = []
        # Limit warnings already sent: {"<medication id>:month": "2026-11", ...:day: "2026-11-20"}
        self.warned: dict[str, str] = {}

    async def async_load(self) -> None:
        """Load from disk."""
        data = await self._store.async_load() or {}
        for raw in data.get("intakes", []):
            try:
                self._intakes.append(Intake.from_dict(raw))
            except (KeyError, TypeError, ValueError) as err:
                # No medication name in the log: it is health data.
                _LOGGER.warning("Skipping invalid intake %s: %s", raw.get("id"), err)
        self._intakes.sort(key=lambda i: i.taken_at)
        self.warned = {str(k): str(v) for k, v in data.get("warned", {}).items()}

    def _data_to_save(self) -> dict[str, Any]:
        return {"intakes": [i.as_dict() for i in self._intakes], "warned": self.warned}

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

    def add(
        self,
        medication_id: str,
        medication_name: str,
        taken_at: datetime,
        source: str,
        user_id: str | None,
    ) -> Intake:
        """Store a new intake."""
        intake = Intake(
            id=ulid_util.ulid_now(),
            medication_id=medication_id,
            medication_name=medication_name,
            taken_at=dt_util.as_utc(taken_at),
            source=source,
            user_id=user_id,
        )
        self._intakes.append(intake)
        self._intakes.sort(key=lambda i: i.taken_at)
        self.async_schedule_save()
        return intake

    def remove(self, ids: set[str]) -> list[Intake]:
        """Delete intakes by id and return them."""
        removed = [i for i in self._intakes if i.id in ids]
        if removed:
            self._intakes = [i for i in self._intakes if i.id not in ids]
            self.async_schedule_save()
        return removed

    def intakes(
        self,
        medication_id: str | None = None,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Intake]:
        """Intakes filtered by medication and time (start inclusive, end exclusive)."""
        return [
            i
            for i in self._intakes
            if (medication_id is None or i.medication_id == medication_id)
            and (start is None or i.taken_at >= start)
            and (end is None or i.taken_at < end)
        ]

    def last(self, medication_id: str) -> Intake | None:
        """Most recent intake of a medication."""
        return next((i for i in reversed(self._intakes) if i.medication_id == medication_id), None)

    def purge(self, retention_days: int, now: datetime) -> None:
        """Drop intakes older than the retention period."""
        cutoff = now - timedelta(days=retention_days)
        kept = [i for i in self._intakes if i.taken_at >= cutoff]
        if len(kept) != len(self._intakes):
            self._intakes = kept
            self.async_schedule_save()

    # ------------------------------------------------------------------ export

    @staticmethod
    def to_csv(intakes: list[Intake]) -> str:
        """Render intakes as CSV (semicolon separated, Excel friendly)."""
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS, delimiter=";")
        writer.writeheader()
        for i in intakes:
            writer.writerow(
                {
                    **i.as_dict(),
                    "taken_at": dt_util.as_local(i.taken_at).isoformat(),
                    "user_id": i.user_id or "",
                }
            )
        return buffer.getvalue()

    async def async_export_csv(self, filename: str, intakes: list[Intake]) -> str:
        """Write intakes as CSV into <config>/pill_reminder/ and return the path."""
        content = self.to_csv(intakes)
        path = Path(self.hass.config.path(EXPORT_DIR, filename))

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8-sig")

        await self.hass.async_add_executor_job(_write)
        return str(path)
