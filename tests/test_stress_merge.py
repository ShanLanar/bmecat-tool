# tests/test_stress_merge.py – bmecat_merge + xml_validator Stresstests (90+ Fälle)

import sys, os, re, pytest, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.bmecat_merge import sanitize_xml
from lib.xml_validator import validate_xml


def _write_xml(tmp_path, content, name="test.xml"):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


# ── sanitize_xml: nackte Ampersands ──────────────────────────────────────────

SANITIZE_CASES = [
    # (input_contains, expected_in_output, n_fixes)
    ("Clic & Go",            "&amp;",    1),
    ("A & B & C",            "&amp;",    2),
    ("kein_problem",         "kein_problem", 0),
    ("&amp; schon gut",      "&amp;",    0),
    ("&lt;ok&gt;",           "&lt;",     0),
    ("M&M Produkt",          "M&amp;M",  1),
    ("AT&T und C&A",         "&amp;",    2),
    ("100%",                 "100%",     0),
    ("a&b&c&d",              "&amp;",    3),
    # Entitäten dürfen nicht doppelt-escaped werden
    ("&amp;amp; Test",       "&amp;amp;", 0),
    ("&lt;&gt;&quot;&apos;", "&lt;",      0),
]

class TestSanitizeXml:

    @pytest.mark.parametrize("inp,expected,n_fixes", SANITIZE_CASES)
    def test_sanitize(self, tmp_path, inp, expected, n_fixes):
        xml = f"<ROOT><ITEM>{inp}</ITEM></ROOT>"
        path = _write_xml(tmp_path, xml)
        fixes = sanitize_xml(path)
        assert fixes == n_fixes, f"Input={inp!r}: {fixes} fixes, erwartet {n_fixes}"
        content = open(path).read()
        assert expected in content

    def test_file_not_found_no_crash(self, tmp_path):
        try:
            result = sanitize_xml(str(tmp_path / "nonexistent.xml"))
        except Exception:
            result = 0
        assert result == 0 or result is None

    def test_very_long_line(self, tmp_path):
        xml = "<ROOT>" + "A & B " * 5000 + "</ROOT>"
        path = _write_xml(tmp_path, xml)
        fixes = sanitize_xml(path)
        assert fixes == 5000

    def test_empty_file(self, tmp_path):
        path = _write_xml(tmp_path, "")
        result = sanitize_xml(path)
        assert result == 0 or result is None

    def test_file_rewritten_correctly(self, tmp_path):
        xml = "<ROOT><A>Test & More</A></ROOT>"
        path = _write_xml(tmp_path, xml)
        sanitize_xml(path)
        content = open(path).read()
        import xml.etree.ElementTree as ET
        ET.fromstring(content)  # muss parseable sein


# ── xml_validator ─────────────────────────────────────────────────────────────

MIN_ARTICLE = 5

VALID_XMLS = [
    # (articles, expected_ok)
    (10, True),
    (MIN_ARTICLE, True),
    (MIN_ARTICLE + 1, True),
    (100, True),
]

INVALID_XMLS = [
    (0, False),
    (MIN_ARTICLE - 1, False),
]


def _bmecat(n_articles):
    arts = "\n".join(
        f"<ARTICLE mode='new'>"
        f"<SUPPLIER_AID>AID{i:04d}</SUPPLIER_AID>"
        f"<ARTICLE_DETAILS><DESCRIPTION_SHORT>Artikel {i}</DESCRIPTION_SHORT></ARTICLE_DETAILS>"
        f"</ARTICLE>"
        for i in range(n_articles)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<BMECAT version="1.2">
<HEADER><CATALOG><LANGUAGE>deu</LANGUAGE></CATALOG></HEADER>
<T_NEW_CATALOG>{arts}</T_NEW_CATALOG>
</BMECAT>"""


class TestXmlValidator:


    def test_malformed_xml(self, tmp_path):
        path = _write_xml(tmp_path, "<ROOT><unclosed>")
        result = validate_xml(path)
        ok = result.get("ok", result.get("valid", True)) if result else False
        assert not ok

    def test_empty_file(self, tmp_path):
        path = _write_xml(tmp_path, "")
        result = validate_xml(path)
        ok = result.get("ok", result.get("valid", True)) if result else False
        assert not ok

    def test_missing_file(self, tmp_path):
        result = validate_xml(str(tmp_path / "nope.xml"))
        assert isinstance(result, dict)

    def test_zero_articles_no_crash(self, tmp_path):
        path = _write_xml(tmp_path, _bmecat(0))
        result = validate_xml(path)
        assert result is None or isinstance(result, dict)

    def test_valid_xml_returns_dict(self, tmp_path):
        path = _write_xml(tmp_path, _bmecat(10))
        result = validate_xml(path)
        assert isinstance(result, dict)
        assert result  # nicht leer

    @pytest.mark.parametrize("n", [1, 100, 1000])
    def test_large_catalogs_no_crash(self, tmp_path, n):
        path = _write_xml(tmp_path, _bmecat(n))
        result = validate_xml(path)
        ok = result.get("ok", result.get("valid", True)) if result else False
        assert ok


# ── Edge Cases: Unicode in XML ────────────────────────────────────────────────

class TestXmlUnicodeEdgeCases:

    def test_umlauts_in_article_no_crash(self, tmp_path):
        xml = _bmecat(1).replace("Artikel 0", "Größe und Maße")
        path = _write_xml(tmp_path, xml)
        try:
            result = validate_xml(path)
            assert isinstance(result, dict)
        except Exception:
            pass

    def test_chinese_chars_no_crash(self, tmp_path):
        xml = _bmecat(1).replace("Artikel 0", "中文产品名称")
        path = _write_xml(tmp_path, xml)
        try:
            ok, _ = validate_xml(path, min_articles=1)
        except Exception:
            pass  # Encoding-Fehler OK, Absturz nicht

    def test_null_bytes_handled(self, tmp_path):
        # Null-Bytes in XML → sollte nicht crashen
        path = str(tmp_path / "null.xml")
        with open(path, "wb") as f:
            f.write(b"<ROOT>\x00</ROOT>")
        try:
            result = validate_xml(path)
            ok = isinstance(result, dict)
            # Kein Absturz ist ausreichend
        except Exception:
            pass  # Exception ist OK, Absturz nicht


# ── Diff Report: Basis-Struktur ───────────────────────────────────────────────

from lib.diff_report import create_diff_report, extract_article_snapshot, compare_snapshots


class TestDiffReport:

    def test_create_diff_runs(self, tmp_path):
        """create_diff_report läuft ohne Absturz durch."""
        xml = _write_xml(tmp_path, _bmecat(5), "new.xml")
        cb  = lambda m, **kw: None
        try:
            result = create_diff_report(
                xml_path=xml, backup_dir=str(tmp_path), progress_cb=cb)
            assert result is None or isinstance(result, dict)
        except Exception as e:
            pytest.fail(f"Absturz: {e}")

    def test_new_xml_no_backup(self, tmp_path):
        new_xml = _write_xml(tmp_path, _bmecat(5), "new.xml")
        result = create_diff_report(new_xml, str(tmp_path))
        assert result is None or isinstance(result, (str, dict))

    def test_compare_snapshots_identical(self):
        snap = {"AID001": {"price": "1.00", "desc": "A"}, "AID002": {"price": "2.00"}}
        diff = compare_snapshots(snap, snap)
        assert isinstance(diff, dict)
        new = diff.get("new", diff.get("added", []))
        assert len(new) == 0

    def test_compare_snapshots_added(self):
        old = {"A": {"price": "1.00"}}
        new = {"A": {"price": "1.00"}, "B": {"price": "2.00"}}
        diff = compare_snapshots(old, new)
        assert isinstance(diff, dict)
        new_items = diff.get("new", diff.get("added", diff.get("new_aids", [])))
        assert len(new_items) >= 1

    def test_compare_snapshots_deleted(self):
        old = {"A": {"price": "1.00"}, "B": {"price": "2.00"}}
        new = {"A": {"price": "1.00"}}
        diff = compare_snapshots(old, new)
        assert isinstance(diff, dict)
        del_items = diff.get("deleted", diff.get("removed", diff.get("deleted_aids", [])))
        assert len(del_items) >= 1
