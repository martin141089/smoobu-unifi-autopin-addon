import random
import requests
import json
import urllib3
from aiohttp import web
import datetime
import time

# SSL-Warnungen für Ubiquiti deaktivieren
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Optionen aus Home Assistant laden
with open("/data/options.json", "r") as f:
    opts = json.load(f)

SMOOBU_API_KEY = opts.get("smoobu_api_key")
UNIFI_IP       = opts.get("unifi_host")      # z.B. 192.168.1.1
UNIFI_TOKEN    = opts.get("unifi_token")
WEBHOOK_SECRET = opts.get("webhook_secret")
ACCESS_POLICY_ID = opts.get("access_policy_id")   # ✅ NEUE OPTION

# Fixer API-Port + Developer-Prefix
UNIFI_BASE = f"https://{UNIFI_IP}:12445/api/v1/developer"

async def status(request):
    return web.Response(
        text=f"""
UniFi Access AutoPIN läuft ✔

API: {UNIFI_BASE}
Policy: {ACCESS_POLICY_ID}
Secret: {WEBHOOK_SECRET}

Alles funktioniert.
""",
        content_type="text/plain"
    )

def to_unix(date_str):
    dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    return int(time.mktime(dt.timetuple()))

async def handle(request):
    if request.query.get("secret") != WEBHOOK_SECRET:
        return web.Response(text="Unauthorized", status=401)

    data = await request.json()

    guest_name = data.get("name")
    arrival    = data.get("arrivalDate")
    departure  = data.get("departureDate")
    booking_id = data.get("bookingId")

    if not (guest_name and arrival and departure and booking_id):
        return web.Response(text="Missing fields", status=400)

    # Start/Endzeit
    start_ts = to_unix(arrival)
    end_ts   = to_unix(departure) + 86399  # bis 23:59:59

    # PIN erzeugen
    pin = "".join(random.choice("0123456789") for _ in range(6))

    # -------------------------------
    # Visitor anlegen
    # -------------------------------
    headers = {
        "Authorization": f"Bearer {UNIFI_TOKEN}",
        "Content-Type": "application/json"
    }

    visitor_payload = {
        "first_name": guest_name,
        "last_name": "",
        "remarks": f"Smoobu Booking {booking_id}",
        "mobile_phone": "",
        "email": "",
        "visitor_company": "Smoobu Gäste",
        "start_time": start_ts,
        "end_time": end_ts,
        "visit_reason": "Business",
        "resources": [],
        "pin_code": pin,
        "access_policy_ids": [ACCESS_POLICY_ID]   # ✅ POLICY AUS HA
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
        return web.Response(text=f"Unifi error: {e}", status=500)

    # -------------------------------
    # PIN an Smoobu schicken
    # -------------------------------
    smoobu_headers = {
        "Api-Key": SMOOBU_API_KEY,
        "Content-Type": "application/json"
    }

    placeholder_payload = {
        "bookingId": booking_id,
        "placeholder": "doorPin",
        "value": pin
    }

    try:
        r2 = requests.post(
            "https://api.smoobu.com/v1/custom-placeholders",
            headers=smoobu_headers,
            json=placeholder_payload,
            timeout=10
        )
        r2.raise_for_status()
    except Exception as e:
        return web.Response(text=f"Smoobu error: {e}", status=500)

    return web.Response(text=f"OK – Visitor + PIN {pin} erstellt", status=200)

app = web.Application()
app.router.add_get("/", status)
app.router.add_post("/", handle)

web.run_app(app, host="0.0.0.0", port=8099)
