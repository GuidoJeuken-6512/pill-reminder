"""Diagnostics must not leak personal or health data."""

from __future__ import annotations

import json

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import Context, HomeAssistant
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.pill_reminder.const import (
    CONF_ESCALATION_ENABLED,
    CONF_ESCALATION_SERVICES,
    CONF_USER_ID,
)
from custom_components.pill_reminder.diagnostics import async_get_config_entry_diagnostics

from .conftest import MED_ID, local, make_entry


async def test_diagnostics_are_redacted(
    hass: HomeAssistant,
    berlin: FrozenDateTimeFactory,
    phone_calls,
    care_calls,
    hass_admin_user,
) -> None:
    """Names, user ids, phones, medication names and dosages are redacted."""
    user_id = hass_admin_user.id
    entry = make_entry(
        options={CONF_ESCALATION_ENABLED: True, CONF_ESCALATION_SERVICES: ["mobile_app_care"]}
    )
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, unique_id=user_id, data={**entry.data, CONF_USER_ID: user_id}
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # 08:00 dose taken by the user, 20:00 dose open and snoozed by the user
    context = Context(user_id=user_id)
    for when, button in ((local(8, 0, 1), "taken"), (local(20, 0, 1), "snooze")):
        berlin.move_to(when)
        async_fire_time_changed(hass, when)
        await hass.async_block_till_done()
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": f"button.ramipril_{button}"},
            blocking=True,
            context=context,
        )
    assert entry.runtime_data.history.open_doses()[0].user_id == user_id

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    dumped = json.dumps(diagnostics)

    for secret in ("Anna", "Ramipril", "5 mg", user_id, "mobile_app_phone", "mobile_app_care"):
        assert secret not in dumped, f"{secret!r} leaks into diagnostics"

    # Still useful for debugging
    assert diagnostics["medications"][MED_ID]["times"] == ["08:00:00", "20:00:00"]
    assert [d["status"] for d in diagnostics["recent_doses"]] == ["taken", "snoozed"]
    assert diagnostics["open_doses"][0]["status"] == "snoozed"
