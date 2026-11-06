"""Fixtures for Pill Reminder body measurement tests."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant, ServiceCall
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.pill_reminder.const import (
    CONF_HEIGHT,
    CONF_METRIC,
    CONF_NOTIFY_SERVICES,
    CONF_PERSON_NAME,
    CONF_REMINDER_ENABLED,
    CONF_REMINDER_TIME,
    CONF_USER_ID,
    CONF_WEEKDAYS,
    DOMAIN,
    SUBENTRY_MEASUREMENT,
)

TZ = ZoneInfo("Europe/Berlin")
SUB_WEIGHT = "sub_weight"
SUB_WAIST = "sub_waist"


def local(hour: int, minute: int = 0, day: int = 2) -> datetime:
    """A local (Berlin) datetime; 2026-11-02 is a Monday."""
    return datetime(2026, 11, day, hour, minute, tzinfo=TZ)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading custom integrations."""


@pytest.fixture
async def berlin(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    """Use Berlin time and start on Monday 06:50."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(local(6, 50))
    return freezer


@pytest.fixture
def phone_calls(hass: HomeAssistant) -> list[ServiceCall]:
    """Calls to the person's phone."""
    return async_mock_service(hass, "notify", "mobile_app_phone")


def metric_subentry(
    subentry_id: str, metric: str, weekdays: list[int], **overrides: Any
) -> ConfigSubentryData:
    """Subentry of a tracked measurement type with a reminder at 07:00."""
    data = {
        CONF_METRIC: metric,
        CONF_REMINDER_ENABLED: True,
        CONF_REMINDER_TIME: "07:00",
        CONF_WEEKDAYS: weekdays,
    }
    data.update(overrides)
    return ConfigSubentryData(
        data=data,
        subentry_id=subentry_id,
        subentry_type=SUBENTRY_MEASUREMENT,
        title=metric.capitalize(),
        unique_id=metric,
    )


def make_entry(
    *,
    options: dict[str, Any] | None = None,
    subentries: list[ConfigSubentryData] | None = None,
    name: str = "Anna",
    **data: Any,
) -> MockConfigEntry:
    """Config entry for a person, 180 cm, weight daily and waist on Mondays."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=name,
        unique_id=name.lower(),
        data={
            CONF_PERSON_NAME: name,
            CONF_USER_ID: None,
            CONF_NOTIFY_SERVICES: ["mobile_app_phone"],
            CONF_HEIGHT: 180.0,
            **data,
        },
        options=options or {},
        subentries_data=(
            subentries
            if subentries is not None
            else [
                metric_subentry(SUB_WEIGHT, "weight", [0, 1, 2, 3, 4, 5, 6]),
                metric_subentry(SUB_WAIST, "waist", [0]),
            ]
        ),
    )


@pytest.fixture
def entry() -> MockConfigEntry:
    """Default entry."""
    return make_entry()


async def setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add and set up an entry."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def advance(hass: HomeAssistant, freezer: FrozenDateTimeFactory, delta: timedelta) -> None:
    """Move time forward and run timers."""
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def advance_to(hass: HomeAssistant, freezer: FrozenDateTimeFactory, when: datetime) -> None:
    """Move time to a point and run timers."""
    freezer.move_to(when)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
