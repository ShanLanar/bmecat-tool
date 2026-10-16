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
    Kopiert BestandBueroring.csv vom EDI-Netzlaufwerk nach in_BME.
    Nicht erreichbar/fehlend → Warnung, vorhandene in_BME-Datei bleibt.
    """
    import shutil
    import datetime as _dt
    try:
        if not os.path.isfile(edi_path):
            p(f"eBay-Bestand-Revise: EDI-Datei nicht gefunden: {edi_path} "
              f"– verwende vorhandene Datei in in_BME.", tag="warn")
            return False
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        tmp = dest_path + ".tmp"
        shutil.copy2(edi_path, tmp)
        from lib.utils import safe_replace
        safe_replace(tmp, dest_path, p=p)
        stamp = _dt.datetime.fromtimestamp(os.path.getmtime(dest_path))
        size  = f"{os.path.getsize(dest_path):,}".replace(",", ".")
        p(f"eBay-Bestand-Revise: BestandBueroring.csv vom EDI-Laufwerk übernommen "
          f"(Stand {stamp:%d.%m.%Y %H:%M}, {size} Bytes).", tag="ok")
        return True
    except Exception as e:
        p(f"eBay-Bestand-Revise: EDI-Datei konnte nicht kopiert werden ({e}) "
          f"– verwende vorhandene Datei in in_BME.", tag="warn")
        return False


def run_bestand_revise(progress_cb=None, file_progress_cb=None) -> dict:
    """
    Task D: aktive eBay-Angebote (eBay-edit-price-quantity-template.csv,
    BASE_DIR) + BestandBueroring.csv (vom EDI-Laufwerk DIRS.brg_bestand_edi
    nach in_BME kopiert; Fallback: per Büroring-Download geladene Datei) →
    eBay-Revise_<Datum>.csv (Bestand aktualisiert) + eBay-end_<Datum>.csv
    (Bestand 0) in BASE_DIR/eBay.
    """
    p = progress_cb or (lambda m, **kw: None)
    from lib.ebay_export import build_revise_end_from_bestand

    template_path = os.path.join(BASE_DIR, "eBay-edit-price-quantity-template.csv")
    bestand_path  = os.path.join(DIRS["in_bme"], "BestandBueroring.csv")

    # Bestand vom EDI-Netzlaufwerk holen (DIRS.brg_bestand_edi, Reiter "Pfade").
    # Kopiert nach in_BME und ersetzt dort die per FTP geladene Datei.
    edi_path = (DIRS.get("brg_bestand_edi") or "").strip()
    if edi_path:
        _fetch_edi_bestand(edi_path, bestand_path, p)
    else:
        p("eBay-Bestand-Revise: kein EDI-Pfad konfiguriert (Pfade → brg_bestand_edi) "
          "– verwende FTP-Datei in in_BME.", tag="dim")

    if not os.path.exists(template_path):
        p(f"eBay-Bestand-Revise: Datei nicht gefunden: {template_path}", tag="warn")
        p("Bitte die aktuellen aktiven Angebote als "
          "'eBay-edit-price-quantity-template.csv' nach BASE_DIR legen.", tag="warn")
        return {}
    if not os.path.exists(bestand_path):
        p(f"eBay-Bestand-Revise: Datei nicht gefunden: {bestand_path}", tag="warn")
        p("Bitte zuerst den Büroring-Download ausführen (lädt BestandBueroring.csv "
          "nach in_BME).", tag="warn")
        return {}

    out_dir = os.path.join(BASE_DIR, "eBay")
    return build_revise_end_from_bestand(template_path, bestand_path, out_dir,
                                         progress_cb=p)
