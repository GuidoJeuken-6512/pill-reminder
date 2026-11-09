"""Number entities: medication windows, measurement input, height."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory, UnitOfLength, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PillReminderConfigEntry
from .const import (
    CONF_EARLY_MINUTES,
    CONF_LATE_MINUTES,
    MAX_HEIGHT,
    MIN_HEIGHT,
)
from .entity import BodyEntity, MeasurementEntity, MedicationEntity
from .measurement_reminders import TrackedMetric
from .metrics import ValueField
from .models import Medication
from .scheduler import ReminderManager

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class WindowNumberDescription(NumberEntityDescription):
    """A confirmation window setting."""

    field: str


WINDOW_NUMBERS: tuple[WindowNumberDescription, ...] = (
    WindowNumberDescription(
        key="cfg_early_minutes",
        translation_key="cfg_early_minutes",
        field=CONF_EARLY_MINUTES,
        native_min_value=0,
        native_max_value=720,
        native_step=5,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
    WindowNumberDescription(
        key="cfg_late_minutes",
        translation_key="cfg_late_minutes",
        field=CONF_LATE_MINUTES,
        native_min_value=5,
        native_max_value=1440,
        native_step=5,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PillReminderConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up number entities."""
    manager = entry.runtime_data
    for med in manager.medications.values():
        async_add_entities(
            (WindowNumber(manager, med, desc) for desc in WINDOW_NUMBERS),
            config_subentry_id=med.id,
        )
    if manager.body.enabled:
        async_add_entities([HeightNumber(manager, "height")])
    for tracked in manager.body.tracked.values():
        async_add_entities(
            (MeasurementInput(manager, tracked, field) for field in tracked.metric.fields),
            config_subentry_id=tracked.subentry_id,
        )


class WindowNumber(MedicationEntity, NumberEntity):
    """'Can be confirmed early' / 'counts as missed after' in minutes."""

    entity_description: WindowNumberDescription

    def __init__(
        self, manager: ReminderManager, med: Medication, desc: WindowNumberDescription
    ) -> None:
        """Initialize."""
        super().__init__(manager, med, desc.key)
        self.entity_description = desc

    def _update_from_manager(self) -> None:
        window = (
            self.med.early if self.entity_description.field == CONF_EARLY_MINUTES else self.med.late
        )
        self._attr_native_value = window.total_seconds() / 60

    async def async_set_native_value(self, value: float) -> None:
        """Validate and store; the person reloads with the new schedule."""
        self.manager.async_update_medication(
            self.med.id, {self.entity_description.field: int(value)}
        )


class MeasurementInput(MeasurementEntity, NumberEntity):
    """Input field of a value, e.g. weight or systolic pressure.

    Setting a value only remembers it; the "Save" button stores the reading.
    On phones the Companion App does not always send the value of a number box,
    and blood pressure needs several values at once.
    """

    _attr_mode = NumberMode.BOX

    def __init__(self, manager: ReminderManager, tracked: TrackedMetric, field: ValueField) -> None:
        """Initialize."""
        super().__init__(manager, tracked, "input", field)
        self.value_field = field
        self._attr_native_min_value = field.min_value
        self._attr_native_max_value = field.max_value
        self._attr_native_step = field.step
        self._attr_native_unit_of_measurement = field.unit
        self._attr_device_class = field.number_device_class

    def _update_from_manager(self) -> None:
        self._attr_native_value = self.body.draft_value(self.value_field.key)

    async def async_set_native_value(self, value: float) -> None:
        """Remember the value until "Save" is pressed."""
        self.body.async_set_draft(self.value_field.key, value)


class HeightNumber(BodyEntity, NumberEntity):
    """Height of the person, used for BMI and waist-to-height ratio."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_device_class = NumberDeviceClass.DISTANCE
    _attr_native_unit_of_measurement = UnitOfLength.CENTIMETERS
    _attr_native_min_value = MIN_HEIGHT
    _attr_native_max_value = MAX_HEIGHT
    _attr_native_step = 0.5

    def _update_from_manager(self) -> None:
        self._attr_native_value = self.body.height

    async def async_set_native_value(self, value: float) -> None:
        """Store the new height."""
        self.body.async_set_height(value)
