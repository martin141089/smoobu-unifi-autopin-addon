# 📘 Smoobu UniFi Access AutoPIN

**Multi‑Wohnungs PIN‑ & Visitor‑Automation für UniFi Access + Smoobu**

Dieses Add-on erlaubt die vollautomatische PIN‑ und Visitor‑Erstellung für UniFi Access
basierend auf Smoobu‑Buchungen — Multi‑Standort‑fähig und generisch für beliebige
Umgebungen (UDM‑SE, UniFi Access Controller etc.).

Es ist **komplett sicher**, denn:

✅ Alle geheimen Daten werden nur lokal im Home Assistant eingegeben  
✅ Keine IDs, Tokens oder IPs liegen im GitHub‑Repo  
✅ Alle Zugänge werden ausschließlich lokal über HTTPS abgefragt  
✅ Auto‑Scan der Türgruppen erfolgt lokal und manuell  
✅ Smoobu‑Anbindung über HMAC‑signierte Requests (keine geheimen Keys im Klartext‑Header)  
✅ Dashboard nur für eingeloggte Home‑Assistant‑Benutzer über Ingress erreichbar

***

# ✅ Funktionen

*   Automatische Visitor‑Erstellung in UniFi Access
*   Automatische PIN‑Generierung für Gäste (kryptographisch sicher)
*   Automatische Zuordnung einer Access Policy
*   Multi‑Wohnungs‑Support (1–4 Apartments)
*   Apartment‑Routing basierend auf Smoobu Property Name
*   Lokaler Tür‑Scan (Door‑Groups + Doors) unter `/scan`
*   Lokale Access‑Policy‑Suche unter `/policies`
*   **Web‑Dashboard** in der Home‑Assistant‑Seitenleiste (über Ingress, mit HA‑Login
    abgesichert): Übersicht aktueller/kommender Smoobu‑Buchungen sowie manuelle
    Besucher‑Anlage (auch unabhängig von Smoobu, z.&nbsp;B. für Handwerker oder Reinigung)
*   Korrekte Filterung des Smoobu‑Webhooks nach Event‑Typ (nur neue/geänderte Buchungen lösen eine PIN aus)
*   Unterstützung für Umlaute & Namens‑Trennung
*   Nicht‑blockierende Verarbeitung (asynchrones HTTP für UniFi & Smoobu)
*   Strukturierte Logs im Add-on‑Protokoll für jeden Webhook, Fehler und abgelehnte Requests
*   Keine sensiblen Daten im Code

***

# ✅ Voraussetzungen

Bevor du die Konfiguration ausfüllst, halte Folgendes bereit:

*   **UniFi Access:** IP/Hostname des Controllers sowie ein API‑Token
    (UniFi Access → Einstellungen → Sicherheit → **Erweiterte API-Einstellungen** → API‑Token erstellen)
*   **Smoobu:** `smoobu_api_key` **und** `smoobu_api_secret`
    (Smoobu → Einstellungen → **API**)
*   Ein selbst gewähltes **Webhook‑Secret** (beliebiger, ausreichend langer Zufallsstring)
*   Die **exakten Namen deiner Wohnungen in Smoobu** (Property Name) — dieser Name muss
    1:1 in `homeN_name` eingetragen werden, da darüber die Zuordnung erfolgt

***

# ✅ Ersteinrichtung – empfohlene Reihenfolge

1.  Konfiguration öffnen und alle Werte aus „Voraussetzungen“ eintragen (Türgruppen‑ und
    Policy‑IDs können zunächst leer bleiben)
2.  Add-on **starten**
3.  `/scan` und `/policies` aufrufen (siehe unten), um Door‑Group‑ und Policy‑IDs zu ermitteln
4.  IDs in die Konfiguration nachtragen und Add‑on **neu starten**
5.  Smoobu‑Webhook einrichten (siehe unten)
6.  Optional: Dashboard über den Menüpunkt „AutoPIN Dashboard“ in der HA‑Seitenleiste öffnen

***

# ✅ Konfiguration

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

Nach dem Ausfüllen der Konfiguration das Add-on starten.

***

# ✅ Door‑Scan & Policy‑Suche verwenden

Das Add-on enthält zwei lokale Hilfsseiten, um die für die Konfiguration nötigen IDs zu finden —
beide laufen auf demselben Port wie der Webhook (8099), ein separater Port ist nicht nötig.

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

# ✅ Dashboard verwenden

Das Dashboard läuft über **Home Assistant Ingress** und erscheint nach dem Start des
Add-ons als eigener Menüpunkt **„AutoPIN Dashboard“** in der Home‑Assistant‑Seitenleiste.
Ein Klick genügt — es ist automatisch mit deinem HA‑Login abgesichert, ein separates
Passwort ist nicht nötig und wird auch nicht mehr abgefragt.

Das Dashboard zeigt:

*   Eine Tabelle aller aktuellen und kommenden Smoobu‑Buchungen (Gast, Wohnung, An‑/Abreise)
*   Einen Link „Besucher anlegen“ pro Buchung, der das Formular darunter mit Name, Wohnung
    und Zeitraum vorausfüllt
*   Ein Formular zur **manuellen** Besucher‑Anlage — auch komplett unabhängig von einer
    Smoobu‑Buchung (z.&nbsp;B. für Handwerker oder Reinigungspersonal)

Beim Absenden wird wie beim automatischen Ablauf ein zufälliger PIN erzeugt und ein
befristeter Visitor in UniFi Access angelegt; der PIN wird direkt im Dashboard angezeigt
(bei manueller Anlage gibt es **keine** Rückschreibung an Smoobu, da kein Bezug zu einer
konkreten Buchung besteht).

**Sicherheitshinweis:** Der interne Dashboard‑Port (8100) wird bewusst **nicht** direkt im
Netzwerk exponiert — er ist ausschließlich über den Ingress‑Proxy von Home Assistant
erreichbar, also nur für bereits eingeloggte HA‑Benutzer. Webhook, `/scan` und `/policies`
bleiben unverändert direkt über Port 8099 erreichbar (Webhook braucht das für Smoobu).

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

# ✅ Betrieb

Nach Abschluss aller Konfigurationen:

*   Gäste erhalten automatisch PINs
*   Visitors erscheinen im UniFi Access
*   Türgruppen werden korrekt zugeordnet
*   Der Fortschritt jedes Webhooks (angenommen, ignoriert, fehlgeschlagen) ist im Add-on‑Log sichtbar

***

# ✅ Changelog

Siehe die Registerkarte **Changelog** dieses Add-ons oder
[CHANGELOG.md](https://github.com/martin141089/smoobu-unifi-autopin-addon/blob/main/smoobu-unifi-autopin/CHANGELOG.md)
im Repository.
