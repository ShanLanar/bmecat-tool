# lib/single_article_dialog.py – Dialog: Einzelartikel aus der PIM-DB in
# eine bestehende BMEcat-Katalog-XML exportieren.
#
# Suche → Trefferliste → Ziel-XML wählen → Export. Die eigentliche Logik
# (Rendern + chirurgisches Einfügen/Ersetzen) steckt in
# lib/single_article_export.py; hier nur die Bedienoberfläche.

import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

_FONT      = ("Segoe UI", 10)
_FONT_MONO = ("Consolas", 9)
_FONT_SM   = ("Segoe UI", 8)


class SingleArticleExportDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        from lib.design import THEMES
        self._app = app
        self._c   = THEMES[app._theme]
        self._target_path = None
        self._selected_id = None

        self.title("Einzelartikel-Export in bestehenden BMEcat")
        self.geometry("780x520")
        self.configure(bg=self._c["BG"])
        self.transient(app)

        self._build()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build(self):
        c = self._c

        # Suche
        top = tk.Frame(self, bg=c["BG"], padx=12, pady=10)
        top.pack(fill="x")
        tk.Label(top, text="Suche (Artikelnummer, EAN oder Bezeichnung):",
                 font=_FONT, bg=c["BG"], fg=c["FG"]).pack(anchor="w")
        row = tk.Frame(top, bg=c["BG"])
        row.pack(fill="x", pady=(4, 0))
        self._search_var = tk.StringVar()
        entry = tk.Entry(row, textvariable=self._search_var, font=_FONT)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda e: self._do_search())
        tk.Button(row, text="Suchen", command=self._do_search,
                  font=_FONT, bg=c["ACCENT"], fg="#fff", relief="flat",
                  bd=0, cursor="hand2", padx=12).pack(side="left", padx=(6, 0))

        # Trefferliste
        mid = tk.Frame(self, bg=c["BG"], padx=12)
        mid.pack(fill="both", expand=True)
        cols = ("product_id", "supplier", "ean", "desc", "status")
        self._tree = ttk.Treeview(mid, columns=cols, show="headings", height=10)
        for key, label, width in [
            ("product_id", "Artikelnummer", 130),
            ("supplier",   "Lieferant",     100),
            ("ean",        "EAN",           110),
            ("desc",       "Bezeichnung",   280),
            ("status",     "Status",         90),
        ]:
            self._tree.heading(key, text=label)
            self._tree.column(key, width=width, anchor="w")
        self._tree.pack(fill="both", expand=True, side="left")
        sb = ttk.Scrollbar(mid, orient="vertical", command=self._tree.yview)
        sb.pack(side="right", fill="y")
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.bind("<<TreeviewSelect>>", self._on_select)
        self._rows_by_iid = {}

        # Ziel-Datei + Export
        bottom = tk.Frame(self, bg=c["BG"], padx=12, pady=10)
        bottom.pack(fill="x")

        self._target_lbl = tk.Label(bottom, text="Ziel-XML: (noch keine gewählt)",
                                    font=_FONT_SM, bg=c["BG"], fg=c["FG"])
        self._target_lbl.pack(anchor="w")

        btn_row = tk.Frame(bottom, bg=c["BG"])
        btn_row.pack(fill="x", pady=(6, 0))
        tk.Button(btn_row, text="Ziel-XML wählen …", command=self._choose_target,
                  font=_FONT, bg=c["BG2"], fg=c["FG"], relief="flat",
                  bd=0, cursor="hand2", padx=10, pady=4).pack(side="left")
        self._export_btn = tk.Button(
            btn_row, text="In Ziel-XML exportieren", command=self._do_export,
            font=_FONT, bg=c["ACCENT"], fg="#fff", relief="flat",
            bd=0, cursor="hand2", padx=10, pady=4, state="disabled")
        self._export_btn.pack(side="left", padx=(6, 0))

        self._log = tk.Text(self, height=6, font=_FONT_MONO, bg=c["BG2"], fg=c["FG"],
                            relief="flat", bd=0)
        self._log.pack(fill="x", padx=12, pady=(0, 12))
        self._log.configure(state="disabled")

    def _log_line(self, msg: str):
        self._log.configure(state="normal")
        self._log.insert("end", msg + "\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    # ── Suche ─────────────────────────────────────────────────────────────────

    def _do_search(self):
        term = self._search_var.get().strip()
        for item in self._tree.get_children():
            self._tree.delete(item)
        self._rows_by_iid.clear()
        self._selected_id = None
        self._export_btn.config(state="disabled")

        if not term:
            return
        try:
            import config
            from lib.article_db import open_db, search_articles
            con = open_db(config.DB_PATH)
            try:
                hits = search_articles(con, term)
            finally:
                con.close()
        except Exception as e:
            messagebox.showerror("Suche fehlgeschlagen", str(e), parent=self)
            return

        for h in hits:
            status = "online" if (h.get("online") and h.get("active")) else "offline"
            iid = str(h["id"])
            self._tree.insert("", "end", iid=iid, values=(
                h.get("product_id", ""), h.get("supplier_name", ""),
                h.get("ean", ""), h.get("description_short", ""), status,
            ))
            self._rows_by_iid[iid] = h

        if not hits:
            self._log_line(f"Keine Treffer für '{term}'.")

    def _on_select(self, event=None):
        sel = self._tree.selection()
        if not sel:
            self._selected_id = None
        else:
            self._selected_id = int(sel[0])
        self._export_btn.config(
            state="normal" if (self._selected_id and self._target_path) else "disabled")

    # ── Ziel-Datei ────────────────────────────────────────────────────────────

    def _choose_target(self):
        import config
        path = filedialog.askopenfilename(
            parent=self,
            title="Ziel-BMEcat-XML wählen",
            initialdir=config.BASE_DIR,
            filetypes=[("XML-Dateien", "*.xml"), ("Alle Dateien", "*.*")],
        )
        if not path:
            return
        self._target_path = path
        self._target_lbl.config(text=f"Ziel-XML: {path}")
        self._export_btn.config(
            state="normal" if (self._selected_id and self._target_path) else "disabled")

    # ── Export ────────────────────────────────────────────────────────────────

    def _do_export(self):
        if not (self._selected_id and self._target_path):
            return
        row = self._rows_by_iid.get(str(self._selected_id))
        pid = row.get("product_id", "") if row else str(self._selected_id)

        if not messagebox.askyesno(
                "Export bestätigen",
                f"Artikel {pid} in\n{self._target_path}\neinfügen bzw. dort "
                f"vorhandenen Artikel ersetzen?\n\nEs wird vorher ein .bak "
                f"der Zieldatei angelegt.", parent=self):
            return

        try:
            import config
            from lib.article_db import open_db
            from lib.single_article_export import (
                load_full_article, render_article_block, insert_or_replace_article,
            )
            con = open_db(config.DB_PATH)
            try:
                art = load_full_article(con, self._selected_id)
                if not art:
                    raise RuntimeError("Artikel nicht mehr in der Datenbank gefunden.")
                article_xml, catalog_map_xml = render_article_block(art, con=con)
            finally:
                con.close()

            result = insert_or_replace_article(
                self._target_path, art["product_id"], article_xml, catalog_map_xml,
                progress_cb=lambda m, **kw: self._log_line(m))

            self._log_line(f"✓ {pid}: Artikel {result['article']}"
                           + (f", Katalogzuordnung {result['catalog_map']}"
                              if result['catalog_map'] else "")
                           + f". Backup: {os.path.basename(result['backup'])}")
            messagebox.showinfo(
                "Export abgeschlossen",
                f"Artikel {pid} wurde in\n{self._target_path}\n"
                f"{result['article']} (Backup angelegt).", parent=self)
        except Exception as e:
            self._log_line(f"✗ Fehler: {e}")
            messagebox.showerror("Export fehlgeschlagen", str(e), parent=self)


def open_single_article_export_dialog(app):
    SingleArticleExportDialog(app)
