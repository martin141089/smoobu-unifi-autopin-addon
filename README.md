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
