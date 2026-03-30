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

***

# ✅ Funktionen

*   Automatische Visitor‑Erstellung in UniFi Access
*   Automatische PIN‑Generierung für Gäste
*   Automatische Zuordnung einer Access Policy
*   Multi‑Wohnungs‑Support (1–4 Apartments)
*   Apartment‑Routing basierend auf Smoobu Property Name
*   Lokaler Tür‑Scan (Door‑Groups + Doors)
*   Unterstützung für Umlaute & Namens‑Trennung
*   Keine sensiblen Daten im Code

***

# ✅ Installation

1.  Repository hinzufügen
2.  Add‑on installieren
3.  Add‑on **nicht sofort starten**
4.  Konfiguration öffnen

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

***

# ✅ Door‑Scan verwenden

Das Add-on enthält eine lokale Seite zur Erkennung aller Türen & Türgruppen.

### Browser öffnen:

    http://HOMEASSISTANT-IP:8098

### Ausgabe Beispiel:

    === TÜRGRUPPE ===
    NAME: EG Wohnung
    ID:   5c496423-...

       - TÜR: Eingang EG → 6ff875d2-...

    === TÜRGRUPPE ===
    NAME: DG Wohnung
    ID:   e311ca94-...
       - TÜR: Eingang DG → d5573467-...

### Diese IDs trägst du im Add-on ein:

*   `home1_door_group_id:`
*   `home2_door_group_id:`
*   …

***

# ✅ Smoobu Webhook konfigurieren

Webhook URL:

    http://HOMEASSISTANT-IP:8099/?secret=DEIN_SECRET

Events aktivieren:

*   Buchung erstellt
*   Buchung geändert

Platzhalter in Nachrichten:

    Tür-PIN: [doorPin]

***

# ✅ Run Mode

Nach Abschluss aller Konfigurationen:

*   Add-on starten
*   Gäste erhalten automatisch PINs
*   Visitors erscheinen im UniFi Access
*   Türgruppen werden korrekt zugeordnet

***

# ✅ Dateistruktur des Add-ons

    /
    ├── config.yaml
    ├── run.py
    ├── scan.py
    ├── README.md
    └── Dockerfile

***
