from aiohttp import web
import random
import requests
import os

SMOOBU_API_KEY = os.environ.get("SMOOBU_API_KEY")
UNIFI_HOST     = os.environ.get("UNIFI_HOST")
UNIFI_TOKEN    = os.environ.get("UNIFI_TOKEN")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")

async def handle(request):
    # Sicherheit: Secret prüfen
    if request.query.get("secret") != WEBHOOK_SECRET:
        return web.Response(text="Unauthorized", status=401)

    # Eingangsdaten vom Webhook lesen
    data = await request.json()

    guest_name = data.get("name")
    arrival    = data.get("arrivalDate")
    departure  = data.get("departureDate")
    booking_id = data.get("bookingId")

    # 1. PIN generieren
    pin = "".join(random.choice("0123456789") for _ in range(6))

    # 2. UniFi Access: Visitor erstellen
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
            timeout=10
        )
        r.raise_for_status()
    except Exception as e:
        return web.Response(text=f"Unifi error: {e}", status=500)

    # 3. PIN an Smoobu zurückgeben (Custom Placeholder)
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
        requests.post(
            "https://api.smoobu.com/v1/custom-placeholders",
            headers=smoobu_headers,
            json=placeholder_payload,
            timeout=10
        )
    except Exception as e:
        return web.Response(text=f"Smoobu error: {e}", status=500)

    return web.Response(text=f"OK – PIN {pin} gesetzt", status=200)


app = web.Application()
app.router.add_post("/", handle)

web.run_app(app, host="0.0.0.0", port=8099)
