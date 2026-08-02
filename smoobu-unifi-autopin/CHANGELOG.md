# Changelog

Alle nennenswerten Änderungen an diesem Add-on werden hier dokumentiert.

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
