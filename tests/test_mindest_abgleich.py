# tests/test_mindest_abgleich.py – Tests für lib/mindest_abgleich.py

import os, sys, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.mindest_abgleich import (
    load_availability, generate_conditionsfile, find_latest_mindest_xlsx
)


def _avail(tmp_path, rows):
    p = tmp_path / "availability.csv"
    p.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return str(p)


class TestLoadAvailability:

    def test_basic(self, tmp_path):
        data = load_availability(_avail(tmp_path, ["AID1;10", "AID2;0", "AID3;5"]))
        assert data == {"AID1": 10, "AID2": 0, "AID3": 5}

    def test_skips_header(self, tmp_path):
        data = load_availability(_avail(tmp_path, ["SUPPLIER_AID;STOCK", "A1;3"]))
        assert "SUPPLIER_AID" not in data
        assert data["A1"] == 3

    def test_missing_file(self, tmp_path):
        assert load_availability(str(tmp_path / "nope.csv")) == {}


class TestGenerateConditionsfile:

    def test_above_minimum_included(self, tmp_path):
        """STOCK >= 10 (globale Grenze) → Export."""
        avail = _avail(tmp_path, ["A1;10", "A2;3"])
        mindest = {"A1": 999, "A2": 999}  # Tabellenwert wird ignoriert
        out = str(tmp_path / "out.csv")
        stats = generate_conditionsfile(avail, mindest, out)
        lines = open(out).read().splitlines()
        assert "A1" in lines     # 10 >= 10 ✓
        assert "A2" not in lines # 3 < 10 ✗
        assert stats["below_minimum"] == 1
        assert stats["exported"] == 1

    def test_exactly_at_minimum_included(self, tmp_path):
        """Genau 10 → exportieren."""
        avail = _avail(tmp_path, ["A1;10"])
        out = str(tmp_path / "out.csv")
        generate_conditionsfile(avail, {"A1": 999}, out)
        assert "A1" in open(out).read().splitlines()

    def test_nine_excluded(self, tmp_path):
        """STOCK=9 < 10 → nicht exportieren."""
        avail = _avail(tmp_path, ["A1;9"])
        out = str(tmp_path / "out.csv")
        generate_conditionsfile(avail, {"A1": 999}, out)
        assert "A1" not in open(out).read().splitlines()

    def test_not_in_table_positive_stock_exported(self, tmp_path):
        """Kein Mindest-Eintrag + STOCK > 0 → exportieren."""
        avail = _avail(tmp_path, ["A1;5", "A2;0"])
        out = str(tmp_path / "out.csv")
        stats = generate_conditionsfile(avail, {}, out)
        lines = open(out).read().splitlines()
        assert "A1" in lines    # STOCK=5 > 0 → exportieren
        assert "A2" not in lines  # STOCK=0, kein Mindest → nicht exportieren
        assert stats["zero_stock"] == 1

    def test_header_written(self, tmp_path):
        avail = _avail(tmp_path, ["A1;10"])
        out = str(tmp_path / "out.csv")
        generate_conditionsfile(avail, {}, out)
        first = open(out).readline().strip()
        assert first == "SUPPLIER_AID"

    def test_mixed_case_aid_matching(self, tmp_path):
        """Mindest-Tabelle und AID müssen case-insensitiv verglichen werden."""
        avail = _avail(tmp_path, ["ALC151WS;198"])
        out = str(tmp_path / "out.csv")
        # Mindest-Tabelle hat uppercase
        stats = generate_conditionsfile(avail, {"ALC151WS": 5}, out)
        assert "ALC151WS" in open(out).read().splitlines()
        assert stats["exported"] == 1

    def test_zero_stock_below_minimum_excluded(self, tmp_path):
        """STOCK=0 < Mindest=5 → nicht exportieren."""
        avail = _avail(tmp_path, ["A1;0"])
        out = str(tmp_path / "out.csv")
        generate_conditionsfile(avail, {"A1": 5}, out)
        lines = open(out).read().splitlines()
        assert "A1" not in lines

    def test_zero_stock_no_mindest_excluded(self, tmp_path):
        """STOCK=0, kein Mindest-Eintrag → nicht exportieren."""
        avail = _avail(tmp_path, ["A1;0", "A2;10"])
        out = str(tmp_path / "out.csv")
        generate_conditionsfile(avail, {}, out)
        lines = open(out).read().splitlines()
        assert "A1" not in lines
        assert "A2" in lines

    def test_output_sorted(self, tmp_path):
        avail = _avail(tmp_path, ["Z9;10", "A1;10", "M5;10"])
        out = str(tmp_path / "out.csv")
        generate_conditionsfile(avail, {}, out)
        lines = [l for l in open(out).read().splitlines() if l != "SUPPLIER_AID"]
        assert lines == sorted(lines)


class TestFindLatestMindestXlsx:

    def test_finds_newest(self, tmp_path):
        import time
        f1 = tmp_path / "Mindest-Abgleich_20260520_.xlsx"
        f2 = tmp_path / "Mindest-Abgleich_20260527_.xlsx"
        f1.write_text("x")
        time.sleep(0.01)
        f2.write_text("x")
        result = find_latest_mindest_xlsx(str(tmp_path))
        assert result.endswith("20260527_.xlsx")

    def test_returns_none_if_missing(self, tmp_path):
        assert find_latest_mindest_xlsx(str(tmp_path)) is None
