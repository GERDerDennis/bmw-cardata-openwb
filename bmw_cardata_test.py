#!/usr/bin/env python3
"""
BMW CarData – Auth, Test & optional Container Create
====================================================

Nur Python 3.x Standardbibliothek – läuft ohne pip install.

Verwendung:
    python bmw_cardata_test.py --auth
    python bmw_cardata_test.py --test
    python bmw_cardata_test.py --create-container
    python bmw_cardata_test.py --create-container --force
    python bmw_cardata_test.py --delete-container <CONTAINER_ID>
    python bmw_cardata_test.py --dump
"""

import argparse
import base64
import hashlib
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

CONFIG = {
    "client_id": "DEINE_CLIENT_ID_HIER",
    "vin": "DEINE_VIN_HIER",
    "token_file": str(Path.home() / ".bmw_cardata_tokens.json"),
    "scope": "authenticate_user openid cardata:api:read cardata:streaming:read",
    "container_name": "ChargeStats",
    "container_purpose": "openWB",
    "container_descriptors": [
        "vehicle.drivetrain.electricEngine.charging.status",
        "vehicle.drivetrain.electricEngine.charging.level",
        "vehicle.drivetrain.batteryManagement.header",
        "vehicle.drivetrain.electricEngine.remainingElectricRange",
        "vehicle.vehicle.travelledDistance",
    ],
}

BMW_AUTH_URL = "https://customer.bmwgroup.com/gcdm/oauth"
BMW_API_URL = "https://api-cardata.bmwgroup.com"

FIELD_SOC = "vehicle.drivetrain.electricEngine.charging.level"
FIELD_SOC_ALT = "vehicle.drivetrain.batteryManagement.header"
FIELD_SOC_OLD = "vehicle.trip.segment.end.drivetrain.batteryManagement.hvSoc"
FIELD_RANGE = "vehicle.drivetrain.electricEngine.remainingElectricRange"
FIELD_STATUS = "vehicle.drivetrain.electricEngine.charging.status"
FIELD_ODOMETER_CANDIDATES = [
    "vehicle.vehicle.travelledDistance",
    "vehicle.trip.segment.end.travelledDistance",
]


def http_post_form(url, data: dict, headers: dict = None) -> dict:
    encoded = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=encoded, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Accept", "application/json")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def http_post_json(url, payload: dict, token: str) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
    )
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "application/json")
    req.add_header("x-version", "v1")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def http_get(url, access_token: str) -> dict:
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Accept", "application/json")
    req.add_header("x-version", "v1")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"\nHTTP Fehler {e.code}: {body[:500]}")
        raise



def http_delete(url: str, access_token: str):
    req = urllib.request.Request(url, method="DELETE")
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Accept", "application/json")
    req.add_header("x-version", "v1")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"\nHTTP Fehler {e.code}: {body[:500]}")
        raise


def generate_pkce_pair():
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return code_verifier, code_challenge


def save_tokens(tokens: dict):
    data = {
        "access_token": tokens.get("access_token"),
        "refresh_token": tokens.get("refresh_token"),
        "id_token": tokens.get("id_token"),
        "expires_at": time.time() + tokens.get("expires_in", 3600) - 60,
    }
    with open(CONFIG["token_file"], "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Tokens gespeichert: {CONFIG['token_file']}")


def load_tokens():
    p = CONFIG["token_file"]
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


def get_valid_token() -> str:
    tokens = load_tokens()
    if not tokens:
        print("Keine Tokens! Bitte zuerst: python bmw_cardata_test.py --auth")
        sys.exit(1)

    if time.time() < tokens.get("expires_at", 0):
        return tokens["access_token"]

    print("Access Token abgelaufen – führe Refresh durch...")
    try:
        new = http_post_form(
            f"{BMW_AUTH_URL}/token",
            {
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": CONFIG["client_id"],
            },
        )
    except urllib.error.HTTPError as e:
        body = e.read().decode() if hasattr(e, "read") else ""
        print(f"\nFehler beim Token-Refresh: {body}")
        sys.exit(1)

    save_tokens(new)
    return new["access_token"]


def run_auth():
    print("\n" + "=" * 55)
    print("  BMW CarData – Authentifizierung (Device Code Flow)")
    print("=" * 55)

    code_verifier, code_challenge = generate_pkce_pair()

    print("\n[1/3] Fordere Device Code an...")
    try:
        device_data = http_post_form(
            f"{BMW_AUTH_URL}/device/code",
            {
                "client_id": CONFIG["client_id"],
                "response_type": "device_code",
                "scope": CONFIG["scope"],
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            },
        )
    except urllib.error.HTTPError as e:
        body = e.read().decode() if hasattr(e, "read") else ""
        print("\nMögliche Ursachen:")
        print("  → client_id falsch eingetragen?")
        print("  → erforderliche Scopes im BMW Portal nicht aktiviert?")
        if body:
            print(f"\nAPI Antwort: {body}")
        sys.exit(1)

    user_code = device_data["user_code"]
    device_code = device_data["device_code"]
    verify_url = device_data.get(
        "verification_uri_complete",
        device_data.get("verification_uri", ""),
    )
    interval = device_data.get("interval", 5)
    expires_in = device_data.get("expires_in", 300)

    print("\n[2/3] Browser öffnen und mit BMW-Zugangsdaten bestätigen:")
    print(f"\n  URL:       {verify_url}")
    print(f"  User Code: {user_code}")
    print(f"\n  Du hast {expires_in // 60} Minuten Zeit.")

    try:
        webbrowser.open(verify_url)
        print("\n  (Browser wurde automatisch geöffnet)")
    except Exception:
        print("\n  (Bitte URL manuell im Browser öffnen)")

    print("\n[3/3] Warte auf Bestätigung", end="", flush=True)

    deadline = time.time() + expires_in
    while time.time() < deadline:
        time.sleep(interval + 1)
        try:
            token_resp = http_post_form(
                f"{BMW_AUTH_URL}/token",
                {
                    "client_id": CONFIG["client_id"],
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "code_verifier": code_verifier,
                },
            )
            save_tokens(token_resp)
            print("\n\n  ✓ Authentifizierung erfolgreich!")
            print(f"  Tokens gespeichert in: {CONFIG['token_file']}")
            print("\n  Jetzt testen mit:")
            print("  python bmw_cardata_test.py --test")
            return
        except urllib.error.HTTPError as e:
            body = e.read().decode() if hasattr(e, "read") else ""
            err = ""
            try:
                parsed = json.loads(body) if body else {}
                err = parsed.get("error", "")
            except Exception:
                pass

            if err == "authorization_pending":
                print(".", end="", flush=True)
                continue

            if err == "authorization_declined":
                print("\n\n  ❌ Authentifizierung wurde im Browser abgelehnt.")
                sys.exit(1)

            if err == "slow_down":
                interval += 5
                print("s", end="", flush=True)
                continue

            print(f"\n\n  ❌ Fehler beim Token-Abruf: {body or 'keine Details'}")
            sys.exit(1)

    print("\n\nZeitlimit abgelaufen. Bitte --auth erneut starten.")
    sys.exit(1)


def get_containers(token: str):
    raw = http_get(f"{BMW_API_URL}/customers/containers", token)
    return raw if isinstance(raw, list) else raw.get("containers", [])


def diagnose_containers(containers_raw):
    containers = (
        containers_raw
        if isinstance(containers_raw, list)
        else containers_raw.get("containers", [])
    )

    print(f"\n{'─' * 55}")
    print("  CONTAINER-DIAGNOSE:")
    print(f"{'─' * 55}")

    if not containers:
        print("  Status: KEIN CONTAINER VORHANDEN")
        print("  Bewertung:")
        print("    - API-Zugang scheint grundsätzlich möglich zu sein")
        print("    - Fahrzeug-Mapping kann trotzdem korrekt sein")
        print("    - Es existiert aktuell aber kein nutzbarer CarData-Container")
        print("\n  Hinweis:")
        print("    Die aktuelle Implementierung kann ohne vorhandenen Container")
        print("    keine Telematikdaten abrufen.")
        return None

    print(f"  Anzahl Container: {len(containers)}")
    active = []
    openwb = []
    for idx, container in enumerate(containers, start=1):
        cid = container.get("containerId") or container.get("id")
        name = container.get("name", "?")
        state = container.get("state", "UNKNOWN")
        purpose = container.get("purpose", "")
        marker = " ← openWB" if purpose == CONFIG["container_purpose"] else ""
        print(f"  [{idx}] ID={cid} | Name={name} | Status={state}{marker}")
        if state == "ACTIVE":
            active.append(container)
            if purpose == CONFIG["container_purpose"]:
                openwb.append(container)

    if not active:
        print("\n  Status: CONTAINER VORHANDEN, ABER KEINER AKTIV")
        return None

    # Bevorzuge openWB-Container
    preferred = openwb if openwb else active
    cid = preferred[0].get("containerId") or preferred[0].get("id")
    label = "openWB-Container" if openwb else "Container (kein openWB-Container gefunden)"
    print(f"\n  Status: AKTIVER {label.upper()} GEFUNDEN ({cid})")
    return cid


def create_container(token: str):
    descriptors = CONFIG.get("container_descriptors") or []
    if not descriptors:
        raise RuntimeError("CONFIG['container_descriptors'] ist leer.")

    body = {
        "name": CONFIG.get("container_name", "ChargeStats"),
        "purpose": CONFIG.get("container_purpose", "openWB"),
        "technicalDescriptors": descriptors,
    }

    print(f"\n{'─' * 55}")
    print("  CONTAINER-ERSTELLUNG:")
    print(f"{'─' * 55}")
    print("  Body:")
    print(json.dumps(body, indent=2, ensure_ascii=False))

    try:
        resp = http_post_json(f"{BMW_API_URL}/customers/containers", body, token)
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode() if hasattr(e, "read") else ""
        print(f"\n  ❌ Container-Erstellung fehlgeschlagen: HTTP {e.code}")
        print(f"  Antwort: {body_txt or 'keine Details'}")
        raise

    print("\n  Antwort:")
    print(json.dumps(resp, indent=2, ensure_ascii=False))

    new_id = resp.get("containerId") or resp.get("id")
    if not new_id:
        raise RuntimeError(
            f"Container konnte nicht erstellt werden: {json.dumps(resp, ensure_ascii=False)}"
        )

    print(f"\n  ✓ Container erstellt: {new_id}")
    return new_id


def extract_preferred_values(telematic_data: dict) -> dict:
    td = telematic_data.get("telematicData", telematic_data)

    def entry(key):
        value = td.get(key)
        return value if isinstance(value, dict) else None

    def scalar(key):
        e = entry(key)
        return e.get("value") if e else None

    preferred_soc_key = None
    preferred_soc_value = None

    for key in [FIELD_SOC, FIELD_SOC_ALT, FIELD_SOC_OLD]:
        val = scalar(key)
        if val is not None:
            preferred_soc_key = key
            preferred_soc_value = val
            break

    range_value = scalar(FIELD_RANGE)
    status_value = scalar(FIELD_STATUS)

    odometer_key = None
    odometer_value = None
    for key in FIELD_ODOMETER_CANDIDATES:
        val = scalar(key)
        if val is not None:
            odometer_key = key
            odometer_value = val
            break

    return {
        "soc_key": preferred_soc_key,
        "soc_value": preferred_soc_value,
        "range_key": FIELD_RANGE if range_value is not None else None,
        "range_value": range_value,
        "status_key": FIELD_STATUS if status_value is not None else None,
        "status_value": status_value,
        "odometer_key": odometer_key,
        "odometer_value": odometer_value,
    }


def run_create_container(force: bool = False):
    print("\n" + "=" * 55)
    print("  BMW CarData – Container erstellen (Prototyp)")
    print("=" * 55)

    token = get_valid_token()

    print("\n  Vorabprüfung vorhandener Container...")
    containers = get_containers(token)
    existing_id = diagnose_containers({"containers": containers})

    if existing_id and not force:
        print("\n  Es existiert bereits ein aktiver Container. Keine Neuerstellung nötig.")
        print("  Mit --force kann trotzdem ein zusätzlicher Container erstellt werden.")
        return

    if existing_id and force:
        print("\n  Hinweis: Es existiert bereits ein aktiver Container.")
        print("  Debug-Modus aktiv: Erstelle trotzdem einen zusätzlichen Container...")

    try:
        new_id = create_container(token)
    except Exception as e:
        print(f"\n  ❌ Abbruch: {e}")
        sys.exit(1)

    print("\n  Prüfe Containerliste erneut...")
    containers_after = get_containers(token)
    diagnose_containers({"containers": containers_after})

    print(f"\n  Teste telematicData mit Container {new_id} ...")
    try:
        url = f"{BMW_API_URL}/customers/vehicles/{CONFIG['vin']}/telematicData?containerId={new_id}"
        result = http_get(url, token)
        print("\n  ✓ telematicData Antwort:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except urllib.error.HTTPError as e:
        body = e.read().decode() if hasattr(e, "read") else ""
        print(f"\n  ❌ telematicData fehlgeschlagen: HTTP {e.code}")
        print(f"  Antwort: {body or 'keine Details'}")


def run_test():
    print("\n" + "=" * 55)
    print("  BMW CarData – Fahrzeugdaten Test")
    print("=" * 55)

    token = get_valid_token()
    vin = CONFIG["vin"]

    print(f"\n  VIN: ...{vin[-6:]}")
    print("  Rufe Daten ab von BMW CarData API...")

    endpoints = [
        f"{BMW_API_URL}/customers/vehicles/mappings",
        f"{BMW_API_URL}/customers/vehicles/{vin}/basicData",
        f"{BMW_API_URL}/customers/containers",
    ]

    all_data = {}
    for url in endpoints:
        try:
            print(f"  → GET {url}")
            result = http_get(url, token)
            all_data[url] = result
            print("     ✓ OK")
        except urllib.error.HTTPError as e:
            print(f"     ✗ Fehler {e.code}")

    if not all_data:
        print("\nAlle Endpoints fehlgeschlagen.")
        sys.exit(1)

    for url, data in all_data.items():
        print(f"\n{'─' * 55}")
        print(f"  {url.split('/')[-1].upper()}:")
        print(f"{'─' * 55}")
        print(json.dumps(data, indent=2, ensure_ascii=False))

    containers_url = f"{BMW_API_URL}/customers/containers"
    if containers_url in all_data:
        cid = diagnose_containers(all_data[containers_url])
        if cid:
            turl = f"{BMW_API_URL}/customers/vehicles/{vin}/telematicData?containerId={cid}"
            try:
                print(f"\n  → GET {turl}")
                result = http_get(turl, token)
                all_data["telematicData"] = result
                print("     ✓ OK")
                print(f"\n{'─' * 55}")
                print(f"  TELEMATIKDATEN (Container: {cid}):")
                print(f"{'─' * 55}")
                print(json.dumps(result, indent=2, ensure_ascii=False))
            except urllib.error.HTTPError as e:
                print(f"     ✗ Fehler {e.code}")

    print(f"\n{'─' * 55}")
    print("  BEVORZUGTE AUSWERTUNG:")
    print(f"{'─' * 55}")

    telematic = all_data.get("telematicData")
    if telematic:
        preferred = extract_preferred_values(telematic)

        if preferred["soc_key"]:
            print(f"  SoC: {preferred['soc_value']}  ({preferred['soc_key']})")
        else:
            print("  SoC: nicht gefunden")

        if preferred["range_key"]:
            print(f"  Reichweite: {preferred['range_value']}  ({preferred['range_key']})")
        else:
            print("  Reichweite: nicht gefunden")

        if preferred["status_key"]:
            print(f"  Ladestatus: {preferred['status_value']}  ({preferred['status_key']})")
        else:
            print("  Ladestatus: nicht gefunden")

        if preferred["odometer_key"]:
            print(f"  Kilometerstand: {preferred['odometer_value']}  ({preferred['odometer_key']})")
        else:
            print("  Kilometerstand: nicht gefunden")
    else:
        print("  Keine telematicData vorhanden.")

    print(f"\n{'─' * 55}")
    print("  GEFUNDENE SoC/LADE-WERTE:")
    print(f"{'─' * 55}")
    found = {}
    for data in all_data.values():
        found.update(extract_values(data))
    if found:
        for key, value in found.items():
            print(f"  {key}: {value}")
    else:
        print("  (keine SoC-Felder gefunden – siehe rohe Antworten oben)")


def extract_values(data) -> dict:
    result = {}
    soc_keys = ["chargingLevelPercent", "batteryLevel", "soc", "electricChargingState", "remainingChargingPercent"]
    range_keys = ["range", "electricRange", "remainingRange"]
    charging_keys = ["chargingStatus", "isCharging", "chargingActive"]
    odometer_keys = ["mileage", "odometer", "vehicleMileage", "kilometer"]

    def search(obj, path=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                full_path = f"{path}.{k}" if path else k
                for sk in soc_keys:
                    if sk.lower() in k.lower():
                        result[f"SoC → {full_path}"] = v
                for rk in range_keys:
                    if rk.lower() in k.lower():
                        result[f"Reichweite → {full_path}"] = v
                for ck in charging_keys:
                    if ck.lower() in k.lower():
                        result[f"Ladestatus → {full_path}"] = v
                for ok in odometer_keys:
                    if ok.lower() in k.lower():
                        result[f"Kilometer → {full_path}"] = v
                search(v, full_path)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                search(item, f"{path}[{i}]")
                if isinstance(item, dict) and "name" in item and "value" in item:
                    name = str(item["name"])
                    value = item["value"]
                    if any(k.lower() in name.lower() for k in soc_keys):
                        result[f"SoC → {name}"] = value
                    if any(k.lower() in name.lower() for k in range_keys):
                        result[f"Reichweite → {name}"] = value
                    if any(k.lower() in name.lower() for k in charging_keys):
                        result[f"Ladestatus → {name}"] = value
                    if any(k.lower() in name.lower() for k in odometer_keys):
                        result[f"Kilometer → {name}"] = value

    search(data)
    return result


def run_dump():
    print("\n" + "=" * 55)
    print("  BMW CarData – Alle Datenpunkte (Dump)")
    print("=" * 55)
    print("  Bitte diese Ausgabe im Forum posten.")
    print("  Deine VIN und Tokens sind NICHT enthalten.")

    token = get_valid_token()
    vin = CONFIG["vin"]

    # Alle aktiven Container abrufen
    try:
        raw = http_get(f"{BMW_API_URL}/customers/containers", token)
        containers = raw if isinstance(raw, list) else raw.get("containers", [])
        active = [c for c in containers if c.get("state") == "ACTIVE"]
        if not active:
            print("\n  Kein aktiver Container gefunden.")
            print("  Bitte zuerst: python bmw_cardata_test.py --create-container")
            sys.exit(1)
    except Exception as e:
        print(f"\n  Fehler beim Container-Abruf: {e}")
        sys.exit(1)

    print(f"\n  VIN: ...{vin[-6:]} (gekürzt)")
    print(f"  Aktive Container: {len(active)}")

    # Alle Container zusammenführen
    all_datapoints = {}
    for container in active:
        cid = container.get("containerId") or container.get("id")
        name = container.get("name", "unbekannt")
        print(f"\n  → Lese Container: {cid} ({name})")
        try:
            url = f"{BMW_API_URL}/customers/vehicles/{vin}/telematicData?containerId={cid}"
            result = http_get(url, token)
            td = result.get("telematicData", {})
            all_datapoints.update(td)
            print(f"     {len(td)} Datenpunkte gefunden")
        except Exception as e:
            print(f"     Fehler: {e}")

    print(f"\n{'─' * 55}")
    print(f"  ALLE DATENPUNKTE ({len(all_datapoints)} gesamt):")
    print(f"{'─' * 55}")

    if not all_datapoints:
        print("  (keine Datenpunkte vorhanden)")
    else:
        for key, value in sorted(all_datapoints.items()):
            if isinstance(value, dict):
                val = value.get("value", "–")
                unit = value.get("unit", "")
                print(f"  {key}: {val} {unit}".rstrip())
            else:
                print(f"  {key}: {value}")

    print(f"\n{'─' * 55}")
    print("  Fahrzeugmodell aus basicData:")
    print(f"{'─' * 55}")
    try:
        basic = http_get(f"{BMW_API_URL}/customers/vehicles/{vin}/basicData", token)
        brand = basic.get("brand", "BMW").replace("BMW_I", "BMW i").replace("_", " ")
        model = basic.get("modelName") or basic.get("series") or "unbekannt"
        drivetrain = basic.get("driveTrain", "")
        series_devt = basic.get("seriesDevt", "")
        print(f"  {brand} {model} ({series_devt}, {drivetrain})")
    except Exception:
        print("  (nicht verfügbar)")

    print(f"\n{'─' * 55}")
    print("  Bitte diese Ausgabe inkl. Fahrzeugmodell im Forum posten!")
    print(f"{'─' * 55}")


def run_delete_container(container_id: str):
    print("\n" + "=" * 55)
    print("  BMW CarData – Container löschen")
    print("=" * 55)

    token = get_valid_token()

    print(f"\n  Lösche Container: {container_id} ...")
    try:
        http_delete(f"{BMW_API_URL}/customers/containers/{container_id}", token)
        print(f"  ✓ Container {container_id} gelöscht.")
    except urllib.error.HTTPError as e:
        body = e.read().decode() if hasattr(e, "read") else ""
        print(f"  ❌ Löschen fehlgeschlagen: HTTP {e.code}")
        print(f"  Antwort: {body or 'keine Details'}")
        sys.exit(1)

    print("\n  Aktuelle Containerliste:")
    containers = get_containers(token)
    diagnose_containers({"containers": containers})



def main():
    if CONFIG["client_id"] == "DEINE_CLIENT_ID_HIER":
        print("\nFEHLER: client_id nicht eingetragen!")
        sys.exit(1)
    if CONFIG["vin"] == "DEINE_VIN_HIER":
        print("\nFEHLER: VIN nicht eingetragen!")
        sys.exit(1)

    parser = argparse.ArgumentParser(description="BMW CarData Test")
    parser.add_argument("--auth", action="store_true", help="Authentifizierung starten")
    parser.add_argument("--test", action="store_true", help="Fahrzeugdaten abrufen")
    parser.add_argument("--create-container", action="store_true", help="Container-Erstellung testen")
    parser.add_argument("--force", action="store_true", help="Mit --create-container auch bei vorhandenen Containern neu erstellen")
    parser.add_argument("--delete-container", metavar="CONTAINER_ID", help="Container mit angegebener ID löschen")
    parser.add_argument("--dump", action="store_true", help="Alle Datenpunkte ausgeben (für Forum-Support)")
    args = parser.parse_args()

    if not args.auth and not args.test and not args.create_container and not args.delete_container and not args.dump:
        print("\nVerwendung:")
        print("  python bmw_cardata_test.py --auth")
        print("  python bmw_cardata_test.py --test")
        print("  python bmw_cardata_test.py --create-container")
        print("  python bmw_cardata_test.py --create-container --force")
        print("  python bmw_cardata_test.py --delete-container <CONTAINER_ID>")
        print("  python bmw_cardata_test.py --dump")
        sys.exit(0)

    if args.force and not args.create_container:
        print("\n--force kann nur zusammen mit --create-container verwendet werden.")
        sys.exit(1)

    if args.auth:
        run_auth()
    elif args.test:
        run_test()
    elif args.create_container:
        run_create_container(force=args.force)
    elif args.delete_container:
        run_delete_container(args.delete_container)
    elif args.dump:
        run_dump()


if __name__ == "__main__":
    main()
