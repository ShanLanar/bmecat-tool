# tasks/others.py
import os, glob, datetime, logging
from lib.ftp_client import make_client
from lib.utils import run_7zip as _run_7zip
from config import CONNECTIONS, DIRS, TOOLS, AVAILABILITY_FILE


def dedup_xmls(xml_paths: list, progress_cb=None, file_progress_cb=None):
    """Dedupliziert FNAMEs in einer Liste von XML-Dateien."""
    from lib.bmecat_merge import deduplicate_files
    p = progress_cb or (lambda m, **kw: None)
    p("FNAME-Deduplizierung ...")
    return deduplicate_files(xml_paths, progress_cb=p)


def upload_bmecat_xmls(xml_paths: list, progress_cb=None, file_progress_cb=None):
    """
    Lädt XML-Dateien auf Brickfox /incoming hoch.
    Merged-Dateien werden unter ihrem Originalnamen hochgeladen:
      bueroring_merged.xml  → bueroring.xml
      soft-carrier_merge.xml → soft-carrier.xml
    Fehlende Dateien werden übersprungen (mit Warnung).
    Vor dem Upload: XML-Validierung und Diff-Report.
    """
    from config import CONNECTIONS
    p  = progress_cb      or (lambda m, **kw: None)
    fp = file_progress_cb or None
    cfg = CONNECTIONS["brickfox_bmecat"]

    # Umbenennungsregeln: lokaler Dateiname → Zieldateiname auf Server
    rename_map = {
        "bueroring_merged.xml":   "bueroring.xml",
        "soft-carrier_merge.xml": "soft-carrier.xml",
    }

    existing = [f for f in xml_paths if os.path.exists(f)]
    missing  = [f for f in xml_paths if not os.path.exists(f)]

    for f in missing:
        p(f"Brickfox XML-Upload: überspringe (nicht gefunden): {os.path.basename(f)}", tag="warn")

    if not existing:
        p("Brickfox XML-Upload: keine Dateien zum Hochladen.", tag="warn")
        return

    # XML-Validierung vor Upload
    try:
        from lib.xml_validator import validate_before_upload
        validate_before_upload(existing, progress_cb=p)
    except Exception as e:
        p(f"XML-Validierung übersprungen: {e}", tag="warn")

    # Diff-Report (Vergleich mit letztem Lauf)
    try:
        from lib.diff_report import create_diff_report
        for path in existing:
            create_diff_report(path, progress_cb=p)
    except Exception as e:
        p(f"Diff-Report übersprungen: {e}", tag="warn")

    # XML-Rollback: Backup der aktuellen Dateien vor dem Upload
    try:
        import shutil
        from pathlib import Path
        backup_dir = os.path.join(DIRS.get("logs", "."), "xml_backups")
        Path(backup_dir).mkdir(parents=True, exist_ok=True)
        for path in existing:
            bn = os.path.basename(path)
            backup_path = os.path.join(backup_dir, bn)
            shutil.copy2(path, backup_path)
        p(f"XML-Backup: {len(existing)} Dateien gesichert → xml_backups/", tag="dim")
    except Exception as e:
        p(f"XML-Backup übersprungen: {e}", tag="warn")

    p(f"Brickfox XML-Upload → {cfg['remote_path']} ({len(existing)} Dateien) ...")
    cl = make_client(cfg)
    cl.connect()
    try:
        for path in existing:
            bn          = os.path.basename(path)
            target_name = rename_map.get(bn, bn)
            # Temporäre Kopie mit Zielnamen falls Umbenennung nötig
            if target_name != bn:
                import shutil, tempfile
                tmp_dir  = tempfile.mkdtemp()
                tmp_path = os.path.join(tmp_dir, target_name)
                shutil.copy2(path, tmp_path)
                cl.upload(tmp_path, cfg["remote_path"],
                          progress_cb=p, file_progress_cb=fp)
                shutil.rmtree(tmp_dir, ignore_errors=True)
                p(f"  {bn} → hochgeladen als {target_name}", tag="ok")
            else:
                cl.upload(path, cfg["remote_path"],
                          progress_cb=p, file_progress_cb=fp)
    finally:
        cl.disconnect()
    p("Brickfox XML-Upload abgeschlossen.", tag="ok")


log = logging.getLogger(__name__)


# ── Mercateo ──────────────────────────────────────────────────────────────────

def upload_mercateo_files(paths: list, progress_cb=None, file_progress_cb=None):
    """
    Lädt Bestands-/Conditionsfile-CSVs (availability-data-catalog-32WQS.csv,
    32WQS_conditionsfile.csv) nach Mercateo-Unite /catalog/32WQS hoch.
    Fehlende Dateien werden übersprungen (mit Warnung). Dateien bleiben lokal
    erhalten (kein delete_after) – anders als upload_availability(), da
    nachfolgende Läufe (Mindest-Abgleich, ATP-Merge) sie weiter lesen.
    """
    cfg = CONNECTIONS["mercateo"]
    p   = progress_cb      or (lambda m, **kw: None)
    fp  = file_progress_cb or None

    existing = [f for f in paths if os.path.exists(f)]
    for f in paths:
        if f not in existing:
            p(f"Mercateo-Upload: übersprungen (nicht gefunden): {os.path.basename(f)}", tag="warn")
    if not existing:
        return

    p("Mercateo-Upload: verbinde ...")
    client = make_client(cfg)
    client.connect()
    try:
        for path in existing:
            client.upload(path, cfg["remote_path"],
                          progress_cb=p, file_progress_cb=fp)
    finally:
        client.disconnect()
    p("Mercateo-Upload abgeschlossen.", tag="ok")


# ── Bestandsdaten (standalone) ────────────────────────────────────────────────

def run_bestandsdaten_only(progress_cb=None):
    from lib.bestandsdaten import erstelle_bestandsdaten
    p   = progress_cb or (lambda m, **kw: None)
    out = os.path.join(DIRS["in_bme"], AVAILABILITY_FILE)
    erstelle_bestandsdaten(DIRS["in_bme"], out, progress_cb=p)


# ── Bilder-Upload ─────────────────────────────────────────────────────────────

def run_bilder(progress_cb=None, file_progress_cb=None):
    in_dir   = DIRS["in"]
    vertrieb = DIRS["vertrieb"]
    seven_z  = TOOLS["7zip"]
    p  = progress_cb      or (lambda m, **kw: None)
    fp = file_progress_cb or None

    zip_path = os.path.join(in_dir, "Bilder_archive.zip")
    if os.path.exists(zip_path):
        p("Bilder: Entpacke Bilder_archive.zip ...")
        _run_7zip(seven_z, zip_path, in_dir, "*.jpg", p)

    cutoff  = datetime.datetime.now().timestamp() - 60 * 86400
    deleted = sum(
        1 for jpg in glob.glob(os.path.join(in_dir, "*.jpg"))
        if os.path.getmtime(jpg) < cutoff and not os.remove(jpg)
    )
    if deleted:
        p(f"Bilder: {deleted} alte JPGs geloescht (>60 Tage).")

    allago = CONNECTIONS["allago_images"]
    p("Bilder: Upload -> Allago ...")
    cl = make_client(allago)
    cl.connect()
    try:
        cl.upload(os.path.join(in_dir,   "*.jpg"), allago["remote_path_thumbs"],
                  progress_cb=p, file_progress_cb=fp)
        cl.upload(os.path.join(vertrieb, "*.jpg"), allago["remote_path_thumbs"],
                  progress_cb=p, file_progress_cb=fp)
        cl.upload(os.path.join(vertrieb, "category", "*.jpg"), allago["remote_path_category"],
                  progress_cb=p, file_progress_cb=fp)
        cl.upload(os.path.join(vertrieb, "category", "*.png"), allago["remote_path_category"],
                  progress_cb=p, file_progress_cb=fp)
    finally:
        cl.disconnect()

    oxl = CONNECTIONS["officexl_images"]
    p("Bilder: Upload -> OfficeXL ...")
    cl2 = make_client(oxl)
    cl2.connect()
    try:
        cl2.upload(os.path.join(in_dir,   "*.jpg"), oxl["remote_path_thumbs"],
                   delete_after=True, progress_cb=p, file_progress_cb=fp)
        cl2.upload(os.path.join(vertrieb, "*.jpg"), oxl["remote_path_thumbs"],
                   delete_after=True, progress_cb=p, file_progress_cb=fp)
        cl2.upload(os.path.join(vertrieb, "category", "*.jpg"), oxl["remote_path_category"],
                   delete_after=True, progress_cb=p, file_progress_cb=fp)
        cl2.upload(os.path.join(vertrieb, "category", "*.png"), oxl["remote_path_category"],
                   delete_after=True, progress_cb=p, file_progress_cb=fp)
    finally:
        cl2.disconnect()

    p("Bilder-Upload abgeschlossen.", tag="ok")


# ── Soennecken (vorbereitet, in BAT auskommentiert) ───────────────────────────

def run_soennecken(progress_cb=None, file_progress_cb=None):
    cfg    = CONNECTIONS["soennecken"]
    in_bme = DIRS["in_bme"]
    in_dir = DIRS["in"]
    p  = progress_cb      or (lambda m, **kw: None)
    fp = file_progress_cb or None

    client = make_client(cfg)
    client.connect()
    try:
        client.download("BMEcat/bmecatabe__20*.xml", in_bme,
                        latest_only=True, progress_cb=p, file_progress_cb=fp)
        client.download("BMEcat/Bilder_archive.zip", in_dir,
                        progress_cb=p, file_progress_cb=fp)
    finally:
        client.disconnect()

    for f in glob.glob(os.path.join(in_bme, "bmecatabe__*.xml")):
        os.replace(f, os.path.join(in_bme, "soennecken_vk3.xml"))

    p("Soennecken abgeschlossen.", tag="ok")
