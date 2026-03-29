import random
import requests
import json
import urllib3
from aiohttp import web

# SSL-Warnungen für die selbst-signierten Ubiquiti-Zertifikate abschalten
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Home Assistant Optionen laden
with open("/data/options.json", "r") as f:
    opts = json.load(f)

# ---------------------------
# KONSTANTEN – NICHT MEHR ÄNDERN
# ---------------------------

# UniFi Access API Port ist FIX laut Dokumentation (Port 12445)
UNIFI_API_PORT = 12445

# Developer API Prefix ist FIX
UNIFI_API_PREFIX = "/api/v1/developer"

# ---------------------------
# KONFIGURATION AUS HA
# ---------------------------

SMOOBU_API_KEY = opts.get("smoobu_api_key")
UNIFI_IP       = opts.get("unifi_host")            # z.B. "192.168.1.1"
UNIFI_TOKEN    = opts.get("unifi_token")
WEBHOOK_SECRET = opts.get("webhook_secret")

# Vollständiger UniFi Access API HOST
UNIFI_BASE_URL = f"https://{UNIFI_IP}:{UNIFI_API_PORT}{UNIFI_API_PREFIX}"


# ---------------------------------------------------------
# GET: Status-Seite für Browser
# ---------------------------------------------------------
async def status(request):
    return web.Response(
        text=f"""
Smoobu UniFi AutoPIN – Status ✔

Add-on läuft.

UniFi Access API Base URL:
{UNIFI_BASE_URL}

Webhook URL:
http://YOUR-HOMEASSISTANT-IP:8099/?secret={WEBHOOK_SECRET}

Hinweis:
- Browser = GET -> nur Statusseite
- Smoobu sendet POST -> löst PIN-Erstellung aus
""",
        content_type="text/plain"
    )


# ---------------------------------------------------------
# POST: Webhook Handler
# ---------------------------------------------------------
async def handle(request):
    # ✅ Secret prüfen
    if request.query.get("secret") != WEBHOOK_SECRET:
        return web.Response(text="Unauthorized", status=401)

    try:
        data = await request.json()
    except:
        return web.Response(text="Invalid JSON", status=400)

    guest_name = data.get("name")
    arrival    = data.get("arrivalDate")
    departure  = data.get("departureDate")
    booking_id = data.get("bookingId")

    if not (guest_name and arrival and departure and booking_id):
        return web.Response(text="Missing fields", status=400)

    # ✅ PIN generieren
    pin = "".join(random.choice("0123456789") for _ in range(6))

    # ---------------------------------------------------------
    # ✅ UniFi Access VISITOR erstellen
    # ---------------------------------------------------------

    headers = {
        "Authorization": f"Bearer {UNIFI_TOKEN}",
        "Content-Type": "application/json"
    }

    visitor_payload = {
        "first_name": guest_name,
        "last_name": "",
        "start_time": int(0),   # Access verlangt Unix-Zeit → Dummy, wenn nicht benötigt
        "end_time": int(0),
        "resources": [],
        "pin_code": pin
    }

    try:
        r = requests.post(
            f"{UNIFI_BASE_URL}/visitors",
            headers=headers,
            json=visitor_payload,
            timeout=10,
            verify=False
        )
        r.raise_for_status()
    except Exception as e:
        return web.Response(text=f"Unifi error: {e}", status=500)


    # ---------------------------------------------------------
    # ✅ PIN an Smoobu zurücksenden
    # ---------------------------------------------------------

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

    return web.Response(text=f"OK – PIN {pin} gesetzt", status=200)


# ---------------------------------------------------------
# Webserver starten
# ---------------------------------------------------------
app = web.Application()
app.router.add_get("/", status)      # Browser
app.router.add_post("/", handle)     # Smoobu Webhook

web.run_app(app, host="0.0.0.0", port=8099)
