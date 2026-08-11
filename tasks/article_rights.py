# tasks/article_rights.py – Artikelrechte-Export-Task (Allago + OfficeXL)
#
# Erzeugt je Katalog eine SKU-Liste für Allago und eine für OfficeXL und lädt
# sie anschließend in den jeweiligen Produkt-Rechte-Ordner hoch.
# Ersetzt die alte SQL-Query/Velocity-Template-Lösung. Läuft unabhängig vom
# VENDOSYS-Export, braucht nur einen abgeschlossenen DB-Import.

import logging
import os
from typing import Callable

import config as _cfg
from config import CONNECTIONS
from lib.article_rights_export import export_article_rights
from lib.ftp_client import make_client

log = logging.getLogger(__name__)


def run(progress_cb: Callable = None, file_progress_cb: Callable = None) -> dict:
    p  = progress_cb      or (lambda m, **kw: None)
    fp = file_progress_cb or None

    out_dir = _cfg.DIRS.get("article_rights", _cfg.EXPORT_DIR)

    p("┌─ Artikelrechte-Export (Allago + OfficeXL) ────────────────────")
    p(f"│  Ausgabe: {out_dir}")
    p("│  Upload → /sites/products/catalog_products/ (Allago + OfficeXL) ")
    p("└────────────────────────────────────────────────────────────")

    result = export_article_rights(
        db_path=_cfg.DB_PATH,
        base_dir=_cfg.BASE_DIR,
        out_dir=out_dir,
        progress_cb=p,
    )

    # Upload: gleicher FTP-Zugang wie die Bilder-Uploads, nur anderer Zielordner.
    for target, conn_key in (("Allago", "allago_images"), ("Oxl", "officexl_images")):
        local_dir = os.path.join(out_dir, target)
        if not os.path.isdir(local_dir):
            continue
        cfg = CONNECTIONS[conn_key]
        p(f"Artikelrechte: Upload → {target} ...")
        cl = make_client(cfg)
        cl.connect()
        try:
            cl.upload(os.path.join(local_dir, "*.csv"), cfg["remote_path_products"],
                      progress_cb=p, file_progress_cb=fp)
        finally:
            cl.disconnect()

    return result
