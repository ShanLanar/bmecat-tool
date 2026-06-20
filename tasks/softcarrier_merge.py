# tasks/softcarrier_merge.py
#
# Liest soft-carrier.xml und reichert sie an:
#
#   1. DATA.CSV (Feld 118-137): TABxBEZ/TABxINH-Paare als <FEATURE>-Blöcke
#      in einen neuen ARTICLE_FEATURES-Block (udf_SOC-0.1) pro Artikel.
#      Verknüpfung über ARTNR (Feld 2) = SUPPLIER_AID im BMEcat.
#
#   2. HERSTINFO.CSV: GPSR-Herstellerdaten pro Marke.
#      Verknüpfung über MARKE (Spalte 1) = <MANUFACTURER_NAME> im BMEcat.
#      Eingefügte Features (im udf_SOC-Block):
#        GPSR Hersteller Name, GPSR Hersteller Straße, GPSR Hersteller PLZ,
#        GPSR Hersteller Ort, GPSR Hersteller Land, GPSR Hersteller Website
#
#   Ausgabe: softcarrier_merge.xml im gleichen Verzeichnis wie soft-carrier.xml

import os
import re
import csv
import logging
from pathlib import Path

log = logging.getLogger(__name__)

DATA_SEP      = "|"
DATA_ARTNR    = 1
DATA_MARKE    = 42
DATA_TAB_START= 117
DATA_TAB_END  = 137

HERSTINFO_SEP = "|"

_AID_PAT      = re.compile(r'(?is)<supplier_aid>(.*?)</supplier_aid>')
_MFR_PAT      = re.compile(r'(?is)<manufacturer_name>(.*?)</manufacturer_name>')
_ARTICLE_PAT  = re.compile(r'(?is)(<article[\s>].*?</article>)')
_ART_END_PAT  = re.compile(r'(?i)</article>')
_SRC_PAT      = re.compile(r'(?i)(<source>)([^<]+)(</source>)')


from lib.utils import detect_encoding  # zentralisiert in lib/utils.py


def read_text_auto(path: str) -> tuple[str, str]:
    """
    Liest eine Textdatei mit automatischer Encoding-Erkennung.
    Gibt (text, encoding) zurück.
    """
    enc  = detect_encoding(path)
    text = Path(path).read_text(encoding=enc, errors="replace")
    log.debug(f"read_text_auto: {os.path.basename(path)} als {enc}")
    return text, enc


def _load_herstinfo(csv_path: str) -> dict:
    """
    Liest HERSTINFO.CSV mit automatischer Encoding-Erkennung.
    { marke_lower → {Name, Zusatz, Strasse, PLZ, Ort, Land, Website} }
    """
    result = {}
    if not os.path.exists(csv_path):
        return result

    enc = detect_encoding(csv_path)
    log.debug(f"HERSTINFO.CSV encoding: {enc}")

    with open(csv_path, encoding=enc, errors="replace") as f:
        for line in f:
            parts = [p.strip() for p in line.rstrip("\r\n").split(HERSTINFO_SEP)]
            if len(parts) < 8:
                continue
            marke = parts[0].strip()
            if not marke:
                continue
            result[marke.lower()] = {
                "GPSR Hersteller Name":    parts[1],
                "GPSR Hersteller Zusatz":  parts[2],
                "GPSR Hersteller Straße":  parts[3],
                "GPSR Hersteller Land":    parts[4],
                "GPSR Hersteller PLZ":     parts[5],
                "GPSR Hersteller Ort":     parts[6],
                "GPSR Hersteller Website": parts[7],
            }
    return result


def _load_data_csv(csv_path: str) -> dict:
    """
    Liest DATA.CSV mit automatischer Encoding-Erkennung.
    { artnr_lower → [(bez, inh), ...] }
    """
    result = {}
    if not os.path.exists(csv_path):
        return result

    enc = detect_encoding(csv_path)
    log.debug(f"DATA.CSV encoding: {enc}")

    with open(csv_path, encoding=enc, errors="replace") as f:
        for line in f:
            parts = line.rstrip("\r\n").split(DATA_SEP)
            if len(parts) <= DATA_ARTNR:
                continue
            artnr = parts[DATA_ARTNR].strip().lstrip("0")
            if not artnr:
                continue

            tabs = []
            for i in range(DATA_TAB_START, min(DATA_TAB_END + 1, len(parts)), 2):
                bez = parts[i].strip() if i < len(parts) else ""
                inh = parts[i+1].strip() if i+1 < len(parts) else ""
                if bez and inh and bez != "0" and inh != "0":
                    tabs.append((bez, inh))

            if tabs:
                result[artnr.lower()] = tabs

    return result


def _build_udf_block(features: list, indent: str = "      ") -> str:
    """
    Erzeugt einen ARTICLE_FEATURES-Block mit REFERENCE_FEATURE_SYSTEM_NAME=udf_SOC-0.1.
    features: [(fname, fvalue), ...]
    """
    lines = [
        f"{indent}<ARTICLE_FEATURES>",
        f"{indent}  <REFERENCE_FEATURE_SYSTEM_NAME>udf_SOC-0.1</REFERENCE_FEATURE_SYSTEM_NAME>",
    ]
    for fname, fvalue in features:
        # XML-Sonderzeichen escapen (zentral aus lib/utils)
        from lib.utils import xml_escape
        fvalue_e = xml_escape(fvalue)
        fname_e  = xml_escape(fname)
        lines.append(
            f"{indent}  <FEATURE>\n"
            f"{indent}    <FNAME>{fname_e}</FNAME>\n"
            f"{indent}    <FVALUE>{fvalue_e}</FVALUE>\n"
            f"{indent}  </FEATURE>"
        )
    lines.append(f"{indent}</ARTICLE_FEATURES>")
    return "\n".join(lines)


def _apply_image_patch(article: str, aid: str, patch_map: dict) -> str:
    """
    Ersetzt <SOURCE>39672.jpg</SOURCE> durch <SOURCE>39672_302.jpg</SOURCE>
    (Ordner_Dateiname) wenn ein Eintrag in der Patch-Map vorhanden ist.
    """
    if not patch_map or aid not in patch_map:
        return article
    folder, img = patch_map[aid]
    new_val = f"{folder}_{img}"
    def _replace(m):
        return f"{m.group(1)}{new_val}{m.group(3)}"
    return _SRC_PAT.sub(_replace, article, count=1)


def _enrich_article(article: str,
                    data_map: dict,
                    herstinfo: dict) -> str:
    """
    Reichert einen einzelnen <article>-Block an:
    - Sucht AID + MANUFACTURER_NAME
    - Fügt udf_SOC-Block mit TAB-Features + GPSR-Daten ein
    """
    aid_m = _AID_PAT.search(article)
    if not aid_m:
        return article
    aid = aid_m.group(1).strip().lstrip("0").lower()

    mfr_m = _MFR_PAT.search(article)
    mfr   = mfr_m.group(1).strip().lower() if mfr_m else ""

    features = []

    # TAB-Features aus DATA.CSV
    for bez, inh in data_map.get(aid, []):
        features.append((bez, inh))

    # GPSR-Daten aus HERSTINFO.CSV
    gpsr = herstinfo.get(mfr, {})
    for fname, fvalue in gpsr.items():
        if fvalue and fname != "GPSR Hersteller Zusatz":
            features.append((fname, fvalue))

    if not features:
        return article

    # Einrückung erkennen (aus dem </article>-Tag)
    end_m = _ART_END_PAT.search(article)
    indent = "      "
    if end_m:
        pos  = end_m.start()
        line_start = article.rfind("\n", 0, pos)
        if line_start >= 0:
            indent = article[line_start+1:pos]

    udf_block = _build_udf_block(features, indent)

    # Vor </article> einfügen
    insert_pos = article.lower().rfind("</article>")
    return article[:insert_pos] + udf_block + "\n" + article[insert_pos:]


def merge(xml_path: str, data_csv: str, herstinfo_csv: str,
          out_path: str = None, progress_cb=None,
          patch_map: dict = None) -> dict:
    """
    Hauptfunktion:
      xml_path      – soft-carrier.xml
      data_csv      – softcarrier_data.csv (entpackt aus data.zip)
      herstinfo_csv – softcarrier_HERSTINFO.CSV
      out_path      – Zieldatei (default: soft-carrier_merge.xml)

    Gibt Statistik-Dict zurück.
    """
    p = progress_cb or (lambda m, **kw: None)

    if out_path is None:
        out_path = xml_path.replace("soft-carrier.xml", "soft-carrier_merge.xml")
        if out_path == xml_path:
            out_path = xml_path + "_merge.xml"

    p(f"Softcarrier Merge: lade HERSTINFO.CSV ...")
    herstinfo = _load_herstinfo(herstinfo_csv)
    p(f"  {len(herstinfo)} Marken geladen  [encoding: {detect_encoding(herstinfo_csv) if os.path.exists(herstinfo_csv) else 'n/a'}]")

    p(f"Softcarrier Merge: lade DATA.CSV ...")
    data_map  = _load_data_csv(data_csv)
    p(f"  {len(data_map)} Artikel mit TAB-Features  [encoding: {detect_encoding(data_csv) if os.path.exists(data_csv) else 'n/a'}]")

    p(f"Softcarrier Merge: lese {os.path.basename(xml_path)} ...")
    xml_enc = detect_encoding(xml_path)
    p(f"  Quelldatei-Encoding erkannt: {xml_enc}")
    content = Path(xml_path).read_text(encoding=xml_enc, errors="replace")

    # XML-Deklaration auf UTF-8 korrigieren – egal was der Lieferant gesetzt hat
    content = re.sub(
        r'<\?xml([^?]*?)encoding=["\'][^"\']*["\']([^?]*?)\?>',
        r'<?xml\1encoding="UTF-8"\2?>',
        content, count=1, flags=re.IGNORECASE)
    # Falls keine Deklaration vorhanden: eine einfügen
    if not content.lstrip().startswith("<?xml"):
        content = '<?xml version="1.0" encoding="UTF-8"?>\n' + content

    img_patched   = 0
    enriched      = 0
    tab_enriched  = 0
    gpsr_enriched = 0

    def _process(m):
        nonlocal enriched, tab_enriched, gpsr_enriched, img_patched
        article = m.group(1)

        aid_m = _AID_PAT.search(article)
        aid   = aid_m.group(1).strip().lstrip("0").lower() if aid_m else ""
        mfr_m = _MFR_PAT.search(article)
        mfr   = mfr_m.group(1).strip().lower() if mfr_m else ""

        has_tab  = bool(data_map.get(aid))
        has_gpsr = bool(herstinfo.get(mfr))

        if has_tab:  tab_enriched  += 1
        if has_gpsr: gpsr_enriched += 1
        if has_tab or has_gpsr:
            enriched += 1
            article = _enrich_article(article, data_map, herstinfo)

        # Bild-Patch: mehrdeutige MIME_SOURCE durch artikelspezifische ersetzen
        if patch_map:
            aid_raw = aid_m.group(1).strip() if aid_m else ""
            patched = _apply_image_patch(article, aid_raw, patch_map)
            if patched is not article:
                img_patched += 1
                article = patched

        return article

    new_content = _ARTICLE_PAT.sub(_process, content)

    # MIME-Sources mit SOC_-Präfix versehen damit sie mit den Bildnamen übereinstimmen
    _MIME_SOURCE_PAT = re.compile(r'(?i)(<source>)([^<]+)(</source>)')
    def _prefix_source(m):
        val = m.group(2).strip()
        if val.upper().startswith("SOC"):
            return m.group()
        return f"{m.group(1)}SOC{val}{m.group(3)}"
    new_content = _MIME_SOURCE_PAT.sub(_prefix_source, new_content)

    p(f"Softcarrier Merge: schreibe {os.path.basename(out_path)} ...")
    Path(out_path).write_text(new_content, encoding="utf-8")

    p(f"  Artikel angereichert: {enriched}", tag="ok")
    p(f"    davon TAB-Features:  {tab_enriched}")
    p(f"    davon GPSR-Daten:    {gpsr_enriched}")
    if patch_map:
        p(f"  Bild-Patch angewendet: {img_patched}", tag="ok" if img_patched else "dim")

    return {
        "enriched":     enriched,
        "tab_enriched": tab_enriched,
        "gpsr_enriched":gpsr_enriched,
        "img_patched":  img_patched,
        "out_path":     out_path,
    }


def run(progress_cb=None, file_progress_cb=None):
    """Task-Einstiegspunkt für main.py."""
    import config as _cfg
    from config import DIRS
    from lib.sc_image_patch import load_patch_map, PATCH_FILENAME

    p      = progress_cb or (lambda m, **kw: None)
    in_bme = DIRS["in_bme"]

    xml_path      = os.path.join(in_bme, "soft-carrier.xml")
    data_csv      = os.path.join(in_bme, "softcarrier_data.csv")
    herstinfo_csv = os.path.join(in_bme, "softcarrier_HERSTINFO.CSV")
    out_path      = os.path.join(in_bme, "soft-carrier_merge.xml")

    if not os.path.exists(xml_path):
        raise FileNotFoundError(f"soft-carrier.xml nicht gefunden: {xml_path}")

    # Bild-Patch-Map laden (optional – wird nur angewendet wenn CSV vorhanden)
    patch_csv = os.path.join(_cfg.BASE_DIR, PATCH_FILENAME)
    patch_map = load_patch_map(patch_csv)
    if patch_map:
        p(f"  Bild-Patch geladen: {len(patch_map):,} Einträge aus {PATCH_FILENAME}", tag="ok")
    else:
        p(f"  Kein Bild-Patch ({PATCH_FILENAME} fehlt) – MIME_SOURCE unverändert", tag="dim")

    merge(xml_path, data_csv, herstinfo_csv, out_path,
          progress_cb=p, patch_map=patch_map)

    # FNAME-Transforms + Dedup (Transforms vor Dedup)
    from lib.fname_transforms import apply_fname_transforms
    from tasks.others import dedup_xmls
    import config as _cfg
    if os.path.exists(out_path):
        apply_fname_transforms(out_path, _cfg.BASE_DIR, progress_cb=p)
        dedup_xmls([out_path], progress_cb=p, file_progress_cb=file_progress_cb)

    from tasks.db_import import run_for_supplier
    run_for_supplier('softcarrier', progress_cb=p)

    p("Softcarrier Merge abgeschlossen.", tag="ok")
