"""Base entities for the Pill Reminder integration."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .body import BodyTracker
from .const import DOMAIN, signal_update
from .measurement_reminders import TrackedMetric
from .metrics import MetricType
from .models import Medication
from .scheduler import ReminderManager


class PillReminderEntity(Entity):
    """Common behaviour: no polling, refresh on dispatcher signal."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, manager: ReminderManager) -> None:
        """Initialize."""
        self.manager = manager

    @property
    def _user_id(self) -> str | None:
        return self._context.user_id if self._context else None

    async def async_added_to_hass(self) -> None:
        """Subscribe to state changes of the person."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_update(self.manager.entry_id), self._handle_update
            )
        )
        self._update_from_manager()

    @callback
    def _handle_update(self) -> None:
        """Recompute state and write it."""
        self._update_from_manager()
        self.async_write_ha_state()

    def _update_from_manager(self) -> None:
        """Override to compute _attr_* values."""


class PersonEntity(PillReminderEntity):
    """Entity attached to the person device."""

    def __init__(self, manager: ReminderManager, key: str) -> None:
        """Initialize."""
        super().__init__(manager)
        self._attr_translation_key = key
        self._attr_unique_id = f"{manager.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, manager.entry_id)},
            name=manager.person,
            manufacturer="Pill Reminder",
            model="Person",
            entry_type=DeviceEntryType.SERVICE,
        )


class MedicationEntity(PillReminderEntity):
    """Entity attached to a medication device (one per subentry)."""

    def __init__(self, manager: ReminderManager, med: Medication, key: str) -> None:
        """Initialize."""
        super().__init__(manager)
        self.med = med
        self._attr_translation_key = key
        self._attr_unique_id = f"{med.id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, med.id)},
            name=med.name,
            manufacturer="Pill Reminder",
            model=med.dosage or None,
            entry_type=DeviceEntryType.SERVICE,
            via_device_id=manager.person_device_id,
        )


class BodyEntity(PersonEntity):
    """Person entity of the body measurements (height, BMI, ...)."""

    def __init__(self, manager: ReminderManager, key: str) -> None:
        """Initialize."""
        super().__init__(manager, key)
        self.body: BodyTracker = manager.body


class MeasurementEntity(PillReminderEntity):
    """Entity of one tracked measurement type (one device per subentry)."""

    def __init__(self, manager: ReminderManager, tracked: TrackedMetric, key: str) -> None:
        """Initialize; translation key and unique id are '<metric>_<key>'."""
        super().__init__(manager)
        self.body: BodyTracker = manager.body
        self.subentry_id = tracked.subentry_id
        self.metric: MetricType = tracked.metric
        full_key = f"{tracked.metric.key}_{key}"
        self._attr_translation_key = full_key
        self._attr_unique_id = f"{manager.entry_id}_{full_key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{manager.entry_id}_{tracked.metric.key}")},
            translation_key=tracked.metric.key,
            translation_placeholders={"person": manager.person},
            manufacturer="Pill Reminder",
            model="Measurement",
            entry_type=DeviceEntryType.SERVICE,
            via_device_id=manager.person_device_id,
        )

    @property
    def tracked(self) -> TrackedMetric | None:
        """Current settings (they change without a reload)."""
        return self.body.tracked.get(self.subentry_id)
