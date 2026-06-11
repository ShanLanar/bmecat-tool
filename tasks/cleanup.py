# tasks/cleanup.py – Alte Daten aufräumen (Port von: del *.xml / *.csv in bmecat-download.bat)
#
# Löscht:
#   in_BME/  → *.xml, *.csv, *.zip
#   in2/     → *.jpg
# Lässt in/ (Soennecken-Bilder) bewusst unangetastet – die werden per ForFiles
# mit 60-Tage-Filter in bilder.py bereinigt.

import os
import glob
import logging
import datetime

log = logging.getLogger(__name__)


def run(progress_cb=None):
    from config import DIRS
    p = progress_cb or (lambda m: None)

    rules = [
        (DIRS["in_bme"], ["*.xml", "*.csv", "*.zip"]),
        (DIRS["in2"],    ["*.jpg"]),
    ]

    total = 0
    for directory, patterns in rules:
        if not os.path.isdir(directory):
            p(f"Aufräumen: Verzeichnis nicht vorhanden, überspringe: {directory}")
            continue
        for pattern in patterns:
            matches = glob.glob(os.path.join(directory, pattern))
            for path in matches:
                try:
                    os.remove(path)
                    total += 1
                    log.info(f"  gelöscht: {path}")
                except Exception as exc:
                    p(f"⚠ Konnte nicht löschen: {path} – {exc}", )
                    log.warning(f"Löschfehler: {path}: {exc}")

    p(f"✅ Aufräumen abgeschlossen – {total} Datei(en) gelöscht.")
    return total


def cleanup_logs(max_days: int = 30, progress_cb=None):
    """
    Löscht alte Dateien:
    - Log-Dateien älter als max_days
    - Lauf-Reports (lauf_*.json) älter als max_days
    - csv_autoimport_*.csv und Products_*.csv im BASE_DIR älter als max_days
    - Diff-Reports älter als 90 Tage
    - XML-Backups älter als 7 Tage (nur letztes Backup pro Datei behalten)
    """
    from config import DIRS
    import config as _cfg
    p       = progress_cb or (lambda m, **kw: None)
    cutoff  = datetime.datetime.now().timestamp() - max_days * 86400
    deleted = 0

    # Log-Dateien
    log_dir = DIRS["logs"]
    if os.path.isdir(log_dir):
        for pattern in ("Log_*.txt", "lauf_*.json"):
            for f in glob.glob(os.path.join(log_dir, pattern)):
                if os.path.getmtime(f) < cutoff:
                    os.remove(f)
                    deleted += 1

    # Alte Export-CSVs im Basisverzeichnis
    base = _cfg.BASE_DIR
    for pattern in ("csv_autoimport_*.csv", "Products_*.csv",
                    "csv_erp_*.csv", "csv_exchange_*.csv"):
        for f in glob.glob(os.path.join(base, pattern)):
            if os.path.getmtime(f) < cutoff:
                os.remove(f)
                deleted += 1

    # Diff-Reports und alte Snapshots (90 Tage)
    diff_dir = os.path.join(log_dir, "diff_backups")
    if os.path.isdir(diff_dir):
        cutoff_90 = datetime.datetime.now().timestamp() - 90 * 86400
        for f in glob.glob(os.path.join(diff_dir, "diff_*.json")):
            if os.path.getmtime(f) < cutoff_90:
                os.remove(f)
                deleted += 1

    # XML-Backups (nur letztes behalten, Rest nach 7 Tagen löschen)
    xml_backup_dir = os.path.join(log_dir, "xml_backups")
    if os.path.isdir(xml_backup_dir):
        cutoff_7 = datetime.datetime.now().timestamp() - 7 * 86400
        for f in glob.glob(os.path.join(xml_backup_dir, "*.xml")):
            if os.path.getmtime(f) < cutoff_7:
                os.remove(f)
                deleted += 1

    # Bilder-Snapshot nicht rotieren (wird überschrieben, nur 1 Datei)

    p(f"Log-Aufräumen: {deleted} alte Datei(en) gelöscht (>{max_days} Tage).")
