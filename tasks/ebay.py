# tasks/ebay.py – eBay File-Exchange Tasks
#
# Eingabedateien werden manuell in in_BME abgelegt (kein FTP-Download – die
# SKU-Liste kommt vom Vertrieb, der Revise-Report von eBay selbst):
#   ebay_sku_liste.csv        – Task A: SKU-Liste → Neuanlage / Revise / Beenden
#   ebay_revise_download.csv  – Task B: eBay-eigener Report → Bestand/Preis sync
#   ebay_kategorie_lernen.csv – Task C: alte, ausgefüllte Draft-Datei →
#                                ebay_category_map.csv lernen
#   eBay-edit-price-quantity-template.csv (BASE_DIR) – Task D: aktive Angebote
#                                + BestandBueroring.csv (in_BME) → Revise/End
#
# Ausgabedateien landen in export_dir/ebay/ mit sprechendem Namen + Timestamp
# (z.B. eBay_Neuanlage_20260427_143012.csv) – Task D landet stattdessen direkt
# in BASE_DIR/eBay/ (eBay-Revise_<Datum>.csv / eBay-end_<Datum>.csv).

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


def _fetch_edi_bestand(edi_path: str, dest_path: str, p) -> bool:
    """
    Kopiert BestandBueroring.csv vom EDI-Netzlaufwerk nach dest_path (in_BME).
    Nicht erreichbar/fehlend → Warnung, vorhandene in_BME-Datei bleibt.
    """
    import shutil
    import datetime as _dt
    try:
        if not os.path.isfile(edi_path):
            p(f"eBay-Bestand-Revise: EDI-Datei nicht gefunden: {edi_path} "
              f"– verwende vorhandene BestandBueroring_EDI.csv, falls vorhanden.", tag="warn")
            return False
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        tmp = dest_path + ".tmp"
        shutil.copy2(edi_path, tmp)
        from lib.utils import safe_replace
        safe_replace(tmp, dest_path, p=p)
        stamp = _dt.datetime.fromtimestamp(os.path.getmtime(dest_path))
        size  = f"{os.path.getsize(dest_path):,}".replace(",", ".")
        p(f"eBay-Bestand-Revise: EDI-Bestand übernommen → BestandBueroring_EDI.csv "
          f"(Stand {stamp:%d.%m.%Y %H:%M}, {size} Bytes).", tag="ok")
        return True
    except Exception as e:
        p(f"eBay-Bestand-Revise: EDI-Datei konnte nicht kopiert werden ({e}) "
          f"– verwende vorhandene BestandBueroring_EDI.csv, falls vorhanden.", tag="warn")
        return False


def run_bestand_revise(progress_cb=None, file_progress_cb=None) -> dict:
    """
    Task D: aktive eBay-Angebote (eBay-edit-price-quantity-template.csv,
    BASE_DIR) + BestandBueroring_EDI.csv (vom EDI-Laufwerk DIRS.brg_bestand_edi
    nach in_BME kopiert) + BestandBueroring.csv (per FTP, in_BME); beide
    zusammengeführt, EDI hat Vorrang →
    eBay-Revise_<Datum>.csv (Bestand aktualisiert) + eBay-end_<Datum>.csv
    (Bestand 0) in BASE_DIR/eBay.
    """
    p = progress_cb or (lambda m, **kw: None)
    from lib.ebay_export import build_revise_end_from_bestand

    template_path = os.path.join(BASE_DIR, "eBay-edit-price-quantity-template.csv")
    bestand_ftp   = os.path.join(DIRS["in_bme"], "BestandBueroring.csv")
    bestand_edi   = os.path.join(DIRS["in_bme"], "BestandBueroring_EDI.csv")

    # Zweiten Bestand vom EDI-Netzlaufwerk holen (DIRS.brg_bestand_edi,
    # Reiter "Pfade"). Wird als eigene Datei BestandBueroring_EDI.csv nach
    # in_BME kopiert – die per FTP geladene BestandBueroring.csv bleibt
    # unangetastet. Beide werden zusammengeführt, EDI hat Vorrang.
    edi_src = (DIRS.get("brg_bestand_edi") or "").strip()
    if edi_src:
        _fetch_edi_bestand(edi_src, bestand_edi, p)
    else:
        p("eBay-Bestand-Revise: kein EDI-Pfad konfiguriert (Pfade → brg_bestand_edi) "
          "– nur FTP-Bestand.", tag="dim")

    if not os.path.exists(template_path):
        p(f"eBay-Bestand-Revise: Datei nicht gefunden: {template_path}", tag="warn")
        p("Bitte die aktuellen aktiven Angebote als "
          "'eBay-edit-price-quantity-template.csv' nach BASE_DIR legen.", tag="warn")
        return {}

    # Reihenfolge = Priorität: EDI vor FTP
    bestand_paths = [pth for pth in (bestand_edi, bestand_ftp) if os.path.exists(pth)]
    if not bestand_paths:
        p(f"eBay-Bestand-Revise: keine Bestandsdatei gefunden ({bestand_ftp}, "
          f"{bestand_edi})", tag="warn")
        p("Bitte den Büroring-Download ausführen (lädt BestandBueroring.csv nach "
          "in_BME) und/oder den EDI-Pfad prüfen.", tag="warn")
        return {}
    if len(bestand_paths) < 2:
        p(f"eBay-Bestand-Revise: nur eine Bestandsdatei vorhanden: "
          f"{os.path.basename(bestand_paths[0])}", tag="warn")

    out_dir = os.path.join(BASE_DIR, "eBay")
    return build_revise_end_from_bestand(template_path, bestand_paths, out_dir,
                                         progress_cb=p)
