"""On-demand medications (e.g. for migraine): log intakes and count them per month."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_INTAKE_ID,
    ATTR_MEDICATION,
    ATTR_MEDICATION_ID,
    ATTR_PERSON,
    ATTR_SOURCE,
    ATTR_TAKEN_AT,
    CONF_DOSAGE,
    CONF_NAME,
    CONF_USER_ID,
    DOMAIN,
    EVENT_INTAKE_LIMIT,
    EVENT_INTAKE_TAKEN,
    SUBENTRY_ON_DEMAND,
)
from .intakes import Intake, IntakeStore, day_window, intake_days, month_window
from .models import OnDemandMedication
from .validation import validate_on_demand

if TYPE_CHECKING:
    from .scheduler import ReminderManager

# An intake may be logged a few minutes ahead (clock differences), not more.
FUTURE_TOLERANCE = timedelta(minutes=5)


class OnDemandTracker:
    """Intakes, monthly counts and limits of the on-demand medications of one person."""

    def __init__(self, manager: ReminderManager) -> None:
        """Initialize from the person's subentries."""
        self.manager = manager
        self.hass = manager.hass
        self.entry = manager.entry
        self.medications: dict[str, OnDemandMedication] = {
            sub.subentry_id: OnDemandMedication.from_subentry(sub)
            for sub in self.entry.subentries.values()
            if sub.subentry_type == SUBENTRY_ON_DEMAND
        }
        self.store = IntakeStore(self.hass, self.entry.entry_id)
        # Input fields "new on-demand medication" in the dashboard (not persisted)
        self.draft: dict[str, str] = {CONF_NAME: "", CONF_DOSAGE: ""}

    # --------------------------------------------------------------- lifecycle

    async def async_start(self) -> None:
        """Load the intakes."""
        await self.store.async_load()
        self.purge(dt_util.utcnow())

    async def async_stop(self) -> None:
        """Persist."""
        await self.store.async_save_now()

    def purge(self, now: datetime) -> None:
        """Drop intakes older than the person's history retention."""
        self.store.purge(self.manager.retention_days, now)

    # ----------------------------------------------------------------- intakes

    def _get(self, med_id: str) -> OnDemandMedication:
        med = self.medications.get(med_id)
        if med is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="unknown_medication"
            )
        return med

    async def async_take(
        self,
        med_id: str,
        *,
        source: str,
        user_id: str | None = None,
        taken_at: datetime | None = None,
    ) -> Intake:
        """Log an intake now or at `taken_at` (to add one later)."""
        med = self._get(med_id)
        now = dt_util.utcnow()
        if taken_at is not None and taken_at.tzinfo is None:
            taken_at = taken_at.replace(tzinfo=dt_util.get_default_time_zone())
        when = dt_util.as_utc(taken_at) if taken_at else now
        if when > now + FUTURE_TOLERANCE:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="taken_in_future"
            )
        intake = self.store.add(med.id, med.name, when, source, user_id)
        self._fire(EVENT_INTAKE_TAKEN, med, intake, now)
        self.manager.async_notify_entities()
        await self._async_check_limits(med, now)
        return intake

    def delete_intake(self, med_id: str, intake_id: str | None = None) -> Intake:
        """Delete an intake by id, or the most recent one of the medication."""
        self._get(med_id)
        target = (
            next((i for i in self.store.intakes(med_id) if i.id == intake_id), None)
            if intake_id
            else self.store.last(med_id)
        )
        if target is None:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_intake")
        self.store.remove({target.id})
        self.manager.async_notify_entities()
        return target

    def _fire(
        self, event_type: str, med: OnDemandMedication, intake: Intake | None, now: datetime
    ) -> None:
        # Link the event to the monthly count sensor (logbook filtering).
        sensor = er.async_get(self.hass).async_get_entity_id(
            "sensor", DOMAIN, f"{med.id}_intakes_month"
        )
        data: dict[str, Any] = {
            ATTR_ENTITY_ID: sensor,
            "entry_id": self.entry.entry_id,
            ATTR_PERSON: self.manager.person,
            CONF_USER_ID: self.manager.user_id,
            ATTR_MEDICATION: med.name,
            ATTR_MEDICATION_ID: med.id,
            "today": self.count_today(med.id, now),
            "month": self.count_month(med.id, now),
            "days_month": self.days_month(med.id, now),
            "max_days_per_month": med.max_days_per_month,
            "max_per_day": med.max_per_day,
        }
        if intake is not None:
            data |= {
                ATTR_INTAKE_ID: intake.id,
                ATTR_TAKEN_AT: intake.taken_at.isoformat(),
                ATTR_SOURCE: intake.source,
            }
        self.hass.bus.async_fire(event_type, data)

    async def _async_check_limits(self, med: OnDemandMedication, now: datetime) -> None:
        """Warn once per month (days limit) and once per day (daily limit)."""
        local = dt_util.as_local(now)
        checks = (
            (True, med.max_days_per_month, self.days_month(med.id, now), local.strftime("%Y-%m")),
            (False, med.max_per_day, self.count_today(med.id, now), local.date().isoformat()),
        )
        for monthly, limit, count, period in checks:
            key = f"{med.id}:{'month' if monthly else 'day'}"
            if not limit or count < limit or self.store.warned.get(key) == period:
                continue
            self.store.warned[key] = period
            self.store.async_schedule_save()
            self._fire(EVENT_INTAKE_LIMIT, med, None, now)
            await self.manager.notifier.async_send_limit_warning(
                self.manager.notify_services,
                med,
                monthly=monthly,
                count=count,
                limit=limit,
                persistent=self.manager.persistent,
            )

    # ----------------------------------------------------------------- queries

    def count(self, med_id: str, window: tuple[datetime, datetime]) -> int:
        """Number of intakes in [start, end)."""
        return len(self.store.intakes(med_id, start=window[0], end=window[1]))

    def days(self, med_id: str, window: tuple[datetime, datetime]) -> int:
        """Number of local days with an intake in [start, end)."""
        return intake_days(self.store.intakes(med_id, start=window[0], end=window[1]))

    def count_today(self, med_id: str, now: datetime) -> int:
        """Intakes on the current local day."""
        return self.count(med_id, day_window(now))

    def count_month(self, med_id: str, now: datetime) -> int:
        """Intakes in the current calendar month."""
        return self.count(med_id, month_window(now))

    def days_month(self, med_id: str, now: datetime) -> int:
        """Days with an intake in the current calendar month."""
        return self.days(med_id, month_window(now))

    def count_previous_month(self, med_id: str, now: datetime) -> int:
        """Intakes in the previous calendar month."""
        return self.count(med_id, month_window(now, -1))

    def days_previous_month(self, med_id: str, now: datetime) -> int:
        """Days with an intake in the previous calendar month."""
        return self.days(med_id, month_window(now, -1))

    def count_30d(self, med_id: str, now: datetime) -> int:
        """Intakes in the last 30 days (rolling)."""
        return self.count(med_id, (now - timedelta(days=30), now + FUTURE_TOLERANCE))

    def last_intake(self, med_id: str) -> datetime | None:
        """Time of the most recent intake."""
        last = self.store.last(med_id)
        return last.taken_at if last else None

    def monthly_limit_reached(self, med_id: str, now: datetime) -> bool:
        """Days with an intake this month reached the configured limit."""
        limit = self.medications[med_id].max_days_per_month
        return bool(limit) and self.days_month(med_id, now) >= limit

    def daily_limit_reached(self, med_id: str, now: datetime) -> bool:
        """Intakes today reached the configured limit."""
        limit = self.medications[med_id].max_per_day
        return bool(limit) and self.count_today(med_id, now) >= limit

    # ------------------------------------------- medication setup (dashboard)

    def _raise_invalid(self, errors: dict[str, str]) -> None:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key=next(iter(errors.values()))
        )

    @callback
    def async_add_medication(self) -> str:
        """Create an on-demand medication from the dashboard input fields."""
        data, errors = validate_on_demand(
            {CONF_NAME: self.draft[CONF_NAME], CONF_DOSAGE: self.draft[CONF_DOSAGE]}
        )
        if errors:
            self._raise_invalid(errors)
        subentry = ConfigSubentry(
            data=MappingProxyType(data),
            subentry_type=SUBENTRY_ON_DEMAND,
            title=data[CONF_NAME],
            unique_id=None,
        )
        self.draft = {CONF_NAME: "", CONF_DOSAGE: ""}
        self.hass.config_entries.async_add_subentry(self.entry, subentry)
        return subentry.subentry_id

    @callback
    def async_update_medication(self, med_id: str, changes: dict[str, Any]) -> None:
        """Change name, dosage or limits; the person reloads."""
        self._get(med_id)
        subentry = self.entry.subentries[med_id]
        data, errors = validate_on_demand({**subentry.data, **changes})
        if errors:
            self._raise_invalid(errors)
        self.hass.config_entries.async_update_subentry(
            self.entry, subentry, title=data[CONF_NAME], data=data
        )

    @callback
    def async_delete_medication(self, med_id: str) -> None:
        """Delete an on-demand medication; its intakes are kept."""
        self._get(med_id)
        self.hass.config_entries.async_remove_subentry(self.entry, med_id)
