"""Constants for the Pill Reminder integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "pill_reminder"

# Config entry (person)
CONF_PERSON_NAME: Final = "person_name"
CONF_USER_ID: Final = "user_id"
CONF_NOTIFY_SERVICES: Final = "notify_services"

# Options (per person)
CONF_REPEAT_INTERVAL: Final = "repeat_interval"
CONF_MAX_REMINDERS: Final = "max_reminders"
CONF_SNOOZE_MINUTES: Final = "snooze_minutes"
CONF_ESCALATION_ENABLED: Final = "escalation_enabled"
CONF_ESCALATE_AFTER: Final = "escalate_after"
CONF_ESCALATION_SERVICES: Final = "escalation_services"
CONF_NOTIFY_MISSED: Final = "notify_missed"
CONF_TIME_SENSITIVE: Final = "time_sensitive"
CONF_PERSISTENT_NOTIFICATION: Final = "persistent_notification"
CONF_RETENTION_DAYS: Final = "retention_days"

DEFAULT_REPEAT_INTERVAL: Final = 10
DEFAULT_MAX_REMINDERS: Final = 6
DEFAULT_SNOOZE_MINUTES: Final = 15
DEFAULT_ESCALATION_ENABLED: Final = False
DEFAULT_ESCALATE_AFTER: Final = 3
DEFAULT_NOTIFY_MISSED: Final = True
DEFAULT_TIME_SENSITIVE: Final = True
DEFAULT_PERSISTENT_NOTIFICATION: Final = False
DEFAULT_RETENTION_DAYS: Final = 365

# Subentry (medication)
SUBENTRY_MEDICATION: Final = "medication"
CONF_NAME: Final = "name"
CONF_DOSAGE: Final = "dosage"
CONF_TIMES: Final = "times"
CONF_WEEKDAYS: Final = "weekdays"
CONF_EARLY_MINUTES: Final = "early_minutes"
CONF_LATE_MINUTES: Final = "late_minutes"
CONF_CREATED_AT: Final = "created_at"

DEFAULT_EARLY_MINUTES: Final = 30
DEFAULT_LATE_MINUTES: Final = 120
ALL_WEEKDAYS: Final = [0, 1, 2, 3, 4, 5, 6]

# Notification actions (Companion App)
ACTION_TAKEN: Final = "PR_TAKEN"
ACTION_SNOOZE: Final = "PR_SNOOZE"
ACTION_SEPARATOR: Final = "::"
MOBILE_APP_ACTION_EVENT: Final = "mobile_app_notification_action"
NOTIFICATION_CHANNEL: Final = "Pill Reminder"

# Events fired by the integration
EVENT_DOSE_DUE: Final = f"{DOMAIN}_dose_due"
EVENT_DOSE_TAKEN: Final = f"{DOMAIN}_dose_taken"
EVENT_DOSE_MISSED: Final = f"{DOMAIN}_dose_missed"
EVENT_DOSE_SKIPPED: Final = f"{DOMAIN}_dose_skipped"
EVENT_DOSE_SNOOZED: Final = f"{DOMAIN}_dose_snoozed"
EVENT_REMINDER_SENT: Final = f"{DOMAIN}_reminder_sent"
EVENT_ESCALATED: Final = f"{DOMAIN}_escalated"

ALL_EVENTS: Final = (
    EVENT_DOSE_DUE,
    EVENT_DOSE_TAKEN,
    EVENT_DOSE_MISSED,
    EVENT_DOSE_SKIPPED,
    EVENT_DOSE_SNOOZED,
    EVENT_REMINDER_SENT,
    EVENT_ESCALATED,
)

# Event / service attributes
ATTR_PERSON: Final = "person"
ATTR_MEDICATION: Final = "medication"
ATTR_MEDICATION_ID: Final = "medication_id"
ATTR_DOSE_ID: Final = "dose_id"
ATTR_SCHEDULED: Final = "scheduled"
ATTR_STATUS: Final = "status"
ATTR_SOURCE: Final = "source"
ATTR_REMINDERS_SENT: Final = "reminders_sent"
ATTR_TAKEN_AT: Final = "taken_at"
ATTR_START: Final = "start"
ATTR_END: Final = "end"
ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"

# Sources of an acknowledgement
SOURCE_BUTTON: Final = "button"
SOURCE_NOTIFICATION: Final = "notification"
SOURCE_SERVICE: Final = "service"
SOURCE_AUTOMATIC: Final = "automatic"

# Services
SERVICE_MARK_TAKEN: Final = "mark_taken"
SERVICE_SNOOZE: Final = "snooze"
SERVICE_SKIP: Final = "skip"
SERVICE_GET_HISTORY: Final = "get_history"
SERVICE_EXPORT_HISTORY: Final = "export_history"

STORAGE_VERSION: Final = 1
EXPORT_DIR: Final = DOMAIN

# How far back the scheduler looks for unresolved doses on startup
RESTORE_LOOKBACK_HOURS: Final = 48


# ---------------------------------------------------------------- measurements
# Person (config entry data)
CONF_HEIGHT: Final = "height"
CONF_TRACK_BODY: Final = "track_body"  # only in the "add person" form
MIN_HEIGHT: Final = 50.0
MAX_HEIGHT: Final = 250.0

# Options
CONF_MEASUREMENT_REPEAT: Final = "measurement_repeat_interval"
DEFAULT_MEASUREMENT_REPEAT: Final = 120  # minutes, 0 = no repeat

# Subentry (tracked measurement type, e.g. weight)
SUBENTRY_MEASUREMENT: Final = "measurement"
CONF_METRIC: Final = "metric"
CONF_REMINDER_ENABLED: Final = "reminder_enabled"
CONF_REMINDER_TIME: Final = "reminder_time"
DEFAULT_REMINDER_TIME: Final = "07:00"

SOURCE_DASHBOARD: Final = "dashboard"

EVENT_MEASUREMENT_ADDED: Final = f"{DOMAIN}_measurement_added"
EVENT_MEASUREMENT_REMINDER: Final = f"{DOMAIN}_measurement_reminder_sent"

ATTR_METRIC: Final = "metric"
ATTR_VALUE: Final = "value"
ATTR_MEASURED_AT: Final = "measured_at"
ATTR_DATE: Final = "date"

SERVICE_ADD_MEASUREMENT: Final = "add_measurement"
SERVICE_DELETE_MEASUREMENT: Final = "delete_measurement"
SERVICE_GET_MEASUREMENTS: Final = "get_measurements"
SERVICE_EXPORT_MEASUREMENTS: Final = "export_measurements"

MEASUREMENT_CHANNEL: Final = "Pill Reminder measurements"


def signal_update(entry_id: str) -> str:
    """Dispatcher signal sent whenever a person's state changes."""
    return f"{DOMAIN}_{entry_id}_update"
