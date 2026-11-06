"""Validation and text formats, shared by config flow, dashboard entities and actions."""

from __future__ import annotations

from datetime import time
import itertools
import re
from typing import Any

from .const import (
    ALL_WEEKDAYS,
    CONF_DOSAGE,
    CONF_EARLY_MINUTES,
    CONF_LATE_MINUTES,
    CONF_METRIC,
    CONF_NAME,
    CONF_REMINDER_ENABLED,
    CONF_REMINDER_TIME,
    CONF_TIMES,
    CONF_WEEKDAYS,
    DEFAULT_EARLY_MINUTES,
    DEFAULT_LATE_MINUTES,
    DEFAULT_REMINDER_TIME,
)
from .metrics import METRICS
from .models import parse_time

# First two letters of German and English weekday names -> weekday number
_WEEKDAY_PREFIXES = {
    "mo": 0,
    "di": 1,
    "tu": 1,
    "mi": 2,
    "we": 2,
    "do": 3,
    "th": 3,
    "fr": 4,
    "sa": 5,
    "so": 6,
    "su": 6,
}
_ALL_DAYS_WORDS = {"täglich", "taeglich", "daily", "alle", "all", "every day", "jeden tag"}
_WEEKDAY_NAMES = {
    "de": ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"],
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
}
_ALL_DAYS_NAME = {"de": "täglich", "en": "daily"}


class MedicationInvalid(ValueError):
    """Raised with an error key (see strings.json) for invalid input."""

    def __init__(self, key: str) -> None:
        """Initialize."""
        super().__init__(key)
        self.key = key


def _weekday(token: str) -> int:
    day = _WEEKDAY_PREFIXES.get(token.strip().lower()[:2])
    if day is None:
        raise MedicationInvalid("invalid_weekdays")
    return day


def parse_weekdays(text: str) -> list[int]:
    """Parse e.g. 'Mo-Fr', 'Mo, Mi, Fr', 'täglich', 'Mon-Sun'."""
    value = text.strip().lower()
    if not value:
        raise MedicationInvalid("weekdays_required")
    if value in _ALL_DAYS_WORDS:
        return list(ALL_WEEKDAYS)
    days: set[int] = set()
    for part in re.split(r"[,;\s]+", value):
        if not part:
            continue
        if "-" in part:
            first, _, last = part.partition("-")
            start, end = _weekday(first), _weekday(last)
            days.update(
                range(start, end + 1) if start <= end else [*range(start, 7), *range(0, end + 1)]
            )
        else:
            days.add(_weekday(part))
    return sorted(days)


def format_weekdays(weekdays: list[int], language: str) -> str:
    """Human readable weekday list, ranges collapsed ('Mo-Fr')."""
    lang = language if language in _WEEKDAY_NAMES else "en"
    days = sorted(set(weekdays))
    if days == list(ALL_WEEKDAYS):
        return _ALL_DAYS_NAME[lang]
    names = _WEEKDAY_NAMES[lang]
    parts: list[str] = []
    for _, group in itertools.groupby(enumerate(days), key=lambda x: x[1] - x[0]):
        run = [d for _, d in group]
        if len(run) >= 3:
            parts.append(f"{names[run[0]]}-{names[run[-1]]}")
        else:
            parts.extend(names[d] for d in run)
    return ", ".join(parts)


def parse_times(value: str | list[str]) -> list[str]:
    """Parse '08:00, 20:00' (or a list) into sorted 'HH:MM' strings."""
    raw = re.split(r"[,;\s]+", value) if isinstance(value, str) else value
    times: set[str] = set()
    for item in raw:
        if not str(item).strip():
            continue
        try:
            times.add(parse_time(str(item)).strftime("%H:%M"))
        except ValueError as err:
            raise MedicationInvalid("invalid_time") from err
    if not times:
        raise MedicationInvalid("times_required")
    return sorted(times)


def format_times(times: list[str]) -> str:
    """'08:00, 20:00'."""
    return ", ".join(times)


def validate_medication(user_input: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Validate medication input; return (clean data, errors per field)."""
    errors: dict[str, str] = {}
    name = str(user_input.get(CONF_NAME, "")).strip()
    if not name:
        errors[CONF_NAME] = "name_required"

    times: list[str] = []
    try:
        times = parse_times(user_input.get(CONF_TIMES) or [])
    except MedicationInvalid as err:
        errors[CONF_TIMES] = err.key

    raw_weekdays = user_input.get(CONF_WEEKDAYS, [])
    weekdays: list[int] = []
    try:
        weekdays = (
            parse_weekdays(raw_weekdays)
            if isinstance(raw_weekdays, str)
            else sorted({int(d) for d in raw_weekdays})
        )
    except MedicationInvalid as err:
        errors[CONF_WEEKDAYS] = err.key
    if not weekdays and CONF_WEEKDAYS not in errors:
        errors[CONF_WEEKDAYS] = "weekdays_required"

    early = int(user_input.get(CONF_EARLY_MINUTES, DEFAULT_EARLY_MINUTES))
    late = int(user_input.get(CONF_LATE_MINUTES, DEFAULT_LATE_MINUTES))
    if times:
        # Windows of consecutive slots must not overlap, otherwise a button
        # press could not be assigned to one dose unambiguously.
        minutes = [int(t[:2]) * 60 + int(t[3:]) for t in times]
        gaps = [b - a for a, b in itertools.pairwise(minutes)]
        gaps.append(minutes[0] + 1440 - minutes[-1])
        if min(gaps) < early + late:
            errors["base"] = "windows_overlap"

    data = {
        CONF_NAME: name,
        CONF_DOSAGE: str(user_input.get(CONF_DOSAGE, "")).strip(),
        CONF_TIMES: times,
        CONF_WEEKDAYS: weekdays,
        CONF_EARLY_MINUTES: early,
        CONF_LATE_MINUTES: late,
    }
    return data, errors


# ---------------------------------------------------------------- measurements

# Same error class, also used for measurement input
InvalidInput = MedicationInvalid


def parse_reminder_time(value: str | time) -> time:
    """Parse 'HH:MM' (or a time) for a measurement reminder."""
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    try:
        return parse_time(str(value))
    except ValueError as err:
        raise InvalidInput("invalid_time") from err


def validate_measurement(user_input: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Validate the reminder settings of a tracked measurement type.

    Returns (clean subentry data, errors per field).
    """
    errors: dict[str, str] = {}
    metric = user_input.get(CONF_METRIC)
    if metric not in METRICS:
        errors[CONF_METRIC] = "unknown_metric"

    reminder_time = DEFAULT_REMINDER_TIME
    try:
        reminder_time = parse_reminder_time(
            user_input.get(CONF_REMINDER_TIME) or DEFAULT_REMINDER_TIME
        ).strftime("%H:%M")
    except InvalidInput as err:
        errors[CONF_REMINDER_TIME] = err.key

    raw_weekdays = user_input.get(CONF_WEEKDAYS, ALL_WEEKDAYS)
    weekdays: list[int] = []
    try:
        weekdays = (
            parse_weekdays(raw_weekdays)
            if isinstance(raw_weekdays, str)
            else sorted({int(d) for d in raw_weekdays if 0 <= int(d) <= 6})
        )
    except InvalidInput as err:
        errors[CONF_WEEKDAYS] = err.key
    except ValueError:
        errors[CONF_WEEKDAYS] = "invalid_weekdays"
    if not weekdays and CONF_WEEKDAYS not in errors:
        errors[CONF_WEEKDAYS] = "weekdays_required"

    data = {
        CONF_METRIC: metric,
        CONF_REMINDER_ENABLED: bool(user_input.get(CONF_REMINDER_ENABLED, True)),
        CONF_REMINDER_TIME: reminder_time,
        CONF_WEEKDAYS: weekdays,
    }
    return data, errors
