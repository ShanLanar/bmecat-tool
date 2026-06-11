# tests/test_bilder_delta.py
"""Tests für Softcarrier Bilder Delta-Upload."""

import os
import sys
import json
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tasks.softcarrier import _compute_delta, _load_snapshot, _save_snapshot


class TestComputeDelta:

    def test_first_run_all_changed(self, tmp_path):
        """Erster Lauf ohne Snapshot: alle Dateien sind 'geändert'."""
        (tmp_path / "SOC001.jpg").write_bytes(b"\xff" * 100)
        (tmp_path / "SOC002.jpg").write_bytes(b"\xff" * 200)

        changed, snapshot = _compute_delta(str(tmp_path), {})
        assert len(changed) == 2
        assert len(snapshot) == 2
        assert snapshot["SOC001.jpg"] == 100
        assert snapshot["SOC002.jpg"] == 200

    def test_no_changes(self, tmp_path):
        """Alle Dateien unverändert → leere Delta-Liste."""
        (tmp_path / "SOC001.jpg").write_bytes(b"\xff" * 100)
        (tmp_path / "SOC002.jpg").write_bytes(b"\xff" * 200)

        previous = {"SOC001.jpg": 100, "SOC002.jpg": 200}
        changed, snapshot = _compute_delta(str(tmp_path), previous)
        assert changed == []
        assert len(snapshot) == 2

    def test_new_file_detected(self, tmp_path):
        """Neue Datei wird erkannt."""
        (tmp_path / "SOC001.jpg").write_bytes(b"\xff" * 100)
        (tmp_path / "SOC002.jpg").write_bytes(b"\xff" * 200)
        (tmp_path / "SOC003.jpg").write_bytes(b"\xff" * 300)

        previous = {"SOC001.jpg": 100, "SOC002.jpg": 200}
        changed, snapshot = _compute_delta(str(tmp_path), previous)
        assert len(changed) == 1
        assert any("SOC003" in c for c in changed)

    def test_size_change_detected(self, tmp_path):
        """Dateigrößen-Änderung wird erkannt."""
        (tmp_path / "SOC001.jpg").write_bytes(b"\xff" * 150)  # war 100
        (tmp_path / "SOC002.jpg").write_bytes(b"\xff" * 200)

        previous = {"SOC001.jpg": 100, "SOC002.jpg": 200}
        changed, snapshot = _compute_delta(str(tmp_path), previous)
        assert len(changed) == 1
        assert any("SOC001" in c for c in changed)
        assert snapshot["SOC001.jpg"] == 150

    def test_mixed_changes(self, tmp_path):
        """Kombination: neue Datei + geänderte Größe + unverändert."""
        (tmp_path / "SOC001.jpg").write_bytes(b"\xff" * 100)  # unverändert
        (tmp_path / "SOC002.jpg").write_bytes(b"\xff" * 250)  # war 200
        (tmp_path / "SOC004.jpg").write_bytes(b"\xff" * 400)  # neu

        previous = {"SOC001.jpg": 100, "SOC002.jpg": 200, "SOC003.jpg": 300}
        changed, snapshot = _compute_delta(str(tmp_path), previous)
        names = [os.path.basename(c) for c in changed]
        assert "SOC002.jpg" in names
        assert "SOC004.jpg" in names
        assert "SOC001.jpg" not in names
        assert len(changed) == 2

    def test_empty_directory(self, tmp_path):
        """Leeres Verzeichnis → leere Ergebnisse."""
        changed, snapshot = _compute_delta(str(tmp_path), {"SOC001.jpg": 100})
        assert changed == []
        assert snapshot == {}


class TestSnapshotIO:

    def test_save_and_load(self, tmp_path, monkeypatch):
        snapshot_path = str(tmp_path / "test_snapshot.json")
        import tasks.softcarrier as sc
        monkeypatch.setattr(sc, "_SNAPSHOT_FILE", snapshot_path)

        data = {"SOC001.jpg": 100, "SOC002.jpg": 200}
        _save_snapshot(data)
        loaded = _load_snapshot()
        assert loaded == data

    def test_load_missing_file(self, tmp_path, monkeypatch):
        import tasks.softcarrier as sc
        monkeypatch.setattr(sc, "_SNAPSHOT_FILE", str(tmp_path / "nope.json"))
        assert _load_snapshot() == {}

    def test_load_corrupt_file(self, tmp_path, monkeypatch):
        bad = tmp_path / "bad.json"
        bad.write_text("not json at all {{{", encoding="utf-8")
        import tasks.softcarrier as sc
        monkeypatch.setattr(sc, "_SNAPSHOT_FILE", str(bad))
        assert _load_snapshot() == {}
