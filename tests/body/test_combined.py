"""A person with medication and body measurements in one entry."""

from __future__ import annotations

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
import pytest

from custom_components.pill_reminder.const import DOMAIN, SUBENTRY_MEDICATION

from ..conftest import medication_data
from .conftest import SUB_WEIGHT, make_entry, metric_subentry, setup

MED_ID = "med_ramipril"


@pytest.fixture
def combined():
    """Anna takes Ramipril and tracks her weight."""
    return make_entry(
        subentries=[
            ConfigSubentryData(
                data=medication_data(),
                subentry_id=MED_ID,
                subentry_type=SUBENTRY_MEDICATION,
                title="Ramipril",
                unique_id=None,
            ),
            metric_subentry(SUB_WEIGHT, "weight", [0, 1, 2, 3, 4, 5, 6]),
        ]
    )


async def test_both_work_side_by_side(hass: HomeAssistant, berlin, phone_calls, combined) -> None:
    """Medication and measurement entities exist; actions do not mix them up."""
    await setup(hass, combined)
    manager = combined.runtime_data
    assert list(manager.medications) == [MED_ID]
    assert list(manager.body.tracked) == [SUB_WEIGHT]
    for entity_id in (
        "button.ramipril_taken",
        "binary_sensor.anna_medication_due",
        "number.anna_weight_enter",
        "sensor.anna_bmi",
    ):
        assert hass.states.get(entity_id) is not None, entity_id

    # A weight entity is no medication ...
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "mark_taken", {"entity_id": "sensor.anna_weight"}, blocking=True
        )
    # ... but any entity of the person works for measurements
    await hass.services.async_call(
        DOMAIN,
        "add_measurement",
        {"entity_id": "button.ramipril_taken", "metric": "weight", "value": 81.0},
        blocking=True,
    )
    assert hass.states.get("sensor.anna_weight").state == "81.0"
    assert hass.states.get("sensor.anna_bmi").state == "25.0"


async def test_height_and_reminder_without_reload_medication_with_reload(
    hass: HomeAssistant, berlin, phone_calls, combined
) -> None:
    """Height and measurement reminders apply in place; a medication change reloads."""
    await setup(hass, combined)
    manager = combined.runtime_data

    await hass.services.async_call(
        "number", "set_value", {"entity_id": "number.anna_height", "value": 170}, blocking=True
    )
    await hass.services.async_call(
        "text",
        "set_value",
        {"entity_id": "text.anna_weight_reminder_weekdays", "value": "Mon-Fri"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert combined.runtime_data is manager
    assert manager.body.height == 170
    assert manager.body.tracked[SUB_WEIGHT].weekdays == (0, 1, 2, 3, 4)

    await hass.services.async_call(
        "text",
        "set_value",
        {"entity_id": "text.ramipril_intake_times", "value": "09:00, 21:00"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert combined.runtime_data is not manager
    assert combined.runtime_data.body.height == 170


async def test_existing_person_without_height(hass: HomeAssistant, berlin, phone_calls) -> None:
    """Persons from older versions have no height: BMI stays unknown until it is set."""
    entry = make_entry()
    entry.add_to_hass(hass)
    data = {k: v for k, v in entry.data.items() if k != "height"}
    hass.config_entries.async_update_entry(entry, data=data)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await entry.runtime_data.body.async_add_measurement("weight", 80.0, source="test")
    await hass.async_block_till_done()
    assert hass.states.get("number.anna_height").state == "unknown"
    assert hass.states.get("sensor.anna_bmi").state == "unknown"
