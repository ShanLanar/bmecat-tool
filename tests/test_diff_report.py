# tests/test_diff_report.py
"""Tests für lib/diff_report.py – Artikel-Diff zwischen Läufen."""

import os
import sys
import json
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.diff_report import (
    extract_article_snapshot,
    compare_snapshots,
    create_diff_report,
)


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


def _make_xml(articles: list) -> str:
    """Erzeugt eine Mini-BMEcat-XML.

    articles: [(aid, price), ...] – price kann None sein
    """
    lines = ['<BMECAT version="1.2">', '<T_NEW_CATALOG>']
    for aid, price in articles:
        lines.append('<ARTICLE>')
        lines.append(f'  <SUPPLIER_AID>{aid}</SUPPLIER_AID>')
        if price is not None:
            lines.append('  <ARTICLE_PRICE_DETAILS>')
            lines.append('    <ARTICLE_PRICE type="net_list">')
            lines.append(f'      <PRICE_AMOUNT>{price}</PRICE_AMOUNT>')
            lines.append('    </ARTICLE_PRICE>')
            lines.append('  </ARTICLE_PRICE_DETAILS>')
        lines.append('</ARTICLE>')
    lines.append('</T_NEW_CATALOG>')
    lines.append('</BMECAT>')
    return '\n'.join(lines)


class TestExtractSnapshot:

    def test_empty_file(self, tmp_path):
        path = _write(tmp_path, "empty.xml", "")
        snap = extract_article_snapshot(path)
        assert snap == {}

    def test_missing_file(self, tmp_path):
        snap = extract_article_snapshot(str(tmp_path / "nope.xml"))
        assert snap == {}

    def test_basic_extraction(self, tmp_path):
        xml = _make_xml([("A001", 19.99), ("A002", 5.50), ("A003", None)])
        path = _write(tmp_path, "test.xml", xml)
        snap = extract_article_snapshot(path)
        assert len(snap) == 3
        assert snap["A001"]["price"] == 19.99
        assert snap["A002"]["price"] == 5.50
        assert snap["A003"]["price"] is None


class TestCompareSnapshots:

    def test_identical(self):
        old = {"A1": {"price": 10.0}, "A2": {"price": 20.0}}
        new = {"A1": {"price": 10.0}, "A2": {"price": 20.0}}
        diff = compare_snapshots(old, new)
        assert diff["added"] == []
        assert diff["removed"] == []
        assert diff["price_changed"] == []
        assert diff["unchanged"] == 2

    def test_added_articles(self):
        old = {"A1": {"price": 10.0}}
        new = {"A1": {"price": 10.0}, "A2": {"price": 20.0}, "A3": {"price": 30.0}}
        diff = compare_snapshots(old, new)
        assert diff["added"] == ["A2", "A3"]
        assert diff["removed"] == []
        assert diff["unchanged"] == 1

    def test_removed_articles(self):
        old = {"A1": {"price": 10.0}, "A2": {"price": 20.0}, "A3": {"price": 30.0}}
        new = {"A1": {"price": 10.0}}
        diff = compare_snapshots(old, new)
        assert diff["added"] == []
        assert diff["removed"] == ["A2", "A3"]
        assert diff["unchanged"] == 1

    def test_price_changes(self):
        old = {"A1": {"price": 10.0}, "A2": {"price": 20.0}}
        new = {"A1": {"price": 15.0}, "A2": {"price": 20.0}}
        diff = compare_snapshots(old, new)
        assert len(diff["price_changed"]) == 1
        assert diff["price_changed"][0]["aid"] == "A1"
        assert diff["price_changed"][0]["old_price"] == 10.0
        assert diff["price_changed"][0]["new_price"] == 15.0
        assert diff["unchanged"] == 1

    def test_combined_changes(self):
        old = {"A1": {"price": 10.0}, "A2": {"price": 20.0}}
        new = {"A1": {"price": 15.0}, "A3": {"price": 30.0}}
        diff = compare_snapshots(old, new)
        assert diff["added"] == ["A3"]
        assert diff["removed"] == ["A2"]
        assert len(diff["price_changed"]) == 1
        assert diff["unchanged"] == 0


class TestCreateDiffReport:

    def test_first_run_creates_baseline(self, tmp_path):
        xml = _make_xml([("A1", 10.0), ("A2", 20.0)])
        path = _write(tmp_path, "test.xml", xml)
        backup_dir = str(tmp_path / "backups")

        logs = []
        result = create_diff_report(path, backup_dir=backup_dir,
                                     progress_cb=lambda m, **kw: logs.append(m))
        assert result is None  # Kein Vergleich beim ersten Lauf
        assert os.path.exists(os.path.join(backup_dir, "test_snapshot.json"))
        assert any("Baseline" in l or "Erster Lauf" in l for l in logs)

    def test_second_run_produces_diff(self, tmp_path):
        backup_dir = str(tmp_path / "backups")

        # Erster Lauf
        xml1 = _make_xml([("A1", 10.0), ("A2", 20.0)])
        path = _write(tmp_path, "test.xml", xml1)
        create_diff_report(path, backup_dir=backup_dir)

        # Zweiter Lauf: A2 gelöscht, A3 neu, A1 Preisänderung
        xml2 = _make_xml([("A1", 15.0), ("A3", 30.0)])
        _write(tmp_path, "test.xml", xml2)
        diff = create_diff_report(path, backup_dir=backup_dir)

        assert diff is not None
        assert "A3" in diff["added"]
        assert "A2" in diff["removed"]
        assert len(diff["price_changed"]) == 1

        # Diff-Report-Datei existiert
        report_files = [f for f in os.listdir(backup_dir)
                        if f.startswith("diff_test_")]
        assert len(report_files) == 1

    def test_unchanged_data(self, tmp_path):
        backup_dir = str(tmp_path / "backups")
        xml = _make_xml([("A1", 10.0)])
        path = _write(tmp_path, "test.xml", xml)

        create_diff_report(path, backup_dir=backup_dir)
        diff = create_diff_report(path, backup_dir=backup_dir)

        assert diff is not None
        assert diff["added"] == []
        assert diff["removed"] == []
        assert diff["price_changed"] == []
        assert diff["unchanged"] == 1
