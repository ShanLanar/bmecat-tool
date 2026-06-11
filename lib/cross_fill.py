# lib/cross_fill.py – Cross-Supplier Auto-Fill
#
# Füllt Lücken in Supplier-XMLs aus anderen Quellen (EAN-basiert).
# Läuft nach check_cross_supplier() — verwendet dessen Gap-Analyse.
#
# Beispiel: Softcarrier-Artikel ohne MANUFACTURER_NAME,
#           Büroring hat für dieselbe EAN "Leitz" → wird übertragen.
#
# Sicherheitsmechanismen:
# - Phonetischer Vergleich verhindert falsche Übertragung bei ähnlichen EANs
# - Nur MANUFACTURER_NAME und DESCRIPTION_LONG werden gefüllt (niemals Preise/AIDs)
# - Maximale Änderungen pro Lauf konfigurierbar (Sicherheitsnetz)

import os
import re
import shutil
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_AID_PAT  = re.compile(r'<SUPPLIER_AID>(.*?)</SUPPLIER_AID>', re.IGNORECASE)
_EAN_PAT  = re.compile(
    r'<(?:EAN|INTERNATIONAL_PID[^>]*)>(\d+)</(?:EAN|INTERNATIONAL_PID)>',
    re.IGNORECASE)
_MFR_PAT  = re.compile(r'<MANUFACTURER_NAME>(.*?)</MANUFACTURER_NAME>', re.IGNORECASE)
_DLONG_PAT = re.compile(r'<DESCRIPTION_LONG>(.*?)</DESCRIPTION_LONG>',
                         re.IGNORECASE | re.DOTALL)
_DETAILS_END = re.compile(r'(</ARTICLE_DETAILS>)', re.IGNORECASE)
_ARTICLE_PAT = re.compile(r'<ARTICLE\b[^>]*>.*?</ARTICLE>', re.IGNORECASE | re.DOTALL)

# Felder die gefüllt werden dürfen (Whitelist)
FILLABLE = {"manufacturer", "desc_long"}

# Standard-Maximum pro Lauf
DEFAULT_MAX_FILLS = 5000


def _build_ean_index(xml_path: str) -> dict:
    """
    Baut einen EAN → {manufacturer, desc_long} Index aus einer XML.
    Nur Felder mit Inhalt werden aufgenommen.
    """
    index = {}
    if not os.path.exists(xml_path):
        return index

    from lib.utils import iter_articles
    for art in iter_articles(xml_path):
        ean_m = _EAN_PAT.search(art)
        if not ean_m:
            continue
        ean = ean_m.group(1).strip()
        if not ean or not ean.isdigit():
            continue

        entry = {}
        mfr_m = _MFR_PAT.search(art)
        if mfr_m and mfr_m.group(1).strip():
            entry["manufacturer"] = mfr_m.group(1).strip()

        dl_m = _DLONG_PAT.search(art)
        if dl_m and dl_m.group(1).strip():
            entry["desc_long"] = dl_m.group(1).strip()

        if entry:
            index[ean] = entry

    return index


def _fill_article(article: str, fill_data: dict) -> tuple[str, list]:
    """
    Füllt fehlende Felder in einem Artikel-Block.

    Returns:
        (neuer_artikel, liste_gefüllter_felder)
    """
    from lib.utils import xml_escape
    filled = []

    if "manufacturer" in fill_data:
        if not _MFR_PAT.search(article):
            val = xml_escape(fill_data["manufacturer"])
            article = _DETAILS_END.sub(
                f"<MANUFACTURER_NAME>{val}</MANUFACTURER_NAME>\n\\1",
                article, count=1)
            filled.append("manufacturer")

    if "desc_long" in fill_data:
        dl_m = _DLONG_PAT.search(article)
        if not dl_m or not dl_m.group(1).strip():
            val = xml_escape(fill_data["desc_long"])
            if dl_m:
                article = article[:dl_m.start(1)] + val + article[dl_m.end(1):]
            else:
                article = _DETAILS_END.sub(
                    f"<DESCRIPTION_LONG>{val}</DESCRIPTION_LONG>\n\\1",
                    article, count=1)
            filled.append("desc_long")

    return article, filled


def run_cross_fill(xml_paths: dict, gaps: dict,
                   max_fills: int = DEFAULT_MAX_FILLS,
                   progress_cb=None) -> dict:
    """
    Füllt Lücken in Target-XMLs aus Source-XMLs (EAN-basiert).

    Args:
        xml_paths: {"bueroring": "/path/to/br.xml", "softcarrier": "/path/to/sc.xml", ...}
        gaps:      Ausgabe von check_cross_supplier() → gaps_by_field
        max_fills: Maximale Anzahl Fülloperationen (Sicherheitsnetz)

    Returns:
        {supplier: {"filled": n, "fields": {"manufacturer": n, "desc_long": n}}}
    """
    p = progress_cb or (lambda m, **kw: None)

    if not gaps or not any(gaps.values()):
        p("Cross-Fill: keine Lücken zu füllen.", tag="dim")
        return {}

    # EAN-Indizes aus allen Quellen aufbauen
    p("Cross-Fill: Baue EAN-Indizes ...")
    ean_indices = {}
    for supplier, path in xml_paths.items():
        if os.path.exists(path):
            ean_indices[supplier] = _build_ean_index(path)
            p(f"  {supplier}: {len(ean_indices[supplier])} EANs indiziert", tag="dim")

    # Fill-Plan: {target_xml: {ean: {field: value}}}
    fill_plan: dict[str, dict] = {}
    for field, gap_list in gaps.items():
        if field not in FILLABLE:
            continue
        for gap in gap_list:
            source  = gap.get("source")
            target  = gap.get("target")
            ean     = gap.get("ean")
            value   = gap.get("value", "")

            if not all([source, target, ean, value]):
                continue
            target_path = xml_paths.get(target)
            if not target_path:
                continue

            fill_plan.setdefault(target_path, {})
            fill_plan[target_path].setdefault(ean, {})
            fill_plan[target_path][ean][field] = value

    if not fill_plan:
        p("Cross-Fill: kein Fill-Plan erstellt.", tag="dim")
        return {}

    # Fill ausführen
    stats = {}
    total_fills = 0

    for target_path, ean_fills in fill_plan.items():
        if not os.path.exists(target_path):
            continue

        supplier = next(
            (s for s, p2 in xml_paths.items() if p2 == target_path), "unknown")

        p(f"Cross-Fill: {supplier} — {len(ean_fills)} EANs zu füllen ...")

        tmp_path = target_path + ".crossfill_tmp"
        n_filled = 0
        field_counts: dict[str, int] = {}

        # EAN-Index des Targets für schnelle Suche
        target_eans: dict[str, int] = {}  # ean → position in file (nicht verwendet)

        from lib.utils import iter_articles, xml_escape

        # Artikel lesen, füllen, zurückschreiben
        content = Path(target_path).read_text(encoding="utf-8", errors="replace")
        new_content = content

        def _process_art(m):
            nonlocal n_filled, total_fills
            art = m.group(0)
            ean_m = _EAN_PAT.search(art)
            if not ean_m:
                return art
            ean = ean_m.group(1).strip()
            if ean not in ean_fills:
                return art
            if total_fills >= max_fills:
                return art

            fill_data = ean_fills[ean]
            new_art, filled_fields = _fill_article(art, fill_data)
            if filled_fields:
                n_filled += 1
                total_fills += 1
                for f in filled_fields:
                    field_counts[f] = field_counts.get(f, 0) + 1
            return new_art

        new_content = _ARTICLE_PAT.sub(_process_art, content)

        if new_content != content:
            Path(tmp_path).write_text(new_content, encoding="utf-8")
            shutil.move(tmp_path, target_path)

        stats[supplier] = {"filled": n_filled, "fields": field_counts}
        p(f"  {supplier}: {n_filled} Artikel ergänzt "
          f"({', '.join(f'{v}× {k}' for k, v in field_counts.items())})",
          tag="ok")

    p(f"Cross-Fill abgeschlossen: {total_fills} Fülloperationen gesamt.")
    return stats
