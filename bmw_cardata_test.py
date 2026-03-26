#!/usr/bin/env python3
"""
BMW CarData – Auth & Test (keine pip-Abhängigkeiten!)
======================================================
Nur Python 3.x Standardbibliothek – läuft sofort ohne pip install.

Verwendung:
    python bmw_cardata_test.py --auth     # Einmalige Authentifizierung
    python bmw_cardata_test.py --test     # Fahrzeugdaten abrufen + anzeigen
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

# ─────────────────────────────────────────────────────────────
# KONFIGURATION – hier anpassen!
# ─────────────────────────────────────────────────────────────
CONFIG = {
    "client_id": "DEINE_CARDATA_CLIENT_ID",
    "vin": "DEINE_VIN_17_STELLIG",
    "token_file": str(Path.home() / ".bmw_cardata_tokens.json"),
}

BMW_AUTH_URL = "https://customer.bmwgroup.com/gcdm/oauth"
BMW_API_URL = "https://api-cardata.bmwgroup.com"

# ─────────────────────────────────────────────────────────────
# HTTP HILFSFUNKTIONEN (ohne requests)
# ─────────────────────────────────────────────────────────────
def http_post(url, data: dict, headers: dict = None) -> dict:
    encoded = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=encoded, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Accept", "application/json")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)

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


# ─────────────────────────────────────────────────────────────
# PKCE
# ─────────────────────────────────────────────────────────────
def generate_pkce_pair():
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return code_verifier, code_challenge


# ─────────────────────────────────────────────────────────────
# TOKEN VERWALTUNG
# ─────────────────────────────────────────────────────────────
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
        new = http_post(
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


# ─────────────────────────────────────────────────────────────
# DEVICE CODE FLOW
# ─────────────────────────────────────────────────────────────
def run_auth():
    print("\n" + "=" * 55)
    print("  BMW CarData – Authentifizierung (Device Code Flow)")
    print("=" * 55)

    code_verifier, code_challenge = generate_pkce_pair()

    print("\n[1/3] Fordere Device Code an...")
    try:
        device_data = http_post(
            f"{BMW_AUTH_URL}/device/code",
            {
                "client_id": CONFIG["client_id"],
                "response_type": "device_code",
                "scope": "authenticate_user openid cardata:api:read cardata:streaming:read",
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            },
        )
    except urllib.error.HTTPError as e:
        body = e.read().decode() if hasattr(e, "read") else ""
        print("\nMögliche Ursachen:")
        print("  → client_id falsch eingetragen?")
        print("  → Subscription 'cardata:api:read' im Portal aktiviert?")
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
            token_resp = http_post(
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
                parsed = {}

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


# ─────────────────────────────────────────────────────────────
# CONTAINER DIAGNOSE
# ─────────────────────────────────────────────────────────────
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
        print("    Das ist nicht zwingend ein Fehler bei Client-ID oder VIN.")
        return None

    print(f"  Anzahl Container: {len(containers)}")

    active = []
    for idx, container in enumerate(containers, start=1):
        cid = container.get("containerId") or container.get("id")
        name = container.get("name", "?")
        state = container.get("state", "UNKNOWN")
        print(f"  [{idx}] ID={cid} | Name={name} | Status={state}")
        if state == "ACTIVE":
            active.append(container)

    if not active:
        print("\n  Status: CONTAINER VORHANDEN, ABER KEINER AKTIV")
        print("  Bewertung:")
        print("    - Container wurden gefunden")
        print("    - Aktuell ist jedoch keiner im Zustand ACTIVE")
        return None

    cid = active[0].get("containerId") or active[0].get("id")
    print(f"\n  Status: AKTIVER CONTAINER GEFUNDEN ({cid})")
    return cid


# ─────────────────────────────────────────────────────────────
# FAHRZEUGDATEN ABRUFEN
# ─────────────────────────────────────────────────────────────
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
        containers_raw = all_data[containers_url]
        cid = diagnose_containers(containers_raw)

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
    """Sucht SoC, Reichweite und Ladestatus in der API-Antwort."""
    result = {}
    soc_keys = [
        "chargingLevelPercent",
        "batteryLevel",
        "soc",
        "electricChargingState",
        "remainingChargingPercent",
    ]
    range_keys = ["range", "electricRange", "remainingRange"]
    charging_keys = ["chargingStatus", "isCharging", "chargingActive"]

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
                search(v, full_path)

        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                search(item, f"{path}[{i}]")
                if isinstance(item, dict) and "name" in item and "value" in item:
                    name = item["name"]
                    value = item["value"]
                    if any(k in name for k in ["charging", "battery", "range", "electric"]):
                        result[name] = value

    search(data)
    return result


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
def main():
    if CONFIG["client_id"] == "DEINE_CLIENT_ID_HIER":
        print("\nFEHLER: client_id nicht eingetragen!")
        print("  Öffne bmw_cardata_test.py und trage deine Client ID ein.")
        input("\nEnter drücken zum Beenden...")
        sys.exit(1)

    if CONFIG["vin"] == "DEINE_VIN_HIER":
        print("\nFEHLER: VIN nicht eingetragen!")
        print("  Öffne bmw_cardata_test.py und trage deine VIN ein.")
        input("\nEnter drücken zum Beenden...")
        sys.exit(1)

    parser = argparse.ArgumentParser(description="BMW CarData Test (kein pip nötig)")
    parser.add_argument("--auth", action="store_true", help="Authentifizierung starten")
    parser.add_argument("--test", action="store_true", help="Fahrzeugdaten abrufen")
    args = parser.parse_args()

    if not args.auth and not args.test:
        print("\nVerwendung:")
        print("  python bmw_cardata_test.py --auth   (einmalige Authentifizierung)")
        print("  python bmw_cardata_test.py --test   (Fahrzeugdaten abrufen)")
        input("\nEnter drücken zum Beenden...")
        sys.exit(0)

    if args.auth:
        run_auth()
    elif args.test:
        run_test()

    input("\nEnter drücken zum Beenden...")


if __name__ == "__main__":
    main()
