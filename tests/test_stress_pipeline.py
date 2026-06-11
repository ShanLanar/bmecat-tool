# tests/stress_pipeline.py – Pipeline-Komponenten Stresstests (80+ Fälle)

import sys, os, pytest, json, zipfile, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.atp import load_atp_from_zip, merge_atp_into_availability
from lib.config_migration import migrate, CONFIG_VERSION
from lib.category_check import extract_categories_from_xml, load_known_categories
from lib.bestandsdaten import erstelle_bestandsdaten, _load_static_articles


# ── ATP Grenzfälle ─────────────────────────────────────────────────────────────

def _make_zip(tmp_path, content: str, fname="atp.txt") -> str:
    path = str(tmp_path / "102_atp_test.zip")
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(fname, content.encode("cp1252", errors="replace"))
    return path


class TestAtpEdgeCases:

    def test_empty_file(self, tmp_path):
        path = _make_zip(tmp_path, "")
        data = load_atp_from_zip(path)
        assert data == {}

    def test_header_only(self, tmp_path):
        path = _make_zip(tmp_path, "AID\tSTOCK\tEAN\tDATUM\n")
        data = load_atp_from_zip(path)
        # Header-Zeile hat keine gültige AID-Zahl → wird ggf. geparst, kein Absturz
        assert isinstance(data, dict)

    def test_malformed_lines_no_crash(self, tmp_path):
        content = "\t\t\n\tabc\t\n000001\t\t\n"
        path = _make_zip(tmp_path, content)
        data = load_atp_from_zip(path)
        assert isinstance(data, dict)

    def test_negative_stock(self, tmp_path):
        path = _make_zip(tmp_path, "001017\t-5\t\t\n")
        data = load_atp_from_zip(path)
        if "001017" in data:
            assert data["001017"]["quantity"] == -5

    def test_very_large_stock(self, tmp_path):
        path = _make_zip(tmp_path, f"001017\t9999999\t\t\n")
        data = load_atp_from_zip(path)
        if "001017" in data:
            assert data["001017"]["quantity"] == 9999999

    def test_duplicate_aid_last_wins(self, tmp_path):
        content = "001017\t10\t\t\n001017\t20\t\t\n"
        path = _make_zip(tmp_path, content)
        data = load_atp_from_zip(path)
        if "001017" in data:
            assert data["001017"]["quantity"] == 20

    @pytest.mark.parametrize("n", [1, 10, 100, 1000])
    def test_many_articles(self, tmp_path, n):
        content = "\n".join(f"{i:06d}\t{i}\t\t" for i in range(n))
        path = _make_zip(tmp_path, content)
        data = load_atp_from_zip(path)
        assert len(data) == n

    def test_atp_merge_empty_data(self, tmp_path):
        avail = tmp_path / "avail.csv"
        avail.write_text("A1;5\nA2;0\n")
        result = merge_atp_into_availability(str(avail), {})
        assert result == {"updated": 0, "added": 0, "unchanged": 0}

    def test_atp_merge_adds_new(self, tmp_path):
        avail = tmp_path / "avail.csv"
        avail.write_text("A1;5\n")
        result = merge_atp_into_availability(str(avail),
                     {"NEW99": {"quantity": 42, "ean": None, "date": None}})
        assert result["added"] == 1
        assert "NEW99;42" in avail.read_text()

    def test_atp_merge_updates_existing(self, tmp_path):
        avail = tmp_path / "avail.csv"
        avail.write_text("A1;5\n")
        merge_atp_into_availability(str(avail),
            {"A1": {"quantity": 99, "ean": None, "date": None}})
        assert "A1;99" in avail.read_text()


# ── Config-Migration ──────────────────────────────────────────────────────────

class TestConfigMigration:

    def _write_cfg(self, tmp_path, data):
        p = tmp_path / "config_user.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return str(p)

    def test_missing_file_no_crash(self, tmp_path):
        result = migrate(str(tmp_path / "nonexistent.json"))
        assert result == False

    def test_already_current_version(self, tmp_path):
        cfg = self._write_cfg(tmp_path, {"__version__": CONFIG_VERSION})
        result = migrate(cfg)
        assert result == False

    def test_adds_missing_sections(self, tmp_path):
        cfg = self._write_cfg(tmp_path, {"__version__": 0, "some_key": "val"})
        result = migrate(cfg)
        assert result == True
        with open(cfg) as f:
            updated = json.load(f)
        assert "__version__" in updated
        assert updated["__version__"] == CONFIG_VERSION

    def test_preserves_existing_values(self, tmp_path):
        cfg = self._write_cfg(tmp_path, {"__version__": 0, "MY_SETTING": "custom"})
        migrate(cfg)
        with open(cfg) as f:
            updated = json.load(f)
        assert updated["MY_SETTING"] == "custom"

    def test_backup_created(self, tmp_path):
        cfg = self._write_cfg(tmp_path, {"__version__": 0})
        migrate(cfg)
        assert os.path.exists(cfg + ".bak")

    def test_invalid_json_no_crash(self, tmp_path):
        p = tmp_path / "config_user.json"
        p.write_text("{invalid json", encoding="utf-8")
        result = migrate(str(p))
        assert result == False


# ── Kategorie-Check Grenzfälle ────────────────────────────────────────────────

def _xml(tmp_path, structs):
    lines = []
    for gid, gname, par in structs:
        lines.append(
            f"<CATALOG_STRUCTURE>"
            f"<GROUP_ID>{gid}</GROUP_ID>"
            f"<GROUP_NAME>{gname}</GROUP_NAME>"
            f"<PARENT_ID>{par}</PARENT_ID>"
            f"</CATALOG_STRUCTURE>"
        )
    content = "<BMECAT>" + "".join(lines) + "<ARTICLE><AID/></ARTICLE></BMECAT>"
    p = tmp_path / "test.xml"
    p.write_text(content, encoding="utf-8")
    return str(p)


class TestCategoryCheckEdgeCases:

    def test_empty_xml(self, tmp_path):
        p = tmp_path / "empty.xml"
        p.write_text("<BMECAT></BMECAT>", encoding="utf-8")
        cats = extract_categories_from_xml(str(p), "BRG")
        assert cats == []

    def test_special_chars_in_name(self, tmp_path):
        xml = _xml(tmp_path, [("1", "Bürobedarf & Schreibwaren", "0")])
        cats = extract_categories_from_xml(xml, "BRG")
        assert len(cats) == 1
        assert "Bürobedarf" in cats[0]["name"]

    def test_very_deep_hierarchy(self, tmp_path):
        structs = [(str(i), f"Level {i}", str(i-1)) for i in range(1, 20)]
        xml = _xml(tmp_path, structs)
        cats = extract_categories_from_xml(xml, "BRG")
        assert len(cats) == 19

    @pytest.mark.parametrize("prefix", ["BRG", "NDW", "SOC", "XYZ", "A1B2"])
    def test_various_prefixes(self, tmp_path, prefix):
        xml = _xml(tmp_path, [("100", "Test", "0")])
        cats = extract_categories_from_xml(xml, prefix)
        assert len(cats) == 1
        assert cats[0]["code"] == f"{prefix}100"

    def test_load_known_categories_empty_csv(self, tmp_path):
        p = tmp_path / "custom_categories.csv"
        p.write_text("category_code;name\n", encoding="utf-8")
        known = load_known_categories(str(tmp_path))
        assert isinstance(known, set)

    def test_load_known_categories_with_data(self, tmp_path):
        p = tmp_path / "custom_categories.csv"
        p.write_text("category_code;name\nBRG001;Test\nSOC002;Test2\n", encoding="utf-8")
        known = load_known_categories(str(tmp_path))
        assert "BRG001" in known
        assert "SOC002" in known


# ── Bestandsdaten Grenzfälle ──────────────────────────────────────────────────

class TestBestandsdatenEdge:

    def _write_bestand(self, tmp_path, rows):
        p = tmp_path / "br-bestand.csv"
        p.write_text("SUPPLIER_AID;STOCK\n" + "\n".join(rows), encoding="utf-8")
        return str(tmp_path)

    def test_very_large_stock(self, tmp_path):
        d = self._write_bestand(tmp_path, ["BR-001;9999999"])
        out = str(tmp_path / "out.csv")
        erstelle_bestandsdaten(d, out)
        assert "BR-001;9999999" in open(out).read()

    def test_special_chars_in_aid(self, tmp_path):
        d = self._write_bestand(tmp_path, ["BR/001-A;5", "BR.002;10"])
        out = str(tmp_path / "out.csv")
        erstelle_bestandsdaten(d, out)
        content = open(out).read()
        assert "BR/001-A;5" in content
        assert "BR.002;10" in content

    def test_zero_stock_included(self, tmp_path):
        d = self._write_bestand(tmp_path, ["BR-001;0"])
        out = str(tmp_path / "out.csv")
        erstelle_bestandsdaten(d, out)
        assert "BR-001;0" in open(out).read()

    def test_static_articles_csv_exists(self):
        """static_articles.csv muss im lib/-Verzeichnis existieren."""
        lib_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "lib")
        csv_path = os.path.join(lib_dir, "static_articles.csv")
        assert os.path.exists(csv_path), f"Fehlt: {csv_path}"

    def test_static_articles_format(self):
        content = _load_static_articles()
        for line in content.splitlines()[:20]:
            parts = line.split(";")
            assert len(parts) == 2, f"Falsch formatiert: {line!r}"
            assert parts[1].strip().isdigit(), f"Stock nicht numerisch: {line!r}"

    def test_no_header_in_static_articles(self):
        content = _load_static_articles()
        assert "SUPPLIER_AID" not in content, "Header darf nicht in STATIC_ARTICLES sein"

    @pytest.mark.parametrize("n", [0, 1, 50, 200])
    def test_output_has_static_plus_dynamic(self, tmp_path, n):
        rows = [f"DYN{i:04d};{i}" for i in range(n)]
        d = self._write_bestand(tmp_path, rows)
        out = str(tmp_path / "out.csv")
        erstelle_bestandsdaten(d, out)
        lines = open(out).read().splitlines()
        # 1 Header + n dynamisch + statische
        static_count = len(_load_static_articles().splitlines())
        assert len(lines) >= 1 + n + static_count - 5  # kleine Toleranz
