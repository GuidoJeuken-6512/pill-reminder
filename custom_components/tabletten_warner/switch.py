"""'Reminders enabled' switch for the Tabletten-Warner integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TablettenWarnerConfigEntry
from .entity import MedicationEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TablettenWarnerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up switches."""
    manager = entry.runtime_data
    for med in manager.medications.values():
        async_add_entities([RemindersSwitch(manager, med, "reminders")], config_subentry_id=med.id)


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
