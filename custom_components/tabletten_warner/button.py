"""Buttons (taken / snooze / skip) for the Tabletten-Warner integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import TablettenWarnerConfigEntry
from .const import SOURCE_BUTTON
from .entity import MedicationEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TablettenWarnerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up buttons."""
    manager = entry.runtime_data
    for med in manager.medications.values():
        async_add_entities(
            [
                TakenButton(manager, med, "taken"),
                SnoozeButton(manager, med, "snooze"),
                SkipButton(manager, med, "skip"),
            ],
            config_subentry_id=med.id,
        )


class TakenButton(MedicationEntity, ButtonEntity):
    """Acknowledge the current dose."""

    def _update_from_manager(self) -> None:
        dose = self.manager.find_actionable_dose(self.med.id, dt_util.utcnow())
        # Stable, language independent attributes for dashboard filters (auto-entities)
        self._attr_extra_state_attributes = {
            "person": self.manager.person,
            "medication": self.med.name,
            "dosage": self.med.dosage,
            "due": bool(dose and dose.is_open),
            "actionable": dose is not None,
            "scheduled": dose.scheduled.isoformat() if dose else None,
        }

    async def async_press(self) -> None:
        """Mark the dose as taken."""
        await self.manager.async_take(self.med.id, source=SOURCE_BUTTON, user_id=self._user_id)


class SnoozeButton(MedicationEntity, ButtonEntity):
    """Postpone the reminder."""

    async def async_press(self) -> None:
        """Snooze the open dose."""
        await self.manager.async_snooze(self.med.id, source=SOURCE_BUTTON, user_id=self._user_id)


class SkipButton(MedicationEntity, ButtonEntity):
    """Deliberately skip the current dose."""

    async def async_press(self) -> None:
        """Skip the dose."""
        await self.manager.async_skip(self.med.id, source=SOURCE_BUTTON, user_id=self._user_id)
