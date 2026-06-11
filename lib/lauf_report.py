# lib/lauf_report.py – Lauf-Zusammenfassung als JSON-Datei
#
# Wird vom _worker in main.py befüllt und am Ende geschrieben.
# Format: logs/lauf_YYYYMMDD_HHMMSS.json

import os
import json
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)


class LaufReport:
    """
    Sammelt Statistiken während eines Tool-Laufs und schreibt
    am Ende eine JSON-Datei in DIRS["logs"].
    """

    def __init__(self, log_dir: str):
        self.log_dir    = log_dir
        self.start_time = datetime.now()
        self.tasks      = []          # [{name, status, duration_s, details}]
        self.dedup            = {"removed": 0, "files": 0, "articles": 0}
        self.errors           = []
        self.dropped_articles : list[dict] = []   # Artikel nicht mehr im Katalog
        self.price_warnings   : list[str]  = []   # Ablaufende Preisregeln
        self._current   = None
        self._task_start = None

    def begin_task(self, name: str):
        self._current   = name
        self._task_start = datetime.now()

    def end_task(self, name: str, success: bool, details: dict = None):
        duration = (datetime.now() - self._task_start).total_seconds() \
                   if self._task_start else 0
        self.tasks.append({
            "name":       name,
            "status":     "ok" if success else "fehler",
            "duration_s": round(duration, 1),
            "details":    details or {},
        })
        if not success:
            self.errors.append(name)
        self._current    = None
        self._task_start = None

    def add_dedup(self, removed: int, files: int, articles: int):
        self.dedup["removed"]  += removed
        self.dedup["files"]    += files
        self.dedup["articles"] += articles

    def add_dropped(self, articles: list[dict]):
        """Artikel die beim Stale-Cleanup entfernt wurden (nicht mehr im Katalog)."""
        self.dropped_articles.extend(articles)

    def add_price_warnings(self, warnings: list[str]):
        """Ablaufende oder abgelaufene Preisregeln."""
        self.price_warnings.extend(warnings)

    def as_dict(self) -> dict:
        """Gibt Report-Dict zurück (für Notifier)."""
        n_ok  = sum(1 for t in self.tasks if t["status"] == "ok")
        n_err = len(self.errors)
        return {
            "tasks_ok":      n_ok,
            "tasks_fehler":  n_err,
            "dauer_s":       (datetime.now() - self.start_time).total_seconds(),
            "fehler":        self.errors,
            "tasks":         self.tasks,
        }

    def write_dropped_csv(self) -> str | None:
        """
        Schreibt weggefallene Artikel als CSV in logs/.
        Nur wenn mindestens 1 Artikel entfernt wurde.
        Gibt den Dateipfad zurück oder None.
        """
        if not self.dropped_articles:
            return None
        Path(self.log_dir).mkdir(parents=True, exist_ok=True)
        ts       = self.start_time.strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join(self.log_dir, f"weggefallen_{ts}.csv")
        try:
            import csv as _csv
            with open(out_path, "w", newline="", encoding="utf-8") as f:
                w = _csv.DictWriter(f, fieldnames=["product_id", "supplier_name"])
                w.writeheader()
                for a in self.dropped_articles:
                    w.writerow({
                        "product_id":    a.get("product_id", ""),
                        "supplier_name": a.get("supplier_name", ""),
                    })
            log.info(f"Weggefallene Artikel: {out_path} "
                     f"({len(self.dropped_articles)} Einträge)")
            return out_path
        except Exception as e:
            log.error(f"Dropped-CSV Fehler: {e}")
            return None

    def write(self) -> str:
        """Schreibt den Report als JSON. Gibt den Pfad zurück."""
        Path(self.log_dir).mkdir(parents=True, exist_ok=True)
        ts       = self.start_time.strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join(self.log_dir, f"lauf_{ts}.json")

        duration_total = (datetime.now() - self.start_time).total_seconds()
        n_ok    = sum(1 for t in self.tasks if t["status"] == "ok")
        n_err   = len(self.errors)

        report = {
            "start":              self.start_time.isoformat(),
            "ende":               datetime.now().isoformat(),
            "dauer_s":            round(duration_total, 1),
            "tasks_gesamt":       len(self.tasks),
            "tasks_ok":           n_ok,
            "tasks_fehler":       n_err,
            "fehler":             self.errors,
            "deduplizierung":     self.dedup,
            "tasks":              self.tasks,
            "dropped_articles":   len(self.dropped_articles),
            "price_warnings":     self.price_warnings,
        }

        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            log.info(f"Lauf-Report: {out_path}")
        except Exception as e:
            log.error(f"Lauf-Report konnte nicht geschrieben werden: {e}")
            return ""

        return out_path
