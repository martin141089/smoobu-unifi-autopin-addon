import asyncio
import base64
import datetime
import hashlib
import hmac
import html
import json
import logging
import os
import secrets
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode

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
SMOOBU_API_SECRET = opts["smoobu_api_secret"]
UNIFI_IP = opts["unifi_host"]
UNIFI_TOKEN = opts["unifi_token"]
WEBHOOK_SECRET = opts["webhook_secret"]
NUKI_API_TOKEN = opts.get("nuki_api_token", "").strip()
ADMIN_EMAIL = opts.get("admin_email", "").strip()
HOMES_COUNT = opts["homes_count"]

HISTORY_PATH = Path("/data/visitor_history.json")
HISTORY_LOCK = asyncio.Lock()


def _normalize_time(value, fallback):
    """Validiert ein HH:MM-Zeitfeld aus der Konfiguration, faellt bei ungueltigem
    Wert auf den fallback zurueck (und loggt eine Warnung), statt spaeter beim
    Anlegen eines Besuchers abzustuerzen."""
    value = (value or "").strip()
    try:
        return datetime.datetime.strptime(value, "%H:%M").strftime("%H:%M")
    except ValueError:
        if value:
            log.warning("Ungültige Zeitangabe '%s' in der Konfiguration - verwende %s", value, fallback)
        return fallback


DEFAULT_CHECKIN_TIME = _normalize_time(opts.get("default_checkin_time"), "15:00")
DEFAULT_CHECKOUT_TIME = _normalize_time(opts.get("default_checkout_time"), "11:00")

# Multi-Standort Konfiguration. Eine Wohnung kann UniFi Access (Door Group + Policy),
# Nuki (Smart Lock mit Keypad) oder beides gleichzeitig nutzen (z.B. zwei Tueren mit
# unterschiedlichen Systemen an derselben Wohnung) - je nachdem, welche Felder gesetzt sind.
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
        "nuki_smartlock_id": opts.get(f"home{i}_nuki_smartlock_id", "").strip(),
    })

if not homes:
    log.warning("Keine Wohnungen konfiguriert - Webhooks können nicht zugeordnet werden")

UNIFI_BASE = f"https://{UNIFI_IP}:12445/api/v1/developer"
UNIFI_HEADERS = {
    "Authorization": f"Bearer {UNIFI_TOKEN}",
    "Content-Type": "application/json; charset=utf-8",
}

# Smoobu HMAC-authentifizierte Public API (loest den Legacy "Api-Key" Header ab,
# der von Smoobu am 25.09.2026 abgeschaltet wird). https://docs.smoobu.com/#hmac-authentication
SMOOBU_API_HOST = "https://login.smoobu.com"

# Nuki Web API (https://api.nuki.io). Statischer API-Token (Nuki Web -> Menue -> API),
# Authentifizierung per "Authorization: Bearer <token>".
NUKI_API_HOST = "https://api.nuki.io"
NUKI_HEADERS = {
    "Authorization": f"Bearer {NUKI_API_TOKEN}",
    "Content-Type": "application/json",
}

UMLAUT_MAP = {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"}

# Smoobu schickt an dieselbe Webhook-URL ALLE Ereignistypen (Buchung neu/geaendert/
# storniert, Preis-/Verfuegbarkeits-Updates, neue Nachrichten, ...), unterschieden
# nur ueber "action". Es gibt in Smoobu keine Checkbox, um einzelne Event-Typen
# ab-/anzuwaehlen - das muss hier gefiltert werden. https://docs.smoobu.com/#webhooks
RELEVANT_ACTIONS = ("newReservation", "updateReservation")


def to_unix(date_str):
    dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    return int(time.mktime(dt.timetuple()))


def to_unix_datetime(date_str, time_str):
    dt = datetime.datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    return int(time.mktime(dt.timetuple()))


def format_ts(ts):
    return datetime.datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")


def parse_smoobu_time(value, default):
    """Smoobu liefert check-in/check-out als Uhrzeit, aber oft NULL (nur gefuellt,
    wenn der Gast das Online-Check-in-Formular ausgefuellt hat) - dann wird die
    konfigurierte Standardzeit verwendet."""
    value = str(value).strip() if value else ""
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.datetime.strptime(value, fmt).strftime("%H:%M")
        except ValueError:
            continue
    return default


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


def find_home_by_door_group(door_group_id):
    for h in homes:
        if h["door_group"] and h["door_group"] == door_group_id:
            return h
    return None


def generate_pin():
    # Nuki-Keypads haben keine "0"-Taste, PINs bestehen daher grundsaetzlich nur aus
    # den Ziffern 1-9 - so funktioniert derselbe PIN auf UniFi- UND Nuki-Tueren.
    return "".join(secrets.choice("123456789") for _ in range(6))


def _iso_millis_utc(ts):
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _parse_nuki_smartlock_id(value):
    """Nuki zeigt die Smart-Lock-ID je nach Quelle unterschiedlich an: die Web API
    (auch unser /nuki-locks) liefert eine Dezimalzahl, die Nuki-App/das Geraet selbst
    zeigt oft die Hex-Form (z.B. "442f2ae4") - wir akzeptieren beides."""
    try:
        return int(value, 10)
    except ValueError:
        return int(value, 16)


class NoProviderConfigured(Exception):
    """Weder UniFi Access noch Nuki ist fuer diese Wohnung konfiguriert."""


async def create_unifi_visitor(session, home, first, last, start_ts, end_ts, remarks, visitor_company, pin):
    """Legt einen befristeten Visitor in UniFi Access an.

    Das optionale "email"-Feld der UniFi-Access-API ist offiziell fuer die E-Mail des
    Besuchers gedacht; wir nutzen es hier bewusst als Admin-Kontaktadresse (admin_email),
    da Smoobu-Buchungen keine verlaessliche Gaeste-E-Mail liefern und der Betreiber so als
    Ansprechpartner am Visitor-Eintrag sichtbar ist.
    """
    visitor_payload = {
        "first_name": first,
        "last_name": last,
        "remarks": remarks,
        "visitor_company": visitor_company,
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
    if ADMIN_EMAIL:
        visitor_payload["email"] = ADMIN_EMAIL
    async with session.post(
        f"{UNIFI_BASE}/visitors",
        headers=UNIFI_HEADERS,
        json=visitor_payload,
        ssl=False,
    ) as r:
        r.raise_for_status()


async def create_nuki_code(session, smartlock_id, pin, name, start_ts, end_ts):
    """Legt einen befristeten Keypad-Code auf einem Nuki Smart Lock an und prueft
    anschliessend, ob er tatsaechlich in Nukis Autorisierungsliste ankommt.

    Erfordert ein physisches Nuki Keypad am Smart Lock - ohne Keypad kann kein Code
    eingegeben werden. type 13 = Keypad-Code. "smartlockIds" ist ein Array (nicht
    "smartlockId" als Einzelwert) und "name" ist auf ca. 20 Zeichen begrenzt - beides
    gemaess einem geloesten Nuki-Forum-Thread mit funktionierendem Beispiel-Body
    (https://developer.nuki.io/t/422-error-when-creating-type-13-authorization-via-web-api-keypad-2/35593).

    Nukis Web API ist laut Nuki-Entwicklerteam asynchron: ein 2xx auf den PUT-Request
    bestaetigt nur die Annahme, nicht dass der Code tatsaechlich am Schloss ankommt
    (https://developer.nuki.io/t/oauth2-api-integration-seems-accepted-but-no-keypad-
    codes-created-redirect-uri-cant-be-saved-500-error/35811). Deshalb wird nach dem
    Anlegen per GET geprueft, ob der Code in der Autorisierungsliste des Smart Locks
    erscheint. Gibt True zurueck, wenn bestaetigt, sonst False (kein Fehler - dann ist
    unklar, ob es nur eine Sync-Verzoegerung ist oder der Code wirklich fehlt).
    """
    lock_id = _parse_nuki_smartlock_id(smartlock_id)
    body = {
        "smartlockIds": [lock_id],
        "name": name[:20],
        "code": int(pin),
        "type": 13,
        "allowedFromDate": _iso_millis_utc(start_ts),
        "allowedUntilDate": _iso_millis_utc(end_ts),
    }
    async with session.put(
        f"{NUKI_API_HOST}/smartlock/auth",
        headers=NUKI_HEADERS,
        json=body,
    ) as r:
        r.raise_for_status()

    try:
        async with session.get(f"{NUKI_API_HOST}/smartlock/{lock_id}/auth", headers=NUKI_HEADERS) as r:
            r.raise_for_status()
            auths = await r.json()
    except aiohttp.ClientError as e:
        log.warning("Nuki-Bestaetigung konnte nicht abgerufen werden (Smartlock %s): %s", lock_id, e)
        return False

    match = next((a for a in auths if a.get("code") == int(pin)), None)
    if match is None:
        return False
    if match.get("error"):
        log.warning("Nuki meldet Fehler für Code auf Smartlock %s: %s", lock_id, match.get("error"))
        return False
    return True


async def create_access_for_home(session, home, first, last, start_ts, end_ts, remarks, visitor_company):
    """Legt Zutritt fuer eine Wohnung an - bei UniFi Access und/oder Nuki, je nachdem
    was fuer sie konfiguriert ist (eine Wohnung kann z.B. eine UniFi-Tuer und eine
    Nuki-Tuer gleichzeitig haben). Beide Systeme bekommen denselben PIN.

    Gibt (pin, erfolgreich, unbestaetigt, fehlgeschlagen) zurueck - jeweils Listen der
    betroffenen Systemnamen. "unbestaetigt" betrifft nur Nuki (asynchrone API - der
    Code wurde angenommen, ist aber nicht sicher bestaetigt) und zaehlt NICHT als
    Fehlschlag, blockiert also z.B. nicht die PIN-Rueckschreibung an Smoobu. Wird
    nichts konfiguriert gefunden, wird NoProviderConfigured geworfen.
    """
    pin = generate_pin()
    succeeded = []
    unconfirmed = []
    failed = []

    if home["door_group"] and home["policy"]:
        try:
            await create_unifi_visitor(session, home, first, last, start_ts, end_ts, remarks, visitor_company, pin)
            succeeded.append("UniFi Access")
        except aiohttp.ClientError as e:
            log.error("UniFi Visitor-Erstellung fehlgeschlagen (Wohnung %s): %s", home["name"], e)
            failed.append(f"UniFi Access ({e})")

    if home["nuki_smartlock_id"]:
        try:
            confirmed = await create_nuki_code(session, home["nuki_smartlock_id"], pin, remarks, start_ts, end_ts)
            if confirmed:
                succeeded.append("Nuki")
            else:
                log.warning(
                    "Nuki-Code wurde angenommen, aber nicht bestätigt (Wohnung %s) - "
                    "ggf. Sync-Verzögerung, bitte im Nuki-Account prüfen",
                    home["name"],
                )
                unconfirmed.append("Nuki")
        except (aiohttp.ClientError, ValueError) as e:
            log.error("Nuki-Code-Erstellung fehlgeschlagen (Wohnung %s): %s", home["name"], e)
            failed.append(f"Nuki ({e})")

    if not succeeded and not unconfirmed and not failed:
        raise NoProviderConfigured(f"Für Wohnung '{home['name']}' ist weder UniFi Access noch Nuki konfiguriert")

    return pin, succeeded, unconfirmed, failed


def _load_history():
    if not HISTORY_PATH.exists():
        return []
    try:
        with HISTORY_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log.warning("Besucher-Historie konnte nicht geladen werden: %s", e)
        return []


def _save_history(entries):
    try:
        tmp_path = HISTORY_PATH.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, HISTORY_PATH)
    except OSError as e:
        log.warning("Besucher-Historie konnte nicht gespeichert werden: %s", e)


async def record_visit(home_name, first, last, pin, start_ts, end_ts, systems, source, booking_id=None):
    """Speichert einen angelegten Besucher lokal (persistent unter /data), damit das
    Dashboard eine Uebersicht zeigen kann - UniFi gibt den PIN nach dem Anlegen nicht
    mehr im Klartext zurueck, daher ist das die einzige Quelle dafuer. Es werden nur
    aktuelle/kommende Eintraege behalten (Abreise in der Zukunft); abgelaufene werden
    bei jedem Aufruf automatisch entfernt."""
    async with HISTORY_LOCK:
        entries = _load_history()
        now = time.time()
        entries = [e for e in entries if e.get("end_ts", 0) >= now]
        entries.append({
            "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "home": home_name,
            "first_name": first,
            "last_name": last,
            "pin": pin,
            "start_ts": start_ts,
            "end_ts": end_ts,
            "systems": systems,
            "source": source,
            "booking_id": booking_id,
        })
        entries.sort(key=lambda e: e["start_ts"])
        _save_history(entries)


async def get_current_history():
    async with HISTORY_LOCK:
        entries = _load_history()
        now = time.time()
        current = [e for e in entries if e.get("end_ts", 0) >= now]
        if len(current) != len(entries):
            _save_history(current)
        current.sort(key=lambda e: e["start_ts"])
        return current


async def fetch_unifi_visitors(session):
    """Holt alle Visitors direkt aus UniFi Access (paginiert), inklusive solcher, die
    nicht ueber dieses Add-on angelegt wurden (z.B. manuell in der UniFi-App, oder von
    vor Einfuehrung der lokalen Besucher-Historie)."""
    visitors = []
    page_num = 1
    while True:
        async with session.get(
            f"{UNIFI_BASE}/visitors",
            headers=UNIFI_HEADERS,
            params={"page_num": page_num, "page_size": 100},
            ssl=False,
        ) as r:
            r.raise_for_status()
            payload = await r.json()
        page = payload.get("data", [])
        visitors.extend(page)
        if len(page) < 100 or page_num >= 20:
            break
        page_num += 1
    return visitors


async def build_display_history(session):
    """Besucher-Uebersicht fuers Dashboard: lokale Historie (mit echtem PIN, von
    diesem Add-on angelegt) ergaenzt um Visitors, die zwar aktuell/kommend in UniFi
    Access existieren, aber nicht in der lokalen Historie stehen (z.B. manuell in der
    UniFi-App angelegt oder von vor Einfuehrung dieser Funktion). Fuer diese ist der
    PIN nicht auslesbar, da UniFi Access seit einiger Zeit nur noch ein Token statt
    des Klartext-PINs zurueckgibt - er wird daher als "unbekannt" markiert. Schlaegt
    der UniFi-Abruf fehl, wird einfach nur die lokale Historie gezeigt (best-effort)."""
    history = await get_current_history()

    if not any(h["door_group"] and h["policy"] for h in homes):
        return history

    try:
        raw_visitors = await fetch_unifi_visitors(session)
    except aiohttp.ClientError as e:
        log.warning("UniFi-Visitors konnten nicht fürs Dashboard geladen werden: %s", e)
        return history

    now = time.time()
    known_keys = {
        (e.get("first_name", "").strip().lower(), e.get("last_name", "").strip().lower(),
         e.get("start_ts"), e.get("end_ts"))
        for e in history
    }

    extras = []
    for v in raw_visitors:
        start_time = v.get("start_time")
        end_time = v.get("end_time")
        if not start_time or not end_time or end_time < now:
            continue
        first = (v.get("first_name") or "").strip()
        last = (v.get("last_name") or "").strip()
        key = (first.lower(), last.lower(), start_time, end_time)
        if key in known_keys:
            continue

        home_name = "-"
        for res in (v.get("resources") or []):
            home = find_home_by_door_group(res.get("id"))
            if home:
                home_name = home["name"]
                break

        extras.append({
            "home": home_name,
            "first_name": first,
            "last_name": last,
            "pin": "unbekannt",
            "start_ts": start_time,
            "end_ts": end_time,
            "systems": ["UniFi Access"],
            "source": "Nur in UniFi (nicht über Add-on angelegt)",
        })

    merged = history + extras
    merged.sort(key=lambda e: e.get("start_ts") or 0)
    return merged


def _smoobu_signature(method, path, query, timestamp, nonce, body_hash):
    canonical = f"{method}\n{path}\n{query}\n{timestamp}\n{nonce}\n{body_hash}\n{SMOOBU_API_KEY}"
    sig = hmac.new(
        SMOOBU_API_SECRET.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(sig).decode("utf-8")


def smoobu_headers(method, path, query="", body: bytes = b""):
    """Baut die vier von Smoobu geforderten HMAC-Header für einen API-Call."""
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    nonce = str(uuid.uuid4())
    body_hash = hashlib.sha256(body).hexdigest()
    signature = _smoobu_signature(method.upper(), path, query, timestamp, nonce, body_hash)
    return {
        "X-API-Key": SMOOBU_API_KEY,
        "X-Timestamp": timestamp,
        "X-Nonce": nonce,
        "X-Signature": signature,
        "Content-Type": "application/json",
    }


async def push_pin_to_smoobu(session, booking_id, pin):
    """Schreibt den Tür-PIN als Custom Placeholder 'doorPin' an die Buchung.

    Endpoint & Payload gemaess offizieller Doku (https://docs.smoobu.com/#create-custom-placeholder-beta):
    POST https://login.smoobu.com/api/custom-placeholders
    { "key": "doorPin", "defaultValue": <pin>, "type": 1, "foreignId": <bookingId> }
    (type 1 = an eine einzelne Buchung gebunden)

    Fehler hier sind best-effort und duerfen die bereits erfolgreiche Visitor-
    Erstellung in UniFi Access nicht rueckwirkend als Fehlschlag melden - werden
    aber geloggt, damit ein defektes HMAC-Signing nicht unbemerkt bleibt.
    """
    path = "/api/custom-placeholders"
    body_obj = {
        "key": "doorPin",
        "defaultValue": pin,
        "type": 1,
        "foreignId": booking_id,
    }
    body_bytes = json.dumps(body_obj, separators=(",", ":")).encode("utf-8")
    headers = smoobu_headers("POST", path, "", body_bytes)

    try:
        async with session.post(
            f"{SMOOBU_API_HOST}{path}",
            headers=headers,
            data=body_bytes,
        ) as r:
            # 400 kommt u.a., wenn fuer diese Buchung schon ein "doorPin"-Placeholder
            # existiert (z.B. bei "Buchung geaendert"-Events). Das ist unkritisch -
            # der PIN wurde beim ersten Mal schon gesetzt.
            if r.status not in (200, 201, 400):
                r.raise_for_status()
    except aiohttp.ClientError as e:
        log.warning("PIN konnte nicht an Smoobu übertragen werden (Booking %s): %s", booking_id, e)


async def fetch_smoobu_bookings(session):
    """Holt aktuelle/kommende Buchungen (Abreise in der Zukunft) aus Smoobu.

    Endpoint gemaess https://docs.smoobu.com/#get-reservations - Query-Parameter
    werden fuer die HMAC-Signatur alphabetisch sortiert und OHNE fuehrendes '?'
    signiert (siehe https://docs.smoobu.com/#hmac-authentication).
    """
    path = "/api/reservations"
    params = {
        "departureFrom": datetime.date.today().isoformat(),
        "excludeBlocked": "true",
        "showCancellation": "false",
        "pageSize": "50",
        "page": "1",
    }
    query = urlencode(sorted(params.items()))
    headers = smoobu_headers("GET", path, query, b"")

    async with session.get(f"{SMOOBU_API_HOST}{path}?{query}", headers=headers) as r:
        r.raise_for_status()
        data = await r.json()

    bookings = data.get("bookings", [])
    bookings.sort(key=lambda b: b.get("arrival") or "")
    return bookings


async def status(request):
    lines = ["UniFi AutoPIN Add-on läuft ✅", "", "Konfigurierte Wohnungen:", ""]
    if homes:
        for h in homes:
            systems = []
            if h["door_group"] and h["policy"]:
                systems.append(f"UniFi (DoorGroup: {h['door_group']}, Policy: {h['policy']})")
            if h["nuki_smartlock_id"]:
                systems.append(f"Nuki (Smartlock: {h['nuki_smartlock_id']})")
            lines.append(f"- {h['name']} → {' + '.join(systems) if systems else '(kein System konfiguriert)'}")
    else:
        lines.append("(keine)")
    lines.append("")
    lines.append("Türgruppen-Scan: GET /scan")
    lines.append("Access Policies:  GET /policies")
    lines.append("Nuki Smart Locks: GET /nuki-locks")
    lines.append("Dashboard:        über die Home Assistant Seitenleiste (Ingress)")
    return web.Response(text="\n".join(lines))


async def scan(request):
    """Listet alle UniFi Access Türgruppen + Türen auf."""
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


async def policies(request):
    """Listet Access Policies auf (Endpunkt-Name ist in der UniFi-Access-Doku
    nicht eindeutig belegt - probiert mehrere gaengige Kandidaten durch)."""
    session = request.app["http"]
    candidates = ["/access_policies", "/policies"]
    results = []

    for path in candidates:
        try:
            async with session.get(
                f"{UNIFI_BASE}{path}",
                headers=UNIFI_HEADERS,
                ssl=False,
            ) as r:
                results.append(f"--- {path} -> HTTP {r.status} ---")
                if r.status == 200:
                    data = await r.json()
                    for item in data.get("data", []):
                        results.append(f"NAME: {item.get('name')}   ID: {item.get('id')}")
                else:
                    results.append((await r.text())[:300])
        except aiohttp.ClientError as e:
            results.append(f"--- {path} -> Fehler: {e} ---")

    return web.Response(text="\n".join(results), content_type="text/plain")


async def nuki_locks(request):
    """Listet alle Nuki Smart Locks des Accounts auf (zur Ermittlung der smartlockId)."""
    if not NUKI_API_TOKEN:
        return web.Response(text="nuki_api_token ist nicht konfiguriert.", status=503)

    session = request.app["http"]
    try:
        async with session.get(f"{NUKI_API_HOST}/smartlock", headers=NUKI_HEADERS) as r:
            r.raise_for_status()
            data = await r.json()
    except aiohttp.ClientError as e:
        log.error("Nuki-Smartlock-Abfrage fehlgeschlagen: %s", e)
        return web.Response(text=f"Fehler beim Abruf: {e}", status=502)

    output = ["Gefundene Nuki Smart Locks:\n"]
    for lock in data:
        lock_id = lock.get("smartlockId", lock.get("id"))
        output.append(f"NAME: {lock.get('name')}   ID: {lock_id}")
    if len(output) == 1:
        output.append("(keine gefunden)")

    return web.Response(text="\n".join(output), content_type="text/plain")


async def handle(request):
    secret = request.query.get("secret", "")
    if not hmac.compare_digest(secret, WEBHOOK_SECRET):
        log.warning("Webhook mit ungültigem Secret abgelehnt (%s)", request.remote)
        return web.Response(text="Unauthorized", status=401)

    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return web.Response(text="ERROR: Invalid JSON body", status=400)

    if not isinstance(payload, dict):
        return web.Response(text="ERROR: Invalid JSON body", status=400)

    action = payload.get("action")
    if action not in RELEVANT_ACTIONS:
        log.info("Webhook ignoriert (action=%s)", action)
        return web.Response(text=f"Ignoriert (action={action})", status=200)

    data = payload.get("data") or {}
    apartment = data.get("apartment") or {}

    # Smoobu Felder (echtes Webhook-Format, verschachtelt unter "data")
    raw_guest = data.get("guest-name", "")
    property_name = apartment.get("name", "")
    arrival = data.get("arrival")
    departure = data.get("departure")
    booking_id = data.get("id")

    if not (raw_guest and property_name and arrival and departure and booking_id):
        log.warning("Webhook mit unvollständigem Payload: %s", data)
        return web.Response(text=f"ERROR: Unvollstaendiges Payload: {data}", status=400)

    home = find_home(property_name)
    if not home:
        log.warning("Keine Wohnung für '%s' gefunden", property_name)
        return web.Response(text=f"ERROR: No mapping for apartment '{property_name}'", status=422)

    guest = normalize(raw_guest)
    first, last = split_name(guest)

    checkin_time = parse_smoobu_time(data.get("check-in"), DEFAULT_CHECKIN_TIME)
    checkout_time = parse_smoobu_time(data.get("check-out"), DEFAULT_CHECKOUT_TIME)

    try:
        start_ts = to_unix_datetime(arrival, checkin_time)
        end_ts = to_unix_datetime(departure, checkout_time)
    except ValueError as e:
        log.warning("Ungültiges Datumsformat: %s", e)
        return web.Response(text=f"ERROR: Invalid date format: {e}", status=400)

    session = request.app["http"]

    try:
        pin, succeeded, unconfirmed, failed = await create_access_for_home(
            session, home, first, last, start_ts, end_ts,
            f"Smoobu Booking {booking_id}", property_name,
        )
    except NoProviderConfigured as e:
        log.warning(str(e))
        return web.Response(text=f"ERROR: {e}", status=422)

    if failed:
        log.error(
            "Zutritt teilweise/komplett fehlgeschlagen (Booking %s, Wohnung %s): erfolgreich=%s, unbestätigt=%s, fehlgeschlagen=%s",
            booking_id, property_name, succeeded, unconfirmed, failed,
        )
        return web.Response(
            text=f"ERROR: {'; '.join(failed)} (erfolgreich: {', '.join(succeeded) or '-'})",
            status=502,
        )

    log.info(
        "Visitor angelegt: %s %s, Wohnung %s, Booking %s, Systeme: %s%s",
        first, last, property_name, booking_id, ", ".join(succeeded),
        f" (unbestätigt: {', '.join(unconfirmed)})" if unconfirmed else "",
    )

    await record_visit(
        property_name, first, last, pin, start_ts, end_ts,
        succeeded + [f"{u} (unbestätigt)" for u in unconfirmed], "Webhook", booking_id,
    )

    await push_pin_to_smoobu(session, booking_id, pin)

    systeme = ", ".join(succeeded + [f"{u} (unbestätigt)" for u in unconfirmed])
    return web.Response(
        text=f"OK – Visitor {first} {last}, PIN {pin}, Wohnung: {property_name}, Systeme: {systeme}",
        status=200,
    )


DASHBOARD_STYLE = """
    * { box-sizing: border-box; }
    body { font-family: -apple-system, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; color: #222; }
    h1, h2 { margin-top: 2rem; }
    table { border-collapse: collapse; width: 100%; margin-top: 0.5rem; }
    th, td { text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid #ddd; }
    th { background: #f2f2f2; }
    form { margin-top: 0.5rem; display: grid; gap: 0.6rem; max-width: 420px; }
    .field-row { display: flex; gap: 0.6rem; }
    .field-row > div { flex: 1; }
    label { font-weight: bold; font-size: 0.9rem; }
    input, select { padding: 0.5rem; font-size: 1rem; width: 100%; box-sizing: border-box; }
    button { padding: 0.6rem 1rem; font-size: 1rem; cursor: pointer; }
    .msg-error { background: #fdecea; border: 1px solid #f5c6cb; padding: 0.6rem 1rem; border-radius: 4px; overflow-wrap: anywhere; }
    .msg-success { background: #e6f4ea; border: 1px solid #b7dfc0; padding: 0.6rem 1rem; border-radius: 4px; }
    .pin { font-size: 1.4rem; font-weight: bold; letter-spacing: 0.1rem; }
    .pin-unknown { font-size: 0.95rem; font-weight: normal; font-style: italic; letter-spacing: normal; color: #888; }
    .hint { font-size: 0.85rem; color: #666; margin-top: 0.3rem; }

    @media (max-width: 640px) {
        body { margin: 1rem auto; padding: 0 0.75rem; }
        h1 { font-size: 1.4rem; margin-top: 0.5rem; }
        h2 { font-size: 1.15rem; margin-top: 1.5rem; }
        form { max-width: none; }
        button { width: 100%; }

        table.stack, table.stack thead, table.stack tbody, table.stack th, table.stack td, table.stack tr {
            display: block;
        }
        table.stack thead { position: absolute; left: -9999px; top: -9999px; }
        table.stack tr {
            border: 1px solid #ddd; border-radius: 8px; margin-bottom: 0.6rem; padding: 0.2rem 0;
        }
        table.stack td {
            display: flex; justify-content: space-between; align-items: center; gap: 0.75rem;
            padding: 0.45rem 0.7rem; border-bottom: 1px dashed #eee; text-align: right;
        }
        table.stack td:last-child { border-bottom: none; }
        table.stack td::before {
            content: attr(data-label); font-weight: bold; color: #555; text-align: left;
        }
        table.stack td.empty-row {
            display: block; text-align: center; color: #666; padding: 0.8rem 0.7rem;
        }
        table.stack td.empty-row::before { content: none; }
        table.stack td.td-action { justify-content: center; }
        table.stack td.td-action::before { content: none; }
        table.stack td.pin-unknown::before { font-style: normal; font-weight: bold; color: #555; }
    }
"""


def render_dashboard(bookings, homes_list, history=None, form=None, error=None, success=None, bookings_error=None):
    form = form or {}
    history = history or []

    def esc(v):
        return html.escape(str(v)) if v is not None else ""

    rows = []
    for b in bookings:
        apartment_name = (b.get("apartment") or {}).get("name", "")
        booking_id = b.get("id")
        rows.append(f"""
            <tr>
                <td data-label="Gast">{esc(b.get('guest-name'))}</td>
                <td data-label="Wohnung">{esc(apartment_name)}</td>
                <td data-label="Anreise">{esc(b.get('arrival'))}</td>
                <td data-label="Abreise">{esc(b.get('departure'))}</td>
                <td class="td-action"><a href="?booking_id={esc(booking_id)}#anlegen">Besucher anlegen</a></td>
            </tr>
        """)
    bookings_html = "".join(rows) if rows else '<tr><td colspan="5" class="empty-row">Keine aktuellen Buchungen gefunden.</td></tr>'

    history_rows = []
    for h in history:
        name = f"{h.get('first_name', '')} {h.get('last_name', '')}".strip()
        pin_class = "pin" if h.get("pin") != "unbekannt" else "pin pin-unknown"
        history_rows.append(f"""
            <tr>
                <td data-label="Gast">{esc(name)}</td>
                <td data-label="Wohnung">{esc(h.get('home'))}</td>
                <td data-label="PIN" class="{pin_class}">{esc(h.get('pin'))}</td>
                <td data-label="Zeitraum">{esc(format_ts(h['start_ts']))} – {esc(format_ts(h['end_ts']))}</td>
                <td data-label="System(e)">{esc(', '.join(h.get('systems', [])))}</td>
                <td data-label="Quelle">{esc(h.get('source'))}</td>
            </tr>
        """)
    history_html = "".join(history_rows) if history_rows else '<tr><td colspan="6" class="empty-row">Noch keine aktuellen/kommenden Besucher angelegt.</td></tr>'
    unknown_pin_note = ""
    if any(h.get("pin") == "unbekannt" for h in history):
        unknown_pin_note = (
            '<p class="hint">PIN „unbekannt“: Dieser Besucher existiert in UniFi Access, wurde aber nicht '
            'über dieses Dashboard/den Webhook angelegt (z.&nbsp;B. manuell in der UniFi-App oder von vor '
            'dieser Funktion) - UniFi gibt den PIN im Nachhinein nicht mehr im Klartext zurück.</p>'
        )

    home_options = ['<option value="">-- Wohnung wählen --</option>']
    for h in homes_list:
        selected = " selected" if form.get("home") == h["name"] else ""
        home_options.append(f'<option value="{esc(h["name"])}"{selected}>{esc(h["name"])}</option>')

    banner = ""
    if bookings_error:
        banner += f'<p class="msg-error">Buchungen konnten nicht von Smoobu geladen werden: {esc(bookings_error)}</p>'
    if error:
        banner += f'<p class="msg-error">{esc(error)}</p>'
    if success:
        banner += f'<p class="msg-success">{success}</p>'

    return f"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Smoobu UniFi Access – Dashboard</title>
<style>{DASHBOARD_STYLE}</style>
</head>
<body>
<h1>Smoobu UniFi Access AutoPIN – Dashboard</h1>

{banner}

<h2>Aktuelle & kommende Besucher</h2>
<table class="stack">
    <thead><tr><th>Gast</th><th>Wohnung</th><th>PIN</th><th>Zeitraum</th><th>System(e)</th><th>Quelle</th></tr></thead>
    <tbody>{history_html}</tbody>
</table>
{unknown_pin_note}

<h2>Aktuelle & kommende Buchungen</h2>
<table class="stack">
    <thead><tr><th>Gast</th><th>Wohnung</th><th>Anreise</th><th>Abreise</th><th></th></tr></thead>
    <tbody>{bookings_html}</tbody>
</table>

<h2 id="anlegen">Besucher manuell anlegen</h2>
<p>Unabhängig von Smoobu nutzbar (z.&nbsp;B. für Handwerker oder Reinigung) oder über
„Besucher anlegen“ bei einer Buchung oben mit Name/Zeitraum vorausgefüllt.</p>
<form method="post" action="visitor">
    <div>
        <label for="home">Wohnung</label><br>
        <select name="home" id="home" required>{''.join(home_options)}</select>
    </div>
    <div>
        <label for="guest_name">Name des Besuchers</label><br>
        <input type="text" name="guest_name" id="guest_name" value="{esc(form.get('guest_name'))}" required>
    </div>
    <div class="field-row">
        <div>
            <label for="arrival">Anreise</label><br>
            <input type="date" name="arrival" id="arrival" value="{esc(form.get('arrival'))}" required>
        </div>
        <div>
            <label for="checkin_time">Uhrzeit</label><br>
            <input type="time" name="checkin_time" id="checkin_time" value="{esc(form.get('checkin_time', DEFAULT_CHECKIN_TIME))}" required>
        </div>
    </div>
    <div class="field-row">
        <div>
            <label for="departure">Abreise</label><br>
            <input type="date" name="departure" id="departure" value="{esc(form.get('departure'))}" required>
        </div>
        <div>
            <label for="checkout_time">Uhrzeit</label><br>
            <input type="time" name="checkout_time" id="checkout_time" value="{esc(form.get('checkout_time', DEFAULT_CHECKOUT_TIME))}" required>
        </div>
    </div>
    <input type="hidden" name="booking_id" value="{esc(form.get('booking_id'))}">
    <button type="submit">Besucher anlegen &amp; PIN erzeugen</button>
</form>

</body>
</html>"""


async def dashboard_page(request):
    session = request.app["http"]

    bookings = []
    bookings_error = None
    try:
        bookings = await fetch_smoobu_bookings(session)
    except aiohttp.ClientError as e:
        log.warning("Buchungsliste konnte nicht geladen werden: %s", e)
        bookings_error = str(e)

    form = {}
    booking_id = request.query.get("booking_id")
    if booking_id:
        match = next((b for b in bookings if str(b.get("id")) == booking_id), None)
        if match:
            apartment_name = (match.get("apartment") or {}).get("name", "")
            form = {
                "home": apartment_name if find_home(apartment_name) else "",
                "guest_name": match.get("guest-name", ""),
                "arrival": match.get("arrival", ""),
                "departure": match.get("departure", ""),
                "checkin_time": parse_smoobu_time(match.get("check-in"), DEFAULT_CHECKIN_TIME),
                "checkout_time": parse_smoobu_time(match.get("check-out"), DEFAULT_CHECKOUT_TIME),
                "booking_id": booking_id,
            }

    history = await build_display_history(session)

    return web.Response(
        text=render_dashboard(bookings, homes, history=history, form=form, bookings_error=bookings_error),
        content_type="text/html",
    )


async def dashboard_create_visitor(request):
    session = request.app["http"]
    data = await request.post()

    form = {
        "home": (data.get("home") or "").strip(),
        "guest_name": (data.get("guest_name") or "").strip(),
        "arrival": (data.get("arrival") or "").strip(),
        "departure": (data.get("departure") or "").strip(),
        "checkin_time": (data.get("checkin_time") or "").strip() or DEFAULT_CHECKIN_TIME,
        "checkout_time": (data.get("checkout_time") or "").strip() or DEFAULT_CHECKOUT_TIME,
        "booking_id": (data.get("booking_id") or "").strip(),
    }

    bookings, bookings_error = [], None
    try:
        bookings = await fetch_smoobu_bookings(session)
    except aiohttp.ClientError as e:
        bookings_error = str(e)

    history = await build_display_history(session)

    def error_page(message, status=400):
        return web.Response(
            text=render_dashboard(bookings, homes, history=history, form=form, error=message, bookings_error=bookings_error),
            content_type="text/html",
            status=status,
        )

    home = find_home(form["home"])
    if not home:
        return error_page(f"Unbekannte Wohnung '{form['home']}'.")

    if not (form["guest_name"] and form["arrival"] and form["departure"]):
        return error_page("Name, Anreise und Abreise sind Pflichtfelder.")

    try:
        start_ts = to_unix_datetime(form["arrival"], form["checkin_time"])
        end_ts = to_unix_datetime(form["departure"], form["checkout_time"])
    except ValueError as e:
        return error_page(f"Ungültiges Datums-/Zeitformat: {e}")

    guest = normalize(form["guest_name"])
    first, last = split_name(guest)
    remarks = "Manuell im Dashboard angelegt"
    if form["booking_id"]:
        remarks += f" (Buchung {form['booking_id']})"

    try:
        pin, succeeded, unconfirmed, failed = await create_access_for_home(
            session, home, first, last, start_ts, end_ts, remarks, home["name"],
        )
    except NoProviderConfigured as e:
        return error_page(str(e), status=422)

    if failed and not succeeded and not unconfirmed:
        log.error("Manuelle Zutritts-Erstellung fehlgeschlagen (Wohnung %s): %s", home["name"], failed)
        return error_page(f"Fehler beim Anlegen des Besuchers: {'; '.join(failed)}", status=502)

    log.info(
        "Manueller Visitor angelegt: %s %s, Wohnung %s, Systeme: %s%s",
        first, last, home["name"], ", ".join(succeeded),
        f" (unbestätigt: {', '.join(unconfirmed)})" if unconfirmed else "",
    )

    await record_visit(
        home["name"], first, last, pin, start_ts, end_ts,
        succeeded + [f"{u} (unbestätigt)" for u in unconfirmed], "Manuell", form["booking_id"] or None,
    )
    history = await build_display_history(session)

    systeme = ", ".join(succeeded) or "-"
    success = (
        f"Besucher <strong>{html.escape(first)} {html.escape(last)}</strong> angelegt "
        f"({html.escape(systeme)}). PIN: <span class=\"pin\">{pin}</span>"
    )
    if unconfirmed:
        success += (
            f'</p><p class="msg-error">Hinweis: {html.escape(", ".join(unconfirmed))} wurde angenommen, '
            f"aber nicht als aktiv bestätigt (Nukis API ist asynchron - ggf. Sync-Verzögerung, bitte "
            f"in ein paar Minuten im Nuki-Account prüfen)."
        )
    if failed:
        success += f'</p><p class="msg-error">Achtung, fehlgeschlagen: {html.escape("; ".join(failed))}'

    return web.Response(
        text=render_dashboard(bookings, homes, history=history, success=success, bookings_error=bookings_error),
        content_type="text/html",
    )


def build_main_app(http_session):
    """Webhook, Tür-Scan und Policy-Suche - direkt im LAN erreichbar (Port 8099)."""
    app = web.Application()
    app["http"] = http_session
    app.router.add_get("/", status)
    app.router.add_get("/scan", scan)
    app.router.add_get("/policies", policies)
    app.router.add_get("/nuki-locks", nuki_locks)
    app.router.add_post("/", handle)
    return app


def build_dashboard_app(http_session):
    """Dashboard - NUR über Home Assistant Ingress erreichbar (Port 8100, nicht
    öffentlich gemappt). Home Assistant übernimmt die Authentifizierung; ein
    eigenes Passwort ist hier bewusst nicht mehr nötig."""
    app = web.Application()
    app["http"] = http_session
    app.router.add_get("/", dashboard_page)
    app.router.add_post("/visitor", dashboard_create_visitor)
    return app


async def main():
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as http_session:
        main_runner = web.AppRunner(build_main_app(http_session))
        await main_runner.setup()
        await web.TCPSite(main_runner, "0.0.0.0", 8099).start()
        log.info("Webhook/Scan/Policies auf Port 8099 gestartet")

        dashboard_runner = web.AppRunner(build_dashboard_app(http_session))
        await dashboard_runner.setup()
        await web.TCPSite(dashboard_runner, "0.0.0.0", 8100).start()
        log.info("Dashboard (nur via Ingress) auf Port 8100 gestartet")

        try:
            await asyncio.Event().wait()
        finally:
            await main_runner.cleanup()
            await dashboard_runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
