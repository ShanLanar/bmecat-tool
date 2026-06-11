# lib/dashboard.py – Cross-Filling-Dashboard (HTML)
#
# Liest Sanity-Reports (logs/sanity_*.json) und erzeugt
# logs/cross_filling_dashboard.html — aufrufbar im Browser.

import os
import json
import glob
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

FIELD_LABELS = {
    "manufacturer": "Hersteller",
    "desc_long":    "Langbeschreibung",
    "has_image":    "Bild",
}


def _load_reports(log_dir: str, max_reports: int = 30) -> list:
    """Liest die letzten N Sanity-Reports."""
    pattern = os.path.join(log_dir, "sanity_*.json")
    files = sorted(glob.glob(pattern), reverse=True)[:max_reports]
    reports = []
    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                reports.append(json.load(fh))
        except Exception:
            pass
    return reports


def _coverage_row(catalog: str, data: dict) -> str:
    def bar(pct, color):
        pct = min(100, max(0, pct))
        cls = "bar-good" if pct >= 90 else "bar-warn" if pct >= 70 else "bar-bad"
        return (f'<div class="bar-wrap" title="{pct:.1f}%">'
                f'<div class="{cls}" style="width:{pct:.0f}%"></div>'
                f'<span class="bar-label">{pct:.0f}%</span></div>')

    total = data.get("total", 0)
    return f"""
    <tr>
      <td class="cat-name">{catalog}</td>
      <td class="num">{total:,}</td>
      <td>{bar(data.get("ean_coverage", 0), "ean")}</td>
      <td>{bar(data.get("mfr_coverage", 0), "mfr")}</td>
      <td>{bar(data.get("dlong_coverage", 0), "dlong")}</td>
      <td>{bar(data.get("image_coverage", 0), "img")}</td>
      <td class="{'warn' if data.get('duplicate_aids', 0) > 0 else 'ok'}">
          {data.get("duplicate_aids", 0)}
      </td>
      <td class="{'warn' if data.get('bad_ean_format', 0) > 0 else 'ok'}">
          {data.get("bad_ean_format", 0)}
      </td>
    </tr>"""


def _fill_matrix_html(fill_matrix: dict, image_gaps: int) -> str:
    if not fill_matrix and not image_gaps:
        return '<p class="dim">Keine geteilten EANs gefunden.</p>'

    rows = []
    all_directions = sorted(fill_matrix.items(),
                            key=lambda x: -sum(x[1].values()))
    for direction, fields in all_directions:
        src, tgt = direction.split(" → ", 1) if " → " in direction else (direction, "?")
        total = sum(fields.values())
        field_pills = " ".join(
            f'<span class="pill">{FIELD_LABELS.get(f, f)}: {n}</span>'
            for f, n in sorted(fields.items(), key=lambda x: -x[1])
        )
        rows.append(f"""
        <tr>
          <td class="cat-name src">{src}</td>
          <td class="arrow">→</td>
          <td class="cat-name tgt">{tgt}</td>
          <td class="num total">{total:,}</td>
          <td>{field_pills}</td>
        </tr>""")

    if image_gaps:
        rows.append(f"""
        <tr>
          <td colspan="3" class="cat-name">Bilder-Lücken (cross-supplier)</td>
          <td class="num total">{image_gaps:,}</td>
          <td><span class="pill">Bild</span></td>
        </tr>""")

    return f"""
    <table class="fill-matrix">
      <thead>
        <tr><th>Quelle</th><th></th><th>Ziel</th><th>Felder</th><th>Details</th></tr>
      </thead>
      <tbody>{''.join(rows)}</tbody>
    </table>"""


def _gap_examples_html(top_gaps: dict) -> str:
    sections = []
    for field, gaps in top_gaps.items():
        if not gaps:
            continue
        label = FIELD_LABELS.get(field, field)
        rows = []
        for g in gaps[:15]:
            val = g.get("value", "")[:70] + ("…" if len(g.get("value", "")) > 70 else "")
            rows.append(f"""
            <tr>
              <td class="ean">{g.get("ean", "")}</td>
              <td class="src-aid">{g.get("source_aid", "")}
                  <span class="sup-tag">{g.get("source", "")}</span></td>
              <td class="value">{val}</td>
              <td class="tgt-aid">{g.get("target_aid", "")}
                  <span class="sup-tag tgt">{g.get("target", "")}</span></td>
            </tr>""")
        sections.append(f"""
        <div class="gap-section">
          <h3>{label} <span class="count">({len(gaps)} Artikel)</span></h3>
          <table class="gaps-table">
            <thead>
              <tr>
                <th>EAN</th>
                <th>Quelle (hat Daten)</th>
                <th>Verfügbarer Wert</th>
                <th>Ziel (fehlt)</th>
              </tr>
            </thead>
            <tbody>{''.join(rows)}</tbody>
          </table>
          {'<p class="more">… und weitere ' + str(len(gaps) - 15) + ' Artikel</p>'
           if len(gaps) > 15 else ''}
        </div>""")
    return "".join(sections) or '<p class="dim">Keine Lücken gefunden.</p>'


def _trend_sparkline(reports: list, catalog: str, field: str) -> str:
    """Einfache Text-Sparkline für Trend."""
    vals = []
    for r in reversed(reports[:10]):
        cats = r.get("kataloge", {})
        if catalog in cats:
            vals.append(cats[catalog].get(field, 0))
    if not vals:
        return ""
    bars = "▁▂▃▄▅▆▇█"
    lo, hi = min(vals), max(vals)
    rng = hi - lo or 1
    spark = "".join(bars[min(7, int((v - lo) / rng * 7))] for v in vals)
    return f'<span class="sparkline" title="{vals[-1]:.0f}% aktuell">{spark}</span>'


def generate_dashboard(log_dir: str, progress_cb=None) -> str:
    """
    Erzeugt logs/cross_filling_dashboard.html aus den Sanity-Reports.
    Gibt den Pfad zur erzeugten Datei zurück.
    """
    p = progress_cb or (lambda m, **kw: None)
    reports = _load_reports(log_dir)

    if not reports:
        p("Dashboard: keine Sanity-Reports gefunden – bitte zuerst Sanity-Check ausführen.",
          tag="warn")
        return ""

    latest = reports[0]
    zeitpunkt = latest.get("zeitpunkt", "?")
    try:
        zeitpunkt = datetime.fromisoformat(zeitpunkt).strftime("%d.%m.%Y %H:%M")
    except Exception:
        pass

    kataloge = latest.get("kataloge", {})
    cross    = latest.get("cross_supplier", {})
    top_gaps = cross.get("top_gaps", {})
    fill_matrix = cross.get("fill_matrix", {})
    image_gaps  = cross.get("image_gaps", 0)
    shared_eans = cross.get("shared_eans", 0)
    total_eans  = cross.get("total_unique_eans", 0)

    # Gesamt-Füll-Potenzial
    total_fillable = sum(cross.get("fillable_gaps", {}).values()) + image_gaps

    coverage_rows = "".join(_coverage_row(cat, data)
                            for cat, data in kataloge.items())

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BMEcat Cross-Filling Dashboard</title>
<style>
  :root {{
    --bg:       #1a1a2e;
    --surface:  #16213e;
    --surface2: #0f3460;
    --accent:   #e94560;
    --accent2:  #533483;
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

  header {{ background: var(--surface2); padding: 20px 32px;
            border-bottom: 2px solid var(--accent); }}
  header h1 {{ font-size: 22px; font-weight: 600; }}
  header .meta {{ color: var(--dim); font-size: 12px; margin-top: 4px; }}

  .kpi-row {{ display: flex; gap: 16px; padding: 20px 32px;
              flex-wrap: wrap; }}
  .kpi {{ background: var(--surface); border: 1px solid var(--border);
          border-radius: 8px; padding: 16px 20px; flex: 1; min-width: 160px; }}
  .kpi .val {{ font-size: 32px; font-weight: 700; color: var(--accent); }}
  .kpi .lbl {{ font-size: 11px; color: var(--dim); text-transform: uppercase;
               letter-spacing: .06em; margin-top: 4px; }}

  section {{ padding: 0 32px 28px; }}
  section h2 {{ font-size: 16px; font-weight: 600; padding: 20px 0 12px;
                border-bottom: 1px solid var(--border); margin-bottom: 16px; }}

  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ text-align: left; padding: 8px 10px; color: var(--dim);
        font-weight: 600; font-size: 11px; text-transform: uppercase;
        letter-spacing: .05em; border-bottom: 1px solid var(--border); }}
  td {{ padding: 8px 10px; border-bottom: 1px solid var(--border); vertical-align: middle; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: rgba(255,255,255,.03); }}

  .cat-name {{ font-weight: 500; white-space: nowrap; }}
  .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .ok  {{ color: var(--good); }}
  .warn {{ color: var(--warn); }}
  .dim {{ color: var(--dim); }}

  .bar-wrap {{ display: flex; align-items: center; gap: 8px;
               min-width: 140px; }}
  .bar-wrap > div {{ height: 10px; border-radius: 5px; min-width: 2px; }}
  .bar-good {{ background: var(--good); }}
  .bar-warn {{ background: var(--warn); }}
  .bar-bad  {{ background: var(--bad); }}
  .bar-label {{ font-size: 11px; color: var(--dim); flex-shrink: 0; }}

  .fill-matrix td {{ padding: 10px; }}
  .arrow {{ color: var(--accent); font-size: 16px; text-align: center; }}
  .src {{ color: #7ec8e3; }}
  .tgt {{ color: #ffb347; }}
  .total {{ font-size: 18px; font-weight: 700; color: var(--accent); }}
  .pill {{ display: inline-block; background: var(--surface2);
           border: 1px solid var(--accent2); border-radius: 12px;
           padding: 2px 8px; font-size: 11px; margin: 2px; white-space: nowrap; }}
  .sup-tag {{ font-size: 10px; color: var(--dim); margin-left: 6px; }}
  .sup-tag.tgt {{ color: var(--warn); }}

  .gap-section {{ margin-bottom: 28px; }}
  .gap-section h3 {{ font-size: 14px; font-weight: 600; margin-bottom: 10px; }}
  .gap-section h3 .count {{ font-weight: 400; color: var(--dim); }}
  .gaps-table .ean {{ font-family: monospace; color: var(--dim); }}
  .gaps-table .value {{ color: #a8d8a8; max-width: 320px;
                        overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .gaps-table .src-aid {{ color: #7ec8e3; }}
  .gaps-table .tgt-aid {{ color: var(--warn); }}
  .more {{ color: var(--dim); font-size: 12px; margin-top: 6px; }}

  .sparkline {{ font-family: monospace; letter-spacing: 1px; color: var(--dim); }}
  footer {{ padding: 20px 32px; color: var(--dim); font-size: 11px; border-top: 1px solid var(--border); }}
</style>
</head>
<body>

<header>
  <h1>⇄ Cross-Filling Dashboard</h1>
  <div class="meta">BMEcat Download-Tool · Stand: {zeitpunkt} · {len(reports)} Report(s) geladen</div>
</header>

<div class="kpi-row">
  <div class="kpi">
    <div class="val">{total_eans:,}</div>
    <div class="lbl">Eindeutige EANs gesamt</div>
  </div>
  <div class="kpi">
    <div class="val">{shared_eans:,}</div>
    <div class="lbl">EANs bei mehreren Lieferanten</div>
  </div>
  <div class="kpi">
    <div class="val" style="color: {'var(--warn)' if total_fillable > 0 else 'var(--good)'}">
        {total_fillable:,}
    </div>
    <div class="lbl">Füllbare Felder (gesamt)</div>
  </div>
  <div class="kpi">
    <div class="val">{len(kataloge)}</div>
    <div class="lbl">Lieferanten-Kataloge</div>
  </div>
</div>

<section>
  <h2>Datenvollständigkeit je Lieferant</h2>
  <table>
    <thead>
      <tr>
        <th>Lieferant</th>
        <th style="text-align:right">Artikel</th>
        <th>EAN-Abdeckung</th>
        <th>Hersteller</th>
        <th>Langbeschreibung</th>
        <th>Bilder</th>
        <th>Duplikate</th>
        <th>Schlechte EAN</th>
      </tr>
    </thead>
    <tbody>
      {coverage_rows}
    </tbody>
  </table>
</section>

<section>
  <h2>Füll-Potenzial: wer kann wem helfen</h2>
  <p class="dim" style="margin-bottom:12px">
    Artikel deren EAN bei mehreren Lieferanten vorkommt, aber ein Feld nur
    bei einem ausgefüllt ist.
  </p>
  {_fill_matrix_html(fill_matrix, image_gaps)}
</section>

<section>
  <h2>Konkrete Lücken (Beispiele)</h2>
  {_gap_examples_html(top_gaps)}
</section>

<footer>
  Generiert von BMEcat Download-Tool v1.1.0 · {datetime.now().strftime("%d.%m.%Y %H:%M")}
</footer>

</body>
</html>"""

    out_path = os.path.join(log_dir, "cross_filling_dashboard.html")
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    p(f"Dashboard: {os.path.basename(out_path)}", tag="ok")
    return out_path


def run_dashboard_task(progress_cb=None, file_progress_cb=None):
    """Task-Einstiegspunkt: Dashboard aus vorhandenen Sanity-Reports generieren."""
    from config import DIRS
    p = progress_cb or (lambda m, **kw: None)
    log_dir = DIRS["logs"]

    out_path = generate_dashboard(log_dir, progress_cb=p)
    if out_path:
        p(f"Dashboard gespeichert: {out_path}", tag="ok")
        p(f"Im Browser öffnen: file:///{out_path.replace(chr(92), '/')}", tag="dim")
    else:
        p("Kein Dashboard erzeugt. Sanity-Check zuerst ausführen.", tag="warn")


def generate_trend_report(log_dir: str, progress_cb=None) -> str:
    """
    Erzeugt logs/trend_dashboard.html aus allen lauf_*.json Dateien.
    Zeigt Artikelzahlen, Fehlerrate und Laufzeiten über Zeit.
    """
    import glob
    p = progress_cb or (lambda m, **kw: None)

    pattern = os.path.join(log_dir, "lauf_*.json")
    files = sorted(glob.glob(pattern))[-30:]  # letzte 30 Läufe

    if not files:
        p("Trend-Report: keine lauf_*.json Dateien gefunden.", tag="warn")
        return ""

    runs = []
    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                runs.append(data)
        except Exception:
            pass

    if not runs:
        return ""

    # Daten für Charts aufbereiten
    labels   = [r.get("start", "?")[:10] for r in runs]
    durations = [round(r.get("dauer_s", 0) / 60, 1) for r in runs]
    errors   = [r.get("tasks_fehler", 0) for r in runs]
    ok_tasks = [r.get("tasks_ok", 0) for r in runs]

    labels_js    = json.dumps(labels)
    durations_js = json.dumps(durations)
    errors_js    = json.dumps(errors)
    ok_js        = json.dumps(ok_tasks)

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<title>BMEcat Lauf-Trends</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<style>
  body {{ background:#1a1a2e; color:#eaeaea; font-family:'Segoe UI',sans-serif;
          padding:24px; }}
  h1 {{ color:#e94560; margin-bottom:4px; }}
  .meta {{ color:#888; font-size:12px; margin-bottom:24px; }}
  .charts {{ display:grid; grid-template-columns:1fr 1fr; gap:24px; }}
  .card {{ background:#16213e; border-radius:8px; padding:20px;
            border:1px solid #2a2a4a; }}
  .card h2 {{ font-size:13px; color:#888; text-transform:uppercase;
               letter-spacing:.06em; margin-bottom:16px; }}
  canvas {{ max-height:220px; }}
  .kpis {{ display:flex; gap:16px; margin-bottom:24px; flex-wrap:wrap; }}
  .kpi {{ background:#16213e; border:1px solid #2a2a4a; border-radius:8px;
           padding:14px 20px; flex:1; min-width:140px; }}
  .kpi .v {{ font-size:28px; font-weight:700; color:#e94560; }}
  .kpi .l {{ font-size:11px; color:#888; text-transform:uppercase; }}
</style>
</head>
<body>
<h1>⏱ Lauf-Trends</h1>
<div class="meta">BMEcat Download-Tool · {len(runs)} Läufe · generiert {datetime.now().strftime("%d.%m.%Y %H:%M")}</div>

<div class="kpis">
  <div class="kpi">
    <div class="v">{len(runs)}</div>
    <div class="l">Läufe gesamt</div>
  </div>
  <div class="kpi">
    <div class="v">{sum(errors)}</div>
    <div class="l">Fehler gesamt</div>
  </div>
  <div class="kpi">
    <div class="v">{round(sum(durations)/len(durations), 1)} min</div>
    <div class="l">Ø Laufzeit</div>
  </div>
  <div class="kpi">
    <div class="v">{max(durations):.0f} min</div>
    <div class="l">Längster Lauf</div>
  </div>
</div>

<div class="charts">
  <div class="card">
    <h2>Laufzeit (Minuten)</h2>
    <canvas id="dur"></canvas>
  </div>
  <div class="card">
    <h2>Fehler pro Lauf</h2>
    <canvas id="err"></canvas>
  </div>
  <div class="card">
    <h2>Erfolgreiche Tasks</h2>
    <canvas id="ok"></canvas>
  </div>
</div>

<script>
const labels = {labels_js};
const cfg = (data, color, label) => ({{
  type: 'line',
  data: {{ labels, datasets: [{{
    label, data, borderColor: color, backgroundColor: color + '33',
    fill: true, tension: 0.3, pointRadius: 3,
  }}] }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ color:'#888', maxRotation:45 }}, grid: {{ color:'#2a2a4a' }} }},
      y: {{ ticks: {{ color:'#888' }}, grid: {{ color:'#2a2a4a' }}, beginAtZero: true }}
    }}
  }}
}});
new Chart(document.getElementById('dur'), cfg({durations_js}, '#e94560', 'Minuten'));
new Chart(document.getElementById('err'), cfg({errors_js},   '#ff9800', 'Fehler'));
new Chart(document.getElementById('ok'),  cfg({ok_js},       '#4caf50', 'Tasks OK'));
</script>
</body>
</html>"""

    out = os.path.join(log_dir, "trend_dashboard.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    p(f"Trend-Report: {os.path.basename(out)} ({len(runs)} Läufe)", tag="ok")
    return out


def run_trend_task(progress_cb=None, file_progress_cb=None):
    """Task-Einstiegspunkt: Trend-Report generieren."""
    from config import DIRS
    p = progress_cb or (lambda m, **kw: None)
    out = generate_trend_report(DIRS["logs"], progress_cb=p)
    if out:
        p(f"Trend-Report öffnen: file:///{out.replace(chr(92), '/')}", tag="dim")
