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
NOTIFY_ON_FAILURE = bool(opts.get("notify_on_failure", True))

HISTORY_PATH = Path("/data/visitor_history.json")
HISTORY_LOCK = asyncio.Lock()

# Fuer Benachrichtigungen bei fehlgeschlagenen/nicht bestaetigten PINs wird die
# Home-Assistant-Core-API ueber den Supervisor-Proxy angesprochen (erfordert
# "homeassistant_api: true" in config.yaml, dann steht SUPERVISOR_TOKEN automatisch
# als Env-Var zur Verfuegung - kein eigener HA-Long-Lived-Token noetig).
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
HA_API_BASE = "http://supervisor/core/api"
HA_NOTIFICATION_ID = "smoobu_autopin_failure"


async def notify_ha_failure(session, guest, home_name, reason):
    """Meldet einen fehlgeschlagenen oder dauerhaft unbestaetigten PIN an Home
    Assistant - als persistent_notification (sofort sichtbar in der HA-Glocke, ohne
    Zusatzkonfiguration) und als Event "smoobu_autopin_failed" (fuer eigene
    Automatisierungen, z.B. Push-Benachrichtigung aufs Handy). Best-effort: ein
    Fehler hier wird nur geloggt, blockiert aber nie den eigentlichen Ablauf."""
    if not NOTIFY_ON_FAILURE or not SUPERVISOR_TOKEN:
        return

    headers = {
        "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
        "Content-Type": "application/json",
    }
    title = "AutoPIN: Zutritt nicht angelegt"
    message = f"{guest} ({home_name}): {reason}"

    try:
        async with session.post(
            f"{HA_API_BASE}/services/persistent_notification/create",
            headers=headers,
            json={"title": title, "message": message, "notification_id": HA_NOTIFICATION_ID},
        ) as r:
            r.raise_for_status()
    except aiohttp.ClientError as e:
        log.warning("HA-Benachrichtigung (persistent_notification) fehlgeschlagen: %s", e)

    try:
        async with session.post(
            f"{HA_API_BASE}/events/smoobu_autopin_failed",
            headers=headers,
            json={"guest": guest, "home": home_name, "reason": reason},
        ) as r:
            r.raise_for_status()
    except aiohttp.ClientError as e:
        log.warning("HA-Event 'smoobu_autopin_failed' konnte nicht gefeuert werden: %s", e)


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


def ts_to_date_time(ts):
    """Kehrt to_unix_datetime() um - liefert (Datum, Uhrzeit) als getrennte Strings
    fuer die Vorbefuellung von <input type="date"> / <input type="time">."""
    dt = datetime.datetime.fromtimestamp(ts)
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")


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
    """Legt einen befristeten Visitor in UniFi Access an und gibt dessen Visitor-ID
    zurueck (aus "data.id" der Antwort) - wird lokal gespeichert, um den Visitor
    spaeter (z.B. bei einer Zeitraum-Aenderung) per PUT /visitors/:id aktualisieren
    zu koennen, statt ihn neu anlegen zu muessen.

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
        payload = await r.json()
    return (payload.get("data") or {}).get("id")


async def update_unifi_visitor(session, home, visitor_id, first, last, start_ts, end_ts, remarks, visitor_company):
    """Aktualisiert Zeitraum (und Stammdaten) eines bestehenden UniFi-Access-Visitors
    per PUT /visitors/:id, ohne ihn neu anzulegen. Der PIN wird bewusst NICHT
    mitgeschickt: Der Update-Endpunkt kennt laut UniFi-Doku kein "pin_code"-Feld
    (dafuer gibt es die separaten Assign/Unassign-PIN-Endpunkte) - der bestehende PIN
    bleibt dadurch unangetastet erhalten.
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
        "access_policy_ids": [home["policy"]],
    }
    if ADMIN_EMAIL:
        visitor_payload["email"] = ADMIN_EMAIL
    async with session.put(
        f"{UNIFI_BASE}/visitors/{visitor_id}",
        headers=UNIFI_HEADERS,
        json=visitor_payload,
        ssl=False,
    ) as r:
        r.raise_for_status()


# Wartezeiten (Sekunden) vor jedem Bestaetigungs-Versuch - erster Versuch sofort,
# danach zunehmender Abstand, um Nukis asynchroner Sync eine faire Chance zu geben,
# bevor "unbestaetigt" gemeldet wird.
NUKI_CONFIRM_RETRY_DELAYS = (0, 3, 5)


async def _find_nuki_auth(session, lock_id, pin):
    """Sucht die Autorisierung mit dem angegebenen Code in Nukis Autorisierungsliste.
    Gibt das Auth-Objekt (inkl. "id") zurueck, wenn gefunden und ohne Fehler, sonst
    None."""
    try:
        async with session.get(f"{NUKI_API_HOST}/smartlock/{lock_id}/auth", headers=NUKI_HEADERS) as r:
            r.raise_for_status()
            auths = await r.json()
    except aiohttp.ClientError as e:
        log.warning("Nuki-Bestaetigung konnte nicht abgerufen werden (Smartlock %s): %s", lock_id, e)
        return None

    match = next((a for a in auths if a.get("code") == int(pin)), None)
    if match is None:
        return None
    if match.get("error"):
        log.warning("Nuki meldet Fehler für Code auf Smartlock %s: %s", lock_id, match.get("error"))
        return None
    return match


async def create_nuki_code(session, smartlock_id, pin, name, start_ts, end_ts):
    """Legt einen befristeten Keypad-Code auf einem Nuki Smart Lock an und prueft
    anschliessend mit mehreren Versuchen, ob er tatsaechlich in Nukis
    Autorisierungsliste ankommt.

    Erfordert ein physisches Nuki Keypad am Smart Lock - ohne Keypad kann kein Code
    eingegeben werden. type 13 = Keypad-Code. "smartlockIds" ist ein Array (nicht
    "smartlockId" als Einzelwert) und "name" ist auf ca. 20 Zeichen begrenzt - beides
    gemaess einem geloesten Nuki-Forum-Thread mit funktionierendem Beispiel-Body
    (https://developer.nuki.io/t/422-error-when-creating-type-13-authorization-via-web-api-keypad-2/35593).

    Nukis Web API ist laut Nuki-Entwicklerteam asynchron: ein 2xx auf den PUT-Request
    bestaetigt nur die Annahme, nicht dass der Code tatsaechlich am Schloss ankommt
    (https://developer.nuki.io/t/oauth2-api-integration-seems-accepted-but-no-keypad-
    codes-created-redirect-uri-cant-be-saved-500-error/35811). Ein offizieller
    Push-Status dazu existiert nur ueber Nukis "Advanced API" (separater
    Freigabeprozess + OAuth2 + eigener Webhook-Empfaenger) und ist fuer den simplen
    statischen API-Token, den dieses Add-on nutzt, nicht verfuegbar. Deshalb wird
    stattdessen per GET wiederholt geprueft (Zeitplan: NUKI_CONFIRM_RETRY_DELAYS),
    ob der Code in der Autorisierungsliste des Smart Locks erscheint. Gibt True
    zurueck, sobald bestaetigt (zusammen mit der Auth-ID - wird lokal gespeichert, um
    die Autorisierung spaeter per POST /smartlock/{id}/auth/{authId} aktualisieren zu
    koennen, statt sie neu anzulegen), sonst (False, None) nach dem letzten Versuch
    (kein Fehler - dann ist unklar, ob es eine laengere Sync-Verzoegerung ist oder der
    Code wirklich fehlt).
    """
    lock_id = _parse_nuki_smartlock_id(smartlock_id)
    body = {
        "smartlockIds": [lock_id],
        "name": name[:20],
        "code": int(pin),
        "type": 13,
        "allowedFromDate": _iso_millis_utc(start_ts),
        "allowedUntilDate": _iso_millis_utc(end_ts),
        # Laut offizieller Nuki-API-Referenz ist allowedWeekDays "mandatory for
        # setting time-limited access" - ohne dieses Feld wird die Datumsgrenze
        # (allowedFromDate/allowedUntilDate) von Nuki NICHT durchgesetzt und der Code
        # bleibt dauerhaft aktiv. 127 = alle Wochentage erlaubt (keine zusaetzliche
        # Wochentags-Einschraenkung, nur die Datumsgrenze zaehlt).
        "allowedWeekDays": 127,
    }
    async with session.put(
        f"{NUKI_API_HOST}/smartlock/auth",
        headers=NUKI_HEADERS,
        json=body,
    ) as r:
        r.raise_for_status()

    for attempt, delay in enumerate(NUKI_CONFIRM_RETRY_DELAYS, start=1):
        if delay:
            await asyncio.sleep(delay)
        match = await _find_nuki_auth(session, lock_id, pin)
        if match:
            if attempt > 1:
                log.info("Nuki-Code auf Smartlock %s erst nach %d. Versuch bestätigt", lock_id, attempt)
            return True, match.get("id")

    return False, None


async def update_nuki_code(session, smartlock_id, auth_id, name, start_ts, end_ts):
    """Aktualisiert Zeitraum (und Namen) einer bestehenden Nuki-Keypad-Autorisierung
    per POST /smartlock/{smartlockId}/auth/{authId}, ohne einen neuen Code anzulegen -
    der PIN selbst bleibt dadurch unveraendert. Wie beim Anlegen ist auch dieser
    Endpunkt laut Nukis eigener API-Beschreibung asynchron, daher dieselbe
    Retry-Bestaetigung wie bei create_nuki_code().

    Gibt True zurueck, sobald der neue Zeitraum bestaetigt wurde, sonst False.
    """
    lock_id = _parse_nuki_smartlock_id(smartlock_id)
    body = {
        "name": name[:20],
        "allowedFromDate": _iso_millis_utc(start_ts),
        "allowedUntilDate": _iso_millis_utc(end_ts),
        # Siehe Kommentar in create_nuki_code() - ohne allowedWeekDays wird die
        # Datumsgrenze von Nuki nicht durchgesetzt.
        "allowedWeekDays": 127,
    }
    async with session.post(
        f"{NUKI_API_HOST}/smartlock/{lock_id}/auth/{auth_id}",
        headers=NUKI_HEADERS,
        json=body,
    ) as r:
        r.raise_for_status()

    expected_from = body["allowedFromDate"]
    expected_until = body["allowedUntilDate"]
    for attempt, delay in enumerate(NUKI_CONFIRM_RETRY_DELAYS, start=1):
        if delay:
            await asyncio.sleep(delay)
        try:
            async with session.get(
                f"{NUKI_API_HOST}/smartlock/{lock_id}/auth/{auth_id}", headers=NUKI_HEADERS,
            ) as r:
                r.raise_for_status()
                current = await r.json()
        except aiohttp.ClientError as e:
            log.warning("Nuki-Update-Bestaetigung konnte nicht abgerufen werden (Auth %s): %s", auth_id, e)
            continue
        if current.get("error"):
            log.warning("Nuki meldet Fehler für Auth %s: %s", auth_id, current.get("error"))
            return False
        if current.get("allowedFromDate") == expected_from and current.get("allowedUntilDate") == expected_until:
            if attempt > 1:
                log.info("Nuki-Zeitraum-Update für Auth %s erst nach %d. Versuch bestätigt", auth_id, attempt)
            return True

    return False


# Die kurze synchrone Pruefung (NUKI_CONFIRM_RETRY_DELAYS, max. 8s) reicht oft nicht:
# Nukis Bridge synct nicht sofort, sondern erst beim naechsten Poll-Intervall mit der
# Cloud (laut Nuki-Forum typischerweise alle paar zehn Sekunden bis wenige Minuten) -
# der Code kommt also meistens trotzdem an, nur zeitversetzt. Statt den Nutzer dafuer
# im Browser warten zu lassen, wird im Hintergrund bis zu NUKI_BACKGROUND_RETRY_MINUTES
# lang weitergeprueft; bestaetigt sich der Code doch noch, korrigiert sich der
# Historie-Eintrag automatisch, ohne dass der Nutzer etwas tun muss.
NUKI_BACKGROUND_RETRY_INTERVAL = 20
NUKI_BACKGROUND_RETRY_MINUTES = 5


async def _apply_nuki_confirmation(auth_id, entry_id=None, home_name=None, pin=None, start_ts=None, end_ts=None):
    """Traegt eine nachtraeglich (im Hintergrund) bestaetigte Nuki-Auth-ID in den
    passenden Historie-Eintrag ein und entfernt den "(unbestätigt)"-Zusatz aus der
    Systemliste. Der Eintrag wird per entry_id gefunden (Zeitraum-Update-Fall) oder,
    falls die noch nicht existiert (frische Anlage - record_visit() laeuft erst nach
    create_access_for_home()), ueber Wohnung+PIN+Zeitraum als Ersatzschluessel."""
    async with HISTORY_LOCK:
        entries = _load_history()
        for e in entries:
            if entry_id:
                if e.get("entry_id") != entry_id:
                    continue
            elif not (
                e.get("home") == home_name and e.get("pin") == pin
                and e.get("start_ts") == start_ts and e.get("end_ts") == end_ts
            ):
                continue
            e["nuki_auth_id"] = auth_id
            e["systems"] = ["Nuki" if s.startswith("Nuki") else s for s in e.get("systems", [])]
            break
        _save_history(entries)


async def _reconfirm_nuki_later(session, lock_id, pin, first, last, home_name, start_ts, end_ts):
    """Hintergrund-Pruefung fuer eine frisch angelegte, zunaechst unbestaetigte
    Nuki-Autorisierung (siehe Kommentar bei NUKI_BACKGROUND_RETRY_INTERVAL)."""
    deadline = time.time() + NUKI_BACKGROUND_RETRY_MINUTES * 60
    while time.time() < deadline:
        await asyncio.sleep(NUKI_BACKGROUND_RETRY_INTERVAL)
        auth = await _find_nuki_auth(session, lock_id, pin)
        if auth and auth.get("id"):
            log.info(
                "Nuki-Code für %s %s (Wohnung %s) im Hintergrund nachträglich bestätigt", first, last, home_name,
            )
            await _apply_nuki_confirmation(
                auth["id"], home_name=home_name, pin=pin, start_ts=start_ts, end_ts=end_ts,
            )
            return
    log.warning(
        "Nuki-Code für %s %s (Wohnung %s) auch nach %d Minuten Hintergrund-Prüfung nicht bestätigt - "
        "bitte manuell im Nuki-Account prüfen",
        first, last, home_name, NUKI_BACKGROUND_RETRY_MINUTES,
    )
    await notify_ha_failure(
        session, f"{first} {last}".strip(), home_name,
        f"Nuki-Code wurde angenommen, aber auch nach {NUKI_BACKGROUND_RETRY_MINUTES} Minuten Prüfung nicht "
        "bestätigt - bitte manuell im Nuki-Account prüfen.",
    )


async def _reconfirm_nuki_update_later(session, lock_id, auth_id, expected_from, expected_until, first, last, home_name, entry_id):
    """Hintergrund-Pruefung fuer ein zunaechst unbestaetigtes Nuki-Zeitraum-Update
    (siehe Kommentar bei NUKI_BACKGROUND_RETRY_INTERVAL) - geprueft wird hier der
    Soll-Zeitraum der bekannten Auth-ID, nicht nur reine Code-Praesenz."""
    deadline = time.time() + NUKI_BACKGROUND_RETRY_MINUTES * 60
    while time.time() < deadline:
        await asyncio.sleep(NUKI_BACKGROUND_RETRY_INTERVAL)
        try:
            async with session.get(
                f"{NUKI_API_HOST}/smartlock/{lock_id}/auth/{auth_id}", headers=NUKI_HEADERS,
            ) as r:
                r.raise_for_status()
                current = await r.json()
        except aiohttp.ClientError as e:
            log.warning("Nuki-Hintergrund-Bestätigung (Update) fehlgeschlagen (Auth %s): %s", auth_id, e)
            continue
        if current.get("error"):
            continue
        if current.get("allowedFromDate") == expected_from and current.get("allowedUntilDate") == expected_until:
            log.info(
                "Nuki-Zeitraum-Update für %s %s (Wohnung %s) im Hintergrund nachträglich bestätigt",
                first, last, home_name,
            )
            await _apply_nuki_confirmation(auth_id, entry_id=entry_id)
            return
    log.warning(
        "Nuki-Zeitraum-Update für %s %s (Wohnung %s) auch nach %d Minuten Hintergrund-Prüfung nicht bestätigt - "
        "bitte manuell im Nuki-Account prüfen",
        first, last, home_name, NUKI_BACKGROUND_RETRY_MINUTES,
    )
    await notify_ha_failure(
        session, f"{first} {last}".strip(), home_name,
        f"Nuki-Zeitraum-Update wurde angenommen, aber auch nach {NUKI_BACKGROUND_RETRY_MINUTES} Minuten Prüfung "
        "nicht bestätigt - bitte manuell im Nuki-Account prüfen.",
    )


async def create_access_for_home(session, home, first, last, start_ts, end_ts, remarks, visitor_company):
    """Legt Zutritt fuer eine Wohnung an - bei UniFi Access und/oder Nuki, je nachdem
    was fuer sie konfiguriert ist (eine Wohnung kann z.B. eine UniFi-Tuer und eine
    Nuki-Tuer gleichzeitig haben). Beide Systeme bekommen denselben PIN.

    Gibt (pin, erfolgreich, unbestaetigt, fehlgeschlagen, unifi_visitor_id,
    nuki_auth_id) zurueck. "erfolgreich"/"unbestaetigt"/"fehlgeschlagen" sind Listen
    der betroffenen Systemnamen. "unbestaetigt" betrifft nur Nuki (asynchrone API -
    der Code wurde angenommen, ist aber nicht sicher bestaetigt) und zaehlt NICHT als
    Fehlschlag, blockiert also z.B. nicht die PIN-Rueckschreibung an Smoobu. Die
    beiden IDs werden lokal gespeichert, um Zeitraum-Aenderungen spaeter per Update
    statt Neuanlage durchfuehren zu koennen (None, wenn das jeweilige System nicht
    konfiguriert ist oder die ID nicht ermittelt werden konnte). Wird nichts
    konfiguriert gefunden, wird NoProviderConfigured geworfen.
    """
    pin = generate_pin()
    succeeded = []
    unconfirmed = []
    failed = []
    unifi_visitor_id = None
    nuki_auth_id = None

    if home["door_group"] and home["policy"]:
        try:
            unifi_visitor_id = await create_unifi_visitor(
                session, home, first, last, start_ts, end_ts, remarks, visitor_company, pin,
            )
            succeeded.append("UniFi Access")
        except aiohttp.ClientError as e:
            log.error("UniFi Visitor-Erstellung fehlgeschlagen (Wohnung %s): %s", home["name"], e)
            failed.append(f"UniFi Access ({e})")
            await notify_ha_failure(
                session, f"{first} {last}".strip(), home["name"], f"UniFi Access fehlgeschlagen: {e}",
            )

    if home["nuki_smartlock_id"]:
        try:
            nuki_name = f"{first} {last}".strip() or remarks
            confirmed, nuki_auth_id = await create_nuki_code(
                session, home["nuki_smartlock_id"], pin, nuki_name, start_ts, end_ts,
            )
            if confirmed:
                succeeded.append("Nuki")
            else:
                log.warning(
                    "Nuki-Code wurde angenommen, aber nicht sofort bestätigt (Wohnung %s) - Bridge synct "
                    "ggf. verzögert, Prüfung läuft im Hintergrund bis zu %d Minuten weiter",
                    home["name"], NUKI_BACKGROUND_RETRY_MINUTES,
                )
                unconfirmed.append("Nuki")
                asyncio.create_task(_reconfirm_nuki_later(
                    session, _parse_nuki_smartlock_id(home["nuki_smartlock_id"]), pin, first, last,
                    home["name"], start_ts, end_ts,
                ))
        except (aiohttp.ClientError, ValueError) as e:
            log.error("Nuki-Code-Erstellung fehlgeschlagen (Wohnung %s): %s", home["name"], e)
            failed.append(f"Nuki ({e})")
            await notify_ha_failure(session, f"{first} {last}".strip(), home["name"], f"Nuki fehlgeschlagen: {e}")

    if not succeeded and not unconfirmed and not failed:
        raise NoProviderConfigured(f"Für Wohnung '{home['name']}' ist weder UniFi Access noch Nuki konfiguriert")

    return pin, succeeded, unconfirmed, failed, unifi_visitor_id, nuki_auth_id


async def update_access_for_home(session, home, entry, first, last, start_ts, end_ts, remarks, visitor_company):
    """Aktualisiert den Zeitraum eines bereits bestehenden Zutritts (UniFi Access
    und/oder Nuki) anhand der in der lokalen Historie gespeicherten IDs, ohne den PIN
    zu aendern. Systeme, fuer die keine gespeicherte ID vorliegt (z.B. Alteintraege
    von vor dieser Funktion), werden uebersprungen und tauchen weder in "erfolgreich"
    noch in "fehlgeschlagen" auf.

    Gibt (erfolgreich, unbestaetigt, fehlgeschlagen) zurueck, analog zu
    create_access_for_home().
    """
    succeeded = []
    unconfirmed = []
    failed = []

    unifi_visitor_id = entry.get("unifi_visitor_id")
    if unifi_visitor_id and home["door_group"] and home["policy"]:
        try:
            await update_unifi_visitor(
                session, home, unifi_visitor_id, first, last, start_ts, end_ts, remarks, visitor_company,
            )
            succeeded.append("UniFi Access")
        except aiohttp.ClientError as e:
            log.error("UniFi Visitor-Update fehlgeschlagen (Wohnung %s): %s", home["name"], e)
            failed.append(f"UniFi Access ({e})")
            await notify_ha_failure(
                session, f"{first} {last}".strip(), home["name"], f"UniFi Access Update fehlgeschlagen: {e}",
            )

    nuki_auth_id = entry.get("nuki_auth_id")
    if nuki_auth_id and home["nuki_smartlock_id"]:
        try:
            nuki_name = f"{first} {last}".strip() or remarks
            confirmed = await update_nuki_code(
                session, home["nuki_smartlock_id"], nuki_auth_id, nuki_name, start_ts, end_ts,
            )
            if confirmed:
                succeeded.append("Nuki")
            else:
                log.warning(
                    "Nuki-Zeitraum-Update wurde angenommen, aber nicht sofort bestätigt (Wohnung %s) - Bridge "
                    "synct ggf. verzögert, Prüfung läuft im Hintergrund bis zu %d Minuten weiter",
                    home["name"], NUKI_BACKGROUND_RETRY_MINUTES,
                )
                unconfirmed.append("Nuki")
                asyncio.create_task(_reconfirm_nuki_update_later(
                    session, _parse_nuki_smartlock_id(home["nuki_smartlock_id"]), nuki_auth_id,
                    _iso_millis_utc(start_ts), _iso_millis_utc(end_ts), first, last, home["name"],
                    entry.get("entry_id"),
                ))
        except (aiohttp.ClientError, ValueError) as e:
            log.error("Nuki-Zeitraum-Update fehlgeschlagen (Wohnung %s): %s", home["name"], e)
            failed.append(f"Nuki ({e})")
            await notify_ha_failure(
                session, f"{first} {last}".strip(), home["name"], f"Nuki-Zeitraum-Update fehlgeschlagen: {e}",
            )

    return succeeded, unconfirmed, failed


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


async def record_visit(
    home_name, first, last, pin, start_ts, end_ts, systems, source, booking_id=None,
    unifi_visitor_id=None, nuki_auth_id=None,
):
    """Speichert einen angelegten Besucher lokal (persistent unter /data), damit das
    Dashboard eine Uebersicht zeigen kann - UniFi gibt den PIN nach dem Anlegen nicht
    mehr im Klartext zurueck, daher ist das die einzige Quelle dafuer. Es werden nur
    aktuelle/kommende Eintraege behalten (Abreise in der Zukunft); abgelaufene werden
    bei jedem Aufruf automatisch entfernt.

    unifi_visitor_id/nuki_auth_id werden mitgespeichert, damit der Zeitraum dieses
    Besuchers spaeter im Dashboard geaendert werden kann (per Update statt Neuanlage).
    Gibt die neu vergebene entry_id zurueck, ueber die der Eintrag spaeter im
    Dashboard wiedergefunden werden kann.
    """
    entry_id = uuid.uuid4().hex
    async with HISTORY_LOCK:
        entries = _load_history()
        now = time.time()
        entries = [e for e in entries if e.get("end_ts", 0) >= now]
        entries.append({
            "entry_id": entry_id,
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
            "unifi_visitor_id": unifi_visitor_id,
            "nuki_auth_id": nuki_auth_id,
        })
        entries.sort(key=lambda e: e["start_ts"])
        _save_history(entries)
    return entry_id


async def update_history_entry(entry_id, start_ts, end_ts, systems):
    """Aktualisiert Zeitraum und System-Status eines bestehenden Historie-Eintrags
    nach einer erfolgreichen Zeitraum-Aenderung. Unbekannte entry_id ist ein
    stiller No-Op (Eintrag kann inzwischen abgelaufen und automatisch entfernt
    worden sein)."""
    async with HISTORY_LOCK:
        entries = _load_history()
        for e in entries:
            if e.get("entry_id") == entry_id:
                e["start_ts"] = start_ts
                e["end_ts"] = end_ts
                e["systems"] = systems
                break
        now = time.time()
        entries = [e for e in entries if e.get("end_ts", 0) >= now]
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


async def find_history_entry(entry_id):
    """Sucht einen einzelnen Historie-Eintrag anhand seiner entry_id (fuer die
    Bearbeiten-Ansicht im Dashboard)."""
    for e in await get_current_history():
        if e.get("entry_id") == entry_id:
            return e
    return None


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


async def backfill_history_ids(session):
    """Verknuepft bestehende Historie-Eintraege (angelegt vor Einfuehrung der
    Bearbeiten-Funktion in 3.12.0 - denen also entry_id/unifi_visitor_id/nuki_auth_id
    fehlen) nachtraeglich mit ihrer echten Provider-ID, indem sie in UniFi Access
    anhand von Name+Zeitraum und in Nuki anhand des PIN-Codes wiedergefunden werden.
    Danach lassen sie sich wie neu angelegte Besucher im Dashboard bearbeiten.

    Betrifft ausschliesslich echte, vom Add-on selbst angelegte Historie-Eintraege -
    die rein zur Anzeige zusammengemischten "Nur in UniFi"-Eintraege (PIN "unbekannt")
    aus build_display_history() stehen nicht in der lokalen Datei und werden hier gar
    nicht erst gesehen.

    Gibt (verknuepft, unvollstaendig) zurueck - Anzahl der Eintraege, die durch diesen
    Lauf vollstaendig bearbeitbar wurden, bzw. bei denen weiterhin mindestens eine
    Provider-ID fehlt (z.B. weil der Visitor/Code in der Zwischenzeit geloescht wurde).
    """
    entries = await get_current_history()

    needs_unifi = any(
        "UniFi Access" in e.get("systems", []) and not e.get("unifi_visitor_id")
        for e in entries
    )
    raw_unifi_visitors = []
    if needs_unifi:
        try:
            raw_unifi_visitors = await fetch_unifi_visitors(session)
        except aiohttp.ClientError as e:
            log.warning("UniFi-Visitors konnten für Verknüpfung nicht geladen werden: %s", e)

    updates = {}
    fully_linked = 0
    still_incomplete = 0

    for e in entries:
        was_editable = bool(e.get("entry_id")) and bool(e.get("unifi_visitor_id") or e.get("nuki_auth_id"))
        if was_editable:
            continue

        key = (
            e.get("first_name", "").strip().lower(), e.get("last_name", "").strip().lower(),
            e.get("start_ts"), e.get("end_ts"),
        )
        fields = {}

        if "UniFi Access" in e.get("systems", []) and not e.get("unifi_visitor_id"):
            match = next((
                v for v in raw_unifi_visitors
                if (v.get("first_name") or "").strip().lower() == key[0]
                and (v.get("last_name") or "").strip().lower() == key[1]
                and v.get("start_time") == key[2]
                and v.get("end_time") == key[3]
            ), None)
            if match and match.get("id"):
                fields["unifi_visitor_id"] = match["id"]

        nuki_system = next((s for s in e.get("systems", []) if s.startswith("Nuki")), None)
        if nuki_system is not None and not e.get("nuki_auth_id"):
            home = find_home(e.get("home", ""))
            if home and home["nuki_smartlock_id"]:
                lock_id = _parse_nuki_smartlock_id(home["nuki_smartlock_id"])
                auth = await _find_nuki_auth(session, lock_id, e["pin"])
                if auth and auth.get("id"):
                    fields["nuki_auth_id"] = auth["id"]

        if not e.get("entry_id"):
            fields["entry_id"] = uuid.uuid4().hex

        if fields:
            updates[key] = fields

        now_editable = bool(fields.get("entry_id") or e.get("entry_id")) and bool(
            fields.get("unifi_visitor_id") or e.get("unifi_visitor_id")
            or fields.get("nuki_auth_id") or e.get("nuki_auth_id")
        )
        if now_editable:
            fully_linked += 1
        else:
            still_incomplete += 1

    if updates:
        async with HISTORY_LOCK:
            current = _load_history()
            for c in current:
                key = (
                    c.get("first_name", "").strip().lower(), c.get("last_name", "").strip().lower(),
                    c.get("start_ts"), c.get("end_ts"),
                )
                if key in updates:
                    c.update(updates[key])
            _save_history(current)

    return fully_linked, still_incomplete


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
        pin, succeeded, unconfirmed, failed, unifi_visitor_id, nuki_auth_id = await create_access_for_home(
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
        unifi_visitor_id, nuki_auth_id,
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
    .banner-form {
        display: flex; align-items: center; justify-content: space-between; gap: 1rem;
        background: #eef4fb; border: 1px solid #cfe0f0; border-radius: 6px;
        padding: 0.6rem 1rem; margin-top: 0.5rem; flex-wrap: wrap;
    }
    .banner-form p { margin: 0; font-size: 0.9rem; }
    .banner-form button { flex-shrink: 0; }
    .badge {
        display: inline-block; padding: 0.15rem 0.55rem; border-radius: 999px;
        font-size: 0.78rem; font-weight: bold; white-space: nowrap;
    }
    .badge-active { background: #e6f4ea; color: #1e7e34; }
    .badge-upcoming { background: #eaf1fb; color: #2c5aa0; }
    .badge-done { background: #f2f2f2; color: #555; }

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


def render_dashboard(
    bookings, homes_list, history=None, form=None, error=None, success=None, bookings_error=None,
    edit_entry=None, edit_form=None,
):
    form = form or {}
    history = history or []

    def esc(v):
        return html.escape(str(v)) if v is not None else ""

    now = time.time()
    known_booking_ids = {str(h.get("booking_id")) for h in history if h.get("booking_id")}

    rows = []
    for b in bookings:
        apartment_name = (b.get("apartment") or {}).get("name", "")
        booking_id = b.get("id")
        if booking_id is not None and str(booking_id) in known_booking_ids:
            action_cell = '<span class="badge badge-done">✓ bereits angelegt</span>'
        else:
            action_cell = f'<a href="./?booking_id={esc(booking_id)}#anlegen">Besucher anlegen</a>'
        rows.append(f"""
            <tr>
                <td data-label="Gast">{esc(b.get('guest-name'))}</td>
                <td data-label="Wohnung">{esc(apartment_name)}</td>
                <td data-label="Anreise">{esc(b.get('arrival'))}</td>
                <td data-label="Abreise">{esc(b.get('departure'))}</td>
                <td class="td-action">{action_cell}</td>
            </tr>
        """)
    bookings_html = "".join(rows) if rows else '<tr><td colspan="5" class="empty-row">Keine aktuellen Buchungen gefunden.</td></tr>'

    history_rows = []
    backfill_candidates = 0
    for h in history:
        name = f"{h.get('first_name', '')} {h.get('last_name', '')}".strip()
        pin_class = "pin" if h.get("pin") != "unbekannt" else "pin pin-unknown"
        is_active = h.get("start_ts", 0) <= now <= h.get("end_ts", 0)
        status_label = "Gerade vor Ort" if is_active else "Kommend"
        status_class = "badge badge-active" if is_active else "badge badge-upcoming"
        editable = bool(h.get("entry_id")) and bool(h.get("unifi_visitor_id") or h.get("nuki_auth_id"))
        if not editable and h.get("pin") != "unbekannt":
            backfill_candidates += 1
        if editable:
            edit_cell = f'<a href="./?edit={esc(h["entry_id"])}#zeitraum-aendern">Bearbeiten</a>'
        else:
            edit_cell = '<span class="hint">–</span>'
        history_rows.append(f"""
            <tr>
                <td data-label="Gast">{esc(name)}</td>
                <td data-label="Status"><span class="{status_class}">{status_label}</span></td>
                <td data-label="Wohnung">{esc(h.get('home'))}</td>
                <td data-label="PIN" class="{pin_class}">{esc(h.get('pin'))}</td>
                <td data-label="Zeitraum">{esc(format_ts(h['start_ts']))} – {esc(format_ts(h['end_ts']))}</td>
                <td data-label="System(e)">{esc(', '.join(h.get('systems', [])))}</td>
                <td data-label="Quelle">{esc(h.get('source'))}</td>
                <td data-label="Aktion" class="td-action">{edit_cell}</td>
            </tr>
        """)
    history_html = "".join(history_rows) if history_rows else '<tr><td colspan="8" class="empty-row">Noch keine aktuellen/kommenden Besucher angelegt.</td></tr>'
    unknown_pin_note = ""
    if any(h.get("pin") == "unbekannt" for h in history):
        unknown_pin_note = (
            '<p class="hint">PIN „unbekannt“: Dieser Besucher existiert in UniFi Access, wurde aber nicht '
            'über dieses Dashboard/den Webhook angelegt (z.&nbsp;B. manuell in der UniFi-App oder von vor '
            'dieser Funktion) - UniFi gibt den PIN im Nachhinein nicht mehr im Klartext zurück.</p>'
        )

    backfill_banner = ""
    if backfill_candidates:
        plural = "e" if backfill_candidates != 1 else ""
        backfill_banner = f"""
<form method="post" action="./link-existing" class="banner-form">
    <p>{backfill_candidates} bereits angelegte{plural} Besucher {'sind' if backfill_candidates != 1 else 'ist'}
    noch nicht bearbeitbar (angelegt vor Einführung dieser Funktion). Einmalig mit UniFi/Nuki abgleichen,
    um „Bearbeiten“ dafür freizuschalten.</p>
    <button type="submit">Jetzt verknüpfen</button>
</form>
"""

    edit_section_html = ""
    if edit_entry:
        edit_form = edit_form or {}
        edit_name = f"{edit_entry.get('first_name', '')} {edit_entry.get('last_name', '')}".strip()
        edit_section_html = f"""
<h2 id="zeitraum-aendern">Zeitraum ändern: {esc(edit_name)}</h2>
<p>Wohnung <strong>{esc(edit_entry.get('home'))}</strong> · PIN <span class="pin">{esc(edit_entry.get('pin'))}</span>
bleibt unverändert - es wird nur der Zeitraum in UniFi Access und/oder Nuki aktualisiert.</p>
<form method="post" action="./edit">
    <input type="hidden" name="entry_id" value="{esc(edit_entry.get('entry_id'))}">
    <div class="field-row">
        <div>
            <label for="edit_arrival">Anreise</label><br>
            <input type="date" name="arrival" id="edit_arrival" value="{esc(edit_form.get('arrival'))}" required>
        </div>
        <div>
            <label for="edit_checkin_time">Uhrzeit</label><br>
            <input type="time" name="checkin_time" id="edit_checkin_time" value="{esc(edit_form.get('checkin_time'))}" required>
        </div>
    </div>
    <div class="field-row">
        <div>
            <label for="edit_departure">Abreise</label><br>
            <input type="date" name="departure" id="edit_departure" value="{esc(edit_form.get('departure'))}" required>
        </div>
        <div>
            <label for="edit_checkout_time">Uhrzeit</label><br>
            <input type="time" name="checkout_time" id="edit_checkout_time" value="{esc(edit_form.get('checkout_time'))}" required>
        </div>
    </div>
    <button type="submit">Zeitraum speichern</button>
</form>
"""

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
{backfill_banner}
<table class="stack">
    <thead><tr><th>Gast</th><th>Status</th><th>Wohnung</th><th>PIN</th><th>Zeitraum</th><th>System(e)</th><th>Quelle</th><th>Aktion</th></tr></thead>
    <tbody>{history_html}</tbody>
</table>
{unknown_pin_note}
{edit_section_html}

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

    edit_entry = None
    edit_form = None
    edit_id = request.query.get("edit")
    if edit_id:
        edit_entry = await find_history_entry(edit_id)
        if edit_entry and (edit_entry.get("unifi_visitor_id") or edit_entry.get("nuki_auth_id")):
            arrival, checkin_time = ts_to_date_time(edit_entry["start_ts"])
            departure, checkout_time = ts_to_date_time(edit_entry["end_ts"])
            edit_form = {
                "arrival": arrival, "checkin_time": checkin_time,
                "departure": departure, "checkout_time": checkout_time,
            }
        else:
            edit_entry = None

    return web.Response(
        text=render_dashboard(
            bookings, homes, history=history, form=form, bookings_error=bookings_error,
            edit_entry=edit_entry, edit_form=edit_form,
        ),
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
        pin, succeeded, unconfirmed, failed, unifi_visitor_id, nuki_auth_id = await create_access_for_home(
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
        unifi_visitor_id, nuki_auth_id,
    )

    if form["booking_id"]:
        try:
            smoobu_booking_id = int(form["booking_id"])
        except ValueError:
            smoobu_booking_id = form["booking_id"]
        await push_pin_to_smoobu(session, smoobu_booking_id, pin)

    history = await build_display_history(session)

    systeme = ", ".join(succeeded) or "-"
    success = (
        f"Besucher <strong>{html.escape(first)} {html.escape(last)}</strong> angelegt "
        f"({html.escape(systeme)}). PIN: <span class=\"pin\">{pin}</span>"
    )
    if form["booking_id"]:
        success += " – PIN wurde außerdem an die verknüpfte Smoobu-Buchung übertragen."
    if unconfirmed:
        success += (
            f'</p><p class="msg-error">Hinweis: {html.escape(", ".join(unconfirmed))} wurde angenommen, '
            f"aber nicht sofort bestätigt (Nukis API ist asynchron). Die Prüfung läuft im Hintergrund "
            f"automatisch bis zu {NUKI_BACKGROUND_RETRY_MINUTES} Minuten weiter - der Status korrigiert "
            f"sich in der Besucherübersicht von selbst, sobald Nuki bestätigt."
        )
    if failed:
        success += f'</p><p class="msg-error">Achtung, fehlgeschlagen: {html.escape("; ".join(failed))}'

    return web.Response(
        text=render_dashboard(bookings, homes, history=history, success=success, bookings_error=bookings_error),
        content_type="text/html",
    )


async def dashboard_update_visitor(request):
    """Aendert Anreise/Abreise (Datum & Uhrzeit) eines bereits angelegten Besuchers -
    PIN bleibt gleich, es wird nur der Zeitraum in UniFi Access und/oder Nuki per
    Update aktualisiert (kein Neuanlegen, keine erneute PIN-Rueckschreibung an
    Smoobu noetig, da sich der PIN nicht aendert)."""
    session = request.app["http"]
    data = await request.post()

    entry_id = (data.get("entry_id") or "").strip()
    form = {
        "arrival": (data.get("arrival") or "").strip(),
        "departure": (data.get("departure") or "").strip(),
        "checkin_time": (data.get("checkin_time") or "").strip() or DEFAULT_CHECKIN_TIME,
        "checkout_time": (data.get("checkout_time") or "").strip() or DEFAULT_CHECKOUT_TIME,
    }

    bookings, bookings_error = [], None
    try:
        bookings = await fetch_smoobu_bookings(session)
    except aiohttp.ClientError as e:
        bookings_error = str(e)

    history = await build_display_history(session)
    entry = await find_history_entry(entry_id)

    def error_page(message, status=400):
        return web.Response(
            text=render_dashboard(
                bookings, homes, history=history, error=message, bookings_error=bookings_error,
                edit_entry=entry, edit_form=form,
            ),
            content_type="text/html",
            status=status,
        )

    if not entry or not (entry.get("unifi_visitor_id") or entry.get("nuki_auth_id")):
        return error_page(
            "Dieser Besucher kann nicht bearbeitet werden (kein bearbeitbarer Eintrag gefunden - "
            "ggf. bereits abgelaufen oder von vor Einführung dieser Funktion angelegt).",
            status=404,
        )

    home = find_home(entry["home"])
    if not home:
        return error_page(f"Wohnung '{entry['home']}' ist nicht mehr konfiguriert.")

    try:
        start_ts = to_unix_datetime(form["arrival"], form["checkin_time"])
        end_ts = to_unix_datetime(form["departure"], form["checkout_time"])
    except ValueError as e:
        return error_page(f"Ungültiges Datums-/Zeitformat: {e}")

    first = entry.get("first_name", "")
    last = entry.get("last_name", "")
    remarks = "Zeitraum geändert im Dashboard"
    if entry.get("booking_id"):
        remarks += f" (Buchung {entry['booking_id']})"

    succeeded, unconfirmed, failed = await update_access_for_home(
        session, home, entry, first, last, start_ts, end_ts, remarks, home["name"],
    )

    if not succeeded and not unconfirmed and not failed:
        return error_page("Für diesen Besucher sind keine aktualisierbaren Systeme hinterlegt.", status=422)

    if failed and not succeeded and not unconfirmed:
        log.error("Zeitraum-Update fehlgeschlagen (Wohnung %s): %s", home["name"], failed)
        return error_page(f"Fehler beim Ändern des Zeitraums: {'; '.join(failed)}", status=502)

    log.info(
        "Zeitraum geändert: %s %s, Wohnung %s, Systeme: %s%s",
        first, last, home["name"], ", ".join(succeeded),
        f" (unbestätigt: {', '.join(unconfirmed)})" if unconfirmed else "",
    )

    await update_history_entry(
        entry_id, start_ts, end_ts, succeeded + [f"{u} (unbestätigt)" for u in unconfirmed],
    )

    history = await build_display_history(session)

    systeme = ", ".join(succeeded) or "-"
    success = (
        f"Zeitraum für <strong>{html.escape(first)} {html.escape(last)}</strong> aktualisiert "
        f"({html.escape(systeme)})."
    )
    if unconfirmed:
        success += (
            f'</p><p class="msg-error">Hinweis: {html.escape(", ".join(unconfirmed))} wurde angenommen, '
            f"aber nicht sofort bestätigt (Nukis API ist asynchron). Die Prüfung läuft im Hintergrund "
            f"automatisch bis zu {NUKI_BACKGROUND_RETRY_MINUTES} Minuten weiter - der Status korrigiert "
            f"sich in der Besucherübersicht von selbst, sobald Nuki bestätigt."
        )
    if failed:
        success += f'</p><p class="msg-error">Achtung, fehlgeschlagen: {html.escape("; ".join(failed))}'

    return web.Response(
        text=render_dashboard(bookings, homes, history=history, success=success, bookings_error=bookings_error),
        content_type="text/html",
    )


async def dashboard_link_existing(request):
    """Verknuepft einmalig alle bestehenden Historie-Eintraege, denen noch die
    UniFi-Visitor-ID bzw. Nuki-Auth-ID fehlt (angelegt vor Einfuehrung der
    Bearbeiten-Funktion in 3.12.0), mit ihrem echten Provider-Datensatz - siehe
    backfill_history_ids()."""
    session = request.app["http"]

    fully_linked, still_incomplete = await backfill_history_ids(session)

    bookings, bookings_error = [], None
    try:
        bookings = await fetch_smoobu_bookings(session)
    except aiohttp.ClientError as e:
        bookings_error = str(e)

    history = await build_display_history(session)

    parts = []
    if fully_linked:
        parts.append(f"{fully_linked} Besucher erfolgreich verknüpft und jetzt bearbeitbar")
    if still_incomplete:
        parts.append(
            f"{still_incomplete} konnten nicht eindeutig zugeordnet werden "
            "(z. B. in UniFi/Nuki inzwischen gelöscht oder verändert)"
        )
    success = (" – ".join(parts) + ".") if parts else "Es gab keine Besucher, die noch verknüpft werden mussten."

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
    app.router.add_post("/edit", dashboard_update_visitor)
    app.router.add_post("/link-existing", dashboard_link_existing)
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
