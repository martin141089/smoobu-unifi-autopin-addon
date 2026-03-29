# Smoobu UniFi AutoPIN – Home Assistant Add-on

Automatische Erzeugung eines zeitlich gültigen Türcodes für **UniFi Access** basierend auf neuen Buchungen in **Smoobu**.

✅ Automatische PIN-Erstellung  
✅ Automatische Übertragung als *Visitor* in UniFi Access  
✅ Automatische Rückgabe des Zugangscodes an Smoobu (via Custom Placeholder)  
✅ Vollständige Integration in Home Assistant Supervisor

---

## ⚙️ Funktionen

- Bei neuer Smoobu-Buchung über Webhook:
  - Generiert 6-stelligen PIN
  - Erzeugt Visitor in UniFi Access API
  - Schreibt PIN zurück in Smoobu als `[doorPin]`
- Läuft vollständig lokal (kein Cloud-Dienst nötig)
- Einfache Konfiguration im Add-on Panel

---

## 📂 Add-on Struktur
smoobu-unifi-autopin/
├── config.yaml
├── Dockerfile
├── run.py
└── icon.png (optional)
repository.json
README.md


---

## 🔧 Installation

### 1️⃣ Repository hinzufügen

In Home Assistant:

**Einstellungen → Add-ons → Add-on Store → Repositories**

Füge ein: https://github.com/martin141089/smoobu-unifi-autopin-addon

---

### 2️⃣ Add-on installieren

- Add-on öffnen: *Smoobu UniFi AutoPIN*
- "Installieren" drücken
- Nach Installation: Konfiguration ausfüllen

---

## 🛠 Konfiguration

In der Add-on Konfiguration folgende Werte setzen:

| Feld | Beschreibung |
|------|--------------|
| `smoobu_api_key` | API-Key aus Smoobu → Einstellungen → Entwickler |
| `unifi_host` | URL zur UniFi Access API, z. B. `https://192.168.1.5` |
| `unifi_token` | UniFi Access Developer Token |
| `webhook_secret` | Eigener geheimer Token für Sicherheit |

Beispiel:

```yaml
smoobu_api_key: "SMOOBU_API_KEY"
unifi_host: "https://192.168.1.5"
unifi_token: "ACCESS_API_TOKEN"
webhook_secret: "mein-geheimer-webhook-token"

https://DEINE-HOMEASSISTANT-IP:8099/?secret=DEIN_SECRET


