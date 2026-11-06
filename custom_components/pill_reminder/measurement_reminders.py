"""Reminder timers, one per tracked measurement type.

Rules:
- At the configured time on a reminder day, a push is sent unless a value of
  this type was already entered that (local) day.
- One repeat after the configured interval, but only before midnight.
- The type is "due" from the reminder time until a value is entered or the day
  ends.
- What was sent is stored, so a restart neither repeats nor loses a reminder:
  a missed reminder of the same day is caught up.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import CALLBACK_TYPE, callback
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.util import dt as dt_util

from .const import (
    ALL_WEEKDAYS,
    CONF_METRIC,
    CONF_REMINDER_ENABLED,
    CONF_REMINDER_TIME,
    CONF_WEEKDAYS,
    DEFAULT_REMINDER_TIME,
    EVENT_MEASUREMENT_REMINDER,
    SUBENTRY_MEASUREMENT,
)
from .measurements import ReminderState
from .metrics import METRICS, MetricType
from .validation import InvalidInput, parse_reminder_time

if TYPE_CHECKING:
    from .body import BodyTracker

_LOGGER = logging.getLogger(__name__)

MAX_REMINDERS_PER_SLOT = 2  # first reminder + one repeat


@dataclass(frozen=True, slots=True)
class TrackedMetric:
    """A measurement type tracked by a person (one config subentry)."""

    subentry_id: str
    metric: MetricType
    reminder_enabled: bool
    reminder_time: time
    weekdays: tuple[int, ...]

    @classmethod
    def from_subentry(cls, subentry: ConfigSubentry) -> TrackedMetric | None:
        """Build from a subentry; None for medications and unknown types."""
        if subentry.subentry_type != SUBENTRY_MEASUREMENT:
            return None
        metric = METRICS.get(subentry.data.get(CONF_METRIC, ""))
        if metric is None:
            _LOGGER.warning("Unknown measurement type in subentry %s", subentry.subentry_id)
            return None
        try:
            reminder_time = parse_reminder_time(
                subentry.data.get(CONF_REMINDER_TIME, DEFAULT_REMINDER_TIME)
            )
        except InvalidInput:
            reminder_time = parse_reminder_time(DEFAULT_REMINDER_TIME)
        return cls(
            subentry_id=subentry.subentry_id,
            metric=metric,
            reminder_enabled=bool(subentry.data.get(CONF_REMINDER_ENABLED, True)),
            reminder_time=reminder_time,
            weekdays=tuple(sorted(subentry.data.get(CONF_WEEKDAYS, ALL_WEEKDAYS))),
        )

    def slot_on(self, day_start: datetime) -> datetime | None:
        """Reminder time on the local day of `day_start` (None if no reminder day)."""
        local = dt_util.as_local(day_start)
        if local.weekday() not in self.weekdays:
            return None
        return datetime.combine(local.date(), self.reminder_time, tzinfo=local.tzinfo)

    def today_slot(self, now: datetime) -> datetime | None:
        """Today's reminder time (also if it is still ahead)."""
        if not self.reminder_enabled:
            return None
        return self.slot_on(now)

    def next_slot(self, after: datetime) -> datetime | None:
        """First reminder time strictly after `after`."""
        if not self.reminder_enabled or not self.weekdays:
            return None
        local = dt_util.as_local(after)
        for offset in range(8):
            day = datetime.combine(
                local.date() + timedelta(days=offset), time(12), tzinfo=local.tzinfo
            )
            slot = self.slot_on(day)
            if slot is not None and slot > after:
                return slot
        return None


def _next_midnight(now: datetime) -> datetime:
    local = dt_util.as_local(now)
    return dt_util.start_of_local_day(local.date() + timedelta(days=1))


class MetricReminder:
    """Timers and notifications for one tracked measurement type."""

    def __init__(self, tracker: BodyTracker, tracked: TrackedMetric) -> None:
        """Initialize."""
        self.tracker = tracker
        self.tracked = tracked
        self._slot_timer: CALLBACK_TYPE | None = None
        self._repeat_timer: CALLBACK_TYPE | None = None

    @property
    def key(self) -> str:
        """Measurement type key."""
        return self.tracked.metric.key

    # --------------------------------------------------------------- lifecycle

    @callback
    def async_start(self, now: datetime) -> None:
        """Start the timers and catch up on today's reminder."""
        self._schedule_slot(now)
        slot = self.tracked.today_slot(now)
        if slot is not None and slot <= now:
            self.tracker.entry.async_create_background_task(
                self.tracker.hass, self.async_check(now), f"pill_reminder catch-up {self.key}"
            )

    @callback
    def async_stop(self) -> None:
        """Cancel all timers."""
        for unsub in (self._slot_timer, self._repeat_timer):
            if unsub:
                unsub()
        self._slot_timer = self._repeat_timer = None

    def _schedule_slot(self, after: datetime) -> None:
        if self._slot_timer:
            self._slot_timer()
            self._slot_timer = None
        slot = self.tracked.next_slot(after)
        if slot is None:
            return

        @callback
        def _fire(now: datetime) -> None:
            self._slot_timer = None
            self._schedule_slot(slot)
            self.tracker.async_notify_entities()  # due sensor turns on
            self.tracker.entry.async_create_background_task(
                self.tracker.hass, self.async_check(slot), f"pill_reminder measurement {self.key}"
            )

        self._slot_timer = async_track_point_in_time(self.tracker.hass, _fire, slot)

    def _schedule_repeat(self, when: datetime) -> None:
        if self._repeat_timer:
            self._repeat_timer()

        @callback
        def _fire(now: datetime) -> None:
            self._repeat_timer = None
            self.tracker.entry.async_create_background_task(
                self.tracker.hass, self.async_check(when), f"pill_reminder repeat {self.key}"
            )

        self._repeat_timer = async_track_point_in_time(self.tracker.hass, _fire, when)

    # ------------------------------------------------------------------- logic

    def is_due(self, now: datetime) -> bool:
        """Reminder time reached today and no value entered today."""
        slot = self.tracked.today_slot(now)
        if slot is None or slot > now:
            return False
        return not self.tracker.store.on_day(self.key, dt_util.as_local(now).date())

    def state_for(self, slot: datetime) -> ReminderState | None:
        """What was sent for this slot (None if nothing)."""
        state = self.tracker.store.reminders.get(self.key)
        return state if state is not None and state.slot == slot else None

    async def async_check(self, now: datetime) -> None:
        """Send the reminder or its repeat if due."""
        if self._repeat_timer:
            self._repeat_timer()
            self._repeat_timer = None
        now = max(now, dt_util.utcnow())
        if not self.is_due(now):
            return
        slot = self.tracked.today_slot(now)
        assert slot is not None
        state = self.state_for(slot)
        interval = self.tracker.repeat_interval

        if state is None:
            state = await self._async_send(slot, 1, now)
        elif (
            state.count < MAX_REMINDERS_PER_SLOT
            and interval
            and now >= state.sent + interval - timedelta(seconds=1)
        ):
            state = await self._async_send(slot, state.count + 1, now)

        if interval and state.count < MAX_REMINDERS_PER_SLOT:
            repeat_at = state.sent + interval
            if repeat_at < _next_midnight(now):
                self._schedule_repeat(repeat_at)

    async def _async_send(self, slot: datetime, count: int, now: datetime) -> ReminderState:
        tracker = self.tracker
        state = ReminderState(slot=slot, count=count, sent=now)
        tracker.store.reminders[self.key] = state
        tracker.store.async_schedule_save()
        await tracker.notifier.async_send_measurement_reminder(
            tracker.notify_services,
            self.tracked.metric,
            last=tracker.store.latest(self.key),
            count=count,
            url=tracker.dashboard_url(),
            persistent=tracker.persistent,
        )
        tracker.hass.bus.async_fire(
            EVENT_MEASUREMENT_REMINDER,
            {
                "entry_id": tracker.entry_id,
                "person": tracker.person,
                "metric": self.key,
                "count": count,
            },
        )
        return state

    async def async_measurement_added(self, now: datetime) -> None:
        """A value was entered: stop repeating and clear today's reminder."""
        if self.is_due(now):
            return
        slot = self.tracked.slot_on(now)
        if self._repeat_timer:
            self._repeat_timer()
            self._repeat_timer = None
        if slot is not None and self.state_for(slot) is not None:
            await self.tracker.notifier.async_clear_measurement(
                self.tracker.notify_services, self.key
            )
