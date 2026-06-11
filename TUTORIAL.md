# BMEcat Download-Tool – Tutorial

**Für:** Neue Benutzer und Übergabe an Kollegen  
**Dauer:** 20 Minuten Lesen, 15 Minuten Einrichten  
**Voraussetzungen:** Windows 10/11, Internetverbindung

---

## Teil 1: Was macht das Tool? (5 Minuten)

Das Tool ist eine tägliche Automatisierung: Es holt Produktkataloge von FTP-Servern, verarbeitet sie und lädt sie auf die Verkaufsplattformen hoch.

**Ohne das Tool:**
- Manuell 3–5 ZIP-Dateien von verschiedenen FTP-Servern runterladen
- Entpacken, umbenennen, zusammenführen
- Manuell auf 8 Plattformen hochladen
- ~2 Stunden täglich

**Mit dem Tool:**
- Starten, Kaffee holen
- ~8 Minuten, alles automatisch

### Was wird verarbeitet?

```
Lieferant         Dateigröße    Artikel    Zielplattformen
──────────────────────────────────────────────────────────
Büroring          ~470 MB XML   ~21.800    Brickfox, Mercateo
Softcarrier       ~280 MB XML   ~63.000    Brickfox, Allago, OfficeXL
                  ~60.000 Bilder
Nordwest          3× XML        ~57.000    Brickfox
Systeam           ZIP           (inaktiv)
```

---

## Teil 2: Ersteinrichtung (10 Minuten)

### Schritt 1: Voraussetzungen installieren

**Python** (falls noch nicht vorhanden):
1. https://www.python.org/downloads/ → neueste Version laden
2. Installer starten → **unbedingt** "Add python.exe to PATH" ankreuzen
3. "Install Now" klicken

**7-Zip** (falls noch nicht vorhanden):
1. https://www.7-zip.org/ → Download (64-bit)
2. Standard-Installation (Pfad `C:\Program Files\7-Zip\` beibehalten)

### Schritt 2: Tool installieren

1. ZIP-Datei nach `C:\bmecat_download\` entpacken
2. `install.bat` doppelklicken

Das Skript:
- Findet Python automatisch (sucht in üblichen Installationspfaden)
- Installiert alle Python-Pakete (paramiko, openpyxl, pandas, chardet, pywin32)
- Prüft ob 7-Zip vorhanden ist
- Legt alle benötigten Verzeichnisse an

Erwartete Ausgabe (grob):
```
[1/6] Suche Python... Python 3.12.3  OK
[2/6] Suche 7-Zip...  Gefunden: C:\Program Files\7-Zip\7z.exe
[3/6] Aktualisiere pip... OK
[4/6] Installiere Abhängigkeiten...
  - paramiko  OK
  - openpyxl  OK
  - pandas    OK
  - chardet   OK
  - pywin32   OK
[5/6] Verzeichnisse anlegen... OK
[6/6] Prüfe Installation...  Alle Pflicht-Pakete geladen.
Installation abgeschlossen!
```

### Schritt 3: Pflicht-Dateien kopieren

Folgende Dateien müssen in `C:\bmecat_download\` liegen:

| Datei | Woher |
|---|---|
| `Bestand_und_Preise.xlsx` | Wird extern gepflegt – vom Vorgänger/Kollegen übergeben |
| `keywords_exploded.csv` | Im ZIP enthalten oder gesondert übergeben (~87 MB) |

### Schritt 4: Ersten Start durchführen

`start.bat` doppelklicken. Das Fenster öffnet sich:

```
┌──────────────────────────────────────────────────────────────┐
│  BMEcat Download-Tool v1.1.0          [Test] [Config] [...]  │
├──────────────┬───────────────────────────────────────────────┤
│ ☑ Aufräumen  │                                               │
│ ☑ Büroring   │  BMEcat Download-Tool v1.1.0 bereit.         │
│ ☑ Softcarrier│  ⚠ Letzter Lauf: vor 72 Stunden (falls       │
│ ☑ Nordwest   │     Heartbeat-Check anspringt)                │
│ ☑ Bilder     │                                               │
│ ☐ Systeam    │                                               │
│ ☐ Soennecken │                                               │
├──────────────┴───────────────────────────────────────────────┤
│  [▶ Starten]   [■ Abbrechen]                                 │
└──────────────────────────────────────────────────────────────┘
```

**Erster Test:** Alle Tasks abwählen (Schaltfläche "Keine"), nur "Büroring – Komplett" aktivieren, dann Starten. Wenn das durchläuft, funktioniert alles grundsätzlich.

---

## Teil 3: Täglicher Betrieb (3 Minuten)

### Normaler Lauf

1. `start.bat` doppelklicken
2. Aktive Tasks prüfen (Standard: Aufräumen, Büroring, Softcarrier, Nordwest, Bilder)
3. **Starten** klicken
4. ~8 Minuten warten
5. Log auf rote Markierungen prüfen

### Was bedeuten die Farben im Log?

| Farbe | Bedeutung |
|---|---|
| Grün / ✓ | Schritt erfolgreich |
| Gelb / ⚠ | Warnung – Lauf läuft weiter, aber etwas stimmt nicht ganz |
| Rot / ✗ | Fehler – dieser Task ist fehlgeschlagen |
| Grau | Informationsmeldung |

### Automatischer Lauf (Scheduler)

Damit das Tool täglich automatisch um z.B. 06:00 Uhr läuft:

1. GUI öffnen → **Scheduler**-Button
2. Uhrzeit einstellen, Tasks auswählen
3. "Zeitplan einrichten" klicken

Das erstellt einen Windows-Task. Ab dann läuft das Tool täglich automatisch, auch ohne dass jemand angemeldet ist (Dienst).

---

## Teil 4: Die häufigsten Aufgaben

### "Nur Büroring hochladen, weil was schief gelaufen ist"

1. Alle Tasks abwählen (Button "Keine")
2. Nur "Büroring – Komplett" aktivieren
3. Starten

### "Merge nochmal machen, ohne neu runterzuladen"

1. Alle abwählen
2. "Büroring – Merge (manuell)" aktivieren
3. Starten — nutzt die bereits heruntergeladenen Dateien

### "Bilder separat hochladen"

1. Alle abwählen
2. "Softcarrier – Bilder (Delta)" aktivieren
3. Starten — lädt nur geänderte Bilder hoch (~347 statt 61.000)

### "Verbindung zu einem Server testen"

Button **Test** in der Kopfzeile → Server auswählen → Verbinden. Zeigt ob FTP/SFTP erreichbar ist und listet das Verzeichnis.

### "Sanity-Check: Datenqualität prüfen"

1. Alle abwählen
2. "Artikel-Sanity-Check" (Extras-Gruppe) aktivieren
3. Starten

Zeigt: EAN-Abdeckung, fehlende Hersteller, Langbeschreibungen, Bilder — pro Lieferant. Findet außerdem Artikel die in mehreren Katalogen sind, aber bei einem Hersteller oder Langbeschreibung fehlt.

### "Altes Log speichern"

Rechtsklick im Log-Fenster → "Kopieren", oder Button "Log speichern" unten rechts.

---

## Teil 5: Konfiguration anpassen

### FTP-Zugangsdaten

In `config.py`:

```python
CONNECTIONS = {
    "bueroring": {
        "host":     "ftp.bueroring.de",
        "user":     "benutzer",
        "password": "passwort",
        "protocol": "sftp",
        "port":     22,
    },
    # ...
}
```

Oder über die GUI: Button **Config** → Felder ändern → Speichern.  
Die GUI speichert in `config_user.json`, die `config.py` überschreibt (original bleibt unberührt).

### E-Mail-Benachrichtigungen aktivieren

In `config.py`:

```python
NOTIFICATION = {
    "enabled":   True,
    "smtp_host": "smtp.office365.com",
    "smtp_port": 587,
    "smtp_user": "bmecat@abe-brands.de",
    "smtp_pass": "passwort",
    "smtp_tls":  True,
    "from":      "bmecat@abe-brands.de",
    "to":        ["admin@abe-brands.de"],
    "on_success": False,  # nur bei Fehlern
}
```

### Artikel-Schwellwerte

Wenn die Validierung zu viele oder zu wenige Warnungen erzeugt:

```python
ARTICLE_THRESHOLDS = {
    "bueroring_merged.xml":    20000,  # Warnung wenn unter 20.000 Artikel
    "soft-carrier_merge.xml":  60000,
    "arbeitsschutz.xml":        5000,
    "werkstatt.xml":           10000,
    "werkzeugtechnik.xml":     40000,
}
```

---

## Teil 6: Troubleshooting

### Das Programm startet nicht

1. `install.bat` erneut ausführen
2. Prüfen ob Python im PATH: Eingabeaufforderung öffnen → `python --version` tippen
3. Falls "nicht erkannt": Python neu installieren mit "Add to PATH"

### "7-Zip nicht gefunden"

Prüfen ob 7-Zip unter `C:\Program Files\7-Zip\7z.exe` liegt.  
Falls anderer Pfad: in `config.py` anpassen:
```python
TOOLS = {"7zip": r"C:\mein\pfad\7z.exe"}
```

### "Bestand_und_Preise.xlsx nicht gefunden"

Datei nach `C:\bmecat_download\` kopieren. Seit v1.1.0 läuft der XML-Upload trotzdem durch — nur die CSV-Dateien für Brickfox ERP/Exchange werden nicht erzeugt.

### Verbindungsfehler bei Systeam

Systeam ist derzeit inaktiv (fehlende Preise). Task ist standardmäßig deaktiviert. Meldungen im Log sind normal.

### "Circuit Breaker OPEN" im Log

Ein FTP-Server hat 3× hintereinander nicht geantwortet. Das Tool sperrt ihn für 5 Minuten automatisch. Wenn das täglich passiert: Server-Status beim Lieferanten prüfen.

### XML-Fehler beim Upload

Das Tool läuft seit v1.1.0 eine automatische Reparatur: nackte `&`-Zeichen (z.B. in Produktnamen wie "Clic & Go") werden zu `&amp;` escaped. Wenn dennoch ein XML-Fehler vom Brickfox kommt: Log prüfen auf "XML-Sanitize" — die Zahl der reparierten Stellen steht dort.

### Log-Dateien finden

| Was | Wo |
|---|---|
| GUI-Log | Rechtsklick → Kopieren |
| Datei-Log | `C:\bmecat_download\logs\Log_YYYYMMDD.txt` |
| Lauf-Report (JSON) | `C:\bmecat_download\logs\lauf_YYYYMMDD_HHMMSS.json` |
| Diff-Reports | `C:\bmecat_download\logs\diff_backups\` |
| XML-Backups | `C:\bmecat_download\logs\xml_backups\` |
| Sanity-Reports | `C:\bmecat_download\logs\sanity_*.json` |

---

## Teil 7: Tests ausführen (für Entwickler)

```bat
cd C:\bmecat_download
python -m pytest tests\ -v
```

Erwartete Ausgabe: `71 passed` (oder mehr) in unter 1 Sekunde.

---

*Letzte Aktualisierung: v1.1.0 — Mai 2026*
