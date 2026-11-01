"""Config, options and subentry flow tests."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.tabletten_warner.const import (
    CONF_ESCALATION_ENABLED,
    CONF_ESCALATION_SERVICES,
    CONF_NOTIFY_SERVICES,
    CONF_PERSON_NAME,
    CONF_USER_ID,
    DOMAIN,
    SUBENTRY_MEDICATION,
)

from .conftest import MED_ID, make_entry, setup

MEDICATION_INPUT = {
    "name": "Metformin",
    "dosage": "500 mg",
    "times": ["07:00", "19:00:00"],
    "weekdays": ["0", "1", "2", "3", "4"],
    "early_minutes": 30,
    "late_minutes": 120,
}


async def test_user_flow(hass: HomeAssistant, phone_calls) -> None:
    """A person can be added."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_PERSON_NAME: " Anna ",
            CONF_USER_ID: "__none__",
            CONF_NOTIFY_SERVICES: ["notify.mobile_app_phone"],
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Anna"
    assert result["data"] == {
        CONF_PERSON_NAME: "Anna",
        CONF_USER_ID: None,
        CONF_NOTIFY_SERVICES: ["mobile_app_phone"],
    }

    # Same person again → abort
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PERSON_NAME: "Anna", CONF_USER_ID: "__none__"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow(hass: HomeAssistant, berlin, phone_calls) -> None:
    """Escalation needs a contact."""
    entry = make_entry()
    await setup(hass, entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    base = {
        "repeat_interval": 5,
        "max_reminders": 4,
        "snooze_minutes": 10,
        "time_sensitive": True,
        "persistent_notification": False,
        "escalate_after": 2,
        "notify_missed": True,
        "retention_days": 90,
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**base, CONF_ESCALATION_ENABLED: True, CONF_ESCALATION_SERVICES: []}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_ESCALATION_SERVICES: "escalation_target_required"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {**base, CONF_ESCALATION_ENABLED: True, CONF_ESCALATION_SERVICES: ["mobile_app_care"]},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options["repeat_interval"] == 5
    assert entry.runtime_data.repeat_interval.total_seconds() == 300


async def test_medication_subentry(hass: HomeAssistant, berlin, phone_calls) -> None:
    """Medications are added and edited as subentries."""
    entry = make_entry()
    await setup(hass, entry)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_MEDICATION),
        context={"source": config_entries.SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**MEDICATION_INPUT, "times": ["07:00", "08:00"]}
    )
    assert result["errors"] == {"base": "windows_overlap"}

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**MEDICATION_INPUT, "times": ["7 Uhr"]}
    )
    assert result["errors"] == {"times": "invalid_time"}

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], MEDICATION_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    manager = entry.runtime_data  # reloaded
    names = sorted(m.name for m in manager.medications.values())
    assert names == ["Metformin", "Ramipril"]
    assert hass.states.get("button.metformin_taken") is not None

    # Edit Ramipril
    result = await entry.start_subentry_reconfigure_flow(hass, MED_ID)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {**MEDICATION_INPUT, "name": "Ramipril", "times": ["09:00"]},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    med = entry.runtime_data.medications[MED_ID]
    assert [t.strftime("%H:%M") for t in med.times] == ["09:00"]
    assert entry.subentries[MED_ID].data["created_at"] == "2026-11-02T06:00:00+00:00"
