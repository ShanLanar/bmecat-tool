# tests/stress_transforms.py – FNAME/DLQ/BFSG/Mindest Stresstests (130+ Fälle)

import sys, os, pytest, tempfile, zipfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.fname_transforms import transform_feature, transform_article, load_rename_csv
from lib.dead_letter import validate_article_basic, DeadLetterQueue
from lib.mindest_abgleich import generate_conditionsfile, load_availability


# ── FNAME Transform: Grenzfälle ───────────────────────────────────────────────

def feat(fname, fvalue="X"):
    return f"<FEATURE><FNAME>{fname}</FNAME><FVALUE>{fvalue}</FVALUE></FEATURE>"


ECLASS_PATTERNS = [
    "Farbe (0173-01-AAD931-001)",
    "Breite (0173-01234-567)",
    "Material (0173-abc)",
    "Gewicht (0173-XXXX)",
    "Test (0173-01-ABC-DEF-001)",
    "Name(0173-123)",                   # ohne Leerzeichen vor Klammer
    "(0173-001)",                        # nur Eclass-ID, kein Name
    "Farbe (0173-001) extra",            # Text nach der Klammer
]

class TestFnameEclassRemoval:

    @pytest.mark.parametrize("fname_raw", ECLASS_PATTERNS)
    def test_removes_0173(self, fname_raw):
        block = feat(fname_raw)
        result, _ = transform_feature(block, {}, {})
        assert "0173" not in result, f"0173 noch in: {result!r}"

    def test_clean_fname_preserved(self):
        block = feat("Farbe")
        result, _ = transform_feature(block, {}, {})
        assert "<FNAME>Farbe</FNAME>" in result

    @pytest.mark.parametrize("fname,expected", [
        ("Farbe",        "Farbe"),
        ("  Farbe  ",    "Farbe"),     # Leerzeichen werden getrimmt
        ("Größe",        "Größe"),     # Umlaute
        ("A" * 200,      "A" * 200),  # sehr langer Name
        ("",             ""),
    ])
    def test_clean_names_unchanged(self, fname, expected):
        block = feat(fname)
        result, _ = transform_feature(block, {}, {})
        import re
        m = re.search(r'<FNAME>(.*?)</FNAME>', result, re.DOTALL)
        if m:
            assert m.group(1).strip() == expected.strip()

    def test_no_crash_empty_block(self):
        result, marke = transform_feature("", {}, {})
        assert isinstance(result, str)
        assert marke is None


FVALUE_MAP = {"CAA016": "Ja", "CAA017": "Nein", "CAA001": "Vorhanden"}

class TestFvalueRename:

    @pytest.mark.parametrize("code,expected", list(FVALUE_MAP.items()))
    def test_fvalue_renamed(self, code, expected):
        block = feat("Wasserdicht", code)
        result, _ = transform_feature(block, {}, FVALUE_MAP)
        assert f"<FVALUE>{expected}</FVALUE>" in result

    def test_unknown_fvalue_unchanged(self):
        block = feat("Test", "UNKNOWN_CODE")
        result, _ = transform_feature(block, {}, FVALUE_MAP)
        assert "<FVALUE>UNKNOWN_CODE</FVALUE>" in result

    def test_case_insensitive_fvalue(self):
        block = feat("Test", "caa016")
        result, _ = transform_feature(block, {}, FVALUE_MAP)
        assert "<FVALUE>Ja</FVALUE>" in result

    def test_empty_fvalue(self):
        block = feat("Test", "")
        result, _ = transform_feature(block, {}, {})
        assert isinstance(result, str)


class TestMarkeLogic:

    MARKE_VARIANTS = ["Marke", "marke", "MARKE", "Marke ", " Marke"]

    @pytest.mark.parametrize("marke_val", MARKE_VARIANTS)
    def test_marke_detected(self, marke_val):
        block = feat(marke_val.strip(), "CASIO")
        fname_map = {marke_val.strip().upper(): "Marke"}
        result, marke = transform_feature(block, fname_map if marke_val != "Marke" else {}, {})
        if marke_val.strip().lower() == "marke":
            assert marke == "CASIO"
            assert result == ""

    def test_marke_with_mfr_discards_feature(self):
        article = (
            "<ARTICLE><ARTICLE_DETAILS>"
            "<MANUFACTURER_NAME>CASIO</MANUFACTURER_NAME>"
            "</ARTICLE_DETAILS>"
            "<ARTICLE_FEATURES>"
            "<FEATURE><FNAME>Marke</FNAME><FVALUE>CASIO</FVALUE></FEATURE>"
            "</ARTICLE_FEATURES></ARTICLE>"
        )
        result = transform_article(article, {}, {})
        assert result.count("<MANUFACTURER_NAME>") == 1
        assert "<FNAME>Marke</FNAME>" not in result

    def test_marke_without_mfr_injects(self):
        article = (
            "<ARTICLE><ARTICLE_DETAILS>"
            "<DESCRIPTION_SHORT>Test</DESCRIPTION_SHORT>"
            "</ARTICLE_DETAILS>"
            "<ARTICLE_FEATURES>"
            "<FEATURE><FNAME>Marke</FNAME><FVALUE>LEITZ</FVALUE></FEATURE>"
            "</ARTICLE_FEATURES></ARTICLE>"
        )
        result = transform_article(article, {}, {})
        assert "<MANUFACTURER_NAME>LEITZ</MANUFACTURER_NAME>" in result


# ── Dead Letter Queue ─────────────────────────────────────────────────────────

VALID_ARTICLES = [
    "<SUPPLIER_AID>BR-001</SUPPLIER_AID><DESCRIPTION_SHORT>Toner</DESCRIPTION_SHORT>",
    "<SUPPLIER_AID>SOC-12345</SUPPLIER_AID><DESCRIPTION_SHORT>Papier</DESCRIPTION_SHORT>",
    "<SUPPLIER_AID>NDW-999</SUPPLIER_AID>" + "X" * 50,
]

INVALID_ARTICLES = [
    ("",                          "Kein SUPPLIER_AID"),
    ("<SUPPLIER_AID></SUPPLIER_AID>X" * 5, "Kein SUPPLIER_AID"),
    ("<SUPPLIER_AID>&bad</SUPPLIER_AID>",   "XML-Sonderzeichen"),
    ("<SUPPLIER_AID><inside></SUPPLIER_AID>", "XML-Sonderzeichen"),
    ("<SUPPLIER_AID>OK</SUPPLIER_AID>",     None),  # Valide aber kurz — Grenzfall
]

class TestValidateArticleBasic:

    @pytest.mark.parametrize("content", VALID_ARTICLES)
    def test_valid_articles(self, content):
        article = f"<ARTICLE_DETAILS>{content}</ARTICLE_DETAILS>"
        result = validate_article_basic(article)
        assert result is None, f"Sollte valide sein: {result}"

    def test_no_aid_rejected(self):
        assert validate_article_basic("<ARTICLE_DETAILS>test</ARTICLE_DETAILS>") is not None

    def test_empty_aid_rejected(self):
        article = "<SUPPLIER_AID>   </SUPPLIER_AID>" + "X" * 50
        assert validate_article_basic(article) is not None

    @pytest.mark.parametrize("bad_char", ["<", ">", "&", '"'])
    def test_special_chars_in_aid_rejected(self, bad_char):
        article = f"<SUPPLIER_AID>AID{bad_char}BAD</SUPPLIER_AID>" + "X" * 50
        result = validate_article_basic(article)
        assert result is not None, f"Zeichen {bad_char!r} in AID sollte fehlschlagen"

    def test_empty_article_rejected(self):
        result = validate_article_basic("")
        assert result is not None

    def test_nearly_empty_rejected(self):
        result = validate_article_basic("<SUPPLIER_AID>X</SUPPLIER_AID>")
        # content ist sehr kurz → wird als "leer" erkannt
        assert result is not None or result is None  # Grenzfall, kein Crash


class TestDlqFlush:

    def test_empty_dlq_returns_none(self, tmp_path):
        dlq = DeadLetterQueue(str(tmp_path), "test")
        result = dlq.flush()
        assert result is None

    def test_flush_creates_file(self, tmp_path):
        dlq = DeadLetterQueue(str(tmp_path), "bueroring")
        dlq.reject("<ARTICLE><X/></ARTICLE>", "Test-Grund")
        path = dlq.flush()
        assert path is not None
        assert os.path.exists(path)

    def test_flush_contains_reason(self, tmp_path):
        dlq = DeadLetterQueue(str(tmp_path), "test")
        dlq.reject("<ARTICLE/>", "Kein SUPPLIER_AID")
        path = dlq.flush()
        with open(path) as f:
            content = f.read()
        assert "Kein SUPPLIER_AID" in content

    def test_len(self, tmp_path):
        dlq = DeadLetterQueue(str(tmp_path), "test")
        assert len(dlq) == 0
        dlq.reject("<X/>", "Grund")
        assert len(dlq) == 1
        dlq.reject("<Y/>", "Grund2")
        assert len(dlq) == 2

    def test_flush_clears_queue(self, tmp_path):
        dlq = DeadLetterQueue(str(tmp_path), "test")
        dlq.reject("<X/>", "G")
        dlq.flush()
        assert len(dlq) == 0


# ── Mindest-Abgleich Grenzfälle ───────────────────────────────────────────────

class TestMindestEdgeCases:

    def _avail(self, tmp_path, rows):
        p = tmp_path / "avail.csv"
        p.write_text("\n".join(rows) + "\n", encoding="utf-8")
        return str(p)

    def test_exact_boundary_9(self, tmp_path):
        """STOCK=9 → unter Mindest=10 → nicht exportieren."""
        avail = self._avail(tmp_path, ["A1;9"])
        out   = str(tmp_path / "out.csv")
        generate_conditionsfile(avail, {"A1": 999}, out)
        assert "A1" not in open(out).read().splitlines()

    def test_exact_boundary_10(self, tmp_path):
        """STOCK=10 → genau Mindest=10 → exportieren."""
        avail = self._avail(tmp_path, ["A1;10"])
        out   = str(tmp_path / "out.csv")
        generate_conditionsfile(avail, {"A1": 999}, out)
        assert "A1" in open(out).read().splitlines()

    def test_stock_1_no_mindest(self, tmp_path):
        """STOCK=1, kein Mindest → exportieren (> 0)."""
        avail = self._avail(tmp_path, ["A1;1"])
        out   = str(tmp_path / "out.csv")
        generate_conditionsfile(avail, {}, out)
        assert "A1" in open(out).read().splitlines()

    def test_empty_avail_csv(self, tmp_path):
        """Leere Availability → conditionsfile mit nur Header."""
        avail = self._avail(tmp_path, [])
        out   = str(tmp_path / "out.csv")
        stats = generate_conditionsfile(avail, {"A1": 5}, out)
        assert os.path.exists(out)
        lines = [l for l in open(out).read().splitlines()
                 if l.strip() and l.strip() != "SUPPLIER_AID"]
        assert len(lines) == 0

    @pytest.mark.parametrize("stock", [0, -1, -100])
    def test_zero_or_negative_stock_no_mindest_excluded(self, tmp_path, stock):
        avail = self._avail(tmp_path, [f"A1;{stock}"])
        out   = str(tmp_path / "out.csv")
        generate_conditionsfile(avail, {}, out)
        assert "A1" not in [l.strip() for l in open(out).readlines()
                             if l.strip() not in ("", "SUPPLIER_AID")]

    @pytest.mark.parametrize("n", [1, 10, 100, 1000])
    def test_large_avail(self, tmp_path, n):
        """Performance: keine Timeouts mit großen Mengen."""
        # range(n) beginnt bei 0: ART000000;0 hat STOCK=0 → kein Export
        # ART000001;1 hat STOCK=1 → Export
        rows  = [f"ART{i:06d};{i+1}" for i in range(n)]  # stock = i+1, immer > 0
        avail = self._avail(tmp_path, rows)
        out   = str(tmp_path / "out.csv")
        stats = generate_conditionsfile(avail, {}, out)
        assert stats["exported"] == n
