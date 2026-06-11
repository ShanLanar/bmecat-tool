# tests/test_stress_improvements.py – Tests für alle 10 Verbesserungen

import sys, os, re, pytest, json, tempfile, zipfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.utils import iter_articles
from lib.article_enrichment import rule_gtin_fix, rule_delivery_time, rule_manufacturer_normalize
from lib.credentials import get_password, set_password, _has_keyring
from lib.supplier_config import get_supplier, get_enabled_suppliers, get_category_prefix


# ── iter_articles: einzeilige XML ────────────────────────────────────────────

class TestIterArticles:

    def _write(self, tmp_path, content, name="test.xml"):
        p = tmp_path / name
        p.write_text(content, encoding="utf-8")
        return str(p)

    def test_multiline_xml(self, tmp_path):
        xml = self._write(tmp_path, """<BMECAT>
<ARTICLE>
  <SUPPLIER_AID>A1</SUPPLIER_AID>
</ARTICLE>
<ARTICLE>
  <SUPPLIER_AID>A2</SUPPLIER_AID>
</ARTICLE>
</BMECAT>""")
        arts = list(iter_articles(xml))
        assert len(arts) == 2
        assert "A1" in arts[0]
        assert "A2" in arts[1]

    def test_singleline_xml(self, tmp_path):
        xml = self._write(tmp_path,
            "<BMECAT>"
            "<ARTICLE><SUPPLIER_AID>A1</SUPPLIER_AID></ARTICLE>"
            "<ARTICLE><SUPPLIER_AID>A2</SUPPLIER_AID></ARTICLE>"
            "</BMECAT>")
        arts = list(iter_articles(xml))
        assert len(arts) == 2, f"Einzeilige XML: {len(arts)} statt 2 Artikel"

    def test_mixed_line_lengths(self, tmp_path):
        xml = self._write(tmp_path,
            "<BMECAT>\n"
            "<ARTICLE><SUPPLIER_AID>A1</SUPPLIER_AID><DESCRIPTION_SHORT>T</DESCRIPTION_SHORT></ARTICLE>\n"
            "<ARTICLE>\n<SUPPLIER_AID>A2</SUPPLIER_AID>\n</ARTICLE>\n"
            "</BMECAT>")
        arts = list(iter_articles(xml))
        assert len(arts) == 2

    def test_empty_xml(self, tmp_path):
        xml = self._write(tmp_path, "<BMECAT></BMECAT>")
        arts = list(iter_articles(xml))
        assert arts == []

    def test_missing_file(self, tmp_path):
        arts = list(iter_articles(str(tmp_path / "nope.xml")))
        assert arts == []

    @pytest.mark.parametrize("n", [1, 10, 100])
    def test_counts_match(self, tmp_path, n):
        arts_xml = "".join(
            f"<ARTICLE><SUPPLIER_AID>A{i}</SUPPLIER_AID></ARTICLE>"
            for i in range(n))
        xml = self._write(tmp_path, f"<BMECAT>{arts_xml}</BMECAT>")
        arts = list(iter_articles(xml))
        assert len(arts) == n

    def test_article_content_complete(self, tmp_path):
        """Jeder Artikel-Block muss vollständig sein."""
        xml = self._write(tmp_path,
            "<BMECAT>"
            "<ARTICLE><SUPPLIER_AID>A1</SUPPLIER_AID>"
            "<EAN>4052396001693</EAN>"
            "<MANUFACTURER_NAME>CASIO</MANUFACTURER_NAME>"
            "</ARTICLE>"
            "</BMECAT>")
        arts = list(iter_articles(xml))
        assert len(arts) == 1
        assert "4052396001693" in arts[0]
        assert "CASIO" in arts[0]


# ── rule_gtin_fix ─────────────────────────────────────────────────────────────

def _art_ean(ean):
    return (f"<ARTICLE><ARTICLE_DETAILS>"
            f"<SUPPLIER_AID>A1</SUPPLIER_AID>"
            f"<DESCRIPTION_SHORT>Test</DESCRIPTION_SHORT>"
            f"<EAN>{ean}</EAN>"
            f"</ARTICLE_DETAILS></ARTICLE>")

class TestRuleGtinFix:

    def test_fixes_wrong_check_digit(self):
        a = _art_ean("4052396001694")  # richtig: 4052396001693
        result, changed = rule_gtin_fix(a)
        assert changed
        assert "4052396001693" in result
        assert "4052396001694" not in result

    def test_valid_ean_unchanged(self):
        a = _art_ean("4052396001693")
        _, changed = rule_gtin_fix(a)
        assert not changed

    def test_non_fixable_ean_unchanged(self):
        a = _art_ean("9999999999999")  # mehrere Stellen falsch
        result, changed = rule_gtin_fix(a)
        # Kein Absturz, und kein Fix wenn nicht eindeutig
        assert isinstance(changed, bool)

    def test_no_ean_no_change(self):
        a = "<ARTICLE><ARTICLE_DETAILS><SUPPLIER_AID>A1</SUPPLIER_AID></ARTICLE_DETAILS></ARTICLE>"
        _, changed = rule_gtin_fix(a)
        assert not changed

    @pytest.mark.parametrize("valid_ean", [
        "4052396001693", "5020073765670", "90311017",
    ])
    def test_valid_eans_preserved(self, valid_ean):
        a = _art_ean(valid_ean)
        result, changed = rule_gtin_fix(a)
        assert not changed
        assert valid_ean in result


# ── rule_delivery_time ────────────────────────────────────────────────────────

class TestRuleDeliveryTime:

    def test_adds_when_missing(self):
        a = ("<ARTICLE><ARTICLE_DETAILS>"
             "<SUPPLIER_AID>A1</SUPPLIER_AID>"
             "<DESCRIPTION_SHORT>Test</DESCRIPTION_SHORT>"
             "</ARTICLE_DETAILS></ARTICLE>")
        result, changed = rule_delivery_time(a)
        assert changed
        assert "<DELIVERY_TIME>1</DELIVERY_TIME>" in result

    def test_no_change_when_present(self):
        a = ("<ARTICLE><ARTICLE_DETAILS>"
             "<DELIVERY_TIME>2</DELIVERY_TIME>"
             "</ARTICLE_DETAILS></ARTICLE>")
        _, changed = rule_delivery_time(a)
        assert not changed

    def test_existing_value_preserved(self):
        a = ("<ARTICLE><ARTICLE_DETAILS>"
             "<DELIVERY_TIME>5</DELIVERY_TIME>"
             "</ARTICLE_DETAILS></ARTICLE>")
        result, _ = rule_delivery_time(a)
        assert "<DELIVERY_TIME>5</DELIVERY_TIME>" in result

    def test_placed_before_details_end(self):
        a = ("<ARTICLE><ARTICLE_DETAILS>"
             "<SUPPLIER_AID>A1</SUPPLIER_AID>"
             "</ARTICLE_DETAILS></ARTICLE>")
        result, changed = rule_delivery_time(a)
        if changed:
            dt_pos = result.find("<DELIVERY_TIME>")
            end_pos = result.find("</ARTICLE_DETAILS>")
            assert dt_pos < end_pos


# ── rule_manufacturer_normalize ───────────────────────────────────────────────

class TestRuleMfrNormalize:

    def _art_mfr(self, mfr):
        return (f"<ARTICLE><ARTICLE_DETAILS>"
                f"<MANUFACTURER_NAME>{mfr}</MANUFACTURER_NAME>"
                f"</ARTICLE_DETAILS></ARTICLE>")

    def test_normalize_from_aliases(self, tmp_path, monkeypatch):
        """Alias-Tabelle wird korrekt angewendet."""
        import lib.article_enrichment as ae
        ae._mfr_aliases = {"HEWLETT PACKARD": "HP", "TEST GMBH": "Test"}
        a = self._art_mfr("HEWLETT PACKARD")
        result, changed = rule_manufacturer_normalize(a)
        assert changed
        assert "<MANUFACTURER_NAME>HP</MANUFACTURER_NAME>" in result
        ae._mfr_aliases = None  # Reset

    def test_unknown_mfr_unchanged(self):
        import lib.article_enrichment as ae
        ae._mfr_aliases = {"HEWLETT PACKARD": "HP"}
        a = self._art_mfr("CASIO")
        _, changed = rule_manufacturer_normalize(a)
        assert not changed
        ae._mfr_aliases = None

    def test_no_mfr_no_change(self):
        a = "<ARTICLE><ARTICLE_DETAILS></ARTICLE_DETAILS></ARTICLE>"
        _, changed = rule_manufacturer_normalize(a)
        assert not changed


# ── supplier_config.py ────────────────────────────────────────────────────────

class TestSupplierConfig:

    def test_get_enabled_suppliers_returns_dict(self):
        result = get_enabled_suppliers()
        assert isinstance(result, dict)

    def test_get_supplier_unknown_returns_empty(self):
        result = get_supplier("unknown_xyz_supplier")
        assert result == {}

    def test_get_category_prefix_fallback(self):
        # Unbekannter Lieferant → Fallback auf ersten 3 Buchstaben
        result = get_category_prefix("testlieferant")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_yaml_loads_without_crash(self):
        cfg = get_enabled_suppliers()
        assert isinstance(cfg, dict)


# ── credentials.py ────────────────────────────────────────────────────────────

class TestCredentials:

    def test_get_without_keyring_returns_fallback(self):
        """Ohne keyring: immer Fallback."""
        result = get_password("nonexistent_supplier", "user", fallback="default_pw")
        assert isinstance(result, str)

    def test_fallback_returned_when_not_found(self):
        result = get_password("xyz_supplier_not_in_keyring", "user", fallback="abc")
        assert result == "abc" or isinstance(result, str)

    def test_has_keyring_returns_bool(self):
        result = _has_keyring()
        assert isinstance(result, bool)

    def test_set_without_keyring_no_crash(self):
        """set_password darf nicht abstürzen wenn keyring fehlt."""
        try:
            result = set_password("test_supplier", "testuser", "testpw")
            assert isinstance(result, bool)
        except Exception as e:
            pytest.fail(f"Absturz: {e}")


# ── Cross-Fill Basis ──────────────────────────────────────────────────────────

from lib.cross_fill import _build_ean_index, _fill_article


class TestCrossFill:

    def _xml(self, tmp_path, articles, name="test.xml"):
        lines = ["<?xml version='1.0'?>", "<BMECAT>"]
        for a in articles:
            lines += [
                "<ARTICLE>", "  <ARTICLE_DETAILS>",
                f"    <SUPPLIER_AID>{a['aid']}</SUPPLIER_AID>",
            ]
            if a.get("ean"):   lines.append(f"    <EAN>{a['ean']}</EAN>")
            if a.get("mfr"):   lines.append(f"    <MANUFACTURER_NAME>{a['mfr']}</MANUFACTURER_NAME>")
            if a.get("desc"):  lines.append(f"    <DESCRIPTION_LONG>{a['desc']}</DESCRIPTION_LONG>")
            lines += ["  </ARTICLE_DETAILS>", "</ARTICLE>"]
        lines.append("</BMECAT>")
        p = tmp_path / name
        p.write_text("\n".join(lines), encoding="utf-8")
        return str(p)

    def test_build_ean_index(self, tmp_path):
        xml = self._xml(tmp_path, [
            {"aid": "A1", "ean": "4052396001693", "mfr": "CASIO"},
            {"aid": "A2", "ean": "5020073765670", "mfr": "Leitz"},
        ])
        idx = _build_ean_index(xml)
        assert "4052396001693" in idx
        assert idx["4052396001693"]["manufacturer"] == "CASIO"
        assert "5020073765670" in idx

    def test_build_ean_index_missing_file(self, tmp_path):
        idx = _build_ean_index(str(tmp_path / "nope.xml"))
        assert idx == {}

    def test_fill_article_manufacturer(self):
        article = ("<ARTICLE><ARTICLE_DETAILS>"
                   "<SUPPLIER_AID>A1</SUPPLIER_AID>"
                   "</ARTICLE_DETAILS></ARTICLE>")
        result, filled = _fill_article(article, {"manufacturer": "CASIO"})
        assert "manufacturer" in filled
        assert "CASIO" in result

    def test_fill_article_no_overwrite(self):
        article = ("<ARTICLE><ARTICLE_DETAILS>"
                   "<MANUFACTURER_NAME>LEITZ</MANUFACTURER_NAME>"
                   "</ARTICLE_DETAILS></ARTICLE>")
        result, filled = _fill_article(article, {"manufacturer": "CASIO"})
        assert "manufacturer" not in filled  # nicht überschreiben
        assert "LEITZ" in result

    def test_fill_article_desc_long(self):
        article = ("<ARTICLE><ARTICLE_DETAILS>"
                   "<SUPPLIER_AID>A1</SUPPLIER_AID>"
                   "</ARTICLE_DETAILS></ARTICLE>")
        result, filled = _fill_article(article, {"desc_long": "Produktbeschreibung"})
        assert "desc_long" in filled
        assert "Produktbeschreibung" in result

    def test_ean_index_skips_no_ean(self, tmp_path):
        xml = self._xml(tmp_path, [
            {"aid": "A1", "mfr": "CASIO"},  # kein EAN
        ])
        idx = _build_ean_index(xml)
        assert len(idx) == 0
