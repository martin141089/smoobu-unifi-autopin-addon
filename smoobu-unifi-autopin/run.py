import random
import requests
import json
import urllib3
from aiohttp import web
import datetime
import time
import hmac
import hashlib
import base64
import uuid

urllib3.disable_warnings()

# Konfiguration laden
with open("/data/options.json", "r") as f:
    opts = json.load(f)

SMOOBU_API_KEY = opts["smoobu_api_key"]
SMOOBU_API_SECRET = opts["smoobu_api_secret"]
UNIFI_IP = opts["unifi_host"]
UNIFI_TOKEN = opts["unifi_token"]
WEBHOOK_SECRET = opts["webhook_secret"]

HOMES_COUNT = opts["homes_count"]

# Multi-Standort Konfiguration
homes = []

for i in range(1, HOMES_COUNT + 1):
    homes.append({
        "name": opts.get(f"home{i}_name", "").strip(),
        "policy": opts.get(f"home{i}_policy_id", "").strip(),
        "door_group": opts.get(f"home{i}_door_group_id", "").strip(),
    })

UNIFI_BASE = f"https://{UNIFI_IP}:12445/api/v1/developer"

# Smoobu API Host (neue HMAC-authentifizierte Public API)
SMOOBU_API_HOST = "https://login.smoobu.com"


def to_unix(date_str):
    dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    return int(time.mktime(dt.timetuple()))


def split_name(name):
    p = name.split(" ")
    if len(p) == 1:
        return p[0], ""
    return p[0], " ".join(p[1:])


def normalize(name):
    r = {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"}
    for k, v in r.items():
        name = name.replace(k, v)
    return name


def find_home(property_name):
    for h in homes:
        if h["name"].lower() == property_name.lower():
            return h
    return None


# ---------------------------------------------------------------------------
# Smoobu HMAC Authentication
# (Legacy "Api-Key" Header wird von Smoobu am 25.09.2026 abgeschaltet.)
# https://docs.smoobu.com/#hmac-authentication
# ---------------------------------------------------------------------------

def _smoobu_signature(method, path, query, timestamp, nonce, body_hash):
    canonical = f"{method}\n{path}\n{query}\n{timestamp}\n{nonce}\n{body_hash}\n{SMOOBU_API_KEY}"
    sig = hmac.new(
        SMOOBU_API_SECRET.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(sig).decode("utf-8")


def smoobu_headers(method, path, query="", body: bytes = b""):
    """Baut die vier von Smoobu geforderten HMAC-Header für einen API-Call."""
    timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    nonce = str(uuid.uuid4())
    body_hash = hashlib.sha256(body).hexdigest()
    signature = _smoobu_signature(method.upper(), path, query, timestamp, nonce, body_hash)
    return {
        "X-API-Key": SMOOBU_API_KEY,
        "X-Timestamp": timestamp,
        "X-Nonce": nonce,
        "X-Signature": signature,
        "Content-Type": "application/json",
    }


def push_pin_to_smoobu(booking_id, pin):
    """Schreibt den Tür-PIN als Custom Placeholder 'doorPin' an die Buchung.

    Endpoint & Payload gemaess offizieller Doku (https://docs.smoobu.com/#create-custom-placeholder-beta):
    POST https://login.smoobu.com/api/custom-placeholders
    { "key": "doorPin", "defaultValue": <pin>, "type": 1, "foreignId": <bookingId> }
    (type 1 = an eine einzelne Buchung gebunden)
    """
    path = "/api/custom-placeholders"
    body_obj = {
        "key": "doorPin",
        "defaultValue": pin,
        "type": 1,
        "foreignId": booking_id,
    }
    body_bytes = json.dumps(body_obj, separators=(",", ":")).encode("utf-8")
    headers = smoobu_headers("POST", path, "", body_bytes)

    try:
        r = requests.post(
            f"{SMOOBU_API_HOST}{path}",
            headers=headers,
            data=body_bytes,
            timeout=10,
        )
        # 400 kommt u.a., wenn fuer diese Buchung schon ein "doorPin"-Placeholder
        # existiert (z.B. bei "Buchung geaendert"-Events). Das ist unkritisch -
        # der PIN wurde beim ersten Mal schon gesetzt.
        if r.status_code not in (200, 201, 400):
            r.raise_for_status()
    except Exception:
        # Smoobu-Rueckschreibung ist best-effort: ein Fehler hier darf die
        # eigentliche PIN-/Visitor-Erstellung in UniFi Access nicht blockieren.
        pass


async def status(request):
    out = "UniFi AutoPIN Add-on läuft ✅\n\nKonfigurierte Wohnungen:\n\n"
    for h in homes:
        out += f"- {h['name']} → DoorGroup: {h['door_group']} → Policy: {h['policy']}\n"
    out += "\nTürgruppen-Scan: /scan\n"
    return web.Response(text=out)


async def scan(request):
    """Listet alle UniFi Access Türgruppen + Türen auf (ersetzt das nie gestartete
    scan.py / Port 8098 - lief im Dockerfile nie mit, siehe CMD)."""
    headers = {
        "Authorization": f"Bearer {UNIFI_TOKEN}",
        "Content-Type": "application/json"
    }

    try:
        r = requests.get(
            f"{UNIFI_BASE}/door_groups/topology",
            headers=headers,
            verify=False,
            timeout=10
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return web.Response(text=f"Fehler beim Abruf: {e}", status=500)

    output = ["Gefundene Türgruppen & Türen:\n"]

    for group in data.get("data", []):
        group_id = group.get("id")
        group_name = group.get("name")
        output.append("\n=== TÜRGRUPPE ===")
        output.append(f"NAME: {group_name}")
        output.append(f"ID:   {group_id}")

        for topo in group.get("resource_topologies", []):
            for door in topo.get("resources", []):
                door_id = door.get("id")
                door_name = door.get("name")
                output.append(f"   - TÜR: {door_name} → {door_id}")

    text = "\n".join(output)
    return web.Response(text=text, content_type="text/plain")


async def policies(request):
    """Listet Access Policies auf (Endpunkt-Name ist in der UniFi-Access-Doku
    nicht eindeutig belegt - probiert mehrere gaengige Kandidaten durch)."""
    headers = {
        "Authorization": f"Bearer {UNIFI_TOKEN}",
        "Content-Type": "application/json"
    }

    candidates = ["/access_policies", "/policies"]
    results = []

    for path in candidates:
        try:
            r = requests.get(
                f"{UNIFI_BASE}{path}",
                headers=headers,
                verify=False,
                timeout=10
            )
            results.append(f"--- {path} -> HTTP {r.status_code} ---")
            if r.status_code == 200:
                data = r.json()
                for item in data.get("data", []):
                    results.append(f"NAME: {item.get('name')}   ID: {item.get('id')}")
            else:
                results.append(r.text[:300])
        except Exception as e:
            results.append(f"--- {path} -> Fehler: {e} ---")

    return web.Response(text="\n".join(results), content_type="text/plain")


async def handle(request):
    if request.query.get("secret") != WEBHOOK_SECRET:
        return web.Response(text="Unauthorized", status=401)

    payload = await request.json()

    # Smoobu schickt an dieselbe Webhook-URL ALLE Ereignistypen (Buchung neu/
    # geaendert/storniert, Preis-/Verfuegbarkeits-Updates, neue Nachrichten, ...),
    # unterschieden nur ueber "action". Es gibt in Smoobu keine Checkbox, um
    # einzelne Event-Typen ab-/anzuwaehlen - das muss hier gefiltert werden.
    # https://docs.smoobu.com/#webhooks
    action = payload.get("action")
    if action not in ("newReservation", "updateReservation"):
        return web.Response(text=f"Ignoriert (action={action})", status=200)

    data = payload.get("data", {}) or {}
    apartment = data.get("apartment", {}) or {}

    # Smoobu Felder (echtes Webhook-Format, verschachtelt unter "data")
    raw_guest = data.get("guest-name", "")
    property_name = apartment.get("name", "")
    arrival = data.get("arrival")
    departure = data.get("departure")
    booking_id = data.get("id")

    if not (raw_guest and property_name and arrival and departure and booking_id):
        return web.Response(text=f"ERROR: Unvollstaendiges Payload: {data}", status=400)

    # Wohnung finden
    home = find_home(property_name)
    if not home:
        return web.Response(text=f"ERROR: No mapping for apartment '{property_name}'", status=500)

    # Namen
    guest = normalize(raw_guest)
    first, last = split_name(guest)

    # Zeitraum
    start_ts = to_unix(arrival)
    end_ts = to_unix(departure) + 86399

    # PIN
    pin = "".join(random.choice("0123456789") for _ in range(6))

    # Visitor-Daten
    visitor_payload = {
        "first_name": first,
        "last_name": last,
        "remarks": f"Smoobu Booking {booking_id}",
        "visitor_company": property_name,
        "start_time": start_ts,
        "end_time": end_ts,
        "visit_reason": "Business",
        "resources": [
            {
                "id": home["door_group"],
                "type": "door_group"
            }
        ],
        "pin_code": pin,
        "access_policy_ids": [home["policy"]]
    }

    headers = {
        "Authorization": f"Bearer {UNIFI_TOKEN}",
        "Content-Type": "application/json; charset=utf-8"
    }

    try:
        r = requests.post(
            f"{UNIFI_BASE}/visitors",
            headers=headers,
            json=visitor_payload,
            timeout=10,
            verify=False
        )
        r.raise_for_status()
    except Exception as e:
        return web.Response(text=f"UNIFI ERROR: {e}", status=500)

    # PIN an Smoobu senden (HMAC-authentifiziert)
    push_pin_to_smoobu(booking_id, pin)

    return web.Response(text=f"OK – Visitor {first} {last}, PIN {pin}, Wohnung: {property_name}", status=200)


app = web.Application()
app.router.add_get("/", status)
app.router.add_get("/scan", scan)
app.router.add_get("/policies", policies)
app.router.add_post("/", handle)

web.run_app(app, host="0.0.0.0", port=8099)
