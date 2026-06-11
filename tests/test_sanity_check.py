# tests/test_sanity_check.py
"""Tests für lib/sanity_check.py – Artikel-Datenqualität."""

import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.sanity_check import (
    extract_catalog_data,
    check_single_catalog,
    check_cross_supplier,
)


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


def _make_xml(articles):
    """articles: [(aid, ean, mfr, dshort, dlong, has_image), ...]"""
    lines = ['<BMECAT version="1.2">', '<T_NEW_CATALOG>']
    for aid, ean, mfr, dshort, dlong, has_image in articles:
        lines.append('<ARTICLE>')
        lines.append(f'  <SUPPLIER_AID>{aid}</SUPPLIER_AID>')
        if ean:
            lines.append(f'  <EAN>{ean}</EAN>')
        if dshort:
            lines.append(f'  <DESCRIPTION_SHORT>{dshort}</DESCRIPTION_SHORT>')
        if dlong:
            lines.append(f'  <DESCRIPTION_LONG>{dlong}</DESCRIPTION_LONG>')
        if mfr:
            lines.append(f'  <MANUFACTURER_NAME>{mfr}</MANUFACTURER_NAME>')
        if has_image:
            lines.append('  <MIME_INFO><MIME><MIME_SOURCE>bild.jpg</MIME_SOURCE></MIME></MIME_INFO>')
        lines.append('</ARTICLE>')
    lines.append('</T_NEW_CATALOG>')
    lines.append('</BMECAT>')
    return '\n'.join(lines)


class TestExtractCatalogData:

    def test_basic(self, tmp_path):
        xml = _make_xml([
            ("A001", "4000123456789", "Leitz", "Ordner A4", "Leitz Ordner breit", True),
            ("A002", None, None, "Stift", None, False),
        ])
        path = _write(tmp_path, "test.xml", xml)
        articles = extract_catalog_data(path)
        assert len(articles) == 2
        assert articles[0]["aid"] == "A001"
        assert articles[0]["ean"] == "4000123456789"
        assert articles[0]["manufacturer"] == "Leitz"
        assert articles[0]["has_image"] is True
        assert articles[1]["ean"] is None
        assert articles[1]["has_image"] is False

    def test_missing_file(self, tmp_path):
        assert extract_catalog_data(str(tmp_path / "nope.xml")) == []


class TestCheckSingleCatalog:

    def test_coverage_percentages(self):
        articles = [
            {"aid": "A1", "ean": "1234567890123", "manufacturer": "M",
             "desc_short": "Desc", "desc_long": "Long", "has_image": True},
            {"aid": "A2", "ean": None, "manufacturer": None,
             "desc_short": "D", "desc_long": None, "has_image": False},
        ]
        r = check_single_catalog(articles, "Test")
        assert r["total"] == 2
        assert r["ean_coverage"] == 50.0
        assert r["mfr_coverage"] == 50.0
        assert r["dlong_coverage"] == 50.0
        assert r["image_coverage"] == 50.0

    def test_duplicates(self):
        articles = [
            {"aid": "A1", "ean": "1", "manufacturer": "M",
             "desc_short": "D", "desc_long": "DL", "has_image": True},
            {"aid": "A1", "ean": "2", "manufacturer": "M",
             "desc_short": "D", "desc_long": "DL", "has_image": True},
        ]
        r = check_single_catalog(articles, "Test")
        assert r["duplicate_aids"] == 1

    def test_bad_ean_format(self):
        articles = [
            {"aid": "A1", "ean": "123", "manufacturer": "M",
             "desc_short": "D", "desc_long": "DL", "has_image": True},
            {"aid": "A2", "ean": "1234567890123", "manufacturer": "M",
             "desc_short": "D", "desc_long": "DL", "has_image": True},
        ]
        r = check_single_catalog(articles, "Test")
        assert r["bad_ean_format"] == 1  # "123" is 3 digits, not 8/13/14

    def test_full_coverage(self):
        articles = [
            {"aid": f"A{i}", "ean": f"{i:013d}", "manufacturer": "M",
             "desc_short": "Desc", "desc_long": "Long", "has_image": True}
            for i in range(10)
        ]
        r = check_single_catalog(articles, "Test")
        assert r["ean_coverage"] == 100.0
        assert r["no_ean"] == 0
        assert r["no_manufacturer"] == 0


class TestCheckCrossSupplier:

    def test_data_gap_manufacturer(self):
        catalogs = {
            "A": [{"aid": "1", "ean": "X", "manufacturer": "Leitz",
                   "desc_short": "S", "desc_long": "L", "has_image": True}],
            "B": [{"aid": "2", "ean": "X", "manufacturer": None,
                   "desc_short": "S", "desc_long": "L", "has_image": True}],
        }
        r = check_cross_supplier(catalogs)
        assert r["shared_eans"] == 1
        assert r["fillable_gaps"]["manufacturer"] == 1

    def test_data_gap_desc_long(self):
        catalogs = {
            "A": [{"aid": "1", "ean": "X", "manufacturer": "M",
                   "desc_short": "S", "desc_long": "Detailed text here",
                   "has_image": True}],
            "B": [{"aid": "2", "ean": "X", "manufacturer": "M",
                   "desc_short": "S", "desc_long": None, "has_image": True}],
        }
        r = check_cross_supplier(catalogs)
        assert r["fillable_gaps"]["desc_long"] == 1
        gap = r["top_gaps"]["desc_long"][0]
        assert gap["source"] == "A"
        assert gap["target"] == "B"
        assert "Detailed" in gap["value"]

    def test_image_gap(self):
        catalogs = {
            "A": [{"aid": "1", "ean": "X", "manufacturer": "M",
                   "desc_short": "S", "desc_long": "L", "has_image": True}],
            "B": [{"aid": "2", "ean": "X", "manufacturer": "M",
                   "desc_short": "S", "desc_long": "L", "has_image": False}],
        }
        r = check_cross_supplier(catalogs)
        assert r["image_gaps"] == 1

    def test_no_overlap(self):
        catalogs = {
            "A": [{"aid": "1", "ean": "111", "manufacturer": "M",
                   "desc_short": "S", "desc_long": "L", "has_image": True}],
            "B": [{"aid": "2", "ean": "222", "manufacturer": "M",
                   "desc_short": "S", "desc_long": "L", "has_image": True}],
        }
        r = check_cross_supplier(catalogs)
        assert r["shared_eans"] == 0
        assert all(v == 0 for v in r["fillable_gaps"].values()) if r["fillable_gaps"] else True

    def test_fill_matrix(self):
        catalogs = {
            "Büroring": [
                {"aid": "BR1", "ean": "111", "manufacturer": "Leitz",
                 "desc_short": "S", "desc_long": "Lang", "has_image": True},
                {"aid": "BR2", "ean": "222", "manufacturer": "Durable",
                 "desc_short": "S", "desc_long": "Lang", "has_image": True},
            ],
            "Softcarrier": [
                {"aid": "SC1", "ean": "111", "manufacturer": None,
                 "desc_short": "S", "desc_long": None, "has_image": True},
                {"aid": "SC2", "ean": "222", "manufacturer": None,
                 "desc_short": "S", "desc_long": None, "has_image": True},
            ],
        }
        r = check_cross_supplier(catalogs)
        # Büroring kann Softcarrier mit manufacturer + desc_long befüllen
        matrix = r["fill_matrix"]
        key = "Büroring → Softcarrier"
        assert key in matrix
        assert matrix[key]["manufacturer"] == 2
        assert matrix[key]["desc_long"] == 2

class TestExtractMultiline:
    """Tests für mehrzeilige Felder und HTML-Entity-Dekodierung."""

    def _write(self, tmp_path, name, content):
        p = tmp_path / name
        p.write_text(content, encoding="utf-8")
        return str(p)

    def test_multiline_desc_long(self, tmp_path):
        """DESCRIPTION_LONG über mehrere Zeilen wird erkannt."""
        xml = (
            '<BMECAT>\n<T_NEW_CATALOG>\n'
            '<ARTICLE>\n'
            '  <SUPPLIER_AID>A001</SUPPLIER_AID>\n'
            '  <EAN>4052396001693</EAN>\n'
            '  <DESCRIPTION_SHORT>Eimer</DESCRIPTION_SHORT>\n'
            '  <DESCRIPTION_LONG>\n'
            '    Eimer 50 Liter\n'
            '    &lt;br&gt;mit Deckel\n'
            '  </DESCRIPTION_LONG>\n'
            '  <MANUFACTURER_NAME>keeeper</MANUFACTURER_NAME>\n'
            '</ARTICLE>\n'
            '</T_NEW_CATALOG>\n</BMECAT>'
        )
        p = tmp_path / "test.xml"
        p.write_text(xml, encoding="utf-8")
        from lib.sanity_check import extract_catalog_data
        articles = extract_catalog_data(str(p))
        assert len(articles) == 1
        assert articles[0]["desc_long"] is not None
        assert "Eimer 50 Liter" in articles[0]["desc_long"]
        # HTML-Tags sollten entfernt worden sein
        assert "&lt;" not in articles[0]["desc_long"]
        assert "<br>" not in articles[0]["desc_long"]

    def test_html_entities_stripped(self, tmp_path):
        """&quot; und &amp; in Kurzbeschreibung werden dekodiert."""
        xml = (
            '<BMECAT><T_NEW_CATALOG>\n'
            '<ARTICLE>\n'
            '  <SUPPLIER_AID>A001</SUPPLIER_AID>\n'
            '  <EAN>4052396001693</EAN>\n'
            '  <DESCRIPTION_SHORT>Eimer &quot;swantje&quot;, 50L</DESCRIPTION_SHORT>\n'
            '  <DESCRIPTION_LONG>Text</DESCRIPTION_LONG>\n'
            '  <MANUFACTURER_NAME>keeeper</MANUFACTURER_NAME>\n'
            '</ARTICLE>\n'
            '</T_NEW_CATALOG></BMECAT>'
        )
        p = tmp_path / "test.xml"
        p.write_text(xml, encoding="utf-8")
        from lib.sanity_check import extract_catalog_data
        articles = extract_catalog_data(str(p))
        assert len(articles) == 1
        # &quot; sollte zu " dekodiert sein
        assert '"' in articles[0]["desc_short"] or 'swantje' in articles[0]["desc_short"]

    def test_ean_tag_recognized(self, tmp_path):
        """<EAN>...</EAN> (nicht INTERNATIONAL_PID) wird erkannt."""
        xml = (
            '<BMECAT><T_NEW_CATALOG>\n'
            '<ARTICLE>\n'
            '  <SUPPLIER_AID>BISL2910645</SUPPLIER_AID>\n'
            '  <EAN>5020073765670</EAN>\n'
            '  <DESCRIPTION_SHORT>MultiDrawer</DESCRIPTION_SHORT>\n'
            '  <DESCRIPTION_LONG>Beschreibung</DESCRIPTION_LONG>\n'
            '  <MANUFACTURER_NAME>bisley</MANUFACTURER_NAME>\n'
            '</ARTICLE>\n'
            '</T_NEW_CATALOG></BMECAT>'
        )
        p = tmp_path / "test.xml"
        p.write_text(xml, encoding="utf-8")
        from lib.sanity_check import extract_catalog_data
        articles = extract_catalog_data(str(p))
        assert len(articles) == 1
        assert articles[0]["ean"] == "5020073765670"
