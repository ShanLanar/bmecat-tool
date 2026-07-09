# tasks/pim_export.py – PIM-Artikelexport-Task (Softcarrier)
#
# Erzeugt PIM-Artikelexport_aktiv.txt / _inaktiv.txt aus der Artikel-DB.
# Ersetzt die alte PIM-SQL-Abfrage. Läuft unabhängig von VENDOSYS-Export,
# braucht nur einen abgeschlossenen DB-Import.

import logging
from typing import Callable

import config as _cfg
from lib.pim_export import export_pim

log = logging.getLogger(__name__)


def run(progress_cb: Callable = None, file_progress_cb: Callable = None) -> dict:
    p = progress_cb or (lambda m, **kw: None)

    out_dir = _cfg.DIRS.get("pim_export", _cfg.EXPORT_DIR)

    p("┌─ PIM-Artikelexport (Softcarrier) ─────────────────────────────")
    p(f"│  Ausgabe: {out_dir}")
    p("└────────────────────────────────────────────────────────────")

    result = export_pim(
        db_path=_cfg.DB_PATH,
        base_dir=_cfg.BASE_DIR,
        out_dir=out_dir,
        product_id_prefix="SOC",
        progress_cb=p,
    )
    return result
