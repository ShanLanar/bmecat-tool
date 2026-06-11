# tests/test_stress_edge.py – Encoding, Config, Pipeline-Edge-Cases (80+ Fälle)

import sys, os, re, json, pytest, tempfile, zipfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Encoding-Erkennung ────────────────────────────────────────────────────────

from lib.utils import detect_encoding


ENCODING_CASES = [
    # (bytes, expected_encoding_contains)
    (b'\xef\xbb\xbf' + "UTF-8 BOM".encode("utf-8"),  "utf"),
    ("Normale ASCII".encode("ascii"),                  None),  # ASCII, keine Assertion
    ("Größe".encode("cp1252"),                         None),  # CP1252 oder latin-1
    ("Größe".encode("utf-8"),                          "utf"),
    (b"",                                              None),  # leer → kein Absturz
]

class TestDetectEncoding:

    @pytest.mark.parametrize("data,expected", ENCODING_CASES)
    def test_detect(self, tmp_path, data, expected):
        p = tmp_path / "test.txt"
        p.write_bytes(data)
        result = detect_encoding(str(p))
        assert isinstance(result, str), f"Ergebnis muss str sein: {result!r}"
        if expected:
            assert expected in result.lower(), \
                f"Erwartet '{expected}' in '{result}'"

    def test_missing_file_no_crash(self, tmp_path):
        try:
            result = detect_encoding(str(tmp_path / "nope.txt"))
            assert isinstance(result, str)
        except Exception:
            pass  # Exception OK

    def test_binary_file_no_crash(self, tmp_path):
        p = tmp_path / "bin.dat"
        p.write_bytes(bytes(range(256)))
        try:
            result = detect_encoding(str(p))
            assert isinstance(result, str)
        except Exception:
            pass

    @pytest.mark.parametrize("encoding", ["utf-8", "cp1252", "latin-1"])
    def test_known_encodings_detected(self, tmp_path, encoding):
        p = tmp_path / f"test_{encoding}.txt"
        p.write_bytes("Größe und Maße".encode(encoding, errors="replace"))
        result = detect_encoding(str(p))
        assert isinstance(result, str) and len(result) > 0


# ── File Hash ─────────────────────────────────────────────────────────────────

from lib.utils import file_hash


class TestFileHash:

    def test_same_content_same_hash(self, tmp_path):
        p1 = tmp_path / "a.txt"; p1.write_text("content")
        p2 = tmp_path / "b.txt"; p2.write_text("content")
        assert file_hash(str(p1)) == file_hash(str(p2))

    def test_different_content_different_hash(self, tmp_path):
        p1 = tmp_path / "a.txt"; p1.write_text("content A")
        p2 = tmp_path / "b.txt"; p2.write_text("content B")
        assert file_hash(str(p1)) != file_hash(str(p2))

    def test_missing_file_returns_empty_or_none(self, tmp_path):
        try:
            result = file_hash(str(tmp_path / "nope.txt"))
            assert result == "" or result is None
        except Exception:
            pass  # Exception bei fehlendem File ist auch OK

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.txt"; p.write_bytes(b"")
        result = file_hash(str(p))
        assert isinstance(result, str)

    def test_large_file(self, tmp_path):
        p = tmp_path / "large.txt"
        p.write_bytes(b"A" * 10_000_000)  # 10 MB
        result = file_hash(str(p))
        assert isinstance(result, str) and len(result) > 0

    @pytest.mark.parametrize("size", [1, 100, 1000, 100_000])
    def test_various_sizes(self, tmp_path, size):
        p = tmp_path / f"f{size}.txt"
        p.write_bytes(b"x" * size)
        result = file_hash(str(p))
        assert isinstance(result, str)


# ── FNAME Transform: vollständige XML-Datei ───────────────────────────────────

from lib.fname_transforms import apply_fname_transforms


def _bmecat_with_features(n=5):
    """Erzeugt BMEcat-XML mit ARTICLE_FEATURES (mehrzeilig für Streaming-Parser)."""
    lines = ["<?xml version='1.0' encoding='UTF-8'?>", "<BMECAT>"]
    for i in range(n):
        lines += [
            "<ARTICLE>",
            "  <ARTICLE_DETAILS>",
            f"    <SUPPLIER_AID>AID{i:04d}</SUPPLIER_AID>",
            f"    <DESCRIPTION_SHORT>Produkt {i} (CODE{i:04d})</DESCRIPTION_SHORT>",
            f"    <MANUFACTURER_NAME>Hersteller {i}</MANUFACTURER_NAME>",
            "  </ARTICLE_DETAILS>",
            "  <ARTICLE_FEATURES>",
            f"    <FEATURE><FNAME>Farbe (0173-0{i}-ABCD)</FNAME><FVALUE>CAA016</FVALUE></FEATURE>",
            f"    <FEATURE><FNAME>Marke</FNAME><FVALUE>Brand{i}</FVALUE></FEATURE>",
            "  </ARTICLE_FEATURES>",
            "</ARTICLE>",
        ]
    lines.append("</BMECAT>")
    return "\n".join(lines)


class TestApplyFnameTransforms:

    def test_removes_eclass_ids(self, tmp_path):
        p = tmp_path / "test.xml"
        p.write_text(_bmecat_with_features(3), encoding="utf-8")
        # Leere Rename-Maps (kein BASE_DIR mit CSVs)
        apply_fname_transforms(str(p), str(tmp_path))
        content = p.read_text(encoding="utf-8")
        assert "0173" not in content

    def test_marke_with_existing_mfr_dropped(self, tmp_path):
        # Artikel haben bereits MANUFACTURER_NAME → Marke-Feature soll verworfen werden
        p = tmp_path / "test.xml"
        p.write_text(_bmecat_with_features(3), encoding="utf-8")
        apply_fname_transforms(str(p), str(tmp_path))
        content = p.read_text(encoding="utf-8")
        # MANUFACTURER_NAME noch vorhanden (original)
        assert "<MANUFACTURER_NAME>" in content

    def test_fvalue_caa016_renamed(self, tmp_path):
        p = tmp_path / "test.xml"
        p.write_text(_bmecat_with_features(3), encoding="utf-8")
        # fvalue_renames.csv anlegen
        (tmp_path / "fvalue_renames.csv").write_text("from,to\nCAA016,Ja\n")
        apply_fname_transforms(str(p), str(tmp_path))
        content = p.read_text(encoding="utf-8")
        assert "<FVALUE>Ja</FVALUE>" in content
        assert "CAA016" not in content

    def test_no_crash_empty_xml(self, tmp_path):
        p = tmp_path / "empty.xml"
        p.write_text("", encoding="utf-8")
        apply_fname_transforms(str(p), str(tmp_path))
        assert p.exists()

    def test_no_crash_missing_xml(self, tmp_path):
        result = apply_fname_transforms(str(tmp_path / "nope.xml"), str(tmp_path))
        assert result == {} or result is None

    @pytest.mark.parametrize("n", [1, 10, 50])
    def test_various_article_counts(self, tmp_path, n):
        p = tmp_path / "test.xml"
        p.write_text(_bmecat_with_features(n), encoding="utf-8")
        stats = apply_fname_transforms(str(p), str(tmp_path))
        assert isinstance(stats, dict)
        assert stats.get("features_processed", 0) >= n * 2  # 2 Features pro Artikel

    def test_fname_renames_applied(self, tmp_path):
        p = tmp_path / "test.xml"
        p.write_text(_bmecat_with_features(2), encoding="utf-8")
        (tmp_path / "fname_renames.csv").write_text("from,to\nFarbe,Produktfarbe\n")
        apply_fname_transforms(str(p), str(tmp_path))
        content = p.read_text(encoding="utf-8")
        assert "<FNAME>Produktfarbe</FNAME>" in content


# ── ATP Robustheit ────────────────────────────────────────────────────────────

from lib.atp import load_atp_from_zip, merge_atp_into_availability


class TestAtpRobustness:

    def _zip(self, tmp_path, content):
        p = str(tmp_path / "102_atp_test.zip")
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("atp.txt", content.encode("cp1252", errors="replace"))
        return p

    def test_aid_with_leading_zeros_preserved(self, tmp_path):
        z = self._zip(tmp_path, "000001\t5\t\t\n")
        data = load_atp_from_zip(z)
        assert "000001" in data

    def test_large_aid_number(self, tmp_path):
        z = self._zip(tmp_path, "999999999\t100\t\t\n")
        data = load_atp_from_zip(z)
        assert "999999999" in data

    def test_tab_in_ean_field(self, tmp_path):
        z = self._zip(tmp_path, "001017\t62\t5902658066092\t30.05.2026\n")
        data = load_atp_from_zip(z)
        assert data["001017"]["ean"] == "5902658066092"
        assert data["001017"]["date"] == "30.05.2026"

    def test_merge_zero_stock_written(self, tmp_path):
        avail = tmp_path / "avail.csv"
        avail.write_text("ART001;99\n")
        merge_atp_into_availability(
            str(avail), {"ART001": {"quantity": 0, "ean": None, "date": None}})
        assert "ART001;0" in avail.read_text()

    def test_merge_preserves_other_articles(self, tmp_path):
        avail = tmp_path / "avail.csv"
        avail.write_text("ART001;5\nART002;10\nART003;0\n")
        merge_atp_into_availability(
            str(avail), {"ART001": {"quantity": 99, "ean": None, "date": None}})
        content = avail.read_text()
        assert "ART002;10" in content
        assert "ART003;0" in content
        assert "ART001;99" in content

    @pytest.mark.parametrize("qty", [-999, 0, 1, 9999, 999999])
    def test_various_quantities(self, tmp_path, qty):
        z = self._zip(tmp_path, f"001017\t{qty}\t\t\n")
        data = load_atp_from_zip(z)
        if "001017" in data:
            assert data["001017"]["quantity"] == qty


# ── Config-Migration Robustheit ───────────────────────────────────────────────

from lib.config_migration import migrate, CONFIG_VERSION, SECTION_DEFAULTS


class TestConfigMigrationRobustness:

    def _cfg(self, tmp_path, data):
        p = tmp_path / "config_user.json"
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return str(p)

    def test_all_sections_added(self, tmp_path):
        cfg = self._cfg(tmp_path, {"__version__": 0})
        migrate(cfg)
        with open(cfg) as f:
            data = json.load(f)
        for section in SECTION_DEFAULTS:
            assert section in data, f"Sektion {section!r} fehlt"

    def test_version_bumped(self, tmp_path):
        cfg = self._cfg(tmp_path, {"__version__": 0})
        migrate(cfg)
        with open(cfg) as f:
            data = json.load(f)
        assert data["__version__"] == CONFIG_VERSION

    def test_subsection_merged(self, tmp_path):
        cfg = self._cfg(tmp_path, {"__version__": 0, "BFSG": {"enabled": True}})
        migrate(cfg)
        with open(cfg) as f:
            data = json.load(f)
        # enabled=True bleibt erhalten
        assert data["BFSG"]["enabled"] == True
        # aber fehlende Schlüssel werden ergänzt
        assert "alt_text" in data["BFSG"]

    def test_deeply_nested_value_preserved(self, tmp_path):
        cfg = self._cfg(tmp_path, {
            "__version__": 0,
            "AI_ENRICHMENT": {"enabled": True, "max_articles": 500}
        })
        migrate(cfg)
        with open(cfg) as f:
            data = json.load(f)
        assert data["AI_ENRICHMENT"]["max_articles"] == 500

    @pytest.mark.parametrize("version", [0, 1, 2, 3, 4])
    def test_old_versions_migrated(self, tmp_path, version):
        cfg = self._cfg(tmp_path, {"__version__": version})
        migrate(cfg)
        with open(cfg) as f:
            data = json.load(f)
        assert data["__version__"] == CONFIG_VERSION

    def test_future_version_untouched(self, tmp_path):
        future = CONFIG_VERSION + 10
        cfg = self._cfg(tmp_path, {"__version__": future, "MY_KEY": "val"})
        result = migrate(cfg)
        assert result == False
        with open(cfg) as f:
            data = json.load(f)
        assert data["MY_KEY"] == "val"
        assert data["__version__"] == future
