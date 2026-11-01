"""Reminder scheduling for one person (config entry)."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .const import (
    ACTION_SNOOZE,
    ACTION_TAKEN,
    ATTR_DOSE_ID,
    ATTR_MEDICATION,
    ATTR_MEDICATION_ID,
    ATTR_PERSON,
    ATTR_REMINDERS_SENT,
    ATTR_SCHEDULED,
    ATTR_SOURCE,
    ATTR_STATUS,
    CONF_ESCALATE_AFTER,
    CONF_ESCALATION_ENABLED,
    CONF_ESCALATION_SERVICES,
    CONF_MAX_REMINDERS,
    CONF_NOTIFY_MISSED,
    CONF_NOTIFY_SERVICES,
    CONF_PERSISTENT_NOTIFICATION,
    CONF_PERSON_NAME,
    CONF_REPEAT_INTERVAL,
    CONF_RETENTION_DAYS,
    CONF_SNOOZE_MINUTES,
    CONF_TIME_SENSITIVE,
    CONF_USER_ID,
    DEFAULT_ESCALATE_AFTER,
    DEFAULT_ESCALATION_ENABLED,
    DEFAULT_MAX_REMINDERS,
    DEFAULT_NOTIFY_MISSED,
    DEFAULT_PERSISTENT_NOTIFICATION,
    DEFAULT_REPEAT_INTERVAL,
    DEFAULT_RETENTION_DAYS,
    DEFAULT_SNOOZE_MINUTES,
    DEFAULT_TIME_SENSITIVE,
    DOMAIN,
    EVENT_DOSE_DUE,
    EVENT_DOSE_MISSED,
    EVENT_DOSE_SKIPPED,
    EVENT_DOSE_SNOOZED,
    EVENT_DOSE_TAKEN,
    EVENT_ESCALATED,
    EVENT_REMINDER_SENT,
    MOBILE_APP_ACTION_EVENT,
    RESTORE_LOOKBACK_HOURS,
    SOURCE_AUTOMATIC,
    SOURCE_NOTIFICATION,
    SUBENTRY_MEDICATION,
    signal_update,
)
from .history import DoseHistory
from .models import DoseRecord, DoseStatus, Medication, dose_id_for
from .notifier import Notifier, parse_action

_LOGGER = logging.getLogger(__name__)

REFRESH_INTERVAL = timedelta(minutes=15)

RESOLVE_EVENTS = {
    DoseStatus.TAKEN: EVENT_DOSE_TAKEN,
    DoseStatus.MISSED: EVENT_DOSE_MISSED,
    DoseStatus.SKIPPED: EVENT_DOSE_SKIPPED,
}


class ReminderManager:
    """Schedules reminders and tracks doses for one person."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize from the config entry and its medication subentries."""
        self.hass = hass
        self.entry = entry
        self.entry_id = entry.entry_id
        self.person: str = entry.data[CONF_PERSON_NAME]
        self.user_id: str | None = entry.data.get(CONF_USER_ID) or None
        self.notify_services: list[str] = list(entry.data.get(CONF_NOTIFY_SERVICES, []))

        opts = entry.options
        self.repeat_interval = timedelta(
            minutes=opts.get(CONF_REPEAT_INTERVAL, DEFAULT_REPEAT_INTERVAL)
        )
        self.max_reminders: int = int(opts.get(CONF_MAX_REMINDERS, DEFAULT_MAX_REMINDERS))
        self.snooze_minutes: int = int(opts.get(CONF_SNOOZE_MINUTES, DEFAULT_SNOOZE_MINUTES))
        self.escalation_services: list[str] = list(opts.get(CONF_ESCALATION_SERVICES, []))
        self.escalation_enabled: bool = bool(
            opts.get(CONF_ESCALATION_ENABLED, DEFAULT_ESCALATION_ENABLED)
        ) and bool(self.escalation_services)
        self.escalate_after: int = int(opts.get(CONF_ESCALATE_AFTER, DEFAULT_ESCALATE_AFTER))
        self.notify_missed: bool = bool(opts.get(CONF_NOTIFY_MISSED, DEFAULT_NOTIFY_MISSED))
        self.time_sensitive: bool = bool(opts.get(CONF_TIME_SENSITIVE, DEFAULT_TIME_SENSITIVE))
        self.persistent: bool = bool(
            opts.get(CONF_PERSISTENT_NOTIFICATION, DEFAULT_PERSISTENT_NOTIFICATION)
        )
        self.retention_days: int = int(opts.get(CONF_RETENTION_DAYS, DEFAULT_RETENTION_DAYS))

        self.medications: dict[str, Medication] = {
            sub.subentry_id: Medication.from_subentry(sub)
            for sub in entry.subentries.values()
            if sub.subentry_type == SUBENTRY_MEDICATION
        }
        self.history = DoseHistory(hass, entry.entry_id)
        self.notifier = Notifier(hass, self.person)
        self.person_device_id: str | None = None

        self._slot_timers: dict[str, CALLBACK_TYPE] = {}
        self._dose_timers: dict[str, dict[str, CALLBACK_TYPE]] = {}
        self._unsubs: list[CALLBACK_TYPE] = []

    # --------------------------------------------------------------- lifecycle

    async def async_start(self) -> None:
        """Load history, catch up on missed time and start all timers."""
        await self.history.async_load()
        now = dt_util.utcnow()
        self.history.purge(self.retention_days, now)
        self.history.paused_medications &= set(self.medications)

        for record in self.history.open_doses():
            if record.medication_id not in self.medications:
                # Medication was deleted while a dose was open.
                await self._async_resolve(record, DoseStatus.PAUSED, source=SOURCE_AUTOMATIC)

        for med in self.medications.values():
            await self._async_restore(med, now)
            self._schedule_next_slot(med, now)

        self._unsubs.append(
            self.hass.bus.async_listen(MOBILE_APP_ACTION_EVENT, self._handle_mobile_action)
        )
        self._unsubs.append(
            async_track_time_change(self.hass, self._handle_midnight, hour=0, minute=0, second=5)
        )
        self._unsubs.append(
            async_track_time_interval(self.hass, self._handle_refresh, REFRESH_INTERVAL)
        )

    async def async_stop(self) -> None:
        """Cancel all timers and persist the history."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        for unsub in self._slot_timers.values():
            unsub()
        self._slot_timers.clear()
        for dose_id in list(self._dose_timers):
            self._cancel_dose_timers(dose_id)
        await self.history.async_save_now()

    async def _async_restore(self, med: Medication, now: datetime) -> None:
        """Resolve or resume doses that were due while HA was not running."""
        start = now - timedelta(hours=RESTORE_LOOKBACK_HOURS)
        if med.created_at:
            start = max(start, med.created_at)
        paused = self.is_paused(med.id)

        for scheduled in med.slots_between(start, now + timedelta(seconds=1)):
            record = self.history.get(dose_id_for(med.id, scheduled))
            if record and record.is_resolved:
                continue
            deadline = scheduled + med.late
            if record is None:
                record = self._new_record(med, scheduled)
            if paused:
                await self._async_resolve(record, DoseStatus.PAUSED, source=SOURCE_AUTOMATIC)
            elif deadline <= now:
                await self._async_resolve(
                    record, DoseStatus.MISSED, source=SOURCE_AUTOMATIC, at=deadline
                )
            elif record.is_open:
                self._arm_dose(record, med, now)
            else:
                await self._async_make_due(record, med)

        # Open doses older than the lookback window
        for record in self.history.open_doses(med.id):
            if record.id in self._dose_timers:
                continue
            deadline = record.scheduled + med.late
            if deadline <= now:
                await self._async_resolve(
                    record, DoseStatus.MISSED, source=SOURCE_AUTOMATIC, at=deadline
                )
            else:
                self._arm_dose(record, med, now)

    # ------------------------------------------------------------------ timers

    def _schedule_next_slot(self, med: Medication, after: datetime) -> None:
        if unsub := self._slot_timers.pop(med.id, None):
            unsub()
        if (scheduled := med.next_slot(after)) is None:
            return

        @callback
        def _fire(_now: datetime) -> None:
            self._slot_timers.pop(med.id, None)
            self.hass.async_create_task(
                self._async_slot_reached(med.id, scheduled),
                f"{DOMAIN} slot {med.name}",
            )

        self._slot_timers[med.id] = async_track_point_in_time(self.hass, _fire, scheduled)

    def _set_dose_timer(
        self,
        dose_id: str,
        kind: str,
        when: datetime,
        action: Callable[[], Coroutine[Any, Any, None]],
    ) -> None:
        timers = self._dose_timers.setdefault(dose_id, {})
        if unsub := timers.pop(kind, None):
            unsub()

        @callback
        def _fire(_now: datetime) -> None:
            self._dose_timers.get(dose_id, {}).pop(kind, None)
            self.hass.async_create_task(action(), f"{DOMAIN} {kind} {dose_id}")

        timers[kind] = async_track_point_in_time(self.hass, _fire, when)

    def _cancel_dose_timers(self, dose_id: str, *kinds: str) -> None:
        timers = self._dose_timers.get(dose_id)
        if not timers:
            return
        for kind in kinds or list(timers):
            if unsub := timers.pop(kind, None):
                unsub()
        if not timers:
            self._dose_timers.pop(dose_id, None)

    def _arm_dose(self, record: DoseRecord, med: Medication, now: datetime) -> None:
        """(Re-)create the timers of an open dose."""
        self._set_dose_timer(
            record.id,
            "deadline",
            record.scheduled + med.late,
            lambda: self._async_deadline(record.id),
        )
        if (
            record.status == DoseStatus.SNOOZED
            and record.snoozed_until
            and record.snoozed_until > now
        ):
            self._set_dose_timer(
                record.id,
                "snooze",
                record.snoozed_until,
                lambda: self._async_snooze_end(record.id),
            )
        else:
            self._schedule_tick(record, now)

    def _schedule_tick(self, record: DoseRecord, now: datetime) -> None:
        reminders_left = record.reminders_sent < self.max_reminders
        escalation_pending = self.escalation_enabled and not record.escalated
        if reminders_left or escalation_pending:
            self._set_dose_timer(
                record.id,
                "tick",
                now + self.repeat_interval,
                lambda: self._async_tick(record.id),
            )

    # ------------------------------------------------------------- transitions

    def _new_record(self, med: Medication, scheduled: datetime) -> DoseRecord:
        return DoseRecord(
            id=dose_id_for(med.id, scheduled),
            medication_id=med.id,
            medication_name=med.name,
            scheduled=scheduled,
        )

    async def _async_slot_reached(self, med_id: str, scheduled: datetime) -> None:
        med = self.medications.get(med_id)
        if med is None:
            return
        self._schedule_next_slot(med, scheduled)
        record = self.history.get(dose_id_for(med_id, scheduled))
        if record and (record.is_resolved or record.is_open):
            # Already taken early / skipped, or restored.
            self.async_notify_entities()
            return
        record = record or self._new_record(med, scheduled)
        if self.is_paused(med_id):
            await self._async_resolve(record, DoseStatus.PAUSED, source=SOURCE_AUTOMATIC)
            return
        await self._async_make_due(record, med)

    async def _async_make_due(self, record: DoseRecord, med: Medication) -> None:
        record.status = DoseStatus.DUE
        self.history.upsert(record)
        self._fire(EVENT_DOSE_DUE, record)
        self._set_dose_timer(
            record.id,
            "deadline",
            record.scheduled + med.late,
            lambda: self._async_deadline(record.id),
        )
        await self._async_remind(record, med)

    async def _async_remind(self, record: DoseRecord, med: Medication) -> None:
        record.status = DoseStatus.DUE
        record.snoozed_until = None
        record.reminders_sent += 1
        self.history.upsert(record)
        self._schedule_tick(record, dt_util.utcnow())
        self.async_notify_entities()
        await self.notifier.async_send_reminder(
            self.notify_services,
            record,
            med,
            snooze_minutes=self.snooze_minutes,
            time_sensitive=self.time_sensitive,
            persistent=self.persistent,
        )
        self._fire(EVENT_REMINDER_SENT, record)

    async def _async_tick(self, dose_id: str) -> None:
        record = self.history.get(dose_id)
        if record is None or record.status != DoseStatus.DUE:
            return
        med = self.medications.get(record.medication_id)
        if med is None:
            return
        threshold = min(self.escalate_after, self.max_reminders)
        if self.escalation_enabled and not record.escalated and record.reminders_sent >= threshold:
            record.escalated = True
            self.history.upsert(record)
            await self.notifier.async_send_escalation(self.escalation_services, record, med)
            self._fire(EVENT_ESCALATED, record)

        if record.reminders_sent < self.max_reminders:
            await self._async_remind(record, med)
        else:
            self._schedule_tick(record, dt_util.utcnow())
            self.async_notify_entities()

    async def _async_snooze_end(self, dose_id: str) -> None:
        record = self.history.get(dose_id)
        if record is None or record.status != DoseStatus.SNOOZED:
            return
        if med := self.medications.get(record.medication_id):
            await self._async_remind(record, med)

    async def _async_deadline(self, dose_id: str) -> None:
        record = self.history.get(dose_id)
        if record is None or not record.is_open:
            return
        med = self.medications.get(record.medication_id)
        await self._async_resolve(record, DoseStatus.MISSED, source=SOURCE_AUTOMATIC)
        if med and self.notify_missed:
            targets = list(self.notify_services)
            if self.escalation_enabled:
                targets += [s for s in self.escalation_services if s not in targets]
            await self.notifier.async_send_missed(targets, record, med)

    async def _async_resolve(
        self,
        record: DoseRecord,
        status: DoseStatus,
        *,
        source: str,
        user_id: str | None = None,
        at: datetime | None = None,
    ) -> None:
        """Give a dose its final status."""
        had_reminder = record.reminders_sent > 0
        self._cancel_dose_timers(record.id)
        record.status = status
        record.resolved_at = at or dt_util.utcnow()
        record.snoozed_until = None
        record.source = source
        record.user_id = user_id
        self.history.upsert(record)
        self.async_notify_entities()
        if event := RESOLVE_EVENTS.get(status):
            self._fire(event, record)
        if had_reminder:
            await self.notifier.async_clear(self.notify_services, record, self.escalation_services)

    # -------------------------------------------------------------- public API

    def is_paused(self, med_id: str) -> bool:
        """Return True if reminders for a medication are paused."""
        return med_id in self.history.paused_medications

    def find_actionable_dose(self, med_id: str, now: datetime) -> DoseRecord | None:
        """The dose a 'taken'/'skip' press refers to.

        Priority: oldest open dose, otherwise a dose whose window (early..late)
        contains `now` and that has no final status yet.
        """
        med = self.medications[med_id]
        if open_doses := self.history.open_doses(med_id):
            return open_doses[0]
        for scheduled in med.slots_between(now - med.late, now + med.early + timedelta(seconds=1)):
            record = self.history.get(dose_id_for(med_id, scheduled))
            if record is None:
                return self._new_record(med, scheduled)
            if not record.is_resolved:
                return record
        return None

    def _dose_near(self, med: Medication, when: datetime) -> DoseRecord | None:
        """Dose whose window contains `when`, also if already marked missed."""
        candidates = med.slots_between(when - med.late, when + med.early + timedelta(seconds=1))
        for scheduled in sorted(candidates, key=lambda s: abs(s - when)):
            record = self.history.get(dose_id_for(med.id, scheduled))
            if record is None:
                return self._new_record(med, scheduled)
            if record.status in (DoseStatus.MISSED, DoseStatus.DUE, DoseStatus.SNOOZED):
                return record
        return None

    def _get_med(self, med_id: str) -> Medication:
        if (med := self.medications.get(med_id)) is None:
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
    ) -> DoseRecord:
        """Acknowledge the current dose (or a past one when `taken_at` is set)."""
        med = self._get_med(med_id)
        now = dt_util.utcnow()
        if taken_at is not None:
            taken_at = dt_util.as_utc(taken_at)
            if taken_at > now:
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="taken_in_future"
                )
            record = self._dose_near(med, taken_at)
        else:
            record = self.find_actionable_dose(med_id, now)
        if record is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="no_dose_due",
                translation_placeholders={"medication": med.name},
            )
        await self._async_resolve(
            record, DoseStatus.TAKEN, source=source, user_id=user_id, at=taken_at
        )
        return record

    async def async_skip(
        self, med_id: str, *, source: str, user_id: str | None = None
    ) -> DoseRecord:
        """Deliberately skip the current dose."""
        med = self._get_med(med_id)
        record = self.find_actionable_dose(med_id, dt_util.utcnow())
        if record is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="no_dose_due",
                translation_placeholders={"medication": med.name},
            )
        await self._async_resolve(record, DoseStatus.SKIPPED, source=source, user_id=user_id)
        return record

    async def async_snooze(
        self,
        med_id: str,
        *,
        minutes: int | None = None,
        source: str,
        user_id: str | None = None,
        dose_id: str | None = None,
    ) -> DoseRecord:
        """Postpone the reminder of an open dose."""
        med = self._get_med(med_id)
        if dose_id:
            record = self.history.get(dose_id)
            open_doses = [record] if record and record.is_open else []
        else:
            open_doses = self.history.open_doses(med_id)
        if not open_doses:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="nothing_to_snooze",
                translation_placeholders={"medication": med.name},
            )
        record = open_doses[0]
        now = dt_util.utcnow()
        self._cancel_dose_timers(record.id, "tick", "snooze")
        record.status = DoseStatus.SNOOZED
        record.snoozed_until = now + timedelta(minutes=minutes or self.snooze_minutes)
        record.source = source
        record.user_id = user_id
        self.history.upsert(record)
        self._set_dose_timer(
            record.id, "snooze", record.snoozed_until, lambda: self._async_snooze_end(record.id)
        )
        self.async_notify_entities()
        self._fire(EVENT_DOSE_SNOOZED, record)
        await self.notifier.async_clear(self.notify_services, record, [])
        return record

    async def async_set_paused(self, med_id: str, paused: bool) -> None:
        """Pause or resume reminders for one medication."""
        self._get_med(med_id)
        if paused:
            self.history.paused_medications.add(med_id)
            for record in self.history.open_doses(med_id):
                await self._async_resolve(record, DoseStatus.PAUSED, source=SOURCE_AUTOMATIC)
        else:
            self.history.paused_medications.discard(med_id)
        self.history.async_schedule_save()
        self.async_notify_entities()

    # ----------------------------------------------------------------- queries

    def medication_status(self, med_id: str, now: datetime) -> DoseStatus:
        """Current status of a medication for display."""
        if self.is_paused(med_id):
            return DoseStatus.PAUSED
        if open_doses := self.history.open_doses(med_id):
            return open_doses[0].status
        # Most recently handled dose of today (may be scheduled later today
        # when it was taken early or skipped).
        today = dt_util.as_utc(dt_util.start_of_local_day(dt_util.as_local(now)))
        handled = [
            r
            for r in self.history.records(
                start=today, end=today + timedelta(days=1), medication_id=med_id
            )
            if r.is_resolved and r.resolved_at
        ]
        latest = max(handled, key=lambda r: r.resolved_at or r.scheduled, default=None)
        return latest.status if latest else DoseStatus.SCHEDULED

    def next_dose(self, med_id: str, now: datetime) -> datetime | None:
        """Next scheduled dose that has not been handled yet."""
        med = self.medications[med_id]
        after = now
        for _ in range(30):
            scheduled = med.next_slot(after)
            if scheduled is None:
                return None
            record = self.history.get(dose_id_for(med_id, scheduled))
            if record is None or not record.is_resolved:
                return scheduled
            after = scheduled
        return None

    def count_today(self, now: datetime, status: DoseStatus) -> int:
        """Number of today's doses (local day) with the given final status."""
        start = dt_util.as_utc(dt_util.start_of_local_day(dt_util.as_local(now)))
        return sum(
            1
            for r in self.history.records(
                start=start, end=start + timedelta(days=1), statuses={status}
            )
            if r.medication_id in self.medications
        )

    def open_today(self, now: datetime) -> int:
        """Number of today's doses that are still open or upcoming."""
        today = dt_util.as_local(now).date()
        count = 0
        for med in self.medications.values():
            if self.is_paused(med.id):
                continue
            for scheduled in med.slots_on(today):
                record = self.history.get(dose_id_for(med.id, scheduled))
                if record is None or not record.is_resolved:
                    count += 1
        return count

    def upcoming(self, start: datetime, end: datetime) -> list[DoseRecord]:
        """Planned doses in a time range (not yet in the history)."""
        now = dt_util.utcnow()
        result: list[DoseRecord] = []
        for med in self.medications.values():
            if self.is_paused(med.id):
                continue
            for scheduled in med.slots_between(max(start, now), end):
                if self.history.get(dose_id_for(med.id, scheduled)) is None:
                    result.append(self._new_record(med, scheduled))
        return result

    # ------------------------------------------------------------------ events

    @callback
    def async_notify_entities(self) -> None:
        """Tell all entities of this person to refresh."""
        async_dispatcher_send(self.hass, signal_update(self.entry_id))

    def _fire(self, event_type: str, record: DoseRecord) -> None:
        # Link the event to the medication's status sensor (logbook filtering).
        status_entity = er.async_get(self.hass).async_get_entity_id(
            "sensor", DOMAIN, f"{record.medication_id}_status"
        )
        self.hass.bus.async_fire(
            event_type,
            {
                ATTR_ENTITY_ID: status_entity,
                "entry_id": self.entry_id,
                ATTR_PERSON: self.person,
                CONF_USER_ID: self.user_id,
                ATTR_MEDICATION: record.medication_name,
                ATTR_MEDICATION_ID: record.medication_id,
                ATTR_DOSE_ID: record.id,
                ATTR_SCHEDULED: record.scheduled.isoformat(),
                ATTR_STATUS: record.status.value,
                ATTR_SOURCE: record.source,
                ATTR_REMINDERS_SENT: record.reminders_sent,
            },
        )

    @callback
    def _handle_mobile_action(self, event: Event) -> None:
        parsed = parse_action(str(event.data.get("action", "")))
        if parsed is None:
            return
        action, dose_id = parsed
        record = self.history.get(dose_id)
        if record is None or record.medication_id not in self.medications:
            return  # belongs to another person
        user_id = event.context.user_id
        if action == ACTION_TAKEN:
            if record.is_resolved:
                return
            self.hass.async_create_task(
                self._async_resolve(
                    record, DoseStatus.TAKEN, source=SOURCE_NOTIFICATION, user_id=user_id
                )
            )
        elif action == ACTION_SNOOZE and record.is_open:
            self.hass.async_create_task(
                self.async_snooze(
                    record.medication_id,
                    source=SOURCE_NOTIFICATION,
                    user_id=user_id,
                    dose_id=dose_id,
                )
            )

    @callback
    def _handle_midnight(self, now: datetime) -> None:
        self.history.purge(self.retention_days, dt_util.utcnow())
        self.async_notify_entities()

    @callback
    def _handle_refresh(self, now: datetime) -> None:
        self.async_notify_entities()
