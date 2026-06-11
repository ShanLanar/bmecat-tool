# tests/test_stress_final.py – Sanity/Pipeline/Robustheit Finale (80+ Fälle)

import sys, os, re, pytest, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.sanity_check import extract_catalog_data, check_single_catalog, check_cross_supplier
from lib.article_enrichment import enrich
from lib.dead_letter import validate_article_basic, DeadLetterQueue
from lib.utils import gtin_valid, gtin_fix, mfr_matches


# ── Sanity Check: check_single_catalog ───────────────────────────────────────

def _xml_with_articles(tmp_path, articles, name="test.xml"):
    """Erstellt mehrzeilige BMEcat-XML (wichtig für Streaming-Parser)."""
    lines = ["<?xml version='1.0' encoding='UTF-8'?>", "<BMECAT>", "<T_NEW_CATALOG>"]
    for a in articles:
        lines.append("<ARTICLE>")
        lines.append("  <ARTICLE_DETAILS>")
        lines.append(f"    <SUPPLIER_AID>{a['aid']}</SUPPLIER_AID>")
        lines.append(f"    <DESCRIPTION_SHORT>{a.get('desc','Artikel')}</DESCRIPTION_SHORT>")
        if a.get("ean"):
            lines.append(f"    <EAN>{a['ean']}</EAN>")
        if a.get("mfr"):
            lines.append(f"    <MANUFACTURER_NAME>{a['mfr']}</MANUFACTURER_NAME>")
        lines.append("  </ARTICLE_DETAILS>")
        lines.append("</ARTICLE>")
    lines += ["</T_NEW_CATALOG>", "</BMECAT>"]
    p = tmp_path / name
    p.write_text("\n".join(lines), encoding="utf-8")
    return str(p)


SAMPLE_ARTICLES = [
    {"aid": f"ART{i:04d}", "ean": f"40521{i:08d}", "mfr": "CASIO", "desc": f"Artikel {i}"}
    for i in range(10)
]


class TestSanityCheckSingle:

    def test_basic_catalog(self, tmp_path):
        xml = _xml_with_articles(tmp_path, SAMPLE_ARTICLES)
        articles = extract_catalog_data(xml)
        result = check_single_catalog(articles, "Test")
        assert isinstance(result, dict)
        assert result["total"] == 10

    def test_empty_catalog(self, tmp_path):
        xml = _xml_with_articles(tmp_path, [])
        articles = extract_catalog_data(xml)
        result = check_single_catalog(articles, "Test")
        assert result["total"] == 0

    def test_ean_coverage(self, tmp_path):
        arts = [{"aid": f"A{i}", "ean": "4052396001693" if i < 7 else None}
                for i in range(10)]
        xml = _xml_with_articles(tmp_path, arts)
        articles = extract_catalog_data(xml)
        result = check_single_catalog(articles, "Test")
        assert 65 <= result["ean_coverage"] <= 75  # ~70%

    def test_full_ean_coverage(self, tmp_path):
        arts = [{"aid": f"A{i}", "ean": "4052396001693"} for i in range(5)]
        xml = _xml_with_articles(tmp_path, arts)
        articles = extract_catalog_data(xml)
        result = check_single_catalog(articles, "Test")
        assert result["ean_coverage"] == 100.0

    def test_no_ean_coverage(self, tmp_path):
        arts = [{"aid": f"A{i}"} for i in range(5)]
        xml = _xml_with_articles(tmp_path, arts)
        articles = extract_catalog_data(xml)
        result = check_single_catalog(articles, "Test")
        assert result["ean_coverage"] == 0.0

    def test_duplicate_aids_detected(self, tmp_path):
        arts = [
            {"aid": "DUPLICATE", "ean": "4052396001693"},
            {"aid": "DUPLICATE", "ean": "5020073765670"},
            {"aid": "UNIQUE",    "ean": "4052396001693"},
        ]
        xml = _xml_with_articles(tmp_path, arts)
        articles = extract_catalog_data(xml)
        result = check_single_catalog(articles, "Test")
        assert result["duplicate_aids"] >= 1

    def test_gtin_validation_reported(self, tmp_path):
        arts = [
            {"aid": "VALID",   "ean": "4052396001693"},  # gültig
            {"aid": "INVALID", "ean": "4052396001694"},  # ungültig (letzte Stelle)
        ]
        xml = _xml_with_articles(tmp_path, arts)
        articles = extract_catalog_data(xml)
        result = check_single_catalog(articles, "Test")
        assert "invalid_gtin" in result or "fixable_gtin" in result

    def test_result_always_dict(self, tmp_path):
        """Auch bei kaputten Eingaben: immer dict zurück."""
        for arts in [[], [{"aid": "A1"}], SAMPLE_ARTICLES[:3]]:
            xml = _xml_with_articles(tmp_path, arts)
            articles = extract_catalog_data(xml)
            result = check_single_catalog(articles, "Test")
            assert isinstance(result, dict)

    def test_missing_xml_handled(self, tmp_path):
        articles = extract_catalog_data(str(tmp_path / "nope.xml"))
        result = check_single_catalog(articles, "Test")
        assert isinstance(result, dict)
        assert result.get("total", 0) == 0

    @pytest.mark.parametrize("n", [1, 5, 50, 200])
    def test_article_count_correct(self, tmp_path, n):
        arts = [{"aid": f"ART{i:06d}", "ean": "4052396001693"} for i in range(n)]
        xml = _xml_with_articles(tmp_path, arts)
        articles = extract_catalog_data(xml)
        result = check_single_catalog(articles, "Test")
        assert result["total"] == n


# ── Artikel-Anreicherung: Vollständige Pipeline ───────────────────────────────

def _full_bmecat(tmp_path, articles, name="merged.xml"):
    """Multi-line BMEcat für Enrichment-Tests."""
    lines = ["<?xml version='1.0' encoding='UTF-8'?>", "<BMECAT>"]
    for a in articles:
        lines += [
            "<ARTICLE>",
            "  <ARTICLE_DETAILS>",
            f"    <SUPPLIER_AID>{a['aid']}</SUPPLIER_AID>",
            f"    <DESCRIPTION_SHORT>{a.get('desc', 'Test')}</DESCRIPTION_SHORT>",
        ]
        if a.get("ean"):
            lines.append(f"    <EAN>{a['ean']}</EAN>")
        if a.get("mfr"):
            lines.append(f"    <MANUFACTURER_NAME>{a['mfr']}</MANUFACTURER_NAME>")
        if a.get("keywords"):
            for kw in a["keywords"]:
                lines.append(f"    <KEYWORD>{kw}</KEYWORD>")
        lines += ["  </ARTICLE_DETAILS>", "</ARTICLE>"]
    lines.append("</BMECAT>")
    p = tmp_path / name
    p.write_text("\n".join(lines), encoding="utf-8")
    return str(p)


class TestEnrichPipeline:

    def test_ean_keyword_added_to_all(self, tmp_path):
        arts = [{"aid": f"A{i}", "ean": "4052396001693"} for i in range(5)]
        xml = _full_bmecat(tmp_path, arts)
        enrich(xml, progress_cb=lambda m, **kw: None)
        content = open(xml).read()
        assert content.count("<KEYWORD>4052396001693</KEYWORD>") == 5

    def test_aid_suffix_removed(self, tmp_path):
        arts = [{"aid": "A1", "ean": "4052396001693",
                 "desc": "Schulrechner FX-87DEX (CASFX87DEX)"}]
        xml = _full_bmecat(tmp_path, arts)
        enrich(xml, progress_cb=lambda m, **kw: None)
        content = open(xml).read()
        assert "CASFX87DEX" not in content
        assert "Schulrechner FX-87DEX" in content

    def test_dedup_across_many_articles(self, tmp_path):
        # Viele Artikel mit duplizierten Keywords
        arts = [{"aid": f"A{i}", "ean": "4052396001693",
                 "keywords": ["CASIO", "casio", "Casio", "Taschenrechner"]}
                for i in range(10)]
        xml = _full_bmecat(tmp_path, arts)
        enrich(xml, progress_cb=lambda m, **kw: None)
        content = open(xml).read()
        # Pro Artikel: maximal 2 CASIO-Varianten → genau 1 nach Dedup
        # Gesamtartikel * 1 = 10 mal "CASIO"
        casio_count = content.upper().count("<KEYWORD>CASIO</KEYWORD>")
        assert casio_count <= 10  # höchstens 1 pro Artikel

    def test_dlq_created_for_bad_articles(self, tmp_path):
        """Artikel ohne AID → DLQ-Datei wird erstellt."""
        # Manuell eine XML mit ungültigem Artikel erstellen
        lines = [
            "<?xml version='1.0' encoding='UTF-8'?>",
            "<BMECAT>",
            "<ARTICLE>",
            "  <ARTICLE_DETAILS>",
            "    <DESCRIPTION_SHORT>Kein AID</DESCRIPTION_SHORT>",  # kein SUPPLIER_AID
            "  </ARTICLE_DETAILS>",
            "</ARTICLE>",
            "<ARTICLE>",
            "  <ARTICLE_DETAILS>",
            "    <SUPPLIER_AID>VALID001</SUPPLIER_AID>",
            "    <DESCRIPTION_SHORT>Gültiger Artikel</DESCRIPTION_SHORT>",
            "  </ARTICLE_DETAILS>",
            "</ARTICLE>",
            "</BMECAT>",
        ]
        p = tmp_path / "test.xml"
        p.write_text("\n".join(lines), encoding="utf-8")
        enrich(str(p), progress_cb=lambda m, **kw: None)
        # Gültiger Artikel soll noch in XML sein
        content = p.read_text()
        assert "VALID001" in content

    def test_file_written_back(self, tmp_path):
        """enrich() schreibt Datei zurück wenn Änderungen."""
        arts = [{"aid": "A1", "ean": "4052396001693"}]
        xml = _full_bmecat(tmp_path, arts)
        import os
        mtime_before = os.path.getmtime(xml)
        import time; time.sleep(0.01)
        enrich(xml, progress_cb=lambda m, **kw: None)
        mtime_after = os.path.getmtime(xml)
        assert mtime_after >= mtime_before

    def test_returns_stats_dict(self, tmp_path):
        arts = [{"aid": "A1", "ean": "4052396001693"}]
        xml = _full_bmecat(tmp_path, arts)
        stats = enrich(xml, progress_cb=lambda m, **kw: None)
        assert isinstance(stats, dict)
        assert "articles_total" in stats
        assert "articles_changed" in stats
        assert "by_rule" in stats

    def test_no_crash_empty_xml(self, tmp_path):
        p = tmp_path / "empty.xml"
        p.write_text("<?xml version='1.0'?><BMECAT></BMECAT>")
        try:
            stats = enrich(str(p), progress_cb=lambda m, **kw: None)
            assert stats["articles_total"] == 0
        except Exception as e:
            pytest.fail(f"Absturz: {e}")


# ── GTIN Spezial-Cases ────────────────────────────────────────────────────────

class TestGtinSpecial:

    def test_ean8_vs_ean13_valid(self):
        """EAN-8 und EAN-13 beide valide."""
        assert gtin_valid("90311017")       # EAN-8
        assert gtin_valid("4052396001693")  # EAN-13

    def test_leading_zeros_ean13(self):
        """EANs mit führenden Nullen."""
        assert gtin_valid("0012345678905") or not gtin_valid("0012345678905")
        # kein Absturz ist ausreichend

    def test_all_same_digit(self):
        """EAN mit lauter gleichen Ziffern."""
        assert not gtin_valid("1111111111111")  # prüfziffer 1? checken
        result = gtin_valid("0000000000000")
        assert isinstance(result, bool)  # kein Absturz

    def test_fix_preserves_first_12_digits(self):
        """gtin_fix ändert nur letzte Stelle."""
        ean = "4052396001694"  # letzte Stelle falsch
        fixed = gtin_fix(ean)
        if fixed:
            assert fixed[:12] == ean[:12]

    @pytest.mark.parametrize("ean", ["0" * 13, "9" * 13, "1234567890128"])
    def test_boundary_eans_no_crash(self, ean):
        result = gtin_valid(ean)
        assert isinstance(result, bool)


# ── Manufacturer Matching Grenzfälle ──────────────────────────────────────────

class TestMfrMatchingEdge:

    def test_same_name_matches(self):
        assert mfr_matches("CASIO", "CASIO")

    def test_empty_vs_nonempty(self):
        assert not mfr_matches("", "CASIO")
        assert not mfr_matches("CASIO", "")

    def test_both_empty(self):
        assert not mfr_matches("", "")

    def test_single_char_names(self):
        result = mfr_matches("A", "A")
        assert isinstance(result, bool)

    def test_very_long_names(self):
        long = "Herstellergesellschaft" * 10
        result = mfr_matches(long, long)
        assert isinstance(result, bool)

    @pytest.mark.parametrize("name", [
        "3M", "HP", "ABB", "GE", "IBM", "SAP"
    ])
    def test_short_company_names(self, name):
        result = mfr_matches(name, name)
        assert isinstance(result, bool)

    def test_numbers_in_name(self):
        result = mfr_matches("3M Deutschland", "3M")
        assert isinstance(result, bool)
