"""Fixtures for Pill Reminder tests."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant, ServiceCall
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.pill_reminder.const import (
    CONF_CREATED_AT,
    CONF_DOSAGE,
    CONF_EARLY_MINUTES,
    CONF_LATE_MINUTES,
    CONF_NAME,
    CONF_NOTIFY_SERVICES,
    CONF_PERSON_NAME,
    CONF_TIMES,
    CONF_USER_ID,
    CONF_WEEKDAYS,
    DOMAIN,
    SUBENTRY_MEDICATION,
)

TZ = ZoneInfo("Europe/Berlin")
MED_ID = "med_ramipril"


def local(hour: int, minute: int = 0, second: int = 0, day: int = 2) -> datetime:
    """A local (Berlin) datetime on Monday 2026-11-02."""
    return datetime(2026, 11, day, hour, minute, second, tzinfo=TZ)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading custom integrations."""


@pytest.fixture
async def berlin(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    """Use Berlin time and start on Monday 07:50."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(local(7, 50))
    return freezer


@pytest.fixture
def phone_calls(hass: HomeAssistant) -> list[ServiceCall]:
    """Calls to the person's phone."""
    return async_mock_service(hass, "notify", "mobile_app_phone")


@pytest.fixture
def care_calls(hass: HomeAssistant) -> list[ServiceCall]:
    """Calls to the escalation contact."""
    return async_mock_service(hass, "notify", "mobile_app_care")


def medication_data(**overrides: Any) -> dict[str, Any]:
    """Subentry data of a medication taken at 08:00 and 20:00."""
    data = {
        CONF_NAME: "Ramipril",
        CONF_DOSAGE: "5 mg",
        CONF_TIMES: ["08:00", "20:00"],
        CONF_WEEKDAYS: [0, 1, 2, 3, 4, 5, 6],
        CONF_EARLY_MINUTES: 30,
        CONF_LATE_MINUTES: 60,
        CONF_CREATED_AT: "2026-11-02T06:00:00+00:00",
    }
    data.update(overrides)
    return data


def make_entry(options: dict[str, Any] | None = None, **med_overrides: Any) -> MockConfigEntry:
    """Config entry for 'Anna' with one medication."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Anna",
        unique_id="anna",
        data={
            CONF_PERSON_NAME: "Anna",
            CONF_USER_ID: None,
            CONF_NOTIFY_SERVICES: ["mobile_app_phone"],
        },
        options=options or {},
        subentries_data=[
            ConfigSubentryData(
                data=medication_data(**med_overrides),
                subentry_id=MED_ID,
                subentry_type=SUBENTRY_MEDICATION,
                title="Ramipril",
                unique_id=None,
            )
        ],
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
