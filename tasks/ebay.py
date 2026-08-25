# tasks/ebay.py – eBay File-Exchange Tasks
#
# Eingabedateien werden manuell in in_BME abgelegt (kein FTP-Download – die
# SKU-Liste kommt vom Vertrieb, der Revise-Report von eBay selbst):
#   ebay_sku_liste.csv        – Task A: SKU-Liste → Neuanlage / Revise / Beenden
#   ebay_revise_download.csv  – Task B: eBay-eigener Report → Bestand/Preis sync
#   ebay_kategorie_lernen.csv – Task C: alte, ausgefüllte Draft-Datei →
#                                ebay_category_map.csv lernen
#
# Ausgabedateien landen in export_dir/ebay/ mit sprechendem Namen + Timestamp
# (z.B. eBay_Neuanlage_20260427_143012.csv).

import os
from config import DB_PATH, DIRS, BASE_DIR, EXPORT_DIR

_IMAGE_BASE = "https://www.officexl.de/whitelabels/officexl/images/thumbnails/zoom"


def _out_dir() -> str:
    d = os.path.join(EXPORT_DIR, "ebay")
    os.makedirs(d, exist_ok=True)
    return d


def run_sku_liste(progress_cb=None, file_progress_cb=None) -> dict:
    """Task A: manuelle SKU-Liste (Vertrieb) → Neuanlage/Revise/Beenden."""
    p = progress_cb or (lambda m, **kw: None)
    from lib.ebay_export import process_sku_list

    in_path = os.path.join(DIRS["in_bme"], "ebay_sku_liste.csv")
    if not os.path.exists(in_path):
        p(f"eBay-SKU-Liste: Datei nicht gefunden: {in_path}", tag="warn")
        p("Bitte SKU-Liste (eine SKU pro Zeile) als 'ebay_sku_liste.csv' "
          "nach in_BME legen.", tag="warn")
        return {}

    return process_sku_list(in_path, DB_PATH, BASE_DIR, _out_dir(), _IMAGE_BASE,
                            progress_cb=p)


def run_revise_sync(progress_cb=None, file_progress_cb=None) -> dict:
    """Task B: von eBay heruntergeladener Revise-Report → Bestand/Preis sync."""
    p = progress_cb or (lambda m, **kw: None)
    from lib.ebay_export import sync_active_listings

    in_path = os.path.join(DIRS["in_bme"], "ebay_revise_download.csv")
    if not os.path.exists(in_path):
        p(f"eBay-Revise-Report: Datei nicht gefunden: {in_path}", tag="warn")
        p("Bitte den von eBay heruntergeladenen Report als "
          "'ebay_revise_download.csv' nach in_BME legen.", tag="warn")
        return {}

    return sync_active_listings(in_path, DB_PATH, _out_dir(), progress_cb=p)


def run_learn_category_map(progress_cb=None, file_progress_cb=None) -> dict:
    """Task C: alte, bereits ausgefüllte Draft-Datei → ebay_category_map.csv lernen."""
    p = progress_cb or (lambda m, **kw: None)
    from lib.ebay_export import learn_category_map

    in_path = os.path.join(DIRS["in_bme"], "ebay_kategorie_lernen.csv")
    if not os.path.exists(in_path):
        p(f"eBay-Kategorie-Lernen: Datei nicht gefunden: {in_path}", tag="warn")
        p("Bitte eine alte, bereits mit Category ID ausgefüllte Draft-Datei "
          "als 'ebay_kategorie_lernen.csv' nach in_BME legen.", tag="warn")
        return {}

    return learn_category_map(in_path, DB_PATH, BASE_DIR, progress_cb=p)
