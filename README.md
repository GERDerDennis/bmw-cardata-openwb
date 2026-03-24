# BMW CarData → openWB 2.x SoC Bridge

Proof of Concept: SoC, Reichweite und Ladestatus vom BMW via CarData REST-API in openWB 2.x anzeigen.

Getestet mit BMW iX M60 + openWB Series 2 (SW 2.1.9). Kein Captcha, kein SSH-Zugang zur openWB nötig.

## Voraussetzungen

- BMW CarData Account mit eingerichteter Client ID
  → https://www.bmw.de → Mein BMW → Fahrzeugdaten → BMW CarData
- "Zugang zur CarData API beantragen" aktivieren
- Mindestens diese Datenpunkte im Portal aktivieren:
  - `vehicle.drivetrain.electricEngine.charging.level` (neuere Fahrzeuge, z.B. iX, iX1, iX3 ab 2022)
  - `vehicle.drivetrain.batteryManagement.header` (ältere Fahrzeuge, z.B. i3, iX3, G08 – als Fallback automatisch genutzt)
  - `vehicle.drivetrain.electricEngine.remainingElectricRange` (Reichweite)
  - `vehicle.drivetrain.electricEngine.charging.status` (Ladestatus)
- Python 3.8+ auf einem Gerät im Heimnetz (PC, NAS, Raspberry Pi)
- openWB 2.x erreichbar im Heimnetz

## Fahrzeugkompatibilität

| Fahrzeug | SoC-Feld | Ergebnis |
|----------|----------|----------|
| BMW iX M60 (2023) | `charging.level` | ✅ funktioniert |
| BMW iX3 G08 | `batteryManagement.header` | ⚠️ bitte testen |
| BMW i3s | `batteryManagement.header` | ⚠️ bitte testen |
| Weitere Modelle | – | Feedback willkommen! |

Das Script prüft automatisch beide Felder – kein manueller Eingriff nötig.

## openWB Fahrzeugeinstellungen

In den openWB Fahrzeugeinstellungen folgendes einstellen:

- **SoC-Modul:** MQTT
- **Nur aktualisieren wenn angesteckt:** Nein

## Installation

```bash
pip install paho-mqtt
```

## Konfiguration

In `bmw_cardata_bridge.py` diese 4 Zeilen anpassen:

```python
"client_id":         "DEINE_CARDATA_CLIENT_ID",
"vin":               "DEINE_VIN_17_STELLIG",
"openwb_host":       "192.168.x.x",
"openwb_vehicle_id": 1,   # Fahrzeug-ID in openWB prüfen!
```

Die Fahrzeug-ID steht in den openWB Fahrzeugeinstellungen (ID: X).

## Verwendung

**Schritt 1 – Einmalige Authentifizierung:**
```bash
python bmw_cardata_bridge.py --auth
```
Browser öffnet sich automatisch → mit BMW-Konto bestätigen → fertig.

**Schritt 2 – Testlauf (ohne MQTT):**
```bash
python bmw_cardata_bridge.py --test
```

**Schritt 3 – Echter Lauf:**
```bash
python bmw_cardata_bridge.py
```

**Automatisch alle 30 Minuten (Cron):**
```bash
*/30 * * * * python3 /pfad/bmw_cardata_bridge.py
```

## Hinweise

- BMW CarData REST-API: 50 Calls/Tag kostenlos
- Erster Start: 2 Calls (Container-ID wird einmalig ermittelt und gespeichert)
- Ab dem zweiten Start: nur noch 1 Call pro Durchlauf
- Tokens werden automatisch erneuert, kein manueller Eingriff nötig
- Bei Erreichen des Tageslimits: saubere Fehlermeldung, kein Absturz
- Der Wert wird nach dem konfigurierten Intervall in openWB übernommen. Sofortige Aktualisierung per Kreispfeil (🔄) auf der Hauptseite möglich.

## Dateien

- `bmw_cardata_bridge.py` – Hauptscript mit MQTT-Publishing an openWB
- `bmw_cardata_test.py` – Test-Script ohne MQTT, zeigt rohe API-Antwort

## Lizenz

MIT
