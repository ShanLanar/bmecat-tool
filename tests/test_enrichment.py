# tests/test_enrichment.py – Tests für lib/article_enrichment.py (Regeln 3+4)

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.article_enrichment import rule_ean_keyword, rule_keyword_dedup


def _article(ean=None, keywords=None, international_pid=None):
    ean_tag = f"<EAN>{ean}</EAN>" if ean else ""
    if international_pid:
        ean_tag = f'<INTERNATIONAL_PID type="ean">{international_pid}</INTERNATIONAL_PID>'
    kw_tags = "\n".join(f"        <KEYWORD>{k}</KEYWORD>" for k in (keywords or []))
    return (
        f'<ARTICLE mode="new">'
        f'<ARTICLE_DETAILS>'
        f'<DESCRIPTION_SHORT>Test</DESCRIPTION_SHORT>'
        f'{ean_tag}'
        f'{kw_tags}'
        f'</ARTICLE_DETAILS>'
        f'</ARTICLE>'
    )


class TestEanKeyword:

    def test_ean_added_when_missing(self):
        article = _article(ean="4549526611858", keywords=["Taschenrechner"])
        result, changed = rule_ean_keyword(article)
        assert changed
        assert "<KEYWORD>4549526611858</KEYWORD>" in result

    def test_ean_not_added_when_already_present(self):
        article = _article(ean="4549526611858",
                           keywords=["Taschenrechner", "4549526611858"])
        result, changed = rule_ean_keyword(article)
        assert not changed
        assert result.count("4549526611858</KEYWORD>") == 1

    def test_ean_added_after_last_keyword(self):
        article = _article(ean="4549526611858", keywords=["A", "B"])
        result, _ = rule_ean_keyword(article)
        kw_pos = result.rfind("<KEYWORD>4549526611858</KEYWORD>")
        b_pos  = result.rfind("<KEYWORD>B</KEYWORD>")
        assert kw_pos > b_pos    # EAN kommt nach B

    def test_no_ean_no_change(self):
        article = _article(keywords=["Taschenrechner"])
        result, changed = rule_ean_keyword(article)
        assert not changed

    def test_non_numeric_ean_ignored(self):
        article = _article(ean="INVALID", keywords=["Taschenrechner"])
        result, changed = rule_ean_keyword(article)
        assert not changed

    def test_international_pid_recognized(self):
        article = _article(international_pid="4549526611858",
                           keywords=["Taschenrechner"])
        result, changed = rule_ean_keyword(article)
        assert changed
        assert "<KEYWORD>4549526611858</KEYWORD>" in result

    def test_ean_added_to_empty_keyword_list(self):
        """Kein Keyword vorhanden → vor </ARTICLE_DETAILS> einfügen."""
        article = _article(ean="1234567890123")
        result, changed = rule_ean_keyword(article)
        assert changed
        assert "<KEYWORD>1234567890123</KEYWORD>" in result


class TestKeywordDedup:

    def test_exact_duplicate_removed(self):
        article = _article(keywords=["CASIO", "Taschenrechner", "CASIO"])
        result, changed = rule_keyword_dedup(article)
        assert changed
        assert result.count("<KEYWORD>CASIO</KEYWORD>") == 1

    def test_case_insensitive_dedup(self):
        article = _article(keywords=["CASIO", "Casio", "casio"])
        result, changed = rule_keyword_dedup(article)
        assert changed
        # Erste Schreibweise bleibt
        assert "<KEYWORD>CASIO</KEYWORD>" in result
        assert result.count("CASIO</KEYWORD>") + result.count("Casio</KEYWORD>") + \
               result.count("casio</KEYWORD>") == 1

    def test_unique_keywords_unchanged(self):
        article = _article(keywords=["Taschenrechner", "Schulrechner", "CASIO"])
        result, changed = rule_keyword_dedup(article)
        assert not changed

    def test_single_keyword_unchanged(self):
        article = _article(keywords=["CASIO"])
        result, changed = rule_keyword_dedup(article)
        assert not changed

    def test_order_preserved(self):
        article = _article(keywords=["A", "B", "C", "B", "D"])
        result, _ = rule_keyword_dedup(article)
        # A, B, C, D in dieser Reihenfolge
        pos_a = result.index(">A<")
        pos_b = result.index(">B<")
        pos_c = result.index(">C<")
        pos_d = result.index(">D<")
        assert pos_a < pos_b < pos_c < pos_d

    def test_ean_and_dedup_combined(self):
        """EAN-Regel läuft vor Dedup → EAN nicht selbst dupliziert."""
        article = _article(ean="4549526611858",
                           keywords=["CASIO", "4549526611858", "CASIO"])
        # Erst EAN-Regel
        article, _ = rule_ean_keyword(article)
        # Dann Dedup
        result, changed = rule_keyword_dedup(article)
        assert result.count("4549526611858</KEYWORD>") == 1
        assert result.count("CASIO</KEYWORD>") == 1
