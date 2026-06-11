# tests/test_category_check.py

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.category_check import (
    load_known_categories, extract_categories_from_xml, check_new_categories
)


def _write_csv(tmp_path, rows):
    p = tmp_path / "custom_categories.csv"
    p.write_bytes(
        ("category_code;original_name;original_parent;ranking;original_online;"
         "product_category_code;name;parent;online\n" +
         "\n".join(rows)).encode("cp1252")
    )
    return str(tmp_path)


def _write_xml(tmp_path, name, structures):
    """Baut eine Mini-BMEcat-XML mit CATALOG_STRUCTURE-Einträgen."""
    structs = "\n".join(
        f"<CATALOG_STRUCTURE type='leaf'>"
        f"<GROUP_ID>{gid}</GROUP_ID>"
        f"<GROUP_NAME>{gname}</GROUP_NAME>"
        f"<PARENT_ID>{par}</PARENT_ID>"
        f"</CATALOG_STRUCTURE>"
        for gid, gname, par in structures
    )
    xml = (
        f"<BMECAT><HEADER></HEADER>"
        f"<T_NEW_CATALOG>{structs}"
        f"<ARTICLE><SUPPLIER_AID>A1</SUPPLIER_AID></ARTICLE>"
        f"</T_NEW_CATALOG></BMECAT>"
    )
    p = tmp_path / name
    p.write_text(xml, encoding="utf-8")
    return str(p)


class TestLoadKnownCategories:

    def test_loads_prefixed_codes(self, tmp_path):
        _write_csv(tmp_path, [
            "BRG64640;Anwalt;BRG1;0;1;;Notariatsbedarf;BRG1;1",
            "SOC904002;;;0;;;Sofas;SOC904000;1",
            "NDW1;Katalog;;1;1;;Katalog;;1",
        ])
        known = load_known_categories(str(tmp_path))
        assert "BRG64640" in known
        assert "SOC904002" in known
        assert "NDW1" in known

    def test_numeric_codes_included(self, tmp_path):
        _write_csv(tmp_path, ["1;Zentralshop;;0;1;;Zentralshop;;1"])
        known = load_known_categories(str(tmp_path))
        assert "1" in known

    def test_missing_file_returns_empty(self, tmp_path):
        assert load_known_categories(str(tmp_path)) == set()


class TestExtractCategoriesFromXml:

    def test_basic_extraction(self, tmp_path):
        xml = _write_xml(tmp_path, "test.xml", [
            ("64640", "Anwalt & Notariatsbedarf", "1"),
            ("65197", "Formulare", "64640"),
        ])
        cats = extract_categories_from_xml(xml, "BRG")
        codes = [c["code"] for c in cats]
        assert "BRG64640" in codes
        assert "BRG65197" in codes

    def test_prefix_applied(self, tmp_path):
        xml = _write_xml(tmp_path, "test.xml", [("904002", "Sofas", "904000")])
        cats = extract_categories_from_xml(xml, "SOC")
        assert cats[0]["code"] == "SOC904002"

    def test_alphanumeric_id(self, tmp_path):
        xml = _write_xml(tmp_path, "test.xml", [("BE", "Bauelemente", "1")])
        cats = extract_categories_from_xml(xml, "NDW")
        assert cats[0]["code"] == "NDWBE"

    def test_name_and_parent_extracted(self, tmp_path):
        xml = _write_xml(tmp_path, "test.xml", [("64640", "Notariat", "1")])
        cats = extract_categories_from_xml(xml, "BRG")
        assert cats[0]["name"] == "Notariat"
        assert cats[0]["parent_id"] == "1"

    def test_missing_file_returns_empty(self, tmp_path):
        assert extract_categories_from_xml(str(tmp_path / "nope.xml"), "BRG") == []


class TestCheckNewCategories:

    def test_known_category_not_reported(self, tmp_path):
        _write_csv(tmp_path, ["BRG64640;Anwalt;BRG1;0;1;;Notariatsbedarf;BRG1;1"])
        xml = _write_xml(tmp_path, "test.xml", [("64640", "Anwalt", "1")])
        new = check_new_categories(xml, "BRG", str(tmp_path), "Büroring")
        assert new == []

    def test_new_category_detected(self, tmp_path):
        _write_csv(tmp_path, ["BRG64640;Anwalt;BRG1;0;1;;Notariatsbedarf;BRG1;1"])
        xml = _write_xml(tmp_path, "test.xml", [
            ("64640", "Anwalt", "1"),
            ("99999", "Neue Kategorie", "1"),  # neu!
        ])
        new = check_new_categories(xml, "BRG", str(tmp_path), "Büroring")
        assert len(new) == 1
        assert new[0]["code"] == "BRG99999"
        assert new[0]["name"] == "Neue Kategorie"

    def test_case_insensitive_match(self, tmp_path):
        _write_csv(tmp_path, ["brg64640;Anwalt;brg1;0;1;;test;brg1;1"])
        xml = _write_xml(tmp_path, "test.xml", [("64640", "Anwalt", "1")])
        new = check_new_categories(xml, "BRG", str(tmp_path), "Büroring")
        assert new == []   # brg64640 == BRG64640 case-insensitiv

    def test_log_messages_produced(self, tmp_path):
        _write_csv(tmp_path, [])
        xml = _write_xml(tmp_path, "test.xml", [("99999", "Neu", "1")])
        messages = []
        check_new_categories(xml, "BRG", str(tmp_path), "Büroring",
                              progress_cb=lambda m, **kw: messages.append(m))
        assert any("BRG99999" in m for m in messages)
        assert any("⚠" in m or "neu" in m.lower() for m in messages)
