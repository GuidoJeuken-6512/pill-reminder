"""Buttons (taken / snooze / skip) for the Pill Reminder integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import PillReminderConfigEntry
from .const import SOURCE_BUTTON
from .entity import MedicationEntity, PersonEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PillReminderConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up buttons."""
    manager = entry.runtime_data
    async_add_entities([AddMedicationButton(manager, "add_medication")])
    for med in manager.medications.values():
        async_add_entities(
            [
                TakenButton(manager, med, "taken"),
                SnoozeButton(manager, med, "snooze"),
                SkipButton(manager, med, "skip"),
                DeleteMedicationButton(manager, med, "delete_medication"),
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


class DeleteMedicationButton(MedicationEntity, ButtonEntity):
    """Delete the medication (its history is kept)."""

    _attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        """Delete the medication."""
        self.manager.async_delete_medication(self.med.id)


class AddMedicationButton(PersonEntity, ButtonEntity):
    """Create a medication from the 'new medication' input fields."""

    _attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        """Add the medication."""
        self.manager.async_add_medication()
