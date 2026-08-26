# tasks/scheduler.py – Automatischen Start einrichten
#
# Zwei Methoden:
#   A) Windows Task Scheduler (schtasks) – empfohlen, läuft auch wenn nicht eingeloggt
#   B) Einfache Zeitsteuerung im laufenden Programm (schedule-Bibliothek, optional)

import os
import sys
import subprocess
import logging
from datetime import datetime

log = logging.getLogger(__name__)

TASK_NAME = "BMEcatDownloadTool"


# ── Windows Task Scheduler ────────────────────────────────────────────────────

def _python_exe() -> str:
    """Findet den aktuellen Python-Interpreter."""
    return sys.executable or "python"


def schedule_daily(hour: int, minute: int,
                   progress_cb=None) -> bool:
    """
    Richtet einen täglichen Task im Windows Task Scheduler ein.
    Startet main.py mit allen Standard-Tasks.
    Gibt True bei Erfolg zurück.
    """
    p = progress_cb or (lambda m, **kw: None)

    script_dir  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    main_py     = os.path.join(script_dir, "main.py")
    python_exe  = _python_exe()
    time_str    = f"{hour:02d}:{minute:02d}"

    # Bestehenden Task zuerst löschen (Fehler ignorieren)
    subprocess.run(
        ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
        capture_output=True)

    cmd = [
        "schtasks", "/create",
        "/tn",  TASK_NAME,
        "/tr",  f'"{python_exe}" "{main_py}" --auto',
        "/sc",  "DAILY",
        "/st",  time_str,
        "/rl",  "HIGHEST",
        "/f",
    ]

    p(f"Erstelle Task '{TASK_NAME}' für {time_str} Uhr ...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        p(f"Task '{TASK_NAME}' erfolgreich eingerichtet.", tag="ok")
        p(f"  Python:  {python_exe}")
        p(f"  Skript:  {main_py}")
        p(f"  Zeit:    täglich {time_str} Uhr")
        return True
    else:
        p(f"Fehler beim Einrichten: {result.stderr.strip()}", tag="warn")
        p("Hinweis: Administratorrechte erforderlich.", tag="warn")
        return False


def remove_schedule(progress_cb=None) -> bool:
    """Entfernt den Task aus dem Windows Task Scheduler."""
    p = progress_cb or (lambda m, **kw: None)
    result = subprocess.run(
        ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
        capture_output=True, text=True)
    if result.returncode == 0:
        p(f"Task '{TASK_NAME}' entfernt.", tag="ok")
        return True
    else:
        p(f"Task nicht gefunden oder Fehler: {result.stderr.strip()}", tag="warn")
        return False


def get_schedule_info() -> dict:
    """Liest den aktuellen Status des Tasks aus."""
    result = subprocess.run(
        ["schtasks", "/query", "/tn", TASK_NAME, "/fo", "LIST"],
        capture_output=True, text=True)
    if result.returncode != 0:
        return {"exists": False}

    info = {"exists": True, "raw": result.stdout}
    for line in result.stdout.splitlines():
        if "Nächste Ausführungszeit" in line or "Next Run Time" in line:
            info["next_run"] = line.split(":", 1)[-1].strip()
        if "Letzte Ausführungszeit" in line or "Last Run Time" in line:
            info["last_run"] = line.split(":", 1)[-1].strip()
        if "Status" in line:
            info["status"] = line.split(":", 1)[-1].strip()
    return info


# ── GUI-Dialog ────────────────────────────────────────────────────────────────

def open_scheduler_dialog(parent=None):
    """Öffnet den Scheduler-Einrichtungs-Dialog."""
    import tkinter as tk
    from tkinter import ttk, messagebox

    BG = "#1e1e2e"; BG2 = "#2a2a3e"; BG3 = "#232336"
    ACCENT = "#7c7cf8"; GREEN = "#50fa7b"; RED = "#ff5555"
    YELLOW = "#f1fa8c"; FG = "#cdd6f4"; FG_DIM = "#6c7086"

    win = tk.Toplevel(parent)
    win.title("Automatischer Start")
    win.configure(bg=BG)
    win.geometry("480x400")
    win.minsize(420, 340)
    win.grab_set()

    tk.Label(win, text="Automatischer Start einrichten",
             font=("Segoe UI Semibold", 12), bg=BG2, fg=ACCENT,
             pady=10).pack(fill="x")

    # Status-Bereich
    status_frame = tk.Frame(win, bg=BG2, padx=16, pady=10)
    status_frame.pack(fill="x", padx=10, pady=(8, 4))

    info = get_schedule_info()
    if info["exists"]:
        status_text = (f"Task aktiv\n"
                       f"Nächste Ausführung: {info.get('next_run', '?')}\n"
                       f"Letzte Ausführung:  {info.get('last_run', '?')}")
        status_color = GREEN
    else:
        status_text  = "Kein automatischer Start eingerichtet."
        status_color = FG_DIM

    tk.Label(status_frame, text="Status:", font=("Segoe UI", 9),
             bg=BG2, fg=FG_DIM).grid(row=0, column=0, sticky="w")
    tk.Label(status_frame, text=status_text, font=("Consolas", 9),
             bg=BG2, fg=status_color, justify="left"
             ).grid(row=0, column=1, sticky="w", padx=8)

    ttk.Separator(win, orient="horizontal").pack(fill="x", padx=10, pady=6)

    # Zeit-Auswahl
    time_frame = tk.Frame(win, bg=BG, padx=16, pady=8)
    time_frame.pack(fill="x")

    tk.Label(time_frame, text="Startzeit:", font=("Segoe UI", 10),
             bg=BG, fg=FG).grid(row=0, column=0, sticky="w")

    hour_var   = tk.StringVar(value="06")
    minute_var = tk.StringVar(value="00")

    hour_spin = tk.Spinbox(time_frame, from_=0, to=23, width=3,
                           textvariable=hour_var, format="%02.0f",
                           font=("Consolas", 12),
                           bg=BG3, fg=FG, buttonbackground=BG2,
                           relief="flat", bd=4)
    hour_spin.grid(row=0, column=1, padx=(12, 4))

    tk.Label(time_frame, text=":", font=("Consolas", 14),
             bg=BG, fg=FG).grid(row=0, column=2)

    min_spin = tk.Spinbox(time_frame, values=["00","05","10","15","20","25",
                                               "30","35","40","45","50","55"],
                          width=3, textvariable=minute_var,
                          font=("Consolas", 12),
                          bg=BG3, fg=FG, buttonbackground=BG2,
                          relief="flat", bd=4)
    min_spin.grid(row=0, column=3, padx=(4, 12))

    tk.Label(time_frame, text="Uhr (täglich)",
             font=("Segoe UI", 10), bg=BG, fg=FG_DIM
             ).grid(row=0, column=4)

    # Log
    from tkinter import scrolledtext
    log_txt = scrolledtext.ScrolledText(win, font=("Consolas", 9),
                                        bg="#13131f", fg=FG, relief="flat",
                                        state="disabled", height=7)
    log_txt.pack(fill="both", expand=True, padx=10, pady=6)
    log_txt.tag_config("ok",   foreground=GREEN)
    log_txt.tag_config("warn", foreground=YELLOW)

    def p(msg, tag=""):
        log_txt.config(state="normal")
        log_txt.insert("end", msg + "\n", tag)
        log_txt.see("end")
        log_txt.config(state="disabled")

    # Buttons
    btn_frame = tk.Frame(win, bg=BG2, pady=8, padx=12)
    btn_frame.pack(fill="x")

    def do_schedule():
        try:
            h = int(hour_var.get())
            m = int(minute_var.get())
        except ValueError:
            p("Ungültige Zeitangabe.", "warn")
            return
        schedule_daily(h, m, progress_cb=p)

    def do_remove():
        if messagebox.askyesno("Task entfernen",
                               "Automatischen Start wirklich entfernen?",
                               parent=win):
            remove_schedule(progress_cb=p)

    def do_test_all():
        p("Teste alle Verbindungen ...")
        from config import CONNECTIONS
        from lib.ftp_client import make_client
        ok = 0
        fail = 0
        for name, cfg in CONNECTIONS.items():
            try:
                cl = make_client(cfg)
                cl.connect()
                cl.disconnect()
                p(f"  ✓ {name}", tag="ok")
                ok += 1
            except Exception as e:
                p(f"  ✗ {name}: {e}", tag="warn")
                fail += 1
        p(f"Ergebnis: {ok} OK, {fail} Fehler",
          tag="ok" if fail == 0 else "warn")

    def do_test():
        p("Teste Task-Scheduler-Zugriff ...")
        result = subprocess.run(["schtasks", "/query"], capture_output=True)
        if result.returncode == 0:
            p("Zugriff OK.", "ok")
        else:
            p("Kein Zugriff – Administratorrechte erforderlich.", "warn")

    for text, cmd, color in [
        ("Einrichten",           do_schedule,  ACCENT),
        ("Entfernen",            do_remove,    RED),
        ("Verbindungen testen",  do_test_all,  BG2),
        ("Scheduler testen",     do_test,      BG2),
    ]:
        tk.Button(btn_frame, text=text, command=cmd,
                  font=("Segoe UI", 9), bg=color, fg=FG,
                  relief="flat", padx=10, pady=4, cursor="hand2"
                  ).pack(side="left", padx=3)

    tk.Button(btn_frame, text="Schließen", command=win.destroy,
              font=("Segoe UI", 9), bg=BG2, fg=FG,
              relief="flat", padx=10, pady=4
              ).pack(side="right", padx=3)


# ── Auto-Modus für --auto Flag ────────────────────────────────────────────────

def is_auto_mode() -> bool:
    """True wenn das Programm via Scheduler mit --auto gestartet wurde."""
    return "--auto" in sys.argv


def is_auto_daily_mode() -> bool:
    """True wenn das Programm via Scheduler mit --auto-daily gestartet wurde
    (führt nur die Aufgaben der Rubrik "Täglich" aus, unabhängig von den
    sonst angehakten Standard-Aufgaben)."""
    return "--auto-daily" in sys.argv


def is_dry_run() -> bool:
    """True wenn --dry-run übergeben wurde (simuliert alle Tasks ohne Upload)."""
    return "--dry-run" in sys.argv or "-n" in sys.argv
