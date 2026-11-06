"""Registry of measurement types.

A new measurement type (e.g. pulse) is added here plus its names in
strings.json, icons.json and the services.yaml selector; config flow, storage,
entities, reminders and dashboard pick it up automatically.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberDeviceClass
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import UnitOfLength, UnitOfMass


@dataclass(frozen=True, slots=True, kw_only=True)
class MetricType:
    """One kind of measurement."""

    key: str
    unit: str
    sensor_device_class: SensorDeviceClass | None
    number_device_class: NumberDeviceClass | None
    min_value: float
    max_value: float
    step: float
    decimals: int
    # |trend| below this (units per week) counts as "stable"
    trend_threshold: float
    # Default reminder: weekdays (0 = Monday) at 07:00
    default_weekdays: tuple[int, ...]


WEIGHT = MetricType(
    key="weight",
    unit=UnitOfMass.KILOGRAMS,
    sensor_device_class=SensorDeviceClass.WEIGHT,
    number_device_class=NumberDeviceClass.WEIGHT,
    min_value=20,
    max_value=400,
    step=0.1,
    decimals=1,
    trend_threshold=0.2,
    default_weekdays=(0, 1, 2, 3, 4, 5, 6),
)

WAIST = MetricType(
    key="waist",
    unit=UnitOfLength.CENTIMETERS,
    sensor_device_class=SensorDeviceClass.DISTANCE,
    number_device_class=NumberDeviceClass.DISTANCE,
    min_value=30,
    max_value=250,
    step=0.5,
    decimals=1,
    trend_threshold=0.5,
    default_weekdays=(0,),
)

METRICS: dict[str, MetricType] = {m.key: m for m in (WEIGHT, WAIST)}

# Names used for subentry titles (entity names come from strings.json)
TITLES: dict[str, dict[str, str]] = {
    "de": {"weight": "Gewicht", "waist": "Bauchumfang"},
    "en": {"weight": "Weight", "waist": "Waist circumference"},
}


def metric_title(key: str, language: str) -> str:
    """Display name of a measurement type in the system language."""
    titles = TITLES.get(language.split("-")[0], TITLES["en"])
    return titles.get(key, key)
