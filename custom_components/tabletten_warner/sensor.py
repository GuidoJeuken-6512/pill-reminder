"""Sensors for the Tabletten-Warner integration."""

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

from . import TablettenWarnerConfigEntry
from .entity import MedicationEntity, PersonEntity
from .models import DoseStatus, Medication
from .scheduler import ReminderManager

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
    entry: TablettenWarnerConfigEntry,
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
