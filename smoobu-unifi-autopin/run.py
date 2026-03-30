import random
import requests
import json
import urllib3
from aiohttp import web
import datetime
import time

urllib3.disable_warnings()

# Konfiguration laden
with open("/data/options.json", "r") as f:
    opts = json.load(f)

SMOOBU_API_KEY = opts["smoobu_api_key"]
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


def to_unix(date_str):
    dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    return int(time.mktime(dt.timetuple()))


def split_name(name):
    p = name.split(" ")
    if len(p) == 1:
        return p[0], ""
    return p[0], " ".join(p[1:])


def normalize(name):
    r = {"ä":"ae","ö":"oe","ü":"ue","Ä":"Ae","Ö":"Oe","Ü":"Ue","ß":"ss"}
    for k,v in r.items(): name = name.replace(k,v)
    return name


def find_home(property_name):
    for h in homes:
        if h["name"].lower() == property_name.lower():
            return h
    return None


async def status(request):
    out = "UniFi AutoPIN Add-on läuft ✅\n\nKonfigurierte Wohnungen:\n\n"
    for h in homes:
        out += f"- {h['name']} → DoorGroup: {h['door_group']} → Policy: {h['policy']}\n"
    return web.Response(text=out)


async def handle(request):
    if request.query.get("secret") != WEBHOOK_SECRET:
        return web.Response(text="Unauthorized", status=401)

    data = await request.json()

    # Smoobu Felder
    raw_guest = data["name"]
    property_name = data["propertyName"]
    arrival = data["arrivalDate"]
    departure = data["departureDate"]
    booking_id = data["bookingId"]

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

    # PIN an Smoobu senden
    try:
        requests.post(
            "https://api.smoobu.com/v1/custom-placeholders",
            headers={"Api-Key": SMOOBU_API_KEY, "Content-Type": "application/json"},
            json={
                "bookingId": booking_id,
                "placeholder": "doorPin",
                "value": pin
            },
            timeout=10
        )
    except:
        pass

    return web.Response(text=f"OK – Visitor {first} {last}, PIN {pin}, Wohnung: {property_name}", status=200)


app = web.Application()
app.router.add_get("/", status)
app.router.add_post("/", handle)

web.run_app(app, host="0.0.0.0", port=8099)
