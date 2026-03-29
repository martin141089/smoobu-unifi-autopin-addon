# ✅ **README.md – Smoobu → UniFi Access AutoPIN (Home Assistant Add-on)**

## 🔐 Automatische PIN‑ und Besucher‑Erstellung für UniFi Access & Smoobu

Dieses Add-on erzeugt vollautomatisch für jede neue oder aktualisierte Smoobu‑Buchung:

✅ Einen **Visitor** in **UniFi Access**  
✅ Automatisch gesetzte **PIN‑Codes**  
✅ Automatische Zuordnung zur gewünschten **Access Policy** (z. B. „Gaeste“)  
✅ Weitergabe der PIN an Smoobu über den Platzhalter **`[doorPin]`**

Alles basierend auf dem offiziellen **UniFi Access Developer API** (Port 12445).

***

## 🚀 **Features**

| Feature                                          | Beschreibung                             |
| ------------------------------------------------ | ---------------------------------------- |
| ✅ Automatische PIN‑Erzeugung                     | 6‑stellige Codes, je Buchung             |
| ✅ Vollautomatische Visitor‑Erstellung            | Name, Zeitraum, Bemerkung, PIN           |
| ✅ Automatische Zuordnung einer Access Policy     | z. B. „Gaeste“                           |
| ✅ Webhook‑Integration mit Smoobu                 | POST → Add‑on → UniFi Access             |
| ✅ Rückgabe des PIN an Smoobu                     | via API Custom Placeholder               |
| ✅ Minimal-Konfiguration in Home Assistant        | nur IP + Token + Policy                  |
| ✅ Keine Tür‑IDs notwendig                        | Besucher werden ohne Ressourcen angelegt |
| ✅ Unterstützt lokale UniFi Access Installationen | via <https://IP:12445>                   |

***

## 🧩 **Voraussetzungen**

Du benötigst:

*   ✅ Home Assistant (Supervisor / Add-on‑fähig)
*   ✅ UniFi Access installiert auf deiner UDM‑SE
*   ✅ API Token aus **Access → Settings → General → Advanced → API Token**
*   ✅ Smoobu Premium (Webhook‑Unterstützung)
*   ✅ Eine Access Policy (z. B. „Gaeste“)

***

## 🛠️ **Installation**

1.  Add-on in Home Assistant installieren
2.  Folgende Felder konfigurieren:

### ✅ Add-on Konfiguration

```yaml
smoobu_api_key: "DEIN_SMOOBU_API_KEY"
unifi_host: "192.168.1.1"            # NUR die IP!
unifi_token: "DEIN_ACCESS_API_TOKEN"
webhook_secret: "DEIN_GEHEIMES_SECRET"
access_policy_id: "0519dc46-ae09-4512-bc1d-9f961adcc389"
```

### Erklärung der Felder

| Feld               | Beschreibung                               |
| ------------------ | ------------------------------------------ |
| `smoobu_api_key`   | Dein Smoobu API‑Schlüssel                  |
| `unifi_host`       | IP-Adresse deiner UDM‑SE (nur IP!)         |
| `unifi_token`      | API Token aus UniFi Access (nicht aus OS!) |
| `webhook_secret`   | Freies Secret zur Absicherung              |
| `access_policy_id` | ID der UniFi Access Policy (z.B. „Gaeste“) |

***

## 🔎 **Access Policy ID herausfinden**

1.  UniFi Access öffnen
2.  Links: **Access Policies**
3.  Policy „Gaeste“ öffnen
4.  Die URL sieht z. B. so aus:

<!---->

    https://unifi.ui.com/.../settings/policies/0519dc46-ae09-4512-bc1d-9f961adcc389

➡️ Diese ID („0519dc46‑…”) trägst du ins Add-on ein

***

## 🔁 **Smoobu konfigurieren**

### Webhook einrichten:

    http://DEINE-HOME-ASSISTANT-IP:8099/?secret=DEIN_SECRET

Ereignisse aktivieren:

*   ✅ Buchung erstellt
*   ✅ Buchung aktualisiert

### Platzhalter in Nachrichten:

In Smoobu → Nachrichten:

    Ihr Tür-Code lautet: [doorPin]

***

## ✅ **Was passiert bei einer neuen Buchung?**

1.  Smoobu sendet Webhook → Add-on
2.  Add-on erzeugt
    *   Visitor in UniFi Access
    *   Zeitraum = Anreise bis Abreise
    *   PIN-Code
    *   Bemerkung mit Buchungsnummer
    *   Access Policy „Gaeste“
3.  PIN wird automatisch an Smoobu zurückgeschrieben
4.  PIN wird in deinen Nachrichten ersetzt

Alles automatisch, ohne Zutun.

***

## ✅ **Status-Ansicht**

Aufruf im Browser:

    http://DEINE-HA-IP:8099/

Zeigt:

*   API‑Endpoint
*   Secret
*   Eingestellte Policy
*   Bestätigung, dass Add‑on läuft

***

## 📦 **run.py – Logik des Add-ons**

Die Datei:

*   parst die Smoobu Daten
*   setzt PIN
*   erstellt Visitor
*   weist die Policy zu
*   sendet PIN zurück an Smoobu
*   gibt Erfolgsmeldung zurück

***

## 🧪 Test (manuell)

```powershell
Invoke-WebRequest -Uri "http://HA-IP:8099/?secret=DEIN_SECRET" `
  -Method POST `
  -Headers @{ "Content-Type" = "application/json" } `
  -Body '{"name":"Testgast","arrivalDate":"2026-05-01","departureDate":"2026-05-05","bookingId":123}'
```

Erwartete Ausgabe:

    OK – Visitor + PIN 123456 erstellt

In UniFi Access → Visitors sollte der Gast sichtbar sein.

***

## ✅ Logs anzeigen

Add-on → Protokolle

***

## 🎯 Troubleshooting

| Problem                      | Ursache                       | Lösung                                         |
| ---------------------------- | ----------------------------- | ---------------------------------------------- |
| 401 Unauthorized             | falscher Access Token         | Token aus Access → Settings → General erzeugen |
| Connection Refused           | falscher Host / falscher Port | Host = NUR IP; Port ist fest: 12445            |
| Visitor erscheint nicht      | Zeitraum = 0                  | run.py setzt nun korrekte Unixzeiten           |
| PIN kommt nicht in Smoobu an | falscher Placeholder          | `[doorPin]` verwenden                          |

