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
from .metrics import (
    BLOOD_PRESSURE,
    FIELD_METRIC,
    FIELDS,
    METRICS,
    WAIST,
    WEIGHT,
    MetricType,
    field_title,
)
from .notifier import MeasurementNotifier
from .stats import (
    BloodPressureCategory,
    BmiCategory,
    TrendDirection,
    WhtrCategory,
    average,
    blood_pressure_category,
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
        # Values typed into the dashboard input fields, stored on "Save"
        self.drafts: dict[str, float] = {}

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

    def _validate(self, metric: MetricType, values: dict[str, float]) -> None:
        unknown = set(values) - {f.key for f in metric.fields}
        if unknown:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_metric",
                translation_placeholders={"metric": ", ".join(sorted(unknown))},
            )
        language = (self.hass.config.language or "en").split("-")[0]
        for field in metric.fields:
            value = values.get(field.key)
            if value is None:
                if field.required:
                    raise ServiceValidationError(
                        translation_domain=DOMAIN,
                        translation_key="value_required",
                        translation_placeholders={"field": field_title(field.key, language)},
                    )
                continue
            if not field.min_value <= value <= field.max_value:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="value_out_of_range",
                    translation_placeholders={
                        "value": f"{value:g}",
                        "min": f"{field.min_value:g}",
                        "max": f"{field.max_value:g}",
                        "unit": field.unit,
                    },
                )
        if metric is BLOOD_PRESSURE and values["systolic"] <= values["diastolic"]:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="systolic_not_above_diastolic"
            )

    async def async_add_values(
        self,
        key: str,
        values: dict[str, float],
        *,
        source: str,
        measured_at: datetime | None = None,
    ) -> list[Measurement]:
        """Store the values of one reading (e.g. systolic, diastolic, pulse) together."""
        metric = self._metric(key)
        values = {k: float(v) for k, v in values.items() if v is not None}
        self._validate(metric, values)
        now = dt_util.utcnow()
        when = dt_util.as_utc(measured_at) if measured_at else now
        if when > now + timedelta(minutes=5):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="measured_in_future"
            )
        stored = [
            self.store.add(field.key, round(values[field.key], field.decimals + 1), when, source)
            for field in metric.fields
            if field.key in values
        ]
        event: dict[str, Any] = {
            "entry_id": self.entry_id,
            "person": self.person,
            "metric": key,
            "values": {m.metric: m.value for m in stored},
            "units": {m.metric: FIELDS[m.metric].unit for m in stored},
            "measured_at": when.isoformat(),
            "source": source,
        }
        if metric.single:
            event["value"] = stored[0].value
            event["unit"] = metric.main.unit
        self.hass.bus.async_fire(EVENT_MEASUREMENT_ADDED, event)
        self.async_notify_entities()
        for reminder in self._reminders.values():
            if reminder.key == key:
                await reminder.async_measurement_added(now)
        return stored

    async def async_add_measurement(
        self,
        key: str,
        value: float,
        *,
        source: str,
        measured_at: datetime | None = None,
    ) -> Measurement:
        """Store a single value (weight, waist)."""
        metric = self._metric(key)
        if not metric.single:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="value_required",
                translation_placeholders={"field": ", ".join(f.key for f in metric.fields)},
            )
        stored = await self.async_add_values(
            key, {key: value}, source=source, measured_at=measured_at
        )
        return stored[0]

    # ------------------------------------------------------- dashboard input

    def draft_value(self, field_key: str) -> float | None:
        """Value shown in an input field.

        Single values (weight) start with the last value, so "Save" without
        typing stores the same weight again. Blood pressure fields start empty,
        so an old reading is never saved by accident.
        """
        if (draft := self.drafts.get(field_key)) is not None:
            return draft
        metric = METRICS[FIELD_METRIC[field_key]]
        if metric.single:
            latest = self.latest(field_key)
            return latest.value if latest else None
        return None

    @callback
    def async_set_draft(self, field_key: str, value: float) -> None:
        """Remember a typed value until "Save" is pressed."""
        self.drafts[field_key] = value
        self.async_notify_entities()

    async def async_save_drafts(self, key: str, *, source: str) -> list[Measurement]:
        """Store the values of the input fields of one measurement type."""
        metric = self._metric(key)
        values = {
            field.key: value
            for field in metric.fields
            if (value := self.draft_value(field.key)) is not None
        }
        stored = await self.async_add_values(key, values, source=source)
        for field in metric.fields:
            self.drafts.pop(field.key, None)
        self.async_notify_entities()
        return stored

    def delete_measurements(self, key: str, day: date | None = None) -> list[Measurement]:
        """Delete all values of a type on a local day, or the most recent reading."""
        metric = self._metric(key)
        targets: list[Measurement] = []
        if day is not None:
            for field in metric.fields:
                targets += self.store.on_day(field.key, day)
        elif latest := self.store.latest(metric.main.key):
            targets = [
                m
                for field in metric.fields
                for m in self.store.measurements(field.key)
                if m.measured_at == latest.measured_at
            ]
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

    def latest_reading(self, key: str) -> str | None:
        """Last reading of a measurement type as text, e.g. '81.2' or '128/82'."""
        metric = METRICS[key]
        if metric is BLOOD_PRESSURE:
            systolic, diastolic = self.latest("systolic"), self.latest("diastolic")
            if systolic is None or diastolic is None:
                return None
            return f"{systolic.value:.0f}/{diastolic.value:.0f}"
        latest = self.latest(metric.main.key)
        return f"{latest.value:.{metric.main.decimals}f}" if latest else None

    def last_measured(self, key: str) -> datetime | None:
        """Time of the last reading of a measurement type."""
        latest = self.latest(METRICS[key].main.key)
        return latest.measured_at if latest else None

    def change(self, key: str, days: int) -> float | None:
        """Change over `days` days (daily values)."""
        value = change(self.store.daily(key), dt_util.utcnow(), days)
        return None if value is None else round(value, FIELDS[key].decimals)

    def average(self, key: str, days: int) -> float | None:
        """Mean of all values of a field in the last `days` days."""
        points = [(m.measured_at, m.value) for m in self.store.measurements(key)]
        value = average(points, dt_util.utcnow(), days)
        return None if value is None else round(value, FIELDS[key].decimals + 1)

    def blood_pressure_category(self) -> BloodPressureCategory | None:
        """Class of the last blood pressure reading."""
        systolic, diastolic = self.latest("systolic"), self.latest("diastolic")
        return blood_pressure_category(
            systolic.value if systolic else None, diastolic.value if diastolic else None
        )

    def trend(self, key: str) -> float | None:
        """Trend in units per week (daily values, last 14 days)."""
        value = trend(self.store.daily(key), dt_util.utcnow())
        return None if value is None else round(value, 2)

    def trend_direction(self, key: str) -> TrendDirection | None:
        """Rising / falling / stable."""
        return trend_direction(self.trend(key), FIELDS[key].trend_threshold)

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
