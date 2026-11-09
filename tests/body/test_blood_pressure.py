"""Blood pressure: several values per reading, save button, class, reminder."""

from __future__ import annotations

from datetime import timedelta
import json
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
import pytest

from custom_components.pill_reminder.const import DOMAIN
from custom_components.pill_reminder.dashboard import async_build_dashboard
from custom_components.pill_reminder.diagnostics import async_get_config_entry_diagnostics
from custom_components.pill_reminder.stats import blood_pressure_category

from .conftest import advance, advance_to, local, make_entry, metric_subentry, setup

BP = "sub_bp"
PREFIX = "anna_blood_pressure"


@pytest.fixture
def bp_entry():
    """Anna tracks her blood pressure daily at 07:00 (and her weight)."""
    return make_entry(
        subentries=[
            metric_subentry("sub_weight", "weight", [0, 1, 2, 3, 4, 5, 6]),
            metric_subentry(BP, "blood_pressure", [0, 1, 2, 3, 4, 5, 6]),
        ]
    )


async def _enter(hass: HomeAssistant, **values: float) -> None:
    for field, value in values.items():
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": f"number.{PREFIX}_{field}", "value": value},
            blocking=True,
        )


async def _save(hass: HomeAssistant) -> None:
    await hass.services.async_call(
        "button", "press", {"entity_id": f"button.{PREFIX}_save"}, blocking=True
    )
    await hass.async_block_till_done()


def _state(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    return state.state


@pytest.mark.parametrize(
    ("systolic", "diastolic", "expected"),
    [
        (115, 75, "optimal"),
        (125, 75, "normal"),
        (118, 82, "normal"),
        (135, 80, "high_normal"),
        (145, 80, "grade_1"),
        (130, 95, "grade_1"),
        (165, 85, "grade_2"),
        (185, 100, "grade_3"),
        (150, 112, "grade_3"),
    ],
)
def test_category(systolic: float, diastolic: float, expected: str) -> None:
    """The higher class of both values counts (ESC/ESH)."""
    assert blood_pressure_category(systolic, diastolic).value == expected


async def test_enter_and_save(hass: HomeAssistant, berlin, phone_calls, bp_entry) -> None:
    """Values are only stored with "Save"; the fields are empty again afterwards."""
    await setup(hass, bp_entry)
    events: list[Any] = []
    hass.bus.async_listen("pill_reminder_measurement_added", events.append)

    assert _state(hass, f"number.{PREFIX}_systolic") == "unknown"
    await _enter(hass, systolic=128, diastolic=82, pulse=64)
    assert _state(hass, f"number.{PREFIX}_systolic") == "128.0"
    assert _state(hass, f"sensor.{PREFIX}") == "unknown"  # not saved yet

    await _save(hass)
    assert _state(hass, f"sensor.{PREFIX}") == "128/82"
    assert _state(hass, f"sensor.{PREFIX}_category") == "normal"  # 128/82
    assert _state(hass, f"sensor.{PREFIX}_systolic") == "128.0"
    assert _state(hass, f"sensor.{PREFIX}_pulse") == "64.0"
    assert _state(hass, f"sensor.{PREFIX}_systolic_7_day_average") == "128.0"
    assert _state(hass, f"number.{PREFIX}_systolic") == "unknown"
    assert events[0].data["metric"] == "blood_pressure"
    assert events[0].data["values"] == {"systolic": 128.0, "diastolic": 82.0, "pulse": 64.0}

    # second reading without pulse: pulse is optional, average over both readings
    await _enter(hass, systolic=120, diastolic=78)
    await _save(hass)
    assert _state(hass, f"sensor.{PREFIX}") == "120/78"
    assert _state(hass, f"sensor.{PREFIX}_systolic_7_day_average") == "124.0"
    assert _state(hass, f"sensor.{PREFIX}_pulse") == "64.0"


async def test_invalid_input(hass: HomeAssistant, berlin, phone_calls, bp_entry) -> None:
    """Missing diastolic, systolic below diastolic and out of range are rejected."""
    await setup(hass, bp_entry)
    await _enter(hass, systolic=128)
    with pytest.raises(ServiceValidationError) as err:
        await _save(hass)
    assert err.value.translation_key == "value_required"

    await _enter(hass, diastolic=130)
    with pytest.raises(ServiceValidationError) as err:
        await _save(hass)
    assert err.value.translation_key == "systolic_not_above_diastolic"
    assert not hass.config_entries.async_entries(DOMAIN)[0].runtime_data.body.store.measurements()


async def test_weight_save_button(hass: HomeAssistant, berlin, phone_calls, bp_entry) -> None:
    """Weight: the field shows the last value, "Save" stores what is shown."""
    await setup(hass, bp_entry)
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.anna_weight_enter", "value": 81.4},
        blocking=True,
    )
    assert _state(hass, "sensor.anna_weight") == "unknown"
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.anna_weight_save"}, blocking=True
    )
    await hass.async_block_till_done()
    assert _state(hass, "sensor.anna_weight") == "81.4"
    assert _state(hass, "number.anna_weight_enter") == "81.4"

    # next day: "Save" without typing stores the same weight again
    await advance(hass, berlin, timedelta(days=1))
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.anna_weight_save"}, blocking=True
    )
    body = bp_entry.runtime_data.body
    assert [m.value for m in body.store.measurements("weight")] == [81.4, 81.4]


async def test_actions(hass: HomeAssistant, berlin, phone_calls, bp_entry) -> None:
    """add_measurement with systolic/diastolic, delete removes the whole reading."""
    await setup(hass, bp_entry)
    result = await hass.services.async_call(
        DOMAIN,
        "add_measurement",
        {"metric": "blood_pressure", "systolic": 142, "diastolic": 91, "pulse": 70},
        blocking=True,
        return_response=True,
    )
    assert [m["metric"] for m in result["measurements"]] == ["systolic", "diastolic", "pulse"]
    await hass.async_block_till_done()
    assert _state(hass, f"sensor.{PREFIX}_category") == "grade_1"

    history = await hass.services.async_call(
        DOMAIN,
        "get_measurements",
        {"metric": "blood_pressure"},
        blocking=True,
        return_response=True,
    )
    assert len(history["people"][0]["measurements"]) == 3

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "add_measurement", {"metric": "blood_pressure", "value": 120}, blocking=True
        )

    await hass.services.async_call(
        DOMAIN, "delete_measurement", {"metric": "blood_pressure"}, blocking=True
    )
    await hass.async_block_till_done()
    assert not bp_entry.runtime_data.body.store.measurements()
    assert _state(hass, f"sensor.{PREFIX}") == "unknown"


async def test_reminder_shows_last_reading(hass: HomeAssistant, berlin, phone_calls) -> None:
    """The reminder names the last reading, e.g. 128/82 mmHg."""
    entry = make_entry(subentries=[metric_subentry(BP, "blood_pressure", [0, 1, 2, 3, 4, 5, 6])])
    await setup(hass, entry)
    await entry.runtime_data.body.async_add_values(
        "blood_pressure",
        {"systolic": 128, "diastolic": 82},
        source="test",
        measured_at=local(7, day=1),
    )
    await advance_to(hass, berlin, local(7, 0) + timedelta(seconds=1))
    (call,) = [c for c in phone_calls if c.data["message"] != "clear_notification"]
    assert call.data["title"] == "🩺 Time to measure your blood pressure"
    assert "Last value: 128/82 mmHg (Nov 01)" in call.data["message"]
    assert _state(hass, f"binary_sensor.{PREFIX}_due") == "on"

    await _enter(hass, systolic=125, diastolic=80)
    await _save(hass)
    assert _state(hass, f"binary_sensor.{PREFIX}_due") == "off"


async def test_dashboard(hass: HomeAssistant, berlin, phone_calls, bp_entry) -> None:
    """Body tab: input card with save button, every referenced entity exists."""
    await setup(hass, bp_entry)
    config = await async_build_dashboard(hass)
    body = config["views"][1]
    cards = [c for section in body["sections"] for c in section["cards"]]
    bp_card = next(c for c in cards if c.get("title") == "Blood pressure")
    assert [r["entity"] for r in bp_card["entities"][:3]] == [
        f"number.{PREFIX}_systolic",
        f"number.{PREFIX}_diastolic",
        f"number.{PREFIX}_pulse",
    ]
    save = bp_card["entities"][3]
    assert save["tap_action"]["target"]["entity_id"] == f"button.{PREFIX}_save"

    def entity_ids(node: Any) -> set[str]:
        if isinstance(node, dict):
            return set().union(set(), *(entity_ids(v) for v in node.values()))
        if isinstance(node, list):
            return set().union(set(), *(entity_ids(v) for v in node))
        if (
            isinstance(node, str)
            and node.split(".")[0]
            in ("sensor", "binary_sensor", "number", "button", "switch", "time", "text")
            and "." in node
            and " " not in node
        ):
            return {node}
        return set()

    referenced = entity_ids(config) - {"button.press"}  # action name, not an entity
    missing = sorted(e for e in referenced if hass.states.get(e) is None)
    assert not missing, missing


async def test_diagnostics_without_values(
    hass: HomeAssistant, berlin, phone_calls, bp_entry
) -> None:
    """Diagnostics show counts and settings, but no blood pressure values."""
    await setup(hass, bp_entry)
    await _enter(hass, systolic=143, diastolic=97, pulse=71)
    await _save(hass)
    diagnostics = await async_get_config_entry_diagnostics(hass, bp_entry)
    dumped = json.dumps(diagnostics)
    for secret in ("143.0", "97.0", "71.0", "Anna", "mobile_app_phone"):
        assert secret not in dumped, f"{secret!r} leaks into diagnostics"
    assert diagnostics["measurements"]["blood_pressure"]["count"] == 1
