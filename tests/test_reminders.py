"""Reminder lifecycle tests."""

from __future__ import annotations

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.pill_reminder.const import (
    CONF_ESCALATE_AFTER,
    CONF_ESCALATION_ENABLED,
    CONF_ESCALATION_SERVICES,
    CONF_MAX_REMINDERS,
    CONF_REPEAT_INTERVAL,
    DOMAIN,
    EVENT_DOSE_MISSED,
    EVENT_DOSE_TAKEN,
    EVENT_ESCALATED,
)
from custom_components.pill_reminder.models import DoseStatus

from .conftest import MED_ID, local, make_entry, setup

STATUS = "sensor.ramipril_status"
DUE = "binary_sensor.ramipril_due"
TAKEN = "button.ramipril_taken"
SNOOZE = "button.ramipril_snooze"
SKIP = "button.ramipril_skip"
SWITCH = "switch.ramipril_reminders"


async def _tick(hass: HomeAssistant, freezer: FrozenDateTimeFactory, when) -> None:
    freezer.move_to(when)
    async_fire_time_changed(hass, when)
    await hass.async_block_till_done()


def _reminders(calls: list[ServiceCall]) -> list[ServiceCall]:
    return [c for c in calls if c.data["message"] != "clear_notification"]


def _clears(calls: list[ServiceCall]) -> list[ServiceCall]:
    return [c for c in calls if c.data["message"] == "clear_notification"]


async def _press(hass: HomeAssistant, entity_id: str) -> None:
    await hass.services.async_call("button", "press", {"entity_id": entity_id}, blocking=True)


async def test_reminder_and_taken_button(
    hass: HomeAssistant, berlin: FrozenDateTimeFactory, phone_calls, entry
) -> None:
    """Dose becomes due, reminds, repeats and is acknowledged by the button."""
    taken_events = async_capture_events(hass, EVENT_DOSE_TAKEN)
    await setup(hass, entry)
    assert hass.states.get(STATUS).state == "scheduled"
    assert hass.states.get(DUE).state == "off"
    assert hass.states.get("sensor.anna_open_today").state == "2"

    await _tick(hass, berlin, local(8, 0, 1))
    assert hass.states.get(DUE).state == "on"
    assert hass.states.get(STATUS).state == "due"
    taken_attrs = hass.states.get(TAKEN).attributes
    assert taken_attrs["due"] is True
    assert taken_attrs["person"] == "Anna"
    assert taken_attrs["medication"] == "Ramipril"
    assert hass.states.get(STATUS).attributes["person"] == "Anna"
    assert len(_reminders(phone_calls)) == 1
    data = phone_calls[0].data
    assert "Ramipril" in data["title"]
    actions = [a["action"] for a in data["data"]["actions"]]
    assert actions[0].startswith("PR_TAKEN::")
    assert actions[1].startswith("PR_SNOOZE::")
    tag = data["data"]["tag"]

    await _tick(hass, berlin, local(8, 10, 2))
    assert len(_reminders(phone_calls)) == 2

    await _press(hass, TAKEN)
    await hass.async_block_till_done()
    assert hass.states.get(STATUS).state == "taken"
    assert hass.states.get(DUE).state == "off"
    assert hass.states.get("sensor.anna_open_today").state == "1"
    assert hass.states.get("sensor.anna_taken_today").state == "1"
    assert hass.states.get("sensor.anna_missed_today").state == "0"
    assert hass.states.get(TAKEN).attributes["due"] is False
    assert [c.data["data"]["tag"] for c in _clears(phone_calls)] == [tag]
    assert len(taken_events) == 1
    assert taken_events[0].data["source"] == "button"

    # No more reminders after acknowledgement
    await _tick(hass, berlin, local(8, 30, 3))
    assert len(_reminders(phone_calls)) == 2
    assert hass.states.get("sensor.ramipril_adherence_7_days").state == "100.0"
    next_dose = dt_util.parse_datetime(hass.states.get("sensor.ramipril_next_dose").state)
    assert next_dose == local(20)


async def test_escalation_and_missed(
    hass: HomeAssistant, berlin: FrozenDateTimeFactory, phone_calls, care_calls
) -> None:
    """Unacknowledged dose escalates and is logged as missed."""
    entry = make_entry(
        options={
            CONF_REPEAT_INTERVAL: 10,
            CONF_MAX_REMINDERS: 3,
            CONF_ESCALATION_ENABLED: True,
            CONF_ESCALATE_AFTER: 2,
            CONF_ESCALATION_SERVICES: ["mobile_app_care"],
        }
    )
    escalated = async_capture_events(hass, EVENT_ESCALATED)
    missed = async_capture_events(hass, EVENT_DOSE_MISSED)
    await setup(hass, entry)

    await _tick(hass, berlin, local(8, 0, 1))
    await _tick(hass, berlin, local(8, 10, 2))
    assert len(_reminders(phone_calls)) == 2
    assert not care_calls

    await _tick(hass, berlin, local(8, 20, 3))
    assert len(escalated) == 1
    assert len(_reminders(care_calls)) == 1
    assert len(_reminders(phone_calls)) == 3

    await _tick(hass, berlin, local(8, 30, 4))
    await _tick(hass, berlin, local(8, 40, 5))
    assert len(_reminders(phone_calls)) == 3  # max reached

    await _tick(hass, berlin, local(9, 0, 6))
    assert len(missed) == 1
    assert hass.states.get(STATUS).state == "missed"
    assert hass.states.get(DUE).state == "off"
    # missed message to phone and escalation contact
    assert any("❌" in c.data["title"] for c in phone_calls)
    assert any("❌" in c.data["title"] for c in care_calls)
    assert hass.states.get("sensor.ramipril_adherence_7_days").state == "0.0"
    assert hass.states.get("sensor.anna_missed_today").state == "1"


async def test_mobile_app_action(
    hass: HomeAssistant, berlin: FrozenDateTimeFactory, phone_calls, entry
) -> None:
    """The 'Taken' action in the push notification acknowledges the dose."""
    await setup(hass, entry)
    await _tick(hass, berlin, local(8, 0, 1))
    action = phone_calls[0].data["data"]["actions"][0]["action"]

    hass.bus.async_fire("mobile_app_notification_action", {"action": action})
    await hass.async_block_till_done()

    assert hass.states.get(STATUS).state == "taken"
    record = entry.runtime_data.history.records()[0]
    assert record.source == "notification"


async def test_snooze(
    hass: HomeAssistant, berlin: FrozenDateTimeFactory, phone_calls, entry
) -> None:
    """Snooze stops reminders until the snooze time has passed."""
    await setup(hass, entry)
    await _tick(hass, berlin, local(8, 0, 1))
    await _press(hass, SNOOZE)
    await hass.async_block_till_done()
    assert hass.states.get(STATUS).state == "snoozed"
    assert len(_clears(phone_calls)) == 1

    await _tick(hass, berlin, local(8, 10, 2))
    assert len(_reminders(phone_calls)) == 1  # repeat suppressed
    await _tick(hass, berlin, local(8, 15, 3))
    assert len(_reminders(phone_calls)) == 2
    assert hass.states.get(STATUS).state == "due"


async def test_take_early_and_skip(
    hass: HomeAssistant, berlin: FrozenDateTimeFactory, phone_calls, entry
) -> None:
    """A dose can be confirmed within the early window; no reminder follows."""
    await setup(hass, entry)
    with pytest.raises(ServiceValidationError):
        await _press(hass, SNOOZE)  # nothing open

    await _press(hass, TAKEN)  # 07:50, slot 08:00, early window 30 min
    await hass.async_block_till_done()
    await _tick(hass, berlin, local(8, 0, 1))
    assert not _reminders(phone_calls)
    assert hass.states.get(STATUS).state == "taken"

    # Nothing actionable until 19:30
    with pytest.raises(ServiceValidationError):
        await _press(hass, TAKEN)

    await _tick(hass, berlin, local(19, 40))
    await _press(hass, SKIP)
    await hass.async_block_till_done()
    assert hass.states.get(STATUS).state == "skipped"
    await _tick(hass, berlin, local(20, 0, 1))
    assert not _reminders(phone_calls)
    # skipped does not count against adherence
    assert hass.states.get("sensor.ramipril_adherence_7_days").state == "100.0"
    assert hass.states.get("sensor.anna_taken_today").state == "1"
    assert hass.states.get("sensor.anna_skipped_today").state == "1"
    assert hass.states.get("sensor.anna_open_today").state == "0"

    # Daily counters reset at midnight
    await _tick(hass, berlin, local(0, 0, 10, day=3))
    assert hass.states.get("sensor.anna_taken_today").state == "0"
    assert hass.states.get("sensor.anna_skipped_today").state == "0"
    assert hass.states.get("sensor.anna_open_today").state == "2"


async def test_pause_switch(
    hass: HomeAssistant, berlin: FrozenDateTimeFactory, phone_calls, entry
) -> None:
    """Paused medications send nothing and log 'paused'."""
    await setup(hass, entry)
    await hass.services.async_call("switch", "turn_off", {"entity_id": SWITCH}, blocking=True)
    assert hass.states.get(STATUS).state == "paused"
    await _tick(hass, berlin, local(8, 0, 1))
    assert not _reminders(phone_calls)
    records = entry.runtime_data.history.records()
    assert [r.status for r in records] == [DoseStatus.PAUSED]


async def test_restart_catches_up(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, phone_calls
) -> None:
    """Doses that passed while HA was down are logged as missed."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(local(12, 0))
    entry = make_entry(**{"created_at": "2026-11-01T06:00:00+00:00"})
    await setup(hass, entry)

    records = entry.runtime_data.history.records()
    # 2026-11-01 08:00 and 20:00, 2026-11-02 08:00 -> missed
    assert [r.status for r in records] == [DoseStatus.MISSED] * 3
    assert not phone_calls
    assert hass.states.get("sensor.anna_adherence_7_days").state == "0.0"


async def test_restart_resumes_open_dose(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, phone_calls
) -> None:
    """HA starting inside a dose window sends the reminder right away."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(local(8, 20))
    entry = make_entry(**{"created_at": "2026-11-02T06:00:00+00:00"})
    await setup(hass, entry)
    assert hass.states.get(DUE).state == "on"
    assert len(_reminders(phone_calls)) == 1


async def test_mark_taken_afterwards(
    hass: HomeAssistant, berlin: FrozenDateTimeFactory, phone_calls, entry
) -> None:
    """A missed dose can be corrected via service with a time."""
    await setup(hass, entry)
    await _tick(hass, berlin, local(8, 0, 1))
    await _tick(hass, berlin, local(9, 0, 2))
    assert hass.states.get(STATUS).state == "missed"

    await hass.services.async_call(
        DOMAIN,
        "mark_taken",
        {"entity_id": TAKEN, "taken_at": local(8, 5).isoformat()},
        blocking=True,
    )
    record = entry.runtime_data.history.records()[0]
    assert record.status == DoseStatus.TAKEN
    assert record.source == "service"
    assert record.resolved_at == local(8, 5)


async def test_history_services(
    hass: HomeAssistant, berlin: FrozenDateTimeFactory, phone_calls, entry, tmp_path
) -> None:
    """get_history returns records, export_history writes a CSV."""
    hass.config.config_dir = str(tmp_path)
    await setup(hass, entry)
    await _tick(hass, berlin, local(8, 0, 1))
    await _press(hass, TAKEN)

    response = await hass.services.async_call(
        DOMAIN, "get_history", {"status": ["taken"]}, blocking=True, return_response=True
    )
    doses = response["people"][0]["doses"]
    assert len(doses) == 1
    assert doses[0]["medication_id"] == MED_ID

    response = await hass.services.async_call(
        DOMAIN, "export_history", {}, blocking=True, return_response=True
    )
    path = response["files"][0]["path"]
    content = (tmp_path / DOMAIN / path.split("/")[-1].split("\\")[-1]).read_text(
        encoding="utf-8-sig"
    )
    assert content.splitlines()[0].startswith("id;medication_id")
    assert "taken" in content


async def test_calendar_and_unload(
    hass: HomeAssistant, berlin: FrozenDateTimeFactory, phone_calls, entry
) -> None:
    """Calendar shows planned doses; unload works."""
    await setup(hass, entry)
    state = hass.states.get("calendar.anna_medication")
    assert state is not None
    assert "Ramipril" in state.attributes["message"]

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_send_message_is_skipped(
    hass: HomeAssistant, berlin: FrozenDateTimeFactory, phone_calls
) -> None:
    """notify.send_message (entity based) is never used for reminders."""
    send_message_calls = async_mock_service(hass, "notify", "send_message")
    entry = make_entry()
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "notify_services": ["send_message", "mobile_app_phone"]}
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await _tick(hass, berlin, local(8, 0, 1))
    assert not send_message_calls
    assert len(_reminders(phone_calls)) == 1
