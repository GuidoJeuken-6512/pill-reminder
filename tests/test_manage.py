"""Editing, adding and deleting medications from the dashboard."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
import pytest

from custom_components.pill_reminder.const import DOMAIN
from custom_components.pill_reminder.validation import (
    MedicationInvalid,
    format_weekdays,
    parse_weekdays,
)

from .conftest import MED_ID, setup


def _eid(hass: HomeAssistant, domain: str, unique_id: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)
    assert entity_id, f"{domain} {unique_id} missing"
    return entity_id


async def _set_text(hass: HomeAssistant, entity_id: str, value: str) -> None:
    await hass.services.async_call(
        "text", "set_value", {"entity_id": entity_id, "value": value}, blocking=True
    )
    await hass.async_block_till_done()


async def _press(hass: HomeAssistant, entity_id: str) -> None:
    await hass.services.async_call("button", "press", {"entity_id": entity_id}, blocking=True)
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("täglich", [0, 1, 2, 3, 4, 5, 6]),
        ("Mo-Fr", [0, 1, 2, 3, 4]),
        ("Mo, Mi, Fr", [0, 2, 4]),
        ("Montag; Sonntag", [0, 6]),
        ("Sa-Mo", [0, 5, 6]),
        ("Mon-Fri", [0, 1, 2, 3, 4]),
        ("daily", [0, 1, 2, 3, 4, 5, 6]),
    ],
)
def test_parse_weekdays(text: str, expected: list[int]) -> None:
    """Weekdays can be typed in German or English."""
    assert parse_weekdays(text) == expected


def test_parse_weekdays_invalid() -> None:
    """Unknown words are rejected."""
    with pytest.raises(MedicationInvalid):
        parse_weekdays("Feiertag")


def test_format_weekdays() -> None:
    """Ranges are collapsed."""
    assert format_weekdays([0, 1, 2, 3, 4], "de") == "Mo-Fr"
    assert format_weekdays([0, 2, 4], "de") == "Mo, Mi, Fr"
    assert format_weekdays([0, 1, 2, 3, 4, 5, 6], "de") == "täglich"
    assert format_weekdays([5, 6], "en") == "Sat, Sun"


async def test_edit_medication(hass: HomeAssistant, berlin, phone_calls, entry) -> None:
    """Times, weekdays and windows can be changed; the schedule follows."""
    await setup(hass, entry)
    times = _eid(hass, "text", f"{MED_ID}_cfg_times")
    weekdays = _eid(hass, "text", f"{MED_ID}_cfg_weekdays")
    assert hass.states.get(times).state == "08:00, 20:00"

    await _set_text(hass, times, "21:00; 9:00")
    assert entry.subentries[MED_ID].data["times"] == ["09:00", "21:00"]
    med = entry.runtime_data.medications[MED_ID]  # reloaded
    assert [t.strftime("%H:%M") for t in med.times] == ["09:00", "21:00"]
    assert hass.states.get(times).state == "09:00, 21:00"
    # created_at is kept (no false "missed" doses after a change)
    assert entry.subentries[MED_ID].data["created_at"] == "2026-11-02T06:00:00+00:00"

    await _set_text(hass, weekdays, "Mo-Fr")
    assert entry.subentries[MED_ID].data["weekdays"] == [0, 1, 2, 3, 4]
    assert hass.states.get(weekdays).state == "Mon-Fri"

    await _set_text(hass, _eid(hass, "text", f"{MED_ID}_cfg_name"), "Ramipril neu")
    assert entry.subentries[MED_ID].title == "Ramipril neu"


async def test_edit_rejects_invalid_input(hass: HomeAssistant, berlin, phone_calls, entry) -> None:
    """Invalid input is refused with a readable error and nothing changes."""
    await setup(hass, entry)
    times = _eid(hass, "text", f"{MED_ID}_cfg_times")

    with pytest.raises(ServiceValidationError) as err:
        await _set_text(hass, times, "25:00")
    assert err.value.translation_key == "invalid_time"

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": _eid(hass, "number", f"{MED_ID}_cfg_late_minutes"), "value": 720},
            blocking=True,
        )
    assert err.value.translation_key == "windows_overlap"
    assert entry.subentries[MED_ID].data["times"] == ["08:00", "20:00"]


async def test_add_and_delete_medication(hass: HomeAssistant, berlin, phone_calls, entry) -> None:
    """New medications are created from the input fields; delete keeps history."""
    await setup(hass, entry)
    eid = entry.entry_id
    add = _eid(hass, "button", f"{eid}_add_medication")

    with pytest.raises(ServiceValidationError) as err:
        await _press(hass, add)
    assert err.value.translation_key == "name_required"

    await _set_text(hass, _eid(hass, "text", f"{eid}_new_name"), "Metformin")
    await _set_text(hass, _eid(hass, "text", f"{eid}_new_times"), "07:00, 19:00")
    await _set_text(hass, _eid(hass, "text", f"{eid}_new_dosage"), "500 mg")
    await _press(hass, add)

    (new_id,) = [s for s in entry.subentries if s != MED_ID]
    assert entry.subentries[new_id].data["times"] == ["07:00", "19:00"]
    assert entry.subentries[new_id].data["dosage"] == "500 mg"
    assert hass.states.get(_eid(hass, "button", f"{new_id}_taken")) is not None
    # input fields are empty again
    assert hass.states.get(_eid(hass, "text", f"{eid}_new_name")).state == ""

    # take the Ramipril dose, then delete Ramipril: history stays
    await _press(hass, _eid(hass, "button", f"{MED_ID}_taken"))
    await _press(hass, _eid(hass, "button", f"{MED_ID}_delete_medication"))
    assert MED_ID not in entry.subentries
    assert list(entry.runtime_data.medications) == [new_id]
    assert [r.medication_name for r in entry.runtime_data.history.records()] == ["Ramipril"]
