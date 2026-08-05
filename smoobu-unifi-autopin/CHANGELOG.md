# Changelog

Alle nennenswerten Änderungen an diesem Add-on werden hier dokumentiert.

## [3.11.1]

### Behoben
- **„405: Method Not Allowed“ beim zweiten Besucher-Anlegen im Dashboard, ohne Neuladen
  der Seite.** Nach dem Anlegen eines Besuchers zeigte die Adressleiste `.../visitor`
  statt der Startseite. Der Link „Besucher anlegen“ war als rein query-basierter,
  pfad-loser Verweis (`?booking_id=...`) gebaut - so ein Verweis übernimmt laut
  URL-Standard den kompletten Pfad der aktuellen Seite unverändert, statt zur
  Startseite zurückzuführen. Ein Klick landete dadurch per GET auf `/visitor`, das
  aber nur POST-Anfragen entgegennimmt. Behoben, indem der Link jetzt explizit auf das
  Wurzelverzeichnis verweist (`./?booking_id=...`) und damit unabhängig vom aktuellen
  Pfad korrekt zur Startseite führt.

## [3.11.0]

### Geändert
- **Nuki-Bestätigung mit Retry statt einmaligem Check:** Bisher wurde direkt nach dem
  Anlegen eines Nuki-Codes einmalig geprüft, ob er in Nukis Autorisierungsliste
  erscheint - bei einer kurzen Sync-Verzögerung führte das öfter zu einem
  unnötigen „unbestätigt", obwohl der Code kurz danach doch ankam. Es wird jetzt bis
  zu dreimal geprüft (sofort, nach 3s, nach weiteren 5s - max. 8 Sekunden
  Gesamtwartezeit), bevor endgültig „unbestätigt" gemeldet wird. Eine echte
  Push-Bestätigung böte nur Nukis „Advanced API" (separater Freigabeprozess +
  OAuth2 + eigener Webhook-Empfänger) - für den hier genutzten einfachen
  API-Token nicht verfügbar, daher dieser pragmatische Kompromiss per Retry.

## [3.10.3]

### Behoben
- **Nuki-Keypad-Code zeigte den falschen Namen an** ("Manuell im Dashboard" bzw.
  "Smoobu Booking 123" statt des Gastnamens). Ursache: Beim Anlegen wurde
  versehentlich der interne `remarks`-Text (gedacht für UniFis Visitor-Notizfeld) auch
  als Nuki-Codename verwendet - durch Nukis ~20-Zeichen-Limit für den Namen wurde
  daraus z.&nbsp;B. „Manuell im Dashboard". Jetzt wird für Nuki der tatsächliche
  Gastname (Vor- + Nachname) übergeben.

## [3.10.2]

### Behoben
- **PIN wurde bei manueller Besucher-Anlage aus einer Smoobu-Buchung heraus nicht an
  Smoobu zurückgeschrieben.** Beim automatischen Webhook-Ablauf wurde der PIN schon
  immer als `doorPin`-Platzhalter an die Buchung übertragen (nutzbar über `[doorPin]`
  in Nachrichtenvorlagen); beim manuellen Anlegen über „Besucher anlegen“ bei einer
  konkreten Buchung im Dashboard fehlte dieser Schritt komplett, wodurch der PIN nicht
  automatisiert an den Gast verschickt werden konnte. Betroffen sind nur Besucher, die
  über eine ausgewählte Smoobu-Buchung angelegt wurden - rein manuelle Besucher ohne
  Buchungsbezug (z.&nbsp;B. Handwerker) sind unverändert, da es dort keine Buchung zum
  Zurückschreiben gibt.

## [3.10.1]

### Geändert
- **Dashboard übersichtlicher gestaltet:**
  - Neue Status-Spalte in der Besucherübersicht: farbiger Badge „Gerade vor Ort“
    (grün, Zeitraum läuft aktuell) bzw. „Kommend“ (blau) auf einen Blick.
  - Buchungen, für die bereits ein Besucher/PIN angelegt wurde, zeigen in der
    Buchungstabelle jetzt „✓ bereits angelegt“ statt eines erneut klickbaren Links
    „Besucher anlegen“ - weniger Redundanz zwischen Besucher- und Buchungstabelle.

## [3.10.0]

### Hinzugefügt
- **Besucherübersicht zeigt jetzt auch UniFi-Visitors, die nicht über dieses Add-on
  angelegt wurden** (z.&nbsp;B. manuell in der UniFi-Access-App, oder von vor
  Einführung der lokalen Besucher-Historie in 3.9.0). Das Dashboard fragt dafür
  zusätzlich aktuelle/kommende Visitors direkt bei UniFi Access ab (`GET /visitors`)
  und ergänzt sie um bereits bekannte Einträge, statt sie zu duplizieren. Da UniFi
  Access den PIN im Nachhinein nicht mehr im Klartext zurückgibt, wird er bei diesen
  Einträgen als „unbekannt" ausgewiesen (mit erklärendem Hinweistext im Dashboard).
  Schlägt der zusätzliche UniFi-Abruf fehl, wird einfach nur die lokale Historie
  gezeigt (best-effort, kein Fehler im Dashboard).

## [3.9.1]

### Geändert
- **Dashboard für Handy optimiert:** Die Tabellen „Aktuelle & kommende Besucher“ und
  „Aktuelle & kommende Buchungen“ wurden auf schmalen Bildschirmen bisher horizontal
  abgeschnitten. Sie werden jetzt auf Smartphones automatisch als Karten mit
  Beschriftung je Feld dargestellt statt als breite Tabelle. Zusätzlich: fehlendes
  Viewport-Meta-Tag ergänzt (korrekte Skalierung auf Mobilgeräten), Überschriften auf
  kleinen Bildschirmen verkleinert, Button „Besucher anlegen & PIN erzeugen“ nimmt auf
  dem Handy die volle Breite ein.

## [3.9.0]

### Hinzugefügt
- **Besucherübersicht im Dashboard:** Da UniFi Access den Klartext-PIN nach der
  Anlage nicht mehr zurückgibt (nur ein Token), merkt sich das Add-on jetzt selbst,
  welcher Besuch mit welchem PIN angelegt wurde. Das Dashboard zeigt eine neue Tabelle
  "Aktuelle & kommende Besucher" mit Gast, Wohnung, PIN, Zeitraum, verwendetem/n
  System(en) (UniFi/Nuki) und Quelle (Smoobu-Webhook oder manuell). Vergangene
  Aufenthalte werden automatisch entfernt, es werden nur aktuelle und kommende
  Besuche angezeigt.
- **Konfigurierbare Check-in-/Check-out-Zeiten:** Neue Optionen `default_checkin_time`
  (Standard `15:00`) und `default_checkout_time` (Standard `11:00`) ersetzen das bisher
  feste Zeitfenster von 00:00-23:59 Uhr. Wenn Smoobu für eine Buchung keine konkrete
  Uhrzeit liefert (das `check-in`/`check-out`-Feld ist bei Smoobu häufig leer), greifen
  diese Standardzeiten. Sowohl beim automatischen Anlegen per Webhook als auch bei der
  manuellen Anlage im Dashboard lässt sich die Uhrzeit zusätzlich zum Datum individuell
  pro Besuch anpassen.

## [3.8.1]

### Behoben
- **Nuki meldete "erfolgreich" (2xx), obwohl kein Code am Gerät ankam.** Nukis Web API
  ist laut Nuki-Entwicklerteam asynchron: ein erfolgreicher HTTP-Status auf die
  Code-Erstellung bestätigt nur die Annahme des Requests, nicht dass der Code
  tatsächlich am Smart Lock/Keypad ankommt. Nach dem Anlegen wird jetzt zusätzlich per
  `GET /smartlock/{id}/auth` geprüft, ob der Code in Nukis Autorisierungsliste
  erscheint.

### Geändert
- Neuer Status **"unbestätigt"** für Nuki (getrennt von "fehlgeschlagen"): Wenn der
  Code angenommen, aber (noch) nicht bestätigt wurde, wird das im Log und im
  Dashboard/Webhook-Ergebnis klar ausgewiesen, blockiert aber - anders als ein echter
  Fehler - nicht die PIN-Rückschreibung an Smoobu, da eine kurze Sync-Verzögerung bei
  Nuki normal sein kann.

## [3.8.0]

### Hinzugefügt
- Neue optionale Option **`admin_email`**: wird bei jeder UniFi-Access-Visitor-Anlage
  (automatisch per Smoobu-Webhook wie auch manuell im Dashboard) im offiziellen
  `email`-Feld des Visitors hinterlegt, damit dort ein fester Ansprechpartner statt der
  bei Smoobu-Buchungen nicht zuverlässig vorhandenen Gäste-E-Mail sichtbar ist.

### Hinweis
- Bei Nuki gibt es für Keypad-Codes (Typ 13) technisch kein vergleichbares
  Kontakt-/E-Mail-Feld (laut offizieller Doku und Community-Beispielen) - `admin_email`
  wirkt sich daher ausschließlich auf UniFi Access aus.

## [3.7.2]

### Behoben
- **Nuki-Codeanlage schlug mit `500, message='Server Error'` fehl.** Zwei Ursachen
  (gefunden über einen gelösten Nuki-Forum-Thread mit funktionierendem Beispiel-Body):
  - Nuki erwartet das Feld `smartlockIds` als **Array**, nicht `smartlockId` als
    Einzelwert.
  - Der `name` im Code ist auf ca. 20 Zeichen begrenzt; unsere bisherigen Texte
    (z.B. „Manuell im Dashboard angelegt (Buchung 12345)“) waren deutlich länger und
    wurden jetzt auf 20 Zeichen gekürzt.

## [3.7.1]

### Behoben
- **Nuki-Smartlock-ID als Hex-String führte zu einem Absturz** (`invalid literal for
  int() with base 10: '442f2ae4'`). Nuki zeigt die Smart-Lock-ID je nach Quelle
  unterschiedlich an - die Web API liefert eine Dezimalzahl, die Nuki-App/das Gerät oft
  die Hex-Form. `home N_nuki_smartlock_id` akzeptiert jetzt beide Formate.
- Der Fehler wurde zusätzlich fälschlich als „für diese Wohnung ist nichts konfiguriert“
  angezeigt statt als echter Fehler geloggt, weil ein zu weit gefasstes `except
  ValueError` die interne ID-Parsing-Exception mit dem eigentlich gemeinten
  „kein System konfiguriert“-Fall verwechselt hat. Dafür gibt es jetzt eine eigene,
  spezifischere Exception (`NoProviderConfigured`).

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
