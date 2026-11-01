# Tabletten-Warner

Home-Assistant-Integration, die an die Einnahme von Tabletten erinnert, die Einnahme protokolliert und auswertbar macht.

## Funktionen

- **Mehrere Personen** (je ein Integrationseintrag), **mehrere Medikamente** pro Person (Untereinträge), **mehrere Einnahmezeiten** pro Medikament, Wochentage wählbar.
- **Push aufs Handy** (Companion App) mit den Buttons **„Eingenommen“** und **„Später“**. Wiederholte Erinnerungen ersetzen die vorherige Nachricht; nach dem Bestätigen verschwindet sie von allen Handys.
- **Wiederholen + Eskalation** (einstellbar): Abstand, maximale Anzahl, Eskalation an weitere Personen nach N Erinnerungen, Nachricht bei verpasster Einnahme.
- **Frontend nur für die betroffene Person**: Das Dashboard zeigt die „Jetzt einnehmen“-Karte nur dem zugeordneten HA-Benutzer.
- **„Eingenommen“-Button** pro Medikament: bestätigt die aktuelle Einnahme (auch bis zu X Minuten vorher). Außerdem „Später“ und „Überspringen“ (bewusst ausgelassen, zählt nicht als verpasst).
- **Pausieren** pro Medikament (z. B. Krankenhaus/Urlaub) – wird als „pausiert“ protokolliert.
- **Tracking**: Jede Einnahme wird mit geplanter Zeit, tatsächlicher Zeit, Anzahl Erinnerungen, Eskalation und Quelle (Button / Push / Service) gespeichert. HA-Neustarts verlieren nichts: Verstrichene Termine werden nachträglich als „verpasst“ erfasst, laufende Erinnerungen werden fortgesetzt.
- **Auswertung**: Einnahmetreue 7/30 Tage (Langzeitstatistik), Serie, letzte/nächste Einnahme, Kalender (✅ eingenommen / ❌ verpasst), Logbuch, Services `get_history` und `export_history` (CSV).

## Installation

**HACS**: Repository als benutzerdefiniertes Repository (Typ „Integration“) hinzufügen, installieren, HA neu starten.
**Manuell**: `custom_components/tabletten_warner` nach `/config/custom_components/` kopieren, HA neu starten.

Mindestversion: Home Assistant 2026.8.

## Einrichtung

1. **Einstellungen → Geräte & Dienste → Integration hinzufügen → „Tabletten-Warner“**
   Name, HA-Benutzer (für das Dashboard) und die Handys (`notify.mobile_app_…`) wählen.
2. Beim Eintrag der Person **„Medikament hinzufügen“**: Name, Dosis, Einnahmezeiten (z. B. 08:00, 20:00), Wochentage, wie früh bestätigt werden darf und nach wie vielen Minuten die Einnahme als verpasst gilt.
3. **Konfigurieren** (Zahnrad) für Wiederholung, „Später“-Dauer, Eskalation, Aufbewahrung der Historie.
4. Dashboard anlegen (Anleitung jeweils im Dateikopf):
   - [dashboards/tabletten_warner_auto.yaml](dashboards/tabletten_warner_auto.yaml) – **empfohlen**, findet alle Medikamente automatisch (benötigt HACS-Karte [auto-entities](https://github.com/thomasloven/lovelace-auto-entities)); nur Personenname und Benutzer-ID ersetzen.
   - [dashboards/tabletten_warner.yaml](dashboards/tabletten_warner.yaml) – nur Standard-Karten, Blöcke pro Medikament kopieren.
   - [dashboards/tabletten_warner_plus.yaml](dashboards/tabletten_warner_plus.yaml) – optionale Zusatzkarten (Mushroom, ApexCharts).

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

Die Medikament-Entitäten tragen die Attribute `person` und `medication`, der Button „Eingenommen“ zusätzlich `due` (gerade fällig) und `actionable` (darf jetzt bestätigt werden). Darüber filtert das Auto-Dashboard – unabhängig von Sprache und Entity-IDs.

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
