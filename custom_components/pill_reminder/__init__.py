"""Pill Reminder: medication reminders and body measurements for Home Assistant."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.typing import ConfigType

from .const import CONF_HEIGHT, CONF_METRIC, CONF_PERSON_NAME, DOMAIN, SUBENTRY_MEASUREMENT
from .dashboard import async_update_dashboard
from .history import DoseHistory
from .measurements import MeasurementStore
from .scheduler import ReminderManager
from .services import async_setup_services

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CALENDAR,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TEXT,
    Platform.TIME,
]

# Person entities that only exist while the person tracks a measurement
BODY_PERSON_ENTITIES = ("height", "bmi", "bmi_category", "whtr", "whtr_category")

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type PillReminderConfigEntry = ConfigEntry[ReminderManager]


def config_signature(entry: ConfigEntry) -> tuple[Any, ...]:
    """Everything that needs a reload when changed.

    The height and the reminder settings of a measurement are applied without
    a reload, so editing them in the dashboard is instant.
    """
    subentries = []
    for sub_id, sub in entry.subentries.items():
        if sub.subentry_type == SUBENTRY_MEASUREMENT:
            subentries.append((sub_id, sub.subentry_type, sub.data.get(CONF_METRIC)))
        else:
            subentries.append(
                (sub_id, sub.subentry_type, sub.title, repr(sorted(sub.data.items())))
            )
    return (
        repr(sorted((k, v) for k, v in entry.data.items() if k != CONF_HEIGHT)),
        repr(sorted(entry.options.items())),
        frozenset(subentries),
    )


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's services."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: PillReminderConfigEntry) -> bool:
    """Set up one person."""
    manager = ReminderManager(hass, entry)
    await manager.async_start()
    entry.runtime_data = manager
    manager.signature = config_signature(entry)

    person_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.data[CONF_PERSON_NAME],
        manufacturer="Pill Reminder",
        model="Person",
        entry_type=dr.DeviceEntryType.SERVICE,
    )
    manager.person_device_id = person_device.id
    manager.body.person_device_id = person_device.id
    if not manager.body.enabled:
        _remove_body_person_entities(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    # Create the dashboard with the first person / refresh it for the others.
    async_update_dashboard(hass)
    return True


@callback
def _remove_body_person_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Height, BMI, ... are left over after the last measurement was removed."""
    registry = er.async_get(hass)
    for key in BODY_PERSON_ENTITIES:
        for domain in ("number", "sensor"):
            if entity_id := registry.async_get_entity_id(domain, DOMAIN, f"{entry.entry_id}_{key}"):
                registry.async_remove(entity_id)


async def _async_update_listener(hass: HomeAssistant, entry: PillReminderConfigEntry) -> None:
    """Reload for medications, options and structure; apply body settings in place."""
    manager = entry.runtime_data
    if config_signature(entry) != manager.signature:
        await hass.config_entries.async_reload(entry.entry_id)
    else:
        manager.body.async_apply_settings()


async def async_unload_entry(hass: HomeAssistant, entry: PillReminderConfigEntry) -> bool:
    """Unload a person."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
        # Refresh open dashboards (the person's view disappears while unloaded).
        async_update_dashboard(hass)
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: PillReminderConfigEntry) -> None:
    """Delete stored doses and measurements when a person is removed."""
    await DoseHistory(hass, entry.entry_id).async_remove()
    await MeasurementStore(hass, entry.entry_id).async_remove()
    # Remove the dashboard together with the last person.
    async_update_dashboard(hass, removed_entry_id=entry.entry_id)
