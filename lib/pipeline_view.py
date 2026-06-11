# lib/pipeline_view.py – Interaktiver Pipeline-Explorer
#
# Zeigt die Verarbeitungspipeline als klickbares Ablaufdiagramm.
# Jede Stufe öffnet ein Detailpanel mit Erklärung + Konfig-Datei.

import tkinter as tk
from tkinter import ttk

_FONT      = ("Segoe UI", 9)
_FONT_SM   = ("Segoe UI", 8)
_FONT_HEAD = ("Segoe UI Semibold", 10)
_FONT_MONO = ("Consolas", 8)
_FONT_BOLD = ("Segoe UI Semibold", 9)

# ── Pipeline-Stufen Definition ────────────────────────────────────────────────

PIPELINE = [
    {
        "id": "download",
        "label": "Download",
        "sub": "FTP / SFTP",
        "color": "#4a6fa5",
        "icon": "⬇",
        "desc": (
            "Das Tool verbindet sich per FTP oder SFTP mit dem Lieferanten-Server\n"
            "und lädt die aktuellen Katalog-Dateien herunter.\n\n"
            "Was heruntergeladen wird (je nach Lieferant):\n"
            "  • Büroring:    bueroring.xml (~470 MB), BESTAND.xlsx\n"
            "  • Softcarrier: soft-carrier.xml (~280 MB), DATA.CSV, HERSTINFO.CSV\n"
            "  • Nordwest:    arbeitsschutz.zip, werkstatt.zip, werkzeugtechnik.zip\n\n"
            "Retry: 3 Versuche mit 30 s Pause bei Verbindungsabbruch.\n"
            "Hash-Check: bereits aktuelle Dateien werden nicht neu heruntergeladen."
        ),
        "files": ["supplier_config.yaml"],
    },
    {
        "id": "transform",
        "label": "Transform",
        "sub": "Merge / FNAME / FUSAGE",
        "color": "#6b5b95",
        "icon": "⚙",
        "desc": (
            "Rohe BMEcat-XMLs werden aufbereitet bevor sie in die DB wandern.\n\n"
            "Schritte (in dieser Reihenfolge):\n"
            "  1. Merge         – Mehrere Quelldateien zu einer XML zusammenführen\n"
            "                     (Büroring: 2 XMLs + ECLASS-Features + Keywords)\n"
            "                     (Softcarrier: TAB-Features + GPSR-Daten)\n"
            "                     (Nordwest: UDX-Felder → ARTICLE_FEATURES)\n"
            "  2. FNAME-Rename  – Feature-Namen normalisieren\n"
            "                     (z. B. 'Strichstaerke' → 'Strichstärke')\n"
            "  3. FVALUE-Rename – Feature-Werte normalisieren\n"
            "  4. FUSAGE setzen – Variantenrelevante Features markieren (=3)\n"
            "  5. Dedup         – Doppelte Features innerhalb eines Artikels entfernen\n\n"
            "Output: bereinigte XML-Datei pro Lieferant."
        ),
        "files": [
            "fname_renames.csv",
            "fvalue_renames.csv",
            "fusage_3_features.csv",
        ],
    },
    {
        "id": "import",
        "label": "DB-Import",
        "sub": "SQLite / article_db",
        "color": "#2e7d32",
        "icon": "🗄",
        "desc": (
            "Die transformierten XMLs werden in die SQLite-Datenbank importiert.\n\n"
            "Was passiert:\n"
            "  • Artikel mit SUPPLIER_AID (BMEcat 1.2) als Schlüssel\n"
            "  • content_hash-Vergleich: nur echte Änderungen bekommen neues\n"
            "    last_changed-Datum → nur diese Artikel werden exportiert\n"
            "  • Katalogbaum aus CATALOG_STRUCTURE importiert\n"
            "  • ARTICLE_TO_CATALOGGROUP_MAP verknüpft Artikel mit Kategorien\n"
            "  • URL-Bereinigung: MIME_SOURCE 'https://...' → 'dateiname.jpg'\n"
            "  • Stale-Cleanup: Artikel die nicht mehr im Katalog sind, werden\n"
            "    entfernt und in weggefallen_*.csv dokumentiert\n\n"
            "Backup: nach jedem Import automatisch nach backups/ kopiert (7 Tage)."
        ),
        "files": [],
        "note": "article_db.sqlite  |  backups/article_db_YYYYMMDD.sqlite",
    },
    {
        "id": "postprocess",
        "label": "Post-Processing",
        "sub": "7 Stufen vor Export",
        "color": "#e65100",
        "icon": "🔧",
        "desc": (
            "Wird beim Export auf jeden Artikel angewendet. Reihenfolge:"
        ),
        "files": [],
        "substeps": [
            {
                "nr": "1",
                "label": "Blacklist",
                "color": "#b71c1c",
                "desc": "Artikel überspringen die nicht exportiert werden sollen.\nGlob-Wildcards: *GRATIS*, BMCLSK2025T1, NDW9000469050",
                "file": "postprocess_blacklist.csv",
            },
            {
                "nr": "2",
                "label": "EAN-Dedup",
                "color": "#4a148c",
                "desc": "Wenn mehrere Lieferanten dieselbe EAN haben:\nder Lieferant mit der kleineren Prioritätsnummer gewinnt.\nBRG=1 > SOC=2 > NDW=3,4,5",
                "file": "supplier_priority.csv",
            },
            {
                "nr": "3",
                "label": "Preisformeln",
                "color": "#1a237e",
                "desc": "Per-Artikel Aufschlag auf den net_list-Preis.\nSOC: ~73K Artikel, Faktoren 1.2–1.7\nFormel: *1.5 → round(net_list * 1.5, 2)\nSetzt auch to_type=nrp und Gültigkeitsdatum.",
                "file": "postprocess_prices.csv",
            },
            {
                "nr": "4",
                "label": "Preis-Typ",
                "color": "#0d47a1",
                "desc": "Globale Preis-Typ-Konvertierung pro Lieferant.\nBRG: net_list → nrp, date_from=2024-01-01, +365 Tage",
                "file": "postprocess_price_types.csv",
            },
            {
                "nr": "5",
                "label": "MIME & Refs",
                "color": "#1b5e20",
                "desc": "MIME-Zwecke korrigieren:\n  Handsatzseite → others\n  T_*.pdf → override_generated_product_datasheet\n  Produktdatenblatt*.pdf (BRG) → override_datasheet\nReferenztypen: consists_of/accessories/followup → others",
                "file": "postprocess_media_global.csv",
            },
            {
                "nr": "6",
                "label": "Plausibilität",
                "color": "#4e342e",
                "desc": "Preise prüfen:\n  Preis ≤ 0  → Warnung im Log + Mail\n  Preis > 5000 → Debug-Log\nSOC-Artikel ohne Preisregel erhalten den net_list-Preis.",
                "file": None,
            },
            {
                "nr": "7",
                "label": "Katalog / Crosssell",
                "color": "#33691e",
                "desc": "Per-Artikel Kategorie-Override.\nCrossell-Verbindungen ergänzen.\nKatalog-IDs beim Export umbenennen.",
                "file": "postprocess_categories.csv",
            },
        ],
    },
    {
        "id": "export",
        "label": "Export",
        "sub": "VENDOSYS_CAT XML",
        "color": "#00695c",
        "icon": "📤",
        "desc": (
            "Jeder Artikel wird als einzelne VENDOSYS_CAT XML-Datei geschrieben.\n\n"
            "Was der Exporter macht:\n"
            "  • Präfix voranstellen: MIME_SOURCE, ART_ID_TO, CATALOG_SUB_GROUP_ID\n"
            "    (NDW_, SOC_, BRG_ je nach Lieferant)\n"
            "  • price_type immer als 'net_customer' schreiben\n"
            "  • ARTICLE_TO_CATALOGGROUP_MAP mit korrektem ART_ID (mit Präfix)\n"
            "  • Atomarer Export: erst Staging-Dir, dann os.replace() ins Ziel\n\n"
            "Dateinamen: {product_id}_{timestamp}.xml\n"
            "Export-Verzeichnis: export_vendosys/ (konfigurierbar in config.py)"
        ),
        "files": [],
        "note": "export_vendosys/{product_id}_{timestamp}.xml",
    },
]


# ── Widget ────────────────────────────────────────────────────────────────────

class PipelineView(tk.Frame):
    """
    Interaktiver Pipeline-Explorer.
    Klick auf eine Stufe → Detailpanel unten aufklappen.
    """

    def __init__(self, parent, colors: dict, open_file_cb=None):
        c = colors
        super().__init__(parent, bg=c["BG"])
        self._C           = c
        self._open_file   = open_file_cb   # Callback zum Öffnen im Editor
        self._active_step = None
        self._active_sub  = None
        self._step_btns   = {}   # id → Button
        self._sub_btns    = {}   # (step_id, nr) → Button

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self._build_pipeline_bar()
        self._build_detail_panel()

    # ── Pipeline-Bar (obere Zeile) ────────────────────────────────────────────

    def _build_pipeline_bar(self):
        c   = self._C
        bar = tk.Frame(self, bg=c["BG2"], pady=10)
        bar.grid(row=0, column=0, sticky="ew")
        bar.columnconfigure(tuple(range(len(PIPELINE) * 2 - 1)), weight=0)

        for i, step in enumerate(PIPELINE):
            # Pfeil zwischen Stufen
            if i > 0:
                tk.Label(bar, text=" → ", bg=c["BG2"],
                         fg=c["FG_DIM"], font=_FONT_HEAD).grid(
                    row=0, column=i * 2 - 1, padx=0)

            btn = tk.Button(
                bar,
                text=f"{step['icon']}  {step['label']}\n{step['sub']}",
                bg=step["color"], fg="#ffffff",
                activebackground=step["color"],
                activeforeground="#ffffff",
                font=_FONT_BOLD, relief="flat", bd=0,
                cursor="hand2", padx=12, pady=8,
                justify="center",
                command=lambda s=step: self._show_step(s))
            btn.grid(row=0, column=i * 2, padx=4)
            self._step_btns[step["id"]] = btn

        tk.Label(bar, text="  Klick auf eine Stufe für Details  ",
                 bg=c["BG2"], fg=c["FG_DIM"], font=_FONT_SM).grid(
            row=1, column=0, columnspan=len(PIPELINE) * 2, pady=(4, 0))

    # ── Detail-Panel (untere Hälfte) ──────────────────────────────────────────

    def _build_detail_panel(self):
        c = self._C
        self._detail = tk.Frame(self, bg=c["BG"])
        self._detail.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)
        self._detail.columnconfigure(0, weight=1)
        self._detail.rowconfigure(0, weight=1)

        # Platzhalter
        self._placeholder = tk.Label(
            self._detail,
            text="← Stufe auswählen um Details zu sehen",
            bg=c["BG"], fg=c["FG_DIM"], font=_FONT)
        self._placeholder.grid(row=0, column=0)

        self._content_frame = None

    def _show_step(self, step: dict):
        c = self._C
        self._active_step = step["id"]
        self._active_sub  = None

        # Highlight aktiver Button
        for sid, btn in self._step_btns.items():
            s = next(s for s in PIPELINE if s["id"] == sid)
            if sid == step["id"]:
                btn.config(relief="sunken", bd=2)
            else:
                btn.config(relief="flat", bd=0)

        # Content-Frame leeren
        if self._content_frame:
            self._content_frame.destroy()
        self._placeholder.grid_forget()

        self._content_frame = tk.Frame(self._detail, bg=c["BG"])
        self._content_frame.grid(row=0, column=0, sticky="nsew")
        self._content_frame.columnconfigure(1, weight=1)
        self._content_frame.rowconfigure(0, weight=1)

        # Linke Spalte: Beschreibung
        left = tk.Frame(self._content_frame, bg=c["BG2"],
                        padx=12, pady=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        tk.Label(left, text=f"{step['icon']}  {step['label']}",
                 bg=c["BG2"], fg=c["FG"], font=_FONT_HEAD,
                 anchor="w").pack(fill="x")
        tk.Label(left, text=step["sub"], bg=c["BG2"],
                 fg=c["FG_DIM"], font=_FONT_SM,
                 anchor="w").pack(fill="x", pady=(0, 8))

        desc_txt = tk.Text(left, bg=c["BG2"],
                           fg=c.get("FG_INPUT", c["FG"]),
                           font=_FONT, wrap="word",
                           relief="flat", bd=0, height=10, width=42,
                           state="normal")
        desc_txt.insert("end", step["desc"])
        desc_txt.config(state="disabled")
        desc_txt.pack(fill="both", expand=True)

        # Config-Dateien Buttons
        if step.get("files"):
            tk.Label(left, text="Konfigurations-Dateien:",
                     bg=c["BG2"], fg=c["FG_DIM"],
                     font=_FONT_SM).pack(anchor="w", pady=(8, 2))
            for fname in step["files"]:
                self._file_btn(left, fname)

        if step.get("note"):
            tk.Label(left, text=step["note"],
                     bg=c["BG2"], fg=c["FG_DIM"],
                     font=_FONT_MONO, wraplength=280,
                     justify="left").pack(anchor="w", pady=(6, 0))

        # Rechte Spalte: Sub-Steps oder leer
        right = tk.Frame(self._content_frame, bg=c["BG"])
        right.grid(row=0, column=1, sticky="nsew")

        if step.get("substeps"):
            self._build_substeps(right, step)

    def _build_substeps(self, parent: tk.Frame, step: dict):
        c = self._C
        tk.Label(parent, text="Reihenfolge der Verarbeitungsschritte:",
                 bg=c["BG"], fg=c["FG_DIM"],
                 font=_FONT_SM).pack(anchor="w", padx=6, pady=(6, 2))

        canvas = tk.Canvas(parent, bg=c["BG"], highlightthickness=0)
        vsb    = ttk.Scrollbar(parent, orient="vertical",
                               command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(6, 0))
        vsb.pack(side="right", fill="y")

        inner = tk.Frame(canvas, bg=c["BG"])
        canvas_window = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e: canvas.configure(
                       scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(
                        canvas_window, width=e.width))

        self._sub_btns.clear()
        for j, sub in enumerate(step["substeps"]):
            row = tk.Frame(inner, bg=c["BG"])
            row.pack(fill="x", pady=2, padx=4)

            nr_lbl = tk.Label(row, text=sub["nr"],
                              bg=sub["color"], fg="#fff",
                              font=_FONT_BOLD, width=2,
                              relief="flat", padx=6, pady=4)
            nr_lbl.pack(side="left")

            btn = tk.Button(
                row, text=f"  {sub['label']}",
                bg=c["BG3"],
                fg=c.get("FG_INPUT", c["FG"]),
                activebackground=c["ACCENT"],
                activeforeground="#fff",
                font=_FONT, relief="flat", bd=0,
                anchor="w", cursor="hand2", padx=6, pady=4,
                command=lambda s=sub: self._show_substep(s))
            btn.pack(side="left", fill="x", expand=True)

            if sub.get("file"):
                file_label = tk.Label(
                    row, text=sub["file"],
                    bg=c["BG3"], fg=c["ACCENT"],
                    font=_FONT_MONO, cursor="hand2",
                    padx=6, pady=4)
                file_label.pack(side="right")
                file_label.bind("<Button-1>",
                                lambda e, f=sub["file"]: self._open_file and
                                self._open_file(f))

            if j < len(step["substeps"]) - 1:
                tk.Label(inner, text="    ↓", bg=c["BG"],
                         fg=c["FG_DIM"], font=_FONT_SM).pack(
                    anchor="w", padx=4)

            self._sub_btns[(step["id"], sub["nr"])] = btn

        # Detail-Box für Sub-Step
        self._sub_detail = tk.Frame(inner, bg=c["BG2"],
                                    padx=10, pady=8)
        self._sub_detail_txt = tk.Text(
            self._sub_detail, bg=c["BG2"],
            fg=c.get("FG_INPUT", c["FG"]),
            font=_FONT, wrap="word", relief="flat",
            bd=0, height=5, state="disabled")
        self._sub_detail_txt.pack(fill="both", expand=True)
        self._sub_file_btn_frame = tk.Frame(self._sub_detail, bg=c["BG2"])
        self._sub_file_btn_frame.pack(fill="x", pady=(4, 0))

    def _show_substep(self, sub: dict):
        c = self._C
        # Alle Sub-Buttons zurücksetzen
        for (sid, nr), btn in self._sub_btns.items():
            btn.config(bg=c["BG3"], fg=c.get("FG_INPUT", c["FG"]))
        # Aktiven hervorheben
        key = (self._active_step, sub["nr"])
        if key in self._sub_btns:
            self._sub_btns[key].config(bg=c["ACCENT"], fg="#fff")

        # Detail-Box einblenden
        self._sub_detail.pack(fill="x", padx=4, pady=(0, 4))
        self._sub_detail_txt.config(state="normal")
        self._sub_detail_txt.delete("1.0", "end")
        self._sub_detail_txt.insert("end", sub["desc"])
        self._sub_detail_txt.config(state="disabled")

        for w in self._sub_file_btn_frame.winfo_children():
            w.destroy()
        if sub.get("file"):
            self._file_btn(self._sub_file_btn_frame, sub["file"])

    def _file_btn(self, parent: tk.Frame, fname: str):
        c = self._C
        btn = tk.Button(
            parent, text=f"  📄 {fname}",
            bg=c["BG3"],
            fg=c.get("FG_INPUT", c["FG"]),
            activebackground=c["ACCENT"], activeforeground="#fff",
            font=_FONT_MONO, relief="flat", bd=0,
            cursor="hand2", padx=6, pady=3, anchor="w",
            command=lambda f=fname: self._open_file and self._open_file(f))
        btn.pack(anchor="w", pady=1)
