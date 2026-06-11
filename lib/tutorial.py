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
            "Dieses Tutorial führt dich in 15 Schritten durch alle wichtigen "
            "Funktionen des Tools.\n\n"
            "Das Tool automatisiert den täglichen Katalogdaten-Import: "
            "Es lädt Produktkataloge von FTP-Servern herunter, verarbeitet "
            "sie und lädt sie auf die Verkaufsplattformen hoch.\n\n"
            "Tipp: Du kannst das Tutorial jederzeit mit 'Schließen' beenden "
            "und später über den '?' Knopf neu starten."
        ),
        "widget_id": None,
    },
    {
        "title": "Die Task-Liste (links)",
        "text": (
            "Hier wählst du aus, welche Aufgaben beim nächsten Lauf ausgeführt "
            "werden sollen.\n\n"
            "Jede Checkbox ist ein 'Task' – ein eigenständiger Arbeitsschritt. "
            "Du kannst beliebig kombinieren: z.B. nur Büroring, oder alles außer Bilder.\n\n"
            "Die grauen Beschriftungen darunter erklären kurz was der Task macht."
        ),
        "widget_id": "task_list",
    },
    {
        "title": "Aufräumen (Vorbereitung)",
        "text": (
            "Der erste Task 'Aufräumen' löscht alte XML-, CSV- und ZIP-Dateien "
            "aus dem Arbeitsverzeichnis.\n\n"
            "Das ist wichtig damit keine veralteten Dateien aus dem Vortag "
            "versehentlich hochgeladen werden. Immer als erstes aktiviert lassen.\n\n"
            "Ausnahme: du willst gezielt einen einzelnen Schritt wiederholen – "
            "dann Aufräumen abwählen."
        ),
        "widget_id": None,
    },
    {
        "title": "Büroring – Komplett",
        "text": (
            "Der komplexeste Lieferant. Dieser Task macht alles in einem Schritt:\n\n"
            "1. Download vom SFTP-Server (~470 MB XML)\n"
            "2. Merge: Zwei Quelldateien zusammenführen + ECLASS-Features + Keywords\n"
            "3. Bestandsdaten: Excel-Datei patchen, CSV-Exporte erzeugen\n"
            "4. Upload auf Brickfox, Mercateo, Brickfox ERP, Brickfox Exchange\n\n"
            "Laufzeit: ~3–4 Minuten."
        ),
        "widget_id": None,
    },
    {
        "title": "Büroring – Merge (manuell)",
        "text": (
            "Dieser Fallback-Task macht nur den Merge-Schritt – "
            "ohne neu herunterzuladen.\n\n"
            "Wann nützlich: Der Download hat geklappt, aber der Merge ist "
            "fehlgeschlagen. Oder du hast die Quelldateien manuell angepasst "
            "und willst nur neu zusammenführen.\n\n"
            "Standardmäßig deaktiviert."
        ),
        "widget_id": None,
    },
    {
        "title": "Softcarrier – Komplett",
        "text": (
            "Download + Merge + XML-Upload für Softcarrier:\n\n"
            "1. Download: soft-carrier.xml (~280 MB), DATA.CSV, HERSTINFO.CSV, PREVIEW.ZIP\n"
            "2. Merge: TAB-Features aus CSV + GPSR-Herstellerdaten einfügen\n"
            "3. Upload der merged XML auf Brickfox\n\n"
            "Die ~61.000 Bilder aus PREVIEW.ZIP werden NICHT hier hochgeladen – "
            "dafür gibt es den separaten 'Bilder'-Task (schneller, entkoppelt)."
        ),
        "widget_id": None,
    },
    {
        "title": "Softcarrier – Bilder (Delta)",
        "text": (
            "Lädt nur die GEÄNDERTEN Bilder auf Allago und OfficeXL hoch.\n\n"
            "Beim ersten Lauf: alle ~61.000 Bilder (einmalig, ~10 Minuten).\n"
            "Bei Folgeläufen: typischerweise nur 200–500 geänderte Bilder (~30 Sekunden).\n\n"
            "Dieser Task läuft ganz am Ende, NACHDEM alle XML-Uploads "
            "der anderen Lieferanten abgeschlossen sind. So blockiert er nicht "
            "den Nordwest-Upload."
        ),
        "widget_id": None,
    },
    {
        "title": "Nordwest – Komplett",
        "text": (
            "Nordwest liefert drei separate XML-Dateien:\n\n"
            "• arbeitsschutz.xml (~40.000 Artikel)\n"
            "• werkstatt.xml (~30.000 Artikel)\n"
            "• werkzeugtechnik.xml (~50.000 Artikel)\n\n"
            "Alle drei werden zusammen heruntergeladen, entpackt, mit "
            "UDX-zu-Feature-Konvertierung verarbeitet und auf Brickfox hochgeladen.\n\n"
            "Außerdem: KIP-CSV für Preisdaten auf ein Netzlaufwerk."
        ),
        "widget_id": None,
    },
    {
        "title": "Standard / Alle / Keine",
        "text": (
            "Diese drei Knöpfe steuern die Auswahl schnell:\n\n"
            "'Standard' → setzt die Vorauswahl zurück (Aufräumen + die 3 aktiven Lieferanten + Bilder)\n"
            "'Alle' → aktiviert jeden einzelnen Task\n"
            "'Keine' → deaktiviert alles (nützlich wenn man nur einen bestimmten Task will)\n\n"
            "Tipp: 'Keine' klicken, dann nur den gewünschten Task ankreuzen – "
            "gut zum Wiederholen einzelner Schritte."
        ),
        "widget_id": "sel_buttons",
    },
    {
        "title": "Starten und Abbrechen",
        "text": (
            "'Starten' führt alle aktivierten Tasks in der richtigen Reihenfolge aus.\n\n"
            "Während ein Lauf läuft:\n"
            "• Die Statusleiste oben rechts zeigt 'Task 2/5: Softcarrier'\n"
            "• Der Fortschrittsbalken zeigt den aktuellen Dateidownload/-upload\n"
            "• Im Log erscheinen alle Schritte in Echtzeit\n\n"
            "'Abbrechen' stoppt nach dem aktuellen Schritt (nicht mitten in einer Datei)."
        ),
        "widget_id": "run_btn",
    },
    {
        "title": "Das Log-Fenster",
        "text": (
            "Hier siehst du alles was das Tool macht – in Echtzeit.\n\n"
            "Farben:\n"
            "• Grün / ✓  = Schritt erfolgreich\n"
            "• Gelb / ⚠  = Warnung (Lauf geht weiter, aber etwas stimmt nicht ganz)\n"
            "• Rot / ✗   = Fehler (dieser Task ist fehlgeschlagen)\n"
            "• Grau      = Informationsmeldung\n\n"
            "Nach dem Lauf: 'Log speichern' für ein Textdokument, oder "
            "in logs/Log_JJJJMMTT.txt nachschauen."
        ),
        "widget_id": "log_area",
    },
    {
        "title": "Verbindungstest",
        "text": (
            "Über diesen Knopf kannst du prüfen ob die FTP/SFTP-Verbindungen "
            "zu den Lieferanten-Servern funktionieren – ohne einen Lauf zu starten.\n\n"
            "Wann sinnvoll:\n"
            "• Nach Änderungen in config.py (neue Zugangsdaten)\n"
            "• Wenn ein Lieferant-Task dauerhaft fehlschlägt\n"
            "• Morgens vor dem ersten Lauf, wenn man sichergehen will\n\n"
            "Zeigt Verbindungsstatus und Verzeichnisinhalt."
        ),
        "widget_id": "conn_test_btn",
    },
    {
        "title": "Konfiguration",
        "text": (
            "Öffnet den Konfigurationsdialog – ohne config.py manuell bearbeiten zu müssen.\n\n"
            "Hier kannst du ändern:\n"
            "• Basispfad (Installationsverzeichnis)\n"
            "• FTP-Zugangsdaten pro Lieferant\n"
            "• E-Mail-Benachrichtigungen (aktivieren + SMTP-Daten)\n"
            "• Artikel-Schwellwerte für Validierung\n\n"
            "Einstellungen werden in config_user.json gespeichert und haben "
            "Vorrang vor config.py – die Originaldatei bleibt unverändert."
        ),
        "widget_id": "config_btn",
    },
    {
        "title": "Scheduler – Automatische Läufe",
        "text": (
            "Hier richtest du ein, dass das Tool täglich automatisch startet – "
            "auch wenn niemand angemeldet ist.\n\n"
            "Einstellen:\n"
            "1. Uhrzeit (z.B. 06:00 Uhr)\n"
            "2. Gewünschte Tasks auswählen\n"
            "3. 'Zeitplan einrichten' klicken\n\n"
            "Das erzeugt einen Windows-Task via 'schtasks'. "
            "Danach läuft das Tool täglich automatisch. Das Ergebnis findest du "
            "am nächsten Morgen in den Log-Dateien."
        ),
        "widget_id": "scheduler_btn",
    },
    {
        "title": "Extras: Sanity-Check und Dashboard",
        "text": (
            "Ganz unten in der Task-Liste findest du die Extras:\n\n"
            "'Artikel-Sanity-Check': Prüft Datenqualität aller Kataloge "
            "(EAN-Abdeckung, fehlende Hersteller, Bildabdeckung) und findet "
            "Artikel die bei mehreren Lieferanten vorkommen aber Lücken haben.\n\n"
            "'Cross-Filling Dashboard': Generiert eine HTML-Datei die du im "
            "Browser öffnen kannst. Zeigt visuell: wer kann wem welche Felder "
            "liefern (z.B. Büroring kennt den Hersteller, Softcarrier nicht).\n\n"
            "Nicht im täglichen Lauf – einmal wöchentlich zur Qualitätskontrolle."
        ),
        "widget_id": None,
    },
    {
        "title": "Reiter: Viewer / Export",
        "text": (
            "Der zweite Reiter 'Viewer / Export' zeigt alle Artikel aus der "
            "internen Datenbank (article_db.sqlite).\n\n"
            "Filter oben:\n"
            "  • Von / Bis: Zeitraum der letzten Änderung\n"
            "  • Lieferant: nur BRG / NDW / SOC\n"
            "  • Katalog: Root-Kategorie (z.B. Arbeitsschutz)\n"
            "  • Artikel-Nr. / EAN: Sofortfilter, reagiert beim Tippen\n\n"
            "Doppelklick auf einen Artikel öffnet das Detailfenster mit allen "
            "Feldern, Features und MIMEs.\n\n"
            "Der DB-Status oben rechts zeigt immer wie viele Artikel pro "
            "Lieferant in der Datenbank sind."
        ),
        "widget_id": None,
    },
    {
        "title": "Viewer: Gefilterter Export",
        "text": (
            "Der Knopf 'Gefilterte Artikel exportieren' exportiert genau die "
            "Artikel die aktuell in der Tabelle angezeigt werden.\n\n"
            "Was beim Export passiert:\n"
            "  1. Blacklist-Prüfung (Artikel überspringen)\n"
            "  2. Preisformeln anwenden (SOC: *Faktor → nrp)\n"
            "  3. Preis-Typ-Konvertierung (BRG: net_list → nrp)\n"
            "  4. FUSAGE=3 setzen\n"
            "  5. MIME-Zwecke korrigieren\n"
            "  6. EAN-Dedup (bei gleicher EAN: BRG schlägt NDW)\n"
            "  7. VENDOSYS_CAT XML schreiben (price_type='net_customer')\n\n"
            "Die Exportdateien liegen im Export-Verzeichnis aus config.py."
        ),
        "widget_id": None,
    },
    {
        "title": "Reiter: Konfiguration",
        "text": (
            "Der dritte Reiter 'Konfiguration' ist ein eingebauter Editor "
            "für alle Konfigurations-Dateien.\n\n"
            "Links: Liste aller Dateien mit Kurztitel.\n"
            "Rechts oben: Ausführliche Erklärung was die Datei macht.\n"
            "Rechts unten: Editor zum direkten Bearbeiten.\n\n"
            "Dateien > 64 KB (z.B. postprocess_prices.csv mit 73K Zeilen) "
            "werden nur zur Ansicht angezeigt – sie werden automatisch "
            "aus dem SQL-Skript generiert und nicht manuell editiert.\n\n"
            "Nach dem Speichern: Das Tool muss NICHT neu gestartet werden –"
            " Änderungen werden beim nächsten Export automatisch gelesen."
        ),
        "widget_id": None,
    },
    {
        "title": "Das war's! 🎉",
        "text": (
            "Du kennst jetzt alle wichtigen Funktionen des Tools.\n\n"
            "Wichtigste Regel für den Alltag:\n"
            "1. start.bat öffnen\n"
            "2. Standard-Auswahl prüfen\n"
            "3. Starten\n"
            "4. Log auf rote Meldungen prüfen\n\n"
            "Bei Problemen: TUTORIAL.md und WIKI.md im Programmordner, "
            "oder den Verbindungstest nutzen.\n\n"
            "Dieses Tutorial ist jederzeit über den '?' Knopf oben erreichbar."
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
    "cleanup":            "Löscht alte XML/CSV/ZIP-Dateien aus dem Arbeitsverzeichnis. Immer zuerst ausführen.",
    "bueroring":          "Büroring komplett: Download (~470 MB) → Merge+Keywords → Bestand → Upload auf Brickfox+Mercateo.",
    "bueroring_merge":    "Nur Merge ohne Download. Nützlich wenn Download erfolgreich war aber Merge fehlgeschlagen ist.",
    "bueroring_bestand":  "Nur Bestandsdaten: Excel patchen + CSV-Exporte für Brickfox ERP und Exchange.",
    "softcarrier":        "Softcarrier komplett: Download → Feature-Merge → Brickfox-Upload. Bilder SEPARAT (nächster Task).",
    "softcarrier_merge":  "Nur Merge ohne Download. Fallback wenn Download OK aber Merge fehlgeschlagen.",
    "softcarrier_bilder": "Nur geänderte Bilder auf Allago + OfficeXL hochladen (Delta: typisch 200-500 statt 61.000).",
    "nordwest":           "Nordwest: 3 XMLs herunterladen + UDX-Konvertierung + KIP-CSV + Brickfox-Upload.",
    "systeam":            "Systeam: nur Download. Aktuell inaktiv (fehlende Preise).",
    "soennecken":         "Soennecken: nur Download. Aktuell inaktiv (keine Datenlieferung).",
    "bmecat_merge":       "Manueller Merge-Trigger: direkt steuern welche Dateien zusammengeführt werden.",
    "bestandsdaten":      "Nur Availability-CSV für Mercateo erzeugen, ohne Download.",
    "cleanup_logs":       "Alte Log-Dateien und Export-CSVs (>30 Tage) löschen.",
    "sanity_check":       "Datenqualität prüfen + Cross-Supplier-Vergleich. Einmal wöchentlich empfohlen.",
    "dashboard":          "HTML-Dashboard aus letztem Sanity-Report generieren. Im Browser öffnen.",
}
