"""On-demand medications: log intakes, count them per day and month, warn at limits."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.pill_reminder.const import (
    CONF_DOSAGE,
    CONF_MAX_DAYS_PER_MONTH,
    CONF_MAX_PER_DAY,
    CONF_NAME,
    DOMAIN,
    EVENT_INTAKE_LIMIT,
    EVENT_INTAKE_TAKEN,
    SUBENTRY_ON_DEMAND,
)
from custom_components.pill_reminder.dashboard import async_build_dashboard
from custom_components.pill_reminder.intakes import month_window
from custom_components.pill_reminder.validation import validate_on_demand

from ..conftest import TZ, local, make_entry, setup
from .conftest import SUB_SUMA, make_on_demand_entry, on_demand_subentry


def _eid(hass: HomeAssistant, domain: str, unique_id: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)
    assert entity_id, f"{domain} {unique_id} missing"
    return entity_id


def _value(hass: HomeAssistant, key: str) -> str:
    return hass.states.get(_eid(hass, "sensor", f"{SUB_SUMA}_{key}")).state


async def _press(hass: HomeAssistant) -> None:
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": _eid(hass, "button", f"{SUB_SUMA}_taken")},
        blocking=True,
    )
    await hass.async_block_till_done()


async def _log(hass: HomeAssistant, taken_at, service: str = "log_intake") -> None:
    await hass.services.async_call(
        DOMAIN,
        service,
        {"entity_id": _eid(hass, "button", f"{SUB_SUMA}_taken"), "taken_at": taken_at},
        blocking=True,
    )
    await hass.async_block_till_done()


async def test_entity_ids(hass: HomeAssistant, berlin, phone_calls, entry) -> None:
    """Device per medication with the expected (English) entity ids."""
    hass.config.language = "en"
    await setup(hass, entry)

    for entity_id in (
        "button.sumatriptan_taken",
        "sensor.sumatriptan_intakes_this_month",
        "sensor.sumatriptan_intake_days_this_month",
        "sensor.sumatriptan_intakes_last_month",
        "sensor.sumatriptan_intakes_30_days",
        "sensor.sumatriptan_intakes_today",
        "sensor.sumatriptan_last_intake",
        "binary_sensor.sumatriptan_limit_reached",
        "number.sumatriptan_limit_days_per_month",
        "number.sumatriptan_limit_intakes_per_day",
        "button.anna_add_on_demand_medication",
        "text.anna_new_on_demand_medication_name",
    ):
        assert hass.states.get(entity_id) is not None, entity_id
    month = hass.states.get("sensor.sumatriptan_intakes_this_month")
    assert month.state == "0"
    assert month.attributes["unit_of_measurement"] == "intakes"
    assert month.attributes["state_class"] == "total"
    assert month.attributes["on_demand"] is True
    # No scheduled medication: the dose entities of scheduled medications are not created
    assert hass.states.get("binary_sensor.sumatriptan_due") is None


async def test_press_counts_intakes(hass: HomeAssistant, berlin, phone_calls, entry) -> None:
    """Each press is one intake; days count distinct local days."""
    await setup(hass, entry)
    events = async_capture_events(hass, EVENT_INTAKE_TAKEN)

    await _press(hass)
    berlin.tick(timedelta(hours=3))
    await _press(hass)

    assert _value(hass, "intakes_today") == "2"
    assert _value(hass, "intakes_month") == "2"
    assert _value(hass, "intake_days_month") == "1"
    assert _value(hass, "intakes_30d") == "2"
    assert _value(hass, "intakes_previous_month") == "0"
    last = _value(hass, "last_intake")
    assert last.startswith("2026-11-02T09:50:00")  # 10:50 Berlin
    assert [e.data["month"] for e in events] == [1, 2]
    assert events[0].data["medication"] == "Sumatriptan"
    assert events[0].data["source"] == "button"
    assert events[0].data["entity_id"] == _eid(hass, "sensor", f"{SUB_SUMA}_intakes_month")


async def test_month_rollover(hass: HomeAssistant, berlin, phone_calls) -> None:
    """At midnight of the 1st the month count restarts; the previous month keeps it."""
    entry = _entry_without_limits()
    berlin.move_to(local(23, 45, day=30))
    await setup(hass, entry)
    await _press(hass)
    # 23:30 local on 30 Nov is still November (22:30 UTC)
    await _log(hass, local(23, 30, day=30))
    assert _value(hass, "intakes_month") == "2"
    assert _value(hass, "intake_days_month") == "1"

    berlin.move_to(local(0, 0, 10, day=30) + timedelta(days=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert _value(hass, "intakes_month") == "0"
    assert _value(hass, "intakes_today") == "0"
    assert _value(hass, "intakes_previous_month") == "2"
    assert _value(hass, "intakes_30d") == "2"
    state = hass.states.get(_eid(hass, "sensor", f"{SUB_SUMA}_intakes_month"))
    assert state.attributes["days"] == 0


def _entry_without_limits() -> MockConfigEntry:
    return make_on_demand_entry(**{CONF_MAX_DAYS_PER_MONTH: None, CONF_MAX_PER_DAY: None})


async def test_month_window_in_local_time(berlin) -> None:
    """Month boundaries are local midnights (CET/CEST), also across a year."""
    start, end = month_window(local(12, day=2))
    assert start.astimezone(TZ).isoformat() == "2026-11-01T00:00:00+01:00"
    assert end.astimezone(TZ).isoformat() == "2026-12-01T00:00:00+01:00"
    previous, _ = month_window(local(12, day=2), -1)
    assert previous.astimezone(TZ).isoformat() == "2026-10-01T00:00:00+02:00"
    following, after = month_window(local(12, day=2), 2)
    assert following.astimezone(TZ).isoformat() == "2027-01-01T00:00:00+01:00"
    assert after.astimezone(TZ).isoformat() == "2027-02-01T00:00:00+01:00"


async def test_limits_warn_once(
    hass: HomeAssistant, berlin, phone_calls: list[ServiceCall], entry
) -> None:
    """3 intake days a month and 2 intakes a day: one warning each."""
    hass.config.language = "en"
    berlin.move_to(local(10, day=20))
    await setup(hass, entry)
    limit_events = async_capture_events(hass, EVENT_INTAKE_LIMIT)
    limit = _eid(hass, "binary_sensor", f"{SUB_SUMA}_limit_reached")

    await _log(hass, local(9, day=18))
    await _log(hass, local(9, day=19))
    assert hass.states.get(limit).state == "off"
    assert phone_calls == []

    await _press(hass)  # 3rd day this month
    assert hass.states.get(limit).state == "on"
    assert hass.states.get(limit).attributes["monthly_limit_reached"] is True
    assert hass.states.get(limit).attributes["daily_limit_reached"] is False
    assert len(phone_calls) == 1
    assert "limit reached" in phone_calls[0].data["title"]
    assert "3 days this month" in phone_calls[0].data["message"]

    await _press(hass)  # 2nd intake today
    assert len(phone_calls) == 2
    assert "2× today" in phone_calls[1].data["message"]
    assert hass.states.get(limit).attributes["daily_limit_reached"] is True

    await _press(hass)
    assert len(phone_calls) == 2  # no repeated warnings
    assert len(limit_events) == 2

    # The daily warning comes again on another day, the monthly one not.
    berlin.move_to(local(10, day=21))
    await _press(hass)
    await _press(hass)
    assert len(phone_calls) == 3
    assert "2× today" in phone_calls[2].data["message"]


async def test_no_limit_no_binary_sensor(hass: HomeAssistant, berlin, phone_calls) -> None:
    """Without limits there is no 'limit reached' sensor and no warning."""
    entry = _entry_without_limits()
    await setup(hass, entry)
    for _ in range(5):
        await _press(hass)
    assert (
        er.async_get(hass).async_get_entity_id("binary_sensor", DOMAIN, f"{SUB_SUMA}_limit_reached")
        is None
    )
    assert phone_calls == []
    assert _value(hass, "intakes_today") == "5"


async def test_log_later_and_future(hass: HomeAssistant, berlin, phone_calls, entry) -> None:
    """Intakes can be added afterwards (naive times are local), not in the future."""
    await setup(hass, entry)
    await _log(hass, "2026-10-15 20:00:00")
    assert _value(hass, "intakes_previous_month") == "1"
    assert _value(hass, "intakes_month") == "0"
    assert _value(hass, "intakes_30d") == "1"
    assert _value(hass, "last_intake").startswith("2026-10-15T18:00:00")  # CEST

    with pytest.raises(ServiceValidationError) as err:
        await _log(hass, local(9, day=3))
    assert err.value.translation_key == "taken_in_future"


async def test_mark_taken_logs_intake(hass: HomeAssistant, berlin, phone_calls, entry) -> None:
    """The general 'mark taken' action also works for on-demand medications."""
    await setup(hass, entry)
    await hass.services.async_call(
        DOMAIN,
        "mark_taken",
        {"entity_id": _eid(hass, "sensor", f"{SUB_SUMA}_intakes_today")},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert _value(hass, "intakes_today") == "1"


async def test_delete_get_export(hass: HomeAssistant, berlin, phone_calls, entry) -> None:
    """Delete the last intake or one by id; list and export as CSV."""
    await setup(hass, entry)
    await _log(hass, local(6, day=1))
    await _press(hass)
    taken = _eid(hass, "button", f"{SUB_SUMA}_taken")

    response = await hass.services.async_call(
        DOMAIN, "get_intakes", {"entity_id": taken}, blocking=True, return_response=True
    )
    intakes = response["people"][0]["intakes"]
    assert [i["medication_name"] for i in intakes] == ["Sumatriptan", "Sumatriptan"]
    assert response["people"][0]["person"] == "Anna"

    deleted = await hass.services.async_call(
        DOMAIN, "delete_intake", {"entity_id": taken}, blocking=True, return_response=True
    )
    assert deleted["deleted"]["id"] == intakes[1]["id"]  # the most recent
    await hass.services.async_call(
        DOMAIN,
        "delete_intake",
        {"entity_id": taken, "intake_id": intakes[0]["id"]},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert _value(hass, "intakes_month") == "0"
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "delete_intake", {"entity_id": taken}, blocking=True)

    await _press(hass)
    files = await hass.services.async_call(
        DOMAIN, "export_intakes", {}, blocking=True, return_response=True
    )
    path = Path(files["files"][0]["path"])
    assert files["files"][0]["count"] == 1
    content = path.read_text(encoding="utf-8-sig")
    assert content.splitlines()[0] == "id;medication_id;medication_name;taken_at;source;user_id"
    assert ";Sumatriptan;2026-11-02T07:50:00+01:00;button;" in content


async def test_not_an_on_demand_entity(hass: HomeAssistant, berlin, phone_calls) -> None:
    """A scheduled medication cannot log intakes."""
    entry = make_entry()
    await setup(hass, entry)
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            "log_intake",
            {"entity_id": "button.ramipril_taken"},
            blocking=True,
        )
    assert err.value.translation_key == "not_an_on_demand_medication"


async def test_intakes_survive_reload(hass: HomeAssistant, berlin, phone_calls, entry) -> None:
    """Intakes are stored and loaded again."""
    await setup(hass, entry)
    await _press(hass)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert _value(hass, "intakes_month") == "1"


async def test_combined_with_scheduled_medication(hass: HomeAssistant, berlin, phone_calls) -> None:
    """A scheduled and an on-demand medication side by side; counts stay separate."""
    hass.config.language = "en"
    entry = make_entry()
    entry.add_to_hass(hass)
    sub = on_demand_subentry()
    hass.config_entries.async_add_subentry(
        entry,
        ConfigSubentry(
            data=sub["data"],
            subentry_type=sub["subentry_type"],
            title=sub["title"],
            unique_id=None,
        ),
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    manager = entry.runtime_data
    assert len(manager.medications) == 1
    assert len(manager.on_demand.medications) == 1
    med_id = next(iter(manager.on_demand.medications))
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": _eid(hass, "button", f"{med_id}_taken")},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert manager.on_demand.count_today(med_id, local(12)) == 1
    # Ramipril's 08:00 dose is not affected
    assert hass.states.get("sensor.ramipril_status").state == "scheduled"

    config = await async_build_dashboard(hass)
    person = config["views"][0]
    headings = [
        c.get("heading") for s in person["sections"] for c in s["cards"] if c["type"] == "heading"
    ]
    assert "As needed" in headings
    assert "Today" in headings


async def test_dashboard(hass: HomeAssistant, berlin, phone_calls, entry) -> None:
    """'As needed' section with the button and counts; manage cards; log includes intakes."""
    hass.config.language = "en"
    await setup(hass, entry)
    config = await async_build_dashboard(hass)
    person, manage = config["views"][0], config["views"][-1]

    headings = [
        c.get("heading") for s in person["sections"] for c in s["cards"] if c["type"] == "heading"
    ]
    # Only an on-demand medication: no empty "Today" section
    assert "Today" not in headings
    assert "As needed" in headings
    cards = [c for s in person["sections"] for c in s["cards"]]
    taken = _eid(hass, "button", f"{SUB_SUMA}_taken")
    button = next(c for c in cards if c.get("entity") == taken)
    assert button["tap_action"]["confirmation"]["text"] == "Log an intake of Sumatriptan?"
    graph = next(c for c in cards if c["type"] == "statistics-graph" and c["period"] == "month")
    assert graph["entities"] == [_eid(hass, "sensor", f"{SUB_SUMA}_intakes_month")]
    logbook = next(c for c in cards if c["type"] == "logbook")
    assert graph["entities"][0] in logbook["target"]["entity_id"]
    warning = next(c for c in cards if c["type"] == "markdown" and "limit" in c["content"])
    assert warning["visibility"][0]["entity"] == _eid(
        hass, "binary_sensor", f"{SUB_SUMA}_limit_reached"
    )

    manage_ids = str(manage)
    for domain, unique_id in (
        ("number", f"{SUB_SUMA}_cfg_max_days_per_month"),
        ("text", f"{SUB_SUMA}_cfg_name"),
        ("button", f"{SUB_SUMA}_delete_medication"),
        ("button", f"{entry.entry_id}_add_on_demand"),
        ("text", f"{entry.entry_id}_new_on_demand_name"),
    ):
        assert _eid(hass, domain, unique_id) in manage_ids


async def test_manage_from_dashboard(hass: HomeAssistant, berlin, phone_calls, entry) -> None:
    """Add, change the limit and delete an on-demand medication from the dashboard."""
    await setup(hass, entry)
    eid = entry.entry_id
    await hass.services.async_call(
        "text",
        "set_value",
        {"entity_id": _eid(hass, "text", f"{eid}_new_on_demand_name"), "value": " Ibuprofen "},
        blocking=True,
    )
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": _eid(hass, "button", f"{eid}_add_on_demand")},
        blocking=True,
    )
    await hass.async_block_till_done()
    added = [
        s
        for s in entry.subentries.values()
        if s.subentry_type == SUBENTRY_ON_DEMAND and s.title == "Ibuprofen"
    ]
    assert len(added) == 1
    assert added[0].data[CONF_MAX_DAYS_PER_MONTH] is None
    new_id = added[0].subentry_id
    assert entry.runtime_data.on_demand.draft[CONF_NAME] == ""

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": _eid(hass, "number", f"{new_id}_cfg_max_days_per_month"), "value": 15},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert entry.subentries[new_id].data[CONF_MAX_DAYS_PER_MONTH] == 15
    # With a limit the person reloads and gets the 'limit reached' sensor
    assert _eid(hass, "binary_sensor", f"{new_id}_limit_reached")

    # Intakes are kept when the medication is deleted
    await _press(hass)
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": _eid(hass, "button", f"{SUB_SUMA}_delete_medication")},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert SUB_SUMA not in entry.subentries
    assert len(entry.runtime_data.on_demand.store.intakes(SUB_SUMA)) == 1


async def test_subentry_flow(hass: HomeAssistant, berlin, phone_calls, entry) -> None:
    """Add and edit an on-demand medication in the UI."""
    await setup(hass, entry)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_ON_DEMAND), context={"source": "user"}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_NAME: " ", CONF_DOSAGE: ""}
    )
    assert result["errors"] == {CONF_NAME: "name_required"}
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {CONF_NAME: "Rizatriptan", CONF_DOSAGE: "10 mg", CONF_MAX_DAYS_PER_MONTH: 10},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_NAME: "Rizatriptan",
        CONF_DOSAGE: "10 mg",
        CONF_MAX_DAYS_PER_MONTH: 10,
        CONF_MAX_PER_DAY: None,
    }

    result = await entry.start_subentry_reconfigure_flow(hass, SUB_SUMA)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_NAME: "Sumatriptan", CONF_DOSAGE: "100 mg", CONF_MAX_PER_DAY: 0}
    )
    assert result["reason"] == "reconfigure_successful"
    assert entry.subentries[SUB_SUMA].data[CONF_DOSAGE] == "100 mg"
    assert entry.subentries[SUB_SUMA].data[CONF_MAX_PER_DAY] is None


@pytest.mark.parametrize(
    ("value", "expected", "error"),
    [
        (None, None, None),
        ("", None, None),
        (0, None, None),
        (10, 10, None),
        (10.0, 10, None),
        (1.5, None, "invalid_limit"),
        (-1, None, "invalid_limit"),
        (32, None, "invalid_limit"),
        ("abc", None, "invalid_limit"),
    ],
)
def test_validate_limits(value, expected, error) -> None:
    """Limits are whole numbers; 0 or empty means no limit."""
    data, errors = validate_on_demand({CONF_NAME: "X", CONF_MAX_DAYS_PER_MONTH: value})
    assert errors.get(CONF_MAX_DAYS_PER_MONTH) == error
    if error is None:
        assert data[CONF_MAX_DAYS_PER_MONTH] == expected


async def test_diagnostics_without_names(hass: HomeAssistant, berlin, phone_calls, entry) -> None:
    """Diagnostics contain counts and limits, not the medication name."""
    from custom_components.pill_reminder.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    await setup(hass, entry)
    await _press(hass)
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["on_demand"][SUB_SUMA]["intakes_month"] == 1
    assert diagnostics["on_demand"][SUB_SUMA]["max_days_per_month"] == 3
    assert "Sumatriptan" not in str(diagnostics)
