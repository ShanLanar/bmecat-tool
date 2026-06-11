# Konstruktionsprinzipien – ABE Tool-Framework

Dieses Dokument beschreibt die Architektur und Konventionen des
BMEcat Download-Tools als Vorlage für weitere Tools im gleichen Framework.

---

## 1. Projektstruktur

```
tool_name/
│
├── main.py               # GUI-Einstiegspunkt (tkinter). Enthält App-Klasse,
│                         # Task-Registry, Threading-Steuerung.
├── config.py             # Alle Konstanten: Pfade, Zugangsdaten, Einstellungen.
├── config_user.json      # Laufzeit-Overrides (von config_editor erzeugt, .gitignore)
├── requirements.txt      # pip-Abhängigkeiten
├── install.bat           # Ersteinrichtung: findet Python, installiert pip + deps
├── start.bat             # Täglicher Start (kein install)
│
├── lib/                  # Wiederverwendbare Bibliotheken (kein GUI, kein State)
│   ├── ftp_client.py     # FTP/SFTP-Wrapper (WinSCP-Ersatz)
│   ├── config_editor.py  # Konfigurations-Dialog + ConnectionTestDialog
│   └── connection_test.py# Verbindungstest-Logik (ohne GUI)
│
└── tasks/                # Je eine Datei pro Aufgabe / Lieferant
    ├── __init__.py
    ├── cleanup.py
    └── mein_task.py
```

---

## 2. Farbschema und Stil (Dark Theme)

Alle Konstanten sind in `main.py` oben definiert und müssen in neuen Tools
identisch übernommen werden:

```python
BG        = "#1e1e2e"   # Haupthintergrund
BG2       = "#2a2a3e"   # Panels, linke Spalte, Header/Footer
BG3       = "#232336"   # Eingabefelder
ACCENT    = "#7c7cf8"   # Buttons, Überschriften
GREEN     = "#50fa7b"   # Erfolg, Status "OK"
RED       = "#ff5555"   # Fehler, Abbrechen-Button
YELLOW    = "#f1fa8c"   # Warnungen, "läuft..."
ORANGE    = "#ffb86c"   # Info-Meldungen im Log
FG        = "#cdd6f4"   # Standardtext
FG_DIM    = "#6c7086"   # Beschreibungen, Labels, Zeitstempel

FONT_MAIN = ("Segoe UI", 10)
FONT_MONO = ("Consolas", 9)       # Log, Pfade, Eingabefelder
FONT_HEAD = ("Segoe UI Semibold", 11)
```

---

## 3. GUI-Layout (App-Klasse)

```
┌─────────────────────────────────────────────────────────┐
│ HEADER (BG2)  Titel    [Btn] [Btn]          Status-Label│
├──────────────┬──────────────────────────────────────────┤
│ LINKE SPALTE │ Obere Zeile: Pfad / Optionen             │
│ (BG2)        ├──────────────────────────────────────────┤
│ scrollbarer  │                                          │
│ Canvas mit   │  LOG-FENSTER (scrolledtext, bg #13131f)  │
│ Checkboxen   │                                          │
│ + Buttons    │                                          │
│              ├──────────────────────────────────────────┤
│              │ Fortschritts-Label + Progressbar         │
├──────────────┴──────────────────────────────────────────┤
│ FOOTER (BG2)  [Starten] [Abbrechen]    [Log] [Log spch]│
└─────────────────────────────────────────────────────────┘
```

### Linke Spalte
- Scrollbarer `tk.Canvas` + `ttk.Scrollbar` + innerer `tk.Frame`
- Mausrad-Binding auf Canvas, alle Labels und Checkboxen
- Tasks werden nach Gruppen sortiert angezeigt (Gruppenname in Caps)
- Jeder Task: Checkbox + Beschreibungs-Label darunter (eingerückt)
- Unten: Buttons „Alle / Keine / Standard"

### Fortschrittsbereich
- Zwei Labels: Dateiname+Bytes links, Speed rechts
- `ttk.Progressbar` mode="determinate" (0–100)
- Beim Start: mode="indeterminate" + start()
- Beim Datei-Transfer: mode="determinate", Wert via `set_file_progress()`
- Nach Abschluss: stop() + value=0

### Log-Fenster
- `scrolledtext.ScrolledText`, state="disabled" außer beim Schreiben
- Tags: `"ok"` (GREEN), `"err"` (RED), `"warn"` (YELLOW), `"info"` (ORANGE), `"dim"` (FG_DIM)
- Kein direkter Widget-Zugriff aus Threads – immer via `self.after(0, _do)`
- Fortschrittszeilen werden **nicht** in die Log-Datei geschrieben

---

## 4. Task-System

### Definition in TASKS-Liste

```python
TASKS = [
    {
        "id":      "mein_task",           # eindeutig, snake_case
        "name":    "Anzeigename",         # in der Checkbox
        "desc":    "Kurzbeschreibung",    # darunter (klein, grau)
        "fn":      "tasks.mein_task:run", # Modul:Funktion
        "default": True,                  # Checkbox-Startzustand
        "group":   "Gruppe",              # Abschnittsüberschrift
    },
]
```

### Gruppen-Reihenfolge (Konvention)
```
Vorbereitung → Lieferanten → Upload → Extras
```

### Task-Funktion Signatur

```python
def run(progress_cb=None, file_progress_cb=None):
    p  = progress_cb      or (lambda m, **kw: None)
    fp = file_progress_cb or None
    ...
    p("Nachricht ins Log")
    p("Warnung", tag="warn")
    p("Erfolg",  tag="ok")
```

- `progress_cb(msg, tag="")` → Textzeile ins Log
- `file_progress_cb(filename, pct, done_bytes, total_bytes, speed_bps, eta_s)` → Fortschrittsbalken
- Beide sind optional; Tasks ohne FTP brauchen `file_progress_cb` nicht
- `inspect.signature` prüft ob `file_progress_cb` im Parameter-Set ist → kein Bruch bei alten Tasks

### Task-Dispatch

```python
def _call_task(fn_spec: str, progress_cb, file_progress_cb=None):
    module_path, func_name = fn_spec.rsplit(":", 1)
    mod = importlib.import_module(module_path)
    fn  = getattr(mod, func_name)
    import inspect
    if "file_progress_cb" in inspect.signature(fn).parameters:
        fn(progress_cb=progress_cb, file_progress_cb=file_progress_cb)
    else:
        fn(progress_cb=progress_cb)
```

### Ausführungsreihenfolge

Tasks werden vor dem Start nach Gruppe sortiert:
```python
group_order = {"Vorbereitung": 0, "Lieferanten": 1, "Upload": 2, "Extras": 3}
selected.sort(key=lambda t: (group_order.get(t.get("group", ""), 9), t["id"]))
```

---

## 5. Threading-Modell

- Alle Tasks laufen in einem einzigen `threading.Thread(daemon=True)`
- GUI-Updates **ausschließlich** via `self.after(0, callable)`
- `_running`-Flag für Abbruch: Tasks prüfen es zwischen Schritten
- Kein `threading.Lock` nötig solange Tasks sequenziell laufen

```python
# Worker-Thread-Muster
def _worker(self, tasks):
    for task in tasks:
        if not self._running:
            break
        try:
            _call_task(task["fn"], log_cb, file_cb)
        except Exception as exc:
            self._append_log(f"FEHLER: {exc}", tag="err")
    self.after(0, self._finish, errors)
```

---

## 6. FTP/SFTP-Client (lib/ftp_client.py)

### make_client(cfg)

```python
cfg = {
    "host":     "ftp.example.com",
    "user":     "user",
    "password": "pass",
    "protocol": "ftp",   # oder "sftp"
    "port":     21,
}
client = make_client(cfg)
client.connect()
client.download("remote/path/file.zip", local_dir,
                progress_cb=p, file_progress_cb=fp)
client.upload("/local/file.csv", "/remote/dir",
              delete_after=False,
              progress_cb=p, file_progress_cb=fp)
client.disconnect()
```

### Performance-Einstellungen
```python
FTP_BLOCKSIZE  = 8 * 1024 * 1024    # 8 MB
SOCKET_BUF     = 16 * 1024 * 1024   # SO_RCVBUF/SO_SNDBUF
SFTP_WINDOW    = 64 * 1024 * 1024   # SSH Window
SFTP_MAX_PACKET= 32 * 1024          # Paketgröße
# SFTP-Download via readv() mit max_concurrent_prefetch_requests=64
# → hält Pipeline dauerhaft gefüllt, kein stop-and-wait
```

### Fortschritts-Callbacks
- `file_progress_cb` wird max. alle 200 ms aufgerufen (throttled)
- Signature: `(filename: str, pct: float, done: int, total: int, speed: float, eta: float)`
- `pct=100, eta=0` beim Abschluss

---

## 7. Konfiguration (config.py + config_user.json)

### config.py – Struktur
```python
BASE_DIR = r"C:\mein_tool"

DIRS = {
    "in":   r"C:\mein_tool\in",
    "logs": r"C:\mein_tool\logs",
    ...
}

TOOLS = {
    "7zip": r"C:\Program Files\7-Zip\7z.exe",
}

CONNECTIONS = {
    "server_name": {
        "host":     "...",
        "user":     "...",
        "password": "...",
        "protocol": "ftp",   # oder "sftp"
        "port":     21,
        "remote_path": "/pfad/",   # optional, task-spezifisch
    },
}
```

### Laufzeit-Overrides
`config_user.json` überschreibt Werte aus `config.py` ohne sie zu ändern.
`apply_overrides()` aus `lib/config_editor.py` beim Start aufrufen:

```python
from lib.config_editor import apply_overrides
apply_overrides()   # vor import config
import config
```

---

## 8. 7-Zip-Aufrufe

Niemals `os.system()` – immer `subprocess.run()` mit Fehlerprüfung:

```python
import subprocess

def _run_7zip(seven_z, zip_path, out_dir, filter_=None, p=None):
    if not os.path.exists(seven_z):
        if p: p(f"7-Zip nicht gefunden: {seven_z}", tag="warn")
        return False
    cmd = [seven_z, "e", zip_path, f"-o{out_dir}", "-y"]
    if filter_: cmd.append(filter_)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0 and p:
            p(f"7-Zip Fehler ({r.returncode}): {r.stderr.strip()}", tag="warn")
        return r.returncode == 0
    except Exception as e:
        if p: p(f"7-Zip Exception: {e}", tag="warn")
        return False
```

Umbenennung nach dem Entpacken: **Vorher/Nachher-Vergleich** von `os.listdir()`,
nicht Glob-Pattern auf den Dateinamen – der interne ZIP-Dateiname ist oft unbekannt.

---

## 9. Logging

- Tägliche Log-Datei: `DIRS["logs"]/Log_YYYYMMDD.txt`
- Fortschrittszeilen **nicht** in die Datei schreiben (zu viel Rauschen)
- `logging.getLogger(__name__)` in jeder Datei für Modul-Logs
- GUI-Handler leitet `logging`-Meldungen ins Log-Widget um

---

## 10. install.bat / start.bat Muster

```bat
@echo off
:: Python suchen (python, py, typische Installationspfade)
python --version >nul 2>&1
if %errorlevel% == 0 ( set PYTHON=python & goto found )
py --version >nul 2>&1
if %errorlevel% == 0 ( set PYTHON=py & goto found )
:: ... weitere Pfade ...
echo Python nicht gefunden. & pause & exit /b 1

:found
%PYTHON% -m ensurepip --upgrade >nul 2>&1
%PYTHON% -m pip install -r "%~dp0requirements.txt" --quiet
%PYTHON% "%~dp0main.py"
```

`pip` niemals direkt aufrufen – immer `%PYTHON% -m pip`, da `pip` oft nicht im PATH ist.

---

## 11. Konventionen

| Thema | Regel |
|---|---|
| Encoding | UTF-8 überall; CSV-Export für Excel: `utf-8-sig` |
| Pfadtrenner | `os.path.join()`, nie hartcodierte Backslashes in Code |
| FTP-Navigation | Vor jedem `cwd()` erst `cwd("/")` → verhindert relative Pfadfehler |
| Fehlende Dateien | Nie einfach Exception – erst versuchen nachzuladen |
| os.system() | Verboten. Immer `subprocess.run()` |
| GUI aus Thread | Nur via `self.after(0, callable)` |
| Passwörter | In `config.py`, nie in Task-Dateien |
| Tag-Keyword | `p("msg", tag="warn")` – `**kw` in Lambda-Default absorbiert unbekannte Keys |
