# tests/test_bestandsdaten.py – Tests für lib/bestandsdaten.py

import os, sys, csv, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.bestandsdaten import erstelle_bestandsdaten, _load_static_articles, STATIC_ARTICLES


class TestStaticArticles:

    def test_static_articles_loaded(self):
        assert len(STATIC_ARTICLES) > 0

    def test_static_articles_format(self):
        for line in STATIC_ARTICLES.splitlines()[:10]:
            parts = line.split(";")
            assert len(parts) == 2, f"Ungültiges Format: {line!r}"
            assert parts[0].startswith("B"), f"AID ohne B-Präfix: {line!r}"
            assert parts[1].isdigit(), f"Stock nicht numerisch: {line!r}"

    def test_minimum_article_count(self):
        count = len([l for l in STATIC_ARTICLES.splitlines() if l.strip()])
        assert count >= 1000, f"Zu wenige statische Artikel: {count}"

    def test_load_static_articles_reproducible(self):
        a = _load_static_articles()
        b = _load_static_articles()
        assert a == b


class TestErstelle:

    def _bestand_csv(self, tmp_path, rows):
        p = tmp_path / "br-bestand.csv"
        p.write_text(
            "SUPPLIER_AID;STOCK\n" + "\n".join(rows),
            encoding="utf-8")
        return str(tmp_path)

    def test_basic(self, tmp_path):
        d = self._bestand_csv(tmp_path, ["BR-001;5", "BR-002;0"])
        out = str(tmp_path / "avail.csv")
        result = erstelle_bestandsdaten(d, out)
        assert result == out
        with open(out) as f:
            lines = f.read().splitlines()
        assert lines[0] == "SUPPLIER_AID;STOCK"
        assert "BR-001;5" in lines
        assert "BR-002;0" in lines

    def test_static_articles_appended(self, tmp_path):
        d = self._bestand_csv(tmp_path, ["BR-001;5"])
        out = str(tmp_path / "avail.csv")
        erstelle_bestandsdaten(d, out)
        with open(out) as f:
            content = f.read()
        assert "B0001;100000" in content

    def test_no_duplicate_header(self, tmp_path):
        d = self._bestand_csv(tmp_path, ["BR-001;5"])
        out = str(tmp_path / "avail.csv")
        erstelle_bestandsdaten(d, out)
        with open(out) as f:
            lines = f.read().splitlines()
        assert lines.count("SUPPLIER_AID;STOCK") == 1

    def test_missing_input_raises(self, tmp_path):
        import pytest
        with pytest.raises(FileNotFoundError):
            erstelle_bestandsdaten(str(tmp_path / "empty"), str(tmp_path / "out.csv"))

    def test_skips_empty_lines(self, tmp_path):
        d = self._bestand_csv(tmp_path, ["BR-001;5", "", "BR-002;3"])
        out = str(tmp_path / "avail.csv")
        erstelle_bestandsdaten(d, out)
        with open(out) as f:
            lines = [l for l in f.read().splitlines() if l.strip()]
        assert "BR-001;5" in lines
        assert "BR-002;3" in lines

    def test_overwrites_existing(self, tmp_path):
        d = self._bestand_csv(tmp_path, ["BR-001;5"])
        out = str(tmp_path / "avail.csv")
        # Erst mit Inhalt schreiben
        with open(out, "w") as f:
            f.write("STALE;DATA\n")
        erstelle_bestandsdaten(d, out)
        with open(out) as f:
            content = f.read()
        assert "STALE" not in content
