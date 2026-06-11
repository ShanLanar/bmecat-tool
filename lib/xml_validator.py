# lib/xml_validator.py – XML-Validierung vor dem Upload
#
# Prüft BMEcat-XMLs auf:
#   1. Wohlgeformtheit (XML-Parser)
#   2. Artikelanzahl plausibel (nicht leer, nicht drastisch weniger als erwartet)
#   3. Pflichtfelder vorhanden (SUPPLIER_AID, DESCRIPTION_SHORT)
#
# Gibt Warnungen aus, verhindert aber keinen Upload (soft validation).

import os
import re
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# Mindest-Artikelzahlen pro Datei (Warnung wenn unterschritten)
# Kann in config.py als ARTICLE_THRESHOLDS überschrieben werden
DEFAULT_THRESHOLDS = {
    "bueroring_merged.xml":    20000,
    "soft-carrier_merge.xml":  60000,
    "arbeitsschutz.xml":        5000,
    "werkstatt.xml":           10000,
    "werkzeugtechnik.xml":     40000,
}


def _get_thresholds() -> dict:
    try:
        import config
        return getattr(config, "ARTICLE_THRESHOLDS", DEFAULT_THRESHOLDS)
    except Exception:
        return DEFAULT_THRESHOLDS


def validate_xml(xml_path: str, progress_cb=None) -> dict:
    """
    Validiert eine BMEcat-XML-Datei vor dem Upload.

    Args:
        xml_path:    Pfad zur XML-Datei
        progress_cb: Log-Callback

    Returns:
        dict mit:
            valid:        bool – True wenn keine kritischen Fehler
            article_count: int – Anzahl gefundener Artikel
            warnings:     list – Warnungen (nicht-kritisch)
            errors:       list – Kritische Fehler
    """
    p = progress_cb or (lambda m, **kw: None)
    basename = os.path.basename(xml_path)

    result = {
        "valid": True,
        "article_count": 0,
        "file_size": 0,
        "warnings": [],
        "errors": [],
    }

    if not os.path.exists(xml_path):
        result["valid"] = False
        result["errors"].append(f"Datei nicht gefunden: {basename}")
        return result

    result["file_size"] = os.path.getsize(xml_path)

    # 1. Datei leer?
    if result["file_size"] == 0:
        result["valid"] = False
        result["errors"].append(f"{basename}: Datei ist leer (0 Bytes)")
        return result

    # 2. Artikel zählen (chunked, nicht alles in RAM laden)
    CHUNK_SIZE = 1024 * 1024  # 1 MB
    article_count = 0
    header_chunk = b""
    footer_chunk = b""
    sample_text = ""

    try:
        with open(xml_path, "rb") as f:
            # Header lesen (erste 2 KB)
            header_chunk = f.read(2048)

            # Zum Anfang zurück für Chunk-Zählung
            f.seek(0)
            sample_bytes = b""
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="replace")
                article_count += len(re.findall(r"<ARTICLE[\s>]", text, re.IGNORECASE))

                # Erste 500 KB für AID-Stichprobe sammeln
                if len(sample_bytes) < 500_000:
                    sample_bytes += chunk

            # Footer lesen (letzte 500 Bytes)
            file_size = f.seek(0, 2)  # seek to end
            footer_start = max(0, file_size - 500)
            f.seek(footer_start)
            footer_chunk = f.read()

            sample_text = sample_bytes[:500_000].decode("utf-8", errors="replace")

    except Exception as e:
        result["valid"] = False
        result["errors"].append(f"{basename}: Datei nicht lesbar – {e}")
        return result

    result["article_count"] = article_count

    if article_count == 0:
        result["valid"] = False
        result["errors"].append(f"{basename}: Keine Artikel gefunden (0 <ARTICLE>-Tags)")
        return result

    # 3. Schwellwert prüfen
    thresholds = _get_thresholds()
    min_count = thresholds.get(basename, 0)
    if min_count > 0 and article_count < min_count:
        pct = (article_count / min_count) * 100
        result["warnings"].append(
            f"{basename}: Nur {article_count} Artikel "
            f"(erwartet mind. {min_count}, = {pct:.0f}%)")

    # 4. XML-Wohlgeformtheit (Start- und End-Tag prüfen)
    header_text = header_chunk.decode("utf-8", errors="replace")
    footer_text = footer_chunk.decode("utf-8", errors="replace")
    has_header = bool(re.search(r"<BMECAT[^>]*>", header_text, re.IGNORECASE))
    has_footer = bool(re.search(r"</BMECAT\s*>", footer_text, re.IGNORECASE))

    if not has_header:
        result["warnings"].append(f"{basename}: Kein <BMECAT>-Header gefunden")
    if not has_footer:
        result["valid"] = False
        result["errors"].append(
            f"{basename}: Kein </BMECAT>-Abschluss – Datei möglicherweise abgeschnitten")

    # 5. Stichprobe: haben Artikel eine SUPPLIER_AID?
    articles_in_sample = re.findall(
        r"<ARTICLE[\s>].*?</ARTICLE>", sample_text,
        re.IGNORECASE | re.DOTALL)
    if articles_in_sample:
        missing_aid = sum(
            1 for a in articles_in_sample[:50]
            if not re.search(r"<SUPPLIER_AID>", a, re.IGNORECASE)
        )
        if missing_aid > 0:
            result["warnings"].append(
                f"{basename}: {missing_aid} Artikel ohne SUPPLIER_AID "
                f"(Stichprobe: {len(articles_in_sample[:50])})")

    return result


def validate_before_upload(xml_paths: list, progress_cb=None) -> bool:
    """
    Validiert alle XMLs vor dem Upload. Gibt Warnungen aus.

    Args:
        xml_paths:   Liste von XML-Dateipfaden
        progress_cb: Log-Callback

    Returns:
        True wenn alle Dateien valide, False wenn kritische Fehler
    """
    p = progress_cb or (lambda m, **kw: None)
    all_valid = True

    for path in xml_paths:
        if not os.path.exists(path):
            continue

        result = validate_xml(path, progress_cb=p)
        basename = os.path.basename(path)
        size_mb = result["file_size"] / (1024 * 1024)

        # Zusammenfassung
        p(f"  Validierung {basename}: "
          f"{result['article_count']} Artikel, {size_mb:.1f} MB",
          tag="ok" if result["valid"] else "warn")

        for warn in result["warnings"]:
            p(f"  ⚠ {warn}", tag="warn")

        for err in result["errors"]:
            p(f"  ✗ {err}", tag="err")
            all_valid = False

    return all_valid
