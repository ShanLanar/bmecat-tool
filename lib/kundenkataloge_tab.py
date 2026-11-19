# lib/kundenkataloge_tab.py – Reiter "Kundenkataloge"
#
# Profile (kundenkataloge/<name>.json) anlegen, bearbeiten, duplizieren,
# löschen; Katalog erzeugen (lib/kundenkatalog.generate) im Hintergrund,
# Ausgabe im Hauptlog; Archiv der erzeugten Dateien je Profil.

import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from lib.design import FONT_UI, FONT_UI_SM, FONT_HEAD
from lib import kundenkatalog as kk

_FIELDS = [
    # (key, label, breite, hinweis)
    ("name",            "Profilname",         28, "Dateiname des Profils"),
    ("catalog_id",      "CATALOG_ID",         28, "z.B. ABE2026"),
    ("catalog_name",    "CATALOG_NAME",       40, ""),
    ("catalog_version", "CATALOG_VERSION",    10, ""),
    ("price_lists",     "PL-Nummer(n)",       20, "ERP-Preisliste(n), Komma-getrennt – Artikelmenge + Preis (nrp)"),
    ("price_mode",      "Preis",              10, "netto | brutto"),
    ("suppliers",       "Lieferanten",        40, "Reihenfolge der Stammdaten-Quelle (Namen, Komma); leer = supplier_priority.csv"),
    ("sources",         "Datenquellen",       12, "db,obs – Artikel-DB zuerst, OBS nur für Artikel, die die DB nicht hat"),
    ("aid_mode",        "Artikelnummer",      12, "native (ohne Präfix) | product_id (mit Präfix)"),
    ("match_order",     "Abgleich",           20, "Preisliste ↔ Artikel-DB: artnr (A_ARTNR), bestnr (A_BESTNR1-5), ean – Reihenfolge"),
    ("root_code",       "Zentralshop-Wurzel", 10, "Code in custom_categories.csv (Standard 1)"),
    ("group_system_id", "GROUP_SYSTEM_ID",    20, ""),
    ("group_system_name", "GROUP_SYSTEM_NAME", 28, ""),
    ("mime_root",       "MIME_ROOT",          40, "Bild-Basis-URL (optional)"),
    ("format",          "Format",             12, ", ".join(kk.RENDERERS)),
    ("notes",           "Notizen",            40, ""),
]
_SUPPLIER_FIELDS = [("id", "ILN/ID"), ("name", "Name"), ("name2", "Name 2"), ("contact", "Kontakt"),
                    ("street", "Straße"), ("zip", "PLZ"), ("city", "Ort"), ("country", "Land"),
                    ("phone", "Telefon"), ("fax", "Fax"), ("email", "E-Mail"), ("url", "URL")]
_BUYER_FIELDS = [("name", "Name"), ("name2", "Name 2"), ("contact", "Kontakt"), ("street", "Straße"),
                 ("zip", "PLZ"), ("city", "Ort"), ("country", "Land")]
_FLAGS = [("include_features", "Merkmale"), ("include_mimes", "Bilder/MIME"),
          ("include_keywords", "Keywords"), ("include_udx", "UDX"),
          ("postprocess", "Shop-Postprocessing (Blacklist, Offline, Regeln)")]


class KundenkatalogeTab:

    def __init__(self, parent: tk.Frame, app, colors: dict):
        self._C = colors
        self._app = app
        self._parent = parent
        import config as _cfg
        self._cfg = _cfg
        self._profiles: list = []
        self._current: dict | None = None
        self._vars: dict = {}
        self._sup_vars: dict = {}
        self._buy_vars: dict = {}
        self._flag_vars: dict = {}
        self._running = False
        self._build()
        self.reload()

    # ── Aufbau ────────────────────────────────────────────────────────────────

    def _build(self):
        c = self._C
        p = self._parent
        p.columnconfigure(1, weight=1)
        p.rowconfigure(0, weight=1)

        # Links: Profilliste
        left = tk.Frame(p, bg=c["BG2"], padx=8, pady=8)
        left.grid(row=0, column=0, sticky="nsw")
        tk.Label(left, text="Kundenkataloge", bg=c["BG2"], fg=c["FG"], font=FONT_HEAD).pack(anchor="w")
        self._list = tk.Listbox(left, width=30, height=18, bg=c["BG3"], fg=c.get("FG_INPUT", c["FG"]),
                                font=FONT_UI, relief="flat", activestyle="none",
                                selectbackground=c["ACCENT"], exportselection=False)
        self._list.pack(fill="both", expand=True, pady=(6, 6))
        self._list.bind("<<ListboxSelect>>", self._on_pick)
        for text, cmd in (("＋ Neu", self._new), ("⧉ Duplizieren", self._duplicate), ("✕ Löschen", self._delete)):
            tk.Button(left, text=text, command=cmd, bg=c["BG3"], fg=c["FG"], relief="flat",
                      cursor="hand2", font=FONT_UI_SM, padx=6).pack(fill="x", pady=1)

        # Rechts: Formular (scrollbar)
        right_outer = tk.Frame(p, bg=c["BG"])
        right_outer.grid(row=0, column=1, sticky="nsew")
        right_outer.rowconfigure(0, weight=1)
        right_outer.columnconfigure(0, weight=1)
        canvas = tk.Canvas(right_outer, bg=c["BG"], highlightthickness=0)
        vsb = ttk.Scrollbar(right_outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        form = tk.Frame(canvas, bg=c["BG"], padx=14, pady=10)
        win = canvas.create_window((0, 0), window=form, anchor="nw")
        form.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units")
                        if str(canvas.winfo_containing(e.x_root, e.y_root)).startswith(str(canvas)) else None)
        form.columnconfigure(1, weight=1)

        r = 0
        tk.Label(form, text="Profil", bg=c["BG"], fg=c["FG"], font=FONT_HEAD).grid(
            row=r, column=0, columnspan=3, sticky="w", pady=(0, 6)); r += 1
        for key, label, width, hint in _FIELDS:
            tk.Label(form, text=label + ":", bg=c["BG"], fg=c["FG"], font=FONT_UI, anchor="e").grid(
                row=r, column=0, sticky="e", padx=(0, 8), pady=2)
            v = tk.StringVar()
            self._vars[key] = v
            tk.Entry(form, textvariable=v, font=FONT_UI, width=width).grid(row=r, column=1, sticky="w", pady=2)
            if hint:
                tk.Label(form, text=hint, bg=c["BG"], fg=c.get("FG_DIM", c["FG"]), font=FONT_UI_SM).grid(
                    row=r, column=2, sticky="w", padx=(8, 0))
            r += 1
        fl = tk.Frame(form, bg=c["BG"])
        fl.grid(row=r, column=1, columnspan=2, sticky="w", pady=(4, 8)); r += 1
        for key, label in _FLAGS:
            v = tk.BooleanVar(value=True)
            self._flag_vars[key] = v
            tk.Checkbutton(fl, text=label, variable=v, bg=c["BG"], fg=c["FG"], selectcolor=c["BG3"],
                           activebackground=c["BG"], font=FONT_UI_SM).pack(side="left", padx=(0, 10))

        def _block(title, fields, store):
            nonlocal r
            tk.Label(form, text=title, bg=c["BG"], fg=c["FG"], font=FONT_HEAD).grid(
                row=r, column=0, columnspan=3, sticky="w", pady=(10, 4)); r += 1
            grid = tk.Frame(form, bg=c["BG"])
            grid.grid(row=r, column=0, columnspan=3, sticky="w"); r += 1
            for i, (key, label) in enumerate(fields):
                rr, cc = divmod(i, 3)
                tk.Label(grid, text=label + ":", bg=c["BG"], fg=c["FG"], font=FONT_UI_SM).grid(
                    row=rr, column=cc * 2, sticky="e", padx=(0, 4), pady=1)
                v = tk.StringVar()
                store[key] = v
                tk.Entry(grid, textvariable=v, font=FONT_UI_SM, width=26).grid(
                    row=rr, column=cc * 2 + 1, sticky="w", padx=(0, 14), pady=1)
        _block("Lieferant im Header (wir)", _SUPPLIER_FIELDS, self._sup_vars)
        _block("Käufer im Header (Kunde)", _BUYER_FIELDS, self._buy_vars)

        btns = tk.Frame(form, bg=c["BG"])
        btns.grid(row=r, column=0, columnspan=3, sticky="w", pady=(14, 6)); r += 1
        tk.Button(btns, text="💾 Profil speichern", command=self._save, bg=c["BG3"], fg=c["FG"],
                  relief="flat", cursor="hand2", font=FONT_UI, padx=10).pack(side="left", padx=(0, 6))
        self._gen_btn = tk.Button(btns, text="▶ Katalog erzeugen", command=self._generate, bg=c["ACCENT"],
                                  fg="#fff", relief="flat", cursor="hand2", font=FONT_UI, padx=12)
        self._gen_btn.pack(side="left", padx=(0, 6))
        tk.Button(btns, text="📂 Archiv öffnen", command=self._open_archive, bg=c["BG3"], fg=c["FG"],
                  relief="flat", cursor="hand2", font=FONT_UI, padx=10).pack(side="left")
        self._status = tk.Label(form, text="", bg=c["BG"], fg=c.get("FG_DIM", c["FG"]), font=FONT_UI_SM,
                                justify="left", wraplength=700)
        self._status.grid(row=r, column=0, columnspan=3, sticky="w"); r += 1

        tk.Label(form, text="Archiv (erzeugte Dateien):", bg=c["BG"], fg=c["FG"], font=FONT_UI_SM).grid(
            row=r, column=0, columnspan=3, sticky="w", pady=(10, 2)); r += 1
        self._archive = tk.Listbox(form, height=6, bg=c["BG3"], fg=c.get("FG_INPUT", c["FG"]), font=FONT_UI_SM,
                                   relief="flat", activestyle="none", selectbackground=c["ACCENT"])
        self._archive.grid(row=r, column=0, columnspan=3, sticky="ew"); r += 1
        self._archive.bind("<Double-1>", self._open_archive_file)

    # ── Profile ───────────────────────────────────────────────────────────────

    def reload(self, select: str = None):
        self._profiles = kk.list_profiles(self._cfg.BASE_DIR)
        self._list.delete(0, "end")
        for pr in self._profiles:
            tag = f"  [{pr['last_run']}]" if pr.get("last_run") else ""
            self._list.insert("end", f"{pr['name']}{tag}")
        idx = next((i for i, pr in enumerate(self._profiles) if pr["name"] == select), None)
        if idx is None and self._profiles:
            idx = 0
        if idx is not None:
            self._list.selection_set(idx)
            self._show(self._profiles[idx])
        else:
            self._show(None)

    def _on_pick(self, _e=None):
        sel = self._list.curselection()
        if sel:
            self._show(self._profiles[sel[0]])

    def _show(self, prof):
        self._current = prof
        src = prof or kk.DEFAULT_PROFILE
        for key, v in self._vars.items():
            v.set("" if src.get(key) is None else str(src.get(key)))
        for key, v in self._sup_vars.items():
            v.set((src.get("supplier") or {}).get(key, "") or "")
        for key, v in self._buy_vars.items():
            v.set((src.get("buyer") or {}).get(key, "") or "")
        for key, v in self._flag_vars.items():
            v.set(bool(src.get(key, True)))
        self._status.config(text=(f"Letzter Lauf: {prof.get('last_run')} → {prof.get('last_file')}"
                                  if prof and prof.get("last_run") else ""))
        self._fill_archive()

    def _collect(self) -> dict:
        prof = dict(self._current) if self._current else dict(kk.DEFAULT_PROFILE)
        for key, v in self._vars.items():
            prof[key] = v.get().strip()
        prof["supplier"] = {k: v.get().strip() for k, v in self._sup_vars.items()}
        prof["supplier"]["id_type"] = (self._current or {}).get("supplier", {}).get("id_type", "iln") or "iln"
        prof["buyer"] = {k: v.get().strip() for k, v in self._buy_vars.items()}
        for key, v in self._flag_vars.items():
            prof[key] = bool(v.get())
        return prof

    def _save(self, quiet=False) -> dict | None:
        prof = self._collect()
        if not prof.get("name"):
            messagebox.showwarning("Profilname fehlt", "Bitte einen Profilnamen eingeben.", parent=self._parent)
            return None
        try:
            kk.save_profile(self._cfg.BASE_DIR, prof)
        except Exception as exc:
            messagebox.showerror("Speichern fehlgeschlagen", str(exc), parent=self._parent)
            return None
        self.reload(select=prof["name"])
        if not quiet:
            self._status.config(text=f"Profil gespeichert: {prof['_path']}")
        return prof

    def _new(self):
        self._list.selection_clear(0, "end")
        self._show(None)
        self._vars["name"].set("neuer_kunde")

    def _duplicate(self):
        if not self._current:
            return
        prof = dict(self._current)
        prof.pop("_path", None)
        prof["name"] = prof["name"] + "_kopie"
        prof["last_run"] = prof["last_file"] = ""
        kk.save_profile(self._cfg.BASE_DIR, prof)
        self.reload(select=prof["name"])

    def _delete(self):
        if not self._current:
            return
        if not messagebox.askyesno("Profil löschen", f"Profil '{self._current['name']}' löschen?\n"
                                   "(Erzeugte Kataloge im Archiv bleiben erhalten.)", parent=self._parent):
            return
        kk.delete_profile(self._current)
        self.reload()

    # ── Erzeugen ──────────────────────────────────────────────────────────────

    def _generate(self):
        if self._running:
            return
        prof = self._save(quiet=True)
        if not prof:
            return
        if not prof.get("price_lists"):
            messagebox.showwarning("PL-Nummer fehlt", "Bitte mindestens eine Preislisten-Nummer eintragen.",
                                   parent=self._parent)
            return
        self._running = True
        self._gen_btn.config(state="disabled", text="Läuft …")
        self._status.config(text="Katalog wird erzeugt – Fortschritt im Hauptlog.")
        log = self._app._append_log

        def _worker():
            try:
                r = kk.generate(prof, progress_cb=log)
                txt = (f"Fertig: {r['articles']} Artikel, {r['groups']} Gruppen, {r['missing']} nicht in DB → "
                       f"{r['file']}")
            except Exception as exc:
                log(f"Kundenkatalog fehlgeschlagen: {exc}", tag="err")
                txt = f"Fehler: {exc}"
            self._parent.after(0, lambda: self._done(prof, txt))

        threading.Thread(target=_worker, daemon=True).start()

    def _done(self, prof, txt):
        self._running = False
        self._gen_btn.config(state="normal", text="▶ Katalog erzeugen")
        self.reload(select=prof["name"])
        self._status.config(text=txt)

    # ── Archiv ────────────────────────────────────────────────────────────────

    def _fill_archive(self):
        self._archive.delete(0, "end")
        self._archive_paths = []
        if not self._current:
            return
        try:
            for path, mtime in kk.archive_files(self._current):
                from datetime import datetime
                size = os.path.getsize(path) / 1024 / 1024
                self._archive.insert("end", f"{datetime.fromtimestamp(mtime):%Y-%m-%d %H:%M}   "
                                            f"{os.path.basename(path)}   {size:.1f} MB")
                self._archive_paths.append(path)
        except Exception:
            pass

    def _open_archive(self):
        if not self._current:
            return
        self._open_path(kk.export_dir(self._current))

    def _open_archive_file(self, _e=None):
        sel = self._archive.curselection()
        if sel and sel[0] < len(self._archive_paths):
            self._open_path(os.path.dirname(self._archive_paths[sel[0]]))

    @staticmethod
    def _open_path(path: str):
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # noqa
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:
            pass
