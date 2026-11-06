"""Reminder timing, repeat, clearing and catch-up."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant

from custom_components.pill_reminder.const import EVENT_MEASUREMENT_REMINDER

from .conftest import advance, advance_to, local, make_entry, metric_subentry, setup


def _reminders(calls) -> list:
    return [c for c in calls if c.data["message"] != "clear_notification"]


def _clears(calls) -> list:
    return [c for c in calls if c.data["message"] == "clear_notification"]


async def test_reminder_at_seven_with_link(hass: HomeAssistant, berlin, phone_calls, entry) -> None:
    """At 07:00 on Monday: weight and waist are due, a push opens the dashboard."""
    await setup(hass, entry)
    tracker = entry.runtime_data.body
    await tracker.async_add_measurement("weight", 80.0, source="test", measured_at=local(7, day=1))
    assert hass.states.get("binary_sensor.anna_weight_due").state == "off"
    assert not phone_calls

    await advance_to(hass, berlin, local(7, 0, day=2) + timedelta(seconds=1))
    assert hass.states.get("binary_sensor.anna_weight_due").state == "on"
    assert hass.states.get("binary_sensor.anna_waist_due").state == "on"
    sent = _reminders(phone_calls)
    assert len(sent) == 2
    weight = next(c for c in sent if c.data["data"]["tag"].endswith("_weight"))
    assert weight.data["title"] == "⚖️ Time to step on the scale"
    assert "Anna" in weight.data["message"]
    assert "Last value: 80.0 kg (Nov 01)" in weight.data["message"]
    assert weight.data["data"]["url"] == "/pill-reminder/anna-body"
    assert weight.data["data"]["clickAction"] == "/pill-reminder/anna-body"


async def test_repeat_and_clear(hass: HomeAssistant, berlin, phone_calls) -> None:
    """One repeat after 2 h; entering a value clears the notification."""
    events = []
    hass.bus.async_listen(EVENT_MEASUREMENT_REMINDER, events.append)
    entry = make_entry(subentries=[metric_subentry("w", "weight", [0, 1, 2, 3, 4, 5, 6])])
    await setup(hass, entry)

    await advance_to(hass, berlin, local(7, 0) + timedelta(seconds=1))
    assert len(_reminders(phone_calls)) == 1
    await advance(hass, berlin, timedelta(hours=2))
    assert len(_reminders(phone_calls)) == 2
    assert _reminders(phone_calls)[1].data["title"].endswith("(reminder)")
    # no third reminder
    await advance(hass, berlin, timedelta(hours=4))
    assert len(_reminders(phone_calls)) == 2
    assert [e.data["count"] for e in events] == [1, 2]

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.anna_weight_enter", "value": 80},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.anna_weight_due").state == "off"
    (clear,) = _clears(phone_calls)
    assert clear.data["data"]["tag"] == f"pill_reminder_{entry.entry_id}_weight"

    # Due again next day at 07:00, off at midnight before that
    await advance_to(hass, berlin, local(0, 0, day=3) + timedelta(seconds=2))
    assert hass.states.get("binary_sensor.anna_weight_due").state == "off"


async def test_measured_before_reminder(hass: HomeAssistant, berlin, phone_calls) -> None:
    """A value entered before 07:00 the same day suppresses the reminder."""
    entry = make_entry(subentries=[metric_subentry("w", "weight", [0, 1, 2, 3, 4, 5, 6])])
    await setup(hass, entry)
    await entry.runtime_data.body.async_add_measurement("weight", 80.0, source="test")
    await advance_to(hass, berlin, local(7, 1))
    assert not phone_calls
    assert hass.states.get("binary_sensor.anna_weight_due").state == "off"


async def test_repeat_not_after_midnight(hass: HomeAssistant, berlin, phone_calls) -> None:
    """A reminder at 23:00 is not repeated after midnight."""
    entry = make_entry(
        subentries=[metric_subentry("w", "weight", [0, 1, 2, 3, 4, 5, 6], reminder_time="23:00")]
    )
    await setup(hass, entry)
    await advance_to(hass, berlin, local(23, 0, day=2) + timedelta(seconds=1))
    assert len(_reminders(phone_calls)) == 1
    await advance_to(hass, berlin, local(1, 30, day=3))
    assert len(_reminders(phone_calls)) == 1
    assert hass.states.get("binary_sensor.anna_weight_due").state == "off"


async def test_weekly_reminder(hass: HomeAssistant, berlin, phone_calls) -> None:
    """Waist on Mondays only."""
    entry = make_entry(
        subentries=[metric_subentry("x", "waist", [0])],
        options={"repeat_interval": 0, "persistent_notification": False},
    )
    await setup(hass, entry)
    await advance_to(hass, berlin, local(7, 1, day=2))
    assert len(_reminders(phone_calls)) == 1
    for day in range(3, 9):
        await advance_to(hass, berlin, local(7, 1, day=day))
        assert hass.states.get("binary_sensor.anna_waist_due").state == "off"
    assert len(_reminders(phone_calls)) == 1  # no repeat (interval 0), nothing Tue-Sun
    await advance_to(hass, berlin, local(7, 1, day=9))
    assert len(_reminders(phone_calls)) == 2


async def test_disabled_reminder(hass: HomeAssistant, berlin, phone_calls) -> None:
    """Reminder off: no push, never due."""
    entry = make_entry(
        subentries=[metric_subentry("w", "weight", [0, 1, 2, 3, 4, 5, 6], reminder_enabled=False)]
    )
    await setup(hass, entry)
    await advance_to(hass, berlin, local(9, 0))
    assert not phone_calls
    assert hass.states.get("binary_sensor.anna_weight_due").state == "off"


async def test_catch_up_after_restart(hass: HomeAssistant, berlin, phone_calls) -> None:
    """A reminder missed while HA was down is sent at start, but only once."""
    berlin.move_to(local(9, 30))
    entry = make_entry(subentries=[metric_subentry("w", "weight", [0, 1, 2, 3, 4, 5, 6])])
    await setup(hass, entry)
    assert len(_reminders(phone_calls)) == 1
    assert hass.states.get("binary_sensor.anna_weight_due").state == "on"

    # Restart: nothing new, the repeat comes 2 h after the first reminder
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert len(_reminders(phone_calls)) == 1
    await advance_to(hass, berlin, local(11, 31))
    assert len(_reminders(phone_calls)) == 2


async def test_persistent_notification(hass: HomeAssistant, berlin, phone_calls) -> None:
    """Optional persistent notification, dismissed after entering a value."""
    entry = make_entry(
        subentries=[metric_subentry("w", "weight", [0, 1, 2, 3, 4, 5, 6])],
        options={"repeat_interval": 120, "persistent_notification": True},
    )
    await setup(hass, entry)
    await advance_to(hass, berlin, local(7, 1))
    notification_id = f"pill_reminder_{entry.entry_id}_weight"
    from homeassistant.components import persistent_notification

    notifications = persistent_notification._async_get_or_create_notifications(hass)
    assert notification_id in notifications
    await entry.runtime_data.body.async_add_measurement("weight", 80.0, source="test")
    await hass.async_block_till_done()
    assert notification_id not in notifications
