"""Calendar event tests."""

from __future__ import annotations

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from .conftest import local, setup

CALENDAR = "calendar.anna_medication"


async def _events(hass: HomeAssistant, start, end, calendar: str = CALENDAR) -> list[dict]:
    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {"entity_id": calendar, "start_date_time": start, "end_date_time": end},
        blocking=True,
        return_response=True,
    )
    return response[calendar]["events"]


async def test_calendar_describes_late_intake(
    hass: HomeAssistant, berlin: FrozenDateTimeFactory, phone_calls, entry
) -> None:
    """A late intake shows dosage, delay, reminders and source; it ends when taken."""
    await setup(hass, entry)
    when = local(8, 25)
    berlin.move_to(local(8, 0, 1))
    async_fire_time_changed(hass, local(8, 0, 1))
    await hass.async_block_till_done()
    berlin.move_to(when)
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.ramipril_taken"}, blocking=True
    )

    events = await _events(hass, local(0), local(23, 59))
    morning, evening = events
    assert morning["summary"] == "✅ Ramipril"
    description = morning["description"]
    assert "Dosage: 5 mg" in description
    assert "Scheduled: 08:00" in description
    assert "Taken at 08:25 (25 min late)" in description
    assert "Reminders: 1" in description
    assert "Confirmed via: button" in description
    assert morning["end"] == when.isoformat()

    assert evening["summary"] == "🕒 Ramipril"
    assert "Status: scheduled" in evening["description"]


async def test_calendar_german(
    hass: HomeAssistant, berlin: FrozenDateTimeFactory, phone_calls, entry
) -> None:
    """Descriptions follow the system language."""
    hass.config.language = "de"
    await setup(hass, entry)
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.ramipril_eingenommen"}, blocking=True
    )
    events = await _events(hass, local(0), local(12), "calendar.anna_medikamente")
    assert "Eingenommen um 07:50 (10 Min. früher)" in events[0]["description"]
    assert "Bestätigt über: Button" in events[0]["description"]
