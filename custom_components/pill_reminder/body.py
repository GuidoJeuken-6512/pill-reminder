"""Body measurements of one person: values, BMI, waist-to-height ratio, trend, reminders."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .const import (
    CONF_HEIGHT,
    CONF_MEASUREMENT_REPEAT,
    CONF_NOTIFY_SERVICES,
    CONF_PERSISTENT_NOTIFICATION,
    CONF_PERSON_NAME,
    CONF_USER_ID,
    DEFAULT_MEASUREMENT_REPEAT,
    DEFAULT_PERSISTENT_NOTIFICATION,
    DOMAIN,
    EVENT_MEASUREMENT_ADDED,
    MAX_HEIGHT,
    MIN_HEIGHT,
    signal_update,
)
from .measurement_reminders import MetricReminder, TrackedMetric
from .measurements import Measurement, MeasurementStore
from .metrics import METRICS, WAIST, WEIGHT, MetricType
from .notifier import MeasurementNotifier
from .stats import (
    BmiCategory,
    TrendDirection,
    WhtrCategory,
    bmi,
    bmi_category,
    change,
    trend,
    trend_direction,
    whtr,
    whtr_category,
)
from .validation import validate_measurement


class BodyTracker:
    """Measurements, evaluation and measurement reminders of one person."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize from the config entry."""
        self.hass = hass
        self.entry = entry
        self.entry_id = entry.entry_id
        self.person: str = entry.data[CONF_PERSON_NAME]
        self.user_id: str | None = entry.data.get(CONF_USER_ID) or None
        self.notify_services: list[str] = list(entry.data.get(CONF_NOTIFY_SERVICES, []))
        minutes = int(entry.options.get(CONF_MEASUREMENT_REPEAT, DEFAULT_MEASUREMENT_REPEAT))
        self.repeat_interval: timedelta | None = timedelta(minutes=minutes) if minutes else None
        self.persistent: bool = bool(
            entry.options.get(CONF_PERSISTENT_NOTIFICATION, DEFAULT_PERSISTENT_NOTIFICATION)
        )
        self.height: float | None = None
        self.tracked: dict[str, TrackedMetric] = {}
        self._read_settings()

        self.store = MeasurementStore(hass, entry.entry_id)
        self.notifier = MeasurementNotifier(hass, self.person, entry.entry_id)
        self.person_device_id: str | None = None
        self._reminders: dict[str, MetricReminder] = {}

    def _read_settings(self) -> None:
        """Settings that can change without a reload."""
        height = self.entry.data.get(CONF_HEIGHT)
        self.height = float(height) if height else None
        self.tracked = {
            sub_id: tracked
            for sub_id, sub in self.entry.subentries.items()
            if (tracked := TrackedMetric.from_subentry(sub)) is not None
        }

    @property
    def enabled(self) -> bool:
        """The person tracks at least one measurement."""
        return bool(self.tracked)

    # --------------------------------------------------------------- lifecycle

    async def async_start(self) -> None:
        """Load the measurements and start the reminders."""
        await self.store.async_load()
        self._start_reminders()

    async def async_stop(self) -> None:
        """Stop timers and persist."""
        self._stop_reminders()
        await self.store.async_save_now()

    def _start_reminders(self) -> None:
        now = dt_util.utcnow()
        for sub_id, tracked in self.tracked.items():
            reminder = MetricReminder(self, tracked)
            self._reminders[sub_id] = reminder
            reminder.async_start(now)

    def _stop_reminders(self) -> None:
        for reminder in self._reminders.values():
            reminder.async_stop()
        self._reminders.clear()

    @callback
    def async_apply_settings(self) -> None:
        """Height or reminder settings changed: apply without a reload."""
        self._read_settings()
        self._stop_reminders()
        self._start_reminders()
        self.async_notify_entities()

    @callback
    def async_notify_entities(self) -> None:
        """Tell all entities of this person to refresh."""
        async_dispatcher_send(self.hass, signal_update(self.entry_id))

    def dashboard_url(self) -> str:
        """URL of the person's body view (opened from the notification)."""
        from .dashboard import body_url  # dashboard imports this module

        return body_url(self.hass, self.entry_id)

    # ----------------------------------------------------------------- changes

    def _metric(self, key: str) -> MetricType:
        metric = METRICS.get(key)
        if metric is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_metric",
                translation_placeholders={"metric": key},
            )
        return metric

    async def async_add_measurement(
        self,
        key: str,
        value: float,
        *,
        source: str,
        measured_at: datetime | None = None,
    ) -> Measurement:
        """Store a value; clears today's reminder."""
        metric = self._metric(key)
        if not metric.min_value <= value <= metric.max_value:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="value_out_of_range",
                translation_placeholders={
                    "value": str(value),
                    "min": f"{metric.min_value:g}",
                    "max": f"{metric.max_value:g}",
                    "unit": metric.unit,
                },
            )
        now = dt_util.utcnow()
        when = dt_util.as_utc(measured_at) if measured_at else now
        if when > now + timedelta(minutes=5):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="measured_in_future"
            )
        measurement = self.store.add(key, round(value, metric.decimals + 1), when, source)
        self.hass.bus.async_fire(
            EVENT_MEASUREMENT_ADDED,
            {
                "entry_id": self.entry_id,
                "person": self.person,
                "metric": key,
                "value": measurement.value,
                "unit": metric.unit,
                "measured_at": measurement.measured_at.isoformat(),
                "source": source,
            },
        )
        self.async_notify_entities()
        for reminder in self._reminders.values():
            if reminder.key == key:
                await reminder.async_measurement_added(now)
        return measurement

    def delete_measurements(self, key: str, day: date | None = None) -> list[Measurement]:
        """Delete all values of a type on a local day, or the most recent one."""
        self._metric(key)
        if day is not None:
            targets = self.store.on_day(key, day)
        else:
            latest = self.store.latest(key)
            targets = [latest] if latest else []
        if not targets:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_measurement"
            )
        removed = self.store.remove({m.id for m in targets})
        self.async_notify_entities()
        return removed

    @callback
    def async_set_height(self, height: float) -> None:
        """Store a new height (applied via the update listener, no reload)."""
        if not MIN_HEIGHT <= height <= MAX_HEIGHT:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="invalid_height"
            )
        self.hass.config_entries.async_update_entry(
            self.entry, data={**self.entry.data, CONF_HEIGHT: round(height, 1)}
        )

    @callback
    def async_update_reminder(self, subentry_id: str, changes: dict[str, Any]) -> None:
        """Change reminder settings of a tracked type (applied without a reload)."""
        subentry = self.entry.subentries.get(subentry_id)
        if subentry is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_metric",
                translation_placeholders={"metric": subentry_id},
            )
        data, errors = validate_measurement({**subentry.data, **changes})
        if errors:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key=next(iter(errors.values()))
            )
        self.hass.config_entries.async_update_subentry(self.entry, subentry, data=data)

    # ----------------------------------------------------------------- queries

    def latest(self, key: str) -> Measurement | None:
        """Most recent value of a type."""
        return self.store.latest(key)

    def change(self, key: str, days: int) -> float | None:
        """Change over `days` days (daily values)."""
        value = change(self.store.daily(key), dt_util.utcnow(), days)
        return None if value is None else round(value, METRICS[key].decimals)

    def trend(self, key: str) -> float | None:
        """Trend in units per week (daily values, last 14 days)."""
        value = trend(self.store.daily(key), dt_util.utcnow())
        return None if value is None else round(value, 2)

    def trend_direction(self, key: str) -> TrendDirection | None:
        """Rising / falling / stable."""
        return trend_direction(self.trend(key), METRICS[key].trend_threshold)

    def bmi(self) -> float | None:
        """BMI from the latest weight."""
        weight = self.latest(WEIGHT.key)
        return bmi(weight.value if weight else None, self.height)

    def bmi_category(self) -> BmiCategory | None:
        """WHO class of the BMI."""
        return bmi_category(self.bmi())

    def whtr(self) -> float | None:
        """Waist-to-height ratio from the latest waist value."""
        waist = self.latest(WAIST.key)
        return whtr(waist.value if waist else None, self.height)

    def whtr_category(self) -> WhtrCategory | None:
        """Class of the waist-to-height ratio."""
        return whtr_category(self.whtr())

    def is_due(self, subentry_id: str) -> bool:
        """Reminder reached today and nothing entered yet."""
        reminder = self._reminders.get(subentry_id)
        return reminder.is_due(dt_util.utcnow()) if reminder else False

    def tracked_by_metric(self, key: str) -> TrackedMetric | None:
        """The tracked type with this key."""
        return next((t for t in self.tracked.values() if t.metric.key == key), None)

    def tracked_keys(self) -> list[str]:
        """Tracked measurement type keys in registry order."""
        keys = {t.metric.key for t in self.tracked.values()}
        return [key for key in METRICS if key in keys]
