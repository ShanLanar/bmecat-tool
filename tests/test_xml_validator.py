# tests/test_xml_validator.py
"""Tests für lib/xml_validator.py – XML-Validierung vor Upload."""

import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.xml_validator import validate_xml, validate_before_upload


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


class TestValidateXml:

    def test_missing_file(self, tmp_path):
        r = validate_xml(str(tmp_path / "nope.xml"))
        assert not r["valid"]
        assert any("nicht gefunden" in e for e in r["errors"])

    def test_empty_file(self, tmp_path):
        path = _write(tmp_path, "empty.xml", "")
        r = validate_xml(path)
        assert not r["valid"]
        assert any("leer" in e for e in r["errors"])

    def test_no_articles(self, tmp_path):
        path = _write(tmp_path, "no_art.xml",
                       '<BMECAT version="1.2"><HEADER/></BMECAT>')
        r = validate_xml(path)
        assert not r["valid"]
        assert any("Keine Artikel" in e for e in r["errors"])

    def test_valid_small_xml(self, tmp_path):
        xml = (
            '<?xml version="1.0"?>\n'
            '<BMECAT version="1.2">\n'
            '<T_NEW_CATALOG>\n'
        )
        for i in range(100):
            xml += (
                f'<ARTICLE>\n'
                f'  <SUPPLIER_AID>AID-{i:04d}</SUPPLIER_AID>\n'
                f'  <DESCRIPTION_SHORT>Test {i}</DESCRIPTION_SHORT>\n'
                f'</ARTICLE>\n'
            )
        xml += '</T_NEW_CATALOG>\n</BMECAT>'
        path = _write(tmp_path, "valid.xml", xml)
        r = validate_xml(path)
        assert r["valid"]
        assert r["article_count"] == 100
        assert r["errors"] == []

    def test_truncated_xml_no_footer(self, tmp_path):
        xml = (
            '<BMECAT version="1.2">\n'
            '<ARTICLE><SUPPLIER_AID>X1</SUPPLIER_AID></ARTICLE>\n'
            '<ARTICLE><SUPPLIER_AID>X2</SUPPLIER_AID></ARTICLE>\n'
            # Kein </BMECAT>
        )
        path = _write(tmp_path, "truncated.xml", xml)
        r = validate_xml(path)
        assert not r["valid"]
        assert any("Abschluss" in e for e in r["errors"])

    def test_threshold_warning(self, tmp_path):
        xml = '<BMECAT version="1.2">\n'
        for i in range(10):
            xml += f'<ARTICLE><SUPPLIER_AID>A{i}</SUPPLIER_AID></ARTICLE>\n'
        xml += '</BMECAT>'
        path = _write(tmp_path, "bueroring_merged.xml", xml)
        r = validate_xml(path)
        # 10 Artikel, Schwellwert = 20000 → Warnung
        assert r["valid"]  # Schwellwert ist nur Warnung, kein Fehler
        assert any("Nur 10 Artikel" in w for w in r["warnings"])

    def test_missing_supplier_aid_warning(self, tmp_path):
        xml = (
            '<BMECAT version="1.2">\n'
            '<ARTICLE><DESCRIPTION_SHORT>Kein AID</DESCRIPTION_SHORT></ARTICLE>\n'
            '<ARTICLE><SUPPLIER_AID>X1</SUPPLIER_AID></ARTICLE>\n'
            '</BMECAT>'
        )
        path = _write(tmp_path, "test.xml", xml)
        r = validate_xml(path)
        assert r["valid"]
        assert any("SUPPLIER_AID" in w for w in r["warnings"])


class TestValidateBeforeUpload:

    def test_all_valid(self, tmp_path):
        xml = '<BMECAT version="1.2">\n<ARTICLE><SUPPLIER_AID>A1</SUPPLIER_AID></ARTICLE>\n</BMECAT>'
        p1 = _write(tmp_path, "a.xml", xml)
        p2 = _write(tmp_path, "b.xml", xml)
        logs = []
        assert validate_before_upload([p1, p2], progress_cb=lambda m, **kw: logs.append(m))

    def test_one_invalid(self, tmp_path):
        good = '<BMECAT version="1.2">\n<ARTICLE><SUPPLIER_AID>A1</SUPPLIER_AID></ARTICLE>\n</BMECAT>'
        bad = '<BMECAT version="1.2"><HEADER/></BMECAT>'
        p1 = _write(tmp_path, "good.xml", good)
        p2 = _write(tmp_path, "bad.xml", bad)
        assert not validate_before_upload([p1, p2])

    def test_skips_missing(self, tmp_path):
        # Fehlende Dateien werden übersprungen
        result = validate_before_upload([str(tmp_path / "nope.xml")])
        assert result  # Keine vorhandenen Dateien = keine Fehler
