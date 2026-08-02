# Changelog

Alle nennenswerten Änderungen an diesem Add-on werden hier dokumentiert.

## [3.7.0]

### Hinzugefügt
- **Nuki-Unterstützung.** Wohnungen können jetzt zusätzlich zu (oder statt) UniFi Access
  auch über Nuki Smart Locks mit Zutritt versehen werden - z.B. eine Wohnung mit zwei
  Türen, eine über UniFi, eine über Nuki. Neue Optionen: `nuki_api_token` (global) und
  `homeN_nuki_smartlock_id` (pro Wohnung, optional). Ist für eine Wohnung sowohl UniFi
  als auch Nuki konfiguriert, bekommen beide Systeme **denselben PIN**.
- Neuer Hilfsendpunkt `GET /nuki-locks` zur Ermittlung der Nuki-Smartlock-IDs (analog zu
  `/scan` und `/policies`).
- `create_unifi_visitor`/neue `create_nuki_code`-Funktion werden jetzt über eine gemeinsame
  `create_access_for_home()` orchestriert, die je Wohnung nur die tatsächlich konfigurierten
  Systeme anspricht und Teilfehler (ein System erfolgreich, eines fehlgeschlagen) klar im
  Log und in der Antwort/Dashboard-Meldung ausweist.

### Geändert
- **PIN-Erzeugung nutzt nur noch die Ziffern 1-9** (keine „0“ mehr). Physische
  Nuki-Keypads haben keine 0-Taste; damit funktioniert ein einzelner PIN jetzt zuverlässig
  auf UniFi- und Nuki-Türen derselben Wohnung.
- Dashboard-Menüpunkt in der HA-Seitenleiste von „AutoPIN Dashboard“ in „FeWo-Tür-PIN“
  umbenannt (`panel_title`).

### Hinweis
- Nuki-Zutritt per PIN erfordert ein **physisches Nuki Keypad** am Smart Lock - ohne
  Keypad kann kein Code eingegeben werden.
- Die Nuki-API-Anbindung (`PUT /smartlock/auth`) ist auf Basis der offiziellen Nuki-Doku
  und verifizierter Community-Beispiele umgesetzt, aber noch nicht gegen einen echten
  Nuki-Account getestet - bitte nach dem ersten Einsatz die Logs / `/nuki-locks` prüfen.

## [3.6.1]

### Geändert
- `panel_admin: false` gesetzt - der „FeWo-Tür-PIN“-Menüpunkt in der HA-Seitenleiste
  ist jetzt für alle Benutzer sichtbar, nicht nur für Administratoren.

## [3.6.0]

### Geändert
- **Dashboard läuft jetzt über Home Assistant Ingress statt Basic Auth.** Das Dashboard
  erscheint als eigener Menüpunkt „FeWo-Tür-PIN“ in der HA‑Seitenleiste und ist
  ausschließlich für eingeloggte Home‑Assistant‑Benutzer erreichbar - die Option
  `dashboard_password` entfällt vollständig, ein separates Passwort ist nicht mehr nötig.
- Das Add-on läuft nicht mehr im `host_network`‑Modus. Webhook, `/scan` und `/policies`
  bleiben unverändert über Port 8099 (jetzt per explizitem Port‑Mapping) erreichbar; das
  Dashboard läuft intern auf einem separaten, nicht öffentlich gemappten Port (8100), der
  ausschließlich über den Ingress‑Proxy von Supervisor erreichbar ist.

### Sicherheit
- Der bisherige Basic‑Auth‑Schutz (Passwort im Klartext über HTTP) entfällt zugunsten der
  echten Zugriffskontrolle durch Home Assistant selbst - keine eigene Passwortverwaltung
  und kein zusätzlicher, potenziell brute-forcebarer Login mehr nötig.

## [3.5.0]

### Hinzugefügt
- **Web‑Dashboard unter `/dashboard`** (Basic‑Auth, neue Option `dashboard_password`):
  - Übersicht aller aktuellen/kommenden Smoobu‑Buchungen (`GET /api/reservations`,
    HMAC‑signiert, gefiltert auf Buchungen mit Abreise in der Zukunft).
  - Manuelle Besucher‑Anlage in UniFi Access, wahlweise über eine Buchung vorausgefüllt
    oder komplett unabhängig von Smoobu (z.&nbsp;B. Handwerker, Reinigung).
  - Ohne gesetztes `dashboard_password` bleibt `/dashboard` deaktiviert (HTTP 503) - kein
    zusätzlicher ungeschützter Endpoint standardmäßig.
- Die Visitor-Erstellung in UniFi Access wurde in eine gemeinsame Funktion
  (`create_unifi_visitor`) extrahiert, die jetzt sowohl vom automatischen Smoobu-Webhook
  als auch von der manuellen Dashboard-Anlage genutzt wird.

### Hinweis
- Die manuelle Besucher-Anlage schreibt den PIN **nicht** an Smoobu zurück (kein Bezug zu
  einer konkreten Buchung) - der PIN wird stattdessen direkt im Dashboard angezeigt.
- Basic Auth läuft wie der Rest des Add-ons unverschlüsselt über HTTP im lokalen Netz -
  ausreichend hinter einem vertrauenswürdigen LAN, aber keine vollwertige Benutzerverwaltung.

## [3.0.1]

### Hinzugefügt
- `DOCS.md` und `CHANGELOG.md` liegen jetzt zusätzlich im Add-on-Ordner
  (`smoobu-unifi-autopin/`), da Home Assistant Dokumentation und Changelog nur von dort
  liest, nicht vom Repo-Root. Dadurch werden Dokumentation und Changelog jetzt korrekt in
  der Add-on-Übersicht angezeigt.
- Installationsbeschreibung um einen „Voraussetzungen“-Abschnitt (wo man UniFi-API-Token
  und Smoobu-API-Key/-Secret findet) sowie die genaue Ersteinrichtungs-Reihenfolge ergänzt.

### Sonstiges
- Repository-Struktur bereinigt: fortan gibt es nur noch einen dauerhaften `main`-Branch
  statt eines nach der jeweiligen Add-on-Version benannten Branches (zuvor `2.1.1`), um
  Verwechslungen zwischen Branch-Name und Add-on-Version zu vermeiden. Alte, nicht mehr
  benötigte Branches und Tags wurden entfernt.

## [3.0.0]

### Geändert
- **Asynchrones HTTP für alle externen Aufrufe**: `run.py` verwendet jetzt eine geteilte
  `aiohttp.ClientSession` statt der blockierenden `requests`-Bibliothek. Ein langsamer
  UniFi- oder Smoobu-Aufruf blockiert dadurch nicht mehr den gesamten Event-Loop, während
  parallel weitere Webhooks eintreffen.
- **Kryptographisch sichere PIN-Erzeugung**: `secrets.choice` statt `random.choice`.
- **Zeitkonstanter Vergleich des Webhook-Secrets**: `hmac.compare_digest` statt `!=`,
  um Timing-Angriffe auf das Secret zu erschweren.
- **`push_pin_to_smoobu`** ist jetzt eine `async`-Funktion und läuft über dieselbe
  `ClientSession` wie alle anderen Requests.

### Hinzugefügt
- **Strukturiertes Logging** nach stdout (sichtbar im Add-on-Log) für jeden angenommenen,
  abgelehnten oder fehlgeschlagenen Webhook sowie für UniFi-/Smoobu-Fehler, die zuvor
  entweder nur in der HTTP-Antwort oder gar nicht sichtbar waren (`push_pin_to_smoobu`
  hat Fehler bisher komplett stumm verschluckt).
- Validierung des Webhook-Bodies: ungültiges JSON, ein nicht-Objekt-Payload und ein
  ungültiges Datumsformat liefern jetzt eine saubere `400`-Antwort statt eines
  unbehandelten Absturzes.
- Warnung im Log, wenn dieselbe Wohnung mehrfach konfiguriert ist (`homeN_name`),
  statt den Eintrag still zu überschreiben.

### Entfernt
- **`scan.py` entfernt.** Die Datei wurde nie vom Dockerfile gestartet (nur `run.py` lief),
  wodurch der dort dokumentierte Tür-Scan auf Port 8098 seit Einführung nie funktioniert hat.
  Die Funktionalität existiert bereits seit 2.3.0 als `/scan`-Route direkt in `run.py` auf
  Port 8099 - die tote Datei blieb bis jetzt nur ungenutzt im Repo liegen.
- Abhängigkeit `requests` aus dem Dockerfile entfernt (durch `aiohttp` ersetzt); `aiohttp`
  ist jetzt auf eine feste Version gepinnt.

### Dokumentation
- README/Dokumentation komplett überarbeitet: neuer `/scan`- und `/policies`-Port (8099
  statt 8098), `smoobu_api_secret`-Option dokumentiert, Hinweis auf die Webhook-Filterung
  nach `action`-Typ, aktualisierte Dateistruktur.

---

## Bisherige Versionen (Kurzüberblick)

- **2.5.0** – Umstellung der Smoobu-Anbindung auf HMAC-Authentifizierung
  (`smoobu_api_secret`, `X-API-Key`/`X-Timestamp`/`X-Nonce`/`X-Signature`-Header), da
  Smoobu den alten `Api-Key`-Header abkündigt. Webhook-Verarbeitung an das reale,
  verschachtelte Smoobu-Payload-Format (`action`/`data`/`data.apartment`) angepasst und
  um eine Filterung nach Event-Typ (`newReservation`/`updateReservation`) ergänzt.
- **2.4.0** – `/policies`-Endpoint zum Auffinden von Access-Policy-IDs hinzugefügt.
- **2.3.0** – `/scan`-Endpoint direkt in `run.py` implementiert; Anpassungen an eine
  neue Smoobu-API-Version.
- **2.1.0–2.1.1** – Multi-Wohnungs-Support (`homes_count`, `homeN_*`-Optionen),
  `scan.py` als separates (nie gestartetes) Script hinzugefügt, Architektur-Support
  (amd64/aarch64) und Repository-Metadaten ergänzt.
- **1.0.x** – Erste Version: einzelne Wohnung, PIN- & Visitor-Erstellung in UniFi Access
  basierend auf Smoobu-Buchungen über den legacy `Api-Key`-Header.
