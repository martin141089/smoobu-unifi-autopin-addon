import datetime
import hmac
import json
import logging
import secrets
import sys
import time
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

UMLAUT_MAP = {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"}

REQUIRED_FIELDS = ("name", "propertyName", "arrivalDate", "departureDate", "bookingId")


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


async def status(request):
    lines = ["UniFi AutoPIN Add-on läuft ✅", "", "Konfigurierte Wohnungen:", ""]
    if homes:
        for h in homes:
            lines.append(f"- {h['name']} → DoorGroup: {h['door_group']} → Policy: {h['policy']}")
    else:
        lines.append("(keine)")
    lines.append("")
    lines.append("Tür-Scan: GET /scan")
    return web.Response(text="\n".join(lines))


async def scan(request):
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


async def handle(request):
    secret = request.query.get("secret", "")
    if not hmac.compare_digest(secret, WEBHOOK_SECRET):
        log.warning("Webhook mit ungültigem Secret abgelehnt (%s)", request.remote)
        return web.Response(text="Unauthorized", status=401)

    try:
        data = await request.json()
    except json.JSONDecodeError:
        return web.Response(text="ERROR: Invalid JSON body", status=400)

    missing = [f for f in REQUIRED_FIELDS if f not in data]
    if missing:
        log.warning("Webhook ohne Pflichtfelder: %s", missing)
        return web.Response(text=f"ERROR: Missing fields: {', '.join(missing)}", status=400)

    raw_guest = data["name"]
    property_name = data["propertyName"]
    arrival = data["arrivalDate"]
    departure = data["departureDate"]
    booking_id = data["bookingId"]

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

    # PIN an Smoobu senden - Fehler hier sollen den Visitor-Erfolg nicht überschreiben
    try:
        async with session.post(
            "https://api.smoobu.com/v1/custom-placeholders",
            headers={"Api-Key": SMOOBU_API_KEY, "Content-Type": "application/json"},
            json={
                "bookingId": booking_id,
                "placeholder": "doorPin",
                "value": pin,
            },
        ) as r:
            r.raise_for_status()
    except aiohttp.ClientError as e:
        log.warning("PIN konnte nicht an Smoobu übertragen werden (Booking %s): %s", booking_id, e)

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
app.router.add_post("/", handle)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=8099)
