"""Entering values and the derived sensors."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util
import pytest

from .conftest import advance, local, make_entry, setup


async def set_number(hass: HomeAssistant, entity_id: str, value: float) -> None:
    """Enter a value and press "Save" like the dashboard does."""
    await hass.services.async_call(
        "number", "set_value", {"entity_id": entity_id, "value": value}, blocking=True
    )
    save = "button." + entity_id.split(".", 1)[1].replace("_enter", "_save")
    await hass.services.async_call("button", "press", {"entity_id": save}, blocking=True)
    await hass.async_block_till_done()


async def test_entities_and_devices(hass: HomeAssistant, berlin, phone_calls, entry) -> None:
    """Person device with BMI/WHtR, one device per measurement type."""
    await setup(hass, entry)
    for entity_id in (
        "number.anna_height",
        "sensor.anna_bmi",
        "sensor.anna_bmi_category",
        "sensor.anna_waist_to_height_ratio",
        "number.anna_weight_enter",
        "sensor.anna_weight",
        "sensor.anna_weight_measured",
        "sensor.anna_weight_change_7_days",
        "sensor.anna_weight_trend",
        "sensor.anna_weight_trend_direction",
        "binary_sensor.anna_weight_due",
        "switch.anna_weight_reminder",
        "time.anna_weight_reminder_time",
        "text.anna_weight_reminder_weekdays",
        "number.anna_waist_enter",
        "sensor.anna_waist",
    ):
        assert hass.states.get(entity_id) is not None, entity_id

    # Everything unknown until values exist
    assert hass.states.get("sensor.anna_bmi").state == "unknown"
    assert hass.states.get("sensor.anna_weight").state == "unknown"
    assert hass.states.get("number.anna_height").state == "180.0"
    assert hass.states.get("sensor.anna_weight_trend").attributes["unit_of_measurement"] == (
        "kg/week"
    )

    devices = dr.async_get(hass)
    weight_entity = er.async_get(hass).async_get("number.anna_weight_enter")
    weight_device = devices.async_get(weight_entity.device_id)
    person_device = devices.async_get(er.async_get(hass).async_get("number.anna_height").device_id)
    assert weight_device.name == "Anna Weight"
    assert weight_device.via_device_id == person_device.id
    assert weight_entity.config_subentry_id == "sub_weight"


async def test_enter_values(hass: HomeAssistant, berlin, phone_calls, entry) -> None:
    """A value updates last value, BMI and WHtR."""
    await setup(hass, entry)
    await set_number(hass, "number.anna_weight_enter", 81)
    assert hass.states.get("sensor.anna_weight").state == "81.0"
    assert hass.states.get("number.anna_weight_enter").state == "81.0"
    assert hass.states.get("sensor.anna_bmi").state == "25.0"
    assert hass.states.get("sensor.anna_bmi_category").state == "overweight"
    measured = dt_util.parse_datetime(hass.states.get("sensor.anna_weight_measured").state)
    assert measured == local(6, 50)
    assert hass.states.get("sensor.anna_waist_to_height_ratio").state == "unknown"

    await set_number(hass, "number.anna_waist_enter", 89.5)
    assert hass.states.get("sensor.anna_waist_to_height_ratio").state == "0.497"
    assert hass.states.get("sensor.anna_waist_to_height_category").state == "healthy"

    # The height changes BMI without a reload
    await set_number(hass, "number.anna_height", 170)
    assert entry.data["height"] == 170
    assert hass.states.get("sensor.anna_bmi").state == "28.0"

    with pytest.raises(ServiceValidationError):
        await entry.runtime_data.body.async_add_measurement("weight", 5, source="test")


async def test_change_and_trend(hass: HomeAssistant, berlin, phone_calls, entry) -> None:
    """Daily values (last of the day counts) give change and trend."""
    await setup(hass, entry)
    tracker = entry.runtime_data.body
    for days_ago in range(14, 0, -1):
        day = local(7, day=2) - timedelta(days=days_ago)
        await tracker.async_add_measurement("weight", 90.0, source="test", measured_at=day)
        # second value of the day wins
        await tracker.async_add_measurement(
            "weight", 85 - days_ago * 0.1, source="test", measured_at=day + timedelta(hours=12)
        )
    await advance(hass, berlin, timedelta(minutes=1))
    await set_number(hass, "number.anna_weight_enter", 85.0)

    # reference: last daily value at or before 7 days ago (Oct 25: 84.2)
    assert hass.states.get("sensor.anna_weight_change_7_days").state == "0.8"
    assert hass.states.get("sensor.anna_weight_trend_direction").state == "rising"
    assert float(hass.states.get("sensor.anna_weight_trend").state) == pytest.approx(0.7, abs=0.05)
    assert hass.states.get("sensor.anna_weight_change_30_days").state == "unknown"


async def test_reminder_settings_entities(hass: HomeAssistant, berlin, phone_calls, entry) -> None:
    """Reminder settings change in place (no reload)."""
    await setup(hass, entry)
    tracker = entry.runtime_data.body
    await hass.services.async_call(
        "time",
        "set_value",
        {"entity_id": "time.anna_waist_reminder_time", "time": "20:30"},
        blocking=True,
    )
    await hass.services.async_call(
        "text",
        "set_value",
        {"entity_id": "text.anna_waist_reminder_weekdays", "value": "Mo-Fr"},
        blocking=True,
    )
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.anna_waist_reminder"}, blocking=True
    )
    await hass.async_block_till_done()
    assert entry.runtime_data.body is tracker  # not reloaded
    waist = entry.subentries["sub_waist"].data
    assert waist["reminder_time"] == "20:30"
    assert waist["weekdays"] == [0, 1, 2, 3, 4]
    assert waist["reminder_enabled"] is False
    assert hass.states.get("text.anna_waist_reminder_weekdays").state == "Mon-Fri"
    assert hass.states.get("switch.anna_waist_reminder").state == "off"

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "text",
            "set_value",
            {"entity_id": "text.anna_waist_reminder_weekdays", "value": "Funday"},
            blocking=True,
        )


async def test_measurements_survive_restart(hass: HomeAssistant, berlin, phone_calls) -> None:
    """Values are stored."""
    entry = make_entry()
    await setup(hass, entry)
    await set_number(hass, "number.anna_weight_enter", 79.4)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.anna_weight").state == "79.4"
