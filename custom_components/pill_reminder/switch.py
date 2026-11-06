"""'Reminders enabled' switch for the Pill Reminder integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PillReminderConfigEntry
from .const import CONF_REMINDER_ENABLED
from .entity import MeasurementEntity, MedicationEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PillReminderConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up switches."""
    manager = entry.runtime_data
    for med in manager.medications.values():
        async_add_entities([RemindersSwitch(manager, med, "reminders")], config_subentry_id=med.id)
    for tracked in manager.body.tracked.values():
        async_add_entities(
            [MeasurementReminderSwitch(manager, tracked, "reminder")],
            config_subentry_id=tracked.subentry_id,
        )


class RemindersSwitch(MedicationEntity, SwitchEntity):
    """Pause reminders, e.g. during a hospital stay."""

    _attr_entity_category = EntityCategory.CONFIG

    def _update_from_manager(self) -> None:
        self._attr_is_on = not self.manager.is_paused(self.med.id)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Resume reminders."""
        await self.manager.async_set_paused(self.med.id, False)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Pause reminders."""
        await self.manager.async_set_paused(self.med.id, True)


class MeasurementReminderSwitch(MeasurementEntity, SwitchEntity):
    """Turn the reminder of a measurement type on or off."""

    _attr_entity_category = EntityCategory.CONFIG

    def _update_from_manager(self) -> None:
        tracked = self.tracked
        self._attr_is_on = bool(tracked and tracked.reminder_enabled)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the reminder on."""
        self.body.async_update_reminder(self.subentry_id, {CONF_REMINDER_ENABLED: True})

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the reminder off."""
        self.body.async_update_reminder(self.subentry_id, {CONF_REMINDER_ENABLED: False})
