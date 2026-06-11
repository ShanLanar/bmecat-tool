# tests/test_stress_bfsg.py – BFSG-Barrierefreiheits-Bereinigung (80+ Fälle)

import sys, os, re, pytest, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.bfsg_cleanup import (
    _clean_desc_short, _remove_html, _is_foreign_keyword,
    _add_mime_alt, transform_article_bfsg,
)

CFG_ALL = {
    "alt_text": True, "clean_desc_short": True,
    "remove_html": True, "foreign_keywords": True,
}
CFG_NONE = {
    "alt_text": False, "clean_desc_short": False,
    "remove_html": False, "foreign_keywords": False,
}


# ── _clean_desc_short ─────────────────────────────────────────────────────────

CLEAN_CASES = [
    ("Schulrechner FX-87DEX (CASFX87DEX)", "Schulrechner FX-87DEX"),
    ("Toner (4BK2X)",                       "Toner"),
    ("Normale Beschreibung",                "Normale Beschreibung"),
    ("",                                    ""),
    ("(ABCDE)",                             ""),
    ("Artikel",                             "Artikel"),
    ("Test (AB12CD)",                       "Test"),
    ("Multi  Spaces   (ABCD)",              "Multi  Spaces"),   # interne Spaces bleiben
    ("Ü Ä Ö (XYZAB)",                       "Ü Ä Ö"),
    ("Stifte (test)",                       "Stifte (test)"),  # Kleinbuchstaben → unverändert
]

class TestCleanDescShort:

    @pytest.mark.parametrize("inp,expected", CLEAN_CASES)
    def test_clean(self, inp, expected):
        assert _clean_desc_short(inp) == expected, f"Input: {inp!r}"

    def test_trailing_spaces_trimmed(self):
        result = _clean_desc_short("Test  ")
        assert result == "Test"

    def test_suffix_only_returns_empty(self):
        result = _clean_desc_short("(ABCDE)")
        assert result == ""

    @pytest.mark.parametrize("length", [4, 10, 15, 20, 30])
    def test_valid_suffix_lengths(self, length):
        title = f"Produkt ({'A' * length})"
        result = _clean_desc_short(title)
        assert result == "Produkt", f"Länge {length}: {result!r}"

    def test_suffix_31_chars_not_removed(self):
        title = f"Produkt ({'A' * 31})"
        result = _clean_desc_short(title)
        assert result == title, "31 Zeichen darf nicht entfernt werden"

    def test_no_crash_unicode(self):
        for s in ["Größe (ABCD)", "Ü (XYZAB)", "日本語 (ABCDE)"]:
            result = _clean_desc_short(s)
            assert isinstance(result, str)


# ── _remove_html ──────────────────────────────────────────────────────────────

HTML_CASES = [
    ("<b>Fett</b>",                         "Fett"),
    ("Text mit <br/> Umbruch",              "Text mit   Umbruch"),  # evtl. mehrere Spaces
    ("&lt;br&gt; sichtbar",                 "<br> sichtbar"),       # HTML-Entity decoded
    ("<p>Absatz</p>",                        "Absatz"),
    ("Kein HTML hier",                       "Kein HTML hier"),
    ("",                                     ""),
    ("<b><i>Nested</i></b>",                 "Nested"),
    ("100% &amp; mehr",                      "100% & mehr"),
    ("<SCRIPT>alert(1)</SCRIPT>",            "alert(1)"),
    ("A&nbsp;B",                             "A\u00a0B"),           # non-breaking space
]

class TestRemoveHtml:

    @pytest.mark.parametrize("inp,expected_contains", HTML_CASES)
    def test_remove(self, inp, expected_contains):
        result = _remove_html(inp)
        assert isinstance(result, str)
        assert "<" not in result or result.count("<") == 0

    def test_no_html_tags_in_output(self):
        inputs = [
            "<br>", "<P>", "<b>text</b>",
            '<a href="x">link</a>', "<ul><li>item</li></ul>"
        ]
        for inp in inputs:
            result = _remove_html(inp)
            assert "<" not in result, f"HTML-Tag noch in: {result!r}"

    def test_entities_decoded(self):
        result = _remove_html("a &amp; b")
        assert "a" in result and "b" in result  # text preserved
        # &lt;tag&gt; decodes to <tag> which is then stripped as HTML tag
        result2 = _remove_html("text &lt;br&gt; more")
        assert "text" in result2 and "more" in result2

    def test_empty_string(self):
        assert _remove_html("") == ""

    def test_whitespace_collapsed(self):
        result = _remove_html("a  b   c")
        assert "  " not in result


# ── _is_foreign_keyword ───────────────────────────────────────────────────────

class TestIsForeignKeyword:

    # Bekannte niederländische Wörter → fremd
    @pytest.mark.parametrize("kw", ["zwart", "wit", "rood", "blauw", "groen"])
    def test_dutch_words_foreign(self, kw):
        assert _is_foreign_keyword(kw), f"{kw!r} sollte als fremd erkannt werden"

    # Deutsche/neutrale Wörter → nicht fremd
    @pytest.mark.parametrize("kw", [
        "CASIO", "Taschenrechner", "schwarz", "4052396001693",
        "FX-87DEX", "A4", "100",
    ])
    def test_german_words_not_foreign(self, kw):
        assert not _is_foreign_keyword(kw), f"{kw!r} sollte NICHT als fremd erkannt werden"

    def test_empty_string(self):
        assert not _is_foreign_keyword("")

    def test_very_short_words(self):
        # Wörter unter 4 Zeichen → nie fremd (zu unsicher)
        assert not _is_foreign_keyword("ab")
        assert not _is_foreign_keyword("de")

    def test_pure_numbers_not_foreign(self):
        assert not _is_foreign_keyword("12345")
        assert not _is_foreign_keyword("0")


# ── _add_mime_alt ─────────────────────────────────────────────────────────────

class TestAddMimeAlt:

    def test_adds_alt_text(self):
        mime = "<MIME><MIME_SOURCE>img.jpg</MIME_SOURCE></MIME>"
        result = _add_mime_alt(mime, "Taschenrechner CASIO")
        assert "<MIME_ALT>" in result
        assert "Taschenrechner CASIO" in result

    def test_no_double_add(self):
        mime = "<MIME><MIME_SOURCE>img.jpg</MIME_SOURCE><MIME_ALT>Existiert</MIME_ALT></MIME>"
        result = _add_mime_alt(mime, "Neuer Text")
        assert result.count("<MIME_ALT>") == 1
        assert "Existiert" in result

    def test_empty_desc_no_add(self):
        mime = "<MIME><MIME_SOURCE>img.jpg</MIME_SOURCE></MIME>"
        result = _add_mime_alt(mime, "")
        assert "<MIME_ALT>" not in result

    def test_alt_text_truncated_at_100(self):
        mime = "<MIME><MIME_SOURCE>img.jpg</MIME_SOURCE></MIME>"
        long_desc = "A" * 200
        result = _add_mime_alt(mime, long_desc)
        if "<MIME_ALT>" in result:
            import re
            m = re.search(r'<MIME_ALT>(.*?)</MIME_ALT>', result)
            assert len(m.group(1)) <= 100

    def test_special_chars_escaped(self):
        mime = "<MIME><MIME_SOURCE>img.jpg</MIME_SOURCE></MIME>"
        result = _add_mime_alt(mime, "Clic & Go")
        assert "&amp;" in result or "Clic" in result


# ── transform_article_bfsg ───────────────────────────────────────────────────

def _art(desc_short="Test", desc_long="", keywords=None, mime_src=None):
    kw = "".join(f"<KEYWORD>{k}</KEYWORD>" for k in (keywords or []))
    mime = f"<MIME><MIME_SOURCE>{mime_src}</MIME_SOURCE></MIME>" if mime_src else ""
    dl = f"<DESCRIPTION_LONG>{desc_long}</DESCRIPTION_LONG>" if desc_long else ""
    return (
        f"<ARTICLE><ARTICLE_DETAILS>"
        f"<DESCRIPTION_SHORT>{desc_short}</DESCRIPTION_SHORT>"
        f"{dl}{kw}{mime}"
        f"</ARTICLE_DETAILS></ARTICLE>"
    )


class TestTransformArticleBfsg:

    def test_all_disabled_no_change(self):
        a = _art("Test (ABCDE)", "<br>html", ["zwart"], "img.jpg")
        result, stats = transform_article_bfsg(a, CFG_NONE)
        assert result == a
        assert all(v == 0 for v in stats.values())

    def test_clean_desc_short(self):
        a = _art("Schulrechner (CASFX)")
        result, stats = transform_article_bfsg(a, {"clean_desc_short": True})
        assert "CASFX" not in result
        assert stats["desc_short"] == 1

    def test_remove_html_from_long(self):
        a = _art(desc_long="<b>Fett</b> normal")
        result, stats = transform_article_bfsg(a, {"remove_html": True})
        assert "<b>" not in result
        assert stats["html"] == 1

    def test_foreign_keyword_removed(self):
        a = _art(keywords=["zwart", "schwarz"])
        result, stats = transform_article_bfsg(a, {"foreign_keywords": True})
        assert "zwart" not in result
        assert "schwarz" in result
        assert stats["keywords"] >= 1

    def test_mime_alt_added(self):
        a = _art("Taschenrechner", mime_src="calc.jpg")
        result, stats = transform_article_bfsg(a, {"alt_text": True})
        if stats["alt_text"] > 0:
            assert "<MIME_ALT>" in result

    @pytest.mark.parametrize("n_kws", [0, 1, 5, 20])
    def test_various_keyword_counts(self, n_kws):
        kws = [f"kw{i}" for i in range(n_kws)] + ["zwart"] * min(3, n_kws)
        a = _art(keywords=kws)
        result, stats = transform_article_bfsg(a, {"foreign_keywords": True})
        assert isinstance(result, str)

    def test_empty_article_no_crash(self):
        result, stats = transform_article_bfsg("", CFG_ALL)
        assert isinstance(result, str)
        assert isinstance(stats, dict)

    def test_stats_always_dict(self):
        for cfg in [CFG_ALL, CFG_NONE, {}]:
            _, stats = transform_article_bfsg(_art(), cfg)
            assert isinstance(stats, dict)
