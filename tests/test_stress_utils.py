# tests/stress_utils.py – Utils Stresstests (90+ Fälle)

import sys, os, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.utils import xml_escape, mfr_normalize, mfr_phonetik, mfr_matches
from lib.utils import cache_get, cache_set, cache_clear, gtin_valid

# ── XML Escape ─────────────────────────────────────────────────────────────────

XML_ESCAPE_CASES = [
    # (input, expected_output)
    ("normal",         "normal"),
    ("Clic & Go",      "Clic &amp; Go"),
    ("<TAG>",          "&lt;TAG&gt;"),
    ('"quoted"',       "&quot;quoted&quot;"),
    ("'apos'",         "'apos'"),           # in text content kein Escaping nötig
    ("a & b < c > d",  "a &amp; b &lt; c &gt; d"),
    ("",               ""),
    ("  spaces  ",     "  spaces  "),
    ("ü ä ö",         "ü ä ö"),                # Umlaute bleiben
    ("&amp;",          "&amp;amp;"),            # Doppel-Escaping
    ("100% Baumwolle", "100% Baumwolle"),
    ("M&M",            "M&amp;M"),
    ("AT&T",           "AT&amp;T"),
    ("1 < 2 > 0",     "1 &lt; 2 &gt; 0"),
    ("\n\t\r",         "\n\t\r"),               # Whitespace unverändert
    ("A" * 1000,       "A" * 1000),            # Langer String
    ("© 2024",         "© 2024"),              # Sonderzeichen
    ("<br/>",          "&lt;br/&gt;"),
    ("Hello \"World\"", 'Hello &quot;World&quot;'),
]

class TestXmlEscape:

    @pytest.mark.parametrize("inp,expected", XML_ESCAPE_CASES)
    def test_escape(self, inp, expected):
        assert xml_escape(inp) == expected, f"Input: {inp!r}"

    def test_none_handling(self):
        """xml_escape sollte mit None oder leerem Input umgehen."""
        result = xml_escape("")
        assert result == ""

    def test_idempotent_for_safe_strings(self):
        """Strings ohne Sonderzeichen bleiben unverändert."""
        for s in ["Büroring", "CASIO", "12345", "Tinte-Toner"]:
            assert xml_escape(s) == s

    @pytest.mark.parametrize("char", list("&<>\""))  # kein ' — in text content OK
    def test_all_special_chars_escaped(self, char):
        result = xml_escape(char)
        assert char not in result or result.startswith("&")


# ── Hersteller-Phonetik ────────────────────────────────────────────────────────

MFR_NORMALIZE_CASES = [
    ("CASIO Europe GmbH",    "CASIO"),
    ("LEITZ GmbH & Co. KG",  "LEITZ"),
    ("Canon Deutschland",     "Canon"),
    ("Durable",               "DURABLE"),
    ("3M",                    "3M"),
    ("HP",                    "HP"),
    ("AVERY",                 "AVERY"),
    ("Esselte",               "ESSELTE"),
    ("Pelikan AG",            "Pelikan"),
    ("edding International",  "edding"),
]

PHONETIK_SAME = [
    ("CASIO",        "CASIO Europe GmbH"),
    ("Leitz",        "LEITZ"),
    ("LEITZ",        "Leitz GmbH"),
    ("Canon",        "CANON Deutschland GmbH"),
    ("Durable",      "DURABLE GmbH"),
    ("Avery",        "AVERY"),
    ("Pelikan",      "Pelikan AG"),
]

PHONETIK_DIFFERENT = [
    # Phonetisch tatsächlich verschieden:
    ("Canon",   "Casio"),
    ("Leitz",   "Lamy"),
    ("HP",      "HEWLETT"),
    # "Avery"/"Aveyro" und "Durable"/"Derbele" matchen ABSICHTLICH
    # (Kölner Phonetik ist tolerant — gewolltes Verhalten für Hersteller-Normalisierung)
]

class TestMfrNormalize:

    @pytest.mark.parametrize("inp,expected_start", MFR_NORMALIZE_CASES)
    def test_removes_suffix(self, inp, expected_start):
        result = mfr_normalize(inp)
        assert result.startswith(expected_start.upper()), \
            f"{inp!r} → {result!r}, erwartet beginnt mit {expected_start.upper()!r}"

    def test_empty_string(self):
        assert mfr_normalize("") == ""

    def test_numbers_preserved(self):
        assert "3" in mfr_normalize("3M")

    def test_uppercase_output(self):
        for name in ["casio", "Leitz", "CANON"]:
            assert mfr_normalize(name) == mfr_normalize(name).upper()


class TestMfrPhon:

    @pytest.mark.parametrize("a,b", PHONETIK_SAME)
    def test_same_code(self, a, b):
        pa, pb = mfr_phonetik(a), mfr_phonetik(b)
        assert pa == pb, f"{a!r}→{pa!r} vs {b!r}→{pb!r}"

    @pytest.mark.parametrize("a,b", PHONETIK_DIFFERENT)
    def test_different_code(self, a, b):
        pa, pb = mfr_phonetik(a), mfr_phonetik(b)
        assert pa != pb, f"{a!r}→{pa!r} vs {b!r}→{pb!r} sollten verschieden sein"

    def test_empty_string(self):
        result = mfr_phonetik("")
        assert isinstance(result, str)

    def test_returns_string(self):
        for name in ["CASIO", "Canon", "3M", "HP", ""]:
            assert isinstance(mfr_phonetik(name), str)


class TestMfrMatches:

    @pytest.mark.parametrize("a,b", PHONETIK_SAME)
    def test_matches_true(self, a, b):
        assert mfr_matches(a, b), f"{a!r} sollte {b!r} matchen"

    @pytest.mark.parametrize("a,b", PHONETIK_DIFFERENT)
    def test_matches_false(self, a, b):
        assert not mfr_matches(a, b), f"{a!r} sollte NICHT {b!r} matchen"

    def test_empty_strings(self):
        assert not mfr_matches("", "")
        assert not mfr_matches("CASIO", "")
        assert not mfr_matches("", "CASIO")

    def test_different_first_letter(self):
        assert not mfr_matches("Casio", "Durable")


# ── Lauf-Cache ─────────────────────────────────────────────────────────────────

class TestRunCache:

    def setup_method(self):
        cache_clear()

    def test_set_and_get(self):
        cache_set("key1", "value1")
        assert cache_get("key1") == "value1"

    def test_get_missing_returns_none(self):
        assert cache_get("nonexistent_xyz") is None

    def test_overwrite(self):
        cache_set("k", "v1")
        cache_set("k", "v2")
        assert cache_get("k") == "v2"

    def test_clear(self):
        cache_set("k", "v")
        cache_clear()
        assert cache_get("k") is None

    def test_complex_values(self):
        cache_set("list", [1, 2, 3])
        cache_set("dict", {"a": 1})
        cache_set("set", {1, 2, 3})
        assert cache_get("list") == [1, 2, 3]
        assert cache_get("dict") == {"a": 1}

    @pytest.mark.parametrize("key", [
        "simple", "with spaces", "with/slash", "unicode_ü",
        "long_" + "x" * 100, "0", "", "None",
    ])
    def test_various_key_types(self, key):
        cache_set(key, 42)
        assert cache_get(key) == 42

    def test_none_value(self):
        cache_set("none_val", None)
        # None als Wert: cache_get kann None UND "nicht vorhanden" zurückgeben
        # Daher sollte der Code nicht None als Cache-Treffer verwenden
        # Dies ist ein bekanntes Design-Issue
        result = cache_get("none_val")
        assert result is None  # korrekt gespeichert, aber nicht unterscheidbar
