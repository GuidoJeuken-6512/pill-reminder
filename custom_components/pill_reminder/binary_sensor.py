"""'Due' binary sensor for the Pill Reminder integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PillReminderConfigEntry
from .entity import MedicationEntity, PersonEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PillReminderConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    manager = entry.runtime_data
    async_add_entities([PersonDueBinarySensor(manager, "any_due")])
    for med in manager.medications.values():
        async_add_entities(
            [MedicationDueBinarySensor(manager, med, "due")], config_subentry_id=med.id
        )


class MedicationDueBinarySensor(MedicationEntity, BinarySensorEntity):
    """On while a dose of this medication waits for acknowledgement."""

    def _update_from_manager(self) -> None:
        open_doses = self.manager.history.open_doses(self.med.id)
        self._attr_is_on = bool(open_doses)
        dose = open_doses[0] if open_doses else None
        self._attr_extra_state_attributes = {
            "person": self.manager.person,
            "medication": self.med.name,
            "dosage": self.med.dosage,
            "scheduled": dose.scheduled.isoformat() if dose else None,
            "status": dose.status.value if dose else None,
            "reminders_sent": dose.reminders_sent if dose else 0,
            "escalated": dose.escalated if dose else False,
        }


class PersonDueBinarySensor(PersonEntity, BinarySensorEntity):
    """On while any medication of this person is due."""

    def _update_from_manager(self) -> None:
        open_doses = [
            r
            for r in self.manager.history.open_doses()
            if r.medication_id in self.manager.medications
        ]
        self._attr_is_on = bool(open_doses)
        self._attr_extra_state_attributes = {
            "user_id": self.manager.user_id,
            "medications": sorted({r.medication_name for r in open_doses}),
        }
