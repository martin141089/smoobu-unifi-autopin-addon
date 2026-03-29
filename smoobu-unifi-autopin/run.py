from aiohttp import web
import random
import requests
import json

# ✅ Optionen direkt aus Home Assistant laden
with open("/data/options.json", "r") as f:
    opts = json.load(f)

SMOOBU_API_KEY = opts.get("smoobu_api_key")
UNIFI_HOST     = opts.get("unifi_host")
UNIFI_TOKEN    = opts.get("unifi_token")
WEBHOOK_SECRET = opts.get("webhook_secret")

async def status(request):
    return web.Response(
        text=f"Smoobu AutoPIN läuft.\nWebhook Secret: {WEBHOOK_SECRET}\n", 
        content_type="text/plain"
    )

async def handle(request):
    if request.query.get("secret") != WEBHOOK_SECRET:
        return web.Response(text="Unauthorized", status=401)

    data = await request.json()

    guest_name = data.get("name")
    arrival    = data.get("arrivalDate")
    departure  = data.get("departureDate")
    booking_id = data.get("bookingId")

    pin = "".join(random.choice("0123456789") for _ in range(6))

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

    r = requests.post(f"{UNIFI_HOST}/api/v1/visitors", headers=headers, json=visitor_payload)
    if r.status_code >= 300:
        return web.Response(text=f"Unifi error: {r.text}", status=500)

    smoobu_headers = {
        "Api-Key": SMOOBU_API_KEY,
        "Content-Type": "application/json"
    }

    placeholder_payload = {
        "bookingId": booking_id,
        "placeholder": "doorPin",
        "value": pin
    }

    r2 = requests.post("https://api.smoobu.com/v1/custom-placeholders", headers=smoobu_headers, json=placeholder_payload)
    if r2.status_code >= 300:
        return web.Response(text=f"Smoobu error: {r2.text}", status=500)

    return web.Response(text=f"OK – PIN {pin} gesetzt", status=200)

app = web.Application()
app.router.add_get("/", status)
app.router.add_post("/", handle)

web.run_app(app, host="0.0.0.0", port=8099)
