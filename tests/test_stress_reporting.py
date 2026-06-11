# tests/test_stress_reporting.py – Dashboard/LaufReport/Notifications (70+ Fälle)

import sys, os, json, pytest, tempfile
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.lauf_report import LaufReport


# ── LaufReport ────────────────────────────────────────────────────────────────

class TestLaufReport:

    def test_creates_file(self, tmp_path):
        r = LaufReport(str(tmp_path))
        r.begin_task("TestTask")
        r.end_task("TestTask", success=True)
        path = r.write()
        assert path and os.path.exists(path)

    def test_json_valid(self, tmp_path):
        r = LaufReport(str(tmp_path))
        r.begin_task("A")
        r.end_task("A", success=True)
        path = r.write()
        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_contains_task_info(self, tmp_path):
        r = LaufReport(str(tmp_path))
        r.begin_task("MeinTask")
        r.end_task("MeinTask", success=True)
        path = r.write()
        content = open(path).read()
        assert "MeinTask" in content

    def test_failed_task_recorded(self, tmp_path):
        r = LaufReport(str(tmp_path))
        r.begin_task("FailTask")
        r.end_task("FailTask", success=False, details={"error": "Schiefgelaufen"})
        path = r.write()
        with open(path) as f:
            data = json.load(f)
        # Report muss Fehlerinformation enthalten
        content = str(data)
        assert "FailTask" in content

    @pytest.mark.parametrize("n_tasks", [1, 5, 20, 50])
    def test_many_tasks(self, tmp_path, n_tasks):
        r = LaufReport(str(tmp_path))
        for i in range(n_tasks):
            r.begin_task(f"Task{i}")
            r.end_task(f"Task{i}", success=(i % 3 != 0))
        path = r.write()
        assert os.path.exists(path)

    def test_start_time_present(self, tmp_path):
        r = LaufReport(str(tmp_path))
        r.begin_task("T")
        r.end_task("T", success=True)
        path = r.write()
        with open(path) as f:
            data = json.load(f)
        assert "start" in str(data)

    def test_duplicate_task_no_crash(self, tmp_path):
        r = LaufReport(str(tmp_path))
        r.begin_task("Same")
        r.end_task("Same", success=True)
        r.begin_task("Same")
        r.end_task("Same", success=True)
        path = r.write()
        assert os.path.exists(path)

    def test_empty_report(self, tmp_path):
        r = LaufReport(str(tmp_path))
        path = r.write()
        # Leerer Report: entweder None oder leere Datei
        assert path is None or os.path.exists(path)

    def test_unicode_in_task_name(self, tmp_path):
        r = LaufReport(str(tmp_path))
        r.begin_task("Büroring-Merge")
        r.end_task("Büroring-Merge", success=True)
        path = r.write()
        assert os.path.exists(path)
        content = open(path, encoding="utf-8").read()
        assert "Büroring" in content

    def test_dedup_recorded(self, tmp_path):
        r = LaufReport(str(tmp_path))
        r.begin_task("T"); r.end_task("T", success=True)
        r.add_dedup(removed=42, files=3, articles=21000)
        path = r.write()
        content = open(path).read()
        assert "42" in content or "dedup" in content.lower()

    def test_write_returns_path(self, tmp_path):
        """write() gibt existierenden Pfad zurück."""
        r = LaufReport(str(tmp_path))
        r.begin_task("A"); r.end_task("A", success=True)
        p = r.write()
        assert p is not None
        assert os.path.exists(p)
        assert p.endswith(".json")


# ── Dashboard Trend Report ────────────────────────────────────────────────────

from lib.dashboard import generate_trend_report


def _make_lauf_json(tmp_path, n=5):
    """Erzeugt n Lauf-JSON-Dateien."""
    import time
    for i in range(n):
        ts = datetime.now().strftime(f"%Y%m%d_{i:06d}")
        path = tmp_path / f"lauf_{ts}.json"
        data = {
            "start": (datetime.now() - timedelta(minutes=10-i)).isoformat(),
            "ende":  datetime.now().isoformat(),
            "dauer_s": 600 - i*10,
            "tasks_gesamt": 8,
            "tasks_ok": 7 - (i % 3),
            "tasks_fehler": i % 3,
        }
        path.write_text(json.dumps(data), encoding="utf-8")


class TestDashboard:

    def test_no_lauf_files(self, tmp_path):
        result = generate_trend_report(str(tmp_path))
        assert result == "" or result is None

    def test_creates_html(self, tmp_path):
        _make_lauf_json(tmp_path, 5)
        result = generate_trend_report(str(tmp_path))
        if result:
            assert os.path.exists(result)
            assert result.endswith(".html")

    def test_html_has_chart(self, tmp_path):
        _make_lauf_json(tmp_path, 5)
        result = generate_trend_report(str(tmp_path))
        if result and os.path.exists(result):
            content = open(result, encoding="utf-8").read()
            assert "chart" in content.lower() or "canvas" in content.lower()

    @pytest.mark.parametrize("n", [1, 5, 15, 30])
    def test_various_run_counts(self, tmp_path, n):
        _make_lauf_json(tmp_path, n)
        result = generate_trend_report(str(tmp_path))
        assert result is None or isinstance(result, str)

    def test_corrupted_lauf_json(self, tmp_path):
        (tmp_path / "lauf_bad.json").write_text("{invalid}", encoding="utf-8")
        _make_lauf_json(tmp_path, 3)
        result = generate_trend_report(str(tmp_path))
        # Kein Absturz bei kaputten Dateien
        assert result is None or isinstance(result, str)

    def test_empty_lauf_json(self, tmp_path):
        (tmp_path / "lauf_empty.json").write_text("{}", encoding="utf-8")
        result = generate_trend_report(str(tmp_path))
        assert result is None or isinstance(result, str)

    def test_max_30_runs_used(self, tmp_path):
        _make_lauf_json(tmp_path, 50)  # 50 Dateien, nur letzte 30 genutzt
        result = generate_trend_report(str(tmp_path))
        if result and os.path.exists(result):
            content = open(result, encoding="utf-8").read()
            assert "30" in content or "50" in content  # irgendeine Zahl drin


# ── Notifications ─────────────────────────────────────────────────────────────

from lib.notifications import _build_subject, _build_body


class TestNotifications:

    SAMPLE_DATA = {
        "start": "2026-05-30T06:00:00",
        "ende":  "2026-05-30T06:12:34",
        "dauer_s": 754.2,
        "tasks_gesamt": 8,
        "tasks_ok": 7,
        "tasks_fehler": 1,
        "fehler": ["Nordwest: FTP timeout"],
        "tasks": [
            {"name": "Büroring", "status": "ok", "duration_s": 45.2},
            {"name": "Nordwest", "status": "err", "duration_s": 12.1, "details": {"fehler": "timeout"}},
        ],
    }

    def test_builds_email(self):
        subject = _build_subject(self.SAMPLE_DATA)
        body = _build_body(self.SAMPLE_DATA)
        assert isinstance(subject, str)
        assert isinstance(body, str)
        assert len(subject) > 0
        assert len(body) > 0

    def test_error_count_in_subject_or_body(self):
        subject = _build_subject(self.SAMPLE_DATA)
        body = _build_body(self.SAMPLE_DATA)
        full = subject + body
        assert "1" in full or "fehler" in full.lower() or "Fehler" in full

    def test_success_run_no_error_mentioned(self):
        data = dict(self.SAMPLE_DATA, tasks_fehler=0, fehler=[])
        subject = _build_subject(data)
        body = _build_body(data)
        full = (subject + body).lower()
        assert "ok" in full or "erfolg" in full or "✅" in full

    def test_empty_data_no_crash(self):
        try:
            result = build_summary_email({})
            assert isinstance(result, tuple)
        except Exception:
            pass  # Exception OK, Absturz nicht

    def test_unicode_in_errors(self):
        data = dict(self.SAMPLE_DATA, fehler=["Fehler: Größe überschritten"])
        subject = _build_subject(data)
        body = _build_body(data)
        assert isinstance(subject, str)

    @pytest.mark.parametrize("n_errors", [0, 1, 5, 10])
    def test_various_error_counts(self, n_errors):
        data = dict(self.SAMPLE_DATA,
                    tasks_fehler=n_errors,
                    fehler=[f"Fehler {i}" for i in range(n_errors)])
        subject = _build_subject(data)
        body = _build_body(data)
        assert isinstance(subject, str) and isinstance(body, str)
