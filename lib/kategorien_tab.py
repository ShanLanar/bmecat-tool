# lib/kategorien_tab.py – Reiter "Kategorien": zwei Kategoriebäume nebeneinander
#
# Zeigt die Bäume aus custom_categories.csv (Shop-Export: Zentralshop +
# Lieferantenbäume) als zwei Baumansichten (links/rechts, je eigener Baum und
# Suche) mit Artikelzahlen aus der DB und dem Ziel-Mapping
# (product_category_code = "Artikel dieser Kategorie werden im Shop in
# Kategorie X gezeigt").
#
# Drag-and-Drop zwischen (oder innerhalb) der Bäume: Knoten auf einen anderen
# Knoten ziehen → Menü:
#   Verschieben    Knoten samt Unterbaum unter das Ziel hängen (parent)
#   Verschmelzen   Artikel des Knotens ins Ziel mappen (product_category_code),
#                  wahlweise inkl. Unterkategorien; der Knoten bleibt bestehen
# Gespeichert wird in dieselbe Datei (Backup in logs/), Import/Export wie bisher.
#
# Datenlogik ohne Tk: lib/category_tree.py

import copy
import os
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox, filedialog

from lib.design import FONT_UI, FONT_UI_SM, FONT_HEAD
from lib import category_tree as ct


class TreePane:
    """Eine Baumansicht (Baum-Auswahl, Suche, Treeview) – zwei davon im Reiter."""

    def __init__(self, tab: "KategorienTab", parent: tk.Frame, side: str):
        self.tab = tab
        self.side = side
        self._C = c = tab._C
        self.iid_to_code: dict = {}
        self.code_to_iid: dict = {}
        self._drag_src = None
        self._drag_active = False

        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        bar = tk.Frame(parent, bg=c["BG2"], pady=4, padx=6)
        bar.grid(row=0, column=0, sticky="ew")
        tk.Label(bar, text="Baum:", bg=c["BG2"], fg=c["FG"], font=FONT_UI_SM).pack(side="left")
        self.root_var = tk.StringVar()
        self.root_cb = ttk.Combobox(bar, textvariable=self.root_var, state="readonly", width=34, font=FONT_UI_SM)
        self.root_cb.pack(side="left", padx=(4, 10))
        self.root_cb.bind("<<ComboboxSelected>>", lambda e: self.fill())
        tk.Label(bar, text="Suche:", bg=c["BG2"], fg=c["FG"], font=FONT_UI_SM).pack(side="left")
        self.search_var = tk.StringVar()
        ent = tk.Entry(bar, textvariable=self.search_var, font=FONT_UI_SM, width=18)
        ent.pack(side="left", padx=4)
        ent.bind("<Return>", lambda e: self.fill())
        self.only_art = tk.BooleanVar(value=False)
        tk.Checkbutton(bar, text="nur mit Artikeln", variable=self.only_art, command=self.fill,
                       bg=c["BG2"], fg=c["FG"], selectcolor=c["BG3"], activebackground=c["BG2"],
                       font=FONT_UI_SM).pack(side="left", padx=6)

        frm = tk.Frame(parent, bg=c["BG"])
        frm.grid(row=1, column=0, sticky="nsew")
        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(0, weight=1)
        cols = ("code", "total", "mapped", "online", "moved", "target")
        self.tree = ttk.Treeview(frm, columns=cols, show="tree headings", selectmode="browse",
                                 style="KAT.Treeview")
        self.tree.heading("#0", text="Kategorie")
        self.tree.column("#0", width=260, minwidth=140, stretch=True)
        for key, head, w, anchor in (("code", "Code", 100, "w"), ("total", "Artikel", 60, "e"),
                                     ("mapped", "→hier", 55, "e"), ("online", "On", 32, "center"),
                                     ("moved", "verschoben aus", 150, "w"), ("target", "Ziel", 170, "w")):
            self.tree.heading(key, text=head)
            self.tree.column(key, width=w, minwidth=30, stretch=(key == "target"), anchor=anchor)
        self.tree.tag_configure("offline", foreground=c.get("FG_DIM", "#888"))
        self.tree.tag_configure("mapped", foreground=c["ACCENT"])
        self.tree.tag_configure("moved", foreground=c.get("WARN", "#c98a00"))          # im Shop schon umgehängt
        self.tree.tag_configure("moved_now", foreground=c.get("OK", "#2e9e4f"),
                                font=("Segoe UI Semibold", 10))                        # in dieser Sitzung verschoben
        self.tree.tag_configure("incoming", foreground=c["ACCENT"], font=("Segoe UI", 10, "italic"))  # verschmolzene Quelle
        self.tree.tag_configure("incoming_now", foreground=c.get("OK", "#2e9e4f"),
                                font=("Segoe UI Semibold", 10, "italic"))              # in dieser Sitzung verschmolzen
        vsb = ttk.Scrollbar(frm, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", lambda e: tab.on_select(self))
        self.tree.bind("<Double-1>", lambda e: tab.show_articles())
        # Drag & Drop
        self.tree.bind("<ButtonPress-1>", self._drag_start, add="+")
        self.tree.bind("<B1-Motion>", self._drag_motion, add="+")
        self.tree.bind("<ButtonRelease-1>", self._drag_end, add="+")

    # ── Inhalt ────────────────────────────────────────────────────────────────

    def set_roots(self, roots, prefer_code: str = None):
        labels = [f"{r.name}  ({r.code})  –  {self.tab.count_desc(r)} Kat." for r in roots]
        self.root_cb.config(values=labels)
        if labels:
            idx = next((i for i, r in enumerate(roots) if r.code == prefer_code), None)
            if idx is None:
                idx = 0
            self.root_cb.current(idx)

    def current_root(self):
        idx = self.root_cb.current()
        return self.tab._roots[idx] if 0 <= idx < len(self.tab._roots) else None

    def fill(self, keep_selection: bool = True):
        sel_key = self.selected_key() if keep_selection else None
        open_keys = {self.iid_to_code[i] for i in self.iid_to_code if self.tree.item(i, "open")} if keep_selection else set()
        self.tree.delete(*self.tree.get_children())
        self.iid_to_code.clear()
        self.code_to_iid.clear()
        root = self.current_root()
        if not root:
            return
        nodes = self.tab._nodes
        q = self.search_var.get().strip().lower()
        only = self.only_art.get()
        # Verschmolzene Quellen je Ziel (product_category_code → hierher)
        incoming: dict = {}
        for s_ in nodes.values():
            if s_.target and s_.target.upper() != s_.key:
                incoming.setdefault(s_.target.upper(), []).append(s_)

        def _matches(n) -> bool:
            if only and n.total == 0 and n.mapped_in == 0:
                return False
            if q and q not in n.name.lower() and q not in n.code.lower() and q not in (n.target or "").lower():
                return False
            return True

        def _visible(n) -> bool:
            return _matches(n) or any(_visible(c) for c in n.children)

        def _insert(n, parent_iid, open_):
            if (q or only) and not _visible(n):
                return
            tgt_txt = ""
            if n.target:
                tp = ct.path_of(nodes, n.target)
                tgt_txt = f"{n.target}  {tp}" if tp else f"{n.target} (?)"
            moved_txt = ""
            moved_now = n.key in self.tab._moved_keys
            moved_before = bool(n.original_parent) and n.original_parent.upper() != n.parent.upper()
            if moved_now or moved_before:
                op = n.original_parent.upper()
                src_name = nodes[op].name if op in nodes else (n.original_parent or "?")
                moved_txt = ("↪ " if moved_now else "") + src_name
            tags = (["offline"] if not n.online else []) + (["mapped"] if n.target else [])
            if moved_now:
                tags.append("moved_now")
            elif moved_before:
                tags.append("moved")
            text = ("↪ " if moved_now else "") + (n.name or n.code)
            iid = self.tree.insert(parent_iid, "end", text=text,
                                   open=open_ or (n.key in open_keys),
                                   values=(n.code, n.total or "", n.mapped_in or "",
                                           "✓" if n.online else "–", moved_txt, tgt_txt), tags=tuple(tags))
            self.iid_to_code[iid] = n.key
            self.code_to_iid[n.key] = iid
            for ch in n.children:
                _insert(ch, iid, bool(q))
            # Verschmolzene Quellen aus anderen Bäumen als eingehängte Zeilen zeigen
            for s_ in sorted(incoming.get(n.key, []), key=lambda x: -x.total):
                if (q or only) and not _matches(s_):
                    continue
                r_ = ct.root_of(nodes, s_.key)
                origin = f" (aus {r_.name})" if r_ and r_ is not self.current_root() else ""
                tag = "incoming_now" if s_.key in self.tab._merged_keys else "incoming"
                viid = self.tree.insert(iid, "end", text=f"⇐ {s_.name or s_.code}{origin}", open=False,
                                        values=(s_.code, s_.total or "", "", "✓" if s_.online else "–",
                                                "verschmolzen", f"→ {n.code}"), tags=(tag,))
                self.iid_to_code[viid] = s_.key

        _insert(root, "", True)
        if sel_key and sel_key in self.code_to_iid:
            iid = self.code_to_iid[sel_key]
            self.tree.selection_set(iid)
            self.tree.see(iid)

    def selected_key(self):
        sel = self.tree.selection()
        return self.iid_to_code.get(sel[0]) if sel else None

    def goto(self, key: str) -> bool:
        if key not in self.tab._nodes:
            return False
        root = ct.root_of(self.tab._nodes, key)
        if root and root is not self.current_root():
            self.root_cb.current(self.tab._roots.index(root))
            self.search_var.set("")
            self.fill(keep_selection=False)
        iid = self.code_to_iid.get(key)
        if not iid:
            self.search_var.set("")
            self.only_art.set(False)
            self.fill(keep_selection=False)
            iid = self.code_to_iid.get(key)
        if iid:
            self.tree.see(iid)
            self.tree.selection_set(iid)
            self.tree.focus(iid)
            return True
        return False

    # ── Drag & Drop ───────────────────────────────────────────────────────────

    def _drag_start(self, e):
        iid = self.tree.identify_row(e.y)
        self._drag_src = self.iid_to_code.get(iid) if iid else None
        self._drag_active = False

    def _drag_motion(self, e):
        if self._drag_src and not self._drag_active:
            self._drag_active = True
            self.tree.configure(cursor="hand2")
            self.tab.status(f"Ziehe {self._drag_src} … auf Zielkategorie ablegen")

    def _drag_end(self, e):
        self.tree.configure(cursor="")
        src, active = self._drag_src, self._drag_active
        self._drag_src, self._drag_active = None, False
        if not src or not active:
            return
        widget = self.tree.winfo_containing(e.x_root, e.y_root)
        pane = self.tab.pane_for_widget(widget)
        if not pane:
            self.tab.status("Abgelegt außerhalb eines Baums – nichts geändert.")
            return
        y = e.y_root - pane.tree.winfo_rooty()
        iid = pane.tree.identify_row(y)
        dst = pane.iid_to_code.get(iid) if iid else None
        if not dst or dst == src:
            self.tab.status("Kein Ziel getroffen – nichts geändert.")
            return
        self.tab.drop_menu(src, dst, e.x_root, e.y_root)


class KategorienTab:

    def __init__(self, parent: tk.Frame, app, colors: dict):
        self._C = colors
        self._app = app
        self._parent = parent
        import config as _cfg
        self._cfg = _cfg
        self._rows, self._fields, self._enc = [], [], "cp1252"
        self._rows_loaded = []
        self._nodes, self._roots = {}, []
        self._counts = {}
        self._dirty = False
        self._loaded = False
        self._active_pane = None
        self._moved_keys: set = set()        # in dieser Sitzung verschobene Knoten
        self._merged_keys: set = set()       # in dieser Sitzung verschmolzene Knoten
        self._build()

    # ── Aufbau ────────────────────────────────────────────────────────────────

    def _build(self):
        c = self._C
        p = self._parent
        p.columnconfigure(0, weight=1)
        p.rowconfigure(1, weight=1)

        sty = ttk.Style()
        sty.configure("KAT.Treeview", background=c["BG3"], foreground=c.get("FG_INPUT", c["FG"]),
                      fieldbackground=c["BG3"], rowheight=22, font=FONT_UI)
        sty.configure("KAT.Treeview.Heading", background=c["BG2"], foreground=c["FG"],
                      font=("Segoe UI Semibold", 10), relief="flat")
        sty.map("KAT.Treeview", background=[("selected", c["ACCENT"])], foreground=[("selected", "#ffffff")])

        bar = tk.Frame(p, bg=c["BG2"], pady=6, padx=10)
        bar.grid(row=0, column=0, sticky="ew")
        tk.Label(bar, text="Kategorien – zwei Bäume nebeneinander, Knoten per Drag & Drop verschieben "
                           "oder verschmelzen", bg=c["BG2"], fg=c["FG"], font=FONT_UI).pack(side="left")
        self._save_btn = tk.Button(bar, text="💾 Speichern", command=self._save, state="disabled",
                                   bg=c["ACCENT"], fg="#fff", relief="flat", cursor="hand2", font=FONT_UI, padx=10)
        self._save_btn.pack(side="right", padx=4)
        tk.Button(bar, text="↻ Neu laden", command=lambda: self.load(force=True), bg=c["BG3"], fg=c["FG"],
                  relief="flat", cursor="hand2", font=FONT_UI, padx=8).pack(side="right")
        tk.Button(bar, text="⬆ Für Shop exportieren …", command=self._export, bg=c["BG3"], fg=c["FG"],
                  relief="flat", cursor="hand2", font=FONT_UI, padx=8).pack(side="right", padx=4)
        tk.Button(bar, text="⬇ Shop-Export importieren …", command=self._import, bg=c["BG3"], fg=c["FG"],
                  relief="flat", cursor="hand2", font=FONT_UI, padx=8).pack(side="right", padx=4)
        self._status = tk.Label(bar, text="", bg=c["BG2"], fg=c.get("FG_DIM", c["FG"]), font=FONT_UI_SM)
        self._status.pack(side="right", padx=10)

        pane = tk.PanedWindow(p, orient="horizontal", bg=c["BG"], sashwidth=6, sashrelief="raised")
        pane.grid(row=1, column=0, sticky="nsew")
        left = tk.Frame(pane, bg=c["BG"])
        right = tk.Frame(pane, bg=c["BG"])
        pane.add(left, minsize=360, width=620)
        pane.add(right, minsize=360, width=620)
        self._panes = [TreePane(self, left, "links"), TreePane(self, right, "rechts")]

        # Details unten
        det = tk.Frame(p, bg=c["BG2"], padx=12, pady=6)
        det.grid(row=2, column=0, sticky="ew")
        det.columnconfigure(1, weight=1)
        det.columnconfigure(3, weight=1)
        self._detail_vars = {}
        items = (("code", "Code"), ("path", "Pfad"), ("orig", "Original"), ("count", "Artikel"),
                 ("target", "Ziel im Shop"), ("sources", "Quellen hierher"))
        for i, (key, label) in enumerate(items):
            rr, cc = divmod(i, 2)
            tk.Label(det, text=label + ":", bg=c["BG2"], fg=c.get("FG_DIM", c["FG"]), font=FONT_UI_SM).grid(
                row=rr, column=cc * 2, sticky="ne", padx=(0, 6), pady=1)
            v = tk.StringVar()
            self._detail_vars[key] = v
            tk.Label(det, textvariable=v, bg=c["BG2"], fg=c["FG"], font=FONT_UI_SM, anchor="w",
                     justify="left", wraplength=560).grid(row=rr, column=cc * 2 + 1, sticky="w", pady=1)
        btns = tk.Frame(det, bg=c["BG2"])
        btns.grid(row=3, column=0, columnspan=4, sticky="w", pady=(6, 0))
        self._btns = {}
        for key, text, cmd in (("pick", "Ziel wählen …", self._pick_target),
                               ("clear", "Ziel entfernen", self._clear_target),
                               ("goto", "Zum Ziel (anderer Baum)", self._goto_target),
                               ("arts", "Artikel anzeigen", self.show_articles),
                               ("online", "Online an/aus", self._toggle_online)):
            b = tk.Button(btns, text=text, command=cmd, bg=c["BG3"], fg=c["FG"], relief="flat",
                          cursor="hand2", font=FONT_UI_SM, padx=8, state="disabled")
            b.pack(side="left", padx=(0, 6))
            self._btns[key] = b
        tk.Label(btns, text="Drag & Drop: Knoten auf Ziel ziehen → Verschieben oder Verschmelzen. "
                            "Grün ↪ = in dieser Sitzung verschoben, orange = im Shop umgehängt, "
                            "⇐ kursiv = verschmolzene Quelle unter ihrem Ziel. Erst mit Speichern wirksam.",
                 bg=c["BG2"], fg=c.get("FG_DIM", c["FG"]), font=FONT_UI_SM).pack(side="left", padx=(12, 0))

    def status(self, text: str):
        self._status.config(text=text)

    def pane_for_widget(self, widget):
        for pn in self._panes:
            if widget is not None and str(widget).startswith(str(pn.tree)):
                return pn
        return None

    def count_desc(self, node) -> int:
        n, stack = 0, list(node.children)
        while stack:
            x = stack.pop()
            n += 1
            stack.extend(x.children)
        return n

    # ── Laden ─────────────────────────────────────────────────────────────────

    def on_tab_activated(self):
        if not self._loaded:
            self.load()

    def load(self, force: bool = False):
        if self._dirty and force and not messagebox.askyesno(
                "Ungespeicherte Änderungen", "Änderungen verwerfen und neu laden?", parent=self._parent):
            return
        self.status("Lade …")

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
        self._moved_keys = set()
        self._merged_keys = set()
        self._save_btn.config(state="disabled")
        self._loaded = True
        # links Zentralshop, rechts der erste Lieferantenbaum
        self._panes[0].set_roots(roots, prefer_code="1")
        other = next((r.code for r in roots if r.code != "1"), None)
        self._panes[1].set_roots(roots, prefer_code=other)
        for pn in self._panes:
            pn.fill(keep_selection=False)
        self.status("custom_categories.csv nicht gefunden (BASE_DIR)" if not rows else
                    f"{len(nodes)} Kategorien, {len(roots)} Bäume" + (f"  ⚠ {err}" if err else ""))
        self.on_select(self._panes[0])

    def _refresh(self, select_key: str = None, pane: TreePane = None):
        ct.apply_counts(self._nodes, self._roots, self._counts)
        for pn in self._panes:
            pn.set_roots(self._roots, prefer_code=(pn.current_root().code if pn.current_root() else None))
            pn.fill()
        if select_key and pane:
            pane.goto(select_key)
        self.on_select(pane or self._active_pane)

    def _mark_dirty(self):
        self._dirty = True
        self._save_btn.config(state="normal")

    # ── Auswahl / Details ─────────────────────────────────────────────────────

    def _selected(self):
        pn = self._active_pane
        if not pn:
            return None
        return self._nodes.get(pn.selected_key() or "")

    def on_select(self, pane: TreePane):
        self._active_pane = pane
        n = self._selected()
        v = self._detail_vars
        for b in self._btns.values():
            b.config(state="disabled")
        if not n:
            for var in v.values():
                var.set("")
            return
        v["code"].set(f"{n.code}   {n.name}   [{pane.side}]")
        v["path"].set(ct.path_of(self._nodes, n.code))
        orig = []
        if n.original_name and n.original_name != n.name:
            orig.append(f"Name: {n.original_name}")
        if n.original_parent and n.original_parent.upper() != n.parent.upper():
            orig.append(f"Parent: {n.original_parent} ({ct.path_of(self._nodes, n.original_parent) or '?'})")
        v["orig"].set("; ".join(orig) if orig else "unverändert")
        v["count"].set(f"{n.direct} direkt, {n.total} inkl. Unterkategorien"
                       + (f", {n.mapped_in} per Mapping hierher" if n.mapped_in else "")
                       + ("" if n.online else "   (offline)"))
        if n.target:
            tp = ct.path_of(self._nodes, n.target)
            v["target"].set(f"{n.target}  {tp}" if tp else f"{n.target} (nicht im Baum)")
        else:
            v["target"].set("– (Artikel bleiben in dieser Kategorie)")
        srcs = sorted(ct.sources_for(self._nodes, n.code), key=lambda x: -x.total)
        v["sources"].set("; ".join(f"{s.code} [{s.total}]" for s in srcs[:8])
                         + (f" … (+{len(srcs) - 8})" if len(srcs) > 8 else "") if srcs else "–")
        self._btns["pick"].config(state="normal")
        self._btns["online"].config(state="normal")
        self._btns["clear"].config(state="normal" if n.target else "disabled")
        self._btns["goto"].config(state="normal" if n.target and n.target.upper() in self._nodes else "disabled")
        self._btns["arts"].config(state="normal" if n.direct else "disabled")

    def _other_pane(self, pane: TreePane) -> TreePane:
        return self._panes[1] if pane is self._panes[0] else self._panes[0]

    def _goto_target(self):
        n = self._selected()
        if n and n.target and self._active_pane:
            self._other_pane(self._active_pane).goto(n.target.upper())

    # ── Änderungen ────────────────────────────────────────────────────────────

    def _set_target(self, n, target: str, with_children: bool = False) -> int:
        target = (target or "").strip()
        if target.upper() == n.key:
            messagebox.showwarning("Ungültig", "Eine Kategorie kann nicht auf sich selbst zeigen.", parent=self._parent)
            return 0
        if "product_category_code" not in self._fields:
            self._fields.append("product_category_code")
        todo = [n]
        if with_children:
            stack = list(n.children)
            while stack:
                x = stack.pop()
                todo.append(x)
                stack.extend(x.children)
        for x in todo:
            if x.key == target.upper():
                continue
            x.target = target
            x.row["product_category_code"] = target
            if target:
                self._merged_keys.add(x.key)
            else:
                self._merged_keys.discard(x.key)
        self._mark_dirty()
        return len(todo)

    def _clear_target(self):
        n = self._selected()
        if n:
            self._set_target(n, "")
            self._refresh(n.key, self._active_pane)

    def _pick_target(self):
        n = self._selected()
        if not n:
            return
        pane = self._active_pane
        TargetPicker(self._parent, self, n,
                     lambda code: (self._set_target(n, code), self._refresh(n.key, pane)))

    def _toggle_online(self):
        n = self._selected()
        if not n:
            return
        n.online = not n.online
        n.row["online"] = "1" if n.online else "0"
        self._mark_dirty()
        self._refresh(n.key, self._active_pane)

    def drop_menu(self, src_key: str, dst_key: str, x: int, y: int):
        src, dst = self._nodes.get(src_key), self._nodes.get(dst_key)
        if not src or not dst:
            return
        m = tk.Menu(self._parent, tearoff=0)
        m.add_command(label=f"Verschieben: '{src.name}' samt Unterbaum unter '{dst.name}' hängen",
                      command=lambda: self._do_move(src, dst))
        m.add_separator()
        m.add_command(label=f"Verschmelzen: Artikel von '{src.name}' in '{dst.name}' zeigen",
                      command=lambda: self._do_merge(src, dst, False))
        if src.children:
            m.add_command(label=f"Verschmelzen inkl. Unterkategorien ({self.count_desc(src)}) → '{dst.name}'",
                          command=lambda: self._do_merge(src, dst, True))
        m.add_separator()
        m.add_command(label="Abbrechen")
        try:
            m.tk_popup(x, y)
        finally:
            m.grab_release()

    def _do_move(self, src, dst):
        err = ct.move_node(self._nodes, self._roots, src.code, dst.code)
        if err:
            messagebox.showwarning("Verschieben nicht möglich", err, parent=self._parent)
            return
        self._mark_dirty()
        self._moved_keys.add(src.key)
        self._refresh(src.key, self._pane_showing(dst.key) or self._active_pane)
        self.status(f"Verschoben: {src.code} → unter {dst.code} ({dst.name})  (ungespeichert)")

    def _do_merge(self, src, dst, with_children: bool):
        n = self._set_target(src, dst.code, with_children)
        if n:
            self._refresh(src.key, self._active_pane)
            self.status(f"Verschmolzen: {n} Kategorie(n) → Ziel {dst.code} ({dst.name})  (ungespeichert)")

    def _pane_showing(self, key: str):
        for pn in self._panes:
            if key in pn.code_to_iid:
                return pn
        return None

    # ── Artikel ───────────────────────────────────────────────────────────────

    def show_articles(self):
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
        if self._dirty and not messagebox.askyesno(
                "Ungespeicherte Änderungen",
                "Es gibt ungespeicherte Änderungen. Trotzdem importieren und verwerfen?", parent=self._parent):
            return
        path = filedialog.askopenfilename(title="Kategorien-Export des Shops wählen", parent=self._parent,
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
        msg = (f"{len(rows)} Kategorien in {os.path.basename(path)}.\n\nGegenüber dem aktuellen Stand:\n"
               f"  {len(d['added'])} neue Kategorien\n  {len(d['removed'])} entfallen\n"
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
            self._app._append_log(f"Kategorien: {os.path.basename(path)} importiert – {len(rows)} Kategorien, "
                                  f"{len(d['added'])} neu, {len(d['removed'])} entfallen, "
                                  f"{len(d['target_changed'])} Ziele geändert.", tag="ok")
        except Exception:
            pass
        self._dirty = False
        self.load(force=True)

    def _export(self):
        if not self._rows:
            return
        if self._dirty and messagebox.askyesno("Ungespeichert", "Änderungen zuerst in custom_categories.csv speichern?",
                                               parent=self._parent):
            self._save()
        d = ct.diff_rows(self._rows_loaded, self._rows)
        out_dir = self._cfg.DIRS.get("pim_export") or self._cfg.BASE_DIR
        default = f"custom_categories_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        path = filedialog.asksaveasfilename(title="Kategorien für den Shop exportieren", parent=self._parent,
                                            initialdir=out_dir if os.path.isdir(out_dir) else self._cfg.BASE_DIR,
                                            initialfile=default, defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            ct.write_file(path, self._rows, self._fields, self._enc)
        except Exception as exc:
            messagebox.showerror("Export fehlgeschlagen", str(exc), parent=self._parent)
            return
        self.status(f"Exportiert: {os.path.basename(path)} ({len(self._rows)} Kategorien)")
        try:
            self._app._append_log(f"Kategorien: {os.path.basename(path)} für den Shop geschrieben – "
                                  f"{len(self._rows)} Kategorien, {len(d['target_changed'])} Ziel-Änderungen, "
                                  f"{len(d['moved'])} umgehängt seit dem letzten Laden.", tag="ok")
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
        d = ct.diff_rows(self._rows_loaded, self._rows)
        self._rows_loaded = copy.deepcopy(self._rows)
        self._dirty = False
        self._save_btn.config(state="disabled")
        self.status(f"Gespeichert: {os.path.basename(path)} (Backup in logs/)")
        try:
            self._app._append_log(f"Kategorien: {os.path.basename(path)} gespeichert – "
                                  f"{len(d['target_changed'])} Ziele geändert, {len(d['moved'])} umgehängt.", tag="ok")
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
        self._tree = ttk.Treeview(frm, columns=("code", "total"), show="tree headings", selectmode="browse",
                                  style="KAT.Treeview")
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
