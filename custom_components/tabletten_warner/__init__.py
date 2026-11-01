"""Tabletten-Warner: medication reminders for Home Assistant."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.typing import ConfigType

from .const import CONF_PERSON_NAME, DOMAIN
from .history import DoseHistory
from .scheduler import ReminderManager
from .services import async_setup_services

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CALENDAR,
    Platform.SENSOR,
    Platform.SWITCH,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type TablettenWarnerConfigEntry = ConfigEntry[ReminderManager]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's services."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: TablettenWarnerConfigEntry) -> bool:
    """Set up one person."""
    manager = ReminderManager(hass, entry)
    await manager.async_start()
    entry.runtime_data = manager

    person_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.data[CONF_PERSON_NAME],
        manufacturer="Tabletten-Warner",
        model="Person",
        entry_type=dr.DeviceEntryType.SERVICE,
    )
    manager.person_device_id = person_device.id

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Medications (subentries) and options changes: reload to rebuild schedule.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: TablettenWarnerConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: TablettenWarnerConfigEntry) -> bool:
    """Unload a person."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: TablettenWarnerConfigEntry) -> None:
    """Delete stored history when a person is removed."""
    await DoseHistory(hass, entry.entry_id).async_remove()
