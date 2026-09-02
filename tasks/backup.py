# tasks/backup.py – Backup/Restore alles außerhalb von Git (Server-Umzug)
#
# Backup:  BASE_DIR-Dateien, die git nicht kennt → ZIP → CONNECTIONS["backup"]
# Restore: neuestes ZIP von CONNECTIONS["backup"] → BASE_DIR/restore_review/
#          (entpackt NEBEN die laufende Installation, überschreibt nichts
#          automatisch – manuell rüberkopieren nach Kontrolle)

import os
import glob
from config import BASE_DIR, DIRS, CONNECTIONS


def _backup_ready(cfg: dict) -> bool:
    return bool(cfg.get("host") and cfg.get("user"))


def run_backup_create(progress_cb=None, file_progress_cb=None) -> dict:
    """Alles was nicht in Git liegt (Config, DB, live Config-CSVs) als ZIP sichern + hochladen."""
    p  = progress_cb      or (lambda m, **kw: None)
    fp = file_progress_cb or None
    from lib.backup_restore import create_backup

    cfg = CONNECTIONS["backup"]
    if not _backup_ready(cfg):
        p("Backup: CONNECTIONS['backup'] ist noch nicht konfiguriert – "
          "bitte über Konfiguration → Verbindungen eintragen.", tag="warn")
        return {}

    out_dir  = DIRS.get("logs", BASE_DIR)
    zip_path = create_backup(BASE_DIR, out_dir, progress_cb=p)
    if not zip_path:
        return {}

    from lib.ftp_client import make_client
    p(f"Backup: Upload → {cfg['host']}{cfg.get('remote_path', '/')} ...")
    client = make_client(cfg)
    client.connect()
    try:
        client.upload(zip_path, cfg.get("remote_path", "/"),
                      progress_cb=p, file_progress_cb=fp)
    finally:
        client.disconnect()

    p(f"Backup abgeschlossen. Lokale Kopie bleibt in {out_dir} erhalten.",
      tag="ok")
    return {"zip": zip_path}


def run_backup_restore(progress_cb=None, file_progress_cb=None) -> dict:
    """
    Neuestes Backup von CONNECTIONS["backup"] herunterladen und nach
    BASE_DIR/restore_review/<Zeitstempel>/ entpacken – NICHT automatisch
    über die laufende Installation kopieren.
    """
    p  = progress_cb      or (lambda m, **kw: None)
    fp = file_progress_cb or None
    from lib.backup_restore import extract_backup, BACKUP_PREFIX

    cfg = CONNECTIONS["backup"]
    if not _backup_ready(cfg):
        p("Restore: CONNECTIONS['backup'] ist noch nicht konfiguriert – "
          "bitte über Konfiguration → Verbindungen eintragen.", tag="warn")
        return {}

    dl_dir = os.path.join(DIRS.get("logs", BASE_DIR), "restore_download")
    os.makedirs(dl_dir, exist_ok=True)
    # Alte heruntergeladene ZIPs aus vorherigen Restore-Versuchen entfernen,
    # damit latest_only nicht versehentlich eine alte Datei erwischt.
    for old in glob.glob(os.path.join(dl_dir, f"{BACKUP_PREFIX}*.zip")):
        os.remove(old)

    from lib.ftp_client import make_client
    p(f"Restore: suche neuestes Backup auf {cfg['host']} ...")
    client = make_client(cfg)
    client.connect()
    try:
        downloaded = client.download(
            os.path.join(cfg.get("remote_path", "/"), f"{BACKUP_PREFIX}*.zip"),
            dl_dir, latest_only=True, progress_cb=p, file_progress_cb=fp)
    finally:
        client.disconnect()

    if not downloaded:
        p("Restore: kein Backup auf dem Server gefunden.", tag="warn")
        return {}

    zip_path = downloaded[0] if isinstance(downloaded, list) else downloaded
    ts = os.path.splitext(os.path.basename(zip_path))[0].replace(
        "bmecat_backup_", "")
    target_dir = os.path.join(BASE_DIR, "restore_review", ts)
    n = extract_backup(zip_path, target_dir, progress_cb=p)

    p(f"Restore: {n} Dateien liegen jetzt in "
      f"restore_review/{ts}/ – bitte manuell prüfen und nach BASE_DIR "
      f"kopieren (überschreibt bewusst nichts automatisch).", tag="ok")
    return {"extracted": n, "target_dir": target_dir}
