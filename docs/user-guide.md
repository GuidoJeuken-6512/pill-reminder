# Pill Reminder – User guide

Pill Reminder reminds people in your household to take their medication and to enter their weight, waist circumference and blood pressure. It records every dose and every measurement and shows how regularly the medication was taken, the BMI, the waist-to-height ratio, the blood pressure class and the trend. This guide explains how it works, every setting, the dashboard, the entities, and how to use it in your own automations.

> **Note:** Pill Reminder is a reminder aid, not a medical device. BMI, waist-to-height ratio and blood pressure classes are general reference values for adults, not a diagnosis. Nothing here replaces medical advice. Always keep a second way of remembering important medication.

## Contents

1. [How it works](#1-how-it-works)
2. [Installation](#2-installation)
3. [Setting up a person](#3-setting-up-a-person)
4. [Adding medications](#4-adding-medications)
5. [Reminder settings](#5-reminder-settings)
6. [The life of a dose](#6-the-life-of-a-dose)
7. [Body measurements](#7-body-measurements)
8. [Phone notifications](#8-phone-notifications)
9. [The dashboard](#9-the-dashboard)
10. [Entities](#10-entities)
11. [Statistics](#11-statistics)
12. [Actions](#12-actions)
13. [Events and automation examples](#13-events-and-automation-examples)
14. [Data, storage and privacy](#14-data-storage-and-privacy)
15. [Troubleshooting](#15-troubleshooting)
16. [FAQ](#16-faq)

---

## 1. How it works

- **Person** – each person is one entry of the integration. A person has a name, optionally a Home Assistant user (for the dashboard), one or more phones and optionally a height.
- **Medication** – each person can have any number of medications. A medication has a name, an optional dosage or note, one or more **intake times** and the **weekdays** on which it is taken.
- **Measurement** – a person can track **weight**, **waist circumference** and **blood pressure**, each with its own reminder. See [Body measurements](#7-body-measurements).
- **Dose** – every intake time on every scheduled day creates one dose. Each dose ends with exactly one final status: *taken*, *missed*, *skipped* or *paused*. All doses are stored, which is the basis for the statistics, the calendar and the export.

At an intake time the dose becomes **due**. The person gets a push notification with **Taken** and **Later** buttons. The reminder repeats until the dose is confirmed or its time window has passed. If it is not confirmed in time, the dose is logged as **missed**.

## 2. Installation

Requires Home Assistant **2026.8** or newer.

**HACS (recommended)**

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=GuidoJeuken-6512&repository=pill-reminder&category=integration)

1. Click the button above, or open HACS → ⋮ → **Custom repositories** and add `https://github.com/GuidoJeuken-6512/pill-reminder` with the type **Integration**.
2. Install **Pill Reminder**.
3. Restart Home Assistant.

**Manual**

Copy the folder `custom_components/pill_reminder` into `/config/custom_components/` and restart Home Assistant.

**Phones:** Push notifications with buttons need the [Home Assistant Companion App](https://companion.home-assistant.io/) on each phone. Each phone with the app gets a notify action named `notify.mobile_app_<phone>`.

## 3. Setting up a person

**Settings → Devices & services → Add integration → Pill Reminder**

| Field | Meaning |
|---|---|
| **Name** | Shown in notifications and as the dashboard tab. |
| **Home Assistant user** | The user who can see this person's dashboard tab. Choose "No user" if the person has no Home Assistant login; then only administrators see the tab. |
| **Phones (notify services)** | The `notify.mobile_app_…` actions that receive the reminders. You can choose several, for example phone and tablet. |
| **Track weight and waist circumference** | On by default. Adds weight (daily) and waist (Mondays), both with a reminder at 07:00. Turn it off for a person who only takes medication. |
| **Height** | Optional. Needed for BMI and waist-to-height ratio. Can also be set later in the dashboard. |

Add each person as a separate entry. To change these values later, open the person's entry and choose **Reconfigure**.

> `notify.send_message` and `notify.persistent_notification` are not offered as phones. They cannot show buttons. Use the separate option in [Reminder settings](#5-reminder-settings) for a notification inside Home Assistant.

## 4. Adding medications

There are two ways to add a medication:

- **In the dashboard:** open the **Manage** tab and fill in **New medication**. The person can do this without admin rights. See [the dashboard](#9-the-dashboard).
- **In the integration entry:** **Settings → Devices & services → Pill Reminder → Add medication** on the person's entry.

| Field | Default | Meaning |
|---|---|---|
| **Name** | – | For example "Ramipril". |
| **Dosage / note** | empty | Free text, for example "5 mg" or "with food". It is shown in the notification. |
| **Intake times** | – | One or more times, for example `08:00` and `20:00`. |
| **Weekdays** | every day | The days on which the medication is taken. |
| **Can be confirmed early** | 30 min | How many minutes before the intake time **Taken** is accepted (0–720). |
| **Counts as missed after** | 120 min | How many minutes after the intake time the dose is logged as missed (5–1440). Reminders repeat until then. |

**Input formats in the dashboard**

- **Times:** `08:00, 20:00`
- **Weekdays:** `daily`, `Mon-Fri`, `Mon, Wed, Fri` or `Sat-Sun`. German also works: `täglich`, `Mo-Fr`, `Mo, Mi, Fr`.

**Overlapping windows are rejected.** Every intake time has a confirmation window that runs from "early" to "missed after". Two windows of the same medication must not overlap, because a **Taken** press must refer to exactly one dose. For example, `08:00` and `09:00` with the defaults (window 07:30–10:00 and 08:30–11:00) are rejected. Reduce the minutes or space the times further apart.

**Changing a medication** takes effect immediately. **Deleting** a medication removes its entities; its past doses stay in the history and the export.

## 5. Reminder settings

Open the person's entry and click the gear icon (**Configure**). The settings apply to all medications of that person; the last one applies to the measurements.

| Setting | Default | Range | Meaning |
|---|---|---|---|
| **Repeat reminder every** | 10 min | 1–240 | Time between two reminders of the same dose. |
| **Maximum number of reminders** | 6 | 1–50 | After this many reminders the phone stays quiet. The dose stays due until it counts as missed. |
| **Snooze duration** | 15 min | 1–240 | How long **Later** postpones the reminder. |
| **Time-sensitive notification** | on | – | iOS: breaks through Focus modes. Android: high priority. |
| **Also show as persistent notification** | off | – | Also shows the reminder in the Home Assistant notification area. **These are visible to all users.** |
| **Escalate to another person** | off | – | Notify a second person, for example a relative or carer, when the dose is not confirmed. |
| **Escalate after this many reminders** | 3 | 1–50 | When escalation is on, the escalation is sent with the next reminder after this many unconfirmed reminders. |
| **Escalation contacts** | – | – | `notify.mobile_app_…` actions of the escalation contacts. Required when escalation is on. |
| **Send a message when a dose was missed** | on | – | Sent to the person and, with escalation on, to the escalation contacts. |
| **Keep history for** | 365 days | 7–3650 | Older doses are deleted every night at midnight. Measurements are kept. |
| **Repeat a measurement reminder after** | 120 min | 0–720 | One repeat if no value was entered, only until midnight. 0 = no repeat. |

## 6. The life of a dose

### Statuses

| Status | Meaning | Final? |
|---|---|---|
| `scheduled` | Nothing is due right now; the next dose is in the future. | – |
| `due` | The intake time has passed and the dose is not confirmed yet. | no |
| `snoozed` | The person pressed **Later**; the reminder comes back after the snooze duration. | no |
| `taken` | Confirmed. | yes |
| `missed` | Not confirmed within the window. | yes |
| `skipped` | Skipped on purpose, for example on a doctor's advice. Not counted as missed. | yes |
| `paused` | Reminders were paused for this medication. Not counted as missed. | yes |

### Timeline with the default settings

Medication at **08:00**, with all default settings and escalation turned on:

| Time | What happens |
|---|---|
| 07:30 | The window opens. **Taken** is accepted from now on; a dose confirmed now gets no reminder at 08:00. |
| 08:00 | The dose becomes `due`. Reminder 1 is sent to the phones. |
| 08:10, 08:20 | Reminders 2 and 3 are sent. Each one replaces the previous notification. |
| 08:30 | Three reminders are unconfirmed, so the escalation goes to the escalation contacts. Reminder 4 is sent. |
| 08:40, 08:50 | Reminders 5 and 6 are sent. This is the maximum; after that the phone stays quiet. |
| 10:00 | The window closes. The dose is logged as `missed`, and the "missed" message is sent. |

If the person presses **Taken** at any point, the notification disappears from all phones (and from the escalation contacts). No more reminders are sent.

### Later (snooze)

**Later** removes the notification and sends a new reminder after the snooze duration. The snooze does **not** extend the window: if the dose is still unconfirmed at 10:00, it is missed.

### Taken, Skip and which dose they refer to

**Taken** and **Skip** always refer to the oldest open dose of the medication. If no dose is open, they refer to the dose whose window contains the current time, for example a dose taken a bit early. If there is no such dose, Home Assistant shows the error "No dose of … is due right now".

### Correcting a dose afterwards

If someone took the medication but forgot to confirm it, use the action `pill_reminder.mark_taken` with `taken_at`. This turns a `missed` dose into `taken` with the real time. `taken_at` must lie within the window of that dose and must not be in the future.

### Pausing

The **Reminders** switch of a medication pauses it, for example for a hospital stay or a holiday. While paused, no reminders are sent and doses are logged as `paused`. Open doses are closed as `paused` immediately.

### Restarts and outages

Doses are saved on disk. After a restart of Home Assistant:

- open doses continue with their reminders and snooze timers,
- doses whose window ended while Home Assistant was down (up to 48 hours back) are logged as `missed`.

## 7. Body measurements

### What is tracked

| Measurement | Unit | Default reminder | Allowed values |
|---|---|---|---|
| **Weight** | kg | every day, 07:00 | 20–400 |
| **Waist circumference** | cm | Mondays, 07:00 | 30–250 |
| **Blood pressure** | systolic and diastolic in mmHg, pulse in bpm | every day, 07:00 | 60–260 / 30–160 / 30–220 |

A new person tracks weight and waist, unless **Track weight and waist circumference** was turned off. Blood pressure is added with **Add measurement**. Each measurement is a sub-entry of the person:

- **Add a measurement** (for example after turning it off): **Settings → Devices & services → Pill Reminder → Add measurement** on the person's entry.
- **Remove a measurement:** delete its sub-entry on the person's entry. Its values stay stored.
- **Change the reminder:** in the dashboard (**Manage** tab) or via the sub-entry's ⋮ → **Edit reminder**. Changes apply immediately.

### Entering values

- In the dashboard (**Body** tab): type the values into the input fields and press **Save**. The reading is stored with the current time. Nothing is stored before **Save** – this also makes input work in the Companion App on phones.
- **Weight and waist:** the field shows the last value. **Save** without typing stores the same value again.
- **Blood pressure:** the fields are empty. Systolic and diastolic are required, pulse is optional; systolic must be higher than diastolic. After saving, the fields are empty again.
- With the action `pill_reminder.add_measurement`, for example from a smart scale or to enter an older value. See [Actions](#12-actions).

Several values on one day are all stored. For change and trend, the **last value of each day** counts.

### Reminders

- At the reminder time on a reminder day, the phones get a notification, for example "⚖️ Time to step on the scale – Anna, please enter today's value. Last value: 81.2 kg (Nov 05)".
- No reminder is sent if a value of that type was already entered that day, also before the reminder time.
- If nothing is entered, the reminder is repeated **once** after the repeat interval (default 2 hours), but never after midnight.
- Tapping the notification opens the person's **Body** tab.
- When a value is entered, the notification disappears from all phones.
- `binary_sensor.anna_weight_due` is on from the reminder time until a value is entered or the day ends.
- After a restart, a reminder that was missed earlier that day is sent; reminders that were already sent are not repeated.

### Evaluation

| Value | How it is calculated |
|---|---|
| **BMI** | weight (kg) ÷ height (m)². Classes (WHO, adults): < 18.5 underweight, < 25 normal, < 30 overweight, < 35 obesity I, < 40 obesity II, from 40 obesity III. |
| **Waist-to-height ratio (WHtR)** | waist (cm) ÷ height (cm). Classes: < 0.5 healthy, < 0.6 increased risk, from 0.6 high risk. |
| **Change 7 / 30 days** | Latest value minus the last value from at least 7 (30) days ago. Empty if there is no value in that period or the reference value is older than twice the period. |
| **Trend** | Slope of a straight line through the daily values of the last 14 days, in kg (cm) per week. Needs at least 3 days with values. |
| **Trend direction** | rising / falling / stable. "Stable" means less than 0.2 kg, 0.5 cm or 2 mmHg (bpm) per week. |
| **Blood pressure class** | Last reading, ESC/ESH classes for office values; the higher class of both values counts: optimal < 120/80, normal from 120/80, high normal from 130/85, hypertension grade 1 from 140/90, grade 2 from 160/100, grade 3 from 180/110. At home, averages from 135/85 already count as high. |
| **7-day average** (blood pressure) | Mean of all readings of the last 7 days, for systolic, diastolic and pulse. |

BMI and WHtR stay `unknown` until there is a value and a height. The last values are long-term statistics, so the 90-day graphs and the Home Assistant history show them over years.

**Imperial units:** Home Assistant shows weight and waist in the unit system of your instance. Input is always in kg and cm.

## 8. Phone notifications

A reminder looks like this (Home Assistant language English):

> **💊 Time for Ramipril**
> Anna, please take Ramipril (5 mg) (scheduled 08:00). Reminder 2.
> **[Taken]** **[Later (15 min)]**

- The texts follow the Home Assistant system language (English or German; other languages fall back to English).
- All reminders of one dose share a tag, so a repeat replaces the previous notification instead of piling up.
- **Taken** and **Later** work directly from the lock screen; Home Assistant does not need to be open.
- **Android:** medication reminders use the channel **Pill Reminder** with high importance; measurement reminders use **Pill Reminder measurements**. In Android settings you can give this channel its own sound or let it bypass Do Not Disturb.
- **iOS:** with **Time-sensitive notification** turned on, reminders break through Focus modes. The app needs the "Time Sensitive Notifications" permission.

## 9. The dashboard

The integration creates the dashboard **Health** in the sidebar (`/pill-reminder`) automatically. It always shows the current medications and measurements; there is nothing to maintain.

**Who can see what**

- Each person has up to three tabs: their **medication** tab (named after the person), **Body** (only when the person tracks measurements) and **Manage**. With several persons the tabs are called "Body (Anna)" and "Manage (Anna)".
- The tabs are visible only to that person's Home Assistant user and to administrators. Other users do not see them.

**The person's tab**

- **Take now** – appears only while something is due. It holds a large **Taken** button per due medication, plus **Later**.
- **Today** – every medication with its status, the next dose, and the **Taken**, **Skip** and **Remind** buttons. **Remind** is the pause switch.
- **Summary** – taken, missed and skipped today; adherence over 7 and 30 days as gauges; one row per medication.
- **History** – adherence over 30 days and the status of the last 7 days as charts.
- **Calendar** and **Log**.

Charts and gauges appear after the first resolved dose; before that the dashboard shows a short hint instead.

**Body tab**

- **Enter today** – one card per measurement with its input fields and a **Save** button, plus a hint while today's value is still missing.
- One section per measurement: last value, when it was measured, change over 7 and 30 days, trend direction. For blood pressure: last reading, class, 7-day averages and trend directions.
- **BMI & waist-to-height** – gauges with colour bands and the class. They appear once there is a value and a height; before that a hint explains what is missing.
- **History (90 days)** – mean, minimum and maximum per day.

**Manage tab**

- Change name, intake times, weekdays, dosage and both time windows of each medication. Changes take effect immediately.
- **Delete** removes a medication after a confirmation.
- **New medication** with name, times and dosage, then **Add**.
- **Measurements:** the height and, per measurement, reminder on/off, time and weekdays.

The person can do all of this without administrator rights. Invalid input, for example an unknown weekday, is rejected with a message.

**Own dashboards**

The generated dashboard cannot be edited in the dashboard editor. To build your own, start from the examples in [`dashboards/`](../dashboards/):

- `pill_reminder.yaml` – standard cards only; exactly what the generated dashboard looks like for a person with one medication, weight and waist.
- `pill_reminder_plus.yaml` – with [Mushroom](https://github.com/piitaya/lovelace-mushroom) and [ApexCharts](https://github.com/RomRider/apexcharts-card).

If a dashboard with the URL `/pill-reminder` already exists, the integration does not overwrite it and logs a warning.

## 10. Entities

Each person, each medication and each measurement appears as its own device. Entity ids follow the names; the examples are for a person "Anna" with the medication "Ramipril" who tracks weight and waist, Home Assistant language English.

### Per medication

| Entity | Meaning |
|---|---|
| `button.ramipril_taken` | Confirm the current dose. |
| `button.ramipril_snooze` | Postpone the reminder. |
| `button.ramipril_skip` | Skip the dose on purpose. |
| `binary_sensor.ramipril_due` | On while a dose waits for confirmation. |
| `sensor.ramipril_status` | The [status](#statuses) of the medication. |
| `sensor.ramipril_next_dose` | Time of the next dose. |
| `sensor.ramipril_last_taken` | Time of the last confirmed dose. |
| `sensor.ramipril_adherence_7_days`, `sensor.ramipril_adherence_30_days` | Adherence in %. |
| `sensor.ramipril_streak` | Days in a row without a missed dose. |
| `switch.ramipril_reminders` | Off = paused. |

Settings (configuration entities, used by the **Manage** tab):

| Entity | Meaning |
|---|---|
| `text.ramipril_name` | Name. |
| `text.ramipril_intake_times` | For example `08:00, 20:00`. |
| `text.ramipril_weekdays` | For example `Mon-Fri`. |
| `text.ramipril_dosage` | Dosage or note. |
| `number.ramipril_confirm_early_minutes_before` | Can be confirmed early. |
| `number.ramipril_missed_after_minutes` | Counts as missed after. |
| `button.ramipril_delete_medication` | Delete the medication. |

### Per person

| Entity | Meaning |
|---|---|
| `binary_sensor.anna_medication_due` | On while any medication of the person is due. |
| `sensor.anna_open_today` | Doses still open today. |
| `sensor.anna_taken_today`, `sensor.anna_missed_today`, `sensor.anna_skipped_today` | Daily counters; they reset at midnight. |
| `sensor.anna_adherence_7_days`, `sensor.anna_adherence_30_days` | Adherence over all medications. |
| `sensor.anna_streak` | Streak over all medications. |
| `calendar.anna_medication` | All doses as calendar events. |
| `text.anna_new_medication_name`, `…_times`, `…_dosage`, `button.anna_add_medication` | Form for a new medication. |

### Per measurement

Shown for weight; waist works the same way (`…_waist_…`).

| Entity | Meaning |
|---|---|
| `number.anna_weight_enter` | Input field. Shows the last value. |
| `button.anna_weight_save` | Store the input. |
| `sensor.anna_weight` | Last value (long-term statistics). |
| `sensor.anna_weight_measured` | Time of the last value. |
| `sensor.anna_weight_change_7_days`, `sensor.anna_weight_change_30_days` | Change compared to 7 / 30 days ago. |
| `sensor.anna_weight_trend` | Trend in kg per week. |
| `sensor.anna_weight_trend_direction` | rising / falling / stable. |
| `binary_sensor.anna_weight_due` | On while today's value is missing after the reminder time. |
| `switch.anna_weight_reminder` | Reminder on/off. |
| `time.anna_weight_reminder_time` | Reminder time. |
| `text.anna_weight_reminder_weekdays` | Reminder weekdays, for example `daily` or `Mon`. |

Blood pressure (each value field has its own last value, change, trend and trend direction, named after the field):

| Entity | Meaning |
|---|---|
| `number.anna_blood_pressure_systolic`, `number.anna_blood_pressure_diastolic`, `number.anna_blood_pressure_pulse` | Input fields. |
| `button.anna_blood_pressure_save` | Store the reading. |
| `sensor.anna_blood_pressure` | Last reading as text, e.g. `128/82`. |
| `sensor.anna_blood_pressure_category` | Class of the last reading. |
| `sensor.anna_blood_pressure_systolic`, `sensor.anna_blood_pressure_diastolic`, `sensor.anna_blood_pressure_pulse` | Last values (long-term statistics). |
| `sensor.anna_blood_pressure_systolic_7_day_average`, `sensor.anna_blood_pressure_diastolic_7_day_average`, `sensor.anna_blood_pressure_pulse_7_day_average` | 7-day averages. |
| `sensor.anna_blood_pressure_systolic_trend_direction` | Trend direction (likewise for diastolic and pulse). |
| `sensor.anna_blood_pressure_measured`, `binary_sensor.anna_blood_pressure_due`, `switch.anna_blood_pressure_reminder`, `time.anna_blood_pressure_reminder_time`, `text.anna_blood_pressure_reminder_weekdays` | As for weight. |

Per person, only while the person tracks a measurement:

| Entity | Meaning |
|---|---|
| `number.anna_height` | Height in cm. |
| `sensor.anna_bmi`, `sensor.anna_bmi_category` | BMI and WHO class. |
| `sensor.anna_waist_to_height_ratio`, `sensor.anna_waist_to_height_category` | Waist-to-height ratio and class. |

### Attributes

Medication entities have the attributes `person` and `medication`. The **Taken** button also has `due` (due right now) and `actionable` (may be confirmed right now). Use them in your own dashboards to filter independently of language and entity ids, for example with [auto-entities](https://github.com/thomasloven/lovelace-auto-entities).

### Calendar

`calendar.anna_medication` shows every dose as an event:

- ✅ taken, ❌ missed, ⏭️ skipped, ⏸️ paused, and 🕒 for upcoming doses.
- The description contains the dosage, when the dose was taken, the delay, the number of reminders, whether it was escalated, and the source (button, notification or action).
- A taken dose ends at the time it was taken, so delays are visible at a glance.

## 11. Statistics

- **Adherence** = taken ÷ (taken + missed) over the last 7 or 30 days, in %. **Skipped** and **paused** doses do not count: they were a decision, not a forgotten dose. Until the first dose is taken or missed, adherence is `unknown`.
- **Streak** = days in a row, up to today, with at least one taken dose and no missed dose. Days without any doses, for example on a weekly medication, do not break the streak.
- Adherence sensors are stored as long-term statistics, so the Home Assistant history and statistics cards can show them over months.

## 12. Actions

All actions are available in **Developer tools → Actions** and in automations. For the dose actions, `entity_id` may be any entity of the medication, for example its **Taken** button or its status sensor.

### `pill_reminder.mark_taken`

Confirm a dose. With `taken_at`, also afterwards (corrects "missed").

```yaml
action: pill_reminder.mark_taken
data:
  entity_id: button.ramipril_taken
  taken_at: "2026-11-04 08:20:00"   # optional
```

### `pill_reminder.snooze`

Postpone the reminder of the open dose. `minutes` is optional; the default is the snooze duration.

```yaml
action: pill_reminder.snooze
data:
  entity_id: button.ramipril_taken
  minutes: 30
```

### `pill_reminder.skip`

Skip the current dose on purpose.

```yaml
action: pill_reminder.skip
data:
  entity_id: button.ramipril_taken
```

### `pill_reminder.get_history`

Returns the doses as response data. All filters are optional: a person (`config_entry_id`), a medication (`entity_id`), `start`, `end`, and `status` (one or more of `taken`, `missed`, `skipped`, `paused`, `due`, `snoozed`).

```yaml
action: pill_reminder.get_history
data:
  entity_id: button.ramipril_taken
  start: "2026-10-01 00:00:00"
  status: [missed]
response_variable: history
```

Response:

```yaml
people:
  - config_entry_id: 01J…
    person: Anna
    doses:
      - id: …
        medication_name: Ramipril
        scheduled: "2026-10-12T06:00:00+00:00"
        status: missed
        reminders_sent: 6
        escalated: true
        …
```

### `pill_reminder.export_history`

Writes the doses as a CSV file to `/config/pill_reminder/<person>_<date>_<time>.csv`. It takes the same filters as `get_history`, and the response contains the file path. The file uses `;` as the separator and UTF-8, and it opens directly in Excel or LibreOffice.

Columns: `id`, `medication_id`, `medication_name`, `scheduled`, `status`, `resolved_at`, `delay_minutes`, `reminders_sent`, `escalated`, `source`, `user_id`.

### Measurement actions

The person is selected with `config_entry_id` or with `entity_id` (any entity of the person). With only one person, both can be left out. With an entity of a measurement, for example `sensor.anna_weight`, `metric` can be left out too.

**`pill_reminder.add_measurement`** – store a reading. For `weight` or `waist`, `value` is in kg or cm. For `blood_pressure`, use `systolic` and `diastolic` (mmHg) and optionally `pulse`. With `measured_at` an older reading can be entered.

```yaml
action: pill_reminder.add_measurement
data:
  entity_id: sensor.anna_weight
  value: 81.2
  measured_at: "2026-11-01 07:15:00"   # optional
```

```yaml
action: pill_reminder.add_measurement
data:
  metric: blood_pressure
  systolic: 128
  diastolic: 82
  pulse: 64   # optional
```

Values entered with an older `measured_at` count for change and trend, but do not appear in the long-term statistics graph (Home Assistant only records the current state).

**`pill_reminder.delete_measurement`** – delete all values of a `date`, or without a date the most recent reading (for blood pressure all three values).

**`pill_reminder.get_measurements`** – the values as response data, filtered by person, `metric`, `start` and `end`. The response also contains the height.

**`pill_reminder.export_measurements`** – the values as CSV in `/config/pill_reminder/<person>_measurements_<date>_<time>.csv`. Columns: `id`, `metric` (`weight`, `waist`, `systolic`, `diastolic`, `pulse`), `value`, `measured_at`, `source`.

## 13. Events and automation examples

The integration fires these events:

| Event | When |
|---|---|
| `pill_reminder_dose_due` | A dose becomes due. |
| `pill_reminder_reminder_sent` | A reminder was sent (also repeats). |
| `pill_reminder_dose_snoozed` | **Later** was pressed. |
| `pill_reminder_escalated` | The escalation was sent. |
| `pill_reminder_dose_taken` | A dose was confirmed. |
| `pill_reminder_dose_missed` | A dose was logged as missed. |
| `pill_reminder_dose_skipped` | A dose was skipped. |

Each dose event carries `entity_id` (the medication's status sensor), `entry_id`, `person`, `user_id`, `medication`, `medication_id`, `dose_id`, `scheduled`, `status`, `source` and `reminders_sent`. The dose events also appear in the logbook of the medication's status sensor.

Measurements fire two more events:

| Event | When | Data |
|---|---|---|
| `pill_reminder_measurement_added` | A reading was stored. | `person`, `metric`, `values` and `units` (per field), `measured_at`, `source`; for weight and waist also `value` and `unit` |
| `pill_reminder_measurement_reminder_sent` | A measurement reminder was sent. | `person`, `metric`, `count` |

**Flash a light while medication is due**

```yaml
automation:
  - alias: "Medication due – kitchen light"
    triggers:
      - trigger: state
        entity_id: binary_sensor.anna_medication_due
        to: "on"
    actions:
      - action: light.turn_on
        target:
          entity_id: light.kitchen
        data:
          color_name: orange
          flash: long
```

**Announce on a speaker after the third reminder**

```yaml
automation:
  - alias: "Medication – speaker announcement"
    triggers:
      - trigger: event
        event_type: pill_reminder_reminder_sent
    conditions:
      - condition: template
        value_template: "{{ trigger.event.data.reminders_sent == 3 }}"
    actions:
      - action: tts.speak
        target:
          entity_id: tts.home_assistant_cloud
        data:
          media_player_entity_id: media_player.kitchen
          message: >
            {{ trigger.event.data.person }}, please take
            {{ trigger.event.data.medication }}.
```

**Confirm with a physical button (e.g. a Zigbee button at the pill box)**

```yaml
automation:
  - alias: "Pill box button – taken"
    triggers:
      - trigger: state
        entity_id: event.pill_box_button
    conditions:
      - condition: state
        entity_id: button.ramipril_taken
        attribute: actionable
        state: true
    actions:
      - action: button.press
        target:
          entity_id: button.ramipril_taken
```

**Weight from a smart scale**

```yaml
automation:
  - alias: "Scale → Pill Reminder"
    triggers:
      - trigger: state
        entity_id: sensor.smart_scale_weight
    conditions:
      - condition: template
        value_template: "{{ trigger.to_state.state | float(0) > 20 }}"
    actions:
      - action: pill_reminder.add_measurement
        data:
          entity_id: sensor.anna_weight
          value: "{{ trigger.to_state.state }}"
```

**Pause automatically while on holiday**

```yaml
automation:
  - alias: "Holiday – pause vitamin D"
    triggers:
      - trigger: state
        entity_id: input_boolean.holiday
    actions:
      - action: >
          switch.turn_{{ 'off' if trigger.to_state.state == 'on' else 'on' }}
        target:
          entity_id: switch.vitamin_d_reminders
```

## 14. Data, storage and privacy

- All data stays in your Home Assistant. Nothing is sent to external services, except the push notifications through the Companion App.
- Doses are stored per person in `/config/.storage/pill_reminder.<entry_id>`. They are saved a few seconds after each change and are part of the Home Assistant backup.
- Measurements are stored per person in `/config/.storage/pill_reminder.<entry_id>.measurements`, also part of the backup.
- Removing a person deletes their doses and measurements. Deleting a medication or a measurement keeps its history.
- **Diagnostics** (Settings → Devices & services → Pill Reminder → ⋮ → Download diagnostics) are made to be attached to public GitHub issues. Names, Home Assistant user ids, phones, medication names, dosages, the height and all measured values are removed. What stays are the times, weekdays, statuses, counters and timestamps needed to find a bug.

## 15. Troubleshooting

**No notification arrives on the phone**

- Check that the person's **Phones** are `notify.mobile_app_…` actions. Open the entry, choose **Reconfigure** and check the selection.
- Test the phone in **Developer tools → Actions** with `notify.mobile_app_<phone>`.
- Check the log for "Notify service … does not exist" or "cannot deliver push notifications with buttons".
- Android: the channel **Pill Reminder** must not be turned off in the app's notification settings.

**"Taken" in the notification does nothing**

The phone must be able to reach Home Assistant at that moment. With remote access missing, the press only works on the home network.

**"No dose of … is due right now"**

There is no open dose, and the current time is outside every window. The dose is either confirmed already or still too far in the future; see **Can be confirmed early**.

**The dashboard tab is missing**

- The tab is visible only to the person's Home Assistant user and to administrators. Check **Home Assistant user** under **Reconfigure**.
- After installing or updating, reload the browser page.

**The dashboard shows "No medication yet"**

Add a medication in the **Manage** tab or in the integration entry. A person who only tracks measurements can ignore this tab.

**BMI or waist-to-height ratio stays empty**

The height is missing. Enter it in the **Manage** tab (`number.anna_height`) or under **Reconfigure**.

**The Body tab is missing**

The person tracks no measurement. Add one: **Settings → Devices & services → Pill Reminder → Add measurement**.

**Times are rejected: "confirmation windows overlap"**

See [Overlapping windows are rejected](#4-adding-medications).

**Debug logging**

```yaml
logger:
  logs:
    custom_components.pill_reminder: debug
```

When opening an issue, please attach the diagnostics and the relevant log lines: <https://github.com/GuidoJeuken-6512/pill-reminder/issues>

## 16. FAQ

**Can one person have medications at different times on different days?**
Yes. Add the medication twice, for example "Vitamin D (weekdays)" with `Mon-Fri` and "Vitamin D (weekend)" with `Sat-Sun` at another time.

**Can several people share one phone?**
Yes. Choose the same phone for both people. Every notification names the person.

**Can I take a medication in the evening that is scheduled in the morning?**
Only within the window. Set **Counts as missed after** larger, or use `mark_taken` with `taken_at` afterwards.

**Can I use it only for weight, without medication?**
Yes. The medication tab then just shows a hint; reminders and statistics work for the measurements alone.

**Can I enter values from a smart scale?**
Yes, with an automation and `pill_reminder.add_measurement`. See [Events and automation examples](#13-events-and-automation-examples).

**Does it track pill stock?**
Not yet.

**Is the dashboard required?**
No. All functions also work through the entities, the notifications and the actions.
