# lib/viewer_tab.py – Viewer / Export Reiter
#
# Zeigt geänderte Artikel aus der SQLite-DB.
# Filter: Datum, Lieferant, Katalog, Artikel-Nr., EAN.
# Paginierung: 100 Zeilen pro Seite. Sortierung per Spaltenklick.

import os
import threading
import datetime
import tkinter as tk
from tkinter import ttk, messagebox

_FONT      = ("Segoe UI", 10)
_FONT_MONO = ("Consolas", 9)
_FONT_SM   = ("Segoe UI", 8)
_FONT_HEAD = ("Segoe UI Semibold", 10)

_PAGE_SIZE = 100

# Spalten: (db-key, Überschrift, Breite, stretch)
_COLS = [
    ("product_id",        "Artikel-Nr.",   155, False),
    ("ean",               "EAN",           120, False),
    ("description_short", "Bezeichnung",   290, True),
    ("supplier_name",     "Lieferant",     130, False),
    ("catalog_display",   "Katalog",       145, False),
    ("price_display",     "Preis",          80, False),
    ("last_changed",      "Geändert",      115, False),
    ("last_export_date",  "Exportiert",    115, False),
]
_SORT_KEYS = {k: k for k, *_ in _COLS}


def _fmt_local(iso_utc: str) -> str:
    """
    Wandelt einen in der DB gespeicherten UTC-Zeitstempel (_now() in
    article_db.py) für die Anzeige in die lokale Zeitzone um. Ohne diese
    Umrechnung stand hier die reine UTC-Uhrzeit, in der Sommerzeit also
    zwei Stunden hinter der Wanduhr.
    """
    if not iso_utc:
        return ""
    try:
        dt = datetime.datetime.fromisoformat(iso_utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso_utc[:16].replace("T", " ")


class ViewerTab:
    def __init__(self, parent: tk.Frame, app, colors: dict):
        self._parent    = parent
        self._app       = app
        self._C         = colors
        self._all       = []      # Rohresultate aus DB
        self._filtered  = []      # nach Lokalfilter + Sortierung
        self._page      = 0
        self._sort_col  = "last_changed"
        self._sort_rev  = True
        self._exporting = False

        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        self._build_filters(parent)
        self._build_table(parent)
        self._build_pagination(parent)
        self._build_export(parent)
        self._load_filter_options()

    # ── Filter-Bereich ────────────────────────────────────────────────────────

    def _build_filters(self, parent):
        c   = self._C
        frm = tk.Frame(parent, bg=c["BG2"], padx=10, pady=8)
        frm.grid(row=0, column=0, sticky="ew")

        today    = datetime.date.today()
        week_ago = today - datetime.timedelta(days=7)

        # ── Zeile 0: Datum + Lieferant + Katalog ──────────────────────────────
        r0 = tk.Frame(frm, bg=c["BG2"])
        r0.pack(fill="x", pady=(0, 4))

        def lbl(parent, text, padleft=6):
            tk.Label(parent, text=text, bg=c["BG2"], fg=c["FG_DIM"],
                     font=_FONT).pack(side="left", padx=(padleft, 2))

        def entry(parent, var, width=11):
            fi = c.get("FG_INPUT", c["FG"])
            e = tk.Entry(parent, textvariable=var, width=width,
                         bg=c["BG3"], fg=fi, insertbackground=fi,
                         relief="flat", bd=3, font=_FONT_MONO)
            e.pack(side="left", padx=(0, 4))
            return e

        def combo(parent, var, vals, width=18):
            cb = ttk.Combobox(parent, textvariable=var, values=vals,
                              width=width, state="readonly", font=_FONT)
            cb.pack(side="left", padx=(0, 6))
            return cb

        self._from_var = tk.StringVar(value=str(week_ago))
        self._to_var   = tk.StringVar(value=str(today))

        lbl(r0, "Von:", 0);  entry(r0, self._from_var)
        lbl(r0, "Bis:");     entry(r0, self._to_var)
        lbl(r0, "Lieferant:")
        self._sup_var = tk.StringVar(value="Alle")
        self._sup_cb  = combo(r0, self._sup_var, ["Alle"])
        lbl(r0, "Katalog:")
        self._cat_var = tk.StringVar(value="Alle")
        self._cat_cb  = combo(r0, self._cat_var, ["Alle"], width=22)

        tk.Button(r0, text="Suchen", command=self._run_search,
                  font=_FONT, bg=c["ACCENT"], fg="#fff",
                  activebackground=c["BG"], activeforeground=c["FG"],
                  relief="flat", bd=0, cursor="hand2",
                  padx=10, pady=3).pack(side="left", padx=(2, 12))

        self._count_lbl = tk.Label(r0, text="", bg=c["BG2"],
                                   fg=c["FG_DIM"], font=_FONT_SM)
        self._count_lbl.pack(side="left")

        self._db_lbl = tk.Label(r0, text="", bg=c["BG2"],
                                fg=c["FG_DIM"], font=_FONT_SM)
        self._db_lbl.pack(side="right", padx=(0, 8))

        # ── Zeile 1: Lokalfilter ──────────────────────────────────────────────
        r1 = tk.Frame(frm, bg=c["BG2"])
        r1.pack(fill="x")

        lbl(r1, "Artikel-Nr.:", 0)
        self._artnr_var = tk.StringVar()
        entry(r1, self._artnr_var, width=18)
        self._artnr_var.trace_add("write", lambda *_: self._apply_local())

        lbl(r1, "EAN:")
        self._ean_var = tk.StringVar()
        entry(r1, self._ean_var, width=14)
        self._ean_var.trace_add("write", lambda *_: self._apply_local())

        tk.Label(r1, text="  (Sofortfilter, kein Neustart nötig)",
                 bg=c["BG2"], fg=c["FG_DIM"], font=_FONT_SM).pack(side="left")

    # ── Ergebnistabelle ───────────────────────────────────────────────────────

    def _build_table(self, parent):
        c   = self._C
        frm = tk.Frame(parent, bg=c["BG"])
        frm.grid(row=1, column=0, sticky="nsew", padx=8, pady=(4, 0))
        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(0, weight=1)

        col_ids = [k for k, *_ in _COLS]
        self._tree = ttk.Treeview(frm, columns=col_ids, show="headings",
                                  selectmode="extended")

        style = ttk.Style()
        fi = c.get("FG_INPUT", c["FG"])
        style.configure("Viewer.Treeview",
                        background=c["BG3"], foreground=fi,
                        fieldbackground=c["BG3"], rowheight=22, font=_FONT)
        style.configure("Viewer.Treeview.Heading",
                        background=c["BG2"], foreground=c["FG"],
                        font=_FONT_HEAD, relief="flat")
        style.map("Viewer.Treeview",
                  background=[("selected", c["ACCENT"])],
                  foreground=[("selected", "#ffffff")])
        self._tree["style"] = "Viewer.Treeview"

        for key, heading, width, stretch in _COLS:
            self._tree.heading(key, text=heading,
                               command=lambda k=key: self._sort(k))
            self._tree.column(key, width=width, minwidth=50,
                              stretch=stretch, anchor="w")

        vsb = ttk.Scrollbar(frm, orient="vertical",   command=self._tree.yview)
        hsb = ttk.Scrollbar(frm, orient="horizontal",  command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        self._tree.bind("<Double-1>", self._show_detail)
        self._update_sort_indicators()

    # ── Paginierung ───────────────────────────────────────────────────────────

    def _build_pagination(self, parent):
        c   = self._C
        frm = tk.Frame(parent, bg=c["BG2"], pady=5)
        frm.grid(row=2, column=0, sticky="ew")
        frm.columnconfigure(2, weight=1)

        btn_cfg = dict(font=_FONT_SM, bg=c["BG3"], fg=c["FG"],
                       activebackground=c["BG"], activeforeground=c["FG"],
                       relief="flat", bd=0, cursor="hand2",
                       padx=10, pady=3)

        self._prev_btn = tk.Button(frm, text="◀ Zurück",
                                   command=self._prev_page, **btn_cfg)
        self._prev_btn.grid(row=0, column=0, padx=(10, 4))

        self._page_lbl = tk.Label(frm, text="", bg=c["BG2"],
                                  fg=c["FG"], font=_FONT)
        self._page_lbl.grid(row=0, column=1, padx=8)

        self._next_btn = tk.Button(frm, text="Weiter ▶",
                                   command=self._next_page, **btn_cfg)
        self._next_btn.grid(row=0, column=2, sticky="w", padx=(4, 0))

        self._total_lbl = tk.Label(frm, text="", bg=c["BG2"],
                                   fg=c["FG_DIM"], font=_FONT_SM)
        self._total_lbl.grid(row=0, column=3, sticky="e", padx=(0, 12))

    # ── Export-Zeile ──────────────────────────────────────────────────────────

    def _build_export(self, parent):
        c   = self._C
        frm = tk.Frame(parent, bg=c["BG2"], padx=10, pady=8)
        frm.grid(row=3, column=0, sticky="ew")

        try:
            import config as _cfg
            export_dir = getattr(_cfg, "EXPORT_DIR", "?")
        except Exception:
            export_dir = "?"

        tk.Label(frm, text="Export-Verz.:", bg=c["BG2"],
                 fg=c["FG_DIM"], font=_FONT).pack(side="left")
        tk.Label(frm, text=export_dir, bg=c["BG2"],
                 fg=c["FG"], font=_FONT_MONO).pack(side="left", padx=(4, 12))
        tk.Button(frm, text="Ordner öffnen", command=self._open_export_dir,
                  font=_FONT_SM, bg=c["BG3"], fg=c["FG"],
                  activebackground=c["BG"], activeforeground=c["FG"],
                  relief="flat", bd=0, cursor="hand2",
                  padx=8, pady=3).pack(side="left")

        self._export_btn = tk.Button(
            frm, text="Gefilterte Artikel exportieren", command=self._run_export,
            font=_FONT, bg=c["GREEN"], fg="#fff",
            activebackground=c["BG"], activeforeground=c["FG"],
            relief="flat", bd=0, cursor="hand2", padx=12, pady=4)
        self._export_btn.pack(side="right", padx=(8, 0))

        self._filter_export_lbl = tk.Label(frm, text="", bg=c["BG2"],
                                            fg=c["FG_DIM"], font=_FONT_SM)
        self._filter_export_lbl.pack(side="right", padx=(0, 4))
        self._export_lbl = tk.Label(frm, text="", bg=c["BG2"],
                                    fg=c["FG_DIM"], font=_FONT_SM)
        self._export_lbl.pack(side="right", padx=8)

    # ── Filter-Optionen aus DB ─────────────────────────────────────────────────

    def on_tab_activated(self):
        """Wird aufgerufen wenn der Viewer-Reiter aktiv wird."""
        self._load_filter_options()
        self._update_db_status()

    def _update_db_status(self):
        """Zeigt Gesamtanzahl Artikel + Teilimport-Warnungen in DB."""
        try:
            import config as _cfg
            from lib.article_db import open_db, stats as db_stats
            from datetime import datetime, timedelta, timezone
            if not os.path.exists(_cfg.DB_PATH):
                self._db_lbl.config(text="DB: nicht gefunden")
                return
            con  = open_db(_cfg.DB_PATH)
            info = db_stats(con)
            total   = info.get('total', 0)
            by_sup  = info.get('by_supplier', {})
            detail  = "  ".join(
                f"{s}: {n:,}".replace(",", ".") for s, n in by_sup.items())

            # Teilimport-Warnung: Lieferant seit >2 Tagen nicht importiert
            warnings = []
            try:
                cutoff = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
                rows = con.execute(
                    "SELECT supplier_name, last_import_date, last_import_xml "
                    "FROM suppliers WHERE last_import_date IS NOT NULL "
                    "AND last_import_date < ?", (cutoff,)).fetchall()
                for r in rows:
                    age = r["last_import_date"][:10] if r["last_import_date"] else "?"
                    warnings.append(f"⚠ {r['supplier_name']} ({r['last_import_xml']}) "
                                    f"zuletzt importiert: {age}")
            except Exception:
                pass

            status_text = f"DB: {total:,} Artikel  ({detail})".replace(",", ".")
            if warnings:
                status_text += "  " + "  ".join(warnings)
            self._db_lbl.config(text=status_text)
        except Exception as e:
            self._db_lbl.config(text=f"DB: {e}")

    def _load_filter_options(self):
        try:
            import config as _cfg
            from lib.article_db import open_db

            # ── Eine DB-Verbindung für alle Abfragen ─────────────────────────────
            sups_in_db = set()
            cats = ['Alle']
            if os.path.exists(_cfg.DB_PATH):
                con = open_db(_cfg.DB_PATH)
                for r in con.execute(
                        "SELECT supplier_name FROM suppliers ORDER BY supplier_name"):
                    sups_in_db.add(r[0])
                rows = con.execute("""
                    SELECT cn.group_id, cn.name, s.supplier_name
                    FROM catalog_nodes cn
                    JOIN suppliers s ON s.id = cn.supplier_id
                    WHERE cn.parent_group_id = '' OR cn.parent_group_id IS NULL
                    ORDER BY s.supplier_name, cn.node_order, cn.name
                """).fetchall()
                seen = set()
                for gid, name, sup_name in rows:
                    entry = f"{sup_name}  /  {name}  [{gid}]"
                    if entry not in seen:
                        cats.append(entry)
                        seen.add(entry)

            try:
                import yaml
                with open(os.path.join(_cfg.BASE_DIR, 'supplier_config.yaml'),
                          encoding='utf-8') as f:
                    cfg = yaml.safe_load(f)
                all_names = []
                for sup in cfg.get('suppliers', {}).values():
                    if not sup.get('enabled', True):
                        continue
                    db_names = sup.get('db_supplier_names', {})
                    name_list = (list(db_names.values()) if db_names
                                 else [sup.get('db_supplier_name', sup.get('label', ''))])
                    for name in name_list:
                        if name and name not in [n.replace(' ✗', '') for n in all_names]:
                            mark = '' if name in sups_in_db else ' ✗'
                            all_names.append(f"{name}{mark}")
                sups = ['Alle'] + sorted(all_names)
            except Exception:
                sups = ['Alle'] + sorted(sups_in_db)

            self._sup_cb["values"] = sups
            self._cat_cb["values"] = cats
        except Exception:
            pass

    # ── DB-Suche ──────────────────────────────────────────────────────────────

    def _run_search(self):
        date_from = self._from_var.get().strip()
        date_to   = self._to_var.get().strip()
        if not date_from or not date_to:
            messagebox.showwarning("Datum fehlt",
                                   "Bitte Von- und Bis-Datum eingeben (YYYY-MM-DD).",
                                   parent=self._parent)
            return
        if len(date_to) == 10:
            date_to += "T23:59:59+00:00"

        sup = self._sup_var.get().replace(' ✗', '').strip()
        if sup == "Alle" or not sup:
            sup = None

        cat = self._cat_var.get()
        # Format: "Lieferant  /  Name  [group_id]"  oder alt "group_id  –  name"
        cat_gid = None
        if cat and cat != "Alle":
            if "[" in cat and cat.endswith("]"):
                cat_gid = cat[cat.rfind("[")+1:-1].strip()
            elif "  –  " in cat:
                cat_gid = cat.split("  –  ")[0].strip()

        self._count_lbl.config(text="Suche läuft...")
        self._parent.update_idletasks()

        def _do():
            try:
                import config as _cfg
                from lib.article_db import open_db, query_changed
                if not os.path.exists(_cfg.DB_PATH):
                    self._parent.after(0, self._count_lbl.config,
                                       {"text": "DB nicht gefunden"})
                    return
                con      = open_db(_cfg.DB_PATH)
                articles = query_changed(con, date_from, date_to, sup)
                if cat_gid:
                    articles = [a for a in articles
                                if (a.get("catalog_node_group_id") == cat_gid
                                    or a.get("catalog_group_id")    == cat_gid
                                    or a.get("catalog_sub_group_id") == cat_gid)]
                # Felder für Anzeige vorberechnen
                for a in articles:
                    a["catalog_display"] = (a.get("catalog_node_name")
                                            or a.get("catalog_sub_group_id")
                                            or a.get("catalog_group_id") or "")
                    p = a.get("price_amount")
                    a["price_display"] = f"{p:.2f} €" if isinstance(p, float) else str(p or "")
                    a["last_changed"] = _fmt_local(a.get("last_changed") or "")
                self._all = articles
                self._parent.after(0, self._apply_local)
                self._parent.after(0, self._load_filter_options)
                self._parent.after(0, self._update_db_status)
            except Exception as exc:
                self._parent.after(0, self._count_lbl.config,
                                   {"text": f"Fehler: {exc}"})

        threading.Thread(target=_do, daemon=True).start()

    # ── Lokalfilter + Sortierung ──────────────────────────────────────────────

    def _apply_local(self, *_):
        """Filtert self._all nach Art-Nr/EAN-Eingabe und sortiert."""
        artnr = self._artnr_var.get().strip().lower()
        ean   = self._ean_var.get().strip().lower()

        data = self._all
        if artnr:
            data = [a for a in data if artnr in (a.get("product_id") or "").lower()]
        if ean:
            data = [a for a in data if ean in (a.get("ean") or "").lower()]

        # Sortierung
        col = self._sort_col
        rev = self._sort_rev
        try:
            data = sorted(data,
                          key=lambda a: (a.get(col) or ""),
                          reverse=rev)
        except Exception:
            pass

        self._filtered = data
        self._page     = 0
        self._render_page()

    # ── Seite rendern ─────────────────────────────────────────────────────────

    def _render_page(self):
        total    = len(self._filtered)
        pages    = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
        self._page = max(0, min(self._page, pages - 1))

        start = self._page * _PAGE_SIZE
        chunk = self._filtered[start : start + _PAGE_SIZE]

        self._tree.delete(*self._tree.get_children())
        for a in chunk:
            exp = _fmt_local(a.get("last_export_date") or "")
            self._tree.insert("", "end", iid=str(a["id"]), values=(
                a.get("product_id", ""),
                a.get("ean", ""),
                a.get("description_short", ""),
                a.get("supplier_name", ""),
                a.get("catalog_display", ""),
                a.get("price_display", ""),
                a.get("last_changed", ""),
                exp,
            ))

        # Pagination-Controls
        self._page_lbl.config(
            text=f"Seite  {self._page + 1}  /  {pages}")
        self._total_lbl.config(
            text=f"Gesamt: {total:,} Artikel".replace(",", "."))
        self._prev_btn.config(state="normal" if self._page > 0 else "disabled")
        self._next_btn.config(state="normal" if self._page < pages - 1 else "disabled")
        self._count_lbl.config(
            text=f"{total:,} Artikel".replace(",", "."))
        n_filtered = len(self._filtered)
        self._filter_export_lbl.config(
            text=f"{n_filtered:,} Artikel im Export".replace(",", "."))

    def _prev_page(self):
        self._page -= 1
        self._render_page()

    def _next_page(self):
        self._page += 1
        self._render_page()

    # ── Sortierung ────────────────────────────────────────────────────────────

    def _sort(self, col_key: str):
        if self._sort_col == col_key:
            self._sort_rev = not self._sort_rev
        else:
            self._sort_col = col_key
            self._sort_rev = False
        self._update_sort_indicators()
        self._apply_local()

    def _update_sort_indicators(self):
        for key, heading, *_ in _COLS:
            if key == self._sort_col:
                arrow = " ▼" if self._sort_rev else " ▲"
                self._tree.heading(key, text=heading + arrow)
            else:
                self._tree.heading(key, text=heading)

    # ── Detail-Ansicht (Doppelklick) ──────────────────────────────────────────

    def _show_detail(self, event=None):
        sel = self._tree.selection()
        if not sel:
            return
        art_id = int(sel[0])
        art    = next((a for a in self._filtered if a["id"] == art_id), None)
        if not art:
            return

        c   = self._C
        win = tk.Toplevel(self._parent)
        win.title(f"Artikel  {art.get('product_id', art_id)}")
        win.geometry("720x540")
        win.configure(bg=c["BG"])

        fi = c.get("FG_INPUT", c["FG"])
        txt = tk.Text(win, bg=c["BG3"], fg=fi, font=_FONT_MONO,
                      wrap="none", relief="flat", bd=6)
        vsb = ttk.Scrollbar(win, orient="vertical",  command=txt.yview)
        hsb = ttk.Scrollbar(win, orient="horizontal", command=txt.xview)
        txt.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side="right",  fill="y")
        hsb.pack(side="bottom", fill="x")
        txt.pack(fill="both", expand=True, padx=2, pady=2)

        skip = {"features","mimes","keywords","references","udx",
                "id","supplier_id","_catalog_node_id",
                "catalog_display","price_display"}
        for k, v in art.items():
            if k not in skip:
                txt.insert("end", f"{k:<28} {v}\n")

        if art.get("features"):
            txt.insert("end", "\n── Features ─────────────────────────────\n")
            for f in art["features"]:
                unit = f"  [{f['funit']}]" if f.get("funit") else ""
                txt.insert("end",
                    f"  {f['fname']:<32} {f.get('fvalue','')}{unit}"
                    f"  fusage={f.get('fusage',1)}\n")

        if art.get("mimes"):
            txt.insert("end", "\n── MIMEs ─────────────────────────────────\n")
            for m in art["mimes"]:
                txt.insert("end",
                    f"  [{m.get('mime_purpose',''):24}] {m.get('mime_source','')}\n")

        if art.get("keywords"):
            txt.insert("end", f"\n── Keywords ──────────────────────────────\n")
            txt.insert("end", "  " + ", ".join(art["keywords"]) + "\n")

        txt.configure(state="disabled")

    # ── Export ────────────────────────────────────────────────────────────────

    def _run_export(self):
        if self._exporting:
            return
        date_from = self._from_var.get().strip()
        date_to   = self._to_var.get().strip()
        if not date_from or not date_to:
            messagebox.showwarning("Datum fehlt",
                                   "Bitte Zeitraum eingeben.",
                                   parent=self._parent)
            return
        if len(date_to) == 10:
            date_to += "T23:59:59+00:00"

        sup = self._sup_var.get().replace(' ✗', '').strip()
        if sup == "Alle" or not sup:
            sup = None

        self._exporting = True
        self._export_btn.config(state="disabled", text="Exportiere...")
        self._export_lbl.config(text="")

        def _log(msg, **kw):
            self._app._append_log(msg, **kw)

        # IDs der aktuell gefilterten Artikel
        filtered_ids = [a['id'] for a in self._filtered] if self._filtered else None

        def _do():
            try:
                from tasks.db_export import run as db_export_run
                result = db_export_run(date_from=date_from, date_to=date_to,
                                       supplier_name=sup,
                                       article_ids=filtered_ids,
                                       progress_cb=_log)
                n  = result.get("exported", 0)
                bl = result.get("blacklisted", 0)
                msg = f"{n} exportiert" + (f", {bl} Blacklist" if bl else "")
                self._parent.after(0, self._on_export_done, msg, True)
            except Exception as exc:
                self._parent.after(0, self._on_export_done, str(exc), False)

        threading.Thread(target=_do, daemon=True).start()

    def _on_export_done(self, msg: str, ok: bool):
        self._exporting = False
        self._export_btn.config(state="normal", text="Gefilterte Artikel exportieren")
        self._export_lbl.config(
            text=msg,
            fg=self._C["GREEN"] if ok else self._C["RED"])

    def _open_export_dir(self):
        try:
            import config as _cfg, subprocess
            d = getattr(_cfg, "EXPORT_DIR", "")
            if os.path.isdir(d):
                subprocess.Popen(f'explorer "{d}"', shell=True)
        except Exception:
            pass
