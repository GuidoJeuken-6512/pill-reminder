"""Config, options and subentry flow tests."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from custom_components.pill_reminder.const import (
    CONF_HEIGHT,
    CONF_NOTIFY_SERVICES,
    CONF_PERSON_NAME,
    CONF_TRACK_BODY,
    CONF_USER_ID,
    DOMAIN,
    SUBENTRY_MEASUREMENT,
)

from .conftest import SUB_WAIST, SUB_WEIGHT, make_entry, metric_subentry, setup


async def test_user_flow_creates_default_measurements(hass: HomeAssistant, phone_calls) -> None:
    """A person gets weight (daily) and waist (Mondays) right away."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_PERSON_NAME: " Anna ",
            CONF_HEIGHT: 172.5,
            CONF_USER_ID: "none",
            CONF_NOTIFY_SERVICES: ["notify.mobile_app_phone"],
        },
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Anna"
    assert result["data"] == {
        CONF_PERSON_NAME: "Anna",
        CONF_USER_ID: None,
        CONF_NOTIFY_SERVICES: ["mobile_app_phone"],
        CONF_HEIGHT: 172.5,
    }
    entry = result["result"]
    subs = {s.unique_id: s for s in entry.subentries.values()}
    assert set(subs) == {"weight", "waist"}
    assert subs["weight"].data["weekdays"] == [0, 1, 2, 3, 4, 5, 6]
    assert subs["waist"].data["weekdays"] == [0]
    assert subs["waist"].data["reminder_time"] == "07:00"
    assert subs["waist"].title == "Waist circumference"
    assert hass.states.get("number.anna_weight_enter") is not None

    # Same person again → abort
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PERSON_NAME: "Anna", CONF_USER_ID: "none", CONF_HEIGHT: 170}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_name_required(hass: HomeAssistant) -> None:
    """An empty name is rejected."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PERSON_NAME: "  ", CONF_USER_ID: "none", CONF_HEIGHT: 170}
    )
    assert result["errors"] == {CONF_PERSON_NAME: "name_required"}


async def test_reconfigure(hass: HomeAssistant, berlin, phone_calls) -> None:
    """Name and height can be changed."""
    entry = make_entry()
    await setup(hass, entry)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_PERSON_NAME: "Anna B.", CONF_USER_ID: "none", CONF_HEIGHT: 181},
    )
    await hass.async_block_till_done()
    assert result["reason"] == "reconfigure_successful"
    assert entry.title == "Anna B."
    assert entry.data[CONF_HEIGHT] == 181


async def test_options_flow(hass: HomeAssistant, berlin, phone_calls) -> None:
    """Repeat interval of measurement reminders and persistent notification."""
    entry = make_entry()
    await setup(hass, entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"measurement_repeat_interval": 60.0, "persistent_notification": True},
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["measurement_repeat_interval"] == 60
    assert entry.options["persistent_notification"] is True
    assert entry.runtime_data.body.repeat_interval.total_seconds() == 3600
    assert entry.runtime_data.body.persistent


async def test_person_without_measurements(hass: HomeAssistant, phone_calls) -> None:
    """Medication only: no measurement subentries, no body entities."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_PERSON_NAME: "Ben", CONF_USER_ID: "none", CONF_TRACK_BODY: False},
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_HEIGHT not in result["data"]
    entry = result["result"]
    assert not entry.subentries
    assert not entry.runtime_data.body.enabled
    assert hass.states.get("number.ben_height") is None
    assert hass.states.get("sensor.ben_bmi") is None
    assert hass.states.get("binary_sensor.ben_medication_due") is not None


async def test_subentry_add_and_edit(hass: HomeAssistant, berlin, phone_calls) -> None:
    """A removed type can be added again; the reminder can be edited."""
    entry = make_entry(subentries=[metric_subentry("sub_w", "weight", [0, 1, 2, 3, 4, 5, 6])])
    await setup(hass, entry)
    assert hass.states.get("number.anna_waist_enter") is None

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_MEASUREMENT), context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "metric": "waist",
            "reminder_enabled": True,
            "reminder_time": "08:15:00",
            "weekdays": ["6"],
        },
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert hass.states.get("number.anna_waist_enter") is not None
    assert hass.states.get("time.anna_waist_reminder_time").state == "08:15:00"

    # Blood pressure is the last one; then all types are tracked → abort
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_MEASUREMENT), context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"metric": "blood_pressure", "reminder_enabled": True, "reminder_time": "08:00"},
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert hass.states.get("number.anna_blood_pressure_systolic") is not None
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_MEASUREMENT), context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "all_tracked"

    # Edit the reminder
    waist = next(s for s in entry.subentries.values() if s.unique_id == "waist")
    result = await entry.start_subentry_reconfigure_flow(hass, waist.subentry_id)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"reminder_enabled": False, "reminder_time": "09:00", "weekdays": ["0", "3"]},
    )
    await hass.async_block_till_done()
    assert result["reason"] == "reconfigure_successful"
    assert hass.states.get("switch.anna_waist_reminder").state == "off"
    assert hass.states.get("text.anna_waist_reminder_weekdays").state == "Mon, Thu"


async def test_subentry_removed(hass: HomeAssistant, berlin, phone_calls) -> None:
    """Removing a type removes its entities, BMI stays; the last one removes BMI too."""
    entry = make_entry()
    await setup(hass, entry)
    assert hass.config_entries.async_remove_subentry(entry, SUB_WAIST)
    await hass.async_block_till_done()
    assert hass.states.get("number.anna_waist_enter") is None
    assert hass.states.get("number.anna_weight_enter") is not None
    assert hass.states.get("sensor.anna_bmi") is not None

    assert hass.config_entries.async_remove_subentry(entry, SUB_WEIGHT)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.anna_bmi") is None
    assert er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_bmi") is None
