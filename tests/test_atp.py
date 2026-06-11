# tests/test_atp.py – Tests für lib/atp.py

import os
import sys
import io
import zipfile
import tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.atp import load_atp_from_zip, merge_atp_into_availability


def _make_zip(tmp_path, content: str, encoding="cp1252") -> str:
    """Erzeugt ein ZIP mit atp.txt."""
    zip_path = str(tmp_path / "102_atp_test.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("atp.txt", content.encode(encoding))
    return zip_path


def _make_avail_csv(tmp_path, rows: list) -> str:
    """Erzeugt eine Availability-CSV."""
    path = str(tmp_path / "availability.csv")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")
    return path


class TestLoadAtpFromZip:

    def test_basic_parse(self, tmp_path):
        content = "001017\t        62\t5902658066092\t\n"
        zip_path = _make_zip(tmp_path, content)
        data = load_atp_from_zip(zip_path)
        assert "001017" in data
        assert data["001017"]["quantity"] == 62
        assert data["001017"]["ean"] == "5902658066092"
        assert data["001017"]["date"] is None

    def test_with_date(self, tmp_path):
        content = "001094022\t       409\t8021684126789\t30.05.2026\n"
        zip_path = _make_zip(tmp_path, content)
        data = load_atp_from_zip(zip_path)
        assert data["001094022"]["quantity"] == 409
        assert data["001094022"]["date"] == "30.05.2026"

    def test_empty_ean(self, tmp_path):
        content = "000024\t         0\t\t\n"
        zip_path = _make_zip(tmp_path, content)
        data = load_atp_from_zip(zip_path)
        assert data["000024"]["quantity"] == 0
        assert data["000024"]["ean"] is None

    def test_multiple_articles(self, tmp_path):
        content = (
            "001017\t62\t5902658066092\t\n"
            "001053\t19\t\t\n"
            "001080\t413\t0051141909943\t03.06.2026\n"
        )
        zip_path = _make_zip(tmp_path, content)
        data = load_atp_from_zip(zip_path)
        assert len(data) == 3
        assert data["001080"]["quantity"] == 413
        assert data["001080"]["date"] == "03.06.2026"

    def test_zero_quantity(self, tmp_path):
        content = "000274\t         0\t\t\n"
        zip_path = _make_zip(tmp_path, content)
        data = load_atp_from_zip(zip_path)
        assert data["000274"]["quantity"] == 0

    def test_missing_file(self, tmp_path):
        data = load_atp_from_zip(str(tmp_path / "nope.zip"))
        assert data == {}

    def test_bad_zip(self, tmp_path):
        bad = str(tmp_path / "bad.zip")
        with open(bad, "w") as f:
            f.write("nicht ein zip")
        data = load_atp_from_zip(bad)
        assert data == {}


class TestMergeAtpIntoAvailability:

    def test_update_existing(self, tmp_path):
        """ATP-Bestand überschreibt bestehenden Wert."""
        avail = _make_avail_csv(tmp_path, ["001017;0", "001053;5"])
        atp   = {"001017": {"quantity": 62, "ean": None, "date": None}}
        result = merge_atp_into_availability(avail, atp)
        assert result["updated"] == 1
        assert result["unchanged"] == 1

        with open(avail) as f:
            lines = [l.strip() for l in f if l.strip()]
        assert "001017;62" in lines
        assert "001053;5" in lines

    def test_add_new_article(self, tmp_path):
        """Neue AID aus ATP wird angehängt."""
        avail = _make_avail_csv(tmp_path, ["001053;5"])
        atp   = {"999888": {"quantity": 42, "ean": None, "date": None}}
        result = merge_atp_into_availability(avail, atp)
        assert result["added"] == 1

        with open(avail) as f:
            lines = [l.strip() for l in f if l.strip()]
        assert "999888;42" in lines

    def test_static_articles_preserved(self, tmp_path):
        """Statische Artikel (B0001 etc.) werden nicht verändert."""
        avail = _make_avail_csv(tmp_path, ["001017;0", "B0001;100000"])
        atp   = {"001017": {"quantity": 62, "ean": None, "date": None}}
        merge_atp_into_availability(avail, atp)

        with open(avail) as f:
            lines = [l.strip() for l in f if l.strip()]
        assert "B0001;100000" in lines

    def test_zero_quantity_written(self, tmp_path):
        """Bestand 0 aus ATP wird korrekt geschrieben."""
        avail = _make_avail_csv(tmp_path, ["001017;99"])
        atp   = {"001017": {"quantity": 0, "ean": None, "date": None}}
        merge_atp_into_availability(avail, atp)

        with open(avail) as f:
            lines = [l.strip() for l in f if l.strip()]
        assert "001017;0" in lines

    def test_empty_atp_no_change(self, tmp_path):
        """Leere ATP-Daten ändern nichts."""
        avail = _make_avail_csv(tmp_path, ["001017;5"])
        result = merge_atp_into_availability(avail, {})
        assert result == {"updated": 0, "added": 0, "unchanged": 0}

    def test_missing_csv(self, tmp_path):
        result = merge_atp_into_availability(str(tmp_path / "nope.csv"), {"x": {"quantity": 1}})
        assert result["updated"] == 0
