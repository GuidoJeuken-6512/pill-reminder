"""Config flow: person (entry), options, medications and measurements (subentries)."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryData,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
    TimeSelector,
)
from homeassistant.util import dt as dt_util, slugify
import voluptuous as vol

from .body import default_subentry_data
from .const import (
    ALL_WEEKDAYS,
    CONF_CREATED_AT,
    CONF_DOSAGE,
    CONF_EARLY_MINUTES,
    CONF_ESCALATE_AFTER,
    CONF_ESCALATION_ENABLED,
    CONF_ESCALATION_SERVICES,
    CONF_HEIGHT,
    CONF_LATE_MINUTES,
    CONF_MAX_REMINDERS,
    CONF_MEASUREMENT_REPEAT,
    CONF_METRIC,
    CONF_NAME,
    CONF_NOTIFY_MISSED,
    CONF_NOTIFY_SERVICES,
    CONF_PERSISTENT_NOTIFICATION,
    CONF_PERSON_NAME,
    CONF_REMINDER_ENABLED,
    CONF_REMINDER_TIME,
    CONF_REPEAT_INTERVAL,
    CONF_RETENTION_DAYS,
    CONF_SNOOZE_MINUTES,
    CONF_TIME_SENSITIVE,
    CONF_TIMES,
    CONF_TRACK_BODY,
    CONF_USER_ID,
    CONF_WEEKDAYS,
    DEFAULT_EARLY_MINUTES,
    DEFAULT_ESCALATE_AFTER,
    DEFAULT_ESCALATION_ENABLED,
    DEFAULT_LATE_MINUTES,
    DEFAULT_MAX_REMINDERS,
    DEFAULT_MEASUREMENT_REPEAT,
    DEFAULT_NOTIFY_MISSED,
    DEFAULT_PERSISTENT_NOTIFICATION,
    DEFAULT_REMINDER_TIME,
    DEFAULT_REPEAT_INTERVAL,
    DEFAULT_RETENTION_DAYS,
    DEFAULT_SNOOZE_MINUTES,
    DEFAULT_TIME_SENSITIVE,
    DOMAIN,
    MAX_HEIGHT,
    MIN_HEIGHT,
    SUBENTRY_MEASUREMENT,
    SUBENTRY_MEDICATION,
)
from .metrics import METRICS, metric_title
from .notifier import UNSUPPORTED_NOTIFY_SERVICES
from .validation import validate_measurement, validate_medication

NO_USER = "none"


def _minutes(min_value: int, max_value: int, unit: str = "min") -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=min_value,
            max=max_value,
            step=1,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement=unit,
        )
    )


def _notify_selector(hass: HomeAssistant) -> SelectSelector:
    """Multi-select of notify services, mobile app services first."""
    services = sorted(
        (
            s
            for s in hass.services.async_services_for_domain("notify")
            if s not in UNSUPPORTED_NOTIFY_SERVICES
        ),
        key=lambda s: (not s.startswith("mobile_app_"), s),
    )
    return SelectSelector(
        SelectSelectorConfig(
            options=[SelectOptionDict(value=s, label=f"notify.{s}") for s in services],
            multiple=True,
            custom_value=True,
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


def _user_selector(hass: HomeAssistant, users: list[tuple[str, str]]) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[SelectOptionDict(value=NO_USER, label="—")]
            + [SelectOptionDict(value=uid, label=name) for uid, name in users],
            mode=SelectSelectorMode.DROPDOWN,
            translation_key="user",
        )
    )


async def _async_users(hass: HomeAssistant) -> list[tuple[str, str]]:
    users = await hass.auth.async_get_users()
    return sorted(
        ((u.id, u.name or u.id) for u in users if not u.system_generated and u.is_active),
        key=lambda u: u[1].lower(),
    )


def _person_schema(
    hass: HomeAssistant, users: list[tuple[str, str]], *, new: bool = False
) -> vol.Schema:
    fields: dict[Any, Any] = {
        vol.Required(CONF_PERSON_NAME): TextSelector(),
        vol.Required(CONF_USER_ID, default=NO_USER): _user_selector(hass, users),
        vol.Optional(CONF_NOTIFY_SERVICES, default=[]): _notify_selector(hass),
    }
    if new:
        fields[vol.Required(CONF_TRACK_BODY, default=True)] = BooleanSelector()
    fields[vol.Optional(CONF_HEIGHT)] = NumberSelector(
        NumberSelectorConfig(
            min=MIN_HEIGHT,
            max=MAX_HEIGHT,
            step=0.5,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="cm",
        )
    )
    return vol.Schema(fields)


def _clean_person(user_input: dict[str, Any]) -> dict[str, Any]:
    user_id = user_input.get(CONF_USER_ID)
    data: dict[str, Any] = {
        CONF_PERSON_NAME: user_input[CONF_PERSON_NAME].strip(),
        CONF_USER_ID: None if user_id in (None, "", NO_USER) else user_id,
        CONF_NOTIFY_SERVICES: [
            s.removeprefix("notify.") for s in user_input.get(CONF_NOTIFY_SERVICES, [])
        ],
    }
    if height := user_input.get(CONF_HEIGHT):
        data[CONF_HEIGHT] = round(float(height), 1)
    return data


def default_measurements(language: str) -> list[ConfigSubentryData]:
    """Weight daily and waist on Mondays, both with a reminder at 07:00."""
    return [
        ConfigSubentryData(
            data=default_subentry_data(metric),
            subentry_type=SUBENTRY_MEASUREMENT,
            title=metric_title(metric.key, language),
            unique_id=metric.key,
        )
        for metric in METRICS.values()
        if metric.default
    ]


class PillReminderConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create one config entry per person."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the person and their phones."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _clean_person(user_input)
            if not data[CONF_PERSON_NAME]:
                errors[CONF_PERSON_NAME] = "name_required"
            else:
                await self.async_set_unique_id(
                    data[CONF_USER_ID] or slugify(data[CONF_PERSON_NAME])
                )
                self._abort_if_unique_id_configured()
                track_body = user_input.get(CONF_TRACK_BODY, True)
                return self.async_create_entry(
                    title=data[CONF_PERSON_NAME],
                    data=data,
                    options={},
                    subentries=(
                        default_measurements(self.hass.config.language or "en")
                        if track_body
                        else ()
                    ),
                )

        schema = _person_schema(self.hass, await _async_users(self.hass), new=True)
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change person, HA user or phones."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _clean_person(user_input)
            if not data[CONF_PERSON_NAME]:
                errors[CONF_PERSON_NAME] = "name_required"
            else:
                return self.async_update_and_abort(entry, title=data[CONF_PERSON_NAME], data=data)

        suggested = dict(entry.data)
        suggested[CONF_USER_ID] = entry.data.get(CONF_USER_ID) or NO_USER
        schema = _person_schema(self.hass, await _async_users(self.hass))
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or suggested),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Reminder behaviour."""
        return PillReminderOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Medications and tracked measurements are subentries of a person."""
        return {
            SUBENTRY_MEDICATION: MedicationSubentryFlow,
            SUBENTRY_MEASUREMENT: MeasurementSubentryFlow,
        }


class PillReminderOptionsFlow(OptionsFlow):
    """Repeat, snooze, escalation and history settings."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the options form."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {
                key: int(value) if isinstance(value, float) else value
                for key, value in user_input.items()
            }
            data[CONF_ESCALATION_SERVICES] = [
                s.removeprefix("notify.") for s in data.get(CONF_ESCALATION_SERVICES, [])
            ]
            if data.get(CONF_ESCALATION_ENABLED) and not data[CONF_ESCALATION_SERVICES]:
                errors[CONF_ESCALATION_SERVICES] = "escalation_target_required"
            else:
                return self.async_create_entry(data=data)

        schema = vol.Schema(
            {
                vol.Required(CONF_REPEAT_INTERVAL, default=DEFAULT_REPEAT_INTERVAL): _minutes(
                    1, 240
                ),
                vol.Required(CONF_MAX_REMINDERS, default=DEFAULT_MAX_REMINDERS): _minutes(
                    1, 50, "×"
                ),
                vol.Required(CONF_SNOOZE_MINUTES, default=DEFAULT_SNOOZE_MINUTES): _minutes(1, 240),
                vol.Required(
                    CONF_TIME_SENSITIVE, default=DEFAULT_TIME_SENSITIVE
                ): BooleanSelector(),
                vol.Required(
                    CONF_PERSISTENT_NOTIFICATION, default=DEFAULT_PERSISTENT_NOTIFICATION
                ): BooleanSelector(),
                vol.Required(
                    CONF_ESCALATION_ENABLED, default=DEFAULT_ESCALATION_ENABLED
                ): BooleanSelector(),
                vol.Required(CONF_ESCALATE_AFTER, default=DEFAULT_ESCALATE_AFTER): _minutes(
                    1, 50, "×"
                ),
                vol.Optional(CONF_ESCALATION_SERVICES, default=[]): _notify_selector(self.hass),
                vol.Required(CONF_NOTIFY_MISSED, default=DEFAULT_NOTIFY_MISSED): BooleanSelector(),
                vol.Required(CONF_RETENTION_DAYS, default=DEFAULT_RETENTION_DAYS): _minutes(
                    7, 3650, "d"
                ),
                vol.Required(CONF_MEASUREMENT_REPEAT, default=DEFAULT_MEASUREMENT_REPEAT): _minutes(
                    0, 720
                ),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                schema, user_input or self.config_entry.options
            ),
            errors=errors,
        )


def _medication_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_NAME): TextSelector(),
            vol.Optional(CONF_DOSAGE, default=""): TextSelector(),
            vol.Required(CONF_TIMES): TextSelector(
                TextSelectorConfig(type=TextSelectorType.TIME, multiple=True)
            ),
            vol.Required(CONF_WEEKDAYS, default=[str(d) for d in ALL_WEEKDAYS]): SelectSelector(
                SelectSelectorConfig(
                    options=[str(d) for d in ALL_WEEKDAYS],
                    multiple=True,
                    mode=SelectSelectorMode.LIST,
                    translation_key="weekdays",
                )
            ),
            vol.Required(CONF_EARLY_MINUTES, default=DEFAULT_EARLY_MINUTES): _minutes(0, 720),
            vol.Required(CONF_LATE_MINUTES, default=DEFAULT_LATE_MINUTES): _minutes(5, 1440),
        }
    )


class MedicationSubentryFlow(ConfigSubentryFlow):
    """Add or edit a medication."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Add a medication."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = validate_medication(user_input)
            if not errors:
                data[CONF_CREATED_AT] = dt_util.utcnow().isoformat()
                return self.async_create_entry(title=data[CONF_NAME], data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(_medication_schema(), user_input),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit a medication."""
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = validate_medication(user_input)
            if not errors:
                data[CONF_CREATED_AT] = subentry.data.get(
                    CONF_CREATED_AT, dt_util.utcnow().isoformat()
                )
                return self.async_update_and_abort(
                    self._get_entry(), subentry, title=data[CONF_NAME], data=data
                )

        suggested = dict(subentry.data)
        suggested[CONF_WEEKDAYS] = [str(d) for d in subentry.data.get(CONF_WEEKDAYS, [])]
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                _medication_schema(), user_input or suggested
            ),
            errors=errors,
        )


def _measurement_reminder_fields() -> dict[Any, Any]:
    return {
        vol.Required(CONF_REMINDER_ENABLED, default=True): BooleanSelector(),
        vol.Required(CONF_REMINDER_TIME, default=DEFAULT_REMINDER_TIME): TimeSelector(),
        vol.Required(CONF_WEEKDAYS, default=[str(d) for d in ALL_WEEKDAYS]): SelectSelector(
            SelectSelectorConfig(
                options=[str(d) for d in ALL_WEEKDAYS],
                multiple=True,
                mode=SelectSelectorMode.LIST,
                translation_key="weekdays",
            )
        ),
    }


class MeasurementSubentryFlow(ConfigSubentryFlow):
    """Track a measurement type (weight, waist) or change its reminder."""

    def _untracked(self) -> list[str]:
        tracked = {
            sub.data.get(CONF_METRIC)
            for sub in self._get_entry().subentries.values()
            if sub.subentry_type == SUBENTRY_MEASUREMENT
        }
        return [key for key in METRICS if key not in tracked]

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Track a measurement type."""
        available = self._untracked()
        if not available:
            return self.async_abort(reason="all_tracked")
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = validate_measurement(user_input)
            if not errors and data[CONF_METRIC] not in available:
                errors[CONF_METRIC] = "already_tracked"
            if not errors:
                return self.async_create_entry(
                    title=metric_title(data[CONF_METRIC], self.hass.config.language or "en"),
                    data=data,
                    unique_id=data[CONF_METRIC],
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_METRIC, default=available[0]): SelectSelector(
                    SelectSelectorConfig(
                        options=available,
                        mode=SelectSelectorMode.DROPDOWN,
                        translation_key="metric",
                    )
                ),
                **_measurement_reminder_fields(),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Change the reminder of a measurement type."""
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = validate_measurement(
                {**user_input, CONF_METRIC: subentry.data.get(CONF_METRIC)}
            )
            if not errors:
                return self.async_update_and_abort(self._get_entry(), subentry, data=data)

        suggested = dict(subentry.data)
        suggested[CONF_WEEKDAYS] = [str(d) for d in subentry.data.get(CONF_WEEKDAYS, [])]
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(_measurement_reminder_fields()), user_input or suggested
            ),
            errors=errors,
            description_placeholders={"metric": subentry.title},
        )
