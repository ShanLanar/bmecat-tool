# lib/db_backup.py – Automatisches SQLite-Backup mit Rotation
#
# Erstellt nach jedem erfolgreichen Import eine datierte Kopie von
# article_db.sqlite im Unterordner backups/ und löscht Kopien die
# älter als RETENTION_DAYS Tage sind.

import os
import shutil
import logging
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

RETENTION_DAYS = 7
BACKUP_SUBDIR  = "backups"


def run_backup(db_path: str, progress_cb=None) -> str | None:
    """
    Kopiert db_path → backups/article_db_YYYYMMDD.sqlite.
    Gibt den Pfad der neuen Backup-Datei zurück, oder None bei Fehler.
    """
    p = progress_cb or (lambda m, **kw: None)

    if not os.path.exists(db_path):
        p("Backup: article_db.sqlite nicht gefunden – übersprungen", tag="dim")
        return None

    base_dir    = os.path.dirname(db_path)
    backup_dir  = os.path.join(base_dir, BACKUP_SUBDIR)
    Path(backup_dir).mkdir(parents=True, exist_ok=True)

    today    = datetime.now().strftime("%Y%m%d")
    dst_name = f"article_db_{today}.sqlite"
    dst_path = os.path.join(backup_dir, dst_name)

    try:
        shutil.copy2(db_path, dst_path)
        size_mb = os.path.getsize(dst_path) / 1_048_576
        p(f"Backup erstellt: backups/{dst_name}  ({size_mb:.1f} MB)", tag="ok")
    except Exception as e:
        p(f"Backup fehlgeschlagen: {e}", tag="warn")
        log.error(f"DB-Backup fehlgeschlagen: {e}")
        return None

    # Rotation: alte Backups löschen
    cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)
    removed = 0
    try:
        for f in Path(backup_dir).glob("article_db_????????.sqlite"):
            try:
                date_str = f.stem.split("_")[-1]          # YYYYMMDD
                file_date = datetime.strptime(date_str, "%Y%m%d")
                if file_date < cutoff and f != Path(dst_path):
                    f.unlink()
                    removed += 1
            except Exception:
                pass
        if removed:
            p(f"Backup-Rotation: {removed} alte Backup(s) gelöscht", tag="dim")
    except Exception as e:
        log.warning(f"Backup-Rotation Fehler: {e}")

    return dst_path
