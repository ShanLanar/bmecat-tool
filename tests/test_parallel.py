# tests/test_parallel.py
"""Tests für lib/parallel.py – Parallele Ausführung."""

import os
import sys
import time
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.parallel import run_parallel


def _fast_ok():
    return "done"

def _fast_fail():
    raise ValueError("test error")

def _slow_ok(seconds=0.1):
    time.sleep(seconds)
    return "slow done"


class TestRunParallel:

    def test_empty_tasks(self):
        results = run_parallel([])
        assert results == {}

    def test_single_success(self):
        results = run_parallel([("Task1", _fast_ok)])
        assert results["Task1"]["ok"]
        assert results["Task1"]["result"] == "done"
        assert results["Task1"]["error"] is None

    def test_single_failure(self):
        results = run_parallel([("Task1", _fast_fail)])
        assert not results["Task1"]["ok"]
        assert "test error" in results["Task1"]["error"]

    def test_mixed_results(self):
        results = run_parallel([
            ("OK",   _fast_ok),
            ("FAIL", _fast_fail),
        ])
        assert results["OK"]["ok"]
        assert not results["FAIL"]["ok"]

    def test_parallel_faster_than_sequential(self):
        tasks = [
            ("A", _slow_ok, 0.15),
            ("B", _slow_ok, 0.15),
            ("C", _slow_ok, 0.15),
        ]
        start = time.time()
        results = run_parallel(tasks, max_workers=3)
        elapsed = time.time() - start

        assert all(r["ok"] for r in results.values())
        # Parallel: ~0.15s statt ~0.45s (mit Toleranz)
        assert elapsed < 0.4

    def test_progress_cb_called(self):
        logs = []
        run_parallel(
            [("T1", _fast_ok)],
            progress_cb=lambda m, **kw: logs.append(m)
        )
        assert any("parallele" in l.lower() for l in logs)
        assert any("T1" in l for l in logs)
