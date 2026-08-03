# 📘 Smoobu UniFi Access AutoPIN

**Multi‑Wohnungs PIN‑ & Visitor‑Automation für UniFi Access + Nuki + Smoobu**

Dieses Home‑Assistant‑Add-on erlaubt die vollautomatische PIN‑ und Visitor‑Erstellung  
für UniFi Access und/oder Nuki Smart Locks basierend auf Smoobu‑Buchungen —  
Multi‑Standort‑fähig, pro Wohnung/Tür frei kombinierbar und generisch für beliebige  
Umgebungen (UDM‑SE, UniFi Access Controller, Nuki Keypad etc.).

Es ist **komplett sicher**, denn:

✅ Alle geheimen Daten werden nur lokal im Home Assistant eingegeben  
✅ Keine IDs, Tokens oder IPs liegen im GitHub‑Repo  
✅ Alle Zugänge werden ausschließlich lokal über HTTPS abgefragt  
✅ Auto‑Scan der Türgruppen erfolgt lokal und manuell  
✅ Smoobu‑Anbindung über HMAC‑signierte Requests (keine geheimen Keys im Klartext‑Header)  
✅ Dashboard nur für eingeloggte Home‑Assistant‑Benutzer über Ingress erreichbar

***

# ✅ Funktionen

*   Automatische Visitor‑Erstellung in UniFi Access **und/oder** Keypad-Code-Erstellung
    auf Nuki Smart Locks — pro Wohnung frei kombinierbar (z.&nbsp;B. eine Tür UniFi,
    eine Tür Nuki, mit demselben PIN für beide)
*   Automatische PIN‑Generierung für Gäste (kryptographisch sicher, nur Ziffern 1–9,
    damit derselbe Code auf UniFi- und Nuki-Keypads funktioniert)
*   Automatische Zuordnung einer Access Policy
*   Multi‑Wohnungs‑Support (1–4 Apartments)
*   Apartment‑Routing basierend auf Smoobu Property Name
*   Lokaler Tür‑Scan (Door‑Groups + Doors) unter `/scan`
*   Lokale Access‑Policy‑Suche unter `/policies`
*   Lokale Nuki-Smart-Lock-Suche unter `/nuki-locks`
*   **Web‑Dashboard** in der Home‑Assistant‑Seitenleiste (über Ingress, mit HA‑Login
    abgesichert): Übersicht aktueller/kommender Smoobu‑Buchungen, Übersicht bereits
    angelegter Besucher inkl. PIN sowie manuelle Besucher‑Anlage (auch unabhängig von
    Smoobu, z.&nbsp;B. für Handwerker oder Reinigung)
*   Konfigurierbare Standard‑Check‑in‑/Check‑out‑Zeiten (`default_checkin_time`,
    `default_checkout_time`), pro Besuch zusätzlich individuell anpassbar
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
*   **Nuki** (nur falls du Nuki Smart Locks nutzt): ein API‑Token aus dem Nuki‑Web-Account
    (Nuki Web → Menü → **API** → Token erstellen) sowie ein **physisches Nuki Keypad**
    am jeweiligen Smart Lock — ohne Keypad kann kein PIN eingegeben werden
*   **Smoobu:** `smoobu_api_key` **und** `smoobu_api_secret`
    (Smoobu → Einstellungen → **API**)
*   Ein selbst gewähltes **Webhook‑Secret** (beliebiger, ausreichend langer Zufallsstring)
*   Die **exakten Namen deiner Wohnungen in Smoobu** (Property Name) — dieser Name muss
    1:1 in `homeN_name` eingetragen werden, da darüber die Zuordnung erfolgt
*   Optional: eine **Admin-E-Mail-Adresse** (`admin_email`) als Kontaktadresse für alle in
    UniFi Access angelegten Visitoren

***

# ✅ Installation

1.  In Home Assistant zu **Einstellungen → Add-ons → Add-on Store** wechseln
2.  Oben rechts auf die drei Punkte → **Repositories** klicken und folgende URL hinzufügen:

        https://github.com/martin141089/smoobu-unifi-autopin-addon

3.  Das Add-on **„Smoobu UniFi Access AutoPIN“** in der Liste suchen und **installieren**
4.  Add‑on **noch nicht starten** — zuerst die Konfiguration ausfüllen (siehe unten)
5.  Konfiguration öffnen, alle Werte aus „Voraussetzungen“ eintragen, speichern
6.  Add‑on **starten**
7.  Türgruppen‑, Policy‑ und (falls genutzt) Nuki-Smartlock-IDs über `/scan`, `/policies`
    bzw. `/nuki-locks` ermitteln (siehe unten), in die Konfiguration nachtragen und
    Add‑on **neu starten**
8.  Smoobu‑Webhook einrichten (siehe unten)

***

# ✅ Konfiguration (`config.yaml`)

Das Add-on bietet dynamische Wohnungsunterstützung:

*   Anzahl der Wohnungen (1–4)
*   Pro Wohnung, beliebig kombinierbar:
    *   Smoobu‑Wohnungsname
    *   UniFi Access: Access Policy ID + Door Group ID
    *   Nuki: Smart-Lock-ID (`home1_nuki_smartlock_id` usw.) — nur ausfüllen, wenn diese
        Wohnung (oder eine ihrer Türen) über Nuki läuft. Sowohl die Dezimalform (z.&nbsp;B.
        aus `/nuki-locks`) als auch die Hex-Form (z.&nbsp;B. `442f2ae4`, wie sie oft in der
        Nuki-App angezeigt wird) werden akzeptiert.

```yaml
options:
  smoobu_api_key: ""
  smoobu_api_secret: ""
  unifi_host: ""
  unifi_token: ""
  webhook_secret: ""
  nuki_api_token: ""
  admin_email: ""
  default_checkin_time: "15:00"
  default_checkout_time: "11:00"

  homes_count: 1

  home1_name: ""
  home1_policy_id: ""
  home1_door_group_id: ""
  home1_nuki_smartlock_id: ""

  home2_name: ""
  home2_policy_id: ""
  home2_door_group_id: ""
  home2_nuki_smartlock_id: ""

  home3_name: ""
  home3_policy_id: ""
  home3_door_group_id: ""
  home3_nuki_smartlock_id: ""

  home4_name: ""
  home4_policy_id: ""
  home4_door_group_id: ""
  home4_nuki_smartlock_id: ""
```

**Wichtig seit Version 3.9:** `default_checkin_time` (Standard `15:00`) und
`default_checkout_time` (Standard `11:00`) legen die Standard‑Uhrzeiten für Ein‑/Auszug
fest — bisher galt fix 00:00–23:59 Uhr. Liefert Smoobu für eine Buchung keine konkrete
Uhrzeit (das ist bei Smoobu häufig der Fall), greifen diese Standardwerte. Sowohl beim
automatischen Anlegen per Webhook als auch im Dashboard lässt sich die Uhrzeit pro Besuch
zusätzlich individuell ändern.

**Wichtig seit Version 3.8:** `admin_email` ist optional und wird bei UniFi‑Access‑Visitoren
(automatisch per Webhook wie auch manuell im Dashboard angelegt) im `email`‑Feld hinterlegt,
damit dort ein fester Ansprechpartner statt der (bei Smoobu-Buchungen nicht zuverlässig
vorhandenen) Gäste‑E‑Mail sichtbar ist. Bei Nuki gibt es für Keypad-Codes technisch kein
vergleichbares Feld, daher bleibt `admin_email` dort ohne Wirkung.

**Wichtig seit Version 3.7:** `nuki_api_token` sowie `homeN_nuki_smartlock_id` sind komplett
optional. Eine Wohnung kann nur UniFi, nur Nuki, oder beides gleichzeitig nutzen (z.&nbsp;B.
zwei Türen mit unterschiedlichen Systemen) — je nachdem, welche Felder für sie ausgefüllt
sind. Bei beiden gleichzeitig bekommen UniFi und Nuki **denselben PIN**, damit der Gast sich
nur einen Code merken muss.

**Wichtig seit Version 3.0:** Smoobu stellt seine Public API auf HMAC‑Authentifizierung um
(der alte `Api-Key`‑Header wird am 25.09.2026 abgeschaltet). Dafür wird zusätzlich zum
bestehenden `smoobu_api_key` ein `smoobu_api_secret` benötigt. Beide findest du in deinem
Smoobu‑Account unter **Einstellungen → API**.

***

# ✅ Door‑Scan, Policy‑ & Nuki-Lock-Suche verwenden

Das Add-on enthält lokale Hilfsseiten, um die für die Konfiguration nötigen IDs zu finden —
sie laufen auf demselben Port wie der Webhook (8099), ein separater Port ist nicht nötig.

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

### Nuki Smart Locks (nur relevant, wenn du Nuki nutzt):

    http://HOMEASSISTANT-IP:8099/nuki-locks

Ausgabe‑Beispiel:

    Gefundene Nuki Smart Locks:

    NAME: Haustür Weitblick   ID: 12345678

### Diese IDs trägst du im Add-on ein:

*   `home1_door_group_id:` / `home1_policy_id:` (UniFi)
*   `home1_nuki_smartlock_id:` (Nuki, falls genutzt)
*   `home2_door_group_id:` / `home2_policy_id:` / `home2_nuki_smartlock_id:`
*   …

***

# ✅ Dashboard verwenden

Das Dashboard läuft über **Home Assistant Ingress** und erscheint nach dem Start des
Add-ons als eigener Menüpunkt **„FeWo-Tür-PIN“** in der Home‑Assistant‑Seitenleiste.
Ein Klick genügt — es ist automatisch mit deinem HA‑Login abgesichert, ein separates
Passwort ist nicht nötig und wird auch nicht mehr abgefragt.

Das Dashboard zeigt:

*   Eine Tabelle **„Aktuelle & kommende Besucher“** mit allen bereits angelegten
    Besuchern inkl. Gast, Wohnung, **PIN**, Zeitraum, verwendetem/n System(en)
    (UniFi/Nuki) und Quelle (Smoobu‑Webhook oder manuell angelegt). Da UniFi Access den
    Klartext‑PIN nach der Anlage nicht mehr zurückgibt, merkt sich das Add-on diese
    Zuordnung selbst lokal. Vergangene Aufenthalte werden automatisch ausgeblendet, es
    werden nur aktuelle und kommende Besuche angezeigt. Zusätzlich werden Visitors
    angezeigt, die direkt in UniFi Access existieren, aber nicht über dieses Add-on
    angelegt wurden (z.&nbsp;B. manuell in der UniFi-App) — hier ist der PIN als
    „unbekannt“ markiert, da UniFi ihn nachträglich nicht mehr im Klartext herausgibt.
*   Eine Tabelle aller aktuellen und kommenden Smoobu‑Buchungen (Gast, Wohnung, An‑/Abreise)
*   Einen Link „Besucher anlegen“ pro Buchung, der das Formular darunter mit Name, Wohnung
    und Zeitraum (inkl. Uhrzeit, sofern von Smoobu geliefert, sonst Standardzeiten) vorausfüllt
*   Ein Formular zur **manuellen** Besucher‑Anlage — auch komplett unabhängig von einer
    Smoobu‑Buchung (z.&nbsp;B. für Handwerker oder Reinigungspersonal) — mit frei wählbarem
    Datum **und** Uhrzeit für An‑ und Abreise

Beim Absenden wird wie beim automatischen Ablauf ein zufälliger PIN erzeugt und je nach
Konfiguration der gewählten Wohnung ein befristeter Visitor in UniFi Access und/oder ein
Keypad-Code auf dem zugehörigen Nuki Smart Lock angelegt; der PIN wird direkt im Dashboard
angezeigt und erscheint anschließend auch in der Besucherübersicht (bei manueller Anlage
gibt es **keine** Rückschreibung an Smoobu, da kein Bezug zu einer konkreten Buchung
besteht).

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

# ✅ Run Mode

Nach Abschluss aller Konfigurationen:

*   Add-on starten
*   Gäste erhalten automatisch PINs
*   Visitors erscheinen im UniFi Access und/oder Codes auf dem Nuki Keypad, je nach
    Konfiguration der jeweiligen Wohnung
*   Türgruppen werden korrekt zugeordnet
*   Der Fortschritt jedes Webhooks (angenommen, ignoriert, fehlgeschlagen) ist im Add-on‑Log sichtbar
*   Nuki-Codes werden nach dem Anlegen zusätzlich verifiziert (Nukis API ist
    asynchron) — bleibt ein Code unbestätigt, steht das klar im Log/Dashboard, ohne
    UniFi oder die Smoobu-PIN-Rückschreibung zu blockieren

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
