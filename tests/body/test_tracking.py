"""Add and remove measurements from the dashboard (track switches)."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.pill_reminder.const import SUBENTRY_MEASUREMENT

from .conftest import SUB_WEIGHT, make_entry, metric_subentry, setup


async def _switch(hass: HomeAssistant, entity_id: str, on: bool) -> None:
    await hass.services.async_call(
        "switch", "turn_on" if on else "turn_off", {"entity_id": entity_id}, blocking=True
    )
    await hass.async_block_till_done()


def _measurements(entry) -> list[str]:
    return sorted(
        s.data["metric"]
        for s in entry.subentries.values()
        if s.subentry_type == SUBENTRY_MEASUREMENT
    )


async def test_track_and_untrack(hass: HomeAssistant, berlin, phone_calls) -> None:
    """Switching on adds the measurement, switching off removes it; values stay."""
    entry = make_entry(subentries=[metric_subentry(SUB_WEIGHT, "weight", [0, 1, 2, 3, 4, 5, 6])])
    await setup(hass, entry)
    assert hass.states.get("switch.anna_track_weight").state == "on"
    assert hass.states.get("switch.anna_track_blood_pressure").state == "off"

    # add blood pressure: default reminder at 07:00 every day
    await _switch(hass, "switch.anna_track_blood_pressure", True)
    assert _measurements(entry) == ["blood_pressure", "weight"]
    bp = next(s for s in entry.subentries.values() if s.data.get("metric") == "blood_pressure")
    assert bp.title == "Blood pressure"
    assert bp.unique_id == "blood_pressure"
    assert bp.data["reminder_time"] == "07:00"
    assert hass.states.get("switch.anna_track_blood_pressure").state == "on"
    assert hass.states.get("number.anna_blood_pressure_systolic") is not None

    # remove weight: entities go, the stored value stays and comes back
    await entry.runtime_data.body.async_add_measurement("weight", 80.5, source="test")
    await _switch(hass, "switch.anna_track_weight", False)
    assert _measurements(entry) == ["blood_pressure"]
    assert hass.states.get("number.anna_weight_enter") is None
    assert hass.states.get("switch.anna_track_weight").state == "off"
    assert [m.value for m in entry.runtime_data.body.store.measurements("weight")] == [80.5]

    await _switch(hass, "switch.anna_track_weight", True)
    assert hass.states.get("sensor.anna_weight").state == "80.5"

    # switching on twice does not add a second subentry
    await _switch(hass, "switch.anna_track_weight", True)
    assert _measurements(entry) == ["blood_pressure", "weight"]


async def test_medication_only_person_starts_tracking(
    hass: HomeAssistant, berlin, phone_calls
) -> None:
    """A person without measurements gets BMI entities once weight is tracked."""
    entry = make_entry(subentries=[])
    await setup(hass, entry)
    assert hass.states.get("sensor.anna_bmi") is None
    await _switch(hass, "switch.anna_track_weight", True)
    assert hass.states.get("sensor.anna_bmi") is not None
    assert hass.states.get("number.anna_height") is not None

    await _switch(hass, "switch.anna_track_weight", False)
    assert hass.states.get("sensor.anna_bmi") is None
    assert hass.states.get("switch.anna_track_weight").state == "off"
