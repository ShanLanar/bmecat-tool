# tests/test_notifications.py
"""Tests für lib/notifications.py – E-Mail-Benachrichtigung."""

import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.notifications import _build_subject, _build_body


class TestBuildSubject:

    def test_error_subject(self):
        data = {"tasks_fehler": 2, "tasks_ok": 3, "tasks_gesamt": 5}
        subj = _build_subject(data)
        assert "2 Fehler" in subj
        assert "5 Tasks" in subj

    def test_success_subject(self):
        data = {"tasks_fehler": 0, "tasks_ok": 5, "tasks_gesamt": 5}
        subj = _build_subject(data)
        assert "5/5" in subj
        assert "erfolgreich" in subj


class TestBuildBody:

    def test_body_contains_task_details(self):
        data = {
            "start":         "2026-05-23T06:00:00",
            "ende":          "2026-05-23T06:05:00",
            "dauer_s":       300,
            "tasks_gesamt":  3,
            "tasks_ok":      2,
            "tasks_fehler":  1,
            "fehler":        ["Systeam"],
            "deduplizierung": {"removed": 10, "articles": 5, "files": 2},
            "tasks": [
                {"name": "Büroring", "status": "ok", "duration_s": 120.5, "details": {}},
                {"name": "Softcarrier", "status": "ok", "duration_s": 90.0, "details": {}},
                {"name": "Systeam", "status": "fehler", "duration_s": 10.0,
                 "details": {"fehler": "Connection timeout"}},
            ],
        }
        body = _build_body(data)
        assert "300 Sekunden" in body
        assert "2 OK" in body
        assert "1 Fehler" in body
        assert "Systeam" in body
        assert "Connection timeout" in body
        assert "Deduplizierung" in body
        assert "10 Features" in body

    def test_body_no_errors(self):
        data = {
            "start": "2026-05-23T06:00:00", "ende": "2026-05-23T06:05:00",
            "dauer_s": 300, "tasks_gesamt": 2, "tasks_ok": 2, "tasks_fehler": 0,
            "fehler": [], "deduplizierung": {"removed": 0, "articles": 0, "files": 0},
            "tasks": [
                {"name": "A", "status": "ok", "duration_s": 100.0, "details": {}},
                {"name": "B", "status": "ok", "duration_s": 200.0, "details": {}},
            ],
        }
        body = _build_body(data)
        assert "FEHLER:" not in body
        assert "2 OK" in body
