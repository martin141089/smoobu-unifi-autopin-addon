import random
import requests
import json
import urllib3
from aiohttp import web

# SSL-Warnungen ausschalten (wegen UniFi self-signed Zertifikat)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Optionen aus Home Assistant laden
with open("/data/options.json", "r") as f:
    opts = json.load(f)

SMOOBU_API_KEY = opts.get("smoobu_api_key")
UNIFI_HOST     = opts.get("unifi_host")
UNIFI_TOKEN    = opts.get("unifi_token")
WEBHOOK_SECRET = opts.get("webhook_secret")


# ---------------------------------------------------------
# GET: Statusseite (Browser-Aufruf)
# ---------------------------------------------------------
async def status(request):
    return web.Response(
        text=f"""
Smoobu UniFi AutoPIN - Status ✔

Add-on läuft.

Webhook URL:
http://YOUR-HOMEASSISTANT:8099/?secret={WEBHOOK_SECRET}

Hinweis:
- Browser nutzt GET → nur Statusseite
- Smoobu Webhook nutzt POST → löst PIN-Erstellung aus
""",
        content_type="text/plain"
    )


# ---------------------------------------------------------
# POST: Smoobu Webhook Handler
# ---------------------------------------------------------
async def handle(request):
    # ✅ Secret prüfen
    if request.query.get("secret") != WEBHOOK_SECRET:
        return web.Response(text="Unauthorized", status=401)

    # ✅ JSON auslesen
    try:
        data = await request.json()
    except:
        return web.Response(text="Invalid JSON", status=400)

    guest_name = data.get("name")
    arrival    = data.get("arrivalDate")
    departure  = data.get("departureDate")
    booking_id = data.get("bookingId")

    if not guest_name or not arrival or not departure or not booking_id:
        return web.Response(text="Missing fields", status=400)

    # ✅ PIN generieren
    pin = "".join(random.choice("0123456789") for _ in range(6))


    # ---------------------------------------------------------
    # ✅ UniFi Access Visitor erstellen
    # ---------------------------------------------------------
    headers = {
        "Authorization": f"Bearer {UNIFI_TOKEN}",
        "Content-Type": "application/json"
    }

    visitor_payload = {
        "full_name": guest_name,
        "pin": pin,
        "valid_from": f"{arrival}T15:00:00Z",
        "valid_until": f"{departure}T11:00:00Z"
    }

    try:
        r = requests.post(
            f"{UNIFI_HOST}/api/v1/visitors",
            headers=headers,
            json=visitor_payload,
            timeout=10,
            verify=False        # ✅ Wichtig: self-signed SSL erlauben
        )
        r.raise_for_status()
    except Exception as e:
        return web.Response(text=f"Unifi error: {e}", status=500)


    # ---------------------------------------------------------
    # ✅ PIN an Smoobu zurückgeben
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
app.router.add_get("/", status)    # ✅ GET für Browser
app.router.add_post("/", handle)   # ✅ POST für Smoobu

web.run_app(app, host="0.0.0.0", port=8099)
