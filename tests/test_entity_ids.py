"""Entity ids and filter attributes used by the dashboards must exist."""

from __future__ import annotations

from pathlib import Path
import re

from homeassistant.core import HomeAssistant
import pytest

from .conftest import setup

DASHBOARDS = Path(__file__).parent.parent / "dashboards"


@pytest.mark.parametrize(
    "dashboard", ["pill_reminder.yaml", "pill_reminder_plus.yaml", "../README.md"]
)
async def test_dashboard_entity_ids_exist(
    hass: HomeAssistant, berlin, phone_calls, entry, dashboard: str
) -> None:
    """Every entity referenced by an example dashboard exists (English instance)."""
    hass.config.language = "en"
    await setup(hass, entry)

    content = (DASHBOARDS / dashboard).read_text(encoding="utf-8")
    referenced = set(
        re.findall(
            r"\b((?:sensor|binary_sensor|button|switch|calendar|text|number)\.(?:anna|ramipril)_[a-z0-9_]+)",
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
