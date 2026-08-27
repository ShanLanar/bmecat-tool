#!/usr/bin/env python3
# main.py – BMEcat Download-Tool  (GUI)
#
# Abhängigkeiten: pip install paramiko
# Python ≥ 3.9, tkinter ist Bestandteil der Standardinstallation

import sys
import os
import threading
import logging
import datetime
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

# ── Projektpfad ────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# User-Overrides so früh wie möglich anwenden
from lib.config_editor import apply_overrides
apply_overrides()

import config
from lib.utils import VERSION
from lib.task_registry import TASKS, call_task, validate_config, TASK_GROUP_ORDER, apply_patches

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
log = logging.getLogger("main")


# ── Themes ────────────────────────────────────────────────────────────────────

# Themes aus design.py importieren
from lib.design import THEMES

_current_theme = "Classic"

def _T(key: str) -> str:
    """Gibt den Farbwert für den aktuellen Theme zurück."""
    return THEMES[_current_theme][key]

FONT_MAIN = ("Segoe UI", 10)
FONT_MONO = ("Consolas", 9)
FONT_HEAD = ("Segoe UI Semibold", 11)


def run_bestandsdaten_only(progress_cb=None):
    from lib.bestandsdaten import erstelle_bestandsdaten
    p      = progress_cb or (lambda m, **kw: None)
    in_bme = config.DIRS["in_bme"]
    csv_in = os.path.join(in_bme, "br-bestand.csv")

    if not os.path.exists(csv_in):
        p("br-bestand.csv nicht gefunden – lade von Büroring nach ...")
        from lib.ftp_client import make_client
        from config import CONNECTIONS, TOOLS
        seven_z = TOOLS["7zip"]
        client  = make_client(CONNECTIONS["bueroring"])
        client.connect()
        try:
            client.download("downloads/bueroforum/br-bestand.zip",
                            in_bme, progress_cb=p)
        finally:
            client.disconnect()
        zip_path = os.path.join(in_bme, "br-bestand.zip")
        if os.path.exists(zip_path):
            import subprocess
            subprocess.run([seven_z, "e", zip_path, f"-o{in_bme}", "-y"],
                           capture_output=True, timeout=120)
            os.remove(zip_path)

    out = os.path.join(in_bme, config.AVAILABILITY_FILE)
    erstelle_bestandsdaten(in_bme, out, progress_cb=p)

    # ATP-Merge: Lagerbestände aus OBS-Archiv einspielen
    try:
        from lib.atp import run_atp_merge
        p("ATP-Bestandsdaten: Suche neueste Archiv-Datei ...")
        run_atp_merge(out, progress_cb=p)
    except Exception as e:
        p(f"ATP-Merge übersprungen: {e}", tag="warn")

    # Mindest-Abgleich → 32WQS_conditionsfile.csv
    try:
        from lib.mindest_abgleich import run_mindest_abgleich
        run_mindest_abgleich(out, progress_cb=p)
    except Exception as e:
        p(f"Mindest-Abgleich übersprungen: {e}", tag="warn")

    # Upload → Mercateo-Unite /catalog/32WQS (Availability + Conditionsfile)
    try:
        from tasks.others import upload_mercateo_files
        conditions_csv = os.path.join(in_bme, "32WQS_conditionsfile.csv")
        upload_mercateo_files([out, conditions_csv], progress_cb=p)
    except Exception as e:
        p(f"Mercateo-Upload übersprungen: {e}", tag="warn")



# ──────────────────────────────────────────────────────────────────────────────
# GUI
# ──────────────────────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"BMEcat Download-Tool v{VERSION}")
        self.resizable(True, True)
        self.geometry("980x700")
        self.minsize(800, 520)

        self._running = False
        self._thread  = None
        self._checks: dict = {}
        self._theme   = _current_theme
        self._widget_refs: dict = {}   # für Tutorial-Highlighting
        self._tutorial = None

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_ui()
        self._ensure_dirs()
        self._append_log(f"BMEcat Download-Tool v{VERSION} bereit.", tag="ok")
        # Startup-Checks nach erstem Render (Fenster erscheint sofort)
        self.after(0, self._startup_checks)

    # ── Verzeichnisse anlegen ─────────────────────────────────────────────────
    def _ensure_dirs(self):
        for d in config.DIRS.values():
            try:
                Path(d).mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

    # ── Startup-Prüfungen ─────────────────────────────────────────────────────
    def _startup_checks(self):
        """Startup-Prüfungen: läuft nach erstem Render im Event-Loop."""
        # Task-Patches (tasks.cleanup + tasks.others) – erst jetzt laden
        apply_patches(run_bestandsdaten_only)

        # 0. Erstinstall: fehlende Templates nach BASE_DIR kopieren
        try:
            from lib.first_run import initialize
            initialize(config.BASE_DIR, progress_cb=self._append_log)
        except Exception:
            pass

        # 1. Config-Migration
        try:
            from lib.config_migration import migrate
            user_cfg = os.path.join(os.path.dirname(__file__), "config_user.json")
            migrate(user_cfg, progress_cb=self._append_log)
        except Exception:
            pass

        # 1. Dependencies
        from lib.utils import check_dependencies
        missing = check_dependencies()
        if missing:
            self._append_log(
                f"⚠ Fehlende Pakete: {', '.join(missing)} "
                f"– bitte installieren: pip install {' '.join(missing)}",
                tag="err")

        # 2. Heartbeat: letzter Lauf-Report
        try:
            import glob as _gl
            log_dir = config.DIRS.get("logs", "")
            reports = sorted(_gl.glob(os.path.join(log_dir, "lauf_*.json")))
            if reports:
                last = os.path.getmtime(reports[-1])
                hours_ago = (datetime.datetime.now().timestamp() - last) / 3600
                if hours_ago > 25:
                    self._append_log(
                        f"⚠ Letzter Lauf: vor {hours_ago:.0f} Stunden "
                        f"({os.path.basename(reports[-1])})",
                        tag="warn")
        except Exception:
            pass

    # ── UI aufbauen ───────────────────────────────────────────────────────────
    def _build_ui(self):
        self.configure(bg=_T("BG"))
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # ── Kopfzeile ─────────────────────────────────────────────────────────
        from lib.design import FONT_HEAD_L, FONT_UI_SM, add_hover, darken, lighten

        self._header = tk.Frame(self, bg=_T("BG2"), pady=0, padx=0)
        self._header.grid(row=0, column=0, sticky="ew")
        self._header.columnconfigure(1, weight=1)

        # Hauptzeile
        header_inner = tk.Frame(self._header, bg=_T("BG2"), pady=10, padx=16)
        header_inner.pack(fill="x")
        header_inner.columnconfigure(1, weight=1)
        header = header_inner

        # Logo-Bereich
        logo_frame = tk.Frame(header, bg=_T("BG2"))
        logo_frame.grid(row=0, column=0, sticky="w")
        self._title_lbl = tk.Label(
            logo_frame,
            text="BMEcat",
            font=("Segoe UI Semibold", 15), bg=_T("BG2"), fg=_T("ACCENT"))
        self._title_lbl.pack(side="left")
        tk.Label(
            logo_frame,
            text=f" Download-Tool  v{VERSION}",
            font=("Segoe UI", 12), bg=_T("BG2"), fg=_T("FG_DIM")).pack(side="left")

        hbf = tk.Frame(header, bg=_T("BG2"))
        hbf.grid(row=0, column=2, sticky="e")
        self._hbf = hbf

        from lib.tutorial import ToolTip, BUTTON_TIPS

        def _ghost_btn(parent, text, cmd, tip=""):
            b = tk.Button(parent, text=text, command=cmd,
                          font=FONT_UI_SM, bg=_T("BG2"), fg=_T("FG_DIM"),
                          activebackground=lighten(_T("BG2"), 10),
                          activeforeground=_T("FG"),
                          relief="flat", bd=0, cursor="hand2",
                          padx=10, pady=5)
            add_hover(b, _T("BG2"), lighten(_T("BG2"), 10), _T("FG_DIM"), _T("FG"))
            b.pack(side="left", padx=2)
            if tip: ToolTip(b, tip)
            return b

        conn_btn = _ghost_btn(hbf, "Verbindungstest",
                              self._open_conn_test, BUTTON_TIPS["Verbindungstest"])
        self._widget_refs["conn_test_btn"] = conn_btn

        cfg_btn  = _ghost_btn(hbf, "Konfiguration",
                              self._open_config,    BUTTON_TIPS["Konfiguration"])
        self._widget_refs["config_btn"] = cfg_btn

        sch_btn  = _ghost_btn(hbf, "Scheduler",
                              self._open_scheduler, BUTTON_TIPS["Scheduler"])
        self._widget_refs["scheduler_btn"] = sch_btn

        import_btn = _ghost_btn(hbf, "BMEcat laden",
                                self._open_manual_import, BUTTON_TIPS["BMEcat laden"])
        self._widget_refs["manual_import_btn"] = import_btn

        # Theme-Umschalter
        theme_lbl = "◑ Classic" if self._theme == "ABE" else "◑ ABE"
        self._theme_btn = tk.Button(
            hbf, text=theme_lbl, command=self._toggle_theme,
            font=FONT_UI_SM, bg=_T("BG2"), fg=_T("FG_DIM"),
            activebackground=lighten(_T("BG2"), 10), activeforeground=_T("FG"),
            relief="flat", bd=0, cursor="hand2", padx=10, pady=5)
        add_hover(self._theme_btn, _T("BG2"), lighten(_T("BG2"), 10), _T("FG_DIM"), _T("FG"))
        self._theme_btn.pack(side="left", padx=2)
        ToolTip(self._theme_btn, "Zwischen Classic (dunkel) und ABE wechseln.")

        # Tutorial-Button
        tut_bg = _T("ACCENT")
        tut_btn = tk.Button(
            hbf, text="?", command=self._start_tutorial,
            font=("Segoe UI Semibold", 9), bg=tut_bg, fg="#ffffff",
            activebackground=darken(tut_bg, 15), activeforeground="#ffffff",
            relief="flat", bd=0, cursor="hand2", padx=10, pady=5, width=2)
        add_hover(tut_btn, tut_bg, darken(tut_bg, 15))
        tut_btn.pack(side="left", padx=(6, 0))
        ToolTip(tut_btn, BUTTON_TIPS["?"])

        self._status_lbl = tk.Label(
            header, text="●  Bereit", font=("Segoe UI", 9),
            bg=_T("BG2"), fg=_T("GREEN"))
        self._status_lbl.grid(row=0, column=3, sticky="e", padx=(16, 0))

        # Akzentlinie am unteren Header-Rand
        tk.Frame(self._header, bg=_T("ACCENT"), height=2).pack(fill="x")

        # ── Hauptbereich: Notebook mit Reitern ───────────────────────────────
        self._notebook = ttk.Notebook(self)
        self._notebook.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)

        from lib.design import apply_notebook_style, THEMES
        apply_notebook_style(self._notebook, THEMES[self._theme], "BME.TNotebook")

        # Tab 1: BMECat-Verarbeitung
        body = tk.Frame(self._notebook, bg=_T("BG"))
        self._notebook.add(body, text="  BMECat-Verarbeitung  ")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        # ── Splitter: Links Task-Liste, Rechts Inhalt ─────────────────────────
        _pane = tk.PanedWindow(body, orient="horizontal", bg=_T("BG"),
                               sashwidth=6, sashrelief="raised",
                               sashcursor="sb_h_double_arrow")
        _pane.grid(row=0, column=0, sticky="nsew")

        left_outer = tk.Frame(_pane, bg=_T("BG2"))
        _pane.add(left_outer, minsize=180, width=240)
        left_outer.columnconfigure(0, weight=1)
        left_outer.columnconfigure(1, weight=0)
        left_outer.rowconfigure(2, weight=1)

        right_outer = tk.Frame(_pane, bg=_T("BG"))
        right_outer.columnconfigure(0, weight=1)
        right_outer.rowconfigure(1, weight=1)
        _pane.add(right_outer, minsize=400)

        tk.Label(left_outer, text="Aufgaben", font=FONT_HEAD,
                 bg=_T("BG2"), fg=_T("FG"), padx=12).grid(row=0, column=0, columnspan=2,
                                               sticky="w", pady=(10, 2))

        # ── Alle / Keine / Standard – immer sichtbar oben ────────────────────
        _bf_top = tk.Frame(left_outer, bg=_T("BG2"), padx=10)
        _bf_top.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        _alle_btn  = self._mk_btn(_bf_top, "Alle",     self._select_all,     small=True)
        _alle_btn.pack(side="left", padx=(0, 2))
        _keine_btn = self._mk_btn(_bf_top, "Keine",    self._deselect_all,   small=True)
        _keine_btn.pack(side="left", padx=2)
        _std_btn   = self._mk_btn(_bf_top, "Standard", self._select_default, small=True)
        _std_btn.pack(side="left", padx=2)
        _daily_btn = self._mk_btn(_bf_top, "Täglich",  self._select_daily,   small=True)
        _daily_btn.pack(side="left", padx=2)
        self._widget_refs["sel_buttons"] = _bf_top

        canvas = tk.Canvas(left_outer, bg=_T("BG2"), highlightthickness=0)
        canvas.grid(row=2, column=0, sticky="nsew")

        vsb = ttk.Scrollbar(left_outer, orient="vertical", command=canvas.yview)
        vsb.grid(row=2, column=1, sticky="ns")
        canvas.configure(yscrollcommand=vsb.set)

        left = tk.Frame(canvas, bg=_T("BG2"), padx=12)
        canvas_win = canvas.create_window((0, 0), window=left, anchor="nw")

        def _on_frame_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        left.bind("<Configure>", _on_frame_configure)

        def _on_mousewheel(e):
            canvas.yview_scroll(-1 * (e.delta // 120), "units")
        canvas.bind("<MouseWheel>", _on_mousewheel)
        left.bind("<MouseWheel>", _on_mousewheel)

        from lib.tutorial import ToolTip, TASK_TIPS
        from lib.design import lighten, FONT_UI, FONT_UI_SM

        _task_items       = []   # ("group"|"task"|"sep", widget)
        self._task_btns   = {}   # task_id → (btn, var)
        _cols_state       = {"n": 0}

        def _refresh_btn(task_id):
            btn, var = self._task_btns[task_id]
            if var.get():
                btn.config(bg=_T("ACCENT"), fg="#ffffff",
                           activebackground=lighten(_T("ACCENT"), 12),
                           activeforeground="#ffffff")
            else:
                btn.config(bg=_T("BG3"), fg=_T("FG_DIM"),
                           activebackground=lighten(_T("BG3"), 8),
                           activeforeground=_T("FG"))

        def _apply_layout(ncols):
            if ncols == _cols_state["n"]:
                return
            _cols_state["n"] = ncols
            for child in left.winfo_children():
                child.grid_forget()
            grow = gcol = 0
            for kind, widget in _task_items:
                if kind in ("group", "sep"):
                    if gcol > 0:
                        grow += 1; gcol = 0
                    sticky = "ew" if kind == "group" else "ew"
                    pady   = (8, 2) if kind == "group" else 6
                    widget.grid(row=grow, column=0, columnspan=ncols,
                                sticky=sticky, pady=pady, padx=4)
                    grow += 1; gcol = 0
                else:
                    widget.grid(row=grow, column=gcol, sticky="nsew",
                                padx=3, pady=2)
                    gcol += 1
                    if gcol >= ncols:
                        gcol = 0; grow += 1
            for i in range(ncols):
                left.columnconfigure(i, weight=1)
            for i in range(ncols, 4):
                left.columnconfigure(i, weight=0)
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(e):
            canvas.itemconfig(canvas_win, width=e.width)
            w = e.width
            ncols = (4 if w >= 400 else
                     3 if w >= 290 else
                     2 if w >= 185 else 1)
            _apply_layout(ncols)
        canvas.bind("<Configure>", _on_canvas_configure)

        current_group = None
        for task in TASKS:
            grp = task.get("group", "")
            if grp != current_group:
                current_group = grp
                sep_frm = tk.Frame(left, bg=_T("BG2"))
                sep_frm.bind("<MouseWheel>", _on_mousewheel)
                tk.Frame(sep_frm, bg=_T("BORDER"), height=1).pack(
                    fill="x", pady=(0, 3))
                tk.Label(sep_frm, text=grp.upper(),
                         font=("Segoe UI", 7, "bold"),
                         bg=_T("BG2"), fg=_T("FG_DIM"),
                         padx=2).pack(anchor="w")
                _task_items.append(("group", sep_frm))

            var = tk.BooleanVar(value=task.get("default", True))
            self._checks[task["id"]] = var

            tip_text = task["desc"]
            btn = tk.Button(
                left,
                text=task["name"],
                font=FONT_UI_SM,
                relief="flat", bd=0,
                cursor="hand2",
                padx=6, pady=5,
                wraplength=95,
                justify="center",
                command=lambda tid=task["id"]: (
                    self._task_btns[tid][1].set(
                        not self._task_btns[tid][1].get()),
                    _refresh_btn(tid)
                )
            )
            btn.bind("<MouseWheel>", _on_mousewheel)
            ToolTip(btn, tip_text)
            self._task_btns[task["id"]] = (btn, var)
            _refresh_btn(task["id"])
            _task_items.append(("task", btn))

        _task_items.append(("sep", ttk.Separator(left, orient="horizontal")))
        _apply_layout(1)
        self._widget_refs["task_list"] = left

        # ── Rechte Seite oben: Basispfad ──────────────────────────────────────
        top_right = tk.Frame(right_outer, bg=_T("BG"))
        top_right.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        top_right.columnconfigure(1, weight=1)

        tk.Label(top_right, text="Basispfad:", font=FONT_MAIN,
                 bg=_T("BG"), fg=_T("FG_DIM_BODY")).grid(row=0, column=0, padx=(0, 6))
        self._path_var = tk.StringVar(value=config.BASE_DIR)
        tk.Entry(top_right, textvariable=self._path_var,
                 font=FONT_MONO, bg=_T("BG2"), fg=_T("FG"),
                 insertbackground=_T("FG"), relief="flat", bd=4,
                 ).grid(row=0, column=1, sticky="ew")
        self._mk_btn(top_right, "Oeffnen", self._open_basedir, small=True
                     ).grid(row=0, column=2, padx=(6, 0))

        # ── Log-Fenster ───────────────────────────────────────────────────────
        self._log_txt = scrolledtext.ScrolledText(
            right_outer, font=FONT_MONO, bg=_T("LOG_BG"), fg=_T("LOG_FG"),
            insertbackground=_T("LOG_FG"), relief="flat", bd=0,
            state="disabled", wrap="word",
        )
        self._log_txt.grid(row=1, column=0, sticky="nsew")
        self._log_txt.tag_config("ok",   foreground=_T("GREEN"))
        self._log_txt.tag_config("err",  foreground=_T("RED"))
        self._log_txt.tag_config("warn", foreground=_T("YELLOW"))
        self._log_txt.tag_config("dim",  foreground=_T("FG_DIM"))
        self._log_txt.tag_config("info", foreground=_T("ORANGE"))
        self._widget_refs["log_area"] = self._log_txt

        # ── Fortschrittsbereich (außerhalb Splitter, volle Breite) ───────────
        prog_frame = tk.Frame(body, bg=_T("BG"))
        prog_frame.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        prog_frame.columnconfigure(0, weight=1)
        self._file_lbl  = tk.Label(prog_frame, text="", font=FONT_MONO,
                                   bg=_T("BG"), fg=_T("FG_DIM_BODY"), anchor="w")
        self._file_lbl.grid(row=0, column=0, sticky="ew")
        self._speed_lbl = tk.Label(prog_frame, text="", font=FONT_MONO,
                                   bg=_T("BG"), fg=_T("FG_DIM_BODY"), anchor="e")
        self._speed_lbl.grid(row=0, column=1, sticky="e", padx=(8, 0))
        self._progress  = ttk.Progressbar(prog_frame, mode="determinate",
                                          maximum=100, value=0)
        self._progress.grid(row=1, column=0, columnspan=2, sticky="ew")

        # ── Tab 2: Viewer / Export ────────────────────────────────────────────
        _tab2 = tk.Frame(self._notebook, bg=_T("BG"))
        self._notebook.add(_tab2, text="  Viewer / Export  ")
        from lib.viewer_tab import ViewerTab
        self._viewer_tab = ViewerTab(_tab2, self, THEMES[self._theme])

        _tab3 = tk.Frame(self._notebook, bg=_T("BG"))
        self._notebook.add(_tab3, text="  Konfiguration  ")
        from lib.config_tab import ConfigTab
        self._config_tab = ConfigTab(_tab3, self, THEMES[self._theme])

        _tab4 = tk.Frame(self._notebook, bg=_T("BG"))
        self._notebook.add(_tab4, text="  eClass Katalog  ")
        from lib.eclass_catalog_browser import EclassCatalogBrowser
        self._eclass_browser = EclassCatalogBrowser(_tab4, self, THEMES[self._theme])

        _tab5 = tk.Frame(self._notebook, bg=_T("BG"))
        self._notebook.add(_tab5, text="  eBay  ")
        from lib.ebay_tab import EbayTab
        self._ebay_tab = EbayTab(_tab5, self, THEMES[self._theme])

        # ── Fusszeile ─────────────────────────────────────────────────────────
        footer_wrap = tk.Frame(self, bg=_T("BG2"))
        footer_wrap.grid(row=2, column=0, sticky="ew")
        tk.Frame(footer_wrap, bg=_T("BORDER"), height=1).pack(fill="x")
        footer = tk.Frame(footer_wrap, bg=_T("BG2"), pady=8, padx=12)
        footer.pack(fill="x")

        self._run_btn = self._mk_btn(footer, "▶  Starten", self._start_run)
        self._run_btn.pack(side="left", padx=(0, 8))
        from lib.tutorial import ToolTip, BUTTON_TIPS
        ToolTip(self._run_btn, BUTTON_TIPS["Starten"])
        self._widget_refs["run_btn"] = self._run_btn

        self._stop_btn = self._mk_btn(footer, "■  Abbrechen", self._stop_run, color=_T("RED"))
        self._stop_btn.pack(side="left")
        self._stop_btn.config(state="disabled")
        ToolTip(self._stop_btn, BUTTON_TIPS["Abbrechen"])

        log_clr = self._mk_btn(footer, "Log loeschen", self._clear_log, small=True)
        log_clr.pack(side="right")
        ToolTip(log_clr, BUTTON_TIPS["Log loeschen"])
        log_sav = self._mk_btn(footer, "Log speichern", self._save_log, small=True)
        log_sav.pack(side="right", padx=4)
        ToolTip(log_sav, BUTTON_TIPS["Log speichern"])

        # Tab-Wechsel: Start/Stop nur auf Tab 0 aktiv; Viewer bei Tab 1 aktualisieren
        def _on_tab_change(event=None):
            idx = self._notebook.index(self._notebook.select())
            self._run_btn.config(state="normal" if idx == 0 else "disabled")
            if idx != 0:
                self._stop_btn.config(state="disabled")
            if idx == 1 and hasattr(self, "_viewer_tab"):
                self._viewer_tab.on_tab_activated()
            if idx == 4 and hasattr(self, "_ebay_tab"):
                self._ebay_tab.on_tab_activated()
        self._notebook.bind("<<NotebookTabChanged>>", _on_tab_change)

        # Logging → GUI
        gui_handler = _GuiLogHandler(self._append_log)
        gui_handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))
        logging.getLogger().addHandler(gui_handler)

    # ── Theme ─────────────────────────────────────────────────────────────────
    def _toggle_theme(self):
        global _current_theme
        _current_theme = "ABE" if _current_theme == "Classic" else "Classic"
        self._theme    = _current_theme

        # Alle Widgets zerstören und UI neu aufbauen
        for w in self.winfo_children():
            w.destroy()
        self._checks = {}
        self._build_ui()
        self._append_log(f"Theme gewechselt zu: {_current_theme}", tag="ok")

    # ── Button-Factory ────────────────────────────────────────────────────────
    def _mk_btn(self, parent, text, cmd, color=None, small=False,
                variant: str = "primary") -> tk.Button:
        from lib.design import make_button, THEMES
        c = THEMES[self._theme]
        if color is not None:
            # Legacy-Aufruf mit expliziter Farbe → primary mit Override
            from lib.design import FONT_UI, FONT_UI_SM, add_hover, lighten
            font = FONT_UI_SM if small else FONT_UI
            padx = 8 if small else 14
            pady = 4 if small else 6
            hover = lighten(color, 18)
            btn = tk.Button(parent, text=text, command=cmd,
                            font=font, bg=color, fg="#ffffff",
                            activebackground=hover, activeforeground="#ffffff",
                            relief="flat", bd=0, cursor="hand2",
                            padx=padx, pady=pady)
            add_hover(btn, color, hover, "#ffffff", "#ffffff")
            return btn
        return make_button(parent, text, cmd, c,
                           variant=variant, small=small)

    # ── Auswahl ───────────────────────────────────────────────────────────────
    def _select_all(self):
        for v in self._checks.values():
            v.set(True)
        self._refresh_all_btns()

    def _deselect_all(self):
        for v in self._checks.values():
            v.set(False)
        self._refresh_all_btns()

    def _select_default(self):
        for task in TASKS:
            self._checks[task["id"]].set(task.get("default", True))
        self._refresh_all_btns()

    def _select_daily(self):
        for v in self._checks.values():
            v.set(False)
        for task in TASKS:
            if task.get("group") == "Täglich":
                self._checks[task["id"]].set(True)
        self._refresh_all_btns()

    def _refresh_all_btns(self):
        from lib.design import lighten
        for tid, (btn, var) in self._task_btns.items():
            if var.get():
                btn.config(bg=_T("ACCENT"), fg="#ffffff",
                           activebackground=lighten(_T("ACCENT"), 12),
                           activeforeground="#ffffff")
            else:
                btn.config(bg=_T("BG3"), fg=_T("FG_DIM"),
                           activebackground=lighten(_T("BG3"), 8),
                           activeforeground=_T("FG"))

    # ── Dialoge ───────────────────────────────────────────────────────────────
    def _open_scheduler(self):
        from tasks.scheduler import open_scheduler_dialog
        open_scheduler_dialog(self)

    def _open_manual_import(self):
        """Lokale BMEcat-1.2-Datei ohne Download direkt in die DB importieren.
        Lieferantenname wird aus SUPPLIER_NAME vorgeschlagen, per Dialog bestätigt
        oder angepasst. Rest der Import-Mechanik ist unverändert (kein Prefix,
        kein Postprocessing – das läuft wie gehabt erst beim Export)."""
        if self._running:
            messagebox.showwarning("Lauf aktiv",
                                   "Es läuft bereits ein Vorgang. Bitte warten.", parent=self)
            return

        from tkinter.filedialog import askopenfilename
        xml_path = askopenfilename(
            title="BMEcat-1.2-Datei auswählen",
            filetypes=[("BMEcat-XML", "*.xml"), ("Alle Dateien", "*.*")],
            parent=self,
        )
        if not xml_path:
            return

        from lib.db_importer import extract_supplier_name
        suggested = extract_supplier_name(xml_path)

        from tkinter.simpledialog import askstring
        supplier_name = askstring(
            "Lieferantenname bestätigen",
            f"Aus der Datei übernommener Lieferantenname (SUPPLIER_NAME):\n"
            f"Für Zuordnung/Filterung in der Datenbank verwendet – bei Bedarf anpassen.",
            initialvalue=suggested,
            parent=self,
        )
        if supplier_name is None:
            return
        supplier_name = supplier_name.strip()
        if not supplier_name:
            messagebox.showwarning("Kein Name",
                                   "Ohne Lieferantenname kann nicht importiert werden.",
                                   parent=self)
            return

        self._running = True
        import_btn = self._widget_refs.get("manual_import_btn")
        if import_btn:
            import_btn.config(state="disabled")
        self._run_btn.config(state="disabled")
        self._set_status("Manueller Import läuft...", _T("YELLOW"))

        def _worker():
            try:
                from lib.db_importer import import_xml
                stats = import_xml(
                    db_path=config.DB_PATH,
                    xml_path=xml_path,
                    base_dir=config.BASE_DIR,
                    progress_cb=self._append_log,
                    supplier_name=supplier_name,
                )
                total = stats['new'] + stats['updated'] + stats['unchanged']
                self._append_log(
                    f"Manueller Import abgeschlossen: {total} Artikel "
                    f"(Lieferant: {supplier_name})", tag="ok")
            except Exception as exc:
                self._append_log(f"Manueller Import fehlgeschlagen: {exc}", tag="err")
            finally:
                self._running = False
                self.after(0, lambda: (
                    import_btn.config(state="normal") if import_btn else None,
                    self._run_btn.config(state="normal"),
                    self._set_status("Bereit", _T("FG_DIM")),
                ))

        threading.Thread(target=_worker, daemon=True).start()

    def _open_config(self):
        from lib.config_editor import ConfigEditor
        ConfigEditor(self)

    def _open_conn_test(self):
        from lib.config_editor import ConnectionTestDialog
        ConnectionTestDialog(self)

    def _open_basedir(self):
        import subprocess
        path = self._path_var.get()
        if os.path.isdir(path):
            subprocess.Popen(f'explorer "{path}"', shell=True)
        else:
            messagebox.showwarning("Pfad nicht gefunden",
                                   f"Verzeichnis existiert nicht:\n{path}", parent=self)

    # ── Log ───────────────────────────────────────────────────────────────────
    def _clear_log(self):
        self._log_txt.config(state="normal")
        self._log_txt.delete("1.0", "end")
        self._log_txt.config(state="disabled")

    def _save_log(self):
        from tkinter.filedialog import asksaveasfilename
        path = asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Textdateien", "*.txt"), ("Alle", "*.*")],
            initialfile=f"bmecat_log_{datetime.date.today():%Y%m%d}.txt",
        )
        if path:
            content = self._log_txt.get("1.0", "end")
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

    # ── Tutorial ──────────────────────────────────────────────────────────────
    def _start_tutorial(self):
        from lib.tutorial import Tutorial
        if not self._tutorial or not (
            self._tutorial._win and self._tutorial._win.winfo_exists()):
            self._tutorial = Tutorial(self, self._widget_refs)
        self._tutorial.start()

    # ── Graceful Shutdown ───────────────────────────────────────────────────────
    def _on_close(self):
        """Sauberes Beenden: laufenden Task abbrechen, dann schließen."""
        if self._running:
            if not messagebox.askyesno(
                "Lauf aktiv",
                "Ein Lauf ist noch aktiv. Wirklich beenden?\n"
                "Der laufende Task wird abgebrochen.",
                parent=self
            ):
                return
            self._running = False
            # Thread hat daemon=True, wird automatisch beendet
            self._append_log("Programm wird geschlossen – Abbruch ...", tag="warn")
        self.destroy()

    # ── Task-Ausfuehrung ──────────────────────────────────────────────────────
    def _check_plain_passwords(self):
        """Warnt wenn Klartext-Passwörter in config.py gefunden werden."""
        try:
            import config as _cfg
            plain = []
            for name, srv in _cfg.FTP_SERVERS.items():
                pw = srv.get("password", "")
                if pw and not str(pw).startswith("enc:"):
                    plain.append(name)
            smtp_pw = _cfg.NOTIFICATION.get("smtp_pass", "")
            if smtp_pw and not str(smtp_pw).startswith("enc:"):
                plain.append("SMTP")
            if plain:
                self._append_log(
                    f"⚠ Klartext-Passwörter in config.py: {', '.join(plain)} – "
                    "Konfigurationsreiter → '🔐 Passwort verschlüsseln' verwenden.",
                    tag="warn")
        except Exception:
            pass

    def _start_run(self):
        selected = [t for t in TASKS if self._checks[t["id"]].get()]
        if not selected:
            messagebox.showwarning("Keine Auswahl",
                                   "Bitte mindestens eine Aufgabe auswaehlen.", parent=self)
            return

        # Disk-Space-Check
        from tasks.scheduler import is_auto_mode, is_auto_daily_mode
        unattended = is_auto_mode() or is_auto_daily_mode()
        try:
            import shutil
            usage = shutil.disk_usage(config.BASE_DIR)
            free_gb = usage.free / (1024 ** 3)
            if free_gb < 2:
                if unattended:
                    # Kein Dialog im Scheduler-Lauf – würde für immer hängen,
                    # da niemand da ist um zu bestätigen. Stattdessen loggen
                    # und trotzdem versuchen.
                    self._append_log(
                        f"⚠ Nur noch {free_gb:.1f} GB frei auf {config.BASE_DIR} – "
                        f"Lauf wird trotzdem gestartet (unbeaufsichtigt).", tag="warn")
                elif not messagebox.askyesno(
                    "Wenig Speicherplatz",
                    f"Nur noch {free_gb:.1f} GB frei auf {config.BASE_DIR}.\n"
                    f"Das Tool braucht ca. 2 GB pro Lauf.\n\n"
                    f"Trotzdem fortfahren?",
                    parent=self
                ):
                    return
            elif free_gb < 5:
                self._append_log(
                    f"⚠ Speicherplatz knapp: {free_gb:.1f} GB frei auf "
                    f"{config.BASE_DIR}", tag="warn")
        except Exception:
            pass

        # Config-Validierung
        problems = validate_config()
        if problems:
            for msg in problems:
                self._append_log(f"⚠ Config: {msg}", tag="warn")

        selected.sort(key=lambda t: (TASK_GROUP_ORDER.get(t.get("group", ""), 9), t["id"]))

        self._running = True
        self._set_status("Läuft...", _T("YELLOW"))
        self._run_btn.config(state="disabled")
        self._stop_btn.config(state="normal")
        self._progress.config(mode="indeterminate", value=0)
        self._progress.start(12)
        self._file_lbl.config(text="")
        self._speed_lbl.config(text="")
        self._set_status("Laeuft ...", _T("YELLOW"))

        self._thread = threading.Thread(
            target=self._worker, args=(selected,), daemon=True)
        self._thread.start()

    def _stop_run(self):
        self._running = False
        self._set_status("Abgebrochen", _T("RED"))
        self._append_log("Abbruch angefordert - laufende Aufgabe wird noch abgeschlossen.",
                         tag="warn")
        self._progress.stop()
        self._run_btn.config(state="normal")
        self._stop_btn.config(state="disabled")

    def _worker(self, tasks):
        # Einzelinstanz-Schutz: verhindert Doppelstart durch Scheduler
        from lib.run_lock import RunLock, RunLockError
        try:
            lock = RunLock(config.BASE_DIR)
            if not lock.acquire():
                self._append_log(
                    "⚠ Lauf bereits aktiv – dieser Start wird übersprungen.",
                    tag="warn")
                lock.release()
                self._parent.after(0, self._on_run_done)
                return
        except Exception:
            lock = None


        start  = datetime.datetime.now()
        errors = []
        dedup_total = {"removed": 0, "files": 0, "articles": 0}

        from lib.lauf_report import LaufReport
        report = LaufReport(config.DIRS["logs"])

        dropped_collector: list[dict] = []

        def log_cb(msg: str, tag: str = "", _dropped: dict = None):
            self._append_log(msg, tag=tag)
            if _dropped:
                dropped_collector.append(_dropped)
                report.add_dropped([_dropped])

        def file_cb(filename, pct, done, total, speed, eta):
            self.set_file_progress(filename, pct, done, total, speed, eta)

        def dedup_cb(msg: str, tag: str = ""):
            self._append_log(msg, tag=tag)
            import re as _re
            m = _re.search(r'(\d+) doppelte Features entfernt in (\d+)', msg)
            if m:
                dedup_total["removed"]  += int(m.group(1))
                dedup_total["articles"] += int(m.group(2))
                dedup_total["files"]    += 1

        for i, task in enumerate(tasks, 1):
            if not self._running:
                break
            self.after(0, self._set_status,
                       f"Task {i}/{len(tasks)}: {task['name']}", _T("YELLOW"))
            self._append_log(f"\n{'─'*60}", tag="dim")
            self._append_log(f"[{i}/{len(tasks)}] Start: {task['name']} ...", tag="info")
            report.begin_task(task["name"])
            try:
                call_task(task["fn"], progress_cb=log_cb, file_progress_cb=file_cb)
                self._append_log(f"OK: {task['name']} abgeschlossen.", tag="ok")
                report.end_task(task["name"], success=True)
            except Exception as exc:
                self._append_log(f"FEHLER: {task['name']}: {exc}", tag="err")
                log.exception(f"Task '{task['name']}' fehlgeschlagen")
                errors.append(task["name"])
                report.end_task(task["name"], success=False,
                                details={"fehler": str(exc)})
                if task["id"] == "setup_check":
                    self._append_log(
                        "⛔ Setup-Check fehlgeschlagen – weitere Tasks abgebrochen. "
                        "Setup-Check abwählen um zu überspringen.", tag="err")
                    break

        report.add_dedup(**dedup_total)
        report_path = report.write()
        if report_path:
            self._append_log(f"Lauf-Report: {os.path.basename(report_path)}",
                             tag="dim")
        # Dropped-Articles CSV
        dropped_csv = report.write_dropped_csv()
        if dropped_csv:
            self._append_log(
                f"⚠ {len(report.dropped_articles)} Artikel nicht mehr im "
                f"Lieferantenkatalog → {os.path.basename(dropped_csv)}", tag="warn")

        # ── DB-Backup ─────────────────────────────────────────────────────
        try:
            from lib.db_backup import run_backup
            run_backup(config.DB_PATH, progress_cb=log_cb)
        except Exception as e:
            log.warning(f"DB-Backup Fehler: {e}")

        # ── Preisregel-Ablauf prüfen ───────────────────────────────────────
        try:
            from lib.db_postprocess import _load_price_rules, _check_price_expiry
            price_rules    = _load_price_rules(config.BASE_DIR)
            price_warnings = _check_price_expiry(price_rules)
            if price_warnings:
                for w in price_warnings:
                    self._append_log(f"⚠ Preisregel: {w}", tag="warn")
                report.add_price_warnings(price_warnings)
        except Exception as e:
            log.debug(f"Preisregel-Check Fehler: {e}")

        # ── E-Mail-Benachrichtigung ────────────────────────────────────────
        try:
            from lib.notifier import send_run_notification
            send_run_notification(
                report.as_dict(),
                dropped_articles=report.dropped_articles,
                price_warnings=report.price_warnings,
            )
        except Exception as e:
            log.debug("Benachrichtigung übersprungen: %s", e)

        # Trend-Report automatisch aktualisieren
        try:
            from lib.dashboard import generate_trend_report
            generate_trend_report(config.DIRS["logs"])
        except Exception:
            pass

        elapsed = datetime.datetime.now() - start
        self._append_log(f"\n{'─'*60}", tag="dim")
        self._append_log(
            f"Laufzeit: {str(elapsed).split('.')[0]}  |  "
            f"Fehler: {len(errors)}/{len(tasks)}", tag="dim")

        if dedup_total["removed"] > 0:
            self._append_log(
                f"⚠ Deduplizierung: {dedup_total['removed']} doppelte Features "
                f"entfernt in {dedup_total['articles']} Artikel(n) "
                f"aus {dedup_total['files']} Datei(en) – Details siehe Log oben.",
                tag="warn")

        self.after(0, self._finish, errors, dedup_total)

    def _finish(self, errors, dedup_total=None):
        self._running = False
        self._progress.stop()
        self._progress.config(mode="determinate", value=0)
        self._file_lbl.config(text="")
        self._speed_lbl.config(text="")
        self._run_btn.config(state="normal")
        self._stop_btn.config(state="disabled")

        if errors:
            self._set_status(f"Fehler bei: {', '.join(errors)}", _T("RED"))
        elif dedup_total and dedup_total["removed"] > 0:
            self._set_status(
                f"Fertig – {dedup_total['removed']} Duplikate entfernt", _T("YELLOW"))
        else:
            self._set_status("Alle Aufgaben abgeschlossen", _T("GREEN"))

    # ── Hilfsmethoden ─────────────────────────────────────────────────────────
    def _set_status(self, text, color=None):
        color = color or _T("FG")
        icon = "●  "
        if color in (_T("GREEN"), "#3fb950", "#15803d", "#50fa7b"):
            icon = "●  "
        elif color in (_T("RED"), "#f85149", "#dc2626", "#ff5555"):
            icon = "✗  "
        elif color in (_T("YELLOW"), "#d29922", "#f1fa8c", "#b45309"):
            icon = "⚠  "
        self._status_lbl.config(text=icon + text, fg=color)

    def _append_log(self, msg: str, tag: str = ""):
        def _do():
            self._log_txt.config(state="normal")
            ts   = datetime.datetime.now().strftime("%H:%M:%S")
            line = f"[{ts}]  {msg}\n"
            self._log_txt.insert("end", line, tag if tag else "")
            self._log_txt.see("end")
            self._log_txt.config(state="disabled")
            self._write_file_log(line)
        self.after(0, _do)

    def set_file_progress(self, filename: str, pct: float,
                          done_bytes: int, total_bytes: int, speed: float, eta: float):
        """Wird aus dem Download-Thread via after() aufgerufen."""
        from lib.ftp_client import _fmt_size
        def _do():
            if total_bytes > 0:
                size_str = f"{_fmt_size(done_bytes)} / {_fmt_size(total_bytes)}"
                eta_str  = f"  ETA {eta:.0f}s" if eta > 0 else ""
                self._file_lbl.config(
                    text=f"  {filename}  {size_str}{eta_str}")
            else:
                self._file_lbl.config(
                    text=f"  {filename}  {_fmt_size(done_bytes)}")
            self._speed_lbl.config(text=f"{_fmt_size(int(speed))}/s  ")
            self._progress.stop()
            self._progress.config(mode="determinate", value=min(pct, 100))
        self.after(0, _do)

    def _write_file_log(self, line: str):
        try:
            log_dir = config.DIRS["logs"]
            Path(log_dir).mkdir(parents=True, exist_ok=True)
            fname = os.path.join(log_dir, f"Log_{datetime.date.today():%Y%m%d}.txt")
            with open(fname, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass


# ── Logging-Handler fuer GUI ──────────────────────────────────────────────────

class _GuiLogHandler(logging.Handler):
    def __init__(self, append_fn):
        super().__init__()
        self._append = append_fn

    def emit(self, record):
        msg = self.format(record)
        tag = ""
        if record.levelno >= logging.ERROR:
            tag = "err"
        elif record.levelno == logging.WARNING:
            tag = "warn"
        self._append(msg, tag=tag)


# ── Einstiegspunkt ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import traceback

    def _crash_handler(exc_type, exc_value, exc_tb):
        """Schreibt ungefangene Ausnahmen in crash_YYYYMMDD.txt vor dem Absturz."""
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        try:
            crash_dir = os.path.join(os.path.dirname(__file__),
                                     config.DIRS.get("logs", "logs"))
            os.makedirs(crash_dir, exist_ok=True)
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            crash_path = os.path.join(crash_dir, f"crash_{stamp}.txt")
            with open(crash_path, "w", encoding="utf-8") as f:
                f.write(f"BMEcat Download-Tool v{VERSION} — Crash Report\n")
                f.write(f"Zeitpunkt: {datetime.datetime.now().isoformat()}\n\n")
                traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _crash_handler

    app = App()
    # --auto: direkt Standard-Tasks starten (für Scheduler)
    # --auto-daily: nur die Aufgaben der Rubrik "Täglich" starten (für Scheduler)
    from tasks.scheduler import is_auto_mode, is_auto_daily_mode
    if is_auto_daily_mode():
        app.after(400, app._select_daily)
        app.after(500, app._start_run)   # kurz warten bis GUI bereit
    elif is_auto_mode():
        app.after(500, app._start_run)   # kurz warten bis GUI bereit
    app.mainloop()
