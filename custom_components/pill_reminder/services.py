"""Service actions of the Pill Reminder integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_END,
    ATTR_START,
    ATTR_STATUS,
    ATTR_TAKEN_AT,
    DOMAIN,
    SERVICE_EXPORT_HISTORY,
    SERVICE_GET_HISTORY,
    SERVICE_MARK_TAKEN,
    SERVICE_SKIP,
    SERVICE_SNOOZE,
    SOURCE_SERVICE,
)
from .models import DoseRecord, DoseStatus

if TYPE_CHECKING:
    from .scheduler import ReminderManager

ATTR_MINUTES = "minutes"

MEDICATION_SCHEMA = vol.Schema({vol.Required(ATTR_ENTITY_ID): cv.entity_id})

MARK_TAKEN_SCHEMA = MEDICATION_SCHEMA.extend({vol.Optional(ATTR_TAKEN_AT): cv.datetime})
SNOOZE_SCHEMA = MEDICATION_SCHEMA.extend(
    {vol.Optional(ATTR_MINUTES): vol.All(vol.Coerce(int), vol.Range(min=1, max=720))}
)
HISTORY_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(ATTR_ENTITY_ID): cv.entity_id,
        vol.Optional(ATTR_START): cv.datetime,
        vol.Optional(ATTR_END): cv.datetime,
        vol.Optional(ATTR_STATUS): vol.All(cv.ensure_list, [vol.In([s.value for s in DoseStatus])]),
    }
)


def _manager_for_entry(hass: HomeAssistant, entry_id: str) -> ReminderManager:
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="entry_not_loaded")
    return entry.runtime_data


def _resolve_medication(hass: HomeAssistant, entity_id: str) -> tuple[ReminderManager, str]:
    """Map any medication entity to (manager, medication id)."""
    entity = er.async_get(hass).async_get(entity_id)
    if (
        entity is None
        or entity.platform != DOMAIN
        or entity.config_entry_id is None
        or entity.config_subentry_id is None
    ):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="not_a_medication",
            translation_placeholders={"entity_id": entity_id},
        )
    return _manager_for_entry(hass, entity.config_entry_id), entity.config_subentry_id


def _managers(hass: HomeAssistant, call: ServiceCall) -> list[tuple[ReminderManager, str | None]]:
    """Managers (and optional medication filter) selected by a history call."""
    if entity_id := call.data.get(ATTR_ENTITY_ID):
        manager, med_id = _resolve_medication(hass, entity_id)
        return [(manager, med_id)]
    if entry_id := call.data.get(ATTR_CONFIG_ENTRY_ID):
        return [(_manager_for_entry(hass, entry_id), None)]
    return [
        (entry.runtime_data, None) for entry in hass.config_entries.async_loaded_entries(DOMAIN)
    ]


def _filtered(call: ServiceCall, manager: ReminderManager, med_id: str | None) -> list[DoseRecord]:
    start = call.data.get(ATTR_START)
    end = call.data.get(ATTR_END)
    statuses = call.data.get(ATTR_STATUS)
    return manager.history.records(
        start=dt_util.as_utc(start) if start else None,
        end=dt_util.as_utc(end) if end else None,
        medication_id=med_id,
        statuses={DoseStatus(s) for s in statuses} if statuses else None,
    )


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register services (once, independent of config entries)."""

    async def mark_taken(call: ServiceCall) -> None:
        manager, med_id = _resolve_medication(hass, call.data[ATTR_ENTITY_ID])
        await manager.async_take(
            med_id,
            source=SOURCE_SERVICE,
            user_id=call.context.user_id,
            taken_at=call.data.get(ATTR_TAKEN_AT),
        )

    async def snooze(call: ServiceCall) -> None:
        manager, med_id = _resolve_medication(hass, call.data[ATTR_ENTITY_ID])
        await manager.async_snooze(
            med_id,
            minutes=call.data.get(ATTR_MINUTES),
            source=SOURCE_SERVICE,
            user_id=call.context.user_id,
        )

    async def skip(call: ServiceCall) -> None:
        manager, med_id = _resolve_medication(hass, call.data[ATTR_ENTITY_ID])
        await manager.async_skip(med_id, source=SOURCE_SERVICE, user_id=call.context.user_id)

    async def get_history(call: ServiceCall) -> ServiceResponse:
        people = []
        for manager, med_id in _managers(hass, call):
            records = _filtered(call, manager, med_id)
            people.append(
                {
                    "config_entry_id": manager.entry_id,
                    "person": manager.person,
                    "doses": [r.as_dict() for r in records],
                }
            )
        return {"people": people}

    async def export_history(call: ServiceCall) -> ServiceResponse:
        stamp = dt_util.now().strftime("%Y%m%d_%H%M%S")
        files = []
        for manager, med_id in _managers(hass, call):
            records = _filtered(call, manager, med_id)
            slug = "".join(c if c.isalnum() else "_" for c in manager.person.lower())
            path = await manager.history.async_export_csv(f"{slug}_{stamp}.csv", records)
            files.append({"person": manager.person, "path": path, "doses": len(records)})
        return {"files": files}

    hass.services.async_register(DOMAIN, SERVICE_MARK_TAKEN, mark_taken, MARK_TAKEN_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_SNOOZE, snooze, SNOOZE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_SKIP, skip, MEDICATION_SCHEMA)
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_HISTORY,
        get_history,
        HISTORY_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_EXPORT_HISTORY,
        export_history,
        HISTORY_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
