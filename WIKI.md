# BMEcat Download-Tool – Wiki & Tutorial

> **Version 1.1.0** · Mai 2026 · ~5.800 Zeilen Python · 5 Lieferanten · 8 Plattform-Uploads

---

## Inhaltsverzeichnis

1. [Was macht das Tool?](#1-was-macht-das-tool)
2. [Schnellstart](#2-schnellstart)
3. [Täglicher Betrieb](#3-täglicher-betrieb)
4. [Die Lieferanten-Pipelines](#4-die-lieferanten-pipelines)
5. [Projektstruktur](#5-projektstruktur)
6. [Einen neuen Lieferanten hinzufügen (Tutorial)](#6-einen-neuen-lieferanten-hinzufügen)
7. [Konfiguration & Anpassung](#7-konfiguration--anpassung)
8. [Neue Module (v1.1.0)](#8-neue-module-v110)
9. [Tests](#9-tests)
10. [Troubleshooting](#10-troubleshooting)
11. [Erweiterungspotenzial](#11-erweiterungspotenzial)

---

## 1. Was macht das Tool?

Das BMEcat Download-Tool automatisiert den täglichen Katalogdaten-Import für ABE:

```
Lieferanten-FTP/SFTP
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  Download → Entpacken → Merge/Anreicherung → Upload         │
│                                                              │
│  Büroring  ──→ ECLASS + UDX + Keywords ──→ Brickfox BMEcat  │
│                                         ──→ Brickfox CSV ERP│
│                                         ──→ Brickfox CSV Exc│
│                                         ──→ Mercateo         │
│  Softcarrier ──→ TAB-Features + GPSR   ──→ Brickfox BMEcat  │
│                                         ──→ Allago Bilder    │
│                                         ──→ OfficeXL Bilder  │
│  Nordwest ──→ UDX→Feature-Konvertierung ──→ Brickfox BMEcat  │
│  Systeam  ──→ nur Download                                   │
│  Soennecken ──→ Download (vorbereitet)                       │
└──────────────────────────────────────────────────────────────┘
```

Pro Lauf werden ca. 1,5 GB Daten verarbeitet: ~160.000 Artikel, ~60.000 Bilder, XML-Dateien bis 470 MB.

### Was ist neu in v1.2.0?

**Pipeline-Qualität**
- **FNAME-Transforms** (`lib/fname_transforms.py`): `(0173-...)` aus FNAMEs entfernen, FNAME/FVALUE umbenennen via CSV, `Marke`→`MANUFACTURER_NAME` Logik
- **GTIN-Prüfziffer** (`lib/utils.py`): GS1-Validierung aller EANs, auto-fixbare Fehler werden gemeldet
- **Dead Letter Queue** (`lib/dead_letter.py`): Problemartikel in Quarantäne-XML statt lautlos überspringen
- **Cross-Supplier Auto-Fill**: Phonetischer Hersteller-Abgleich (Kölner Phonetik)
- **EAN als Keyword** + **Keyword-Deduplication** (Regeln 3+4 in article_enrichment)
- **AID-Suffix entfernen** aus DESCRIPTION_SHORT (`(CASFX87DEX)` → weg)
- **XML-Sanitize**: Nackte Ampersands (`&`) → `&amp;` repariert (z.B. "Clic & Go")

**Neue Datenquellen**
- **ATP-Merge** (`lib/atp.py`): OBS-Lagerbestände aus `102_atp*.zip` in Availability-CSV
- **Mindest-Abgleich** (`lib/mindest_abgleich.py`): `Mindest-Abgleich_*.xlsx` → `32WQS_conditionsfile.csv`
- **Kategorie-Check** (`lib/category_check.py`): neue Lieferantenkategorien vs. `custom_categories.csv` melden

**Qualitätssicherung**
- **Sanity-Check** (`lib/sanity_check.py`): EAN-Abdeckung, Hersteller, Bilder, Duplikate pro Katalog
- **Cross-Supplier-Dashboard** (`logs/cross_filling_dashboard.html`): wer kann wem welche Felder liefern
- **Lauf-Trend-Dashboard** (`logs/trend_dashboard.html`): Laufzeiten und Fehler der letzten 30 Läufe
- **Integrationstests** (`tests/test_integration.py`): Plausibilitätsprüfung nach echtem Merge

**Optionale KI/Barrierefreiheit**
- **KI-Anreicherung** (`lib/ai_enrichment.py`): Claude Haiku verbessert schwache Artikeldaten (Opt-in)
- **BFSG-Cleanup** (`lib/bfsg_cleanup.py`): Barrierefreiheit – MIME_ALT, HTML bereinigen, etc. (Opt-in)

**Robustheit**
- **Crash-Logger**: Ungefangene Ausnahmen in `logs/crash_*.txt`
- **Config-Migration** (`lib/config_migration.py`): Neue Config-Keys werden auto-ergänzt
- **`@timed`-Decorator**: Laufzeitmessung pro Schritt im LaufReport
- **Allgemeiner Lauf-Cache**: CSV/Kategorie-Dateien pro Lauf nur einmal lesen
- **Parallele Downloads** (`tasks/parallel_download.py`): Büroring + Softcarrier + Nordwest gleichzeitig
- **`supplier_config`** in `config.py`: Konfigurierbare ATP-Pfade, BFSG, KI-Einstellungen

**In-App-Tutorial**: `?`-Button öffnet 15-Schritt-Tutorial + Tooltips auf allen UI-Elementen

### Was ist neu in v1.1.0?

- **Zentralisierte Utilities** (`lib/utils.py`): `run_7zip` und `glob_ci` – waren vorher 5× dupliziert
- **E-Mail-Benachrichtigung** (`lib/notifications.py`): Automatische Zusammenfassung bei Fehlern
- **XML-Validierung** (`lib/xml_validator.py`): Prüfung vor dem Upload (Wohlgeformtheit, Artikelanzahl)
- **Diff-Reports** (`lib/diff_report.py`): Vergleich mit dem letzten Lauf (neu, gelöscht, Preisänderungen)
- **Parallele Downloads** (`lib/parallel.py`): ThreadPoolExecutor für gleichzeitige Downloads
- **Soennecken-Task** registriert und aktivierbar
- **Versionsnummer** in GUI-Titelleiste
- **40 Unit-Tests** in `tests/`
- **Bugfixes**: Softcarrier-Doppelglob, Büroring-Excel-Crash, Doppel-Upload (Softcarrier + Nordwest)

---

## 2. Schnellstart

### Voraussetzungen

- Windows 10/11 mit Python ≥ 3.9
- 7-Zip unter `C:\Program Files\7-Zip\7z.exe`
- Netzwerkzugang zu allen FTP/SFTP-Servern

### Installation

```bat
:: 1. Ordner anlegen
mkdir C:\bmecat_download
:: 2. Tool-Dateien nach C:\bmecat_download\ entpacken
:: 3. Ersteinrichtung
install.bat
```

`install.bat` sucht Python, installiert `paramiko` und `openpyxl` via pip.

### Erster Start

```bat
start.bat
```

Die GUI öffnet sich:

```
┌─────────────────────────────────────────────────────────────┐
│ BMEcat Download-Tool v1.1.0  [Test][Config][Sched] Status   │
├──────────────┬──────────────────────────────────────────────┤
│ ☑ Aufräumen  │                                              │
│ ☑ Büroring   │  [06:01:23]  Büroring: Merge abgeschlossen. │
│ ☐ Büro-Merge │  [06:01:24]  Keywords: 18.432 injiziert.    │
│ ☑ Softcarrier│  [06:01:25]  ✓ Validierung bueroring.xml:   │
│ ☐ SC-Merge   │      21.847 Artikel, 312.4 MB               │
│ ☑ Nordwest   │  [06:01:26]  Diff: +47 neu, -12 gelöscht,   │
│ ☑ Systeam    │      ~231 Preisänderungen                    │
│ ☐ Soennecken │                                              │
│              ├──────────────────────────────────────────────┤
│ [Alle][Keine]│ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░  72%  bueroring.xml   │
├──────────────┴──────────────────────────────────────────────┤
│ [▶ Starten] [■ Abbrechen]              [Log öffnen][Speich]│
└─────────────────────────────────────────────────────────────┘
```

### Wichtige Dateien die vorliegen müssen

| Datei | Pfad | Herkunft |
|---|---|---|
| `Bestand_und_Preise.xlsx` | `C:\bmecat_download\` | Manuell gepflegt – Master-Excel mit Reitern "Master", "Bestand" und Preis-Sheets |
| `keywords_exploded.csv` | `C:\bmecat_download\` | Keyword-Tabelle für Büroring-Merge, ~87 MB |

---

## 3. Täglicher Betrieb

### Standard-Lauf (manuell)

1. Tool starten via `start.bat`
2. Standard-Tasks sind vorausgewählt: Aufräumen, Büroring, Softcarrier, Nordwest, Systeam
3. **Starten** klicken → Laufzeit typisch 5–10 Minuten
4. Ergebnis: grüne ✅ oder rote ❌ pro Task, Fehlerdetails im Log

### Automatischer Lauf (Scheduler)

Über die GUI einrichtbar: **Scheduler**-Button. Erzeugt einen Windows-Task via `schtasks`, der `main.py --auto` täglich zur gewünschten Uhrzeit startet.

### Was passiert in welcher Reihenfolge?

```
1. Aufräumen       Löscht alte *.xml, *.csv, *.zip aus in_BME/
2. Büroring        Download → Entpacken → Merge+Keywords → Bestand+Preis → Upload
3. Softcarrier     Download → Entpacken → Merge (Features+GPSR) → Upload → Bilder
4. Nordwest        Download → Entpacken → UDX-Konvertierung → Upload
5. Systeam         Download → Entpacken (nur Daten ablegen)
```

### Was passiert vor jedem Upload? (NEU in v1.1.0)

Vor dem Upload auf Brickfox werden automatisch zwei Prüfungen durchgeführt:

**1. XML-Validierung** – prüft:
- Datei existiert und ist nicht leer
- XML-Wohlgeformtheit (BMECAT-Header und -Footer vorhanden)
- Artikelanzahl plausibel (konfigurierbare Schwellwerte)
- Stichprobe: haben Artikel eine SUPPLIER_AID?

**2. Diff-Report** – vergleicht mit dem letzten Lauf:
- Neue Artikel (SUPPLIER_AID erstmals vorhanden)
- Gelöschte Artikel (SUPPLIER_AID fehlt)
- Preisänderungen (net_list PRICE_AMOUNT geändert)

Beides ist "soft validation" – Warnungen im Log, kein Upload-Abbruch.

### Lauf-Reports

Nach jedem Lauf wird `logs/lauf_YYYYMMDD_HHMMSS.json` geschrieben:

```json
{
  "start": "2026-05-23T06:00:00",
  "dauer_s": 312.5,
  "tasks_gesamt": 5,
  "tasks_ok": 4,
  "tasks_fehler": 1,
  "fehler": ["Systeam"],
  "deduplizierung": {"removed": 847, "files": 5, "articles": 312},
  "tasks": [
    {"name": "Büroring – Komplett", "status": "ok", "duration_s": 185.2},
    ...
  ]
}
```

### E-Mail-Benachrichtigung (NEU in v1.1.0)

Wenn in `config.py` aktiviert, wird nach dem Lauf automatisch eine Zusammenfassung per E-Mail gesendet. Standardmäßig nur bei Fehlern (konfigurierbar auch bei Erfolg).

---

## 4. Die Lieferanten-Pipelines

### 4.1 Büroring (`tasks/bueroring.py`)

Komplexester Lieferant – drei Datenströme werden zusammengeführt:

```
bueroring.xml (ABE/UDX)  ──┐
                            ├──→ bueroring_merged.xml ──→ Validierung
bueroring_basis.xml ────────┘         ↑                ──→ Diff-Report
                              Keywords injiziert       ──→ Brickfox /incoming
                              ECLASS-Features ergänzt
                              FNAME-Deduplizierung

br-bestand.csv ──→ availability-data-catalog-32WQS.csv ──→ Mercateo
               ──→ Bestand_und_Preise.xlsx patchen ──→ Products_*.csv → Brickfox ERP
                                                    ──→ csv_autoimport_*.csv → Brickfox Exchange
```

**Merge-Logik** (`lib/bmecat_merge.py`, 775 Zeilen):
- Phase 0: UDX- und ECLASS-Blöcke aus ABE-Quelle extrahieren
- Phase 1: Basisdatei kopieren
- Phase 2: Für jeden Artikel: ECLASS-Features einfügen, UDX-Blöcke ergänzen, leere Blöcke füllen
- Dann: Keywords aus CSV injizieren, FNAMEs deduplizieren

**Bestand+Preis** (`tasks/bueroring_bestand.py`, 262 Zeilen):
- Liest `Bestand_und_Preise.xlsx` (Master-Excel mit VLOOKUP-Logik)
- Berechnet VLOOKUPs in Python nach (Conrad, Kaufland DE/AT/FR, Netto)
- Patcht v_stock aus Bestands-CSV
- Setzt Marketplace-Flags (1 wenn Preis ≠ 0)
- Exportiert zwei CSVs: ERP (nur Preise+Bestand) und Exchange (Stammdaten ohne Preise)

**Bugfix v1.1.0**: Wenn `Bestand_und_Preise.xlsx` fehlt, wird der XML-Upload trotzdem durchgeführt (vorher: gesamter Büroring-Task abgebrochen).

### 4.2 Softcarrier (`tasks/softcarrier.py`)

```
soft-carrier.xml ──→ soft-carrier_merge.xml ──→ Validierung
HERSTINFO.CSV ─────┘     ↑                  ──→ Diff-Report
DATA.CSV ──────────────────┘  TAB-Features   ──→ Brickfox /incoming (als soft-carrier.xml)
                              + GPSR-Daten
PREVIEW.ZIP ──→ 61.000+ JPGs ──→ SOC-Prefix ──→ Allago + OfficeXL
```

**Merge** (`tasks/softcarrier_merge.py`, 355 Zeilen):
- Lädt HERSTINFO.CSV (Marken-Mapping) und DATA.CSV (TAB-Features pro Artikel)
- Für jeden Artikel: Feature-Block aus CSV-Spalten bauen, GPSR-Felder ergänzen
- Markenname via HERSTINFO nachschlagen

**Bugfix v1.1.0**: `glob_ci()` verhindert den Windows-Doppelglob-Crash bei JPG-Umbenennung.

### 4.3 Nordwest (`tasks/nordwest.py`)

```
arbeitsschutz.zip ──→ arbeitsschutz.xml ──┐
werkstatt.zip     ──→ werkstatt.xml     ──┼──→ UDX→Feature ──→ Validierung
werkzeugtechnik.zip ──→ werkzeugtechnik.xml┘   + Dedup    ──→ Diff-Report
                                                            ──→ Brickfox /incoming
kip.zip ──→ NDW{datum}.csv ──→ Netzlaufwerk (OBS)
```

**Bugfix v1.1.0**: Doppel-Upload entfernt (toter Code in `others.py`). Spart ~2 Min + 640 MB pro Lauf.

### 4.4 Systeam (`tasks/systeam.py`)

Einfachster Task – nur Download + Entpacken, kein Upload. Server oft instabil (Timeout-Fehler im Log sind normal).

### 4.5 Soennecken (`tasks/others.py:run_soennecken`)

NEU in v1.1.0 als GUI-Task registriert (Standard: aus). Lädt BMEcat-XML + Bilder-Archiv vom Soennecken-FTP. Merge und Brickfox-Upload sind noch nicht implementiert.

---

## 5. Projektstruktur

```
bmecat_tool/
├── main.py                   # GUI (tkinter), Task-Registry, Thread-Steuerung (730 Z.)
├── config.py                 # Pfade, FTP-Credentials, Merge-Config, Notification, Thresholds
├── requirements.txt          # paramiko, openpyxl
├── install.bat / start.bat   # Einrichtung / Start
├── ARCHITECTURE.md           # Technische Konventionen (Framework-Referenz)
├── WIKI.md                   # ← dieses Dokument
│
├── lib/                      # Wiederverwendbare Bibliotheken (kein GUI, kein State)
│   ├── utils.py              #   run_7zip, glob_ci, VERSION (NEU)
│   ├── ftp_client.py         #   FTP/SFTP-Wrapper (507 Z.)
│   ├── bmecat_merge.py       #   Kern-Merge-Logik + UDX-Konvertierung (775 Z.)
│   ├── bestandsdaten.py      #   Availability-CSV-Erzeugung (1155 Z.)
│   ├── article_enrichment.py #   Regelbasierte XML-Nachbearbeitung (235 Z.)
│   ├── config_editor.py      #   GUI-Dialog für Konfiguration (486 Z.)
│   ├── connection_test.py    #   Verbindungstest ohne GUI
│   ├── lauf_report.py        #   JSON-Reports pro Lauf
│   ├── notifications.py      #   E-Mail-Benachrichtigung (NEU)
│   ├── xml_validator.py      #   Pre-Upload-Validierung (NEU)
│   ├── diff_report.py        #   Artikel-Diff zwischen Läufen (NEU)
│   └── parallel.py           #   ThreadPoolExecutor-Wrapper (NEU)
│
├── tasks/                    # Ein Modul pro Lieferant/Aufgabe
│   ├── cleanup.py            #   Aufräumen (in_BME, in2)
│   ├── bueroring.py          #   Büroring Komplett-Pipeline
│   ├── bueroring_bestand.py  #   Excel-Patching + CSV-Export
│   ├── bmecat_merge.py       #   Manueller Merge-Trigger
│   ├── softcarrier.py        #   Softcarrier Komplett-Pipeline
│   ├── softcarrier_merge.py  #   Feature+GPSR-Merge
│   ├── nordwest.py           #   Nordwest Pipeline
│   ├── systeam.py            #   Systeam Download
│   ├── others.py             #   Shared: Brickfox-Upload, Bilder, Mercateo, Bestandsdaten
│   └── scheduler.py          #   Windows Task Scheduler Integration
│
├── tests/                    # Unit-Tests (NEU)
│   ├── test_utils.py         #   9 Tests: glob_ci, VERSION
│   ├── test_xml_validator.py #   10 Tests: Validierung
│   ├── test_diff_report.py   #   11 Tests: Snapshot + Diff
│   ├── test_notifications.py #   4 Tests: Subject + Body
│   └── test_parallel.py      #   6 Tests: Parallelität + Fehlerbehandlung
│
├── Bestand_und_Preise.xlsx   # Master-Excel (manuell gepflegt)
└── keywords_exploded.csv     # Keyword-Tabelle (~87 MB, nicht im ZIP)
```

### Datenfluss-Verzeichnisse (auf dem Arbeitsrechner)

```
C:\bmecat_download\
├── in_BME\              # Haupt-Arbeitsverzeichnis: XMLs, CSVs, ZIPs
│   └── soc_bilder\      # Softcarrier Vorschaubilder (temporär)
├── in\                  # Soennecken-Bilder + allgemeine Bilder
├── in2\                 # Büroring-Bilder (temporär)
├── in_vertrieb\         # Vertriebsbilder + category/
├── logs\                # Log_YYYYMMDD.txt + lauf_*.json
│   └── diff_backups\    # Diff-Snapshots + Reports (NEU)
├── sql\                 # SQL-Snippets (HeidiSQL)
└── unzip\               # Reserviert
```

---

## 6. Einen neuen Lieferanten hinzufügen

Dieses Tutorial zeigt Schritt für Schritt, wie ein sechster Lieferant eingebaut wird.

### Schritt 1: FTP-Zugang testen

Bevor Code geschrieben wird: über die GUI den Verbindungstest nutzen.

1. Zugangsdaten in `config.py` eintragen (siehe Schritt 3)
2. Tool starten → **Verbindungstest** → Server auswählen → Testen
3. Oder mit einem FTP-Client (FileZilla, WinSCP) manuell prüfen:
   - Welche Dateien liegen wo?
   - In welchem Format? (ZIP/XML/CSV)
   - Wie groß?
   - Wie heißen sie?

### Schritt 2: Task-Datei anlegen

```python
# tasks/neulieferant.py
"""
Pipeline für den neuen Lieferanten:
  1. ZIP vom SFTP laden
  2. Entpacken
  3. Optional: Merge/Anreicherung
  4. Upload nach Brickfox
"""
import os
import logging
from lib.ftp_client import make_client
from lib.utils import run_7zip
from config import CONNECTIONS, DIRS, TOOLS

log = logging.getLogger(__name__)


def run(progress_cb=None, file_progress_cb=None):
    """Haupt-Entry-Point – wird von main.py aufgerufen."""
    cfg    = CONNECTIONS["neulieferant"]
    in_bme = DIRS["in_bme"]
    seven_z = TOOLS["7zip"]
    p  = progress_cb      or (lambda m, **kw: None)
    fp = file_progress_cb or None

    # ── 1. Download ──────────────────────────────────────────
    p("Neulieferant: Verbinde mit FTP ...")
    client = make_client(cfg)
    client.connect()
    try:
        # Wildcards möglich: "katalog/*.zip"
        client.download("katalog/produkte.zip", in_bme,
                        progress_cb=p, file_progress_cb=fp)
    finally:
        client.disconnect()

    # ── 2. Entpacken ─────────────────────────────────────────
    zip_path = os.path.join(in_bme, "produkte.zip")
    if os.path.exists(zip_path):
        p("Neulieferant: Entpacke ...")
        run_7zip(seven_z, zip_path, in_bme, "*.xml", p)
        # ZIP nach dem Entpacken löschen
        os.remove(zip_path)
        # Interne Datei umbenennen
        src = os.path.join(in_bme, "bmecat_export.xml")
        dst = os.path.join(in_bme, "neulieferant.xml")
        if os.path.exists(src):
            os.rename(src, dst)
    else:
        p("Neulieferant: ZIP nicht gefunden!", tag="err")
        return

    # ── 3. FNAME-Deduplizierung (optional) ───────────────────
    from tasks.others import dedup_xmls
    dedup_xmls([os.path.join(in_bme, "neulieferant.xml")],
               progress_cb=p, file_progress_cb=fp)

    p("Neulieferant Download+Verarbeitung abgeschlossen.", tag="ok")

    # ── 4. Upload nach Brickfox ──────────────────────────────
    from tasks.others import upload_bmecat_xmls
    upload_bmecat_xmls(
        [os.path.join(in_bme, "neulieferant.xml")],
        progress_cb=p, file_progress_cb=fp
    )
```

### Schritt 3: Zugangsdaten in config.py

```python
CONNECTIONS = {
    # ... bestehende Einträge ...
    "neulieferant": {
        "host":        "sftp.neulieferant.de",
        "user":        "abe_import",
        "password":    "geheim123",
        "protocol":    "sftp",       # oder "ftp"
        "port":        22,           # 21 für FTP, 22 für SFTP
        # Optional: remote_path für Upload-Ziel
    },
}
```

### Schritt 4: Task in main.py registrieren

In der `TASKS`-Liste, zwischen Systeam und Extras:

```python
    # ── Neulieferant ──────────────────────────────────────────────────────────
    {
        "id":      "neulieferant",
        "name":    "Neulieferant – Komplett",
        "desc":    "Download + Entpacken + Brickfox-Upload",
        "fn":      "tasks.neulieferant:run",
        "default": True,           # True = bei Standard-Lauf aktiv
        "group":   "Neulieferant", # Gruppenname in der Sidebar
    },
```

### Schritt 5: Schwellwert für Validierung eintragen

In `config.py`, damit die XML-Validierung warnt wenn zu wenige Artikel geliefert werden:

```python
ARTICLE_THRESHOLDS = {
    # ... bestehende ...
    "neulieferant.xml":  5000,   # Warnung wenn unter 5.000 Artikel
}
```

### Schritt 6: Testen

1. Tool starten
2. Alle Tasks abwählen, nur "Neulieferant – Komplett" aktivieren
3. Starten und Log beobachten
4. Erwartete Log-Ausgabe:

```
[09:15:01]  Start: Neulieferant – Komplett ...
[09:15:02]  Neulieferant: Verbinde mit FTP ...
[09:15:05]  Neulieferant: Entpacke ...
[09:15:06]  FNAME-Deduplizierung ...
[09:15:07]    Validierung neulieferant.xml: 6.234 Artikel, 45.2 MB
[09:15:07]  Diff neulieferant.xml: Erster Lauf – Baseline mit 6.234 Artikeln
[09:15:08]  Brickfox XML-Upload → /incoming (1 Dateien) ...
[09:15:42]  Brickfox XML-Upload abgeschlossen.
[09:15:42]  OK: Neulieferant – Komplett abgeschlossen.
```

### Schritt 7: Manuellen Fallback-Task anlegen (optional)

Für den Fall dass der Download funktioniert hat aber der Merge fehlschlägt:

```python
# Am Ende von tasks/neulieferant.py:
def run_upload_only(progress_cb=None, file_progress_cb=None):
    """Nur Upload, ohne Download (Fallback)."""
    p  = progress_cb or (lambda m, **kw: None)
    fp = file_progress_cb or None
    in_bme = DIRS["in_bme"]
    from tasks.others import upload_bmecat_xmls
    upload_bmecat_xmls(
        [os.path.join(in_bme, "neulieferant.xml")],
        progress_cb=p, file_progress_cb=fp
    )
```

Und in `main.py`:

```python
    {
        "id":      "neulieferant_upload",
        "name":    "Neulieferant – Upload (manuell)",
        "desc":    "Nur XML-Upload ohne Download (Fallback)",
        "fn":      "tasks.neulieferant:run_upload_only",
        "default": False,
        "group":   "Neulieferant",
    },
```

### Konventionen für neue Tasks

| Thema | Regel |
|---|---|
| Callbacks | `progress_cb(msg, tag="ok"/"warn"/"err")` für Log-Ausgaben |
| Fortschritt | `file_progress_cb` an FTP-Aufrufe durchreichen → Fortschrittsbalken |
| Fehler | Nicht still verschlucken, aber auch nicht den ganzen Lauf crashen |
| Temporäre Dateien | In `in_BME/` ablegen (werden beim nächsten Aufräumen gelöscht) |
| FTP-Verbindungen | Immer in `try/finally: client.disconnect()` |
| 7-Zip | `from lib.utils import run_7zip` – nie lokale Kopie |
| Glob | `from lib.utils import glob_ci` – nie `glob.glob` direkt (Windows-Bug) |

---

## 7. Konfiguration & Anpassung

### Pfade ändern

Alle Pfade stehen in `config.py`:

```python
BASE_DIR = r"C:\bmecat_download"        # Ändern für anderen Installationsort
DIRS = {
    "in_bme": os.path.join(BASE_DIR, "in_BME"),
    # ...
}
TOOLS = {
    "7zip": r"C:\Program Files\7-Zip\7z.exe",   # Anpassen falls woanders
}
```

### Laufzeit-Overrides (ohne config.py zu editieren)

Über die GUI: **Konfiguration** → Felder ändern → Speichern. Erzeugt `config_user.json`, die beim Start automatisch geladen wird und `config.py`-Werte überschreibt.

### Merge-Konfiguration

```python
MERGE = {
    "udx_src":   "bueroring.xml",          # ABE-Datei (mit UDX + ECLASS)
    "basis_src": "bueroring_basis.xml",    # Hauptkatalog
    "out_file":  "bueroring_merged.xml",   # Ausgabe
    "keywords":  "keywords_exploded.csv",  # Keywords-Tabelle
}
```

### Upload-Umbenennung

In `tasks/others.py:upload_bmecat_xmls` steuert `rename_map`, welche Dateien unter welchem Namen auf Brickfox landen:

```python
rename_map = {
    "bueroring_merged.xml":   "bueroring.xml",
    "soft-carrier_merge.xml": "soft-carrier.xml",
}
```

### Themes

Zwei Themes: **Classic** (dunkles Lila) und **ABE** (helles Orange). Wechsel via Button in der Kopfzeile.

### E-Mail-Benachrichtigung konfigurieren

In `config.py`:

```python
NOTIFICATION = {
    "enabled":    True,                         # ← einschalten
    "smtp_host":  "smtp.office365.com",
    "smtp_port":  587,
    "smtp_user":  "bmecat@abe-brands.de",
    "smtp_pass":  "passwort",
    "smtp_tls":   True,
    "from":       "bmecat@abe-brands.de",
    "to":         ["admin@abe-brands.de", "lager@abe-brands.de"],
    "on_success": False,                        # True = auch bei Erfolg senden
}
```

### Artikelanzahl-Schwellwerte anpassen

Die XML-Validierung warnt wenn die Artikelzahl unter den Schwellwert fällt. In `config.py`:

```python
ARTICLE_THRESHOLDS = {
    "bueroring_merged.xml":    20000,   # Normalerweise ~21.800
    "soft-carrier_merge.xml":  60000,   # Normalerweise ~65.000
    "arbeitsschutz.xml":        5000,
    "werkstatt.xml":           10000,
    "werkzeugtechnik.xml":     40000,
}
```

---

## 8. Neue Module (v1.1.0)

### 8.1 lib/utils.py – Zentralisierte Utilities

Enthält zwei Funktionen die vorher in 5 Task-Dateien identisch dupliziert waren:

**`run_7zip(seven_z, zip_path, out_dir, filter_=None, p=None, timeout=600)`**

Entpackt ein Archiv mit 7-Zip. Gibt `True` bei Erfolg zurück, loggt Fehler.

```python
from lib.utils import run_7zip
run_7zip(TOOLS["7zip"], "archiv.zip", in_bme, "*.xml", p)
```

**`glob_ci(directory, extension)`**

Case-insensitiver Glob mit automatischer Deduplizierung. Auf Windows liefern `*.JPG` und `*.jpg` identische Ergebnisse – ohne Deduplizierung crashed `os.replace()`.

```python
from lib.utils import glob_ci
jpgs = glob_ci(img_dir, "jpg")  # Gibt sortierte, deduplizierte Liste zurück
```

**`VERSION`**

Zentrale Versionsnummer, angezeigt in der GUI-Titelleiste.

### 8.2 lib/notifications.py – E-Mail-Benachrichtigung

Sendet nach dem Lauf automatisch eine Zusammenfassung per SMTP. Standard: nur bei Fehlern.

```python
from lib.notifications import send_run_summary
send_run_summary(report_data, progress_cb=p)
```

Die E-Mail enthält: Start/Ende/Dauer, Task-Übersicht mit ✅/❌, Fehlerdetails, Deduplizierungs-Statistiken.

### 8.3 lib/xml_validator.py – Pre-Upload-Validierung

Prüft BMEcat-XMLs vor dem Upload:

```python
from lib.xml_validator import validate_before_upload
all_ok = validate_before_upload(xml_paths, progress_cb=p)
```

Prüfungen:
1. Datei existiert und ist nicht leer
2. Artikel gefunden (Regex-Zählung, kein vollständiger XML-Parse)
3. Artikelanzahl über Schwellwert (konfigurierbar)
4. XML-Wohlgeformtheit (BMECAT-Header und -Footer)
5. Stichprobe: SUPPLIER_AID vorhanden

Ist als "soft validation" implementiert: warnt im Log, blockiert den Upload aber nicht.

### 8.4 lib/diff_report.py – Artikel-Diff

Vergleicht die aktuelle XML mit dem letzten Lauf:

```python
from lib.diff_report import create_diff_report
diff = create_diff_report("bueroring_merged.xml", progress_cb=p)
# diff = {"added": [...], "removed": [...], "price_changed": [...], "unchanged": 1234}
```

Arbeitsweise:
1. Beim ersten Lauf: Baseline speichern (keine Vergleichsdaten)
2. Ab dem zweiten Lauf: Vergleich mit dem letzten Snapshot
3. Snapshot als JSON unter `logs/diff_backups/` ablegen
4. Diff-Report als `diff_{datei}_{datum}.json`

Performance: Regex-basiert, verarbeitet 470 MB XML in ~5 Sekunden.

### 8.5 lib/parallel.py – Parallele Downloads

```python
from lib.parallel import run_parallel

results = run_parallel([
    ("Büroring",    download_bueroring,    p, fp),
    ("Softcarrier", download_softcarrier,  p, fp),
    ("Nordwest",    download_nordwest,     p, fp),
], max_workers=3, progress_cb=p)

for name, r in results.items():
    print(f"{name}: {'OK' if r['ok'] else r['error']}")
```

Ist ein Opt-in-Modul – aktuell laufen Tasks sequenziell. Kann in einem künftigen "Parallel-Download"-Task genutzt werden, der die Download-Phasen parallelisiert.

---

## 9. Tests

### Tests ausführen

```bat
cd C:\bmecat_download
python -m pytest tests/ -v
```

### Test-Übersicht

| Datei | Tests | Was wird geprüft |
|---|---|---|
| `test_utils.py` | 9 | glob_ci (leer, case, dedup, sortiert, extension), VERSION-Format |
| `test_xml_validator.py` | 10 | Fehlende Datei, leere Datei, keine Artikel, Truncation, Schwellwerte, AID-Stichprobe |
| `test_diff_report.py` | 11 | Snapshot-Extraktion, Vergleich (identisch, +/-, Preise, kombiniert), Baseline, Diff-Report-Datei |
| `test_notifications.py` | 4 | Subject-Zeile (Erfolg/Fehler), Body (Details, ohne Fehler) |
| `test_parallel.py` | 6 | Leer, Erfolg, Fehler, gemischt, tatsächlich parallel, Callback |

Alle Tests laufen ohne externe Abhängigkeiten (kein FTP, kein SMTP, keine echten XMLs).

### Eigene Tests schreiben

```python
# tests/test_mein_modul.py
import os, sys, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.mein_modul import meine_funktion

def test_basic():
    assert meine_funktion("input") == "expected"

def test_with_tmpdir(tmp_path):
    # tmp_path ist ein pathlib.Path der nach dem Test gelöscht wird
    (tmp_path / "test.xml").write_text("<BMECAT/>")
    result = meine_funktion(str(tmp_path / "test.xml"))
    assert result is not None
```

---

## 10. Troubleshooting

### Häufige Fehler

| Fehler | Ursache | Lösung |
|---|---|---|
| `Bestand_und_Preise.xlsx nicht gefunden` | Excel fehlt unter `C:\bmecat_download\` | Datei dorthin kopieren. Seit v1.1.0 wird der XML-Upload trotzdem ausgeführt. |
| `[WinError 2] Datei nicht gefunden` bei Softcarrier-Bildern | Doppelter Glob auf Windows (case-insensitiv) | In v1.1.0 behoben (`glob_ci` mit `set()` um die Ergebnisse). |
| `[WinError 10060] Verbindungsversuch fehlgeschlagen` bei Systeam | Server antwortet nicht, Timeout | Normal – Systeam-Server ist häufig offline. Ignorieren. |
| Doppelter Brickfox-Upload (2× im Log) | Toter Code in `others.py` | In v1.1.0 behoben. Spart ~2 Min + 640 MB pro Lauf. |
| `7-Zip nicht gefunden` | Pfad in config.py stimmt nicht | `TOOLS["7zip"]` anpassen oder 7-Zip installieren. |
| `Reiter 'Master' nicht gefunden` | Falsches Excel-Format | Prüfen ob `Bestand_und_Preise.xlsx` Reiter "Master" und "Bestand" hat. |
| `Nur X Artikel (erwartet mind. Y)` | Lieferant hat weniger Artikel geliefert | Schwellwert in `ARTICLE_THRESHOLDS` prüfen; ist nur Warnung. |

### Log-Dateien finden

| Log | Pfad | Inhalt |
|---|---|---|
| GUI-Log | Rechtsklick → Kopieren, oder Button "Speichern" | Vollständiges Lauf-Protokoll |
| Datei-Log | `logs/Log_YYYYMMDD.txt` | Gleicher Inhalt wie GUI (ohne Fortschrittszeilen) |
| Lauf-Report | `logs/lauf_YYYYMMDD_HHMMSS.json` | Strukturierte Zusammenfassung |
| Diff-Snapshots | `logs/diff_backups/*_snapshot.json` | Letzter Artikel-Stand pro Datei |
| Diff-Reports | `logs/diff_backups/diff_*_YYYYMMDD_HHMMSS.json` | Änderungen zum vorherigen Lauf |

### Task manuell wiederholen

Wenn nur ein Schritt fehlschlägt: in der GUI alle Checkboxen abwählen, nur den gewünschten Task aktivieren und starten. Fallback-Tasks:

- **Büroring – Merge (manuell)**: Startet nur Merge + Keywords, ohne Download
- **Bestandsdaten (nur CSV)**: Erzeugt nur die Availability-CSV
- **Verbindungstest**: Prüft ob FTP/SFTP-Server erreichbar sind

---

## 11. Erweiterungspotenzial

### Bereits implementiert (v1.1.0)

- ✅ `_run_7zip` zentralisiert in `lib/utils.py`
- ✅ `glob_ci()` Helper gegen Windows-Doppelglob
- ✅ Versionsstring in GUI-Titelleiste
- ✅ E-Mail-Benachrichtigung bei Fehlern
- ✅ XML-Validierung vor Upload
- ✅ Diff-Reports (neue/gelöschte Artikel, Preisänderungen)
- ✅ Parallele Downloads (lib/parallel.py, opt-in)
- ✅ Soennecken-Task registriert
- ✅ 40 Unit-Tests
- ✅ Bugfixes (Doppelglob, Excel-Crash, Doppel-Upload)

### Nächste Schritte (offene Ideen)

**Geringer Aufwand:**

- **Post-Upload-Prüfung** – nach dem Upload per FTP-Listing prüfen ob die Datei auf Brickfox angekommen ist. Aktuell kein Feedback ob Brickfox die Datei verarbeitet hat.
- **Rollback-Mechanismus** – die letzte funktionierende `bueroring_merged.xml` archivieren. Bei fehlerhaftem Merge kann die vorherige Version hochgeladen werden.
- **Bestandsdaten-Plausibilität** – Alarm wenn die Availability-CSV plötzlich unter einen Schwellwert fällt.

**Mittlerer Aufwand:**

- **Parallele Downloads aktivieren** – die Download-Phasen von Büroring, Softcarrier und Nordwest tatsächlich parallel starten. Das Modul steht bereit; fehlt ein Wrapper-Task der die drei Download-Funktionen parallel und die Merge/Upload-Phasen sequenziell aufruft.
- **Soennecken-Merge + Upload** – der Task ist registriert aber macht nur Download. Merge-Logik und Brickfox-Upload wie bei den anderen Lieferanten ergänzen.
- **Dashboard** – die `lauf_*.json`-Reports als HTML-Trend-Übersicht: Laufzeiten über 30 Tage, Fehlerquote, Datenmengen.

**Größerer Aufwand:**

- **XML-Verarbeitung mit lxml statt Regex** – robuster bei Formatänderungen, aber neue Dependency. Die Merge-Logik (775 Zeilen Regex) wäre der Hauptkandidat.
- **Bilder-Upload batchen** – 61.000 Einzel-JPGs per FTP ist langsam. ZIP-Upload oder Batch-mput wenn die Zielserver es unterstützen.
- **Multi-Mandanten** – `config.py` ist auf ABE zugeschnitten. Für mehrere Mandanten: `BASE_DIR` und `CONNECTIONS` pro Mandant (Kommandozeilen-Argument oder Config-Datei-Auswahl).
- **CI/CD** – `pytest` + GitHub Actions für automatische Regressionstests nach Code-Änderungen.
