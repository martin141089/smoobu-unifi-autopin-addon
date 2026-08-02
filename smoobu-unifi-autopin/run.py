import base64
import datetime
import hashlib
import hmac
import json
import logging
import secrets
import sys
import time
import uuid
from pathlib import Path

import aiohttp
from aiohttp import web

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("autopin")

OPTIONS_PATH = Path("/data/options.json")

try:
    with OPTIONS_PATH.open("r", encoding="utf-8") as f:
        opts = json.load(f)
except (OSError, json.JSONDecodeError) as e:
    log.error("Konnte %s nicht laden: %s", OPTIONS_PATH, e)
    raise SystemExit(1)

SMOOBU_API_KEY = opts["smoobu_api_key"]
SMOOBU_API_SECRET = opts["smoobu_api_secret"]
UNIFI_IP = opts["unifi_host"]
UNIFI_TOKEN = opts["unifi_token"]
WEBHOOK_SECRET = opts["webhook_secret"]
HOMES_COUNT = opts["homes_count"]

# Multi-Standort Konfiguration
homes = []
seen_names = set()

for i in range(1, HOMES_COUNT + 1):
    name = opts.get(f"home{i}_name", "").strip()
    if not name:
        continue
    key = name.lower()
    if key in seen_names:
        log.warning("Wohnung '%s' ist mehrfach konfiguriert - nur der erste Eintrag wird verwendet", name)
        continue
    seen_names.add(key)
    homes.append({
        "name": name,
        "policy": opts.get(f"home{i}_policy_id", "").strip(),
        "door_group": opts.get(f"home{i}_door_group_id", "").strip(),
    })

if not homes:
    log.warning("Keine Wohnungen konfiguriert - Webhooks können nicht zugeordnet werden")

UNIFI_BASE = f"https://{UNIFI_IP}:12445/api/v1/developer"
UNIFI_HEADERS = {
    "Authorization": f"Bearer {UNIFI_TOKEN}",
    "Content-Type": "application/json; charset=utf-8",
}

# Smoobu HMAC-authentifizierte Public API (loest den Legacy "Api-Key" Header ab,
# der von Smoobu am 25.09.2026 abgeschaltet wird). https://docs.smoobu.com/#hmac-authentication
SMOOBU_API_HOST = "https://login.smoobu.com"

UMLAUT_MAP = {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"}

# Smoobu schickt an dieselbe Webhook-URL ALLE Ereignistypen (Buchung neu/geaendert/
# storniert, Preis-/Verfuegbarkeits-Updates, neue Nachrichten, ...), unterschieden
# nur ueber "action". Es gibt in Smoobu keine Checkbox, um einzelne Event-Typen
# ab-/anzuwaehlen - das muss hier gefiltert werden. https://docs.smoobu.com/#webhooks
RELEVANT_ACTIONS = ("newReservation", "updateReservation")


def to_unix(date_str):
    dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    return int(time.mktime(dt.timetuple()))


def split_name(name):
    p = name.split(" ")
    if len(p) == 1:
        return p[0], ""
    return p[0], " ".join(p[1:])


def normalize(name):
    for k, v in UMLAUT_MAP.items():
        name = name.replace(k, v)
    return name


def find_home(property_name):
    for h in homes:
        if h["name"].lower() == property_name.lower():
            return h
    return None


def generate_pin():
    return "".join(secrets.choice("0123456789") for _ in range(6))


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
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
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


async def push_pin_to_smoobu(session, booking_id, pin):
    """Schreibt den Tür-PIN als Custom Placeholder 'doorPin' an die Buchung.

    Endpoint & Payload gemaess offizieller Doku (https://docs.smoobu.com/#create-custom-placeholder-beta):
    POST https://login.smoobu.com/api/custom-placeholders
    { "key": "doorPin", "defaultValue": <pin>, "type": 1, "foreignId": <bookingId> }
    (type 1 = an eine einzelne Buchung gebunden)

    Fehler hier sind best-effort und duerfen die bereits erfolgreiche Visitor-
    Erstellung in UniFi Access nicht rueckwirkend als Fehlschlag melden - werden
    aber geloggt, damit ein defektes HMAC-Signing nicht unbemerkt bleibt.
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
        async with session.post(
            f"{SMOOBU_API_HOST}{path}",
            headers=headers,
            data=body_bytes,
        ) as r:
            # 400 kommt u.a., wenn fuer diese Buchung schon ein "doorPin"-Placeholder
            # existiert (z.B. bei "Buchung geaendert"-Events). Das ist unkritisch -
            # der PIN wurde beim ersten Mal schon gesetzt.
            if r.status not in (200, 201, 400):
                r.raise_for_status()
    except aiohttp.ClientError as e:
        log.warning("PIN konnte nicht an Smoobu übertragen werden (Booking %s): %s", booking_id, e)


async def status(request):
    lines = ["UniFi AutoPIN Add-on läuft ✅", "", "Konfigurierte Wohnungen:", ""]
    if homes:
        for h in homes:
            lines.append(f"- {h['name']} → DoorGroup: {h['door_group']} → Policy: {h['policy']}")
    else:
        lines.append("(keine)")
    lines.append("")
    lines.append("Türgruppen-Scan: GET /scan")
    lines.append("Access Policies:  GET /policies")
    return web.Response(text="\n".join(lines))


async def scan(request):
    """Listet alle UniFi Access Türgruppen + Türen auf."""
    session = request.app["http"]
    try:
        async with session.get(
            f"{UNIFI_BASE}/door_groups/topology",
            headers=UNIFI_HEADERS,
            ssl=False,
        ) as r:
            r.raise_for_status()
            data = await r.json()
    except aiohttp.ClientError as e:
        log.error("Scan fehlgeschlagen: %s", e)
        return web.Response(text=f"Fehler beim Abruf: {e}", status=502)

    output = ["Gefundene Türgruppen & Türen:\n"]
    for group in data.get("data", []):
        output.append("\n=== TÜRGRUPPE ===")
        output.append(f"NAME: {group.get('name')}")
        output.append(f"ID:   {group.get('id')}")
        for topo in group.get("resource_topologies", []):
            for door in topo.get("resources", []):
                output.append(f"   - TÜR: {door.get('name')} → {door.get('id')}")

    return web.Response(text="\n".join(output), content_type="text/plain")


async def policies(request):
    """Listet Access Policies auf (Endpunkt-Name ist in der UniFi-Access-Doku
    nicht eindeutig belegt - probiert mehrere gaengige Kandidaten durch)."""
    session = request.app["http"]
    candidates = ["/access_policies", "/policies"]
    results = []

    for path in candidates:
        try:
            async with session.get(
                f"{UNIFI_BASE}{path}",
                headers=UNIFI_HEADERS,
                ssl=False,
            ) as r:
                results.append(f"--- {path} -> HTTP {r.status} ---")
                if r.status == 200:
                    data = await r.json()
                    for item in data.get("data", []):
                        results.append(f"NAME: {item.get('name')}   ID: {item.get('id')}")
                else:
                    results.append((await r.text())[:300])
        except aiohttp.ClientError as e:
            results.append(f"--- {path} -> Fehler: {e} ---")

    return web.Response(text="\n".join(results), content_type="text/plain")


async def handle(request):
    secret = request.query.get("secret", "")
    if not hmac.compare_digest(secret, WEBHOOK_SECRET):
        log.warning("Webhook mit ungültigem Secret abgelehnt (%s)", request.remote)
        return web.Response(text="Unauthorized", status=401)

    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return web.Response(text="ERROR: Invalid JSON body", status=400)

    if not isinstance(payload, dict):
        return web.Response(text="ERROR: Invalid JSON body", status=400)

    action = payload.get("action")
    if action not in RELEVANT_ACTIONS:
        log.info("Webhook ignoriert (action=%s)", action)
        return web.Response(text=f"Ignoriert (action={action})", status=200)

    data = payload.get("data") or {}
    apartment = data.get("apartment") or {}

    # Smoobu Felder (echtes Webhook-Format, verschachtelt unter "data")
    raw_guest = data.get("guest-name", "")
    property_name = apartment.get("name", "")
    arrival = data.get("arrival")
    departure = data.get("departure")
    booking_id = data.get("id")

    if not (raw_guest and property_name and arrival and departure and booking_id):
        log.warning("Webhook mit unvollständigem Payload: %s", data)
        return web.Response(text=f"ERROR: Unvollstaendiges Payload: {data}", status=400)

    home = find_home(property_name)
    if not home:
        log.warning("Keine Wohnung für '%s' gefunden", property_name)
        return web.Response(text=f"ERROR: No mapping for apartment '{property_name}'", status=422)

    guest = normalize(raw_guest)
    first, last = split_name(guest)

    try:
        start_ts = to_unix(arrival)
        end_ts = to_unix(departure) + 86399
    except ValueError as e:
        log.warning("Ungültiges Datumsformat: %s", e)
        return web.Response(text=f"ERROR: Invalid date format: {e}", status=400)

    pin = generate_pin()

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
                "type": "door_group",
            }
        ],
        "pin_code": pin,
        "access_policy_ids": [home["policy"]],
    }

    session = request.app["http"]

    try:
        async with session.post(
            f"{UNIFI_BASE}/visitors",
            headers=UNIFI_HEADERS,
            json=visitor_payload,
            ssl=False,
        ) as r:
            r.raise_for_status()
    except aiohttp.ClientError as e:
        log.error("UniFi Visitor-Erstellung fehlgeschlagen (Booking %s): %s", booking_id, e)
        return web.Response(text=f"UNIFI ERROR: {e}", status=502)

    log.info("Visitor angelegt: %s %s, Wohnung %s, Booking %s", first, last, property_name, booking_id)

    await push_pin_to_smoobu(session, booking_id, pin)

    return web.Response(text=f"OK – Visitor {first} {last}, PIN {pin}, Wohnung: {property_name}", status=200)


async def make_http_session(app):
    timeout = aiohttp.ClientTimeout(total=10)
    app["http"] = aiohttp.ClientSession(timeout=timeout)
    yield
    await app["http"].close()


app = web.Application()
app.cleanup_ctx.append(make_http_session)
app.router.add_get("/", status)
app.router.add_get("/scan", scan)
app.router.add_get("/policies", policies)
app.router.add_post("/", handle)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=8099)
