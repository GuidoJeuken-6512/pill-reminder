"""Text entities to set up medications from the dashboard."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.text import TextEntity, TextEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PillReminderConfigEntry
from .const import CONF_DOSAGE, CONF_NAME, CONF_TIMES, CONF_WEEKDAYS
from .entity import MedicationEntity, PersonEntity
from .models import Medication
from .scheduler import ReminderManager
from .validation import format_times, format_weekdays

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class MedicationTextDescription(TextEntityDescription):
    """A medication setting shown as text."""

    field: str
    value_fn: Callable[[Medication, str], str]


MEDICATION_TEXTS: tuple[MedicationTextDescription, ...] = (
    MedicationTextDescription(
        key="cfg_name",
        translation_key="cfg_name",
        field=CONF_NAME,
        native_min=1,
        native_max=60,
        value_fn=lambda med, _lang: med.name,
    ),
    MedicationTextDescription(
        key="cfg_times",
        translation_key="cfg_times",
        field=CONF_TIMES,
        native_max=120,
        value_fn=lambda med, _lang: format_times([t.strftime("%H:%M") for t in med.times]),
    ),
    MedicationTextDescription(
        key="cfg_dosage",
        translation_key="cfg_dosage",
        field=CONF_DOSAGE,
        native_max=60,
        value_fn=lambda med, _lang: med.dosage,
    ),
    MedicationTextDescription(
        key="cfg_weekdays",
        translation_key="cfg_weekdays",
        field=CONF_WEEKDAYS,
        native_max=60,
        value_fn=lambda med, lang: format_weekdays(med.weekdays, lang),
    ),
)

# Input fields for a new medication: (key, draft field, max length)
DRAFT_TEXTS = (
    ("new_name", CONF_NAME, 60),
    ("new_times", CONF_TIMES, 120),
    ("new_dosage", CONF_DOSAGE, 60),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PillReminderConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up text entities."""
    manager = entry.runtime_data
    async_add_entities(
        DraftText(manager, key, field, max_len) for key, field, max_len in DRAFT_TEXTS
    )
    for med in manager.medications.values():
        async_add_entities(
            (MedicationText(manager, med, desc) for desc in MEDICATION_TEXTS),
            config_subentry_id=med.id,
        )


class MedicationText(MedicationEntity, TextEntity):
    """Name, times, dosage or weekdays of a medication."""

    _attr_entity_category = EntityCategory.CONFIG
    entity_description: MedicationTextDescription

    def __init__(
        self, manager: ReminderManager, med: Medication, desc: MedicationTextDescription
    ) -> None:
        """Initialize."""
        super().__init__(manager, med, desc.key)
        self.entity_description = desc

    def _update_from_manager(self) -> None:
        language = (self.hass.config.language or "en").split("-")[0]
        self._attr_native_value = self.entity_description.value_fn(self.med, language)

    async def async_set_value(self, value: str) -> None:
        """Validate and store; the person reloads with the new schedule."""
        self.manager.async_update_medication(self.med.id, {self.entity_description.field: value})


class DraftText(PersonEntity, TextEntity):
    """Input field for a new medication."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, manager: ReminderManager, key: str, field: str, max_len: int) -> None:
        """Initialize."""
        super().__init__(manager, key)
        self._field = field
        self._attr_native_max = max_len

    def _update_from_manager(self) -> None:
        self._attr_native_value = self.manager.draft[self._field]

    async def async_set_value(self, value: str) -> None:
        """Remember the input until 'add medication' is pressed."""
        self.manager.draft[self._field] = value.strip()
        self._update_from_manager()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Attributes for dashboard filters."""
        return {"person": self.manager.person}
