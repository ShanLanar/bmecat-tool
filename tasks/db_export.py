# tasks/db_export.py – Manueller VENDOSYS-Export-Task
#
# Wird händisch angestoßen. Erwartet date_from und date_to als Parameter.
# Kann aus main.py über den Task-Scheduler oder direkt aufgerufen werden.
#
# Beispiel-Direktaufruf:
#   python -c "from tasks.db_export import run; run('2026-06-01', '2026-06-30')"

import logging
from datetime import datetime, timezone
from typing import Callable

import config as _cfg
from lib.db_exporter import export_changed
from lib.article_db import open_db, stats as db_stats

log = logging.getLogger(__name__)


def run(date_from: str = None, date_to: str = None,
        supplier_name: str = None,
        article_ids: list = None,
        progress_cb: Callable = None,
        file_progress_cb: Callable = None) -> dict:
    """
    Exportiert geänderte Artikel als VENDOSYS_CAT XML-Dateien.

    date_from / date_to: ISO-Datum oder Datetime, z.B. '2026-06-01'
                         Default: letzten 7 Tage bis jetzt
    supplier_name:       Optionaler Filter auf einen Lieferanten
    """
    p = progress_cb or (lambda m, **kw: None)

    now = datetime.now(timezone.utc)
    if not date_to:
        date_to = now.isoformat(timespec='seconds')
    if not date_from:
        from datetime import timedelta
        date_from = (now - timedelta(days=7)).isoformat(timespec='seconds')

    p(f"DB-Export: Zeitraum {date_from[:10]} – {date_to[:10]}")
    if supplier_name:
        p(f"DB-Export: Lieferant-Filter: {supplier_name}")

    # DB-Stats vor Export
    try:
        con  = open_db(_cfg.DB_PATH)
        info = db_stats(con)
        p(f"Datenbank: {info['total']} Artikel gesamt")
        for sup, n in info['by_supplier'].items():
            p(f"  {sup}: {n}", tag='dim')
    except Exception as e:
        p(f"DB-Stats Fehler: {e}", tag='warn')

    result = export_changed(
        db_path=_cfg.DB_PATH,
        base_dir=_cfg.BASE_DIR,
        export_dir=_cfg.EXPORT_DIR,
        date_from=date_from,
        date_to=date_to,
        supplier_name=supplier_name,
        article_ids=article_ids,
        progress_cb=p,
    )
    return result


def run_today(progress_cb: Callable = None, **kw):
    """Exportiert alle heute geänderten Artikel."""
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    return run(date_from=f"{today}T00:00:00+00:00",
               date_to=f"{today}T23:59:59+00:00",
               progress_cb=progress_cb)
