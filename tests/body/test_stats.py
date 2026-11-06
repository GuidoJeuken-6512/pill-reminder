"""Tests for the pure evaluation functions and validation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.pill_reminder.stats import (
    BmiCategory,
    TrendDirection,
    WhtrCategory,
    bmi,
    bmi_category,
    change,
    trend,
    trend_direction,
    whtr,
    whtr_category,
)
from custom_components.pill_reminder.validation import (
    InvalidInput,
    format_weekdays,
    parse_weekdays,
    validate_measurement,
)

NOW = datetime(2026, 11, 2, 12, tzinfo=UTC)


def days_ago(days: float) -> datetime:
    return NOW - timedelta(days=days)


def test_bmi() -> None:
    assert bmi(80, 180) == 24.7
    assert bmi(None, 180) is None
    assert bmi(80, None) is None


@pytest.mark.parametrize(
    ("value", "category"),
    [
        (None, None),
        (18.4, BmiCategory.UNDERWEIGHT),
        (18.5, BmiCategory.NORMAL),
        (24.9, BmiCategory.NORMAL),
        (25, BmiCategory.OVERWEIGHT),
        (30, BmiCategory.OBESE_1),
        (35, BmiCategory.OBESE_2),
        (40, BmiCategory.OBESE_3),
    ],
)
def test_bmi_category(value: float | None, category: BmiCategory | None) -> None:
    assert bmi_category(value) == category


def test_whtr() -> None:
    assert whtr(90, 180) == 0.5
    assert whtr(None, 180) is None
    assert whtr_category(None) is None
    assert whtr_category(0.499) == WhtrCategory.HEALTHY
    assert whtr_category(0.5) == WhtrCategory.INCREASED
    assert whtr_category(0.6) == WhtrCategory.HIGH


def test_change() -> None:
    points = [(days_ago(10), 82.0), (days_ago(7), 81.0), (days_ago(3), 80.5), (days_ago(0), 80.0)]
    assert change(points, NOW, 7) == pytest.approx(-1.0)
    # no value 30-60 days ago
    assert change(points, NOW, 30) is None
    # latest value older than the period
    assert change([(days_ago(20), 80.0), (days_ago(8), 79.0)], NOW, 7) is None
    # reference too old (more than twice the period)
    assert change([(days_ago(15), 80.0), (days_ago(1), 79.0)], NOW, 7) is None
    assert change([], NOW, 7) is None


def test_trend() -> None:
    rising = [(days_ago(d), 80 + (14 - d) * 0.1) for d in range(14, -1, -1)]
    assert trend(rising, NOW) == pytest.approx(0.7)
    assert trend_direction(trend(rising, NOW), 0.2) == TrendDirection.RISING

    falling = [(days_ago(d), 80 - (14 - d) * 0.1) for d in range(14, -1, -1)]
    assert trend_direction(trend(falling, NOW), 0.2) == TrendDirection.FALLING

    flat = [(days_ago(d), 80 + (0.05 if d % 2 else 0)) for d in range(14, -1, -1)]
    assert trend_direction(trend(flat, NOW), 0.2) == TrendDirection.STABLE

    # too few points or values outside the window
    assert trend([(days_ago(1), 80.0), (days_ago(0), 81.0)], NOW) is None
    assert trend([(days_ago(d), 80.0) for d in (30, 20, 16)], NOW) is None
    assert trend_direction(None, 0.2) is None


def test_weekdays() -> None:
    assert parse_weekdays("täglich") == [0, 1, 2, 3, 4, 5, 6]
    assert parse_weekdays("Mo-Fr") == [0, 1, 2, 3, 4]
    assert parse_weekdays("Mon, Thu") == [0, 3]
    assert parse_weekdays("Sa-Mo") == [0, 5, 6]
    with pytest.raises(InvalidInput):
        parse_weekdays("xyz")
    assert format_weekdays([0], "en") == "Mon"
    assert format_weekdays([0, 1, 2, 3, 4], "de") == "Mo-Fr"
    assert format_weekdays([0, 1, 2, 3, 4, 5, 6], "de") == "täglich"


def test_validate_measurement() -> None:
    data, errors = validate_measurement(
        {"metric": "waist", "reminder_time": "07:30:00", "weekdays": ["0"]}
    )
    assert not errors
    assert data == {
        "metric": "waist",
        "reminder_enabled": True,
        "reminder_time": "07:30",
        "weekdays": [0],
    }
    _, errors = validate_measurement({"metric": "pulse", "reminder_time": "25:00", "weekdays": []})
    assert errors == {
        "metric": "unknown_metric",
        "reminder_time": "invalid_time",
        "weekdays": "weekdays_required",
    }
