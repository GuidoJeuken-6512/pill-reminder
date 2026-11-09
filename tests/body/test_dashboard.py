"""Body tab and measurement settings in the generated dashboard."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from custom_components.pill_reminder.const import CONF_USER_ID
from custom_components.pill_reminder.dashboard import async_build_dashboard

from .conftest import make_entry, setup

ENTITY_DOMAINS = ("sensor.", "binary_sensor.", "switch.", "text.", "number.", "time.")


def _entity_ids(node: Any) -> set[str]:
    """All entity ids referenced anywhere in a dashboard config."""
    if isinstance(node, dict):
        return set().union(*(_entity_ids(v) for v in node.values())) if node else set()
    if isinstance(node, list):
        return set().union(*(_entity_ids(v) for v in node)) if node else set()
    if isinstance(node, str) and node.startswith(ENTITY_DOMAINS):
        return {node}
    return set()


def _cards(view: dict) -> list[dict]:
    """All cards of a view."""
    return [card for section in view.get("sections", []) for card in section["cards"]]


async def test_body_tab(
    hass: HomeAssistant, berlin, phone_calls, hass_admin_user, hass_read_only_user
) -> None:
    """Medication, body and manage tab, visible to the person and administrators only."""
    hass.config.language = "de"
    await setup(hass, make_entry(**{CONF_USER_ID: hass_read_only_user.id}))

    config = await async_build_dashboard(hass)
    assert config["title"] == "Gesundheit"
    medication, body, manage = config["views"]
    assert [v["path"] for v in config["views"]] == ["anna", "anna-koerper", "anna-verwalten"]
    assert body["title"] == "Körper"
    assert manage["title"] == "Verwalten"
    visible = [v["user"] for v in body["visible"]]
    assert hass_read_only_user.id in visible
    assert hass_admin_user.id in visible
    assert body["visible"] == medication["visible"] == manage["visible"]

    body_ids = _entity_ids(body)
    assert {"number.anna_gewicht_eintragen", "sensor.anna_bmi"} <= body_ids
    manage_ids = _entity_ids(manage)
    assert "number.anna_korpergrosse" in manage_ids
    assert "time.anna_bauchumfang_erinnerungszeit" in manage_ids

    # every referenced entity exists
    missing = sorted(e for e in _entity_ids(config) if hass.states.get(e) is None)
    assert not missing, missing

    # the reminder opens the body tab
    entry = hass.config_entries.async_entries("pill_reminder")[0]
    assert entry.runtime_data.body.dashboard_url() == "/pill-reminder/anna-koerper"


async def test_body_without_values(hass: HomeAssistant, berlin, phone_calls, entry) -> None:
    """Without values no card shows an error: gauges and graphs need a number."""
    await setup(hass, entry)
    config = await async_build_dashboard(hass)
    body = config["views"][1]
    cards = _cards(body)
    gauges = [c for c in cards if c["type"] in ("gauge", "statistics-graph")]
    assert len(gauges) == 4  # BMI, WHtR, 2 graphs
    for card in gauges:
        assert card["visibility"][0]["condition"] == "numeric_state", card
    assert any(c["type"] == "markdown" and "first weight" in c["content"] for c in cards)
    # the missing-value hint follows the due sensor
    hints = [c for c in cards if c["type"] == "markdown" and "still missing" in c["content"]]
    assert hints[0]["visibility"][0]["entity"] == "binary_sensor.anna_weight_due"


async def test_no_body_tab_without_measurements(hass: HomeAssistant, berlin, phone_calls) -> None:
    """Medication only: no body tab; the manage tab offers to track measurements."""
    await setup(hass, make_entry(subentries=[]))
    config = await async_build_dashboard(hass)
    assert [v["path"] for v in config["views"]] == ["anna", "anna-manage"]
    manage_ids = _entity_ids(config["views"][1])
    assert {
        "switch.anna_track_weight",
        "switch.anna_track_waist_circumference",
        "switch.anna_track_blood_pressure",
    } <= manage_ids
    assert "number.anna_height" not in manage_ids


async def test_two_persons_unique_paths(hass: HomeAssistant, berlin, phone_calls) -> None:
    """Two persons get their own tabs and links."""
    await setup(hass, make_entry())
    ben = make_entry(name="Ben")
    await setup(hass, ben)
    config = await async_build_dashboard(hass)
    assert [v["path"] for v in config["views"]] == [
        "anna",
        "anna-body",
        "anna-manage",
        "ben",
        "ben-body",
        "ben-manage",
    ]
    assert config["views"][4]["title"] == "Body (Ben)"
    assert config["views"][5]["title"] == "Manage (Ben)"
    assert ben.runtime_data.body.dashboard_url() == "/pill-reminder/ben-body"
