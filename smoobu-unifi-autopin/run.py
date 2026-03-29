from aiohttp import web
import random
import requests
import os

SMOOBU_API_KEY = os.environ.get("SMOOBU_API_KEY")
UNIFI_HOST     = os.environ.get("UNIFI_HOST")
UNIFI_TOKEN    = os.environ.get("UNIFI_TOKEN")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")

# -----------------------
# GET: Statusseite
# -----------------------
async def status(request):
    return web.Response(
        text=f"""
<html>
<head>
<title>Smoobu UniFi AutoPIN – Status</title>
<style>
body {{
    font-family: Arial, sans-serif;
    background: #f4f4f4;
    padding: 40px;
}}
.container {{
    background: white;
    padding: 25px;
    border-radius: 8px;
    max-width: 600px;
    margin: auto;
    box-shadow: 0 0 10px rgba(0,0,0,0.15);
}}
h1 {{
    color: #333;
}}
.code {{
    background: #eee;
    padding: 5px 12px;
    border-radius: 5px;
    font-family: monospace;
}}
</style>
</head>
<body>
<div class="container">
<h1>Smoobu UniFi AutoPIN – Status</h1>

<p>✅ Das Add-on läuft.</p>

<p>Die Webhook‑URL lautet:</p>

<p class="code">http://YOUR_HOME_ASSISTANT_IP:8099/?secret={WEBHOOK_SECRET}</p>

<p><b>Hinweis:</b><br>
Smoobu muss einen <b>POST</b>-Request senden.<br>
Ein Aufruf im Browser zeigt nur diese Statusseite.</p>

</div>
</body>
</html>
""",
        content_type="text/html"
    )

# -----------------------
# POST: Webhook Handler
# -----------------------
async def handle(request):
    if request.query.get("secret") != WEBHOOK_SECRET:
        return web.Response(text="Unauthorized", status=401)

    data = await request.json()

    guest_name = data.get("name")
    arrival    = data.get("arrivalDate")
    departure  = data.get("departureDate")
    booking_id = data.get("bookingId")

    # PIN erzeugen
    pin = "".join(random.choice("0123456789") for _ in range(6))

    # UniFi Access Visitor erstellen
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

    # PIN zu Smoobu senden
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


# -----------------------
# Webserver starten
# -----------------------
app = web.Application()
app.router.add_get("/", status)   # ✅ Statusseite
app.router.add_post("/", handle)  # ✅ Webhook POST

web.run_app(app, host="0.0.0.0", port=8099)
