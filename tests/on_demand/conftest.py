"""Fixtures for on-demand medication tests."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigSubentryData
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pill_reminder.const import (
    CONF_DOSAGE,
    CONF_MAX_DAYS_PER_MONTH,
    CONF_MAX_PER_DAY,
    CONF_NAME,
    CONF_NOTIFY_SERVICES,
    CONF_PERSON_NAME,
    CONF_USER_ID,
    DOMAIN,
    SUBENTRY_ON_DEMAND,
)

SUB_SUMA = "sub_sumatriptan"


def on_demand_subentry(
    subentry_id: str = SUB_SUMA, name: str = "Sumatriptan", **overrides: Any
) -> ConfigSubentryData:
    """Subentry of an on-demand medication: at most 3 days a month, 2 a day."""
    data = {
        CONF_NAME: name,
        CONF_DOSAGE: "50 mg",
        CONF_MAX_DAYS_PER_MONTH: 3,
        CONF_MAX_PER_DAY: 2,
    }
    data.update(overrides)
    return ConfigSubentryData(
        data=data,
        subentry_id=subentry_id,
        subentry_type=SUBENTRY_ON_DEMAND,
        title=name,
        unique_id=None,
    )


def make_on_demand_entry(**overrides: Any) -> MockConfigEntry:
    """Anna with one on-demand medication (no scheduled medication, no measurements)."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Anna",
        unique_id="anna",
        data={
            CONF_PERSON_NAME: "Anna",
            CONF_USER_ID: None,
            CONF_NOTIFY_SERVICES: ["mobile_app_phone"],
        },
        subentries_data=[on_demand_subentry(**overrides)],
    )


@pytest.fixture
def entry() -> MockConfigEntry:
    """Default entry of the on-demand tests."""
    return make_on_demand_entry()
