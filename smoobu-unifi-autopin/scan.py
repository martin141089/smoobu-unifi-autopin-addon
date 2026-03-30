import requests
import json
import urllib3
from aiohttp import web

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# HA Optionen laden
with open("/data/options.json") as f:
    opts = json.load(f)

UNIFI_IP = opts.get("unifi_host")
UNIFI_TOKEN = opts.get("unifi_token")

UNIFI_BASE = f"https://{UNIFI_IP}:12445/api/v1/developer"

async def scan(request):
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

    output = []
    output.append("Gefundene Türgruppen & Türen:\n")

    for group in data.get("data", []):
        group_id = group.get("id")
        group_name = group.get("name")
        output.append(f"\n=== TÜRGRUPPE ===")
        output.append(f"NAME: {group_name}")
        output.append(f"ID:   {group_id}")

        for topo in group.get("resource_topologies", []):
            for door in topo.get("resources", []):
                door_id = door.get("id")
                door_name = door.get("name")
                output.append(f"   - TÜR: {door_name} → {door_id}")

    text = "\n".join(output)
    return web.Response(text=text, content_type="text/plain")

app = web.Application()
app.router.add_get("/", scan)

web.run_app(app, host="0.0.0.0", port=8098)
