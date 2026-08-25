# lib/ebay_tab.py – eBay-Tab: SKU-Liste / Bestand & Preis / Kategorie-Lernen
#
# Dedizierter Tab statt generischer Task-Buttons im Pipeline-Runner, weil dort
# unklar war, was ein Klick genau tut (welche Datei wird gelesen, was kommt
# raus). Jede Aktion öffnet einen Datei-Dialog und zeigt das Ergebnis direkt
# an. Darunter eine Ansicht der ebay_listings-Registry (SKU -> ItemID), damit
# sichtbar ist, welche SKUs das Tool schon als "bei eBay vorhanden" kennt.

import os
import threading
import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

_FONT      = ("Segoe UI", 10)
_FONT_MONO = ("Consolas", 9)
_FONT_SM   = ("Segoe UI", 8)
_FONT_HEAD = ("Segoe UI Semibold", 10)

_PAGE_SIZE = 200

_IMAGE_BASE = "https://www.officexl.de/whitelabels/officexl/images/thumbnails/zoom"

_COLS = [
    ("sku",           "SKU",             160, False),
    ("item_id",       "eBay-ItemID",     140, False),
    ("category_name", "Kategorie",       280, True),
    ("status",        "Status",           90, False),
    ("last_seen",     "Zuletzt gesehen", 140, False),
]


def _fmt_local(iso_utc: str) -> str:
    if not iso_utc:
        return ""
    try:
        dt = datetime.datetime.fromisoformat(iso_utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso_utc[:16].replace("T", " ")


class EbayTab:
    def __init__(self, parent: tk.Frame, app, colors: dict):
        self._parent   = parent
        self._app      = app
        self._C        = colors
        self._all      = []
        self._filtered = []
        self._page     = 0
        self._busy     = False

        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)

        self._build_actions(parent)
        self._build_filter(parent)
        self._build_table(parent)
        self._build_pagination(parent)

    # ── Aktionen ──────────────────────────────────────────────────────────────

    def _build_actions(self, parent):
        c   = self._C
        frm = tk.Frame(parent, bg=c["BG2"], padx=10, pady=10)
        frm.grid(row=0, column=0, sticky="ew")
        frm.columnconfigure(0, weight=1)

        def action_block(row, title, desc, btn_text, cmd):
            box = tk.Frame(frm, bg=c["BG2"])
            box.grid(row=row, column=0, sticky="ew", pady=4)
            box.columnconfigure(1, weight=1)
            btn = tk.Button(box, text=btn_text, command=cmd,
                            font=_FONT, bg=c["ACCENT"], fg="#fff",
                            activebackground=c["BG"], activeforeground=c["FG"],
                            relief="flat", bd=0, cursor="hand2",
                            padx=12, pady=6, width=22, anchor="center")
            btn.grid(row=0, column=0, sticky="nw", padx=(0, 14))
            info = tk.Frame(box, bg=c["BG2"])
            info.grid(row=0, column=1, sticky="ew")
            tk.Label(info, text=title, bg=c["BG2"], fg=c["FG"],
                     font=_FONT_HEAD, anchor="w").pack(fill="x")
            tk.Label(info, text=desc, bg=c["BG2"], fg=c["FG_DIM"],
                     font=_FONT_SM, anchor="w", justify="left",
                     wraplength=680).pack(fill="x")
            return btn

        self._btn_sku = action_block(
            0, "1) SKU-Liste verarbeiten",
            "CSV mit SKUs (eine pro Zeile) auswählen. Wird automatisch aufgeteilt: "
            "unbekannte SKU → Neuanlage-Datei, bekannte SKU mit Bestand → Revise/"
            "Reaktivierung, bekannte SKU ohne Bestand → Beenden.",
            "SKU-Liste wählen ...", self._run_sku_liste)

        self._btn_revise = action_block(
            1, "2) Bestand & Preis aktualisieren",
            "Den von eBay selbst heruntergeladenen Revise-Report (aktive Angebote) "
            "auswählen. Preis/Bestand werden aus der Artikel-DB aufgefrischt, "
            "Nullbestand landet automatisch in einer Beenden-Datei.",
            "eBay-Report wählen ...", self._run_revise_sync)

        self._btn_learn = action_block(
            2, "3) Kategorie-Mapping aus Altdatei lernen",
            "Eine alte, bereits von Hand mit Category ID befüllte Draft-Datei "
            "auswählen. Befüllt nur leere eBay-Zellen in "
            "channels/channel_category_mapping.csv – vorhandene Werte bleiben "
            "unangetastet.",
            "Altdatei wählen ...", self._run_learn_category)

        self._status_lbl = tk.Label(frm, text="", bg=c["BG2"], fg=c["FG_DIM"],
                                    font=_FONT_SM, anchor="w", justify="left",
                                    wraplength=900)
        self._status_lbl.grid(row=3, column=0, sticky="ew", pady=(8, 0))

        btn_row = tk.Frame(frm, bg=c["BG2"])
        btn_row.grid(row=4, column=0, sticky="w", pady=(6, 0))
        tk.Button(btn_row, text="Ausgabeordner öffnen", command=self._open_out_dir,
                  font=_FONT_SM, bg=c["BG3"], fg=c["FG"],
                  activebackground=c["BG"], activeforeground=c["FG"],
                  relief="flat", bd=0, cursor="hand2",
                  padx=8, pady=3).pack(side="left")

    def _set_busy(self, busy: bool):
        self._busy = busy
        state = "disabled" if busy else "normal"
        for b in (self._btn_sku, self._btn_revise, self._btn_learn):
            b.config(state=state)

    def _log(self, msg, **kw):
        self._app._append_log(msg, **kw)

    def _run_in_thread(self, fn):
        if self._busy:
            return
        self._set_busy(True)
        self._status_lbl.config(text="Läuft ...", fg=self._C["FG_DIM"])

        def _do():
            try:
                result = fn(self._log)
                self._parent.after(0, self._on_task_done, result, None)
            except Exception as exc:
                self._parent.after(0, self._on_task_done, None, str(exc))

        threading.Thread(target=_do, daemon=True).start()

    def _on_task_done(self, result, error):
        self._set_busy(False)
        if error:
            self._status_lbl.config(text=f"Fehler: {error}", fg=self._C["RED"])
            messagebox.showerror("Fehler", error, parent=self._parent)
            return
        if not result:
            self._status_lbl.config(text="Keine Datei ausgewählt oder keine Treffer.",
                                    fg=self._C.get("YELLOW", self._C["FG_DIM"]))
            return
        parts = []
        for key, label in (("neuanlage", "Neuanlage"), ("revise", "Revise"),
                           ("beenden", "Beenden"), ("learned", "gelernt")):
            if result.get(key):
                parts.append(f"{label}: {result[key]}")
        if result.get("not_found"):
            parts.append(f"nicht in DB gefunden: {result['not_found']}")
        if result.get("missing"):
            parts.append(f"nicht (mehr) in DB: {result['missing']}")
        if result.get("no_category"):
            parts.append(f"ohne eBay-Kategorie: {result['no_category']}")
        text = "  |  ".join(parts) if parts else "Fertig – keine Änderungen."
        self._status_lbl.config(text=text, fg=self._C["GREEN"])
        self._load_registry()

    def _run_sku_liste(self):
        path = filedialog.askopenfilename(
            parent=self._parent, title="eBay SKU-Liste auswählen",
            filetypes=[("CSV-Datei", "*.csv"), ("Alle Dateien", "*.*")])
        if not path:
            return
        import config as _cfg
        from lib.ebay_export import process_sku_list
        out_dir = os.path.join(_cfg.EXPORT_DIR, "ebay")
        self._run_in_thread(lambda log: process_sku_list(
            path, _cfg.DB_PATH, _cfg.BASE_DIR, out_dir, _IMAGE_BASE, progress_cb=log))

    def _run_revise_sync(self):
        path = filedialog.askopenfilename(
            parent=self._parent, title="eBay Revise-Report auswählen",
            filetypes=[("CSV-Datei", "*.csv"), ("Alle Dateien", "*.*")])
        if not path:
            return
        import config as _cfg
        from lib.ebay_export import sync_active_listings
        out_dir = os.path.join(_cfg.EXPORT_DIR, "ebay")
        self._run_in_thread(lambda log: sync_active_listings(
            path, _cfg.DB_PATH, out_dir, progress_cb=log))

    def _run_learn_category(self):
        path = filedialog.askopenfilename(
            parent=self._parent, title="Alte eBay-Batch-Datei auswählen",
            filetypes=[("CSV-Datei", "*.csv"), ("Alle Dateien", "*.*")])
        if not path:
            return
        import config as _cfg
        from lib.ebay_export import learn_category_map
        self._run_in_thread(lambda log: learn_category_map(
            path, _cfg.DB_PATH, _cfg.BASE_DIR, progress_cb=log))

    def _open_out_dir(self):
        try:
            import config as _cfg, subprocess
            d = os.path.join(_cfg.EXPORT_DIR, "ebay")
            if os.path.isdir(d):
                subprocess.Popen(f'explorer "{d}"', shell=True)
            else:
                messagebox.showinfo("Ordner", "Noch keine Ausgabedateien vorhanden.",
                                    parent=self._parent)
        except Exception:
            pass

    # ── Filter ────────────────────────────────────────────────────────────────

    def _build_filter(self, parent):
        c   = self._C
        frm = tk.Frame(parent, bg=c["BG2"], padx=10, pady=6)
        frm.grid(row=1, column=0, sticky="ew")

        tk.Label(frm, text="SKU/ItemID:", bg=c["BG2"], fg=c["FG_DIM"],
                 font=_FONT).pack(side="left", padx=(0, 4))
        self._search_var = tk.StringVar()
        e = tk.Entry(frm, textvariable=self._search_var, width=24,
                     bg=c["BG3"], fg=c.get("FG_INPUT", c["FG"]),
                     insertbackground=c.get("FG_INPUT", c["FG"]),
                     relief="flat", bd=3, font=_FONT_MONO)
        e.pack(side="left", padx=(0, 12))
        self._search_var.trace_add("write", lambda *_: self._apply_filter())

        tk.Label(frm, text="Status:", bg=c["BG2"], fg=c["FG_DIM"],
                 font=_FONT).pack(side="left", padx=(0, 4))
        self._status_var = tk.StringVar(value="Alle")
        cb = ttk.Combobox(frm, textvariable=self._status_var,
                          values=["Alle", "active", "ended"], width=10,
                          state="readonly", font=_FONT)
        cb.pack(side="left", padx=(0, 12))
        cb.bind("<<ComboboxSelected>>", lambda *_: self._apply_filter())

        tk.Button(frm, text="Aktualisieren", command=self._load_registry,
                  font=_FONT_SM, bg=c["BG3"], fg=c["FG"],
                  activebackground=c["BG"], activeforeground=c["FG"],
                  relief="flat", bd=0, cursor="hand2",
                  padx=8, pady=3).pack(side="left")

        self._count_lbl = tk.Label(frm, text="", bg=c["BG2"], fg=c["FG_DIM"],
                                   font=_FONT_SM)
        self._count_lbl.pack(side="right")

    # ── Tabelle ───────────────────────────────────────────────────────────────

    def _build_table(self, parent):
        c   = self._C
        frm = tk.Frame(parent, bg=c["BG"])
        frm.grid(row=2, column=0, sticky="nsew", padx=8, pady=(4, 0))
        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(0, weight=1)

        col_ids = [k for k, *_ in _COLS]
        self._tree = ttk.Treeview(frm, columns=col_ids, show="headings")

        style = ttk.Style()
        fi = c.get("FG_INPUT", c["FG"])
        style.configure("Ebay.Treeview", background=c["BG3"], foreground=fi,
                        fieldbackground=c["BG3"], rowheight=22, font=_FONT)
        style.configure("Ebay.Treeview.Heading", background=c["BG2"],
                        foreground=c["FG"], font=_FONT_HEAD, relief="flat")
        style.map("Ebay.Treeview", background=[("selected", c["ACCENT"])],
                  foreground=[("selected", "#ffffff")])
        self._tree["style"] = "Ebay.Treeview"

        for key, heading, width, stretch in _COLS:
            self._tree.heading(key, text=heading)
            self._tree.column(key, width=width, minwidth=50, stretch=stretch, anchor="w")

        vsb = ttk.Scrollbar(frm, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

    def _build_pagination(self, parent):
        c   = self._C
        frm = tk.Frame(parent, bg=c["BG2"], pady=5)
        frm.grid(row=3, column=0, sticky="ew")
        frm.columnconfigure(2, weight=1)

        btn_cfg = dict(font=_FONT_SM, bg=c["BG3"], fg=c["FG"],
                       activebackground=c["BG"], activeforeground=c["FG"],
                       relief="flat", bd=0, cursor="hand2", padx=10, pady=3)
        self._prev_btn = tk.Button(frm, text="◀ Zurück", command=self._prev_page, **btn_cfg)
        self._prev_btn.grid(row=0, column=0, padx=(10, 4))
        self._page_lbl = tk.Label(frm, text="", bg=c["BG2"], fg=c["FG"], font=_FONT)
        self._page_lbl.grid(row=0, column=1, padx=8)
        self._next_btn = tk.Button(frm, text="Weiter ▶", command=self._next_page, **btn_cfg)
        self._next_btn.grid(row=0, column=2, sticky="w", padx=(4, 0))

    # ── Laden / Filtern / Rendern ────────────────────────────────────────────

    def on_tab_activated(self):
        self._load_registry()

    def _load_registry(self):
        def _do():
            try:
                import config as _cfg
                from lib.article_db import open_db
                if not os.path.exists(_cfg.DB_PATH):
                    self._parent.after(0, self._count_lbl.config, {"text": "DB nicht gefunden"})
                    return
                con = open_db(_cfg.DB_PATH)
                rows = con.execute(
                    "SELECT sku, item_id, category_name, status, last_seen "
                    "FROM ebay_listings ORDER BY last_seen DESC").fetchall()
                self._all = [dict(r) for r in rows]
                self._parent.after(0, self._apply_filter)
            except Exception as exc:
                self._parent.after(0, self._count_lbl.config, {"text": f"Fehler: {exc}"})
        # Thread-Start über .after() verzögern statt direkt: siehe
        # eclass_catalog_browser.py – vermeidet "main thread is not in main
        # loop" (Python 3.14), falls der Aufrufer je vor Mainloop-Start läuft.
        self._parent.after(0, lambda: threading.Thread(target=_do, daemon=True).start())

    def _apply_filter(self, *_):
        term   = self._search_var.get().strip().lower()
        status = self._status_var.get()
        data = self._all
        if term:
            data = [r for r in data if term in r["sku"].lower()
                    or term in (r.get("item_id") or "").lower()]
        if status != "Alle":
            data = [r for r in data if r.get("status") == status]
        self._filtered = data
        self._page = 0
        self._render_page()

    def _render_page(self):
        total = len(self._filtered)
        pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
        self._page = max(0, min(self._page, pages - 1))
        start = self._page * _PAGE_SIZE
        chunk = self._filtered[start:start + _PAGE_SIZE]

        self._tree.delete(*self._tree.get_children())
        for r in chunk:
            self._tree.insert("", "end", values=(
                r.get("sku", ""), r.get("item_id", ""),
                r.get("category_name", ""), r.get("status", ""),
                _fmt_local(r.get("last_seen", "")),
            ))
        self._page_lbl.config(text=f"Seite  {self._page + 1}  /  {pages}")
        self._prev_btn.config(state="normal" if self._page > 0 else "disabled")
        self._next_btn.config(state="normal" if self._page < pages - 1 else "disabled")
        self._count_lbl.config(text=f"{total:,} Einträge".replace(",", "."))

    def _prev_page(self):
        self._page -= 1
        self._render_page()

    def _next_page(self):
        self._page += 1
        self._render_page()
