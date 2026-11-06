"""Tests for the generated dashboard."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pill_reminder.const import (
    CONF_NOTIFY_SERVICES,
    CONF_PERSON_NAME,
    CONF_USER_ID,
    DOMAIN,
)
from custom_components.pill_reminder.dashboard import (
    DASHBOARD_URL,
    PillReminderDashboard,
    async_build_dashboard,
)

from .conftest import make_entry

ENTITY_DOMAINS = (
    "sensor.",
    "binary_sensor.",
    "button.",
    "switch.",
    "calendar.",
    "text.",
    "number.",
)


def _entity_ids(node: Any) -> set[str]:
    """All entity ids referenced anywhere in a dashboard config."""
    if isinstance(node, dict):
        return set().union(*(_entity_ids(v) for v in node.values())) if node else set()
    if isinstance(node, list):
        return set().union(*(_entity_ids(v) for v in node)) if node else set()
    if isinstance(node, str) and node.startswith(ENTITY_DOMAINS) and node != "button.press":
        return {node}
    return set()


def _dashboard_calls(mock) -> list:
    """Panel registrations of our dashboard (other components register panels too)."""
    return [c for c in mock.call_args_list if c.args[1] == "lovelace"]


async def _setup_person(hass: HomeAssistant, user_id: str | None):
    entry = make_entry()
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_USER_ID: user_id})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.fixture
def lovelace(hass: HomeAssistant):
    """Pretend Lovelace and the frontend are loaded; capture panel calls."""
    hass.data[LOVELACE_DATA] = SimpleNamespace(dashboards={})
    hass.config.components.add("frontend")
    with (
        patch(
            "custom_components.pill_reminder.dashboard.frontend.async_register_built_in_panel"
        ) as register,
        patch("custom_components.pill_reminder.dashboard.frontend.async_remove_panel") as remove,
    ):
        yield SimpleNamespace(data=hass.data[LOVELACE_DATA], register=register, remove=remove)


async def test_view_per_person(
    hass: HomeAssistant, berlin, phone_calls, hass_admin_user, hass_read_only_user
) -> None:
    """One view per person, visible to the person and administrators only."""
    hass.config.language = "de"
    await _setup_person(hass, hass_read_only_user.id)

    config = await async_build_dashboard(hass)
    assert config["title"] == "Gesundheit"
    view, manage = config["views"]
    assert view["title"] == "Anna"
    assert view["path"] == "anna"
    visible = [v["user"] for v in view["visible"]]
    assert hass_read_only_user.id in visible
    assert hass_admin_user.id in visible

    # Separate tab to manage medication, same visibility
    assert manage["title"] == "Verwalten"
    assert manage["path"] == "anna-verwalten"
    assert manage["visible"] == view["visible"]
    manage_ids = _entity_ids(manage)
    assert "text.ramipril_einnahmezeiten" in manage_ids
    assert "button.anna_medikament_hinzufugen" in manage_ids
    assert not manage_ids & _entity_ids(view["sections"][-1])  # not in the overview

    referenced = _entity_ids(config)
    assert "button.ramipril_eingenommen" in referenced
    assert "calendar.anna_medikamente" in referenced
    missing = sorted(e for e in referenced if hass.states.get(e) is None)
    assert not missing, missing

    # "Take now" section only while something is due, button presses the right entity
    now_section = view["sections"][0]
    assert now_section["visibility"][0]["entity"] == "binary_sensor.anna_medikament_fallig"
    taken_tile = now_section["cards"][1]
    assert taken_tile["tap_action"]["target"]["entity_id"] == "button.ramipril_eingenommen"
    assert taken_tile["visibility"][0]["entity"] == "binary_sensor.ramipril_fallig"


async def test_no_persons_message(hass: HomeAssistant) -> None:
    """Without persons the dashboard explains how to start."""
    config = await async_build_dashboard(hass)
    assert "Pill Reminder" in config["views"][0]["cards"][0]["content"]


async def test_dashboard_registered_and_removed(
    hass: HomeAssistant, berlin, phone_calls, lovelace
) -> None:
    """The panel appears with the first person and disappears with the last."""
    entry = await _setup_person(hass, None)

    (call,) = _dashboard_calls(lovelace.register)
    assert call.kwargs["frontend_url_path"] == DASHBOARD_URL
    assert call.kwargs["require_admin"] is False
    dashboard = lovelace.data.dashboards[DASHBOARD_URL]
    assert isinstance(dashboard, PillReminderDashboard)
    assert (await dashboard.async_get_info())["views"] == 2

    # Reload (e.g. medication added) refreshes instead of registering again
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert len(_dashboard_calls(lovelace.register)) == 1

    # Unload keeps the dashboard, deleting the last person removes it
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert DASHBOARD_URL in lovelace.data.dashboards
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    lovelace.remove.assert_called()
    assert DASHBOARD_URL not in lovelace.data.dashboards


async def test_existing_dashboard_not_overwritten(
    hass: HomeAssistant, berlin, phone_calls, lovelace
) -> None:
    """A user dashboard on the same URL is left alone."""
    lovelace.data.dashboards[DASHBOARD_URL] = object()
    await _setup_person(hass, None)
    assert not _dashboard_calls(lovelace.register)


def _cards(config: dict) -> list[dict]:
    """All cards of all views and sections."""
    return [
        card
        for view in config["views"]
        for section in view.get("sections", [])
        for card in section["cards"]
    ]


async def test_person_without_medication(hass: HomeAssistant, berlin, phone_calls) -> None:
    """Without medication (adherence unknown) no card may show an error."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Anna",
        unique_id="anna",
        data={CONF_PERSON_NAME: "Anna", CONF_USER_ID: None, CONF_NOTIFY_SERVICES: []},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.anna_adherence_7_days").state == "unknown"

    config = await async_build_dashboard(hass)
    cards = _cards(config)
    # Gauges and the statistics graph only appear once there is a number
    for card in cards:
        if card["type"] in ("gauge", "statistics-graph"):
            assert card["visibility"][0]["condition"] == "numeric_state", card
    # ... a hint is shown instead
    assert any(c["type"] == "markdown" and "No adherence data yet" in c["content"] for c in cards)
    assert any(c["type"] == "markdown" and "No medication yet" in c["content"] for c in cards)
    # no card refers to an entity that does not exist
    missing = sorted(e for e in _entity_ids(config) if hass.states.get(e) is None)
    assert not missing, missing
