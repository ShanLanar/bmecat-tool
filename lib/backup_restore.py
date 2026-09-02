# lib/backup_restore.py – Backup/Restore für alles, was NICHT in Git liegt
#
# Betrifft: config_user.json, .fernet.key, article_db.sqlite (+ -wal/-shm),
# live editierte Config-CSVs direkt in BASE_DIR (Git kennt nur die leeren
# Vorlagen unter templates/), Bestand_und_Preise.xlsx, channels/*.csv usw.
#
# Dateiauswahl: alles, was `git ls-files --others` (ignoriert + nicht
# ignoriert) in BASE_DIR zurückgibt, abzüglich rein transienter/regenerier-
# barer Arbeitsverzeichnisse (in_BME, logs, Downloads-Zwischenstände …).
# Fällt git aus irgendeinem Grund aus (kein Git installiert, BASE_DIR kein
# Repo), greift eine statische Mindestliste als Fallback.
#
# Ziel: CONNECTIONS["backup"] (FTP/SFTP, Zugangsdaten über den
# Konfigurationseditor eintragen). Für Server-Umzüge: Code kommt per
# `git pull` auf den neuen Server, alles andere über dieses Backup/Restore.

import os
import subprocess
import zipfile
import logging
from datetime import datetime

log = logging.getLogger(__name__)

BACKUP_PREFIX = "bmecat_backup_"

# Top-Level-Verzeichnisse (relativ zu BASE_DIR), die NIE ins Backup gehören –
# rein transiente Downloads/Exports, die jeder Lauf neu erzeugt.
_EXCLUDE_DIRS = {
    "logs", "in_BME", "in", "in2", "in_vertrieb", "unzip", "export_vendosys",
    "backups", "brickfox", "eBay", "__pycache__", ".git", "restore_review",
}

# Fallback falls git nicht verfügbar ist – deckt die kritischsten Dateien ab.
_FALLBACK_FILES = [
    "config_user.json", ".fernet.key", "article_db.sqlite",
    "article_db.sqlite-wal", "article_db.sqlite-shm",
    "Bestand_und_Preise.xlsx", "eBay-edit-price-quantity-template.csv",
    "BestandBueroring.csv",
]
try:
    from lib.first_run import TEMPLATE_FILES as _FALLBACK_TEMPLATE_FILES
    _FALLBACK_FILES += _FALLBACK_TEMPLATE_FILES
except Exception:
    pass


def _git_untracked_files(base_dir: str) -> list[str] | None:
    """
    Alle Dateien in base_dir, die git NICHT als getrackt kennt (egal ob
    durch .gitignore erfasst oder einfach nie hinzugefügt) – relative Pfade.
    None wenn git nicht verfügbar / base_dir kein Repo ist.
    """
    try:
        result = subprocess.run(
            ["git", "-C", base_dir, "ls-files", "--others", "--exclude-standard"],
            capture_output=True, text=True, timeout=30)
        result_ignored = subprocess.run(
            ["git", "-C", base_dir, "ls-files", "--others", "--ignored", "--exclude-standard"],
            capture_output=True, text=True, timeout=30)
        if result.returncode != 0 or result_ignored.returncode != 0:
            return None
        files = set(result.stdout.splitlines()) | set(result_ignored.stdout.splitlines())
        return sorted(f for f in files if f.strip())
    except Exception as e:
        log.debug(f"git ls-files fehlgeschlagen: {e}")
        return None


def _is_excluded(rel_path: str) -> bool:
    top = rel_path.split("/")[0].split(os.sep)[0]
    return top in _EXCLUDE_DIRS


def collect_backup_files(base_dir: str, progress_cb=None) -> list[str]:
    """Relative Pfade (ab base_dir) aller Dateien, die ins Backup gehören."""
    p = progress_cb or (lambda m, **kw: None)

    untracked = _git_untracked_files(base_dir)
    if untracked is not None:
        files = [f for f in untracked if not _is_excluded(f)]
        p(f"Backup: {len(files)} nicht in Git verwaltete Dateien gefunden "
          f"(git-basiert).")
    else:
        p("Backup: git nicht verfügbar – nutze statische Mindestliste.", tag="warn")
        files = [f for f in _FALLBACK_FILES
                if os.path.exists(os.path.join(base_dir, f))]

    return files


def create_backup(base_dir: str, out_dir: str, progress_cb=None) -> str | None:
    """
    Packt alle nicht in Git verwalteten Dateien in ein ZIP
    (bmecat_backup_<Zeitstempel>.zip in out_dir). Gibt den Pfad zurück.
    """
    p = progress_cb or (lambda m, **kw: None)
    files = collect_backup_files(base_dir, progress_cb=p)
    if not files:
        p("Backup: keine Dateien gefunden – nichts zu sichern.", tag="warn")
        return None

    os.makedirs(out_dir, exist_ok=True)
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_name = f"{BACKUP_PREFIX}{ts}.zip"
    zip_path = os.path.join(out_dir, zip_name)

    written = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in files:
            src = os.path.join(base_dir, rel)
            if not os.path.isfile(src):
                continue
            zf.write(src, arcname=rel)
            written += 1

    size_mb = os.path.getsize(zip_path) / 1_048_576
    p(f"Backup erstellt: {zip_name}  ({written} Dateien, {size_mb:.1f} MB)",
      tag="ok")
    return zip_path


def extract_backup(zip_path: str, target_dir: str, progress_cb=None) -> int:
    """Entpackt zip_path komplett nach target_dir. Gibt Dateianzahl zurück."""
    p = progress_cb or (lambda m, **kw: None)
    os.makedirs(target_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        zf.extractall(target_dir)
    p(f"Backup entpackt: {len(names)} Dateien → {target_dir}", tag="ok")
    return len(names)
