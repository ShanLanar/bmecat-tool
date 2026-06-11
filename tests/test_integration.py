# tests/test_integration.py – Integrationstests für Merge-Output
#
# Prüfen nicht einzelne Funktionen, sondern ob das Ergebnis der gesamten
# Pipeline plausibel ist: Artikelzahl, EAN-Abdeckung, keine Duplikate.
#
# Laufen auf echten XMLs wenn vorhanden, andernfalls als Skip markiert.
# Aufruf: python -m pytest tests/test_integration.py -v

import os
import re
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def _xml_path(filename: str) -> str:
    """Pfad zur XML im in_bme-Verzeichnis, falls konfiguriert."""
    try:
        import config
        return os.path.join(config.DIRS.get("in_bme", ""), filename)
    except Exception:
        return ""


def _skip_if_missing(path: str):
    if not path or not os.path.exists(path):
        pytest.skip(f"Datei nicht vorhanden: {path}")


def _stream_count(xml_path: str, pattern: re.Pattern) -> int:
    count = 0
    with open(xml_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            count += len(pattern.findall(line))
    return count


def _stream_collect(xml_path: str, pattern: re.Pattern) -> list:
    values = []
    with open(xml_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            values.extend(pattern.findall(line))
    return values


_ART_PAT  = re.compile(r'<ARTICLE[\s>]', re.IGNORECASE)
_AID_PAT  = re.compile(r'<SUPPLIER_AID>(.*?)</SUPPLIER_AID>', re.IGNORECASE)
_EAN_PAT  = re.compile(
    r'<(?:EAN|INTERNATIONAL_PID[^>]*)>(\d+)</(?:EAN|INTERNATIONAL_PID)>',
    re.IGNORECASE)
_FNAME_PAT = re.compile(r'<FNAME>(.*?)</FNAME>', re.IGNORECASE)


# ── Schwellwerte (müssen mit ARTICLE_THRESHOLDS in config.py übereinstimmen) ──

THRESHOLDS = {
    "bueroring_merged.xml":    {"min_articles": 20_000, "min_ean_pct": 85},
    "soft-carrier_merge.xml":  {"min_articles": 60_000, "min_ean_pct": 90},
    "arbeitsschutz.xml":       {"min_articles":  5_000, "min_ean_pct": 75},
    "werkstatt.xml":           {"min_articles": 10_000, "min_ean_pct": 75},
    "werkzeugtechnik.xml":     {"min_articles": 40_000, "min_ean_pct": 75},
}


# ── Büroring ──────────────────────────────────────────────────────────────────

class TestBueroringMerge:

    @pytest.fixture
    def xml(self):
        path = _xml_path("bueroring_merged.xml")
        _skip_if_missing(path)
        return path

    def test_minimum_article_count(self, xml):
        count = _stream_count(xml, _ART_PAT)
        threshold = THRESHOLDS["bueroring_merged.xml"]["min_articles"]
        assert count >= threshold, \
            f"Büroring: nur {count} Artikel (min. {threshold})"

    def test_no_duplicate_aids(self, xml):
        aids = _stream_collect(xml, _AID_PAT)
        dupes = [a for a, n in __import__("collections").Counter(aids).items() if n > 1]
        assert not dupes, \
            f"Büroring: {len(dupes)} doppelte AIDs: {dupes[:5]}"

    def test_ean_coverage(self, xml):
        aids = _stream_collect(xml, _AID_PAT)
        eans = _stream_collect(xml, _EAN_PAT)
        if not aids:
            pytest.skip("Keine Artikel")
        pct = len(eans) / len(aids) * 100
        threshold = THRESHOLDS["bueroring_merged.xml"]["min_ean_pct"]
        assert pct >= threshold, \
            f"Büroring EAN-Abdeckung: {pct:.0f}% (min. {threshold}%)"

    def test_no_raw_0173_in_fnames(self, xml):
        """Nach FNAME-Transforms darf kein (0173-...) mehr in FNAMEs stehen."""
        fnames = _stream_collect(xml, _FNAME_PAT)
        dirty = [f for f in fnames if "0173" in f]
        assert not dirty, \
            f"Büroring: {len(dirty)} FNAMEs noch mit (0173-...): {dirty[:3]}"

    def test_file_not_truncated(self, xml):
        """XML muss mit </BMECAT> enden (nicht abgeschnitten)."""
        tail = ""
        with open(xml, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.strip():
                    tail = line.strip()
        assert "</BMECAT>" in tail.upper() or "</T_NEW_CATALOG>" in tail.upper(), \
            "Büroring: XML endet nicht mit schließendem Tag — möglicherweise abgeschnitten"


# ── Softcarrier ───────────────────────────────────────────────────────────────

class TestSoftcarrierMerge:

    @pytest.fixture
    def xml(self):
        path = _xml_path("soft-carrier_merge.xml")
        _skip_if_missing(path)
        return path

    def test_minimum_article_count(self, xml):
        count = _stream_count(xml, _ART_PAT)
        threshold = THRESHOLDS["soft-carrier_merge.xml"]["min_articles"]
        assert count >= threshold, \
            f"Softcarrier: nur {count} Artikel (min. {threshold})"

    def test_ean_coverage(self, xml):
        aids = _stream_collect(xml, _AID_PAT)
        eans = _stream_collect(xml, _EAN_PAT)
        if not aids:
            pytest.skip("Keine Artikel")
        pct = len(eans) / len(aids) * 100
        threshold = THRESHOLDS["soft-carrier_merge.xml"]["min_ean_pct"]
        assert pct >= threshold, \
            f"Softcarrier EAN: {pct:.0f}% (min. {threshold}%)"


# ── Nordwest ──────────────────────────────────────────────────────────────────

class TestNordwestCatalogs:

    @pytest.mark.parametrize("filename,key", [
        ("arbeitsschutz.xml",    "arbeitsschutz.xml"),
        ("werkstatt.xml",        "werkstatt.xml"),
        ("werkzeugtechnik.xml",  "werkzeugtechnik.xml"),
    ])
    def test_minimum_article_count(self, filename, key):
        path = _xml_path(filename)
        _skip_if_missing(path)
        count = _stream_count(path, _ART_PAT)
        threshold = THRESHOLDS[key]["min_articles"]
        assert count >= threshold, \
            f"{filename}: nur {count} Artikel (min. {threshold})"


# ── Allgemeine XML-Qualität ───────────────────────────────────────────────────

class TestXmlQuality:

    @pytest.mark.parametrize("filename", list(THRESHOLDS.keys()))
    def test_no_naked_ampersands(self, filename):
        """Kein nacktes & in der XML (würde Parser crashen)."""
        path = _xml_path(filename)
        _skip_if_missing(path)
        naked_pat = re.compile(r'&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)')
        found = []
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f, 1):
                if naked_pat.search(line):
                    found.append(i)
                    if len(found) >= 3:
                        break
        assert not found, \
            f"{filename}: nackte Ampersands in Zeilen {found}"
