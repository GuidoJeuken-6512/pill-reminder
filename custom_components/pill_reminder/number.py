"""Number entities (confirmation window) to set up medications from the dashboard."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PillReminderConfigEntry
from .const import CONF_EARLY_MINUTES, CONF_LATE_MINUTES
from .entity import MedicationEntity
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
