# tasks/article_rights.py – Artikelrechte-Export-Task (Allago + OfficeXL)
#
# Erzeugt je Katalog eine SKU-Liste für Allago und eine für OfficeXL.
# Ersetzt die alte SQL-Query/Velocity-Template-Lösung. Läuft unabhängig vom
# VENDOSYS-Export, braucht nur einen abgeschlossenen DB-Import.

import logging
from typing import Callable

import config as _cfg
from lib.article_rights_export import export_article_rights

log = logging.getLogger(__name__)


def run(progress_cb: Callable = None, file_progress_cb: Callable = None) -> dict:
    p = progress_cb or (lambda m, **kw: None)

    out_dir = _cfg.DIRS.get("article_rights", _cfg.EXPORT_DIR)

    p("┌─ Artikelrechte-Export (Allago + OfficeXL) ────────────────────")
    p(f"│  Ausgabe: {out_dir}")
    p("└────────────────────────────────────────────────────────────")

    result = export_article_rights(
        db_path=_cfg.DB_PATH,
        base_dir=_cfg.BASE_DIR,
        out_dir=out_dir,
        progress_cb=p,
    )
    return result
