#!/usr/bin/env python3
"""
BMW CarData → openWB 2.x SoC Bridge
=====================================
Liest SoC, Reichweite und Ladestatus via BMW CarData REST-API
und publiziert die Werte per MQTT an openWB 2.x.

Einmalige Abhängigkeit:
    pip install paho-mqtt

Verwendung:
    python bmw_cardata_bridge.py --auth    (einmalig)
    python bmw_cardata_bridge.py           (normaler Betrieb)
    python bmw_cardata_bridge.py --test    (ohne MQTT)

Cron (alle 30 Minuten auf dem NAS/HA):
    */30 * * * * python3 /pfad/bmw_cardata_bridge.py
"""

import argparse, base64, hashlib, json, logging, os
import secrets, sys, time, urllib.error, urllib.parse
import urllib.request, webbrowser
from pathlib import Path

# ─── KONFIGURATION ────────────────────────────────────────────
CONFIG = {
    "client_id":         "DEINE_CARDATA_CLIENT_ID",
    "vin":               "DEINE_VIN_17_STELLIG",
    "container_id":      "",   # erster aktiver Container
    "openwb_host":       "192.168.x.x",
    "openwb_port":       1883,
    "openwb_vehicle_id": 1,
    "token_file":        str(Path.home() / ".bmw_cardata_tokens.json"),
}

BMW_AUTH = "https://customer.bmwgroup.com/gcdm/oauth"
BMW_API  = "https://api-cardata.bmwgroup.com"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("bmw_bridge")

# ─── HTTP ─────────────────────────────────────────────────────
def http_post(url, data):
    req = urllib.request.Request(
        url, data=urllib.parse.urlencode(data).encode(), method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def http_get(url, token):
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    req.add_header("x-version", "v1")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

# ─── PKCE ─────────────────────────────────────────────────────
def pkce():
    v = secrets.token_urlsafe(64)
    c = base64.urlsafe_b64encode(
        hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()
    return v, c

# ─── TOKEN ────────────────────────────────────────────────────
def save_tokens(t, container_id=None):
    # Bestehende Token-Datei laden um container_id nicht zu überschreiben
    existing = load_tokens() or {}
    d = {"access_token": t["access_token"], "refresh_token": t["refresh_token"],
         "id_token": t.get("id_token"),
         "expires_at": time.time() + t.get("expires_in", 3600) - 60,
         "container_id": container_id or existing.get("container_id")}
    with open(CONFIG["token_file"], "w") as f:
        json.dump(d, f, indent=2)
    os.chmod(CONFIG["token_file"], 0o600)

def load_tokens():
    p = CONFIG["token_file"]
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)

def get_token():
    t = load_tokens()
    if not t:
        log.error("Keine Tokens! Bitte: python bmw_cardata_bridge.py --auth")
        sys.exit(1)
    if time.time() < t.get("expires_at", 0):
        return t["access_token"]
    log.info("Token refresh...")
    try:
        new = http_post(f"{BMW_AUTH}/token", {
            "grant_type": "refresh_token",
            "refresh_token": t["refresh_token"],
            "client_id": CONFIG["client_id"]})
        save_tokens(new)
        return new["access_token"]
    except Exception as e:
        log.error("Refresh fehlgeschlagen: %s → bitte --auth", e)
        sys.exit(1)

# ─── AUTH ─────────────────────────────────────────────────────
def run_auth():
    print("\n" + "="*55)
    print("  BMW CarData – Authentifizierung")
    print("="*55)
    v, c = pkce()
    print("\n[1/3] Device Code anfordern...")
    try:
        r = http_post(f"{BMW_AUTH}/device/code", {
            "client_id": CONFIG["client_id"],
            "response_type": "device_code",
            "scope": "authenticate_user openid cardata:api:read cardata:streaming:read",
            "code_challenge": c, "code_challenge_method": "S256"})
    except Exception as e:
        print(f"FEHLER: {e}")
        sys.exit(1)

    url      = r.get("verification_uri_complete", r.get("verification_uri",""))
    interval = r.get("interval", 5)
    expires  = r.get("expires_in", 300)

    print(f"\n[2/3] Browser öffnen und mit BMW-Konto bestätigen:")
    print(f"\n  URL:  {url}")
    print(f"  Code: {r['user_code']}")
    print(f"  Zeit: {expires//60} Minuten")
    try:
        webbrowser.open(url)
        print("  (Browser automatisch geöffnet)")
    except Exception:
        pass

    print("\n[3/3] Warte...", end="", flush=True)
    dl = time.time() + expires
    while time.time() < dl:
        time.sleep(interval + 1)
        try:
            tokens = http_post(f"{BMW_AUTH}/token", {
                "client_id": CONFIG["client_id"],
                "device_code": r["device_code"],
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "code_verifier": v})
            save_tokens(tokens)
            print(f"\n\n  ✓ Erfolgreich! Tokens: {CONFIG['token_file']}")
            return
        except urllib.error.HTTPError as e:
            body = ""
            try: body = e.read().decode()
            except: pass
            err = ""
            try: err = json.loads(body).get("error","")
            except: pass
            if err in ("authorization_pending",) or e.code == 403:
                print(".", end="", flush=True)
            elif err == "slow_down":
                interval += 5
            else:
                print(f"\nFEHLER: {body}")
                sys.exit(1)
    print("\nZeitlimit abgelaufen.")
    sys.exit(1)

# ─── FAHRZEUGDATEN ────────────────────────────────────────────
def fetch_data(token):
    vin = CONFIG["vin"]
    cid = CONFIG["container_id"]

    # Container-ID: erst aus Token-Datei, dann via API (einmalig)
    if not cid:
        tokens = load_tokens()
        cid = tokens.get("container_id") if tokens else None

    if not cid:
        log.info("Container-ID wird einmalig via API ermittelt und gespeichert...")
        raw = http_get(f"{BMW_API}/customers/containers", token)
        cs  = raw if isinstance(raw, list) else raw.get("containers", [])
        act = [c for c in cs if c.get("state") == "ACTIVE"]
        if not act:
            raise RuntimeError("Keine aktiven Container!")
        cid = act[0].get("containerId") or act[0].get("id")
        # Container-ID in Token-Datei speichern → kein extra Call mehr nötig
        tokens = load_tokens() or {}
        tokens["container_id"] = cid
        with open(CONFIG["token_file"], "w") as f:
            json.dump(tokens, f, indent=2)
        log.info("Container-ID gespeichert: %s", cid)
    else:
        log.debug("Container-ID aus Datei: %s", cid)

    url = f"{BMW_API}/customers/vehicles/{vin}/telematicData?containerId={cid}"
    raw = http_get(url, token)
    td  = raw.get("telematicData", raw)

    def v(key):
        e = td.get(key, {})
        return e.get("value") if isinstance(e, dict) else None

    def ts(key):
        e = td.get(key, {})
        return e.get("timestamp") if isinstance(e, dict) else None

    # SoC: charging.level hat aktuelleren Timestamp (bestätigt für iX M60)
    soc_raw = v("vehicle.drivetrain.electricEngine.charging.level") \
           or v("vehicle.drivetrain.batteryManagement.header")
    soc_ts  = ts("vehicle.drivetrain.electricEngine.charging.level") \
           or ts("vehicle.drivetrain.batteryManagement.header")

    rng_raw = v("vehicle.drivetrain.electricEngine.remainingElectricRange")
    status  = v("vehicle.drivetrain.electricEngine.charging.status")

    soc = int(float(soc_raw)) if soc_raw is not None else None
    rng = int(float(rng_raw)) if rng_raw is not None else None

    log.info("SoC=%s%%, Reichweite=%s km, Status=%s (Stand: %s)",
             soc, rng, status, soc_ts)

    return {"soc": soc, "range_km": rng,
            "charging_status": status,
            "is_charging": (status == "CHARGINGACTIVE"),
            "soc_timestamp": soc_ts,
            "max_energy_kwh": v("vehicle.drivetrain.batteryManagement.maxEnergy")}

# ─── MQTT → OPENWB ────────────────────────────────────────────
def publish(data):
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        log.error("paho-mqtt fehlt: pip install paho-mqtt")
        sys.exit(1)

    vid = CONFIG["openwb_vehicle_id"]
    try:
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                        client_id="bmw_cardata_bridge", clean_session=True)
    except AttributeError:
        # paho-mqtt < 2.0 Fallback
        c = mqtt.Client(client_id="bmw_cardata_bridge", clean_session=True)
    c.connect(CONFIG["openwb_host"], CONFIG["openwb_port"], keepalive=10)
    c.loop_start()
    time.sleep(0.5)

    published = []
    if data["soc"] is not None:
        c.publish(f"openWB/set/mqtt/vehicle/{vid}/get/soc",
                  str(data["soc"]), qos=1, retain=True)
        c.publish(f"openWB/set/mqtt/vehicle/{vid}/get/soc_timestamp",
                  str(int(time.time())), qos=1, retain=True)
        published.append(f"SoC={data['soc']}%")

    if data["range_km"] is not None:
        c.publish(f"openWB/set/mqtt/vehicle/{vid}/get/range",
                  str(data["range_km"]), qos=1, retain=True)
        published.append(f"Reichweite={data['range_km']}km")

    time.sleep(1)
    c.loop_stop()
    c.disconnect()

    if published:
        log.info("✓ openWB aktualisiert: %s", ", ".join(published))
    else:
        log.warning("Keine Daten publiziert (SoC/Reichweite = None).")

# ─── MAIN ─────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="BMW CarData → openWB Bridge")
    ap.add_argument("--auth",  action="store_true")
    ap.add_argument("--test",  action="store_true")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.auth:
        run_auth()
        return

    log.info("Start (VIN: ...%s)", CONFIG["vin"][-6:])
    token = get_token()

    try:
        data = fetch_data(token)
    except urllib.error.HTTPError as e:
        body = ""
        try: body = e.read().decode()
        except: pass
        if e.code == 403 and "CU-429" in body:
            log.warning("⚠ BMW API Tageslimit erreicht (50 Calls/Tag). Versuche es morgen wieder.")
            sys.exit(0)
        log.error("HTTP Fehler %s: %s", e.code, body[:300])
        sys.exit(1)

    if args.test:
        print(f"\n  SoC:        {data['soc']}%")
        print(f"  Reichweite: {data['range_km']} km")
        print(f"  Ladestatus: {data['charging_status']}")
        print(f"  Timestamp:  {data['soc_timestamp']}")
        print(f"  Batterie:   {data['max_energy_kwh']} kWh")
        return

    publish(data)
    log.info("Fertig.")

if __name__ == "__main__":
    main()
