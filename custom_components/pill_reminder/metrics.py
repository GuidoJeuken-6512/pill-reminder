"""Registry of measurement types.

A measurement type (one config subentry, one reminder, one device) has one or
more value fields that are entered and saved together: weight has the field
"weight", blood pressure has "systolic", "diastolic" and "pulse". Values are
stored per field, so statistics and sensors work per field.

A new measurement type is added here plus its names in strings.json,
icons.json and the services.yaml selector; config flow, storage, entities,
reminders and dashboard pick it up automatically.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberDeviceClass
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import UnitOfLength, UnitOfMass, UnitOfPressure


@dataclass(frozen=True, slots=True, kw_only=True)
class ValueField:
    """One stored series, e.g. weight or systolic pressure."""

    key: str
    unit: str
    sensor_device_class: SensorDeviceClass | None = None
    number_device_class: NumberDeviceClass | None = None
    min_value: float
    max_value: float
    step: float
    decimals: int
    # |trend| below this (units per week) counts as "stable"
    trend_threshold: float
    # Must be entered when saving (pulse is optional)
    required: bool = True
    # Also offer a 7-day average (blood pressure is judged by averages)
    average: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class MetricType:
    """One kind of measurement with its value fields."""

    key: str
    fields: tuple[ValueField, ...]
    # Default reminder: weekdays (0 = Monday) at 07:00
    default_weekdays: tuple[int, ...]
    # Tracked right away for new persons
    default: bool = True

    @property
    def single(self) -> bool:
        """Only one value field (its key equals the metric key)."""
        return len(self.fields) == 1

    @property
    def main(self) -> ValueField:
        """The first (required) field, e.g. used to see if anything was entered."""
        return self.fields[0]

    def field(self, key: str) -> ValueField | None:
        """Field by key."""
        return next((f for f in self.fields if f.key == key), None)


WEIGHT = MetricType(
    key="weight",
    fields=(
        ValueField(
            key="weight",
            unit=UnitOfMass.KILOGRAMS,
            sensor_device_class=SensorDeviceClass.WEIGHT,
            number_device_class=NumberDeviceClass.WEIGHT,
            min_value=20,
            max_value=400,
            step=0.1,
            decimals=1,
            trend_threshold=0.2,
        ),
    ),
    default_weekdays=(0, 1, 2, 3, 4, 5, 6),
)

WAIST = MetricType(
    key="waist",
    fields=(
        ValueField(
            key="waist",
            unit=UnitOfLength.CENTIMETERS,
            sensor_device_class=SensorDeviceClass.DISTANCE,
            number_device_class=NumberDeviceClass.DISTANCE,
            min_value=30,
            max_value=250,
            step=0.5,
            decimals=1,
            trend_threshold=0.5,
        ),
    ),
    default_weekdays=(0,),
)

# No pressure device class: Home Assistant would convert mmHg into hPa.
BLOOD_PRESSURE = MetricType(
    key="blood_pressure",
    fields=(
        ValueField(
            key="systolic",
            unit=UnitOfPressure.MMHG,
            min_value=60,
            max_value=260,
            step=1,
            decimals=0,
            trend_threshold=2,
            average=True,
        ),
        ValueField(
            key="diastolic",
            unit=UnitOfPressure.MMHG,
            min_value=30,
            max_value=160,
            step=1,
            decimals=0,
            trend_threshold=2,
            average=True,
        ),
        ValueField(
            key="pulse",
            unit="bpm",
            min_value=30,
            max_value=220,
            step=1,
            decimals=0,
            trend_threshold=2,
            required=False,
            average=True,
        ),
    ),
    default_weekdays=(0, 1, 2, 3, 4, 5, 6),
    default=False,
)

METRICS: dict[str, MetricType] = {m.key: m for m in (WEIGHT, WAIST, BLOOD_PRESSURE)}
FIELDS: dict[str, ValueField] = {f.key: f for m in METRICS.values() for f in m.fields}
# Field key -> measurement type key
FIELD_METRIC: dict[str, str] = {f.key: m.key for m in METRICS.values() for f in m.fields}

# Names used for subentry titles (entity names come from strings.json)
TITLES: dict[str, dict[str, str]] = {
    "de": {"weight": "Gewicht", "waist": "Bauchumfang", "blood_pressure": "Blutdruck"},
    "en": {"weight": "Weight", "waist": "Waist circumference", "blood_pressure": "Blood pressure"},
}


def metric_title(key: str, language: str) -> str:
    """Display name of a measurement type in the system language."""
    titles = TITLES.get(language.split("-")[0], TITLES["en"])
    return titles.get(key, key)


FIELD_TITLES: dict[str, dict[str, str]] = {
    "de": {
        "weight": "Gewicht",
        "waist": "Bauchumfang",
        "systolic": "Oberer Wert (systolisch)",
        "diastolic": "Unterer Wert (diastolisch)",
        "pulse": "Puls",
    },
    "en": {
        "weight": "Weight",
        "waist": "Waist circumference",
        "systolic": "Systolic",
        "diastolic": "Diastolic",
        "pulse": "Pulse",
    },
}


def field_title(key: str, language: str) -> str:
    """Display name of a value field in the system language."""
    titles = FIELD_TITLES.get(language.split("-")[0], FIELD_TITLES["en"])
    return titles.get(key, key)
