# BMEcat Download-Tool – Erweiterungskonzept

**Stand:** v1.1.0, Mai 2026  
**Für:** Technische Entscheider, Entwickler

Dieses Dokument beschreibt drei realistische Erweiterungsstufen: von kleinen Ergänzungen am bestehenden Tool bis zur vollständigen Modernisierung als Webservice.

---

## Stufe 1: Sofort umsetzbar (Wochen, kein Architekturwechsel)

### 1.1 Neue Lieferanten

Das Tool ist darauf ausgelegt neue Lieferanten in ca. 2 Stunden zu integrieren. Benötigt wird:

- FTP/SFTP-Zugangsdaten vom Lieferanten
- Katalogformat (BMEcat 1.2, CSV, oder proprietäres XML)
- Zielplattform (Brickfox oder andere)

Technisch: eine neue `tasks/lieferant.py` (~80 Zeilen), ein Eintrag in `config.py` und einer in der TASKS-Liste in `main.py`. Der Rest (FTP-Client, Upload-Verify, Retry, Circuit Breaker, Diff-Report, Validierung) ist bereits fertig und wird automatisch genutzt.

Kandidaten: Lyreco, Staples, Dahle, DURABLE (falls diese Lieferanten FTP-Kataloge anbieten).

### 1.2 Neue Zielplattformen

Aktuell: Brickfox, Mercateo, Allago, OfficeXL. Weitere Plattformen folgen demselben Muster:

- FTP/SFTP-Upload: fertige Infrastruktur in `lib/ftp_client.py`
- CSV-Export: `tasks/others.py` als Vorlage
- API-Anbindung: neues Modul in `lib/`

### 1.3 Vollständige Soennecken-Integration

Der Soennecken-Task macht aktuell nur Download. Merge-Logik und Brickfox-Upload fehlen. Da keine Daten geliefert werden, ist dies niedrige Priorität — aber sobald der Lieferant wieder aktiv ist, sind es ca. 4 Stunden Arbeit.

### 1.4 Bestandsdaten automatisch aktualisieren

`Bestand_und_Preise.xlsx` wird manuell gepflegt. Ein Export-Script oder API-Anbindung an das ERP-System (z.B. Microsoft Dynamics, SAP) könnte diese Datei täglich automatisch erzeugen — statt sie manuell zu pflegen.

---

## Stufe 2: Mittelfristig (Monate, moderate Architekturänderung)

### 2.1 Web-Dashboard

Aktuell ist das Log nur in der GUI sichtbar. Ein einfaches lokales Webinterface würde ermöglichen:

- Lauf-Status von jedem Rechner im Netzwerk einsehen
- Trend: Laufzeiten und Artikelzahlen der letzten 30 Tage
- Sanity-Check-Ergebnisse visualisiert
- Diff-Reports durchsuchen

**Technisch:** Flask (Python) oder ein statischer HTML-Report der nach jedem Lauf in `logs/dashboard.html` geschrieben wird. Für ein Netzwerk-Dashboard: kleiner Flask-Server als Windows-Dienst.

**Aufwand:** 2–3 Wochen für ein brauchbares Dashboard.

### 2.2 Parallelisierung der Download-Phase

Die Bibliothek `lib/parallel.py` ist bereits implementiert aber nicht verdrahtet. Büroring, Softcarrier und Nordwest laden von verschiedenen Servern — die Downloads könnten parallel laufen:

```
Vorher (sequenziell, ~4 Min Download):
  Büroring  Download ──────────────────┐
                                       ├── 4 Min
  Softcarrier Download ────────────────┘
  Nordwest   Download ────────────────────── +90s

Nachher (parallel, ~90s Download):
  Büroring ──┐
  Softcarrier──┼── parallel ── ~90s (längster Download)
  Nordwest ──┘
```

**Aufwand:** 1 Woche (Download-Phasen aus Tasks extrahieren, Worker-Pattern aufbauen, Tests).

### 2.3 Daten-Anreicherung durch Cross-Supplier-Filling

Der Sanity-Check findet bereits Lücken (z.B. "EAN 4000123: Hersteller fehlt bei Softcarrier, vorhanden bei Büroring"). Der nächste Schritt wäre, diese Lücken automatisch zu füllen:

Nach dem Merge aller Kataloge: pro Artikel mit EAN prüfen ob ein anderer Lieferant bessere Daten hat (längere Beschreibung, Hersteller, Bild-Referenz) und diese Daten einfügen.

Das würde die Katalogqualität auf Plattformen deutlich verbessern ohne manuelle Arbeit.

**Aufwand:** 2–3 Wochen (Datenfusion-Logik, Konfliktstrategie definieren, Tests).

### 2.4 ERP-Integration

Statt `Bestand_und_Preise.xlsx` manuell zu pflegen: direkter Datenbankzugriff auf das Warenwirtschaftssystem.

- **Microsoft Dynamics:** ODBC oder REST-API
- **SAP:** BAPI oder RFC
- **Andere:** ODBC-Verbindung zu beliebiger Datenbank

Technisch in Python gut umsetzbar (`pyodbc`, `sqlalchemy`). Erfordert IT-Zugang zum WaWi.

**Aufwand:** 1–4 Wochen je nach WaWi-System und IT-Zugängen.

---

## Stufe 3: Langfristig (Monate bis Jahr, Architekturwechsel)

### 3.1 Vom Desktop-Tool zum Microservice

Das aktuelle Tool ist ein Windows-Desktop-Programm. Für mehrere Mandanten, Remote-Betrieb oder Cloud-Deployment müsste es als Service laufen:

```
Aktuell:              Ziel (Microservice):
┌─────────────┐       ┌──────────────────┐    ┌──────────────┐
│ Windows GUI │  →→→  │  Python Backend  │ ←─ │  Web-UI      │
│ + Scheduler │       │  (FastAPI/Flask)  │    │  (Browser)   │
│ + Worker    │       │  + Celery Tasks  │    │              │
└─────────────┘       └──────────────────┘    └──────────────┘
                              │
                       ┌──────┴──────┐
                       │  Redis/DB   │  (Task-Queue, State)
                       └─────────────┘
```

**Vorteile:**
- Mehrere Mandanten auf einem Server
- Kein Windows-Desktop nötig, läuft auf Linux
- Webinterface für alle Benutzer
- Horizontal skalierbar

**Aufwand:** 3–6 Monate für eine vollständige Migration. Sinnvoll wenn >3 Mandanten oder Cloud-Betrieb geplant ist.

### 3.2 Cloud-Native (Azure/AWS)

Für maximale Skalierbarkeit und minimale Wartung:

- **Azure Logic Apps** oder **AWS Step Functions** für die Workflow-Orchestrierung
- **Azure Blob Storage** / **S3** für XML/Bilder-Zwischenspeicherung
- **Azure Functions** / **Lambda** für einzelne Verarbeitungsschritte
- **Azure Data Factory** für Datenpipelines

Vorteil: kein eigener Server, automatische Skalierung, integriertes Monitoring.  
Nachteil: Vendor Lock-in, laufende Kosten, Datenschutz bei EU-Daten prüfen.

**Aufwand:** 2–4 Monate für eine initiale Cloud-Migration.

### 3.3 Marketplace-Integration

Direktanbindung an Marktplatz-APIs statt FTP-Upload:

- **Amazon Seller Central API** (SP-API)
- **eBay Inventory API**
- **Kaufland Marketplace API**
- **OTTO Partner API**

Statt eine Datei auf Brickfox zu legen würde das Tool Artikel direkt über die jeweilige API anlegen/aktualisieren. Ermöglicht Echtzeit-Aktualisierungen statt täglichen Batches.

---

## Entscheidungsmatrix

| Erweiterung | Aufwand | Nutzen | Priorität |
|---|---|---|---|
| Neuer Lieferant | 2h–1T | Hoch (mehr Daten) | Bedarfsgesteuert |
| Neue Zielplattform | 1–3T | Hoch (mehr Reichweite) | Bedarfsgesteuert |
| Web-Dashboard | 2–3W | Mittel (Transparenz) | Niedrig |
| Parallele Downloads | 1W | Mittel (~3 Min schneller) | Niedrig |
| Cross-Supplier-Filling | 2–3W | Hoch (Qualität) | Mittel |
| ERP-Integration | 1–4W | Sehr hoch (kein Excel) | Hoch |
| Microservice-Architektur | 3–6M | Hoch (bei >1 Mandant) | Nur wenn nötig |
| Cloud-Native | 2–4M | Niedrig (bei aktuellem Umfang) | Nicht empfohlen |

### Empfehlung

Kurzfristig hat die **ERP-Integration** den höchsten Hebel: sie eliminiert die manuelle Pflege von `Bestand_und_Preise.xlsx` und macht den Lauf vollständig wartungsfrei.

Mittelfristig lohnt sich **Cross-Supplier-Filling** für bessere Katalogqualität auf den Plattformen — die Datenbasis ist durch den Sanity-Check bereits vorbereitet.

Alles andere (Dashboard, Cloud, Microservice) lohnt sich erst wenn das Tool auf mehr als einen Mandanten oder mehr als ein System ausgerollt werden soll.

---

*v1.1.0 · Mai 2026*
