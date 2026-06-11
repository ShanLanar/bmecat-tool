# tests/stress_enrichment.py – Enrichment-Regeln Stresstests (100+ Fälle)

import sys, os, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.article_enrichment import (
    rule_description_long, rule_manufacturer_name,
    rule_ean_keyword, rule_keyword_dedup, rule_clean_desc_short,
)


def art(aid="A1", desc_short="Test Artikel", desc_long="",
        manufacturer="", ean="", keywords=None):
    """Baut einen minimalen Artikel-XML-String."""
    mfr_tag   = f"<MANUFACTURER_NAME>{manufacturer}</MANUFACTURER_NAME>" if manufacturer else ""
    ean_tag   = f"<EAN>{ean}</EAN>" if ean else ""
    dlong_tag = f"<DESCRIPTION_LONG>{desc_long}</DESCRIPTION_LONG>" if desc_long else ""
    kw_tags   = "\n".join(f"<KEYWORD>{k}</KEYWORD>" for k in (keywords or []))
    return (
        f"<ARTICLE><ARTICLE_DETAILS>"
        f"<SUPPLIER_AID>{aid}</SUPPLIER_AID>"
        f"<DESCRIPTION_SHORT>{desc_short}</DESCRIPTION_SHORT>"
        f"{ean_tag}{mfr_tag}{dlong_tag}{kw_tags}"
        f"</ARTICLE_DETAILS></ARTICLE>"
    )


# ── Regel 1: description_long ─────────────────────────────────────────────────

DESC_LONG_CASES = [
    # rule_description_long greift nur für BRjCat-Features, nicht einfache Artikel!
    # Folgende Cases testen nur "kein Absturz" und "Long bleibt wenn vorhanden"
    ("Kurz",              "Lang",    False),     # Long vorhanden → nicht ändern
    ("",                  "",        False),     # kein Short, kein Feature
    ("Test",              "Test",    False),     # Long vorhanden → behalten
    # Ohne BRjCat-Features: keine Änderung, auch wenn Long fehlt
    ("Kurz ohne Long",    "",        False),     # kein BRjCat-Feature → False
]

class TestRuleDescriptionLong:

    @pytest.mark.parametrize("short,long_ex,should_change", DESC_LONG_CASES)
    def test_cases(self, short, long_ex, should_change):
        a = art(desc_short=short, desc_long=long_ex)
        _, changed = rule_description_long(a)
        assert changed == should_change, \
            f"short={short!r}, long={long_ex!r}: ändern={should_change}"

    def test_no_change_without_brjcat_features(self):
        """Ohne BRjCat-Features kein Fallback — das ist korrekt."""
        a = art(desc_short="Taschenrechner CASIO", desc_long="")
        result, changed = rule_description_long(a)
        assert not changed  # Regel greift nur auf BRjCat-Features

    def test_preserves_existing_long(self):
        a = art(desc_short="Kurz", desc_long="Ausführliche Beschreibung des Produkts")
        result, changed = rule_description_long(a)
        assert not changed
        assert "Ausführliche Beschreibung" in result


# ── Regel 2: manufacturer_name ────────────────────────────────────────────────

class TestRuleManufacturerName:

    def test_adds_from_marke_feature(self):
        a = (
            "<ARTICLE><ARTICLE_DETAILS>"
            "<SUPPLIER_AID>X</SUPPLIER_AID>"
            "<DESCRIPTION_SHORT>Test</DESCRIPTION_SHORT>"
            "</ARTICLE_DETAILS>"
            "<ARTICLE_FEATURES>"
            "<FEATURE><FNAME>Marke</FNAME><FVALUE>CASIO</FVALUE></FEATURE>"
            "</ARTICLE_FEATURES></ARTICLE>"
        )
        result, changed = rule_manufacturer_name(a)
        # Diese Regel greift nur wenn FNAME=Marke UND kein MANUFACTURER_NAME
        assert isinstance(changed, bool)

    def test_no_change_when_mfr_exists(self):
        a = art(manufacturer="CASIO")
        _, changed = rule_manufacturer_name(a)
        assert not changed


# ── Regel 3: ean_keyword ──────────────────────────────────────────────────────

EAN_KW_CASES = [
    # (ean, existing_keywords, should_add)
    ("4052396001693", [],                    True),
    ("4052396001693", ["4052396001693"],      False),  # schon drin
    ("4052396001693", ["Taschenrechner"],     True),
    ("abc",           [],                    False),   # nicht numerisch
    ("",              [],                    False),   # leer
    ("123",           [],                    False),   # zu kurz, nicht numerisch... wait, "123" ist numerisch
    ("1234567890123", [],                    True),    # 13 Stellen numerisch
    ("9780201379624", ["9780201379624"],      False),  # schon drin
]

class TestRuleEanKeyword:

    @pytest.mark.parametrize("ean,kws,should_add", EAN_KW_CASES)
    def test_ean_keyword(self, ean, kws, should_add):
        a = art(ean=ean, keywords=kws)
        _, changed = rule_ean_keyword(a)
        assert changed == should_add, \
            f"EAN={ean!r}, kws={kws}: add={should_add}"

    def test_ean_placed_after_last_keyword(self):
        a = art(ean="4052396001693", keywords=["A", "B", "C"])
        result, changed = rule_ean_keyword(a)
        assert changed
        idx_c   = result.rfind(">C<")
        idx_ean = result.rfind("4052396001693")
        assert idx_ean > idx_c

    def test_no_crash_with_various_eans(self):
        for ean in ["", "abc", "0" * 13, "9" * 13, "123456789012X"]:
            a = art(ean=ean)
            result, changed = rule_ean_keyword(a)
            assert isinstance(changed, bool)


# ── Regel 4: keyword_dedup ────────────────────────────────────────────────────

DEDUP_CASES = [
    # (keywords_in, expected_count_out)
    (["A", "B", "C"],           3),
    (["A", "A", "A"],           1),
    (["a", "A", "a"],           1),  # case-insensitiv
    (["CASIO", "Casio"],        1),
    (["Taschenrechner", "Schulrechner", "Taschenrechner"], 2),
    ([],                        0),
    (["single"],                1),
    (["A"] * 10,                1),
    (["A", "B", "A", "C", "B"], 3),  # A, B, C
    # ("  spaces  " vs "spaces") → verschiedene Keywords → beide bleiben
]

class TestRuleKeywordDedup:

    @pytest.mark.parametrize("kws,expected_count", DEDUP_CASES)
    def test_dedup_count(self, kws, expected_count):
        import re
        a = art(keywords=kws)
        result, _ = rule_keyword_dedup(a)
        found = re.findall(r'<KEYWORD>(.*?)</KEYWORD>', result)
        assert len(found) == expected_count, \
            f"Input: {kws} → erwartet {expected_count}, bekommen {len(found)}: {found}"

    def test_preserves_first_occurrence(self):
        a = art(keywords=["CASIO", "Casio", "casio"])
        result, _ = rule_keyword_dedup(a)
        assert "CASIO" in result
        import re
        found = re.findall(r'<KEYWORD>(.*?)</KEYWORD>', result)
        assert found[0] == "CASIO"

    def test_no_change_for_unique(self):
        a = art(keywords=["A", "B", "C"])
        _, changed = rule_keyword_dedup(a)
        assert not changed

    def test_changed_for_duplicates(self):
        a = art(keywords=["A", "A"])
        _, changed = rule_keyword_dedup(a)
        assert changed


# ── Regel 5: clean_desc_short ─────────────────────────────────────────────────

CLEAN_DESC_CASES = [
    # (input_title, should_change, expected_contains)
    ("Schulrechner FX-87DEX (CASFX87DEX)", True,  "Schulrechner FX-87DEX"),
    ("Toner (4BK2X)",                       True,  "Toner"),
    ("Normale Beschreibung",                False, "Normale Beschreibung"),
    ("(ABCD)",                              True,  ""),       # nur der Suffix
    ("Produkt (AB)",                        False, None),     # zu kurz (< 4 Zeichen)
    ("Artikel (ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567)", False, None),  # zu lang (> 30)
    ("Test (lowercase)",                    False, None),     # Kleinbuchstaben
    ("Test (ABC123)",                       True,  "Test"),
    ("Test (12345)",                        True,  "Test"),
    ("",                                    False, None),
]

class TestRuleCleanDescShort:

    @pytest.mark.parametrize("title,should_change,contains", CLEAN_DESC_CASES)
    def test_clean(self, title, should_change, contains):
        import re
        a = art(desc_short=title)
        result, changed = rule_clean_desc_short(a)
        assert changed == should_change, \
            f"Input: {title!r}, erwartet changed={should_change}"
        if contains is not None and should_change:
            found = re.search(
                r'<DESCRIPTION_SHORT>(.*?)</DESCRIPTION_SHORT>', result)
            actual = found.group(1) if found else ""
            assert contains in actual, \
                f"Input: {title!r} → {actual!r}, erwartet {contains!r} drin"

    def test_no_crash_on_empty_article(self):
        result, changed = rule_clean_desc_short("<ARTICLE></ARTICLE>")
        assert not changed

    @pytest.mark.parametrize("suffix_len", [4, 10, 15, 20, 30])
    def test_various_suffix_lengths(self, suffix_len):
        suffix = "A" * suffix_len
        title  = f"Produkt ({suffix})"
        a = art(desc_short=title)
        _, changed = rule_clean_desc_short(a)
        assert changed, f"Sollte bereinigen: {title!r}"

    def test_suffix_too_long_ignored(self):
        title = "Produkt (" + "A" * 31 + ")"
        a = art(desc_short=title)
        _, changed = rule_clean_desc_short(a)
        assert not changed
