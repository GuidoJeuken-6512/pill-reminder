"""Reminder time per measurement type."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PillReminderConfigEntry
from .const import CONF_REMINDER_TIME
from .entity import MeasurementEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PillReminderConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up time entities."""
    manager = entry.runtime_data
    for tracked in manager.body.tracked.values():
        async_add_entities(
            [ReminderTime(manager, tracked, "reminder_time")],
            config_subentry_id=tracked.subentry_id,
        )


class ReminderTime(MeasurementEntity, TimeEntity):
    """Time of day of a measurement reminder."""

    _attr_entity_category = EntityCategory.CONFIG

    def _update_from_manager(self) -> None:
        tracked = self.tracked
        self._attr_native_value = tracked.reminder_time if tracked else None

    async def async_set_value(self, value: time) -> None:
        """Store the new reminder time."""
        self.body.async_update_reminder(
            self.subentry_id, {CONF_REMINDER_TIME: value.strftime("%H:%M")}
        )
