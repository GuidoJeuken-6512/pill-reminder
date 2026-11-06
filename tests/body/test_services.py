"""Actions: add (backfill), delete, history, CSV export, diagnostics."""

from __future__ import annotations

import json
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
import pytest

from custom_components.pill_reminder.const import DOMAIN, EVENT_MEASUREMENT_ADDED
from custom_components.pill_reminder.diagnostics import async_get_config_entry_diagnostics

from .conftest import local, make_entry, setup


async def _call(hass: HomeAssistant, service: str, data: dict, response: bool = True):
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=response
    )


async def test_add_backfill_and_delete(hass: HomeAssistant, berlin, phone_calls, entry) -> None:
    """Backfill with a date, by entry or by entity; delete by date or the last one."""
    events = []
    hass.bus.async_listen(EVENT_MEASUREMENT_ADDED, events.append)
    await setup(hass, entry)

    # Only one person: no target needed
    result = await _call(
        hass,
        "add_measurement",
        {"metric": "weight", "value": 82.3, "measured_at": "2026-10-30 07:15:00"},
    )
    assert result["measurement"]["value"] == 82.3
    assert result["measurement"]["source"] == "service"
    # Metric taken from the entity
    await _call(
        hass,
        "add_measurement",
        {"entity_id": "number.anna_waist_enter", "value": 91, "measured_at": local(7, day=1)},
    )
    await _call(
        hass,
        "add_measurement",
        {"config_entry_id": entry.entry_id, "metric": "weight", "value": 81.9},
    )
    await hass.async_block_till_done()
    assert [e.data["metric"] for e in events] == ["weight", "waist", "weight"]
    assert hass.states.get("sensor.anna_weight").state == "81.9"
    assert hass.states.get("sensor.anna_waist").state == "91.0"

    history = await _call(hass, "get_measurements", {"metric": "weight"})
    (person,) = history["people"]
    assert person["person"] == "Anna"
    assert [m["value"] for m in person["measurements"]] == [82.3, 81.9]

    # Delete the last weight → the backfilled one is the latest again
    deleted = await _call(hass, "delete_measurement", {"metric": "weight"})
    assert [m["value"] for m in deleted["deleted"]] == [81.9]
    await hass.async_block_till_done()
    assert hass.states.get("sensor.anna_weight").state == "82.3"

    # Delete by date
    await _call(
        hass, "delete_measurement", {"entity_id": "sensor.anna_waist", "date": "2026-11-01"}
    )
    await hass.async_block_till_done()
    assert hass.states.get("sensor.anna_waist").state == "unknown"

    with pytest.raises(ServiceValidationError):
        await _call(hass, "delete_measurement", {"metric": "waist"})
    with pytest.raises(ServiceValidationError):
        await _call(hass, "add_measurement", {"value": 80})  # metric missing
    with pytest.raises(ServiceValidationError):
        await _call(
            hass,
            "add_measurement",
            {"metric": "weight", "value": 80, "measured_at": "2026-11-05 07:00:00"},
        )


async def test_person_required_with_several(hass: HomeAssistant, berlin, phone_calls) -> None:
    """With two persons the target must be given."""
    await setup(hass, make_entry())
    await setup(hass, make_entry(name="Ben"))
    with pytest.raises(ServiceValidationError):
        await _call(hass, "add_measurement", {"metric": "weight", "value": 80})
    history = await _call(hass, "get_measurements", {})
    assert {p["person"] for p in history["people"]} == {"Anna", "Ben"}


async def test_export_csv(hass: HomeAssistant, berlin, phone_calls, entry) -> None:
    """CSV with semicolons in /config/pill_reminder/."""
    await setup(hass, entry)
    await entry.runtime_data.body.async_add_measurement("weight", 80.5, source="test")
    result = await _call(hass, "export_measurements", {"config_entry_id": entry.entry_id})
    (file,) = result["files"]
    assert file["count"] == 1
    content = Path(file["path"]).read_text(encoding="utf-8-sig")
    lines = content.strip().splitlines()
    assert lines[0] == "id;metric;value;measured_at;source"
    assert ";weight;80.5;2026-11-02T06:50:00+01:00;test" in lines[1]
    Path(file["path"]).unlink()


async def test_diagnostics(hass: HomeAssistant, berlin, phone_calls, entry) -> None:
    """Diagnostics contain no values, no height and no name."""
    await setup(hass, entry)
    await entry.runtime_data.body.async_add_measurement("weight", 80.5, source="test")
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["entry"]["data"]["height"] == "**REDACTED**"
    assert diag["entry"]["data"]["person_name"] == "**REDACTED**"
    assert diag["measurements"]["weight"]["count"] == 1
    assert diag["measurements"]["height_set"] is True
    dumped = json.dumps(diag)
    for secret in ("80.5", "180", "Anna", "mobile_app_phone"):
        assert secret not in dumped, f"{secret!r} leaks into diagnostics"
