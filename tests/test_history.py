"""Statistics tests."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant

from custom_components.pill_reminder.history import DoseHistory
from custom_components.pill_reminder.models import DoseRecord, DoseStatus, dose_id_for

from .conftest import local


def _record(day: int, hour: int, status: DoseStatus) -> DoseRecord:
    scheduled = local(hour, day=day)
    return DoseRecord(
        id=dose_id_for("m", scheduled),
        medication_id="m",
        medication_name="M",
        scheduled=scheduled,
        status=status,
        resolved_at=scheduled + timedelta(minutes=5),
    )


async def test_adherence_and_streak(hass: HomeAssistant) -> None:
    """Skipped/paused do not count; a miss breaks the streak."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    history = DoseHistory(hass, "test")
    for record in (
        _record(1, 8, DoseStatus.MISSED),
        _record(1, 20, DoseStatus.TAKEN),
        _record(2, 8, DoseStatus.TAKEN),
        _record(2, 20, DoseStatus.SKIPPED),
        _record(3, 8, DoseStatus.TAKEN),
        _record(3, 20, DoseStatus.PAUSED),
    ):
        history.upsert(record)

    now = local(21, day=3)
    assert history.adherence(now, 7) == 75.0
    assert history.adherence(now, 7, "other") is None
    assert history.streak(now) == 2
    assert history.last_taken().scheduled == local(8, day=3)

    csv = history.to_csv(history.records())
    assert csv.count("\n") == 7
    assert ";5;" in csv  # delay in minutes

    assert history.purge(1, now) == 4
