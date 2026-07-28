# lib/tutorial.py – Interaktives In-App-Tutorial
#
# Zwei Komponenten:
#   ToolTip     – Hover-Tooltip für beliebige tkinter-Widgets
#   Tutorial    – Schritt-für-Schritt-Popup-Führung durch die UI

import tkinter as tk
from tkinter import ttk


# ── Tooltip ──────────────────────────────────────────────────────────────────

class ToolTip:
    """
    Einfacher Hover-Tooltip für tkinter-Widgets.
    Erscheint nach 600ms, verschwindet beim Verlassen.
    """
    _DELAY = 600

    def __init__(self, widget: tk.Widget, text: str):
        self._widget = widget
        self._text   = text
        self._tw     = None
        self._job    = None
        widget.bind("<Enter>",  self._schedule, add="+")
        widget.bind("<Leave>",  self._cancel,   add="+")
        widget.bind("<Button>", self._cancel,   add="+")

    def _schedule(self, _event=None):
        self._cancel()
        self._job = self._widget.after(self._DELAY, self._show)

    def _cancel(self, _event=None):
        if self._job:
            self._widget.after_cancel(self._job)
            self._job = None
        self._hide()

    def _show(self):
        if self._tw:
            return
        x, y, _, cy = self._widget.bbox("insert") if hasattr(self._widget, "bbox") \
                       and self._widget.bbox("insert") else (0, 0, 0, 0)
        x += self._widget.winfo_rootx() + 20
        y += self._widget.winfo_rooty() + self._widget.winfo_height() + 4

        self._tw = tw = tk.Toplevel(self._widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.attributes("-topmost", True)

        lbl = tk.Label(tw, text=self._text, wraplength=260,
                       justify="left", bg="#1a1a3a", fg="#eaeaea",
                       font=("Segoe UI", 9), relief="flat",
                       padx=8, pady=6, bd=1)
        lbl.pack()

        # Rahmen
        tw.configure(bg="#444466")
        tw.wm_attributes("-alpha", 0.95)

    def _hide(self):
        if self._tw:
            self._tw.destroy()
            self._tw = None


# ── Tutorial-Schritte ────────────────────────────────────────────────────────

STEPS = [
    {
        "title": "Willkommen im BMEcat Download-Tool",
        "text": (
            "Dieses Tutorial führt dich durch alle wichtigen Funktionen des Tools.\n\n"
            "Das Tool automatisiert den täglichen Katalogdaten-Import: "
            "Es lädt Produktkataloge von Lieferanten-Servern herunter, verarbeitet "
            "sie (Merge, Keywords, Preise, Bestand) und lädt sie auf die "
            "Verkaufsplattformen hoch (Brickfox, Mercateo/Unite).\n\n"
            "Tipp: Du kannst das Tutorial jederzeit mit 'Schließen' beenden "
            "und später über den '?' Knopf oben rechts neu starten."
        ),
        "widget_id": None,
    },
    {
        "title": "Die Task-Liste (linke Leiste)",
        "text": (
            "Die linke Leiste zeigt alle verfügbaren Aufgaben als farbige Buttons.\n\n"
            "Aktiv (Accent-Farbe) = wird beim nächsten Lauf ausgeführt.\n"
            "Inaktiv (grau) = wird übersprungen.\n\n"
            "Klick auf einen Button schaltet ihn ein oder aus. "
            "Tooltip beim Hover zeigt die ausführliche Beschreibung.\n\n"
            "Die Leiste lässt sich durch Ziehen des Trennbalkens breiter machen. "
            "Ab bestimmten Breiten schalten die Buttons automatisch auf "
            "2, 3 oder 4 Spalten um."
        ),
        "widget_id": "task_list",
    },
    {
        "title": "Alle / Keine / Standard",
        "text": (
            "Diese drei Knöpfe ganz oben steuern die Auswahl auf einmal:\n\n"
            "'Standard' → Vorauswahl wiederherstellen\n"
            "  (Setup-Check + Aufräumen + Büroring + Softcarrier + Nordwest + Bilder)\n\n"
            "'Alle' → jeden Task aktivieren\n\n"
            "'Keine' → alles deaktivieren – nützlich wenn du nur einen einzigen "
            "Task gezielt ausführen willst\n\n"
            "Tipp: 'Keine' → dann den gewünschten Task anklicken → 'Starten'."
        ),
        "widget_id": "sel_buttons",
    },
    {
        "title": "Setup-Check (Vorbereitung)",
        "text": (
            "Der Setup-Check prüft ohne Netzwerkzugriff ob alle Voraussetzungen "
            "für einen erfolgreichen Lauf erfüllt sind:\n\n"
            "• Git-Stand (Branch, Commit, Remote-URL)\n"
            "• 7-Zip installiert und gefunden\n"
            "• FTP/SFTP-Passwörter in allen Verbindungen gesetzt\n"
            "• Pflichtdateien: keywords_exploded.csv, Bestand_und_Preise.xlsx, "
            "fname_renames.csv, fvalue_renames.csv\n"
            "• Optionale Dateien: postprocess_*.csv, Mapping-CSVs\n"
            "• Verzeichnisse: in_BME, in, logs, export_vendosys\n\n"
            "Wichtig: Bei Fehlern bricht der Setup-Check den gesamten Lauf ab. "
            "Erst abwählen wenn die Ursache bekannt und absichtlich ignoriert wird."
        ),
        "widget_id": None,
    },
    {
        "title": "Aufräumen (Vorbereitung)",
        "text": (
            "Löscht alte XML-, CSV- und ZIP-Dateien aus dem Arbeitsverzeichnis "
            "bevor neue heruntergeladen werden.\n\n"
            "Warum wichtig: Ohne Aufräumen könnten veraltete Dateien vom Vortag "
            "versehentlich verarbeitet oder hochgeladen werden.\n\n"
            "Wann abwählen:\n"
            "• Du willst einen einzelnen Schritt wiederholen (z.B. nur Merge)\n"
            "• Die Quelldateien wurden gerade manuell angepasst\n\n"
            "Im Normalbetrieb immer aktiviert lassen."
        ),
        "widget_id": None,
    },
    {
        "title": "Büroring – Komplett",
        "text": (
            "Der komplexeste Lieferant – macht alles in einem Schritt:\n\n"
            "Quellen (Download von sftp.bueroring.de):\n"
            "  ↓ br-ek_DE_BMEcat_DEU_ABE.zip → bueroring.xml (ABE + ECLASS)\n"
            "  ↓ bf-ek_DE_BMEcat_DEU.zip → bueroring_basis.xml (Hauptkatalog)\n"
            "  ↓ br-bestand.zip → Bestandsdaten-CSV\n\n"
            "Verarbeitung: Merge beider XMLs + Keywords + FNAME/FVALUE + DB-Import\n\n"
            "Uploads:\n"
            "  ↑ bueroring_merged.xml → Brickfox (c_abe_ftp_2)\n"
            "  ↑ Products_bueroring_*.csv → Brickfox ERP (c_abe_ftp_3)\n"
            "  ↑ csv_autoimport_bueroring_*.csv → Brickfox Exchange (c_abe_ftp_5)\n\n"
            "Laufzeit: ~3–4 Minuten."
        ),
        "widget_id": None,
    },
    {
        "title": "Büroring – Merge (manuell)",
        "text": (
            "Nur der Merge-Schritt – ohne neuen Download.\n\n"
            "Wann nützlich:\n"
            "• Download hat funktioniert, aber Merge ist fehlgeschlagen\n"
            "• Quelldateien wurden manuell geändert (z.B. keywords_exploded.csv)\n"
            "• Schneller Test ob Konfigurationsänderungen korrekt wirken\n\n"
            "Standardmäßig deaktiviert."
        ),
        "widget_id": None,
    },
    {
        "title": "Softcarrier – Komplett",
        "text": (
            "Download + Merge + XML-Upload für Softcarrier:\n\n"
            "Quellen (ftp.softcarrier.com):\n"
            "  ↓ soft-carrier.xml (~280 MB Hauptkatalog)\n"
            "  ↓ DATA.CSV (TAB-Features/Attributdaten)\n"
            "  ↓ HERSTINFO.CSV (GPSR-Herstellerdaten)\n\n"
            "Verarbeitung: TAB-Features + GPSR in XML einarbeiten\n\n"
            "Upload: soft-carrier.xml → Brickfox /incoming\n\n"
            "Bilder (PREVIEW.ZIP mit ~61.000 JPGs) werden SEPARAT hochgeladen "
            "– über den 'Softcarrier – Bilder (Delta)' Task."
        ),
        "widget_id": None,
    },
    {
        "title": "Softcarrier – Bilder (Delta)",
        "text": (
            "Lädt nur die GEÄNDERTEN Bilder hoch – nicht alle 61.000 jedes Mal.\n\n"
            "Wie es funktioniert:\n"
            "Beim ersten Lauf werden alle Bilder hochgeladen (~10 Minuten, einmalig).\n"
            "Danach vergleicht das Tool Checksummen und lädt nur Neue/Geänderte "
            "hoch (~30 Sekunden bei typisch 200–500 Änderungen).\n\n"
            "Ziele:\n"
            "  ↑ Allago: 217.71.221.27 /thumbnails/ + /category/\n"
            "  ↑ OfficeXL: 217.71.221.26 /thumbnails/ + /category/\n\n"
            "Läuft nach allen XML-Uploads, damit er die anderen Tasks nicht blockiert."
        ),
        "widget_id": None,
    },
    {
        "title": "Nordwest – Komplett",
        "text": (
            "Nordwest liefert drei separate Katalog-Dateien (filehub.configo.de):\n\n"
            "  ↓ arbeitsschutz.zip → arbeitsschutz.xml (~40.000 Artikel)\n"
            "  ↓ werkstatt.zip → werkstatt.xml (~30.000 Artikel)\n"
            "  ↓ werkzeugtechnik.zip → werkzeugtechnik.xml (~50.000 Artikel)\n\n"
            "Verarbeitung: UDX-Felder → ARTICLE_FEATURES konvertieren\n"
            "Außerdem: KIP-CSV für Preisdaten auf Netzlaufwerk schreiben\n\n"
            "Upload: alle drei XMLs → Brickfox /incoming"
        ),
        "widget_id": None,
    },
    {
        "title": "Marktplätze – ECLASS-Analyse",
        "text": (
            "Liest die BMEcat-XML aus und löst für jeden Artikel die "
            "ECLASS-Kategorie auf (ECLASS 5.x und 9.x werden erkannt).\n\n"
            "Ergebnis: channels/article_eclass_categories.csv\n"
            "  → Artikel-Nr. | ECLASS-ID | ECLASS-Name | Konfidenz\n\n"
            "Warum nützlich:\n"
            "ECLASS ist eine lieferantenübergreifende Produktklassifikation. "
            "Damit lassen sich Artikel mehrerer Lieferanten auf dieselbe "
            "Marktplatz-Kategorie mappen – statt jeden Lieferanten einzeln.\n\n"
            "Voraussetzung für 'ECLASS → Kanal-Mapping'."
        ),
        "widget_id": None,
    },
    {
        "title": "Marktplätze – Kanal-Mappings",
        "text": (
            "Zwei Mapping-Tasks bereiten Marktplatz-Exporte vor:\n\n"
            "'ECLASS → Kanal-Mapping':\n"
            "Ordnet ECLASS-Endknoten den Kategorien auf eBay, Kaufland, "
            "Conrad, ManoMano etc. zu. Einmal gemappt gilt die Zuordnung "
            "lieferantenübergreifend für alle Artikel mit dieser ECLASS-ID.\n"
            "→ eclass_channel_mapping.csv\n\n"
            "'Kanal-Kategorie-Mapping':\n"
            "Fallback für Artikel ohne ECLASS: Lieferanten-Kategorien "
            "(BRG/SOC/NDW-Codes) direkt zu Marktplatz-Kategorien mappen.\n"
            "→ channel_category_mapping.csv\n\n"
            "Beide CSVs können im Konfiguration-Reiter bearbeitet werden."
        ),
        "widget_id": None,
    },
    {
        "title": "Starten und Abbrechen",
        "text": (
            "'Starten' führt alle aktiven Tasks in der richtigen Reihenfolge aus.\n\n"
            "Während ein Lauf läuft:\n"
            "• Statusleiste oben rechts zeigt 'Task 2/5: Softcarrier – Komplett'\n"
            "• Fortschrittsbalken zeigt aktuellen Dateidownload/-upload\n"
            "• Log zeigt alle Schritte in Echtzeit\n\n"
            "'Abbrechen' stoppt nach dem aktuellen Schritt "
            "(nicht mitten in einer Datei).\n\n"
            "Tipp: Wenn der Setup-Check rot ist, startet kein weiterer Task – "
            "erst die Ursache beheben oder Setup-Check abwählen."
        ),
        "widget_id": "run_btn",
    },
    {
        "title": "Das Log-Fenster",
        "text": (
            "Zeigt in Echtzeit alles was das Tool macht.\n\n"
            "Farben:\n"
            "• Grün / ✓  = Schritt erfolgreich\n"
            "• Gelb / ⚠  = Warnung (Lauf geht weiter, aber prüfen)\n"
            "• Rot / ✗   = Fehler (Task fehlgeschlagen, ggf. Abbruch)\n"
            "• Grau      = Info / Detailmeldung\n\n"
            "Am Anfang eines Tasks: Datenfluss-Box mit Quellen und Upload-Zielen.\n"
            "Am Anfang des Büroring-Tasks: Preflight-Check mit ✓/✗ für jede Datei.\n\n"
            "Nach dem Lauf: 'Log speichern' oder logs/Log_JJJJMMTT.txt."
        ),
        "widget_id": "log_area",
    },
    {
        "title": "Verbindungstest",
        "text": (
            "Prüft alle FTP/SFTP-Verbindungen ohne einen Lauf zu starten.\n\n"
            "Wann sinnvoll:\n"
            "• Nach Änderungen an Zugangsdaten\n"
            "• Wenn ein Lieferant-Task dauerhaft fehlschlägt\n"
            "• Auf einem neuen Rechner nach der Einrichtung\n\n"
            "Zeigt pro Verbindung: Status, Serverantwort, Verzeichnisinhalt.\n\n"
            "Tipp: Vor dem ersten echten Lauf auf einem neuen System immer "
            "zuerst den Verbindungstest durchführen."
        ),
        "widget_id": "conn_test_btn",
    },
    {
        "title": "Konfiguration (Knopf oben)",
        "text": (
            "Öffnet den Konfigurationsdialog – config.py muss nicht manuell "
            "bearbeitet werden.\n\n"
            "Änderbar:\n"
            "• Basispfad (Installationsverzeichnis)\n"
            "• FTP/SFTP-Zugangsdaten pro Lieferant\n"
            "• E-Mail-Benachrichtigungen (SMTP-Daten)\n"
            "• Artikel-Schwellwerte für Validierung\n\n"
            "Einstellungen werden in config_user.json gespeichert – "
            "haben Vorrang vor config.py, die Originaldatei bleibt unberührt."
        ),
        "widget_id": "config_btn",
    },
    {
        "title": "Reiter: Konfiguration – Pipeline-Übersicht",
        "text": (
            "Der Konfiguration-Reiter hat ganz oben 'Pipeline-Übersicht'.\n\n"
            "Klick auf eine Stufe zeigt:\n"
            "• Was in dieser Phase passiert\n"
            "• Welche Konfigurations-Datei sie steuert\n"
            "• Konkrete Server-Namen und Dateipfade\n\n"
            "Die Pipeline-Stufen:\n"
            "  Download → Transform → DB-Import → Post-Processing → Export → Upload\n\n"
            "Im Upload-Schritt siehst du alle Brickfox-FTP-Verbindungen "
            "(c_abe_ftp_2/3/5) und die Unite/Mercateo-Verbindung mit "
            "den genauen Remote-Pfaden."
        ),
        "widget_id": None,
    },
    {
        "title": "Reiter: Konfiguration – Dateien bearbeiten",
        "text": (
            "Links die Liste aller Konfigurations-Dateien, rechts der Editor.\n\n"
            "Wichtige Dateien:\n"
            "• fname_renames.csv – Feature-Namen normalisieren\n"
            "• fvalue_renames.csv – Feature-Werte normalisieren\n"
            "• postprocess_prices.csv – Preisformeln je Artikel\n"
            "• postprocess_blacklist.csv – Artikel dauerhaft ausblenden\n"
            "• postprocess_offline.csv – Artikel offline (ONLINE=0), bleibt im Export\n"
            "• description_regex.csv – Text-Ersetzungen in Kurz-/Langbeschreibung (vor Import)\n"
            "• udx_inject.csv – SOE.EPAG_ID/SELECTIONFEATURE nachtragen (vor Import)\n"
            "• custom_categories.csv – Eigene Kategorie-Namen\n"
            "• channel_category_mapping.csv – Marktplatz-Zuordnungen\n\n"
            "Dateien > 64 KB werden nur angezeigt (nicht editierbar) – "
            "sie werden per SQL-Skript generiert.\n\n"
            "Änderungen wirken beim nächsten Lauf – kein Neustart nötig."
        ),
        "widget_id": None,
    },
    {
        "title": "Reiter: Viewer / Export",
        "text": (
            "Zeigt alle Artikel aus der internen Datenbank (article_db.sqlite).\n\n"
            "Filter:\n"
            "  • Von / Bis: Zeitraum der letzten Änderung\n"
            "  • Lieferant: BRG / NDW / SOC\n"
            "  • Katalog: Root-Kategorie\n"
            "  • Artikel-Nr. / EAN: Sofortfilter beim Tippen\n\n"
            "Doppelklick = Detailansicht mit allen Feldern, Features und MIMEs.\n\n"
            "'Gefilterte Artikel exportieren' schreibt genau die "
            "aktuell sichtbaren Artikel als VENDOSYS_CAT XML ins Export-Verzeichnis – "
            "mit Blacklist, Preisformeln, EAN-Dedup und allen Post-Processing-Stufen."
        ),
        "widget_id": None,
    },
    {
        "title": "Scheduler – Automatische Läufe",
        "text": (
            "Richtet einen automatischen täglichen Lauf ein – "
            "auch ohne angemeldeten Benutzer.\n\n"
            "Einrichten:\n"
            "1. Uhrzeit wählen (z.B. 06:00)\n"
            "2. Gewünschte Tasks aktivieren\n"
            "3. 'Zeitplan einrichten' klicken\n\n"
            "Das erstellt einen Windows-Scheduled-Task via 'schtasks'.\n"
            "Das Ergebnis steht am nächsten Morgen in logs/Log_JJJJMMTT.txt.\n\n"
            "Empfehlung: Setup-Check im Scheduler-Lauf immer aktiviert lassen – "
            "er erkennt Konfigurationsprobleme bevor sie zu Fehlern werden."
        ),
        "widget_id": "scheduler_btn",
    },
    {
        "title": "Extras: Analyse und Qualitätskontrolle",
        "text": (
            "'Artikel-Sanity-Check':\n"
            "Prüft Datenqualität aller Kataloge – EAN-Abdeckung, fehlende "
            "Hersteller, Bildabdeckung, Artikel die bei mehreren Lieferanten "
            "vorkommen aber Lücken haben. Einmal wöchentlich empfohlen.\n\n"
            "'Cross-Filling Dashboard':\n"
            "HTML-Report: wer kann wem welche Felder liefern.\n\n"
            "'FNAME-Analyse':\n"
            "Extrahiert alle Feature-Namen aus den XMLs, prüft Kollisionen "
            "und erzeugt fname_alle.csv als Grundlage für fname_renames.csv.\n\n"
            "'Lauf-Trend-Report':\n"
            "Visualisiert Laufzeiten und Fehler der letzten 30 Läufe."
        ),
        "widget_id": None,
    },
    {
        "title": "Updates – neuen Stand ziehen",
        "text": (
            "Das Tool wird über Git aktualisiert. Auf dem Windows-Rechner:\n\n"
            "  cd C:\\Test\\bmecat-tool\n"
            "  git pull\n\n"
            "Der Setup-Check zeigt beim nächsten Start den aktuellen "
            "Git-Branch und Commit-Hash im Log – so siehst du sofort "
            "ob du den neuesten Stand hast.\n\n"
            "Tipp: git log --oneline -3 zeigt die letzten 3 Commits "
            "und ob du aktuell bist."
        ),
        "widget_id": None,
    },
    {
        "title": "Das war's!",
        "text": (
            "Du kennst jetzt alle wichtigen Funktionen des Tools.\n\n"
            "Täglicher Ablauf:\n"
            "  1. daten_ziehen.bat starten (oder Tool öffnen)\n"
            "  2. Standard-Auswahl prüfen\n"
            "  3. 'Starten' klicken\n"
            "  4. Log auf rote Meldungen prüfen\n\n"
            "Bei Problemen:\n"
            "  • Verbindungstest nutzen\n"
            "  • Setup-Check einzeln starten\n"
            "  • Log in logs/Log_JJJJMMTT.txt nachschauen\n"
            "  • Im Konfiguration-Reiter → Pipeline-Übersicht\n\n"
            "Das Tutorial ist jederzeit über den '?' Knopf oben erreichbar."
        ),
        "widget_id": None,
    },
]


# ── Tutorial-Dialog ───────────────────────────────────────────────────────────

class Tutorial:
    """
    Schritt-für-Schritt-Tutorial-Dialog für das BMEcat-Tool.
    """

    def __init__(self, parent: tk.Tk, widget_refs: dict = None):
        self._parent = parent
        self._refs   = widget_refs or {}
        self._step   = 0
        self._win    = None
        self._highlighted = None

    def start(self):
        self._step = 0
        self._build_window()
        self._show_step()
        if self._win and self._win.winfo_exists():
            self._win.lift()
            self._win.focus_force()

    def _build_window(self):
        if self._win and self._win.winfo_exists():
            self._win.lift()
            return

        self._win = win = tk.Toplevel(self._parent)
        win.title("Tutorial – BMEcat Download-Tool")
        win.resizable(True, True)                  # Fenstergröße nicht sperren
        win.attributes("-topmost", False)
        win.protocol("WM_DELETE_WINDOW", self._close)

        bg, fg = "#1a1a2e", "#eaeaea"
        accent  = "#e94560"
        win.configure(bg=bg)

        # Fortschrittsleiste oben
        pf = tk.Frame(win, bg="#0f3460", pady=6)
        pf.pack(fill="x")
        self._prog_lbl = tk.Label(pf, text="", font=("Segoe UI", 8),
                                   bg="#0f3460", fg="#aaa")
        self._prog_lbl.pack(side="left", padx=12)
        self._prog_bar = ttk.Progressbar(pf, length=160, mode="determinate",
                                          maximum=max(1, len(STEPS) - 1))
        self._prog_bar.pack(side="right", padx=12)

        # Titel
        self._title_lbl = tk.Label(win, text="Lade ...", font=("Segoe UI Semibold", 12),
                                    bg=bg, fg=accent, wraplength=420,
                                    justify="left", padx=20, pady=14, anchor="w")
        self._title_lbl.pack(fill="x")

        # Trennlinie
        tk.Frame(win, bg="#2a2a4a", height=1).pack(fill="x", padx=20)

        # Text – Text-Widget statt Label: scrollbar-fähig, keine Größenproblem
        self._text_lbl = tk.Text(
            win, font=("Segoe UI", 10), bg=bg, fg=fg,
            wrap="word", relief="flat", bd=0,
            padx=20, pady=14, cursor="arrow",
            width=52, height=10,  # feste Zeichengröße → vorhersehbare Pixelgröße
            state="disabled",
        )
        self._text_lbl.pack(fill="both", expand=True)

        # Navigation
        tk.Frame(win, bg="#2a2a4a", height=1).pack(fill="x")
        nav = tk.Frame(win, bg="#12122a", pady=10, padx=16)
        nav.pack(fill="x")

        self._back_btn = tk.Button(
            nav, text="← Zurück", command=self._prev,
            font=("Segoe UI", 9), bg="#0f3460", fg=fg,
            activebackground="#1a2a5a", activeforeground=fg,
            relief="flat", padx=12, pady=5, cursor="hand2", bd=0)
        self._back_btn.pack(side="left")

        tk.Button(nav, text="Schließen", command=self._close,
                  font=("Segoe UI", 9), bg="#2a2a3a", fg="#888",
                  activebackground="#3a3a5a", activeforeground=fg,
                  relief="flat", padx=12, pady=5, cursor="hand2", bd=0,
                  ).pack(side="left", padx=8)

        self._next_btn = tk.Button(
            nav, text="Weiter →", command=self._next,
            font=("Segoe UI Semibold", 9), bg=accent, fg="white",
            activebackground="#c73550", activeforeground="white",
            relief="flat", padx=16, pady=5, cursor="hand2", bd=0)
        self._next_btn.pack(side="right")

    def _reposition(self):
        """Positioniert das Tutorial-Fenster rechts neben dem Hauptfenster."""
        if not (self._win and self._win.winfo_exists()):
            return
        self._win.update_idletasks()

        pw   = self._parent.winfo_x()
        py   = self._parent.winfo_y()
        pw_w = self._parent.winfo_width()
        sw   = self._win.winfo_screenwidth()
        tw   = self._win.winfo_width()

        x = pw + pw_w + 8
        if x + tw > sw:
            x = max(0, pw - tw - 8)
        y = py + 40

        # Nur Position, keine Größe – Größe hat tkinter schon berechnet
        self._win.geometry(f"+{x}+{y}")

    def _show_step(self):
        if not (self._win and self._win.winfo_exists()):
            return

        step = STEPS[self._step]
        n    = len(STEPS)

        self._prog_lbl.config(text=f"Schritt {self._step + 1} von {n}")
        self._prog_bar.config(value=self._step)
        self._title_lbl.config(text=step["title"])

        # Text-Widget: normal → beschreiben → wieder sperren
        txt = self._text_lbl
        txt.config(state="normal")
        txt.delete("1.0", "end")
        txt.insert("end", step["text"])
        txt.config(state="disabled")

        self._back_btn.config(state="normal" if self._step > 0 else "disabled")
        last = self._step == n - 1
        self._next_btn.config(text="Fertig ✓" if last else "Weiter →")

        # Highlight
        self._unhighlight()
        wid = step.get("widget_id")
        if wid and wid in self._refs:
            self._highlight(self._refs[wid])

        self._reposition()

    def _highlight(self, widget: tk.Widget):
        """Hebt ein Widget durch temporäre Hintergrundänderung hervor."""
        try:
            orig = widget.cget("bg")
            widget.config(bg="#533483")
            self._highlighted = (widget, orig)
        except Exception:
            self._highlighted = None

    def _unhighlight(self):
        if self._highlighted:
            widget, orig = self._highlighted
            try:
                widget.config(bg=orig)
            except Exception:
                pass
            self._highlighted = None

    def _next(self):
        if self._step < len(STEPS) - 1:
            self._step += 1
            self._show_step()
        else:
            self._close()

    def _prev(self):
        if self._step > 0:
            self._step -= 1
            self._show_step()

    def _close(self):
        self._unhighlight()
        if self._win and self._win.winfo_exists():
            self._win.destroy()
        self._win = None


# ── Tooltips für alle UI-Elemente ────────────────────────────────────────────

BUTTON_TIPS = {
    "Verbindungstest": "FTP/SFTP-Verbindung zu den Lieferanten-Servern testen, ohne einen Lauf zu starten.",
    "Konfiguration":   "Zugangsdaten, Pfade und E-Mail-Benachrichtigungen konfigurieren.",
    "Scheduler":       "Automatische tägliche Läufe einrichten (Windows Task Scheduler).",
    "BMEcat laden":    "Eine lokale BMEcat-1.2-Datei ohne vorherigen Download direkt in die Artikel-Datenbank importieren.",
    "Theme: ABE":      "Zur hellen ABE-Farbgebung wechseln.",
    "Theme: Classic":  "Zur dunklen Classic-Farbgebung wechseln.",
    "Starten":         "Alle aktivierten Tasks in der richtigen Reihenfolge ausführen.",
    "Abbrechen":       "Laufenden Lauf nach dem aktuellen Schritt stoppen.",
    "Log loeschen":    "Logfenster leeren (Datei in logs/ bleibt erhalten).",
    "Log speichern":   "Log als Textdatei speichern.",
    "Alle":            "Alle Tasks aktivieren.",
    "Keine":           "Alle Tasks deaktivieren.",
    "Standard":        "Standardauswahl wiederherstellen (aktive Lieferanten).",
    "Oeffnen":         "Basispfad im Explorer öffnen.",
    "?":               "Schritt-für-Schritt-Tutorial starten.",
    "Viewer / Export": "Artikel aus der DB anzeigen, filtern und als VENDOSYS-XML exportieren.",
    "Konfiguration":   "Alle Konfigurations-Dateien im eingebauten Editor anzeigen und bearbeiten.",
}

TASK_TIPS = {
    "setup_check":        "Prüft Git-Stand, 7-Zip, alle FTP-Passwörter, Pflichtdateien und Verzeichnisse – kein Netzwerkzugriff. Bei Fehlern wird der gesamte Lauf abgebrochen.",
    "cleanup":            "Löscht alte XML/CSV/ZIP-Dateien aus dem Arbeitsverzeichnis. Immer zuerst ausführen.",
    "parallel_download":  "Lädt Büroring, Softcarrier und Nordwest gleichzeitig herunter – spart ca. 3 Minuten Wartezeit.",
    "bueroring":          "Büroring komplett: Download (~470 MB) → Merge+Keywords → Bestand → Upload auf Brickfox+Mercateo.",
    "bueroring_bilder":   "Büroring Bilder und Dokumente herunterladen und entpacken. Nicht täglich nötig – nur wenn neue Bilddaten erwartet werden.",
    "bueroring_merge":    "Nur Merge ohne Download. Nützlich wenn Download erfolgreich war aber Merge fehlgeschlagen ist.",
    "buecat_merge":       "Manueller Merge-Trigger: direkt steuern welche Dateien zusammengeführt werden.",
    "bueroring_bestand":  "Nur Bestandsdaten: Excel patchen + CSV-Exporte für Brickfox ERP und Exchange.",
    "softcarrier":        "Softcarrier komplett: Download → Feature-Merge → Brickfox-Upload. Bilder SEPARAT (nächster Task).",
    "softcarrier_merge":  "Nur Merge ohne Download. Fallback wenn Download OK aber Merge fehlgeschlagen.",
    "softcarrier_img_patch": "Einmalig ausführen wenn die Softcarrier-Bild-ZIPs (GRAPHIK1-9.ZIP) lokal vorliegen. Löst das MIME_SOURCE-Problem: Farbvarianten bekommen ihr richtiges Bild statt zufällig dasselbe. Vorher DIRS.sc_bilder_zips in der Konfiguration setzen.",
    "softcarrier_bilder": "Nur geänderte Bilder auf Allago + OfficeXL hochladen (Delta: typisch 200-500 statt 61.000).",
    "nordwest":           "Nordwest: 3 XMLs herunterladen + UDX-Konvertierung + KIP-CSV + Brickfox-Upload.",
    "systeam":            "Systeam: nur Download. Aktuell inaktiv (fehlende Preise).",
    "soennecken":         "Soennecken: nur Download. Aktuell inaktiv (keine Datenlieferung).",
    "bmecat_merge":       "Manueller Merge-Trigger: direkt steuern welche Dateien zusammengeführt werden.",
    "bestandsdaten":      "Nur Availability-CSV für Mercateo erzeugen, ohne Download.",
    "cleanup_logs":       "Alte Log-Dateien und Export-CSVs (>30 Tage) löschen.",
    "fname_analyse":      "Extrahiert alle Feature-Namen aus den XMLs, prüft Kollisionen und erzeugt fname_alle.csv als Grundlage für fname_renames.csv.",
    "sanity_check":       "Datenqualität prüfen + Cross-Supplier-Vergleich. Einmal wöchentlich empfohlen.",
    "dashboard":          "HTML-Dashboard aus letztem Sanity-Report generieren. Im Browser öffnen.",
    "trend_report":       "Visualisiert Laufzeiten und Fehlerquoten der letzten 30 Läufe als HTML-Bericht.",
    "ki_anreicherung":    "Verbessert Artikeldaten mit Claude-KI (Beschreibungen, Kategorien). Erfordert AI_ENRICHMENT in config aktiviert.",
    "eclass_catalog_scrape": "Scrapt den vollständigen eClass-Katalog von eclass.eu (alle Versionen, alle 4 Ebenen). Einmalig ausführen. Benötigt: py -m pip install selenium webdriver-manager. Ausgabe: eclass_catalog.csv.",
    "eclass_analyse":     "Liest ECLASS-Kategorien aus BMEcat-XMLs und erzeugt article_eclass_categories.csv. Voraussetzung für ECLASS→Kanal-Mapping.",
    "eclass_channel_map": "Ordnet ECLASS-Endknoten Marktplatz-Kategorien zu (eBay, Kaufland, Conrad…). Einmal gemappt gilt die Zuordnung für alle Lieferanten mit dieser ECLASS-ID.",
    "channel_mapping":    "Lieferanten-Kategorien direkt zu Marktplatz-Kanälen mappen – Fallback für Artikel ohne ECLASS-ID.",
}
