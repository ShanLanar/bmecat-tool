# lib/config_tab.py – Konfigurationseditor-Reiter
#
# Zeigt alle Konfigurations-CSVs und YAML-Dateien in einem Editor.
# Große Dateien (> MAX_BYTES) werden nur teilweise angezeigt, aber vollständig
# gespeichert (postprocess_prices.csv mit 73K Zeilen z. B. nicht manuell editieren).

import os
import tkinter as tk
from tkinter import ttk, messagebox

_FONT      = ("Segoe UI", 10)
_FONT_MONO = ("Consolas", 9)
_FONT_SM   = ("Segoe UI", 8)
_FONT_HEAD = ("Segoe UI Semibold", 10)

MAX_DISPLAY_BYTES = 64_000   # ab hier: Datei wird nur teilweise angezeigt


# ── Konfigurationsdateien mit Beschreibungen ─────────────────────────────────

CONFIG_FILES = [
    # (Dateiname, Kurztitel, Ausführliche Beschreibung)
    (
        "supplier_config.yaml",
        "Lieferanten-Konfiguration",
        """\
Zentrale Konfigurationsdatei für alle Lieferanten.

Für jeden Lieferanten (Büroring, Nordwest, Softcarrier …) sind hier
eingetragen:
  • FTP-/SFTP-Host, Port, Benutzer, Passwort
  • Pfade auf dem Server (Download-Verzeichnis)
  • Lokale Zielpfade
  • Präfix (BRG / NDW / SOC) – wird MIME-Source, ART_ID_TO und
    CATALOG_SUB_GROUP_ID vorangestellt
  • Upload-Ziele (Brickfox-API-URL, Credentials)
  • enabled: true/false – deaktiviert einen Lieferanten komplett

Format: YAML.  Nach Änderung muss das Tool neu gestartet werden.
"""
    ),
    (
        "postprocess_blacklist.csv",
        "Artikel-Blacklist",
        """\
Liste von Artikeln, die beim Export IMMER übersprungen werden.

Einträge:
  • Einfache Artikel-ID (Supplier-AID, ohne Präfix): BMCLSK2025T1
  • Mit Präfix (product_id):                         BRGBMCLSK2025T1
  • Glob-Wildcards erlaubt:                          *GRATIS*

Kommentarzeilen beginnen mit #.
Beim Export werden übereinstimmende Artikel nicht in den VENDOSYS-XML
geschrieben.  Der gezählte Wert "N Blacklist" im Export-Log zeigt wie viele
Artikel übersprungen wurden.

Typische Einträge:
  • Artikel die dauerhaft nicht lieferbar sind
  • Werbeware / Gratisartikel
  • Saisonartikel die außer Saison nicht gelistet werden sollen
"""
    ),
    (
        "postprocess_fname_blacklist.csv",
        "FNAME-Blacklist (Feature-Filter)",
        """\
Liste von FNAMEs (Feature-Namen), die beim Export IMMER oder bedingt
aus den Artikeln entfernt werden – z. B. interne/redaktionelle Felder,
die nicht im Shop angezeigt werden sollen.

Spalten:
  fname   – Feature-Name (Wildcards * und ? erlaubt, z. B. *intern*)
  fvalue  – optional. Leer = Feature immer entfernen.
            Gesetzt = nur entfernen wenn FVALUE genau diesem Wert
            entspricht (z. B. "Be Green" nur wenn Wert = CAA017/Nein).

ECLASS-Booleschwerte (CAA016/CAA017) werden sowohl als Rohcode als
auch als bereits übersetzter Text (Ja/Nein) erkannt.

Kommentarzeilen beginnen mit #.
Gross-/Kleinschreibung wird bei fname und fvalue ignoriert.
"""
    ),
    (
        "postprocess_prices.csv",
        "Preisformeln (SOC ~73 K Artikel)",
        """\
Per-Artikel-Preisformeln.  Wird VOR dem Export auf den net_list-Preis
aus dem BMEcat angewendet.

Spalten:
  supplier          – Lieferant (z. B. Softcarrier); leer = alle
  product_id_pattern – product_id (mit Präfix, Glob erlaubt)
  formula           – Rechenformel:  *1.5  |  +2.00  |  fixed:9.99
  to_type           – Preistyp im Export-XML (z. B. nrp)
  date_from         – Gültig-ab-Datum
  date_to           – Gültig-bis-Datum

Softcarrier-Einträge (73 K Zeilen, generiert aus SQL-Skript):
  Faktor 1.08–1.70 je nach Artikel.  Nicht manuell bearbeiten –
  bei Preisänderungen das SQL-Skript neu einspielen.

Büroring-Preise laufen über postprocess_price_types.csv (globale Regel).

⚠  Diese Datei ist zu groß für die vollständige Anzeige im Editor.
   Die ersten 200 Zeilen werden angezeigt.
"""
    ),
    (
        "postprocess_price_types.csv",
        "Preistyp-Konvertierung",
        """\
Konvertiert Preistypen global pro Lieferant.

Spalten:
  supplier              – Lieferant (leer = alle)
  from_type             – Quelltyp (z. B. net_list)
  to_type               – Zieltyp  (z. B. nrp)
  date_from             – Gültig ab (ISO-Datum, leer = kein Eintrag)
  date_to_offset_days   – Gültig bis = heute + N Tage

Aktuell konfiguriert:
  Büroring:  net_list → nrp,  ab 2024-01-01,  +365 Tage ab heute

Der Export schreibt immer price_type="net_customer" im VENDOSYS-XML.
Diese Konvertierung setzt nur den internen DB-Typ für die Zwischenbuchführung.
"""
    ),
    (
        "postprocess_media_global.csv",
        "MIME-Regeln global",
        """\
Ändert den MIME-Zweck (purpose) von Dateien anhand von Mustern –
gilt für alle Artikel.

Spalten:
  supplier        – Lieferant (leer = alle)
  source_pattern  – Glob auf mime_source (z. B. T_*.pdf)
  old_purpose     – Nur umbenennen wenn purpose diesem Wert entspricht
                    (leer = immer)
  new_purpose     – Neuer Zweck-Wert

Aktuelle Regeln:
  Handsatzseite (NDW)    → others
  T_*.pdf     (NDW)      → override_generated_product_datasheet
  Produktdatenblatt*.pdf (BRG) → override_generated_product_datasheet

Diese Datei wird für wiederkehrende strukturelle Korrekturen genutzt,
die der Lieferant falsch oder inkonsistent ausliefert.
"""
    ),
    (
        "postprocess_media.csv",
        "MIME-Overrides per Artikel",
        """\
Manuelle MIME-Korrekturen für einzelne Artikel.

Spalten:
  product_id      – product_id (mit Präfix)
  mime_source     – Dateiname des Bildes/Dokuments
  new_purpose     – Neuer Zweck-Wert

Wird nach den globalen Regeln (postprocess_media_global.csv) angewendet
und überschreibt deren Ergebnis für den jeweiligen Artikel.

Wird nur selten benötigt – für seltene Einzelfälle wo ein Lieferant
einen falschen MIME-Zweck für einen bestimmten Artikel ausliefert.
"""
    ),
    (
        "postprocess_reference_types.csv",
        "Referenztyp-Umbenennung",
        """\
Benennt ARTICLE_REFERENCE-Typen um.

Spalten:
  from_type   – Quell-Typ (z. B. consists_of)
  to_type     – Ziel-Typ  (z. B. others)

Aktuell konfiguriert:
  consists_of  → others
  accessories  → others
  followup     → others

Hintergrund: Brickfox/VENDOSYS erkennt nur bestimmte Referenztypen.
Nicht unterstützte Typen werden zu 'others' umgeschrieben damit sie
im System nicht verworfen werden.
"""
    ),
    (
        "postprocess_categories.csv",
        "Katalog-Zuordnung (Override)",
        """\
Weist einzelnen Artikeln manuell eine andere Kataloggruppe zu.

Spalten:
  product_id          – product_id (mit Präfix)
  catalog_group_id    – Neue Root-Katalog-ID
  catalog_sub_group_id – Neue Sub-Katalog-ID

Wird verwendet wenn ein Lieferant einen Artikel in der falschen
Kategorie ausliefert und eine manuelle Korrektur nötig ist.
Die hier eingetragene Kategorie überschreibt die aus dem BMEcat.
"""
    ),
    (
        "postprocess_crosssell.csv",
        "Crosssell-Verbindungen",
        """\
Fügt Crosssell-Referenzen zwischen Artikeln ein (oder ergänzt fehlende).

Spalten:
  from_product_id  – Quell-Artikel (product_id mit Präfix)
  to_product_id    – Ziel-Artikel  (product_id mit Präfix)
  ref_type         – Referenztyp   (z. B. similar, accessories)

Bisher leer – wird bei Bedarf befüllt wenn manuell Crosssell-Links
gepflegt werden sollen die nicht im BMEcat enthalten sind.
"""
    ),
    (
        "postprocess_suffixes.csv",
        "AID-Suffix",
        """\
Hängt einen Suffix an die SUPPLIER_AID im Export an.

Spalten:
  supplier  – Lieferant
  suffix    – Anzuhängender String

Aktuell leer.  Wird benötigt wenn ein Lieferant dieselbe
supplier_pid für verschiedene Varianten verwendet und ein
Suffix zur Unterscheidung nötig ist.
"""
    ),
    (
        "postprocess_catalog_remap.csv",
        "Katalog-Neuordnung (Export)",
        """\
Benennt Katalog-IDs beim Export um (ohne die DB zu ändern).

Spalten:
  supplier      – Lieferant (leer = alle)
  old_group_id  – Bisherige group_id
  new_group_id  – Neue group_id im Export-XML

Wird angewendet NACH dem Katalogbaum-Lookup, kurz vor dem XML-Schreiben.
Nützlich wenn VENDOSYS/Brickfox andere Kategorie-IDs erwartet als
im BMEcat geliefert werden, ohne die importierten Daten zu verändern.
"""
    ),
    (
        "fusage_3_features.csv",
        "FUSAGE=3 Feature-Liste",
        """\
Liste von Feature-Namen (FNAME) die beim Export FUSAGE=3 bekommen.

FUSAGE-Bedeutung im VENDOSYS-Schema:
  1 = normales Merkmal (wird angezeigt, nicht variantenrelevant)
  3 = variantenrelevant  (Auswahl-Dropdown im Shop, z. B. Farbe, Größe)

Alle anderen Features, die NICHT in dieser Liste stehen, bekommen FUSAGE=1.

~150 Feature-Namen sind eingetragen (Farbe, Strichstärke, Grammatur etc.).
Format: Ein Feature-Name pro Zeile, Kommentarzeilen mit #.
"""
    ),
    (
        "supplier_priority.csv",
        "EAN-Dedup-Priorität",
        """\
Bestimmt welcher Lieferant 'gewinnt' wenn mehrere Lieferanten
denselben Artikel (gleiche EAN) ausliefern.

Spalten:
  supplier   – Lieferant
  priority   – Numerisch, kleiner = höhere Priorität

Aktuell:
  BRG (Büroring)    → 1  (höchste Priorität)
  SOC (Softcarrier) → 2
  NDW (Nordwest)    → 3/4/5

Wenn zwei Lieferanten dieselbe EAN haben, wird der Artikel des Lieferanten
mit der kleineren Prioritätszahl exportiert, der andere wird unterdrückt.
"""
    ),
    (
        "udx_fields.csv",
        "UDX → Feature-Mapping (Nordwest)",
        """\
Steuert welche UDX-Felder aus Nordwest-Artikeln als reguläre
ARTICLE_FEATURES im Export erscheinen und welche als
USER_DEFINED_EXTENSIONS bleiben.

Spalten:
  fname       – Feature-Name (FNAME) wie er in der DB steht
  udx_key     – UDX-Schlüssel für den Export (z. B. LIEFNR)

Nordwest liefert viele proprietäre UDX-Felder (UDX.LIEFNR,
UDX.BEZUGSQUELLE etc.).  Diese Datei ist der Schlüssel der festlegt
welche davon im VENDOSYS-Export als <UDX.SCHLUESSEL> erscheinen.
"""
    ),
    (
        "fname_renames.csv",
        "FNAME-Umbenennung",
        """\
Benennt Feature-Namen (FNAME) beim Import um – BEVOR sie in die DB
geschrieben werden.

Spalten:
  old_fname   – Originalname aus dem BMEcat
  new_fname   – Neuer Name in der DB / im Export

Normalisiert inkonsistente Lieferantennamen
(z. B. 'Strichstaerke' → 'Strichstärke').
Änderungen hier erfordern einen Neu-Import damit die DB aktualisiert wird.
"""
    ),
    (
        "fvalue_renames.csv",
        "FVALUE-Umbenennung",
        """\
Benennt Feature-Werte (FVALUE) beim Import um.

Spalten:
  fname       – Feature-Name (nur für diesen FNAME anwenden)
  old_fvalue  – Originalwert aus dem BMEcat
  new_fvalue  – Neuer Wert in der DB / im Export

Beispiele:
  Farbe, 'blau (hell)' → 'hellblau'
  Ja/Nein-Normalisierung: 'ja' → 'Ja', '1' → 'Ja'

Änderungen erfordern Neu-Import.
"""
    ),
]


# ── Config-Tab ────────────────────────────────────────────────────────────────

class ConfigTab:
    def __init__(self, parent: tk.Frame, app, colors: dict):
        self._parent  = parent
        self._app     = app
        self._C       = colors
        self._current = None   # aktuell geladene Datei (voller Pfad)
        self._dirty   = False
        self._full_content: str | None = None  # Original wenn Datei abgeschnitten

        parent.columnconfigure(0, weight=0)
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(0, weight=1)

        self._build_file_list(parent)
        self._build_editor(parent)

    # ── Dateiliste ────────────────────────────────────────────────────────────

    def _build_file_list(self, parent):
        c   = self._C
        frm = tk.Frame(parent, bg=c["BG2"], width=260)
        frm.grid(row=0, column=0, sticky="nsew")
        frm.grid_propagate(False)
        frm.rowconfigure(1, weight=1)
        frm.columnconfigure(0, weight=1)

        tk.Label(frm, text="Konfigurationsdateien", bg=c["BG2"],
                 fg=c["FG"], font=_FONT_HEAD,
                 pady=8).grid(row=0, column=0, sticky="ew")

        lb_frame = tk.Frame(frm, bg=c["BG2"])
        lb_frame.grid(row=1, column=0, sticky="nsew")
        lb_frame.rowconfigure(0, weight=1)
        lb_frame.columnconfigure(0, weight=1)

        self._listbox = tk.Listbox(
            lb_frame, bg=c["BG3"],
            fg=c.get("FG_INPUT", c["FG"]),
            selectbackground=c["ACCENT"],
            selectforeground="#ffffff",
            activestyle="none",
            font=_FONT_SM, bd=0, relief="flat",
            highlightthickness=0)
        vsb = ttk.Scrollbar(lb_frame, orient="vertical",
                            command=self._listbox.yview)
        self._listbox.configure(yscrollcommand=vsb.set)
        self._listbox.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        self._listbox.insert("end", "  ▶  Pipeline-Übersicht")
        for fname, title, _ in CONFIG_FILES:
            self._listbox.insert("end", f"  {title}")

        self._listbox.bind("<<ListboxSelect>>", self._on_select)

    # ── Editor ────────────────────────────────────────────────────────────────

    def _build_editor(self, parent):
        c   = self._C
        frm = tk.Frame(parent, bg=c["BG"])
        frm.grid(row=0, column=1, sticky="nsew")
        frm.rowconfigure(2, weight=1)
        frm.columnconfigure(0, weight=1)

        # Titelzeile
        self._title_lbl = tk.Label(
            frm, text="← Datei auswählen", bg=c["BG2"],
            fg=c["FG"], font=_FONT_HEAD, anchor="w",
            padx=10, pady=6)
        self._title_lbl.grid(row=0, column=0, columnspan=2, sticky="ew")

        # Beschreibungs-Box
        self._desc_txt = tk.Text(
            frm, height=6, bg=c["BG2"],
            fg=c.get("FG_INPUT", c["FG"]),
            font=_FONT_SM, wrap="word", relief="flat",
            bd=6, state="disabled",
            insertbackground=c.get("FG_INPUT", c["FG"]))
        self._desc_txt.grid(row=1, column=0, columnspan=2, sticky="ew",
                            padx=2, pady=(0, 2))

        # Text-Editor
        edit_frm = tk.Frame(frm, bg=c["BG"])
        edit_frm.grid(row=2, column=0, columnspan=2, sticky="nsew",
                      padx=2, pady=2)
        edit_frm.rowconfigure(0, weight=1)
        edit_frm.columnconfigure(0, weight=1)

        self._editor = tk.Text(
            edit_frm, bg=c["BG3"],
            fg=c.get("FG_INPUT", c["FG"]),
            insertbackground=c.get("FG_INPUT", c["FG"]),
            font=_FONT_MONO, wrap="none", relief="flat",
            bd=6, undo=True)
        vsb = ttk.Scrollbar(edit_frm, orient="vertical",
                            command=self._editor.yview)
        hsb = ttk.Scrollbar(edit_frm, orient="horizontal",
                            command=self._editor.xview)
        self._editor.configure(yscrollcommand=vsb.set,
                               xscrollcommand=hsb.set)
        self._editor.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self._editor.bind("<<Modified>>", self._on_edit)

        # Buttons
        btn_frm = tk.Frame(frm, bg=c["BG2"], pady=6)
        btn_frm.grid(row=3, column=0, columnspan=2, sticky="ew")

        def btn(parent, text, cmd, color=None):
            b = tk.Button(
                parent, text=text, command=cmd,
                font=_FONT_SM,
                bg=color or c["BG3"], fg=c["FG"],
                activebackground=c["BG"],
                activeforeground=c["FG"],
                relief="flat", bd=0, cursor="hand2",
                padx=10, pady=4)
            b.pack(side="left", padx=4)
            return b

        btn(btn_frm, "Neu laden",  self._reload_file)
        self._save_btn = btn(btn_frm, "Speichern", self._save_file,
                             color=c["GREEN"])
        self._save_btn.config(fg="#fff")
        btn(btn_frm, "🔐 Passwort verschlüsseln", self._encrypt_password)

        self._status_lbl = tk.Label(btn_frm, text="", bg=c["BG2"],
                                    fg=c["FG_DIM"], font=_FONT_SM)
        self._status_lbl.pack(side="right", padx=10)

        self._warn_lbl = tk.Label(frm, text="", bg=c["YELLOW"],
                                  fg="#222", font=_FONT_SM, pady=3)
        # wird erst eingeblendet wenn nötig

    # ── Datei auswählen ───────────────────────────────────────────────────────

    def _on_select(self, _event=None):
        sel = self._listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx == 0:
            self._show_pipeline()
            return
        self._hide_pipeline()
        fname, title, desc = CONFIG_FILES[idx - 1]

        if self._dirty:
            if not messagebox.askyesno(
                    "Ungespeicherte Änderungen",
                    "Änderungen verwerfen und andere Datei öffnen?",
                    parent=self._parent):
                return

        try:
            import config as _cfg
            path = os.path.join(_cfg.BASE_DIR, fname)
        except Exception:
            path = os.path.join('.', fname)

        self._current = path
        self._full_content = None
        self._title_lbl.config(text=f"  {fname}")

        # Beschreibung
        self._desc_txt.config(state="normal")
        self._desc_txt.delete("1.0", "end")
        self._desc_txt.insert("end", desc.strip())
        self._desc_txt.config(state="disabled")

        self._load_file(path)

    def open_file_in_editor(self, fname: str):
        """Öffnet eine Konfigurationsdatei aus dem Pipeline-Explorer im Editor."""
        for i, (f, title, _) in enumerate(CONFIG_FILES):
            if f == fname:
                self._listbox.selection_clear(0, "end")
                self._listbox.selection_set(i + 1)
                self._listbox.see(i + 1)
                self._on_select()
                return

    def _show_pipeline(self):
        c = self._C
        if self._dirty:
            from tkinter import messagebox
            if not messagebox.askyesno("Änderungen verwerfen?",
                    "Ungespeicherte Änderungen verwerfen?",
                    parent=self._parent):
                return
        self._current = None
        self._dirty   = False
        self._title_lbl.config(text="  ▶  Pipeline-Übersicht")
        self._desc_txt.config(state="normal")
        self._desc_txt.delete("1.0", "end")
        self._desc_txt.insert("end",
            "Klick auf eine Pipeline-Stufe zeigt was dort passiert und "
            "welche Konfigurations-Datei sie steuert.\n"
            "Klick auf einen Dateinamen öffnet ihn direkt im Editor.")
        self._desc_txt.config(state="disabled")
        self._editor.config(state="normal")
        self._editor.delete("1.0", "end")
        self._editor.config(state="disabled")
        self._warn_lbl.grid_forget()
        self._status_lbl.config(text="")
        # Pipeline-Widget über Editor legen
        if hasattr(self, "_pw") and self._pw and self._pw.winfo_exists():
            self._pw.lift()
            self._pw.place(relx=0, rely=0, relwidth=1, relheight=1)
            return
        from lib.pipeline_view import PipelineView
        self._pw = PipelineView(self._editor.master, colors=c,
                                open_file_cb=self.open_file_in_editor)
        self._pw.place(relx=0, rely=0, relwidth=1, relheight=1)

    def _hide_pipeline(self):
        if hasattr(self, "_pw") and self._pw and self._pw.winfo_exists():
            self._pw.place_forget()

    def _load_file(self, path: str):
        c = self._C
        self._warn_lbl.grid_forget()
        self._editor.config(state="normal")
        self._editor.delete("1.0", "end")
        self._full_content = None

        if not os.path.exists(path):
            self._editor.insert("end",
                f"# Datei existiert noch nicht: {os.path.basename(path)}\n"
                f"# Einfach Inhalt eingeben und 'Speichern' klicken.\n")
            self._editor.edit_modified(False)
            self._dirty = False
            self._status_lbl.config(text="Neue Datei")
            return

        size = os.path.getsize(path)
        try:
            raw = open(path, encoding='utf-8', errors='replace').read()
        except Exception as e:
            self._editor.insert("end", f"# Fehler beim Lesen: {e}")
            self._editor.edit_modified(False)
            self._dirty = False
            return

        if size > MAX_DISPLAY_BYTES:
            # Nur ersten Teil anzeigen
            self._full_content = raw
            lines = raw.splitlines()
            preview = '\n'.join(lines[:200])
            self._editor.insert("end", preview)
            self._warn_lbl.config(
                text=f"⚠  Datei zu groß ({size//1024} KB, {len(lines):,} Zeilen)"
                     f" – nur erste 200 Zeilen sichtbar."
                     f"  Änderungen hier betreffen nur diese Zeilen."
                    .replace(',', '.'))
            self._warn_lbl.grid(row=4, column=0, columnspan=2, sticky="ew")
            self._editor.config(state="disabled")
            self._status_lbl.config(
                text=f"{size//1024} KB  |  nur lesen")
        else:
            self._editor.insert("end", raw)
            self._status_lbl.config(
                text=f"{size//1024 or '<1'} KB  |  {raw.count(chr(10))+1} Zeilen")

        self._editor.edit_modified(False)
        self._dirty = False

    def _on_edit(self, _event=None):
        if self._editor.edit_modified():
            self._dirty = True
            self._status_lbl.config(text="● Ungespeichert")

    def _reload_file(self):
        if self._current:
            if self._dirty:
                if not messagebox.askyesno(
                        "Neu laden",
                        "Änderungen verwerfen und Datei neu laden?",
                        parent=self._parent):
                    return
            self._load_file(self._current)

    def _encrypt_password(self):
        """Hilfsfunktion: Klartext-Passwort verschlüsseln und in Zwischenablage legen."""
        import tkinter.simpledialog as sd
        pw = sd.askstring("Passwort verschlüsseln",
                          "Klartext-Passwort eingeben:\n(wird als 'enc:...' in die Zwischenablage kopiert)",
                          show="*", parent=self._parent)
        if not pw:
            return
        try:
            from lib.credentials import encrypt
            enc = encrypt(pw)
            self._parent.clipboard_clear()
            self._parent.clipboard_append(enc)
            from tkinter import messagebox
            messagebox.showinfo(
                "Verschlüsselt",
                f"Verschlüsselter Wert in Zwischenablage:\n\n{enc}\n\n"
                "In supplier_config.yaml oder config.py als password-Wert eintragen.",
                parent=self._parent)
        except Exception as e:
            from tkinter import messagebox
            messagebox.showerror("Fehler", str(e), parent=self._parent)

    def _save_file(self):
        if not self._current:
            return
        if self._full_content is not None:
            messagebox.showinfo(
                "Datei zu groß",
                "Diese Datei ist zu groß für den Editor.\n"
                "Bitte direkt im Datei-Explorer bearbeiten:\n\n"
                f"{self._current}",
                parent=self._parent)
            return
        try:
            os.makedirs(os.path.dirname(self._current) or '.', exist_ok=True)
            content = self._editor.get("1.0", "end-1c")
            with open(self._current, 'w', encoding='utf-8') as f:
                f.write(content)
            self._editor.edit_modified(False)
            self._dirty = False
            size = os.path.getsize(self._current)
            self._status_lbl.config(
                text=f"Gespeichert  ✓  {size//1024 or '<1'} KB",
                fg=self._C["GREEN"])
            self._parent.after(3000, lambda: self._status_lbl.config(
                text=f"{size//1024 or '<1'} KB",
                fg=self._C["FG_DIM"]))
        except Exception as e:
            messagebox.showerror("Speicherfehler", str(e), parent=self._parent)
