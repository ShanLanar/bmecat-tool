# lib/kategorien_tab.py – Reiter "Kategorien": Kategoriebäume als Baum
#
# Zeigt die Bäume aus custom_categories.csv (Shop-Export: Zentralshop +
# Lieferantenbäume) als echten Baum mit Artikelzahlen aus der DB und dem
# Ziel-Mapping (product_category_code = "Artikel dieser Kategorie werden im
# Shop in Kategorie X gezeigt"). Das Ziel lässt sich hier ändern/entfernen,
# gespeichert wird in dieselbe Datei (Backup in logs/).
#
# Datenlogik ohne Tk: lib/category_tree.py

import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import copy
from datetime import datetime

from lib.design import FONT_UI, FONT_UI_SM, FONT_HEAD
from lib import category_tree as ct


class KategorienTab:

    def __init__(self, parent: tk.Frame, app, colors: dict):
        self._C = colors
        self._app = app
        self._parent = parent
        import config as _cfg
        self._cfg = _cfg
        self._rows, self._fields, self._enc = [], [], "cp1252"
        self._nodes, self._roots = {}, []
        self._counts = {}
        self._dirty = False
        self._loaded = False
        self._iid_to_code = {}
        self._code_to_iid = {}
        self._build()

    # ── Aufbau ────────────────────────────────────────────────────────────────

    def _build(self):
        c = self._C
        p = self._parent
        p.columnconfigure(0, weight=1)
        p.rowconfigure(1, weight=1)

        bar = tk.Frame(p, bg=c["BG2"], pady=6, padx=10)
        bar.grid(row=0, column=0, sticky="ew")
        tk.Label(bar, text="Baum:", bg=c["BG2"], fg=c["FG"], font=FONT_UI).pack(side="left")
        self._root_var = tk.StringVar()
        self._root_cb = ttk.Combobox(bar, textvariable=self._root_var, state="readonly",
                                     width=42, font=FONT_UI)
        self._root_cb.pack(side="left", padx=(4, 12))
        self._root_cb.bind("<<ComboboxSelected>>", lambda e: self._fill_tree())

        tk.Label(bar, text="Suche:", bg=c["BG2"], fg=c["FG"], font=FONT_UI).pack(side="left")
        self._search_var = tk.StringVar()
        ent = tk.Entry(bar, textvariable=self._search_var, font=FONT_UI, width=28)
        ent.pack(side="left", padx=4)
        ent.bind("<Return>", lambda e: self._fill_tree())
        tk.Button(bar, text="Filtern", command=self._fill_tree, bg=c["BG3"], fg=c["FG"],
                  relief="flat", cursor="hand2", font=FONT_UI, padx=8).pack(side="left")
        self._only_art = tk.BooleanVar(value=False)
        tk.Checkbutton(bar, text="nur mit Artikeln", variable=self._only_art,
                       command=self._fill_tree, bg=c["BG2"], fg=c["FG"], selectcolor=c["BG3"],
                       activebackground=c["BG2"], font=FONT_UI_SM).pack(side="left", padx=8)

        self._save_btn = tk.Button(bar, text="💾 Speichern", command=self._save, state="disabled",
                                   bg=c["ACCENT"], fg="#fff", relief="flat", cursor="hand2",
                                   font=FONT_UI, padx=10)
        self._save_btn.pack(side="right", padx=4)
        tk.Button(bar, text="↻ Neu laden", command=lambda: self.load(force=True), bg=c["BG3"],
                  fg=c["FG"], relief="flat", cursor="hand2", font=FONT_UI, padx=8).pack(side="right")
        tk.Button(bar, text="⬆ Für Shop exportieren …", command=self._export, bg=c["BG3"],
                  fg=c["FG"], relief="flat", cursor="hand2", font=FONT_UI, padx=8).pack(side="right", padx=4)
        tk.Button(bar, text="⬇ Shop-Export importieren …", command=self._import, bg=c["BG3"],
                  fg=c["FG"], relief="flat", cursor="hand2", font=FONT_UI, padx=8).pack(side="right", padx=4)
        self._status = tk.Label(bar, text="", bg=c["BG2"], fg=c.get("FG_DIM", c["FG"]), font=FONT_UI_SM)
        self._status.pack(side="right", padx=10)

        pane = tk.PanedWindow(p, orient="horizontal", bg=c["BG"], sashwidth=6, sashrelief="raised")
        pane.grid(row=1, column=0, sticky="nsew")

        # Baum links
        left = tk.Frame(pane, bg=c["BG"])
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        pane.add(left, minsize=420, width=760)
        sty = ttk.Style()
        sty.configure("KAT.Treeview", background=c["BG3"], foreground=c.get("FG_INPUT", c["FG"]),
                      fieldbackground=c["BG3"], rowheight=22, font=FONT_UI)
        sty.configure("KAT.Treeview.Heading", background=c["BG2"], foreground=c["FG"],
                      font=("Segoe UI Semibold", 10), relief="flat")
        sty.map("KAT.Treeview", background=[("selected", c["ACCENT"])],
                foreground=[("selected", "#ffffff")])
        cols = ("code", "direct", "total", "mapped", "online", "target")
        self._tree = ttk.Treeview(left, columns=cols, show="tree headings", selectmode="browse",
                                  style="KAT.Treeview")
        self._tree.heading("#0", text="Kategorie")
        self._tree.column("#0", width=320, minwidth=160, stretch=True)
        for key, head, w, anchor in (("code", "Code", 110, "w"), ("direct", "Artikel", 60, "e"),
                                     ("total", "gesamt", 60, "e"), ("mapped", "gemappt→hier", 85, "e"),
                                     ("online", "Online", 50, "center"), ("target", "Ziel im Shop", 260, "w")):
            self._tree.heading(key, text=head)
            self._tree.column(key, width=w, minwidth=40, stretch=(key == "target"), anchor=anchor)
        self._tree.tag_configure("offline", foreground=c.get("FG_DIM", "#888"))
        self._tree.tag_configure("mapped", foreground=c["ACCENT"])
        vsb = ttk.Scrollbar(left, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self._tree.bind("<<TreeviewSelect>>", self._on_select)
        self._tree.bind("<Double-1>", lambda e: self._show_articles())

        # Details rechts
        right = tk.Frame(pane, bg=c["BG"], padx=12, pady=8)
        right.columnconfigure(1, weight=1)
        pane.add(right, minsize=300)
        tk.Label(right, text="Kategorie", bg=c["BG"], fg=c["FG"], font=FONT_HEAD).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        self._detail_vars = {}
        r = 1
        for key, label in (("code", "Code"), ("name", "Name"), ("orig", "Original"), ("path", "Pfad"),
                           ("parent", "Übergeordnet"), ("online", "Online"), ("count", "Artikel"),
                           ("target", "Ziel im Shop")):
            tk.Label(right, text=label + ":", bg=c["BG"], fg=c.get("FG_DIM", c["FG"]),
                     font=FONT_UI_SM, anchor="ne").grid(row=r, column=0, sticky="ne", padx=(0, 8), pady=2)
            v = tk.StringVar()
            self._detail_vars[key] = v
            tk.Label(right, textvariable=v, bg=c["BG"], fg=c["FG"], font=FONT_UI, anchor="w",
                     justify="left", wraplength=360).grid(row=r, column=1, sticky="w", pady=2)
            r += 1

        btns = tk.Frame(right, bg=c["BG"])
        btns.grid(row=r, column=0, columnspan=2, sticky="w", pady=(8, 4))
        r += 1
        self._btn_pick = tk.Button(btns, text="Ziel wählen …", command=self._pick_target, bg=c["BG3"],
                                   fg=c["FG"], relief="flat", cursor="hand2", font=FONT_UI, padx=8,
                                   state="disabled")
        self._btn_pick.pack(side="left", padx=(0, 6))
        self._btn_clear = tk.Button(btns, text="Ziel entfernen", command=self._clear_target, bg=c["BG3"],
                                    fg=c["FG"], relief="flat", cursor="hand2", font=FONT_UI, padx=8,
                                    state="disabled")
        self._btn_clear.pack(side="left", padx=(0, 6))
        self._btn_goto = tk.Button(btns, text="Zum Ziel springen", command=self._goto_target, bg=c["BG3"],
                                   fg=c["FG"], relief="flat", cursor="hand2", font=FONT_UI, padx=8,
                                   state="disabled")
        self._btn_goto.pack(side="left", padx=(0, 6))
        self._btn_arts = tk.Button(btns, text="Artikel anzeigen", command=self._show_articles, bg=c["BG3"],
                                   fg=c["FG"], relief="flat", cursor="hand2", font=FONT_UI, padx=8,
                                   state="disabled")
        self._btn_arts.pack(side="left")

        tk.Label(right, text="Hierher gemappt (Quellen):", bg=c["BG"], fg=c.get("FG_DIM", c["FG"]),
                 font=FONT_UI_SM).grid(row=r, column=0, columnspan=2, sticky="w", pady=(10, 2))
        r += 1
        right.rowconfigure(r, weight=1)
        self._src_list = tk.Listbox(right, bg=c["BG3"], fg=c.get("FG_INPUT", c["FG"]), font=FONT_UI_SM,
                                    relief="flat", activestyle="none", selectbackground=c["ACCENT"])
        self._src_list.grid(row=r, column=0, columnspan=2, sticky="nsew")
        self._src_list.bind("<Double-1>", self._goto_source)
        self._src_codes = []

        info = ("Ziel = product_category_code in custom_categories.csv: Artikel dieser Kategorie\n"
                "werden im Shop im Ziel gezeigt. Änderungen erst mit 'Speichern' in die Datei\n"
                "(Backup in logs/). Die Datei dann wie gewohnt in den Shop übernehmen.")
        tk.Label(right, text=info, bg=c["BG"], fg=c.get("FG_DIM", c["FG"]), font=FONT_UI_SM,
                 justify="left").grid(row=r + 1, column=0, columnspan=2, sticky="w", pady=(8, 0))

    # ── Laden ─────────────────────────────────────────────────────────────────

    def on_tab_activated(self):
        if not self._loaded:
            self.load()

    def load(self, force: bool = False):
        if self._dirty and force:
            if not messagebox.askyesno("Ungespeicherte Änderungen",
                                       "Änderungen verwerfen und neu laden?", parent=self._parent):
                return
        self._status.config(text="Lade …")

        def _work():
            err = None
            try:
                rows, fields, enc = ct.load_rows(self._cfg.BASE_DIR)
                nodes, roots = ct.build_tree(rows)
                try:
                    counts = ct.load_article_counts(self._cfg.DB_PATH)
                except Exception as exc:
                    counts = {}
                    err = f"Artikelzahlen nicht geladen: {exc}"
                ct.apply_counts(nodes, roots, counts)
            except Exception as exc:
                rows, fields, enc, nodes, roots, counts = [], [], "cp1252", {}, [], {}
                err = str(exc)
            self._parent.after(0, lambda: self._apply_loaded(rows, fields, enc, nodes, roots, counts, err))

        threading.Thread(target=_work, daemon=True).start()

    def _apply_loaded(self, rows, fields, enc, nodes, roots, counts, err):
        self._rows, self._fields, self._enc = rows, fields, enc
        self._rows_loaded = copy.deepcopy(rows)
        self._nodes, self._roots, self._counts = nodes, roots, counts
        self._dirty = False
        self._save_btn.config(state="disabled")
        self._loaded = True
        labels = [f"{r.name}  ({r.code})  –  {len(self._descendants(r))} Kategorien" for r in roots]
        self._root_cb.config(values=labels)
        if labels:
            # Zentralshop (Code '1') zuerst, falls vorhanden
            idx = next((i for i, r in enumerate(roots) if r.code == "1"), 0)
            self._root_cb.current(idx)
        if not rows:
            self._status.config(text="custom_categories.csv nicht gefunden (BASE_DIR)")
        else:
            self._status.config(text=f"{len(nodes)} Kategorien, {len(roots)} Bäume"
                                     + (f"  ⚠ {err}" if err else ""))
        self._fill_tree()

    def _descendants(self, node) -> list:
        out = []
        stack = list(node.children)
        while stack:
            n = stack.pop()
            out.append(n)
            stack.extend(n.children)
        return out

    def _current_root(self):
        idx = self._root_cb.current()
        return self._roots[idx] if 0 <= idx < len(self._roots) else None

    # ── Baum füllen ───────────────────────────────────────────────────────────

    def _fill_tree(self):
        self._tree.delete(*self._tree.get_children())
        self._iid_to_code.clear()
        self._code_to_iid.clear()
        root = self._current_root()
        if not root:
            return
        q = self._search_var.get().strip().lower()
        only = self._only_art.get()

        def _matches(n) -> bool:
            if only and n.total == 0 and n.mapped_in == 0:
                return False
            if q and q not in n.name.lower() and q not in n.code.lower() \
                    and q not in (n.target or "").lower():
                return False
            return True

        def _visible(n) -> bool:
            # Knoten zeigen, wenn er selbst oder ein Nachfahre passt
            return _matches(n) or any(_visible(c) for c in n.children)

        def _insert(n, parent_iid, open_=False):
            if (q or only) and not _visible(n):
                return
            tgt = n.target
            tgt_txt = ""
            if tgt:
                tp = ct.path_of(self._nodes, tgt)
                tgt_txt = f"{tgt}  {tp}" if tp else f"{tgt} (unbekannt)"
            tags = []
            if not n.online:
                tags.append("offline")
            if tgt:
                tags.append("mapped")
            iid = self._tree.insert(parent_iid, "end", text=n.name or n.code, open=open_,
                                    values=(n.code, n.direct or "", n.total or "", n.mapped_in or "",
                                            "✓" if n.online else "–", tgt_txt), tags=tuple(tags))
            self._iid_to_code[iid] = n.key
            self._code_to_iid[n.key] = iid
            for ch in n.children:
                _insert(ch, iid, open_=bool(q))

        _insert(root, "", open_=True)
        self._status.config(text=f"{len(self._iid_to_code)} Kategorien angezeigt"
                                 + ("  (ungespeichert)" if self._dirty else ""))

    # ── Auswahl / Details ─────────────────────────────────────────────────────

    def _selected(self):
        sel = self._tree.selection()
        if not sel:
            return None
        return self._nodes.get(self._iid_to_code.get(sel[0], ""))

    def _on_select(self, _e=None):
        n = self._selected()
        v = self._detail_vars
        for btn in (self._btn_pick, self._btn_clear, self._btn_goto, self._btn_arts):
            btn.config(state="disabled")
        self._src_list.delete(0, "end")
        self._src_codes = []
        if not n:
            for var in v.values():
                var.set("")
            return
        v["code"].set(n.code)
        v["name"].set(n.name)
        orig = []
        if n.original_name and n.original_name != n.name:
            orig.append(f"Name: {n.original_name}")
        if n.original_parent and n.original_parent.upper() != n.parent.upper():
            orig.append(f"Parent: {n.original_parent} ({ct.path_of(self._nodes, n.original_parent) or '?'})")
        v["orig"].set("; ".join(orig) if orig else "unverändert")
        v["path"].set(ct.path_of(self._nodes, n.code))
        v["parent"].set(f"{n.parent}  {ct.path_of(self._nodes, n.parent)}" if n.parent else "(Wurzel)")
        v["online"].set("ja" if n.online else "nein")
        v["count"].set(f"{n.direct} direkt, {n.total} inkl. Unterkategorien"
                       + (f", {n.mapped_in} per Mapping hierher" if n.mapped_in else ""))
        if n.target:
            tp = ct.path_of(self._nodes, n.target)
            v["target"].set(f"{n.target}  {tp}" if tp else f"{n.target} (nicht im Baum)")
        else:
            v["target"].set("– (Artikel bleiben in dieser Kategorie)")
        self._btn_pick.config(state="normal")
        self._btn_clear.config(state="normal" if n.target else "disabled")
        self._btn_goto.config(state="normal" if n.target and n.target.upper() in self._nodes else "disabled")
        self._btn_arts.config(state="normal" if n.direct else "disabled")
        for s in sorted(ct.sources_for(self._nodes, n.code), key=lambda x: -x.total):
            self._src_list.insert("end", f"{s.code}  {ct.path_of(self._nodes, s.code)}  [{s.total}]")
            self._src_codes.append(s.key)

    def _goto(self, key: str):
        if not key or key not in self._nodes:
            return
        root = ct.root_of(self._nodes, key)
        if root and root is not self._current_root():
            idx = self._roots.index(root)
            self._root_cb.current(idx)
            self._search_var.set("")
            self._fill_tree()
        iid = self._code_to_iid.get(key)
        if not iid:
            self._search_var.set("")
            self._only_art.set(False)
            self._fill_tree()
            iid = self._code_to_iid.get(key)
        if iid:
            self._tree.see(iid)
            self._tree.selection_set(iid)
            self._tree.focus(iid)

    def _goto_target(self):
        n = self._selected()
        if n and n.target:
            self._goto(n.target.upper())

    def _goto_source(self, _e=None):
        sel = self._src_list.curselection()
        if sel and sel[0] < len(self._src_codes):
            self._goto(self._src_codes[sel[0]])

    # ── Ziel ändern ───────────────────────────────────────────────────────────

    def _set_target(self, n, target: str):
        target = (target or "").strip()
        if target.upper() == n.key:
            messagebox.showwarning("Ungültig", "Eine Kategorie kann nicht auf sich selbst zeigen.",
                                   parent=self._parent)
            return
        n.target = target
        n.row["product_category_code"] = target
        if "product_category_code" not in self._fields:
            self._fields.append("product_category_code")
        ct.apply_counts(self._nodes, self._roots, self._counts)
        self._dirty = True
        self._save_btn.config(state="normal")
        sel = self._tree.selection()
        self._fill_tree()
        iid = self._code_to_iid.get(n.key)
        if iid:
            self._tree.see(iid)
            self._tree.selection_set(iid)
        elif sel:
            pass
        self._on_select()

    def _clear_target(self):
        n = self._selected()
        if n:
            self._set_target(n, "")

    def _pick_target(self):
        n = self._selected()
        if not n:
            return
        TargetPicker(self._parent, self, n, lambda code: self._set_target(n, code))

    # ── Artikel ───────────────────────────────────────────────────────────────

    def _show_articles(self):
        n = self._selected()
        if not n or not n.direct:
            return
        c = self._C
        win = tk.Toplevel(self._parent)
        win.title(f"Artikel in {n.code} – {n.name}")
        win.geometry("760x520")
        win.configure(bg=c["BG"])
        tk.Label(win, text=f"{ct.path_of(self._nodes, n.code)}   ({n.direct} aktive Artikel direkt)",
                 bg=c["BG"], fg=c["FG"], font=FONT_UI, anchor="w").pack(fill="x", padx=10, pady=(8, 4))
        frm = tk.Frame(win, bg=c["BG"])
        frm.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        tv = ttk.Treeview(frm, columns=("pid", "name"), show="headings", style="KAT.Treeview")
        tv.heading("pid", text="product_id")
        tv.heading("name", text="Bezeichnung")
        tv.column("pid", width=160, stretch=False)
        tv.column("name", width=540, stretch=True)
        vsb = ttk.Scrollbar(frm, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=vsb.set)
        tv.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        def _work():
            try:
                rows = ct.articles_in(self._cfg.DB_PATH, n.code)
            except Exception as exc:
                rows = [("Fehler", str(exc))]
            win.after(0, lambda: [tv.insert("", "end", values=r) for r in rows])
        threading.Thread(target=_work, daemon=True).start()

    # ── Import / Export ───────────────────────────────────────────────────────

    def _import(self):
        """Neuen Kategorien-Export des Shops übernehmen (ersetzt custom_categories.csv)."""
        if self._dirty and not messagebox.askyesno(
                "Ungespeicherte Änderungen",
                "Es gibt ungespeicherte Ziel-Änderungen. Trotzdem importieren und verwerfen?",
                parent=self._parent):
            return
        path = filedialog.askopenfilename(
            title="Kategorien-Export des Shops wählen", parent=self._parent,
            filetypes=[("CSV", "*.csv"), ("Alle Dateien", "*.*")])
        if not path:
            return
        try:
            rows, fields, enc = ct.load_file(path)
        except Exception as exc:
            messagebox.showerror("Import fehlgeschlagen", str(exc), parent=self._parent)
            return
        if not rows:
            messagebox.showwarning("Import", "Die Datei enthält keine Kategorien.", parent=self._parent)
            return
        d = ct.diff_rows(self._rows, rows)
        msg = (f"{len(rows)} Kategorien in {os.path.basename(path)}.\n\n"
               f"Gegenüber dem aktuellen Stand:\n"
               f"  {len(d['added'])} neue Kategorien\n"
               f"  {len(d['removed'])} entfallen\n"
               f"  {len(d['target_changed'])} geänderte Ziele\n"
               f"  {len(d['renamed'])} umbenannt, {len(d['moved'])} umgehängt\n\n"
               f"custom_categories.csv ersetzen? (Backup in logs/)")
        if not messagebox.askyesno("Shop-Export importieren", msg, parent=self._parent):
            return
        try:
            ct.save_rows(self._cfg.BASE_DIR, rows, fields, enc, logs_dir=self._cfg.DIRS.get("logs"))
        except Exception as exc:
            messagebox.showerror("Import fehlgeschlagen", str(exc), parent=self._parent)
            return
        try:
            self._app._append_log(
                f"Kategorien: {os.path.basename(path)} importiert – {len(rows)} Kategorien, "
                f"{len(d['added'])} neu, {len(d['removed'])} entfallen, "
                f"{len(d['target_changed'])} Ziele geändert.", tag="ok")
        except Exception:
            pass
        self._dirty = False
        self.load(force=True)

    def _export(self):
        """Aktuellen Stand als Datei für den Shop schreiben (gleiches Format wie der Export)."""
        if not self._rows:
            return
        if self._dirty:
            if messagebox.askyesno("Ungespeichert", "Änderungen zuerst in custom_categories.csv speichern?",
                                   parent=self._parent):
                self._save()
        changes = ct.changed_targets(getattr(self, "_rows_loaded", []), self._rows)
        out_dir = self._cfg.DIRS.get("pim_export") or self._cfg.BASE_DIR
        default = f"custom_categories_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        path = filedialog.asksaveasfilename(
            title="Kategorien für den Shop exportieren", parent=self._parent,
            initialdir=out_dir if os.path.isdir(out_dir) else self._cfg.BASE_DIR,
            initialfile=default, defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            ct.write_file(path, self._rows, self._fields, self._enc)
        except Exception as exc:
            messagebox.showerror("Export fehlgeschlagen", str(exc), parent=self._parent)
            return
        self._status.config(text=f"Exportiert: {os.path.basename(path)} ({len(self._rows)} Kategorien)")
        try:
            self._app._append_log(
                f"Kategorien: {os.path.basename(path)} für den Shop geschrieben – {len(self._rows)} "
                f"Kategorien, {len(changes)} Ziel-Änderungen seit dem letzten Laden.", tag="ok")
        except Exception:
            pass

    # ── Speichern ─────────────────────────────────────────────────────────────

    def _save(self):
        if not self._dirty:
            return
        try:
            path = ct.save_rows(self._cfg.BASE_DIR, self._rows, self._fields, self._enc,
                                logs_dir=self._cfg.DIRS.get("logs"))
        except Exception as exc:
            messagebox.showerror("Speichern fehlgeschlagen", str(exc), parent=self._parent)
            return
        self._dirty = False
        self._save_btn.config(state="disabled")
        self._status.config(text=f"Gespeichert: {os.path.basename(path)} (Backup in logs/)")
        try:
            self._app._append_log(f"Kategorien: {os.path.basename(path)} gespeichert (Ziel-Mapping geändert).",
                                  tag="ok")
        except Exception:
            pass


class TargetPicker(tk.Toplevel):
    """Ziel-Kategorie aus einem beliebigen Baum wählen (Standard: Zentralshop)."""

    def __init__(self, parent, tab: KategorienTab, source, on_pick):
        super().__init__(parent)
        self._tab = tab
        self._on_pick = on_pick
        c = tab._C
        self.title(f"Ziel für {source.code} – {source.name}")
        self.geometry("720x560")
        self.configure(bg=c["BG"])
        self.transient(parent.winfo_toplevel())

        bar = tk.Frame(self, bg=c["BG2"], padx=10, pady=6)
        bar.pack(fill="x")
        tk.Label(bar, text="Baum:", bg=c["BG2"], fg=c["FG"], font=FONT_UI).pack(side="left")
        self._root_var = tk.StringVar()
        self._cb = ttk.Combobox(bar, textvariable=self._root_var, state="readonly", width=36,
                                values=[f"{r.name} ({r.code})" for r in tab._roots], font=FONT_UI)
        idx = next((i for i, r in enumerate(tab._roots) if r.code == "1"), 0)
        if tab._roots:
            self._cb.current(idx)
        self._cb.pack(side="left", padx=(4, 10))
        self._cb.bind("<<ComboboxSelected>>", lambda e: self._fill())
        tk.Label(bar, text="Suche:", bg=c["BG2"], fg=c["FG"], font=FONT_UI).pack(side="left")
        self._q = tk.StringVar()
        ent = tk.Entry(bar, textvariable=self._q, font=FONT_UI, width=24)
        ent.pack(side="left", padx=4)
        ent.bind("<Return>", lambda e: self._fill())
        ent.focus_set()

        frm = tk.Frame(self, bg=c["BG"])
        frm.pack(fill="both", expand=True, padx=10, pady=6)
        self._tree = ttk.Treeview(frm, columns=("code", "total"), show="tree headings",
                                  selectmode="browse", style="KAT.Treeview")
        self._tree.heading("#0", text="Kategorie")
        self._tree.column("#0", width=420, stretch=True)
        self._tree.heading("code", text="Code")
        self._tree.column("code", width=120, stretch=False)
        self._tree.heading("total", text="Artikel")
        self._tree.column("total", width=70, stretch=False, anchor="e")
        vsb = ttk.Scrollbar(frm, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self._tree.bind("<Double-1>", lambda e: self._ok())
        self._iid_code = {}

        btns = tk.Frame(self, bg=c["BG"], pady=6)
        btns.pack(fill="x", padx=10)
        tk.Button(btns, text="Übernehmen", command=self._ok, bg=c["ACCENT"], fg="#fff", relief="flat",
                  cursor="hand2", font=FONT_UI, padx=12).pack(side="right", padx=4)
        tk.Button(btns, text="Abbrechen", command=self.destroy, bg=c["BG3"], fg=c["FG"], relief="flat",
                  font=FONT_UI, padx=12).pack(side="right")
        self._fill()

    def _fill(self):
        self._tree.delete(*self._tree.get_children())
        self._iid_code.clear()
        idx = self._cb.current()
        if not (0 <= idx < len(self._tab._roots)):
            return
        root = self._tab._roots[idx]
        q = self._q.get().strip().lower()

        def _vis(n):
            return (not q) or q in n.name.lower() or q in n.code.lower() or any(_vis(c) for c in n.children)

        def _ins(n, parent, open_):
            if not _vis(n):
                return
            iid = self._tree.insert(parent, "end", text=n.name or n.code, open=open_,
                                    values=(n.code, n.total + n.mapped_in or ""))
            self._iid_code[iid] = n.code
            for ch in n.children:
                _ins(ch, iid, bool(q))
        _ins(root, "", True)

    def _ok(self):
        sel = self._tree.selection()
        if not sel:
            return
        code = self._iid_code.get(sel[0])
        if code:
            self._on_pick(code)
            self.destroy()
