# Changelog

All releases of Health Tracker (formerly Pill Reminder). Each release is also on [GitHub](https://github.com/GuidoJeuken-6512/pill-reminder/releases).

## v0.7.1 – Dashboard made for phones

*Released 2026-11-21* · [GitHub release](https://github.com/GuidoJeuken-6512/pill-reminder/releases/tag/v0.7.1)

### Dashboard made for phones

The generated **Health** dashboard was reworked for narrow screens – still with Home Assistant's own cards only.

- Cards use the full or half width of a section; nothing is squeezed into thirds any more, and labels are no longer cut off.
- Each medication and measurement has its own heading, with the next dose, the last intake or the measurement time as a badge next to it.
- **Today:** Status, Confirm, Skip and Remind two by two per medication.
- **As needed:** a wide **Log intake** button; with a monthly limit, a gauge shows the intake days against the limit (amber from 70 %, red at the limit).
- **Summary:** today's counts next to the heading, both adherence gauges side by side.
- **Body:** full-width input forms, BMI and waist-to-height gauges side by side.
- **Manage:** one full-width card per medication.

No configuration changes; the dashboard updates itself after the update.

## v0.7.0 – Health Tracker: on-demand medication

*Released 2026-11-20* · [GitHub release](https://github.com/GuidoJeuken-6512/pill-reminder/releases/tag/v0.7.0)

### Health Tracker (formerly Pill Reminder)

The integration is now called **Health Tracker**. Only the name changed: the domain stays `pill_reminder`, so all persons, medications, doses, measurements, entity ids, actions, events and automations are kept. Nothing needs to be set up again.

### On-demand medication

For medication taken **as needed**, e.g. for migraine – not *whether* it was taken, but **how often**.

- New **Add on-demand medication** (integration entry or **Manage** tab): name, dosage, optional limits. No intake times, no reminders.
- **Taken** button per intake.
- Counts: intakes **today**, **this month**, **last month**, **30 days**, **intake days this month** (several intakes on one day = one day), last intake. Monthly bar chart from the long-term statistics.
- Optional **limits**: days per month (e.g. 10 for triptans) and intakes per day. When reached: `binary_sensor.<name>_limit_reached` turns on and the phones get one warning (once per month / day).
- New **As needed** section in the dashboard; add, edit and delete in the **Manage** tab.
- Actions: `log_intake` (with `taken_at` to add a forgotten intake), `delete_intake`, `get_intakes`, `export_intakes` (CSV). `mark_taken` also works.
- Events: `pill_reminder_intake_taken`, `pill_reminder_intake_limit_reached` (shown in the logbook).

Details: [user guide → On-demand medication](https://github.com/GuidoJeuken-6512/pill-reminder/blob/main/docs/user-guide.md#on-demand-medication-as-needed)

## v0.6.0 – Measurements in the dashboard

*Released 2026-11-09* · [GitHub release](https://github.com/GuidoJeuken-6512/pill-reminder/releases/tag/v0.6.0)

### Add and remove measurements in the dashboard

- New **Track** switches in the **Manage** tab: *Track weight*, *Track waist circumference*, *Track blood pressure*.
- Switching on adds the measurement with a reminder at 07:00; the **Body** tab appears if it was missing.
- Switching off removes the measurement from the dashboard. Stored values are kept and come back when it is switched on again.
- The person can do this without admin rights. **Add measurement** in the integration settings still works.

## v0.5.0 – Blood pressure

*Released 2026-11-09* · [GitHub release](https://github.com/GuidoJeuken-6512/pill-reminder/releases/tag/v0.5.0)

### Blood pressure and save buttons

- **Blood pressure** as a new measurement (**Add measurement** on a person's entry): systolic, diastolic and optional pulse in one reading.
  - Class of the last reading (ESC/ESH: optimal, normal, high normal, hypertension grade 1–3), 7-day averages, change and trend per value, 90-day graph.
  - Reminder shows the last reading, e.g. "128/82 mmHg".
  - `pill_reminder.add_measurement` accepts `metric: blood_pressure` with `systolic`, `diastolic`, `pulse`.
- **Save button** per measurement: the input fields only remember the value, **Save** stores it. Input now works in the Companion App on phones. Weight still starts with the last value.
- Releases now include `pill_reminder.zip`, which HACS installs.
- README badges for downloads and installs.

Existing weight and waist values and entity ids stay unchanged. Diagnostics contain no measured values.

## v0.4.0 – Body measurements

*Released 2026-11-06* · [GitHub release](https://github.com/GuidoJeuken-6512/pill-reminder/releases/tag/v0.4.0)

### Body measurements – one app for medication and health

Pill Reminder now also tracks **weight** and **waist circumference**.

- New measurement type next to medication: **Add measurement** on a person's entry. New persons track weight (daily) and waist (Mondays) by default, each with a reminder at 07:00; this can be turned off.
- **Height** on the person (optional), used for **BMI** (WHO class) and **waist-to-height ratio** (class).
- Change over 7 and 30 days, **trend** per week (rising / falling / stable), long-term statistics for 90-day graphs.
- Reminder per measurement with one repeat (configurable, default 2 h), tapping it opens the dashboard. Time, weekdays and on/off can be changed in the dashboard without a reload.
- Dashboard renamed to **Health** (`/pill-reminder` stays): per person a medication, a **Body** and a **Manage** tab.
- New actions: `add_measurement` (e.g. from a smart scale), `delete_measurement`, `get_measurements`, `export_measurements`.
- Diagnostics contain no measured values and no height.
- New [user guide](https://github.com/GuidoJeuken-6512/pill-reminder/blob/main/docs/user-guide.md).

Existing persons keep working unchanged (medication only); add measurements via **Add measurement**.

## v0.3.1 – privacy fix for diagnostics

*Released 2026-11-04* · [GitHub release](https://github.com/GuidoJeuken-6512/pill-reminder/releases/tag/v0.3.1)

#### Fixed
- Diagnostics no longer contain personal or health data: person name, config entry and medication titles, `unique_id`, Home Assistant user ids, notify services, medication names, dosages and `medication_name` are redacted. Open doses are redacted as well, and the medications block is keyed by id only.

Diagnostics files are often shared in public issues – please update.

## v0.3.0 – first public release

*Released 2026-11-04* · [GitHub release](https://github.com/GuidoJeuken-6512/pill-reminder/releases/tag/v0.3.0)

First public release of **Pill Reminder** for Home Assistant (2026.8 or newer).

#### Features
- Several people, several medications per person, several intake times per medication, selectable weekdays
- Phone notifications (Companion App) with **Taken** and **Later** buttons; repeated reminders replace each other and disappear once confirmed
- Configurable repeat interval, maximum reminders, escalation to another person and a message when a dose was missed
- **Dashboard created automatically** ("Medication"): one view per person, visible only to that person and administrators, plus a **Manage medication** tab to add, edit, pause and delete medications – no admin rights needed
- Tracking of every dose (scheduled/actual time, reminders, escalation, source); restarts lose nothing
- Adherence 7/30 days, streak, daily counters, calendar with details, logbook, `get_history` / `export_history` (CSV) actions
- English and German translations

#### Installation
HACS → ⋮ → Custom repositories → `https://github.com/GuidoJeuken-6512/pill-reminder` (Integration) → install **Pill Reminder** → restart Home Assistant.
