# BMW CarData → openWB 2.x SoC Bridge

Proof of Concept: SoC, Reichweite und Ladestatus vom BMW via CarData REST-API in openWB 2.x anzeigen.

Getestet mit BMW iX M60 + openWB Series 2. Kein Captcha, kein SSH-Zugang zur openWB nötig.

## Voraussetzungen

- BMW CarData Account mit eingerichteter Client ID
  → https://www.bmw.de → Mein BMW → Fahrzeugdaten → BMW CarData
- "Zugang zur CarData API beantragen" aktivieren
- Mindestens diese Datenpunkte im Portal aktivieren:
  - `vehicle.drivetrain.electricEngine.charging.level`
  - `vehicle.drivetrain.electricEngine.remainingElectricRange`
  - `vehicle.drivetrain.electricEngine.charging.status`
- Python 3.8+ auf einem Gerät im Heimnetz (PC, NAS, Raspberry Pi)
- openWB 2.x erreichbar im Heimnetz

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

Die Fahrzeug-ID steht in den openWB Fahrzeugeinstellungen.

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

- BMW CarData REST-API: 50 Calls/Tag kostenlos → alle 30 Minuten = 48 Calls/Tag
- Tokens werden automatisch erneuert, kein manueller Eingriff nötig
- Container-ID wird automatisch ermittelt, muss nicht eingetragen werden
- Ältere Modelle (i3, iDrive 6) senden Telemetriedaten seltener – bekannte BMW-Einschränkung

## Getestet mit

| Fahrzeug | Ergebnis |
|----------|----------|
| BMW iX M60 (2023) | ✅ funktioniert |
| Weitere Modelle | Feedback willkommen! |

## Dateien

- `bmw_cardata_bridge.py` – Hauptscript mit MQTT-Publishing an openWB
- `bmw_cardata_test.py` – Test-Script ohne MQTT, zeigt rohe API-Antwort

## Lizenz

MIT
