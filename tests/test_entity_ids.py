"""Entity ids and filter attributes used by the dashboards must exist."""

from __future__ import annotations

from pathlib import Path
import re

from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
import pytest

from .body.conftest import metric_subentry
from .conftest import setup

DASHBOARDS = Path(__file__).parent.parent / "dashboards"


@pytest.mark.parametrize(
    "dashboard",
    ["pill_reminder.yaml", "pill_reminder_plus.yaml", "../README.md", "../docs/user-guide.md"],
)
async def test_dashboard_entity_ids_exist(
    hass: HomeAssistant, berlin, phone_calls, entry, dashboard: str
) -> None:
    """Every entity referenced by an example dashboard exists (English instance).

    Anna takes Ramipril and tracks weight and waist.
    """
    hass.config.language = "en"
    entry.add_to_hass(hass)
    for metric, weekdays in (
        ("weight", [0, 1, 2, 3, 4, 5, 6]),
        ("waist", [0]),
        ("blood_pressure", [0, 1, 2, 3, 4, 5, 6]),
    ):
        sub = metric_subentry(f"sub_{metric}", metric, weekdays)
        hass.config_entries.async_add_subentry(
            entry,
            ConfigSubentry(
                data=sub["data"],
                subentry_type=sub["subentry_type"],
                title=sub["title"],
                unique_id=sub["unique_id"],
            ),
        )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    content = (DASHBOARDS / dashboard).read_text(encoding="utf-8")
    referenced = set(
        re.findall(
            r"\b((?:sensor|binary_sensor|button|switch|calendar|text|number|time)\.(?:anna|ramipril)_[a-z0-9_]+)",
            content,
        )
    )
    assert referenced
    missing = sorted(e for e in referenced if hass.states.get(e) is None)
    assert not missing, f"missing: {missing}; existing: {sorted(hass.states.async_entity_ids())}"


async def test_auto_entities_filter_attributes(
    hass: HomeAssistant, berlin, phone_calls, entry
) -> None:
    """Filter attributes (person, medication, due, actionable) are set."""
    hass.config.language = "de"
    await setup(hass, entry)

    def matching(domain: str, **attrs) -> list[str]:
        return sorted(
            s.entity_id
            for s in hass.states.async_all(domain)
            if all(s.attributes.get(k) == v for k, v in attrs.items())
        )

    assert matching("sensor", person="Anna", device_class="enum") == ["sensor.ramipril_status"]
    assert [e for e in matching("sensor", person="Anna", unit_of_measurement="%") if "7" in e] == [
        "sensor.ramipril_einnahmetreue_7_tage"
    ]
    # 07:50: the 08:00 dose may be confirmed early, but is not due yet
    assert matching("button", person="Anna", actionable=True) == ["button.ramipril_eingenommen"]
    assert matching("button", person="Anna", due=True) == []
