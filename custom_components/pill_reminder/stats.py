"""Pure evaluation functions (no Home Assistant objects)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from enum import StrEnum


class BmiCategory(StrEnum):
    """WHO BMI classes for adults."""

    UNDERWEIGHT = "underweight"
    NORMAL = "normal"
    OVERWEIGHT = "overweight"
    OBESE_1 = "obese_1"
    OBESE_2 = "obese_2"
    OBESE_3 = "obese_3"


class WhtrCategory(StrEnum):
    """Waist-to-height ratio classes."""

    HEALTHY = "healthy"
    INCREASED = "increased"
    HIGH = "high"


class TrendDirection(StrEnum):
    """Direction of a trend."""

    RISING = "rising"
    FALLING = "falling"
    STABLE = "stable"


# (time, value) pairs, oldest first
Points = Sequence[tuple[datetime, float]]

TREND_DAYS = 14
TREND_MIN_POINTS = 3


def bmi(weight_kg: float | None, height_cm: float | None) -> float | None:
    """Body mass index in kg/m²."""
    if not weight_kg or not height_cm:
        return None
    height_m = height_cm / 100
    return round(weight_kg / (height_m * height_m), 1)


def bmi_category(value: float | None) -> BmiCategory | None:
    """WHO class of a BMI value."""
    if value is None:
        return None
    if value < 18.5:
        return BmiCategory.UNDERWEIGHT
    if value < 25:
        return BmiCategory.NORMAL
    if value < 30:
        return BmiCategory.OVERWEIGHT
    if value < 35:
        return BmiCategory.OBESE_1
    if value < 40:
        return BmiCategory.OBESE_2
    return BmiCategory.OBESE_3


def whtr(waist_cm: float | None, height_cm: float | None) -> float | None:
    """Waist-to-height ratio."""
    if not waist_cm or not height_cm:
        return None
    return round(waist_cm / height_cm, 3)


def whtr_category(value: float | None) -> WhtrCategory | None:
    """Class of a waist-to-height ratio."""
    if value is None:
        return None
    if value < 0.5:
        return WhtrCategory.HEALTHY
    if value < 0.6:
        return WhtrCategory.INCREASED
    return WhtrCategory.HIGH


def change(points: Points, now: datetime, days: int) -> float | None:
    """Latest value minus the value about `days` days ago.

    The reference is the last value measured at least `days` days ago, but not
    more than twice as long ago (an ancient value is no "7 day change"). The
    latest value must be newer than the reference period.
    """
    if not points:
        return None
    cutoff = now - timedelta(days=days)
    oldest_allowed = now - timedelta(days=2 * days)
    latest_time, latest_value = points[-1]
    if latest_time <= cutoff:
        return None
    reference = next((p for p in reversed(points) if p[0] <= cutoff), None)
    if reference is None or reference[0] < oldest_allowed:
        return None
    return latest_value - reference[1]


def trend(
    points: Points,
    now: datetime,
    days: int = TREND_DAYS,
    min_points: int = TREND_MIN_POINTS,
) -> float | None:
    """Slope of a linear regression over the last `days` days, in units per week."""
    start = now - timedelta(days=days)
    recent = [(t, v) for t, v in points if start <= t <= now]
    if len(recent) < min_points:
        return None
    xs = [(t - start).total_seconds() / 86400 for t, _ in recent]
    ys = [v for _, v in recent]
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx == 0:
        return None
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    return sxy / sxx * 7


def trend_direction(slope: float | None, threshold: float) -> TrendDirection | None:
    """Classify a trend (units per week)."""
    if slope is None:
        return None
    if slope >= threshold:
        return TrendDirection.RISING
    if slope <= -threshold:
        return TrendDirection.FALLING
    return TrendDirection.STABLE


class BloodPressureCategory(StrEnum):
    """Blood pressure classes for adults (ESC/ESH, office values)."""

    OPTIMAL = "optimal"
    NORMAL = "normal"
    HIGH_NORMAL = "high_normal"
    GRADE_1 = "grade_1"
    GRADE_2 = "grade_2"
    GRADE_3 = "grade_3"


# (systolic from, diastolic from, class) - the higher of both values decides
_BP_CLASSES = (
    (180, 110, BloodPressureCategory.GRADE_3),
    (160, 100, BloodPressureCategory.GRADE_2),
    (140, 90, BloodPressureCategory.GRADE_1),
    (130, 85, BloodPressureCategory.HIGH_NORMAL),
    (120, 80, BloodPressureCategory.NORMAL),
)


def blood_pressure_category(
    systolic: float | None, diastolic: float | None
) -> BloodPressureCategory | None:
    """Class of a blood pressure reading; the higher class of both values counts."""
    if systolic is None or diastolic is None:
        return None
    for sys_from, dia_from, category in _BP_CLASSES:
        if systolic >= sys_from or diastolic >= dia_from:
            return category
    return BloodPressureCategory.OPTIMAL


def average(points: Points, now: datetime, days: int) -> float | None:
    """Mean of all values of the last `days` days."""
    start = now - timedelta(days=days)
    values = [v for t, v in points if start <= t <= now]
    if not values:
        return None
    return sum(values) / len(values)
