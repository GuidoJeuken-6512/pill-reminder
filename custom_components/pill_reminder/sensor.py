"""Sensors: medication, adherence, body measurements, BMI and waist-to-height ratio."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import PillReminderConfigEntry
from .body import BodyTracker
from .entity import BodyEntity, MeasurementEntity, MedicationEntity, PersonEntity
from .measurement_reminders import TrackedMetric
from .metrics import MetricType
from .models import DoseStatus, Medication
from .scheduler import ReminderManager
from .stats import BmiCategory, TrendDirection, WhtrCategory

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class MedicationSensorDescription(SensorEntityDescription):
    """Describes a medication sensor."""

    value_fn: Callable[[ReminderManager, Medication, datetime], Any]


@dataclass(frozen=True, kw_only=True)
class PersonSensorDescription(SensorEntityDescription):
    """Describes a person sensor."""

    value_fn: Callable[[ReminderManager, datetime], Any]


def _last_taken(manager: ReminderManager, med: Medication, _now: datetime) -> datetime | None:
    record = manager.history.last_taken(med.id)
    return record.resolved_at if record else None


MEDICATION_SENSORS: tuple[MedicationSensorDescription, ...] = (
    MedicationSensorDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=[s.value for s in DoseStatus],
        value_fn=lambda m, med, now: m.medication_status(med.id, now).value,
    ),
    MedicationSensorDescription(
        key="next_dose",
        translation_key="next_dose",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda m, med, now: m.next_dose(med.id, now),
    ),
    MedicationSensorDescription(
        key="last_taken",
        translation_key="last_taken",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_last_taken,
    ),
    MedicationSensorDescription(
        key="adherence_7d",
        translation_key="adherence_7d",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda m, med, now: m.history.adherence(now, 7, med.id),
    ),
    MedicationSensorDescription(
        key="adherence_30d",
        translation_key="adherence_30d",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda m, med, now: m.history.adherence(now, 30, med.id),
    ),
    MedicationSensorDescription(
        key="streak",
        translation_key="streak",
        native_unit_of_measurement=UnitOfTime.DAYS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda m, med, now: m.history.streak(now, med.id),
    ),
)

PERSON_SENSORS: tuple[PersonSensorDescription, ...] = (
    PersonSensorDescription(
        key="open_today",
        translation_key="open_today",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda m, now: m.open_today(now),
    ),
    PersonSensorDescription(
        key="taken_today",
        translation_key="taken_today",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda m, now: m.count_today(now, DoseStatus.TAKEN),
    ),
    PersonSensorDescription(
        key="missed_today",
        translation_key="missed_today",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda m, now: m.count_today(now, DoseStatus.MISSED),
    ),
    PersonSensorDescription(
        key="skipped_today",
        translation_key="skipped_today",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda m, now: m.count_today(now, DoseStatus.SKIPPED),
    ),
    PersonSensorDescription(
        key="adherence_7d",
        translation_key="adherence_7d",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda m, now: m.history.adherence(now, 7),
    ),
    PersonSensorDescription(
        key="adherence_30d",
        translation_key="adherence_30d",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda m, now: m.history.adherence(now, 30),
    ),
    PersonSensorDescription(
        key="streak",
        translation_key="streak",
        native_unit_of_measurement=UnitOfTime.DAYS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda m, now: m.history.streak(now),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PillReminderConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    manager = entry.runtime_data
    async_add_entities(PersonSensor(manager, desc) for desc in PERSON_SENSORS)
    for med in manager.medications.values():
        async_add_entities(
            (MedicationSensor(manager, med, desc) for desc in MEDICATION_SENSORS),
            config_subentry_id=med.id,
        )
    if manager.body.enabled:
        async_add_entities(BodySensor(manager, desc) for desc in BODY_SENSORS)
    for tracked in manager.body.tracked.values():
        async_add_entities(
            (MeasurementSensor(manager, tracked, desc) for desc in MEASUREMENT_SENSORS),
            config_subentry_id=tracked.subentry_id,
        )


class MedicationSensor(MedicationEntity, SensorEntity):
    """Sensor of one medication."""

    entity_description: MedicationSensorDescription

    def __init__(
        self, manager: ReminderManager, med: Medication, desc: MedicationSensorDescription
    ) -> None:
        """Initialize."""
        super().__init__(manager, med, desc.key)
        self.entity_description = desc

    def _update_from_manager(self) -> None:
        now = dt_util.utcnow()
        self._attr_native_value = self.entity_description.value_fn(self.manager, self.med, now)
        # Stable attributes for dashboard filters (auto-entities)
        attributes: dict[str, Any] = {
            "person": self.manager.person,
            "medication": self.med.name,
        }
        if self.entity_description.key == "status":
            open_doses = self.manager.history.open_doses(self.med.id)
            dose = open_doses[0] if open_doses else None
            attributes |= {
                "dosage": self.med.dosage,
                "times": [t.strftime("%H:%M") for t in self.med.times],
                "scheduled": dose.scheduled.isoformat() if dose else None,
                "reminders_sent": dose.reminders_sent if dose else 0,
                "snoozed_until": (
                    dose.snoozed_until.isoformat() if dose and dose.snoozed_until else None
                ),
            }
        self._attr_extra_state_attributes = attributes


class PersonSensor(PersonEntity, SensorEntity):
    """Summary sensor of one person."""

    entity_description: PersonSensorDescription

    def __init__(self, manager: ReminderManager, desc: PersonSensorDescription) -> None:
        """Initialize."""
        super().__init__(manager, desc.key)
        self.entity_description = desc

    def _update_from_manager(self) -> None:
        self._attr_native_value = self.entity_description.value_fn(self.manager, dt_util.utcnow())


# ---------------------------------------------------------------- measurements


@dataclass(frozen=True, kw_only=True)
class BodySensorDescription(SensorEntityDescription):
    """A value derived from the person's measurements."""

    value_fn: Callable[[BodyTracker], Any]


BODY_SENSORS: tuple[BodySensorDescription, ...] = (
    BodySensorDescription(
        key="bmi",
        translation_key="bmi",
        native_unit_of_measurement="kg/m²",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda b: b.bmi(),
    ),
    BodySensorDescription(
        key="bmi_category",
        translation_key="bmi_category",
        device_class=SensorDeviceClass.ENUM,
        options=[c.value for c in BmiCategory],
        value_fn=lambda b: c.value if (c := b.bmi_category()) else None,
    ),
    BodySensorDescription(
        key="whtr",
        translation_key="whtr",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda b: b.whtr(),
    ),
    BodySensorDescription(
        key="whtr_category",
        translation_key="whtr_category",
        device_class=SensorDeviceClass.ENUM,
        options=[c.value for c in WhtrCategory],
        value_fn=lambda b: c.value if (c := b.whtr_category()) else None,
    ),
)


@dataclass(frozen=True, kw_only=True)
class MeasurementSensorDescription(SensorEntityDescription):
    """A value per measurement type."""

    value_fn: Callable[[BodyTracker, str], Any]
    # Use the metric's unit and device class
    with_unit: bool = False


def _last_value(body: BodyTracker, key: str) -> float | None:
    latest = body.latest(key)
    return latest.value if latest else None


def _last_measured(body: BodyTracker, key: str) -> datetime | None:
    latest = body.latest(key)
    return latest.measured_at if latest else None


MEASUREMENT_SENSORS: tuple[MeasurementSensorDescription, ...] = (
    MeasurementSensorDescription(
        key="last",
        state_class=SensorStateClass.MEASUREMENT,
        with_unit=True,
        value_fn=_last_value,
    ),
    MeasurementSensorDescription(
        key="last_measured",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_last_measured,
    ),
    MeasurementSensorDescription(
        key="change_7d",
        with_unit=True,
        value_fn=lambda b, key: b.change(key, 7),
    ),
    MeasurementSensorDescription(
        key="change_30d",
        with_unit=True,
        value_fn=lambda b, key: b.change(key, 30),
    ),
    MeasurementSensorDescription(
        key="trend",
        suggested_display_precision=2,
        value_fn=lambda b, key: b.trend(key),
    ),
    MeasurementSensorDescription(
        key="trend_direction",
        device_class=SensorDeviceClass.ENUM,
        options=[d.value for d in TrendDirection],
        value_fn=lambda b, key: d.value if (d := b.trend_direction(key)) else None,
    ),
)


class BodySensor(BodyEntity, SensorEntity):
    """BMI, waist-to-height ratio and their categories."""

    entity_description: BodySensorDescription

    def __init__(self, manager: ReminderManager, desc: BodySensorDescription) -> None:
        """Initialize."""
        super().__init__(manager, desc.key)
        self.entity_description = desc

    def _update_from_manager(self) -> None:
        self._attr_native_value = self.entity_description.value_fn(self.body)


class MeasurementSensor(MeasurementEntity, SensorEntity):
    """Last value, last measured, change and trend of a measurement type."""

    entity_description: MeasurementSensorDescription

    def __init__(
        self,
        manager: ReminderManager,
        tracked: TrackedMetric,
        desc: MeasurementSensorDescription,
    ) -> None:
        """Initialize."""
        super().__init__(manager, tracked, desc.key)
        self.entity_description = desc
        metric: MetricType = tracked.metric
        if desc.key == "last":
            # Main value of the device: named like the device ("Anna Weight")
            self._attr_name = None
        if desc.with_unit:
            self._attr_native_unit_of_measurement = metric.unit
            self._attr_device_class = metric.sensor_device_class
            self._attr_suggested_display_precision = metric.decimals

    def _update_from_manager(self) -> None:
        self._attr_native_value = self.entity_description.value_fn(self.body, self.metric.key)
