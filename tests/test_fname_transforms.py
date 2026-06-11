# tests/test_fname_transforms.py

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.fname_transforms import transform_feature, transform_article, load_rename_csv


class TestTransformFeature:

    def test_eclass_id_removed(self):
        block = "<FEATURE><FNAME>Breite (0173-01-AAD931-001)</FNAME><FVALUE>50</FVALUE></FEATURE>"
        result, marke = transform_feature(block, {}, {})
        assert "0173" not in result
        assert "<FNAME>Breite</FNAME>" in result
        assert marke is None

    def test_fname_renamed(self):
        block = "<FEATURE><FNAME>Farbe</FNAME><FVALUE>Rot</FVALUE></FEATURE>"
        result, marke = transform_feature(block, {"FARBE": "Produktfarbe"}, {})
        assert "<FNAME>Produktfarbe</FNAME>" in result
        assert marke is None

    def test_fvalue_caa016_to_ja(self):
        block = "<FEATURE><FNAME>Wasserdicht</FNAME><FVALUE>CAA016</FVALUE></FEATURE>"
        result, marke = transform_feature(block, {}, {"CAA016": "Ja", "CAA017": "Nein"})
        assert "<FVALUE>Ja</FVALUE>" in result
        assert marke is None

    def test_fvalue_caa017_to_nein(self):
        block = "<FEATURE><FNAME>Wasserdicht</FNAME><FVALUE>CAA017</FVALUE></FEATURE>"
        result, _ = transform_feature(block, {}, {"CAA016": "Ja", "CAA017": "Nein"})
        assert "<FVALUE>Nein</FVALUE>" in result

    def test_marke_returns_value(self):
        block = "<FEATURE><FNAME>Marke</FNAME><FVALUE>CASIO</FVALUE></FEATURE>"
        result, marke = transform_feature(block, {}, {})
        assert result == ""     # Block verworfen
        assert marke == "CASIO"

    def test_marke_after_rename(self):
        """FNAME wird zu Marke nach Rename → gleiche Logik."""
        block = "<FEATURE><FNAME>Hersteller</FNAME><FVALUE>CASIO</FVALUE></FEATURE>"
        result, marke = transform_feature(block, {"HERSTELLER": "Marke"}, {})
        assert result == ""
        assert marke == "CASIO"

    def test_eclass_and_rename_combined(self):
        """(0173-...) entfernen UND dann umbenennen."""
        block = "<FEATURE><FNAME>Farbe (0173-01-AAD931-001)</FNAME><FVALUE>Blau</FVALUE></FEATURE>"
        result, _ = transform_feature(block, {"FARBE": "Produktfarbe"}, {})
        assert "<FNAME>Produktfarbe</FNAME>" in result
        assert "0173" not in result

    def test_no_fname_block_unchanged(self):
        block = "<FEATURE><FVALUE>abc</FVALUE></FEATURE>"
        result, marke = transform_feature(block, {}, {})
        assert result == block
        assert marke is None


class TestTransformArticle:

    def _article(self, mfr=None, features=None):
        mfr_tag = f"<MANUFACTURER_NAME>{mfr}</MANUFACTURER_NAME>" if mfr else ""
        feat_str = "\n".join(features or [])
        return (
            f"<ARTICLE><ARTICLE_DETAILS>"
            f"<DESCRIPTION_SHORT>Test</DESCRIPTION_SHORT>"
            f"{mfr_tag}"
            f"</ARTICLE_DETAILS>"
            f"<ARTICLE_FEATURES>{feat_str}</ARTICLE_FEATURES>"
            f"</ARTICLE>"
        )

    def test_marke_adds_manufacturer_when_missing(self):
        article = self._article(mfr=None, features=[
            "<FEATURE><FNAME>Marke</FNAME><FVALUE>CASIO</FVALUE></FEATURE>"
        ])
        result = transform_article(article, {}, {})
        assert "<MANUFACTURER_NAME>CASIO</MANUFACTURER_NAME>" in result
        # Feature selbst sollte nicht mehr drin sein
        assert "<FNAME>Marke</FNAME>" not in result

    def test_marke_dropped_when_manufacturer_exists(self):
        article = self._article(mfr="CASIO", features=[
            "<FEATURE><FNAME>Marke</FNAME><FVALUE>CASIO</FVALUE></FEATURE>",
            "<FEATURE><FNAME>Farbe</FNAME><FVALUE>Schwarz</FVALUE></FEATURE>",
        ])
        result = transform_article(article, {}, {})
        # Marke-Feature verworfen
        assert result.count("<MANUFACTURER_NAME>") == 1  # nur das original
        assert "<FNAME>Marke</FNAME>" not in result
        # Farbe-Feature bleibt
        assert "<FNAME>Farbe</FNAME>" in result

    def test_caa016_renamed_in_article(self):
        article = self._article(features=[
            "<FEATURE><FNAME>Recycelbar</FNAME><FVALUE>CAA016</FVALUE></FEATURE>"
        ])
        result = transform_article(article, {}, {"CAA016": "Ja", "CAA017": "Nein"})
        assert "<FVALUE>Ja</FVALUE>" in result

    def test_eclass_id_removed_in_article(self):
        article = self._article(features=[
            "<FEATURE><FNAME>Breite (0173-01-AAD931-001)</FNAME><FVALUE>50</FVALUE></FEATURE>"
        ])
        result = transform_article(article, {}, {})
        assert "0173" not in result
        assert "<FNAME>Breite</FNAME>" in result


class TestLoadRenameCsv:

    def test_basic(self, tmp_path):
        p = tmp_path / "renames.csv"
        p.write_text("from,to\nFarbe,Produktfarbe\nMarke,Hersteller\n", encoding="utf-8")
        m = load_rename_csv(str(p))
        assert m["FARBE"] == "Produktfarbe"
        assert m["MARKE"] == "Hersteller"

    def test_missing_file(self, tmp_path):
        assert load_rename_csv(str(tmp_path / "nope.csv")) == {}

    def test_bom_handled(self, tmp_path):
        p = tmp_path / "renames.csv"
        p.write_bytes("from,to\nA,B\n".encode("utf-8-sig"))
        m = load_rename_csv(str(p))
        assert "A" in m
