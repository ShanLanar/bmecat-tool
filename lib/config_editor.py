# lib/config_editor.py – Grafischer Konfigurations-Editor
#
# Öffnet ein modales Fenster mit zwei Tabs:
#   1. Verbindungen  – alle FTP/SFTP-Zugangsdaten bearbeitbar
#   2. Pfade         – DIRS + TOOLS + Hilfspfade
#
# Änderungen werden in config_user.json gespeichert und von config.py
# beim nächsten Import geladen (Laufzeit-Patch über _apply_overrides).

import json
import os
import tempfile
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path

# ── Stil-Konstanten (müssen zu main.py passen) ────────────────────────────────
BG        = "#1e1e2e"
BG2       = "#2a2a3e"
BG3       = "#232336"
ACCENT    = "#7c7cf8"
GREEN     = "#50fa7b"
RED       = "#ff5555"
YELLOW    = "#f1fa8c"
FG        = "#cdd6f4"
FG_DIM    = "#6c7086"
FONT_MAIN = ("Segoe UI", 10)
FONT_MONO = ("Consolas", 9)
FONT_HEAD = ("Segoe UI Semibold", 11)
FONT_SM   = ("Segoe UI", 9)

# Pfad zur Benutzerkonfiguration
_CFG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "config_user.json")


# ──────────────────────────────────────────────────────────────────────────────
# Persistenz
# ──────────────────────────────────────────────────────────────────────────────

_config_cache: dict | None = None


def load_user_config() -> dict:
    """Lädt gespeicherte Überschreibungen. Fällt bei I/O-Fehler auf Cache zurück."""
    global _config_cache
    if os.path.exists(_CFG_FILE):
        try:
            with open(_CFG_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                _config_cache = data
                return dict(data)  # Kopie — kein Aliasing
        except Exception:
            pass
    return dict(_config_cache) if _config_cache else {}


def save_user_config(data: dict):
    """Speichert Überschreibungen atomar. Cache wird nur bei Erfolg aktualisiert."""
    global _config_cache
    cfg_path = Path(_CFG_FILE)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=cfg_path.parent, delete=False,
                                     suffix=".tmp", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        tmp = f.name
    os.replace(tmp, _CFG_FILE)
    _config_cache = dict(data)  # nur nach erfolgreichem Write aktualisieren


def apply_overrides():
    import config
    overrides = load_user_config()
    for key, val in overrides.get("connections", {}).items():
        if key in config.CONNECTIONS:
            config.CONNECTIONS[key].update(val)
    for key, val in overrides.get("dirs", {}).items():
        config.DIRS[key] = val
    for key, val in overrides.get("tools", {}).items():
        config.TOOLS[key] = val
    for key, val in overrides.get("merge", {}).items():
        config.MERGE[key] = val
    if "base_dir" in overrides:
        config.BASE_DIR = overrides["base_dir"]


# ──────────────────────────────────────────────────────────────────────────────
# Hilfsfunktionen GUI
# ──────────────────────────────────────────────────────────────────────────────

def _styled_entry(parent, textvariable=None, width=36, show=None):
    kw = dict(font=FONT_MONO, bg=BG3, fg=FG, insertbackground=FG,
              relief="flat", bd=4, width=width)
    if textvariable:
        kw["textvariable"] = textvariable
    if show:
        kw["show"] = show
    return tk.Entry(parent, **kw)


def _label(parent, text, dim=False, head=False):
    font = FONT_HEAD if head else (FONT_SM if dim else FONT_MAIN)
    fg   = FG_DIM if dim else FG
    return tk.Label(parent, text=text, font=font, bg=BG2, fg=fg)


def _mk_btn(parent, text, cmd, color=ACCENT, small=False):
    font = ("Segoe UI", 8) if small else FONT_MAIN
    pad  = (6, 3) if small else (10, 5)
    return tk.Button(parent, text=text, command=cmd,
                     font=font, bg=color, fg="#fff",
                     activebackground=BG, activeforeground=FG,
                     relief="flat", bd=0, cursor="hand2",
                     padx=pad[0], pady=pad[1])


# ──────────────────────────────────────────────────────────────────────────────
# Haupt-Dialog
# ──────────────────────────────────────────────────────────────────────────────

class ConfigEditor(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Konfiguration")
        self.configure(bg=BG)
        self.geometry("780x580")
        self.minsize(680, 460)
        self.grab_set()          # modal
        self.resizable(True, True)

        # Daten laden
        import config as _cfg
        self._cfg    = _cfg
        self._overrides = load_user_config()

        # Widget-Variablen: {conn_name: {field: StringVar}}
        self._conn_vars: dict[str, dict[str, tk.StringVar]] = {}
        self._dir_vars:  dict[str, tk.StringVar] = {}
        self._tool_vars: dict[str, tk.StringVar] = {}
        self._merge_vars: dict[str, tk.StringVar] = {}

        self._build()
        self._populate()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        notebook = ttk.Notebook(self)
        notebook.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 0))

        # ── Tab 1: Verbindungen ───────────────────────────────────────────────
        self._tab_conn = tk.Frame(notebook, bg=BG2)
        notebook.add(self._tab_conn, text="  Verbindungen  ")
        self._tab_conn.columnconfigure(0, weight=1)
        self._tab_conn.rowconfigure(0, weight=1)

        conn_canvas = tk.Canvas(self._tab_conn, bg=BG2, highlightthickness=0)
        conn_scroll = ttk.Scrollbar(self._tab_conn, orient="vertical",
                                    command=conn_canvas.yview)
        self._conn_frame = tk.Frame(conn_canvas, bg=BG2)
        self._conn_frame.bind("<Configure>",
            lambda e: conn_canvas.configure(scrollregion=conn_canvas.bbox("all")))
        conn_canvas.create_window((0, 0), window=self._conn_frame, anchor="nw")
        conn_canvas.configure(yscrollcommand=conn_scroll.set)
        conn_canvas.grid(row=0, column=0, sticky="nsew")
        conn_scroll.grid(row=0, column=1, sticky="ns")
        conn_canvas.bind("<MouseWheel>",
            lambda e: conn_canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        # ── Tab 2: Pfade & Tools ─────────────────────────────────────────────
        self._tab_paths = tk.Frame(notebook, bg=BG2)
        notebook.add(self._tab_paths, text="  Pfade & Tools  ")
        self._tab_paths.columnconfigure(1, weight=1)

        # ── Fußzeile ──────────────────────────────────────────────────────────
        footer = tk.Frame(self, bg=BG2, pady=8, padx=12)
        footer.grid(row=1, column=0, sticky="ew")

        _mk_btn(footer, "💾  Speichern", self._save, color=GREEN).pack(side="left")
        _mk_btn(footer, "✖  Schließen", self.destroy, color=RED, small=True).pack(side="right")
        _mk_btn(footer, "↺  Zurücksetzen", self._reset, small=True).pack(side="right", padx=4)
        self._saved_lbl = tk.Label(footer, text="", font=FONT_SM, bg=BG2, fg=GREEN)
        self._saved_lbl.pack(side="left", padx=12)

    # ── Felder befüllen ───────────────────────────────────────────────────────

    CONN_FIELDS = [
        ("host",     "Host",      False),
        ("user",     "Benutzer",  False),
        ("password", "Passwort",  True),
        ("database", "Datenbank", False),
        ("port",     "Port",      False),
        ("protocol", "Protokoll", False),
    ]

    def _populate(self):
        # ── Verbindungen ──────────────────────────────────────────────────────
        f = self._conn_frame
        f.columnconfigure(1, weight=1)

        row = 0
        conn_overrides = self._overrides.get("connections", {})

        for conn_name, conn_cfg in self._cfg.CONNECTIONS.items():
            # Abschnittsüberschrift
            tk.Label(f, text=conn_name.upper(), font=FONT_HEAD,
                     bg=BG2, fg=ACCENT).grid(
                row=row, column=0, columnspan=3, sticky="w",
                padx=12, pady=(14, 2))
            row += 1

            self._conn_vars[conn_name] = {}
            user_conn = conn_overrides.get(conn_name, {})

            for field, label, is_pw in self.CONN_FIELDS:
                default = user_conn.get(field, conn_cfg.get(field, ""))
                var = tk.StringVar(value=str(default))
                self._conn_vars[conn_name][field] = var

                _label(f, label, dim=True).grid(
                    row=row, column=0, sticky="e", padx=(16, 6), pady=2)
                entry = _styled_entry(f, textvariable=var, width=44,
                                      show="●" if is_pw else None)
                entry.grid(row=row, column=1, sticky="ew", padx=(0, 12), pady=2)

                if is_pw:
                    # Passwort anzeigen/verbergen
                    show_var = tk.BooleanVar(value=False)
                    def _toggle(e=entry, sv=show_var):
                        sv.set(not sv.get())
                        e.config(show="" if sv.get() else "●")
                    tk.Button(f, text="👁", command=_toggle,
                              bg=BG2, fg=FG_DIM, relief="flat", bd=0,
                              cursor="hand2", font=("Segoe UI", 10)
                              ).grid(row=row, column=2, padx=(0, 8))
                row += 1

            # Trennlinie
            ttk.Separator(f, orient="horizontal").grid(
                row=row, column=0, columnspan=3, sticky="ew",
                padx=8, pady=4)
            row += 1

        # ── Pfade & Tools ─────────────────────────────────────────────────────
        pf = self._tab_paths
        pf.columnconfigure(1, weight=1)
        dir_overrides  = self._overrides.get("dirs", {})
        tool_overrides = self._overrides.get("tools", {})

        r = 0
        _label(pf, "Verzeichnisse", head=True).grid(
            row=r, column=0, columnspan=3, sticky="w", padx=12, pady=(12, 4))
        r += 1

        for key, default_path in self._cfg.DIRS.items():
            val = dir_overrides.get(key, default_path)
            var = tk.StringVar(value=val)
            self._dir_vars[key] = var
            _label(pf, key, dim=True).grid(row=r, column=0, sticky="e", padx=(16, 6), pady=2)
            _styled_entry(pf, textvariable=var, width=52).grid(
                row=r, column=1, sticky="ew", padx=(0, 8), pady=2)
            _mk_btn(pf, "…", lambda k=key: self._browse_dir(k), small=True).grid(
                row=r, column=2, padx=(0, 8))
            r += 1

        ttk.Separator(pf, orient="horizontal").grid(
            row=r, column=0, columnspan=3, sticky="ew", padx=8, pady=8)
        r += 1

        _label(pf, "Tools / Programme", head=True).grid(
            row=r, column=0, columnspan=3, sticky="w", padx=12, pady=(0, 4))
        r += 1

        for key, default_path in self._cfg.TOOLS.items():
            val = tool_overrides.get(key, default_path)
            var = tk.StringVar(value=val)
            self._tool_vars[key] = var
            _label(pf, key, dim=True).grid(row=r, column=0, sticky="e", padx=(16, 6), pady=2)
            _styled_entry(pf, textvariable=var, width=52).grid(
                row=r, column=1, sticky="ew", padx=(0, 8), pady=2)
            _mk_btn(pf, "…", lambda k=key: self._browse_file(k), small=True).grid(
                row=r, column=2, padx=(0, 8))
            r += 1

        ttk.Separator(pf, orient="horizontal").grid(
            row=r, column=0, columnspan=3, sticky="ew", padx=8, pady=8)
        r += 1

        _label(pf, "BMEcat-Merge (Dateinamen in in_BME)", head=True).grid(
            row=r, column=0, columnspan=3, sticky="w", padx=12, pady=(0, 4))
        r += 1

        merge_overrides = self._overrides.get("merge", {})
        merge_labels = {
            "udx_src":   "ABE-Datei (UDX + ECLASS)",
            "basis_src": "Basisdatei (Hauptkatalog)",
            "out_file":  "Ausgabedatei",
        }
        for key, default_val in self._cfg.MERGE.items():
            val = merge_overrides.get(key, default_val)
            var = tk.StringVar(value=val)
            self._merge_vars[key] = var
            _label(pf, merge_labels.get(key, key), dim=True).grid(
                row=r, column=0, sticky="e", padx=(16, 6), pady=2)
            _styled_entry(pf, textvariable=var, width=52).grid(
                row=r, column=1, sticky="ew", padx=(0, 8), pady=2)
            r += 1

    # ── Datei-/Verzeichnis-Auswahl ────────────────────────────────────────────

    def _browse_dir(self, key: str):
        from tkinter.filedialog import askdirectory
        path = askdirectory(title=f"Verzeichnis für '{key}'",
                            initialdir=self._dir_vars[key].get())
        if path:
            self._dir_vars[key].set(path)

    def _browse_file(self, key: str):
        from tkinter.filedialog import askopenfilename
        path = askopenfilename(title=f"Programm für '{key}'",
                               initialfile=self._tool_vars[key].get(),
                               filetypes=[("Ausführbare Dateien", "*.exe *.com"),
                                          ("Alle", "*.*")])
        if path:
            self._tool_vars[key].set(path)

    # ── Speichern / Zurücksetzen ──────────────────────────────────────────────

    def _save(self):
        data: dict = {"connections": {}, "dirs": {}, "tools": {}, "merge": {}}

        for conn_name, fields in self._conn_vars.items():
            data["connections"][conn_name] = {
                field: var.get() for field, var in fields.items()
            }
            try:
                data["connections"][conn_name]["port"] = int(
                    data["connections"][conn_name].get("port", 21))
            except ValueError:
                pass

        for key, var in self._dir_vars.items():
            data["dirs"][key] = var.get()

        for key, var in self._tool_vars.items():
            data["tools"][key] = var.get()

        for key, var in self._merge_vars.items():
            data["merge"][key] = var.get()

        try:
            save_user_config(data)
            apply_overrides()
            self._saved_lbl.config(text="✓ Gespeichert", fg=GREEN)
            self.after(3000, lambda: self._saved_lbl.config(text=""))
        except Exception as exc:
            messagebox.showerror("Fehler", f"Speichern fehlgeschlagen:\n{exc}", parent=self)

    def _reset(self):
        if not messagebox.askyesno(
            "Zurücksetzen",
            "Alle Benutzeranpassungen löschen und Standardwerte wiederherstellen?",
            parent=self
        ):
            return
        if os.path.exists(_CFG_FILE):
            os.remove(_CFG_FILE)
        self._overrides = {}
        # Dialog neu aufbauen
        for w in self._conn_frame.winfo_children():
            w.destroy()
        for w in self._tab_paths.winfo_children():
            w.destroy()
        self._conn_vars.clear()
        self._dir_vars.clear()
        self._tool_vars.clear()
        self._merge_vars.clear()
        self._populate()
        self._saved_lbl.config(text="✓ Zurückgesetzt", fg=YELLOW)
        self.after(3000, lambda: self._saved_lbl.config(text=""))


# ──────────────────────────────────────────────────────────────────────────────
# Verbindungstest-Dialog
# ──────────────────────────────────────────────────────────────────────────────

class ConnectionTestDialog(tk.Toplevel):
    """
    Modales Fenster das alle FTP/SFTP-Verbindungen testet
    und das Ergebnis live anzeigt.
    """
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Verbindungstest")
        self.configure(bg=BG)
        self.geometry("620x440")
        self.minsize(500, 340)
        self.grab_set()
        self.resizable(True, True)

        self._build()
        self.after(100, self._run_tests)

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        # Ergebnis-Tabelle
        frame = tk.Frame(self, bg=BG2, padx=12, pady=10)
        frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        tk.Label(frame, text="Verbindungstest", font=FONT_HEAD,
                 bg=BG2, fg=ACCENT).grid(row=0, column=0, sticky="w", pady=(0, 8))

        # Scrollbares Text-Widget
        from tkinter import scrolledtext
        self._txt = scrolledtext.ScrolledText(
            frame, font=FONT_MONO, bg="#13131f", fg=FG,
            relief="flat", bd=0, state="disabled", wrap="word", height=16)
        self._txt.grid(row=1, column=0, sticky="nsew")
        self._txt.tag_config("ok",   foreground=GREEN)
        self._txt.tag_config("err",  foreground=RED)
        self._txt.tag_config("warn", foreground=YELLOW)
        self._txt.tag_config("dim",  foreground=FG_DIM)

        # Fortschritt
        self._progress = ttk.Progressbar(frame, mode="indeterminate")
        self._progress.grid(row=2, column=0, sticky="ew", pady=(6, 0))

        # Fußzeile
        footer = tk.Frame(self, bg=BG2, pady=8, padx=12)
        footer.grid(row=1, column=0, sticky="ew")
        self._close_btn = tk.Button(
            footer, text="Schließen", command=self.destroy,
            font=FONT_MAIN, bg=ACCENT, fg="#fff",
            activebackground=BG, activeforeground=FG,
            relief="flat", bd=0, cursor="hand2", padx=12, pady=5,
            state="disabled")
        self._close_btn.pack(side="right")
        self._retest_btn = tk.Button(
            footer, text="↺ Erneut testen", command=self._run_tests,
            font=FONT_MAIN, bg=BG3, fg=FG,
            activebackground=BG, activeforeground=FG,
            relief="flat", bd=0, cursor="hand2", padx=12, pady=5,
            state="disabled")
        self._retest_btn.pack(side="right", padx=6)

    def _append(self, msg: str, tag: str = ""):
        self._txt.config(state="normal")
        if tag:
            self._txt.insert("end", msg + "\n", tag)
        else:
            self._txt.insert("end", msg + "\n")
        self._txt.see("end")
        self._txt.config(state="disabled")

    def _run_tests(self):
        self._txt.config(state="normal")
        self._txt.delete("1.0", "end")
        self._txt.config(state="disabled")
        self._close_btn.config(state="disabled")
        self._retest_btn.config(state="disabled")
        self._progress.start(12)

        import threading
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        from lib.connection_test import test_all
        import datetime

        self.after(0, self._append,
                   f"Test gestartet: {datetime.datetime.now():%d.%m.%Y %H:%M:%S}", "dim")

        def cb(msg, **_):
            tag = ""
            if msg.startswith("✅"):
                tag = "ok"
            elif msg.startswith("❌"):
                tag = "err"
            elif msg.startswith("⚠"):
                tag = "warn"
            elif msg.startswith("─"):
                tag = "dim"
            self.after(0, self._append, msg, tag)

        results = test_all(progress_cb=cb)

        ok  = sum(1 for r in results if r.ok)
        total = len(results)
        summary_tag = "ok" if ok == total else ("warn" if ok > 0 else "err")
        self.after(0, self._append,
                   f"\nGesamt: {ok}/{total} Verbindungen OK", summary_tag)
        self.after(0, self._progress.stop)
        self.after(0, lambda: self._close_btn.config(state="normal"))
        self.after(0, lambda: self._retest_btn.config(state="normal"))
