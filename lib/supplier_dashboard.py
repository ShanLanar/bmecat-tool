# lib/supplier_dashboard.py – Lieferanten-Statistik (HTML)
#
# Liest den je Lauf gespeicherten Schnappschuss von lib.article_db.stats()
# aus logs/lauf_*.json ("supplier_stats") und zeigt:
#   - aktuelle Artikelzahl je Lieferant, aufgeteilt in online/offline
#   - Verlauf der Artikelzahl je Lieferant über die letzten Läufe
#
# lauf_*.json ohne supplier_stats (ältere Läufe vor Einführung dieses
# Felds) werden einfach übersprungen.

import os
import json
import glob
import logging
from datetime import datetime

log = logging.getLogger(__name__)

_LINE_COLORS = [
    "#e94560", "#4caf50", "#ff9800", "#2196f3", "#9c27b0",
    "#00bcd4", "#ffc107", "#795548",
]


def _de(n: int) -> str:
    """Ganzzahl mit deutscher Tausendertrennung (Punkt)."""
    return f"{n:,}".replace(",", ".")


def _load_runs(log_dir: str, max_runs: int = 30) -> list:
    pattern = os.path.join(log_dir, "lauf_*.json")
    files = sorted(glob.glob(pattern))[-max_runs:]
    runs = []
    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            continue
        if data.get("supplier_stats", {}).get("by_supplier_detail"):
            runs.append(data)
    return runs


def generate_supplier_dashboard(log_dir: str, db_path: str = None,
                                progress_cb=None) -> str:
    """
    Erzeugt logs/supplier_dashboard.html: aktuelle Artikelzahl je Lieferant
    (online/offline) + Verlauf über die letzten Läufe. Gibt den Pfad zurück
    (leer wenn weder Lauf-Historie noch eine lesbare DB vorliegen).

    Der Verlauf braucht Lauf-Reports mit "supplier_stats" (erst seit
    Einführung dieses Felds vorhanden). Solange die noch fehlen – z.B.
    direkt nach dem Update, ohne dass schon ein neuer Lauf gelaufen ist –
    wird der aktuelle Stand stattdessen live aus db_path gelesen (Tabelle
    dann sofort korrekt, nur der Verlauf startet erst ab jetzt).
    """
    p = progress_cb or (lambda m, **kw: None)
    runs = _load_runs(log_dir)

    if not runs and db_path:
        try:
            from lib.article_db import open_db, stats as article_stats
            con = open_db(db_path)
            try:
                live_stats = article_stats(con)
            finally:
                con.close()
            if live_stats.get("by_supplier_detail"):
                now_iso = datetime.now().isoformat()
                runs = [{"start": now_iso, "ende": now_iso,
                        "supplier_stats": live_stats}]
                p("Lieferanten-Dashboard: noch keine Lauf-Historie – "
                  "zeige aktuellen Datenbankstand (Verlauf startet ab jetzt).",
                  tag="dim")
        except Exception as e:
            log.debug(f"Live-DB-Fallback fehlgeschlagen: {e}")

    if not runs:
        p("Lieferanten-Dashboard: weder Lauf-Historie noch lesbare "
          "Artikel-DB gefunden – bitte zuerst einen DB-Import durchführen.",
          tag="warn")
        return ""

    latest = runs[-1]
    detail = latest["supplier_stats"]["by_supplier_detail"]
    suppliers = sorted(detail.keys())

    # Verlauf je Lieferant über die vorliegenden Läufe (fehlende Werte = 0,
    # falls ein Lieferant in einem Lauf noch nicht vorkam).
    labels = [r.get("ende", r.get("start", "?"))[:16].replace("T", " ") for r in runs]
    series = {
        sup: [r["supplier_stats"]["by_supplier_detail"].get(sup, {}).get("total", 0)
              for r in runs]
        for sup in suppliers
    }

    labels_js = json.dumps(labels)
    datasets_js = json.dumps([
        {
            "label": sup,
            "data": series[sup],
            "borderColor": _LINE_COLORS[i % len(_LINE_COLORS)],
            "backgroundColor": _LINE_COLORS[i % len(_LINE_COLORS)] + "33",
            "tension": 0.3,
            "pointRadius": 2,
            "fill": False,
        }
        for i, sup in enumerate(suppliers)
    ])

    total_current = sum(d["total"] for d in detail.values())
    total_online  = sum(d["online"] for d in detail.values())
    total_offline = sum(d["offline"] for d in detail.values())

    rows = "".join(f"""
    <tr>
      <td class="name">{sup}</td>
      <td class="num">{_de(detail[sup]['total'])}</td>
      <td class="num online">{_de(detail[sup]['online'])}</td>
      <td class="num offline">{_de(detail[sup]['offline'])}</td>
    </tr>""" for sup in suppliers)

    stamp = latest.get("ende") or latest.get("start")
    try:
        stamp_fmt = datetime.fromisoformat(stamp).strftime("%d.%m.%Y %H:%M")
    except Exception:
        stamp_fmt = stamp or "?"

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BMEcat Lieferanten-Statistik</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<style>
  body {{ background:#1a1a2e; color:#eaeaea; font-family:'Segoe UI',sans-serif;
          padding:24px; }}
  h1 {{ color:#e94560; margin-bottom:4px; }}
  .meta {{ color:#888; font-size:12px; margin-bottom:24px; }}
  .kpis {{ display:flex; gap:16px; margin-bottom:24px; flex-wrap:wrap; }}
  .kpi {{ background:#16213e; border:1px solid #2a2a4a; border-radius:8px;
           padding:14px 20px; flex:1; min-width:140px; }}
  .kpi .v {{ font-size:28px; font-weight:700; color:#e94560; }}
  .kpi .l {{ font-size:11px; color:#888; text-transform:uppercase; }}
  .card {{ background:#16213e; border-radius:8px; padding:20px;
            border:1px solid #2a2a4a; margin-bottom:24px; }}
  .card h2 {{ font-size:13px; color:#888; text-transform:uppercase;
               letter-spacing:.06em; margin-bottom:16px; }}
  canvas {{ max-height:320px; }}
  table {{ width:100%; border-collapse:collapse; }}
  th {{ text-align:left; padding:8px 12px; color:#888; font-size:11px;
        text-transform:uppercase; border-bottom:1px solid #2a2a4a; }}
  td {{ padding:8px 12px; border-bottom:1px solid #2a2a4a; }}
  td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  td.online {{ color:#4caf50; }}
  td.offline {{ color:#f44336; }}
</style>
</head>
<body>
<h1>📦 Lieferanten-Statistik</h1>
<div class="meta">BMEcat Download-Tool · Stand {stamp_fmt}
  · {len(runs)} Läufe im Verlauf</div>

<div class="kpis">
  <div class="kpi"><div class="v">{_de(total_current)}</div><div class="l">Artikel gesamt</div></div>
  <div class="kpi"><div class="v">{_de(total_online)}</div><div class="l">Online</div></div>
  <div class="kpi"><div class="v">{_de(total_offline)}</div><div class="l">Offline</div></div>
  <div class="kpi"><div class="v">{len(suppliers)}</div><div class="l">Lieferanten</div></div>
</div>

<div class="card">
  <h2>Aktuell (letzter Lauf)</h2>
  <table>
    <thead><tr><th>Lieferant</th><th class="num">Gesamt</th>
      <th class="num">Online</th><th class="num">Offline</th></tr></thead>
    <tbody>{rows}
    </tbody>
  </table>
</div>

<div class="card">
  <h2>Verlauf: Artikelzahl je Lieferant</h2>
  <canvas id="trend"></canvas>
</div>

<script>
new Chart(document.getElementById('trend'), {{
  type: 'line',
  data: {{ labels: {labels_js}, datasets: {datasets_js} }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ labels: {{ color: '#eaeaea' }} }} }},
    scales: {{
      x: {{ ticks: {{ color:'#888', maxRotation:45 }}, grid: {{ color:'#2a2a4a' }} }},
      y: {{ ticks: {{ color:'#888' }}, grid: {{ color:'#2a2a4a' }}, beginAtZero: true }}
    }}
  }}
}});
</script>
</body>
</html>"""

    out_path = os.path.join(log_dir, "supplier_dashboard.html")
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        p(f"Lieferanten-Dashboard aktualisiert: {os.path.basename(out_path)}",
          tag="ok")
    except Exception as e:
        log.error(f"Lieferanten-Dashboard konnte nicht geschrieben werden: {e}")
        return ""

    return out_path


def run_supplier_dashboard_task(progress_cb=None, file_progress_cb=None):
    """Task-Wrapper: Lieferanten-Dashboard manuell (neu) erzeugen."""
    from config import DIRS, DB_PATH
    return generate_supplier_dashboard(DIRS.get("logs", "."), db_path=DB_PATH,
                                       progress_cb=progress_cb)
