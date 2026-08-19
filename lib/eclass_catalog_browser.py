# lib/eclass_catalog_browser.py – eClass-Katalog Viewer
#
# Tab mit Filter (Version, Ebene, Regex) und paginierter Treeview.
# Wird in main.py als vierter Tab eingebunden.

import re
import threading
import tkinter as tk
from tkinter import ttk

from lib.design import FONT_UI, FONT_UI_SM, FONT_MONO

_PAGE_SIZE = 200

_COLS = [
    ("version",     "Version",   80,  False),
    ("code",        "Code",     120,  False),
    ("name_de",     "Name DE",  250,  True),
    ("name_en",     "Name EN",  220,  True),
    ("level",       "Ebene",     95,  False),
    ("parent_code", "Parent",   110,  False),
]
_COL_IDX = {k: i for i, (k, *_) in enumerate(_COLS)}

_LEVELS = ["Alle Ebenen", "segment", "hauptgruppe", "gruppe", "klasse"]

_VERSION_SORT_KEY = lambda v: [
    int(x) if x.isdigit() else 999
    for x in v.replace("UNSPSC ", "").replace("UNv", "999.").split(".")
]


class EclassCatalogBrowser:

    def __init__(self, parent: tk.Frame, app, colors: dict):
        self._C          = colors
        self._app        = app
        self._all: list  = []       # list[tuple] – alle Zeilen
        self._filtered   = []       # nach Filter
        self._page       = 0
        self._sort_col   = "code"
        self._sort_rev   = False
        self._debounce   = None

        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        self._build_filters(parent)
        self._build_table(parent)
        self._build_footer(parent)
        self._load_async()

    # ── Filter-Leiste ─────────────────────────────────────────────────────────

    def _build_filters(self, parent):
        c   = self._C
        bar = tk.Frame(parent, bg=c["BG2"], pady=6, padx=10)
        bar.grid(row=0, column=0, sticky="ew")

        def lbl(text):
            tk.Label(bar, text=text, bg=c["BG2"], fg=c["FG"],
                     font=FONT_UI).pack(side="left", padx=(0, 4))

        # Version
        lbl("Version:")
        self._ver_var = tk.StringVar(value="Alle")
        self._ver_cb  = ttk.Combobox(bar, textvariable=self._ver_var,
                                     width=14, state="readonly")
        self._ver_cb["values"] = ["Alle"]
        self._ver_cb.pack(side="left", padx=(0, 14))
        self._ver_cb.bind("<<ComboboxSelected>>", self._on_filter)

        # Ebene
        lbl("Ebene:")
        self._lvl_var = tk.StringVar(value="Alle Ebenen")
        lvl_cb = ttk.Combobox(bar, textvariable=self._lvl_var,
                               width=14, state="readonly")
        lvl_cb["values"] = _LEVELS
        lvl_cb.pack(side="left", padx=(0, 14))
        lvl_cb.bind("<<ComboboxSelected>>", self._on_filter)

        # Regex-Suche
        lbl("Regex:")
        self._search_var = tk.StringVar()
        self._entry = tk.Entry(
            bar, textvariable=self._search_var, width=30,
            bg=c["BG3"], fg=c.get("FG_INPUT", c["FG"]),
            insertbackground=c["FG"], relief="flat", font=FONT_MONO)
        self._entry.pack(side="left", padx=(0, 4), ipady=3)
        self._entry.bind("<Return>", self._on_filter)
        self._search_var.trace_add("write", self._debounced_filter)

        tk.Button(
            bar, text="✕", command=self._clear,
            bg=c["BG2"], fg=c.get("FG_DIM", c["FG"]),
            relief="flat", cursor="hand2", font=FONT_UI,
        ).pack(side="left", padx=(0, 14))

        # Status rechts
        self._status = tk.Label(bar, text="Lade Katalog …",
                                bg=c["BG2"], fg=c.get("FG_DIM", c["FG"]),
                                font=FONT_UI_SM)
        self._status.pack(side="right", padx=6)

    # ── Tabelle ───────────────────────────────────────────────────────────────

    def _build_table(self, parent):
        c   = self._C
        frm = tk.Frame(parent, bg=c["BG"])
        frm.grid(row=1, column=0, sticky="nsew")
        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(0, weight=1)

        sty = ttk.Style()
        sty.configure("ECB.Treeview",
                      background=c["BG3"],
                      foreground=c.get("FG_INPUT", c["FG"]),
                      fieldbackground=c["BG3"],
                      rowheight=22, font=FONT_UI)
        sty.configure("ECB.Treeview.Heading",
                      background=c["BG2"], foreground=c["FG"],
                      font=("Segoe UI Semibold", 10), relief="flat")
        sty.map("ECB.Treeview",
                background=[("selected", c["ACCENT"])],
                foreground=[("selected", "#ffffff")])

        cols = [k for k, *_ in _COLS]
        self._tree = ttk.Treeview(frm, columns=cols, show="headings",
                                  selectmode="browse", style="ECB.Treeview")
        for key, heading, width, stretch in _COLS:
            self._tree.heading(key, text=heading,
                               command=lambda k=key: self._sort(k))
            self._tree.column(key, width=width, minwidth=40,
                              stretch=stretch, anchor="w")

        vsb = ttk.Scrollbar(frm, orient="vertical",   command=self._tree.yview)
        hsb = ttk.Scrollbar(frm, orient="horizontal",  command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

    # ── Fußzeile / Paginierung ────────────────────────────────────────────────

    def _build_footer(self, parent):
        c    = self._C
        foot = tk.Frame(parent, bg=c["BG2"], pady=4, padx=10)
        foot.grid(row=2, column=0, sticky="ew")

        self._prev_btn = tk.Button(foot, text="◀", command=self._prev_page,
                                   bg=c["BG2"], fg=c["FG"], relief="flat",
                                   cursor="hand2", font=FONT_UI)
        self._prev_btn.pack(side="left")

        self._page_lbl = tk.Label(foot, text="–", bg=c["BG2"], fg=c["FG"],
                                  font=FONT_UI, width=20)
        self._page_lbl.pack(side="left", padx=6)

        self._next_btn = tk.Button(foot, text="▶", command=self._next_page,
                                   bg=c["BG2"], fg=c["FG"], relief="flat",
                                   cursor="hand2", font=FONT_UI)
        self._next_btn.pack(side="left")

        self._total_lbl = tk.Label(foot, text="", bg=c["BG2"],
                                   fg=c.get("FG_DIM", c["FG"]), font=FONT_UI_SM)
        self._total_lbl.pack(side="right", padx=8)

    # ── Laden ─────────────────────────────────────────────────────────────────

    def _load_async(self):
        def _worker():
            try:
                from lib.eclass_catalog import load_catalog
                cat   = load_catalog()
                rows  = []
                for v, codes in cat._by_version.items():
                    for code, row in codes.items():
                        rows.append((
                            row.get("version", v),
                            code,
                            row.get("name_de", ""),
                            row.get("name_en", ""),
                            row.get("level",   ""),
                            row.get("parent_code", ""),
                        ))
                versions = ["Alle"] + sorted(cat.versions, key=_VERSION_SORT_KEY)
                self._all = rows
                self._tree.after(0, lambda: self._on_loaded(versions))
            except Exception as exc:
                self._tree.after(0, lambda: self._status.config(
                    text=f"Fehler: {exc}", fg=self._C.get("RED", "#c00")))

        # Thread-Start über .after() verzögern, statt direkt aus __init__:
        # so startet der Thread erst, wenn die Tk-Mainloop im Hauptthread
        # tatsächlich läuft (sonst wirft tkinter ab Python 3.14
        # "RuntimeError: main thread is not in main loop", falls der
        # Worker-Thread schneller fertig ist als root.mainloop() anläuft).
        self._tree.after(0, lambda: threading.Thread(target=_worker, daemon=True).start())

    def _on_loaded(self, versions):
        self._ver_cb["values"] = versions
        self._status.config(text=f"{len(self._all):,} Einträge")
        self._apply_filter()

    # ── Filter & Sortierung ───────────────────────────────────────────────────

    def _on_filter(self, *_):
        self._page = 0
        self._apply_filter()

    def _debounced_filter(self, *_):
        if self._debounce:
            self._tree.after_cancel(self._debounce)
        self._debounce = self._tree.after(280, self._on_filter)

    def _clear(self):
        self._search_var.set("")
        self._ver_var.set("Alle")
        self._lvl_var.set("Alle Ebenen")
        self._entry.config(bg=self._C["BG3"])
        self._on_filter()

    def _apply_filter(self):
        ver = self._ver_var.get()
        lvl = self._lvl_var.get()
        pat = self._search_var.get().strip()

        data = self._all

        if ver and ver != "Alle":
            data = [r for r in data if r[0] == ver]

        if lvl and lvl != "Alle Ebenen":
            data = [r for r in data if r[4] == lvl]

        if pat:
            try:
                rx = re.compile(pat, re.IGNORECASE)
                # Code (1), name_de (2), name_en (3)
                data = [r for r in data
                        if rx.search(r[1]) or rx.search(r[2]) or rx.search(r[3])]
                self._entry.config(bg=self._C["BG3"])
            except re.error:
                self._entry.config(bg=self._C.get("RED", "#fdd"))

        si = _COL_IDX.get(self._sort_col, 1)
        self._filtered = sorted(data, key=lambda r: r[si], reverse=self._sort_rev)
        self._render_page()

    def _sort(self, col_key: str):
        if self._sort_col == col_key:
            self._sort_rev = not self._sort_rev
        else:
            self._sort_col = col_key
            self._sort_rev = False
        for key, heading, *_ in _COLS:
            arrow = (" ▼" if self._sort_rev else " ▲") if key == col_key else ""
            self._tree.heading(key, text=heading + arrow)
        self._page = 0
        self._apply_filter()

    # ── Paginierung ───────────────────────────────────────────────────────────

    def _render_page(self):
        total = len(self._filtered)
        pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
        self._page = max(0, min(self._page, pages - 1))
        start = self._page * _PAGE_SIZE
        chunk = self._filtered[start : start + _PAGE_SIZE]

        self._tree.delete(*self._tree.get_children())
        for r in chunk:
            self._tree.insert("", "end", values=r)

        self._page_lbl.config(text=f"Seite {self._page + 1} / {pages}")
        self._total_lbl.config(text=f"{total:,} Treffer")
        self._prev_btn.config(state="normal" if self._page > 0      else "disabled")
        self._next_btn.config(state="normal" if self._page < pages-1 else "disabled")

    def _prev_page(self):
        self._page -= 1
        self._render_page()

    def _next_page(self):
        self._page += 1
        self._render_page()
