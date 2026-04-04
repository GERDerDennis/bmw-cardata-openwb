# BMW CarData → openWB 2.x SoC Bridge

Proof of Concept: SoC, Reichweite und Ladestatus vom BMW via CarData REST-API in openWB 2.x anzeigen.

Getestet mit BMW iX M60 + openWB Series 2 (SW 2.1.9). Kein Captcha, kein SSH-Zugang zur openWB nötig.

> ⚠️ **Hinweis:** BMW CarData liefert nicht bei allen Accounts automatisch Container.
> Dieses Repository enthält Tools zur Diagnose und optionalen Erstellung.

---

## Voraussetzungen

- BMW CarData Account mit eingerichteter Client ID
  → [BMW ConnectedDrive](https://www.bmw.de) → Mein BMW → Fahrzeugdaten → BMW CarData
- „Zugang zur CarData API beantragen" aktivieren
- Mindestens diese Datenpunkte im Portal aktivieren:
  - `vehicle.drivetrain.electricEngine.charging.level` (neuere Fahrzeuge)
  - `vehicle.drivetrain.batteryManagement.header` (Fallback für ältere Modelle)
  - `vehicle.drivetrain.electricEngine.remainingElectricRange`
  - `vehicle.drivetrain.electricEngine.charging.status`
- Python 3.8+ auf einem Gerät im Heimnetz (PC, NAS, Raspberry Pi)
- openWB 2.x erreichbar im Heimnetz

---

## Fahrzeugkompatibilität

## Fahrzeugkompatibilität
| Fahrzeug | SoC-Feld | Kilometerstand | Ergebnis |
|----------|----------|----------------|----------|
| BMW iX M60 (2023, I20) | `charging.level` | ✅ | ✅ funktioniert |
| BMW iX3 G08 | `batteryManagement.header` | ❓ | ✅ SoC + Reichweite |
| BMW i3s | `batteryManagement.header` | ❓ | ✅ SoC + Reichweite |
| BMW iX1 (BJ 11/23, OS9) | `batteryManagement.header` | ❓ | ✅ SoC bestätigt |
| BMW i4 M50 xDrive (G26, BEV) | `charging.level` | ⚠️ fehlt in BimmerData-Containern | ✅ SoC + Reichweite |
| Weitere Modelle | – | – | Feedback willkommen! |

> **Hinweis:** Das native openWB-Modul legt automatisch einen eigenen Container mit allen benötigten Datenpunkten an – inklusive Kilometerstand. Nutzer die bisher nur BimmerData-Container haben erhalten den Kilometerstand nach der ersten Abfrage automatisch.

Das Script prüft automatisch beide Felder – kein manueller Eingriff nötig.

---

## openWB Fahrzeugeinstellungen

- **SoC-Modul:** MQTT
- **Nur aktualisieren wenn angesteckt:** Nein

---

## Installation

```bash
pip install paho-mqtt
```

---

## Konfiguration

In `bmw_cardata_bridge.py` diese Werte anpassen:

```python
"client_id":         "DEINE_CARDATA_CLIENT_ID",
"vin":               "DEINE_VIN_17_STELLIG",
"openwb_host":       "192.168.x.x",
"openwb_vehicle_id": 1
```

---

## Verwendung

### 1. Einmalige Authentifizierung

```bash
python bmw_cardata_bridge.py --auth
```

Browser öffnet sich automatisch → mit BMW-Konto bestätigen.

### 2. Testlauf (ohne MQTT)

```bash
python bmw_cardata_bridge.py --test
```

### 3. Normalbetrieb

```bash
python bmw_cardata_bridge.py
```

### Cron (alle 30 Minuten)

```bash
*/30 * * * * python3 /pfad/bmw_cardata_bridge.py
```

---

## Container-Diagnose & Debugging

In manchen Fällen liefert BMW trotz korrekter Einrichtung keine Container:

```json
{
  "containers": []
}
```

Ohne Container können keine Telematikdaten (SoC, Reichweite, Status) abgerufen werden.

### Diagnose mit Testscript

```bash
python bmw_cardata_test.py --auth
python bmw_cardata_test.py --test
```

### Mögliche Ergebnisse

| Status | Bedeutung |
|--------|-----------|
| `KEIN CONTAINER VORHANDEN` | BMW liefert aktuell keinen Container |
| `AKTIVER CONTAINER GEFUNDEN` | Telematikdaten sollten abrufbar sein |

### Container manuell erstellen (Debug)

Falls keine Container vorhanden sind:

```bash
python bmw_cardata_test.py --create-container
```

Erfolgreiches Ergebnis:

```json
{
  "containerId": "...",
  "state": "ACTIVE"
}
```

Danach sollte `--test` direkt Daten liefern.

### Wichtige Hinweise zur Container-Erstellung

- Container-Erstellung ist aktuell eine Debug-/Entwicklerfunktion
- Funktioniert nicht bei allen BMW Accounts
- BMW erstellt Container normalerweise automatisch (nicht deterministisch)
- Dieses Script hilft, fehlende Container gezielt zu analysieren

### Typisches Problem

Häufiger Zustand:

```
Auth funktioniert       ✔
Mapping vorhanden       ✔
basicData funktioniert  ✔
Container fehlen        ❌
```

→ Lösung: `--create-container` testen

---

## API Limits

- BMW CarData API: **50 Calls/Tag** kostenlos
- Erster Start: ca. 2 Calls
- Danach: 1 Call pro Durchlauf

---

## Weitere Hinweise

- Tokens werden automatisch erneuert – keine manuelle Pflege nötig
- Bei Erreichen des API-Limits → saubere Fehlermeldung statt Absturz
- Werte werden zyklisch aktualisiert
- Manuelle Aktualisierung über openWB UI möglich

---

## Dateien

| Datei | Beschreibung |
|-------|-------------|
| `bmw_cardata_bridge.py` | Hauptscript – sendet SoC via MQTT an openWB |
| `bmw_cardata_test.py` | Diagnose- und Testtool |

---

## Lizenz

MIT
