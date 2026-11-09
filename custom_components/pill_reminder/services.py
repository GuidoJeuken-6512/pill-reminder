"""Service actions of the Pill Reminder integration (doses and measurements)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
    ATTR_DATE,
    ATTR_END,
    ATTR_MEASURED_AT,
    ATTR_METRIC,
    ATTR_START,
    ATTR_STATUS,
    ATTR_TAKEN_AT,
    ATTR_VALUE,
    CONF_METRIC,
    DOMAIN,
    SERVICE_ADD_MEASUREMENT,
    SERVICE_DELETE_MEASUREMENT,
    SERVICE_EXPORT_HISTORY,
    SERVICE_EXPORT_MEASUREMENTS,
    SERVICE_GET_HISTORY,
    SERVICE_GET_MEASUREMENTS,
    SERVICE_MARK_TAKEN,
    SERVICE_SKIP,
    SERVICE_SNOOZE,
    SOURCE_SERVICE,
    SUBENTRY_MEASUREMENT,
)
from .metrics import BLOOD_PRESSURE, METRICS
from .models import DoseRecord, DoseStatus

if TYPE_CHECKING:
    from .body import BodyTracker
    from .measurements import Measurement
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
    manager = _manager_for_entry(hass, entity.config_entry_id)
    if entity.config_subentry_id not in manager.medications:
        # e.g. an entity of a measurement (weight)
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="not_a_medication",
            translation_placeholders={"entity_id": entity_id},
        )
    return manager, entity.config_subentry_id


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


# ---------------------------------------------------------------- measurements

PERSON_FIELDS = {
    vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    vol.Optional(ATTR_ENTITY_ID): cv.entity_id,
}
METRIC_FIELD = vol.In(list(METRICS))

ADD_MEASUREMENT_SCHEMA = vol.Schema(
    {
        **PERSON_FIELDS,
        vol.Optional(ATTR_METRIC): METRIC_FIELD,
        # weight / waist
        vol.Optional(ATTR_VALUE): vol.Coerce(float),
        # blood pressure
        **{vol.Optional(field.key): vol.Coerce(float) for field in BLOOD_PRESSURE.fields},
        vol.Optional(ATTR_MEASURED_AT): cv.datetime,
    }
)
DELETE_MEASUREMENT_SCHEMA = vol.Schema(
    {
        **PERSON_FIELDS,
        vol.Optional(ATTR_METRIC): METRIC_FIELD,
        vol.Optional(ATTR_DATE): cv.date,
    }
)
MEASUREMENTS_SCHEMA = vol.Schema(
    {
        **PERSON_FIELDS,
        vol.Optional(ATTR_METRIC): METRIC_FIELD,
        vol.Optional(ATTR_START): cv.datetime,
        vol.Optional(ATTR_END): cv.datetime,
    }
)


def _resolve_person(hass: HomeAssistant, call: ServiceCall) -> tuple[BodyTracker, str | None]:
    """Person (and measurement type, if the entity belongs to one) of a call."""
    if entity_id := call.data.get(ATTR_ENTITY_ID):
        entity = er.async_get(hass).async_get(entity_id)
        if entity is None or entity.platform != DOMAIN or entity.config_entry_id is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="not_a_person_entity",
                translation_placeholders={"entity_id": entity_id},
            )
        body = _manager_for_entry(hass, entity.config_entry_id).body
        metric = None
        sub = body.entry.subentries.get(entity.config_subentry_id or "")
        if sub is not None and sub.subentry_type == SUBENTRY_MEASUREMENT:
            metric = sub.data.get(CONF_METRIC)
        return body, call.data.get(ATTR_METRIC) or metric
    if entry_id := call.data.get(ATTR_CONFIG_ENTRY_ID):
        return _manager_for_entry(hass, entry_id).body, call.data.get(ATTR_METRIC)
    loaded = hass.config_entries.async_loaded_entries(DOMAIN)
    if len(loaded) == 1:
        return loaded[0].runtime_data.body, call.data.get(ATTR_METRIC)
    raise ServiceValidationError(translation_domain=DOMAIN, translation_key="person_required")


def _required_metric(metric: str | None) -> str:
    if metric is None:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="metric_required")
    return metric


def _bodies(hass: HomeAssistant, call: ServiceCall) -> list[tuple[BodyTracker, str | None]]:
    """Persons selected by a measurement history call (all if none is given)."""
    if call.data.get(ATTR_ENTITY_ID) or call.data.get(ATTR_CONFIG_ENTRY_ID):
        return [_resolve_person(hass, call)]
    return [
        (entry.runtime_data.body, call.data.get(ATTR_METRIC))
        for entry in hass.config_entries.async_loaded_entries(DOMAIN)
    ]


def _measurements(call: ServiceCall, body: BodyTracker, metric: str | None) -> list[Measurement]:
    start = call.data.get(ATTR_START)
    end = call.data.get(ATTR_END)
    fields = {f.key for f in METRICS[metric].fields} if metric else None
    return [
        m
        for m in body.store.measurements(
            start=dt_util.as_utc(start) if start else None,
            end=dt_util.as_utc(end) if end else None,
        )
        if fields is None or m.metric in fields
    ]


@callback
def _async_setup_measurement_services(hass: HomeAssistant) -> None:
    """Register the measurement actions."""

    async def add_measurement(call: ServiceCall) -> ServiceResponse:
        body, metric_key = _resolve_person(hass, call)
        metric = METRICS[_required_metric(metric_key)]
        measured_at = call.data.get(ATTR_MEASURED_AT)
        if measured_at is not None and measured_at.tzinfo is None:
            measured_at = measured_at.replace(tzinfo=dt_util.get_default_time_zone())
        if metric.single:
            values = {metric.key: call.data.get(ATTR_VALUE)}
        else:
            values = {field.key: call.data.get(field.key) for field in metric.fields}
        stored = await body.async_add_values(
            metric.key, values, source=SOURCE_SERVICE, measured_at=measured_at
        )
        response: dict[str, Any] = {"measurements": [m.as_dict() for m in stored]}
        if metric.single:
            response["measurement"] = stored[0].as_dict()  # as in 0.4.0
        return response

    async def delete_measurement(call: ServiceCall) -> ServiceResponse:
        body, metric = _resolve_person(hass, call)
        removed = body.delete_measurements(_required_metric(metric), call.data.get(ATTR_DATE))
        return {"deleted": [m.as_dict() for m in removed]}

    async def get_measurements(call: ServiceCall) -> ServiceResponse:
        people: list[dict[str, Any]] = [
            {
                "config_entry_id": body.entry_id,
                "person": body.person,
                "height": body.height,
                "measurements": [m.as_dict() for m in _measurements(call, body, metric)],
            }
            for body, metric in _bodies(hass, call)
        ]
        return {"people": people}

    async def export_measurements(call: ServiceCall) -> ServiceResponse:
        stamp = dt_util.now().strftime("%Y%m%d_%H%M%S")
        files = []
        for body, metric in _bodies(hass, call):
            measurements = _measurements(call, body, metric)
            slug = "".join(c if c.isalnum() else "_" for c in body.person.lower())
            path = await body.store.async_export_csv(
                f"{slug}_measurements_{stamp}.csv", measurements
            )
            files.append({"person": body.person, "path": path, "count": len(measurements)})
        return {"files": files}

    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_MEASUREMENT,
        add_measurement,
        ADD_MEASUREMENT_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_MEASUREMENT,
        delete_measurement,
        DELETE_MEASUREMENT_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_MEASUREMENTS,
        get_measurements,
        MEASUREMENTS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_EXPORT_MEASUREMENTS,
        export_measurements,
        MEASUREMENTS_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register services (once, independent of config entries)."""
    _async_setup_measurement_services(hass)

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
