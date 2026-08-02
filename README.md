# 📘 Smoobu UniFi Access AutoPIN

**Multi‑Wohnungs PIN‑ & Visitor‑Automation für UniFi Access + Smoobu**

Dieses Home‑Assistant‑Add-on erlaubt die vollautomatische PIN‑ und Visitor‑Erstellung  
für UniFi Access basierend auf Smoobu‑Buchungen — Multi‑Standort‑fähig und generisch  
für beliebige Umgebungen (UDM‑SE, UniFi Access Controller etc.).

Es ist **komplett sicher**, denn:

✅ Alle geheimen Daten werden nur lokal im Home Assistant eingegeben  
✅ Keine IDs, Tokens oder IPs liegen im GitHub‑Repo  
✅ Alle Zugänge werden ausschließlich lokal über HTTPS abgefragt  
✅ Auto‑Scan der Türgruppen erfolgt lokal und manuell  
✅ Smoobu‑Anbindung über HMAC‑signierte Requests (keine geheimen Keys im Klartext‑Header)

***

# ✅ Funktionen

*   Automatische Visitor‑Erstellung in UniFi Access
*   Automatische PIN‑Generierung für Gäste (kryptographisch sicher)
*   Automatische Zuordnung einer Access Policy
*   Multi‑Wohnungs‑Support (1–4 Apartments)
*   Apartment‑Routing basierend auf Smoobu Property Name
*   Lokaler Tür‑Scan (Door‑Groups + Doors) unter `/scan`
*   Lokale Access‑Policy‑Suche unter `/policies`
*   Korrekte Filterung des Smoobu‑Webhooks nach Event‑Typ (nur neue/geänderte Buchungen lösen eine PIN aus)
*   Unterstützung für Umlaute & Namens‑Trennung
*   Nicht‑blockierende Verarbeitung (asynchrones HTTP für UniFi & Smoobu)
*   Strukturierte Logs im Add-on‑Protokoll für jeden Webhook, Fehler und abgelehnte Requests
*   Keine sensiblen Daten im Code

***

# ✅ Voraussetzungen

Bevor du startest, halte Folgendes bereit:

*   **UniFi Access:** IP/Hostname des Controllers sowie ein API‑Token
    (UniFi Access → Einstellungen → Sicherheit → **Erweiterte API-Einstellungen** → API‑Token erstellen)
*   **Smoobu:** `smoobu_api_key` **und** `smoobu_api_secret`
    (Smoobu → Einstellungen → **API**)
*   Ein selbst gewähltes **Webhook‑Secret** (beliebiger, ausreichend langer Zufallsstring)
*   Die **exakten Namen deiner Wohnungen in Smoobu** (Property Name) — dieser Name muss
    1:1 in `homeN_name` eingetragen werden, da darüber die Zuordnung erfolgt

***

# ✅ Installation

1.  In Home Assistant zu **Einstellungen → Add-ons → Add-on Store** wechseln
2.  Oben rechts auf die drei Punkte → **Repositories** klicken und folgende URL hinzufügen:

        https://github.com/martin141089/smoobu-unifi-autopin-addon

3.  Das Add-on **„Smoobu UniFi Access AutoPIN“** in der Liste suchen und **installieren**
4.  Add‑on **noch nicht starten** — zuerst die Konfiguration ausfüllen (siehe unten)
5.  Konfiguration öffnen, alle Werte aus „Voraussetzungen“ eintragen, speichern
6.  Add‑on **starten**
7.  Türgruppen‑ und Policy‑IDs über `/scan` bzw. `/policies` ermitteln (siehe unten),
    in die Konfiguration nachtragen und Add‑on **neu starten**
8.  Smoobu‑Webhook einrichten (siehe unten)

***

# ✅ Konfiguration (`config.yaml`)

Das Add-on bietet dynamische Wohnungsunterstützung:

*   Anzahl der Wohnungen (1–4)
*   Pro Wohnung:
    *   Smoobu‑Wohnungsname
    *   Access Policy ID
    *   Door Group ID

```yaml
options:
  smoobu_api_key: ""
  smoobu_api_secret: ""
  unifi_host: ""
  unifi_token: ""
  webhook_secret: ""

  homes_count: 1

  home1_name: ""
  home1_policy_id: ""
  home1_door_group_id: ""

  home2_name: ""
  home2_policy_id: ""
  home2_door_group_id: ""

  home3_name: ""
  home3_policy_id: ""
  home3_door_group_id: ""

  home4_name: ""
  home4_policy_id: ""
  home4_door_group_id: ""
```

**Wichtig seit Version 3.0:** Smoobu stellt seine Public API auf HMAC‑Authentifizierung um
(der alte `Api-Key`‑Header wird am 25.09.2026 abgeschaltet). Dafür wird zusätzlich zum
bestehenden `smoobu_api_key` ein `smoobu_api_secret` benötigt. Beide findest du in deinem
Smoobu‑Account unter **Einstellungen → API**.

***

# ✅ Door‑Scan & Policy‑Suche verwenden

Das Add-on enthält zwei lokale Hilfsseiten, um die für die Konfiguration nötigen IDs zu finden —
beide laufen auf demselben Port wie der Webhook (8099), ein separater Port ist nicht mehr nötig.

### Türgruppen & Türen:

    http://HOMEASSISTANT-IP:8099/scan

Ausgabe‑Beispiel:

    === TÜRGRUPPE ===
    NAME: EG Wohnung
    ID:   5c496423-...

       - TÜR: Eingang EG → 6ff875d2-...

    === TÜRGRUPPE ===
    NAME: DG Wohnung
    ID:   e311ca94-...
       - TÜR: Eingang DG → d5573467-...

### Access Policies:

    http://HOMEASSISTANT-IP:8099/policies

### Diese IDs trägst du im Add-on ein:

*   `home1_door_group_id:`
*   `home1_policy_id:`
*   `home2_door_group_id:` / `home2_policy_id:`
*   …

***

# ✅ Smoobu Webhook konfigurieren

Webhook URL:

    http://HOMEASSISTANT-IP:8099/?secret=DEIN_SECRET

Smoobu sendet an diese eine URL **alle** Ereignistypen (neue Buchung, geänderte Buchung,
Stornierung, Preis-/Verfügbarkeitsänderungen, neue Nachrichten, …) — eine Auswahl einzelner
Events ist in Smoobu selbst nicht möglich. Das Add-on filtert deshalb intern und reagiert nur
auf `newReservation` und `updateReservation`; alle anderen Ereignisse werden mit HTTP 200
quittiert und ignoriert, ohne dass ein Visitor angelegt wird.

Platzhalter in Nachrichten:

    Tür-PIN: [doorPin]

***

# ✅ Run Mode

Nach Abschluss aller Konfigurationen:

*   Add-on starten
*   Gäste erhalten automatisch PINs
*   Visitors erscheinen im UniFi Access
*   Türgruppen werden korrekt zugeordnet
*   Der Fortschritt jedes Webhooks (angenommen, ignoriert, fehlgeschlagen) ist im Add-on‑Log sichtbar

***

# ✅ Dateistruktur des Add-ons

    /
    ├── config.yaml
    ├── run.py
    ├── DOCS.md          (Dokumentation, wird in Home Assistant angezeigt)
    ├── CHANGELOG.md     (Changelog, wird in Home Assistant angezeigt)
    └── Dockerfile

***

# ✅ Changelog

Siehe [smoobu-unifi-autopin/CHANGELOG.md](smoobu-unifi-autopin/CHANGELOG.md) für die
vollständige Versionshistorie. Dieselbe Datei wird auch im Update-Dialog von Home Assistant
angezeigt.

***
