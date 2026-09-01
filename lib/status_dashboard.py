# lib/status_dashboard.py – Lauf-Status-Ampel (HTML)
#
# Liest die vorhandenen Lauf-Reports (logs/lauf_*.json, geschrieben von
# lib/lauf_report.py nach jedem Programmlauf) und erzeugt
# logs/lauf_status_dashboard.html — eine Ampel-Übersicht je Task, damit
# ein fehlgeschlagener Kanal-Upload (z.B. eine erschöpfte Inode-Grenze auf
# einem FTP-Server) sichtbar ist, ohne Logdateien durchsuchen zu müssen.

import os
import json
import glob
import logging
from datetime import datetime

log = logging.getLogger(__name__)

_DOT_OK   = '<span class="dot ok"></span>'
_DOT_BAD  = '<span class="dot bad"></span>'
_DOT_NONE = '<span class="dot none"></span>'


def _load_reports(log_dir: str, max_reports: int = 20) -> list:
    """Liest die letzten N Lauf-Reports (neueste zuerst)."""
    pattern = os.path.join(log_dir, "lauf_*.json")
    files = sorted(glob.glob(pattern), reverse=True)[:max_reports]
    reports = []
    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                reports.append(json.load(fh))
        except Exception:
            pass
    return reports


def _fmt_time(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return iso or "?"


def _task_row(name: str, history: list) -> str:
    """history: Liste von {'status': 'ok'|'fehler', 'ende': iso, 'dauer_s': n}, neueste zuerst."""
    latest = history[0]
    status_class = "ok" if latest["status"] == "ok" else "bad"
    status_text  = "OK" if latest["status"] == "ok" else "FEHLER"
    dots = "".join(_DOT_OK if h["status"] == "ok" else _DOT_BAD
                   for h in reversed(history[:10]))
    return f"""
    <tr class="{status_class}">
      <td class="name">{name}</td>
      <td class="status"><span class="badge {status_class}">{status_text}</span></td>
      <td class="time">{_fmt_time(latest['ende'])}</td>
      <td class="dur">{latest['dauer_s']:.0f}s</td>
      <td class="history">{dots}</td>
    </tr>"""


def generate_status_dashboard(log_dir: str, progress_cb=None) -> str:
    """
    Erzeugt logs/lauf_status_dashboard.html aus den letzten Lauf-Reports.
    Gibt den Pfad zur erzeugten Datei zurück (leer wenn keine Reports da sind).
    """
    p = progress_cb or (lambda m, **kw: None)
    reports = _load_reports(log_dir)

    if not reports:
        p("Status-Dashboard: keine Lauf-Reports gefunden.", tag="warn")
        return ""

    # Je Task-Name die Historie über die letzten Läufe einsammeln
    # (jüngster Lauf zuerst, da reports bereits so sortiert sind).
    per_task: dict[str, list] = {}
    for report in reports:
        for t in report.get("tasks", []):
            per_task.setdefault(t["name"], []).append({
                "status":  t["status"],
                "ende":    report.get("ende", ""),
                "dauer_s": t.get("duration_s", 0),
            })

    latest = reports[0]
    total_errors = latest.get("tasks_fehler", 0)
    overall_class = "bad" if total_errors else "ok"
    overall_text  = f"{total_errors} Fehler" if total_errors else "Alles OK"

    rows = "".join(_task_row(name, hist) for name, hist in per_task.items())

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BMEcat Lauf-Status</title>
<style>
  :root {{
    --bg:       #1a1a2e;
    --surface:  #16213e;
    --surface2: #0f3460;
    --text:     #eaeaea;
    --dim:      #888;
    --good:     #4caf50;
    --warn:     #ff9800;
    --bad:      #f44336;
    --border:   #2a2a4a;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text);
          font-family: 'Segoe UI', system-ui, sans-serif;
          font-size: 14px; line-height: 1.5; }}
  header {{ background: var(--surface2); padding: 20px 32px; }}
  header h1 {{ font-size: 20px; margin-bottom: 4px; }}
  header .sub {{ color: var(--dim); font-size: 13px; }}
  .overall {{ display: inline-block; padding: 4px 14px; border-radius: 999px;
              font-weight: 600; font-size: 13px; margin-top: 8px; }}
  .overall.ok  {{ background: rgba(76,175,80,0.18); color: var(--good); }}
  .overall.bad {{ background: rgba(244,67,54,0.18);  color: var(--bad); }}
  main {{ padding: 24px 32px; }}
  table {{ width: 100%; border-collapse: collapse; background: var(--surface);
           border-radius: 8px; overflow: hidden; }}
  th {{ text-align: left; padding: 10px 14px; background: var(--surface2);
        color: var(--dim); font-size: 12px; text-transform: uppercase;
        letter-spacing: 0.04em; }}
  td {{ padding: 10px 14px; border-top: 1px solid var(--border); }}
  tr.bad td.name {{ color: var(--bad); }}
  .badge {{ padding: 2px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; }}
  .badge.ok  {{ background: rgba(76,175,80,0.18); color: var(--good); }}
  .badge.bad {{ background: rgba(244,67,54,0.18); color: var(--bad); }}
  .time, .dur {{ color: var(--dim); white-space: nowrap; }}
  .dot {{ display: inline-block; width: 9px; height: 9px; border-radius: 50%;
          margin-right: 3px; }}
  .dot.ok   {{ background: var(--good); }}
  .dot.bad  {{ background: var(--bad); }}
  .dot.none {{ background: var(--border); }}
  .history {{ white-space: nowrap; }}
  footer {{ padding: 16px 32px; color: var(--dim); font-size: 12px; }}
</style>
</head>
<body>
<header>
  <h1>BMEcat Lauf-Status</h1>
  <div class="sub">Letzter Lauf: {_fmt_time(latest.get('ende', ''))}
    &nbsp;·&nbsp; {latest.get('tasks_ok', 0)} OK, {latest.get('tasks_fehler', 0)} Fehler
    &nbsp;·&nbsp; {latest.get('dauer_s', 0):.0f}s Laufzeit</div>
  <div class="overall {overall_class}">{overall_text}</div>
</header>
<main>
  <table>
    <thead>
      <tr><th>Task</th><th>Status</th><th>Letzter Lauf</th><th>Dauer</th>
          <th>Verlauf (neueste rechts)</th></tr>
    </thead>
    <tbody>{rows}
    </tbody>
  </table>
</main>
<footer>Basiert auf den letzten {len(reports)} Lauf-Reports (logs/lauf_*.json).</footer>
</body>
</html>"""

    out_path = os.path.join(log_dir, "lauf_status_dashboard.html")
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        p(f"Status-Dashboard aktualisiert: {os.path.basename(out_path)}", tag="dim")
    except Exception as e:
        log.error(f"Status-Dashboard konnte nicht geschrieben werden: {e}")
        return ""

    return out_path


def run_status_dashboard_task(progress_cb=None, file_progress_cb=None):
    """Task-Wrapper: Status-Dashboard manuell (neu) erzeugen."""
    from config import DIRS
    return generate_status_dashboard(DIRS.get("logs", "."), progress_cb=progress_cb)
