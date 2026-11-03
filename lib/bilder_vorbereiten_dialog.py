# lib/bilder_vorbereiten_dialog.py – Dialog "Bilder für Lieferant vorbereiten"
#
# Lieferant (aus der DB) + Kürzel + Quellordner wählen → lib/bilder_vorbereiten
# übernimmt nur die in der DB referenzierten Bilder als JPG mit Präfix nach
# DIRS["in"]. Läuft im Hintergrund-Thread, Ausgabe im Hauptlog.

import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

_FONT    = ("Segoe UI", 10)
_FONT_SM = ("Segoe UI", 8)


class BilderVorbereitenDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        from lib.design import THEMES
        import config as _cfg
        self._app = app
        self._cfg = _cfg
        self._c   = THEMES[app._theme]
        self._running = False

        self.title("Bilder für Lieferant vorbereiten")
        self.geometry("640x380")
        self.configure(bg=self._c["BG"])
        self.transient(app)

        self._suppliers = self._load_suppliers()
        self._build()

    def _load_suppliers(self) -> dict:
        """{supplier_name: abgeleitetes Kürzel} aus der DB (Präfix = product_id − supplier_pid)."""
        result = {}
        try:
            from lib.article_db import open_db
            con = open_db(self._cfg.DB_PATH)
            rows = con.execute("""
                SELECT s.supplier_name, a.product_id, a.supplier_pid
                FROM suppliers s
                JOIN articles a ON a.id = (
                    SELECT id FROM articles WHERE supplier_id = s.id AND active = 1 LIMIT 1)
                ORDER BY s.supplier_name
            """).fetchall()
            con.close()
            for r in rows:
                pid, spid = r["product_id"] or "", r["supplier_pid"] or ""
                pfx = pid[:-len(spid)] if spid and pid.endswith(spid) else ""
                result[r["supplier_name"]] = pfx
        except Exception:
            pass
        manual = getattr(self._cfg, "MANUAL_IMPORT_PREFIXES", {}) or {}
        for name, pfx in manual.items():
            result.setdefault(name, pfx)
        return result

    def _build(self):
        c = self._c
        frm = tk.Frame(self, bg=c["BG"], padx=14, pady=12)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        def label(text, r):
            tk.Label(frm, text=text, font=_FONT, bg=c["BG"], fg=c["FG"]).grid(
                row=r, column=0, sticky="e", padx=(0, 8), pady=4)

        label("Lieferant:", 0)
        self._sup_var = tk.StringVar()
        cb = ttk.Combobox(frm, textvariable=self._sup_var, state="readonly",
                          values=sorted(self._suppliers), font=_FONT)
        cb.grid(row=0, column=1, columnspan=2, sticky="ew", pady=4)
        cb.bind("<<ComboboxSelected>>", self._on_supplier)

        label("Kürzel (Präfix):", 1)
        self._pfx_var = tk.StringVar()
        tk.Entry(frm, textvariable=self._pfx_var, font=_FONT, width=12).grid(
            row=1, column=1, sticky="w", pady=4)

        label("Quellordner:", 2)
        self._src_var = tk.StringVar()
        tk.Entry(frm, textvariable=self._src_var, font=_FONT).grid(
            row=2, column=1, sticky="ew", pady=4)
        tk.Button(frm, text="…", command=self._browse, font=_FONT, bg=c["BG3"],
                  fg=c["FG"], relief="flat", padx=8).grid(row=2, column=2, padx=(6, 0))

        label("Ziel:", 3)
        dest = self._cfg.DIRS.get("in", "")
        tk.Label(frm, text=dest, font=_FONT_SM, bg=c["BG"], fg=c["FG_DIM"]).grid(
            row=3, column=1, columnspan=2, sticky="w")

        self._move_var = tk.BooleanVar(value=False)
        tk.Checkbutton(frm, text="Quelldateien nach Übernahme löschen (statt kopieren)",
                       variable=self._move_var, font=_FONT_SM, bg=c["BG"], fg=c["FG"],
                       selectcolor=c["BG3"], activebackground=c["BG"]).grid(
            row=4, column=1, columnspan=2, sticky="w", pady=(6, 2))

        info = ("Übernommen werden nur Bilder, die ein aktiver Artikel des Lieferanten in der\n"
                "Datenbank referenziert (Zuordnung über den Dateinamen ohne Endung). Andere\n"
                "Formate werden nach JPG konvertiert, die Datei heißt dann Kürzel + Name.jpg.\n"
                "Danach: Task 'Bilder-Upload (Allago + OfficeXL)'.")
        tk.Label(frm, text=info, font=_FONT_SM, bg=c["BG"], fg=c["FG_DIM"],
                 justify="left").grid(row=5, column=0, columnspan=3, sticky="w", pady=(10, 4))

        self._status = tk.Label(frm, text="", font=_FONT_SM, bg=c["BG"], fg=c["FG"],
                                justify="left", wraplength=580)
        self._status.grid(row=6, column=0, columnspan=3, sticky="w", pady=(4, 8))

        btns = tk.Frame(frm, bg=c["BG"])
        btns.grid(row=7, column=0, columnspan=3, sticky="e")
        self._start_btn = tk.Button(btns, text="Start", command=self._start, font=_FONT,
                                    bg=c["ACCENT"], fg="#fff", relief="flat", bd=0,
                                    cursor="hand2", padx=14, pady=4)
        self._start_btn.pack(side="left", padx=4)
        tk.Button(btns, text="Schließen", command=self.destroy, font=_FONT, bg=c["BG3"],
                  fg=c["FG"], relief="flat", bd=0, padx=14, pady=4).pack(side="left", padx=4)

    def _on_supplier(self, _e=None):
        self._pfx_var.set(self._suppliers.get(self._sup_var.get(), ""))

    def _browse(self):
        d = filedialog.askdirectory(title="Quellordner mit Bildern", parent=self)
        if d:
            self._src_var.set(d)

    def _start(self):
        if self._running:
            return
        sup = self._sup_var.get().strip()
        pfx = self._pfx_var.get().strip().upper()
        src = self._src_var.get().strip()
        if not sup or not src:
            messagebox.showwarning("Angaben fehlen", "Bitte Lieferant und Quellordner wählen.",
                                   parent=self)
            return
        if pfx and not pfx.isalnum():
            messagebox.showwarning("Ungültiges Kürzel",
                                   "Das Kürzel darf nur Buchstaben und Ziffern enthalten.",
                                   parent=self)
            return
        if not os.path.isdir(src):
            messagebox.showwarning("Ordner fehlt", f"Quellordner nicht gefunden:\n{src}",
                                   parent=self)
            return
        try:
            import PIL  # noqa: F401
        except ImportError:
            messagebox.showerror("Pillow fehlt",
                                 "Für die JPG-Konvertierung wird das Paket Pillow benötigt.\n"
                                 "Bitte install.bat ausführen (oder: py -m pip install Pillow).",
                                 parent=self)
            return

        self._running = True
        self._start_btn.config(state="disabled", text="Läuft …")
        self._status.config(text="Läuft – Fortschritt im Hauptlog.")
        log = self._app._append_log
        move = self._move_var.get()
        dest = self._cfg.DIRS.get("in", "")
        logs = self._cfg.DIRS.get("logs", "")

        def _fp(i, n):
            self.after(0, lambda: self._status.config(text=f"{i} von {n} Dateien geprüft …"))

        def _worker():
            try:
                from lib.bilder_vorbereiten import prepare_images
                r = prepare_images(self._cfg.DB_PATH, sup, pfx, src, dest, logs,
                                   move=move, progress_cb=log, file_progress_cb=_fp)
                if r:
                    txt = (f"Fertig: {r['copied']} kopiert, {r['converted']} konvertiert, "
                           f"{r['present']} vorhanden, {r['missing']} fehlen, "
                           f"{r['skipped']} nicht referenziert.")
                else:
                    txt = "Nichts übernommen – siehe Hauptlog."
            except Exception as exc:
                log(f"Bilder vorbereiten fehlgeschlagen: {exc}", tag="err")
                txt = f"Fehler: {exc}"
            self.after(0, lambda: (self._status.config(text=txt),
                                   self._start_btn.config(state="normal", text="Start")))
            self._running = False

        threading.Thread(target=_worker, daemon=True).start()


def open_bilder_vorbereiten_dialog(app):
    BilderVorbereitenDialog(app)
