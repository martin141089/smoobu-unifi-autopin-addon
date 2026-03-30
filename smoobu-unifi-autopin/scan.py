import requests
import json
import urllib3
from aiohttp import web

urllib3.disable_warnings()

with open("/data/options.json") as f:
    opts = json.load(f)

UNIFI_IP = opts["unifi_host"]
UNIFI_TOKEN = opts["unifi_token"]

UNIFI_BASE = f"https://{UNIFI_IP}:12445/api/v1/developer"

async def scan(request):
    headers = {
        "Authorization": f"Bearer {UNIFI_TOKEN}"
    }

    try:
        r = requests.get(
            f"{UNIFI_BASE}/door_groups/topology",
            headers=headers, verify=False, timeout=10
        )
        data = r.json()
    except Exception as e:
        return web.Response(text=f"Error: {e}", status=500)

    txt = "Gefundene Türgruppen / Türen:\n\n"

    for g in data.get("data", []):
        txt += f"- GROUP: {g['name']} → {g['id']}\n"
        for topo in g.get("resource_topologies", []):
            for rsrc in topo.get("resources", []):
                txt += f"    - DOOR: {rsrc['name']} → {rsrc['id']}\n"

    return web.Response(text=txt)

app = web.Application()
app.router.add_get("/", scan)
web.run_app(app, host="0.0.0.0", port=8098)
