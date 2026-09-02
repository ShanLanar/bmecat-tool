# tasks/pim_export.py – PIM-Artikelexport-Task (Softcarrier)
#
# Erzeugt PIM-Artikelexport_aktiv.txt / _inaktiv.txt aus der Artikel-DB.
# Ersetzt die alte PIM-SQL-Abfrage. Läuft unabhängig von VENDOSYS-Export,
# braucht nur einen abgeschlossenen DB-Import.
#
# PIM-Artikelexport_aktiv.txt wird zusätzlich als soc_pim_export.csv (alter,
# von nachgelagerten Systemen erwarteter Dateiname) auf zwei Netzwerk-
# freigaben kopiert (überschreibt dort jeweils die letzte Version; die
# lokale Kopie in pim_export/ bleibt unangetastet erhalten).

import os
import shutil
import logging
from typing import Callable

import config as _cfg
from lib.pim_export import export_pim

log = logging.getLogger(__name__)

_SHARE_FILENAME = "soc_pim_export.csv"


def _copy_to_share(src: str, share_dir: str, label: str, p):
    dst = os.path.join(share_dir, _SHARE_FILENAME)
    try:
        shutil.copy2(src, dst)
        p(f"  ✓ {label}: {dst}", tag="ok")
    except Exception as e:
        p(f"  ⚠ {label} nicht erreichbar/kopierbar ({share_dir}): {e}", tag="warn")


def run(progress_cb: Callable = None, file_progress_cb: Callable = None) -> dict:
    p = progress_cb or (lambda m, **kw: None)

    out_dir = _cfg.DIRS.get("pim_export", _cfg.EXPORT_DIR)

    p("┌─ PIM-Artikelexport (Softcarrier) ─────────────────────────────")
    p(f"│  Ausgabe: {out_dir}")
    p(f"│  ↑ aktiv.txt → {_SHARE_FILENAME} auf zwei Netzwerkfreigaben")
    p("└────────────────────────────────────────────────────────────")

    result = export_pim(
        db_path=_cfg.DB_PATH,
        base_dir=_cfg.BASE_DIR,
        out_dir=out_dir,
        product_id_prefix="SOC",
        progress_cb=p,
    )

    active_path = os.path.join(out_dir, "PIM-Artikelexport_aktiv.txt")
    if os.path.exists(active_path):
        p(f"Kopiere {os.path.basename(active_path)} auf Netzwerkfreigaben ...")
        _copy_to_share(active_path, _cfg.DIRS["pim_export_mgmt_share"],
                       "mgmt-Freigabe (S.Berlin)", p)
        _copy_to_share(active_path, _cfg.DIRS["pim_export_obs_share"],
                       "OBS-Freigabe (780102150)", p)
    else:
        p(f"⚠ {active_path} nicht gefunden – Netzwerkfreigaben übersprungen.",
          tag="warn")

    return result
