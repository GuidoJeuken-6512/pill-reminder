# Tabletten-Warner

Home-Assistant-Integration, die an die Einnahme von Tabletten erinnert, die Einnahme protokolliert und auswertbar macht.

## Funktionen

- **Mehrere Personen** (je ein Integrationseintrag), **mehrere Medikamente** pro Person (Untereinträge), **mehrere Einnahmezeiten** pro Medikament, Wochentage wählbar.
- **Push aufs Handy** (Companion App) mit den Buttons **„Eingenommen“** und **„Später“**. Wiederholte Erinnerungen ersetzen die vorherige Nachricht; nach dem Bestätigen verschwindet sie von allen Handys.
- **Wiederholen + Eskalation** (einstellbar): Abstand, maximale Anzahl, Eskalation an weitere Personen nach N Erinnerungen, Nachricht bei verpasster Einnahme.
- **Eigenes Dashboard „Tabletten“** wird automatisch angelegt: je Person eine Ansicht, die **nur diese Person und Administratoren** sehen. Es ist immer aktuell – neue Medikamente erscheinen sofort, nichts muss von Hand gepflegt werden.
- **Medikamente direkt im Dashboard verwalten**: anlegen, Zeiten/Wochentage/Dosis/Bestätigungsfenster ändern, pausieren, löschen – auch ohne Admin-Rechte.
- **„Eingenommen“-Button** pro Medikament: bestätigt die aktuelle Einnahme (auch bis zu X Minuten vorher). Außerdem „Später“ und „Überspringen“ (bewusst ausgelassen, zählt nicht als verpasst).
- **Pausieren** pro Medikament (z. B. Krankenhaus/Urlaub) – wird als „pausiert“ protokolliert.
- **Tracking**: Jede Einnahme wird mit geplanter Zeit, tatsächlicher Zeit, Anzahl Erinnerungen, Eskalation und Quelle (Button / Push / Service) gespeichert. HA-Neustarts verlieren nichts: Verstrichene Termine werden nachträglich als „verpasst“ erfasst, laufende Erinnerungen werden fortgesetzt.
- **Auswertung**: Einnahmetreue 7/30 Tage (Langzeitstatistik), Serie, letzte/nächste Einnahme, Kalender (✅ eingenommen / ❌ verpasst), Logbuch, Services `get_history` und `export_history` (CSV).

## Installation

**HACS**: HACS → ⋮ → Benutzerdefinierte Repositories → `https://github.com/GuidoJeuken-6512/pill-reminder` (Typ „Integration“) hinzufügen, „Tabletten-Warner“ installieren, HA neu starten.
**Manuell**: `custom_components/tabletten_warner` nach `/config/custom_components/` kopieren, HA neu starten.

Mindestversion: Home Assistant 2026.8.

## Einrichtung

1. **Einstellungen → Geräte & Dienste → Integration hinzufügen → „Tabletten-Warner“**
   Name, HA-Benutzer (wer die Ansicht im Dashboard sieht) und die Handys (`notify.mobile_app_…`) wählen.
2. Beim Eintrag der Person **„Medikament hinzufügen“**: Name, Dosis, Einnahmezeiten (z. B. 08:00, 20:00), Wochentage, wie früh bestätigt werden darf und nach wie vielen Minuten die Einnahme als verpasst gilt.
3. **Konfigurieren** (Zahnrad) für Wiederholung, „Später“-Dauer, Eskalation, Aufbewahrung der Historie.
4. Fertig: Im Seitenmenü erscheint **„Tabletten“** (`/tabletten-warner`). Medikamente lassen sich dort im Bereich **„Medikamente verwalten“** anlegen und ändern – oder wie gewohnt über den Integrationseintrag.

Eingabeformate im Dashboard: Zeiten `08:00, 20:00` · Wochentage `täglich`, `Mo-Fr` oder `Mo, Mi, Fr` (auch Englisch: `daily`, `Mon-Fri`).

Das Dashboard wird von der Integration erzeugt und kann daher nicht im Editor bearbeitet werden. Wer ein eigenes Dashboard bauen möchte, findet Vorlagen in [dashboards/](dashboards/) (nur Standard-Karten bzw. mit Mushroom/ApexCharts).

## Entitäten

| Entität (Beispiel, HA auf Deutsch) | Bedeutung |
|---|---|
| `button.ramipril_eingenommen` | Aktuelle Einnahme bestätigen |
| `button.ramipril_spater` | Erinnerung verschieben |
| `button.ramipril_uberspringen` | Bewusst auslassen |
| `binary_sensor.ramipril_fallig` | An, solange eine Einnahme offen ist |
| `sensor.ramipril_status` | geplant / fällig / verschoben / eingenommen / verpasst / übersprungen / pausiert |
| `sensor.ramipril_nachste_einnahme`, `sensor.ramipril_letzte_einnahme` | Zeitstempel |
| `sensor.ramipril_einnahmetreue_7_tage`, `…_30_tage` | Anteil eingenommen / (eingenommen + verpasst) in % |
| `sensor.ramipril_serie` | Tage in Folge ohne verpasste Einnahme |
| `switch.ramipril_erinnerungen` | Erinnerungen pausieren |
| `binary_sensor.anna_medikament_fallig` | Irgendein Medikament der Person fällig |
| `sensor.anna_offen_heute`, `sensor.anna_einnahmetreue_7_tage`, … | Zusammenfassung pro Person |
| `sensor.anna_heute_eingenommen` / `_heute_verpasst` / `_heute_ubersprungen` | Tageszähler (springen um Mitternacht auf 0) |
| `calendar.anna_medikamente` | Alle Einnahmen als Kalender; Beschreibung mit Dosis, Einnahmezeit, Verspätung, Erinnerungen und Quelle |

Die Medikament-Entitäten tragen die Attribute `person` und `medication`, der Button „Eingenommen“ zusätzlich `due` (gerade fällig) und `actionable` (darf jetzt bestätigt werden). Damit lassen sich eigene Dashboards sprachunabhängig filtern (z. B. mit auto-entities).

Zusätzlich gibt es pro Medikament Einstellungs-Entitäten (`text.<med>_einnahmezeiten`, `_wochentage`, `_dosis`, `_name`, `number.<med>_fruher_bestatigen_…`, `_verpasst_nach_…`, `button.<med>_medikament_loschen`) und pro Person die Eingabefelder „Neues Medikament: …“ mit `button.<person>_medikament_hinzufugen`.

## Events (für eigene Automationen)

`tabletten_warner_dose_due`, `…_reminder_sent`, `…_dose_snoozed`, `…_escalated`, `…_dose_taken`, `…_dose_missed`, `…_dose_skipped` – jeweils mit `person`, `medication`, `scheduled`, `status`, `source`, `reminders_sent`.

## Services

| Service | Zweck |
|---|---|
| `tabletten_warner.mark_taken` | Einnahme bestätigen; mit `taken_at` auch nachträglich (korrigiert „verpasst“) |
| `tabletten_warner.snooze` | Erinnerung verschieben (`minutes` optional) |
| `tabletten_warner.skip` | Einnahme auslassen |
| `tabletten_warner.get_history` | Historie als Antwortdaten (Filter: Person, Medikament, Zeitraum, Status) |
| `tabletten_warner.export_history` | Historie als CSV nach `/config/tabletten_warner/` |

## Entwicklung

```powershell
# Tests (isolierter Container, berührt die HA-Testinstanz nicht)
docker run -d --name tw-test -v "${PWD}:/work" -w /work python:3.14-slim sleep infinity
docker exec tw-test pip install -r requirements_test.txt
docker exec tw-test python -m pytest -q
docker exec tw-test ruff check custom_components tests

# In die lokale HA-Testinstanz (Container homeassistant-test) kopieren und neu starten
powershell -ExecutionPolicy Bypass -File scripts\deploy.ps1
```

**Hinweis:** Dies ist eine Erinnerungshilfe und kein Medizinprodukt. Sie ersetzt keine ärztliche Anweisung.
