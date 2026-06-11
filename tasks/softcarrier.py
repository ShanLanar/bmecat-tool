# tasks/softcarrier.py
import os, json, logging
from pathlib import Path
from lib.ftp_client import make_client
from lib.utils import run_7zip as _run_7zip, glob_ci
from config import CONNECTIONS, DIRS, TOOLS

log = logging.getLogger(__name__)

# Snapshot-Datei: speichert {filename: size} des letzten Uploads
_SNAPSHOT_FILE = os.path.join(DIRS.get("logs", "."), "bilder_snapshot.json")


def _load_snapshot() -> dict:
    """Lädt den letzten Bilder-Snapshot (Dateiname → Größe)."""
    try:
        with open(_SNAPSHOT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_snapshot(snapshot: dict):
    """Speichert den aktuellen Bilder-Snapshot."""
    Path(os.path.dirname(_SNAPSHOT_FILE)).mkdir(parents=True, exist_ok=True)
    try:
        with open(_SNAPSHOT_FILE, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False)
    except Exception as e:
        log.warning("Bilder-Snapshot konnte nicht gespeichert werden: %s", e)


def _compute_delta(jpg_dir: str, previous: dict) -> tuple[list, dict]:
    """
    Vergleicht aktuelle JPGs mit dem letzten Snapshot.

    Returns:
        (changed_files, new_snapshot)
        changed_files: Pfade der neuen/geänderten JPGs
        new_snapshot:  aktueller Stand {filename: size}
    """
    current = {}
    changed = []
    for path in glob_ci(jpg_dir, "jpg"):
        bn   = os.path.basename(path)
        size = os.path.getsize(path)
        current[bn] = size
        if bn not in previous or previous[bn] != size:
            changed.append(path)

    return changed, current


def _upload_bilder(jpg_dir: str, p, fp):
    """
    Benennt alle JPGs in jpg_dir mit SOC_-Präfix um (falls noch nicht vorhanden)
    und lädt nur neue/geänderte Bilder auf Allago und OfficeXL hoch (Delta-Upload).
    """
    jpgs = glob_ci(jpg_dir, "jpg")

    if not jpgs:
        p("Softcarrier Bilder: keine JPGs gefunden.", tag="warn")
        return

    # SOC_-Präfix vergeben
    renamed = []
    for src in jpgs:
        bn = os.path.basename(src)
        if not bn.upper().startswith("SOC"):
            dst = os.path.join(jpg_dir, "SOC" + bn)
            os.replace(src, dst)
            renamed.append(dst)
        else:
            renamed.append(src)

    p(f"Softcarrier Bilder: {len(renamed)} JPGs (SOC-Präfix gesetzt).")

    # Delta berechnen
    previous = _load_snapshot()
    changed, new_snapshot = _compute_delta(jpg_dir, previous)

    if not changed:
        p(f"Softcarrier Bilder: keine Änderungen seit dem letzten Lauf "
          f"({len(renamed)} Dateien unverändert).", tag="ok")
        return

    skipped = len(renamed) - len(changed)
    p(f"Softcarrier Bilder: {len(changed)} geändert/neu, "
      f"{skipped} unverändert → nur Delta hochladen.")

    for conn_key, label in [("allago_images", "Allago"), ("officexl_images", "OfficeXL")]:
        cfg = CONNECTIONS[conn_key]
        p(f"Softcarrier Bilder → {label} ({len(changed)} Dateien) ...")
        cl = make_client(cfg)
        cl.connect()
        try:
            for jpg in changed:
                cl.upload(jpg, cfg["remote_path_thumbs"],
                          progress_cb=p, file_progress_cb=fp)
        finally:
            cl.disconnect()
        p(f"  {label}: {len(changed)} Bilder hochgeladen.", tag="ok")

    # Snapshot erst NACH erfolgreichem Upload auf beiden Servern speichern
    _save_snapshot(new_snapshot)
    p(f"Bilder-Snapshot gespeichert ({len(new_snapshot)} Dateien).", tag="dim")


def run(progress_cb=None, file_progress_cb=None):
    cfg     = CONNECTIONS["softcarrier"]
    in_bme  = DIRS["in_bme"]
    in_dir  = DIRS["in"]
    seven_z = TOOLS["7zip"]
    p  = progress_cb      or (lambda m, **kw: None)
    fp = file_progress_cb or None

    # Stagingverzeichnis für Softcarrier-Bilder
    img_dir = os.path.join(in_bme, "soc_bilder")
    os.makedirs(img_dir, exist_ok=True)

    client = make_client(cfg)
    client.connect()
    try:
        client.download("Lagerbestand/lagerbestand.csv", in_bme,
                        progress_cb=p, file_progress_cb=fp)
        client.download("Artikeldaten deutsch/FULL/XML.ZIP", in_bme,
                        progress_cb=p, file_progress_cb=fp)
        client.download("Artikeldaten deutsch/FULL/HERSTINFO.CSV", in_bme,
                        progress_cb=p, file_progress_cb=fp)
        client.download("Artikeldaten deutsch/FULL/DATA.ZIP", in_bme,
                        progress_cb=p, file_progress_cb=fp)
        client.download("Artikeldaten deutsch/FULL/PREVIEW.ZIP", in_bme,
                        progress_cb=p, file_progress_cb=fp)
    finally:
        client.disconnect()

    lager = os.path.join(in_bme, "lagerbestand.csv")
    if os.path.exists(lager):
        os.replace(lager, os.path.join(in_bme, "soc_bestand.csv"))

    herstinfo = os.path.join(in_bme, "HERSTINFO.CSV")
    if os.path.exists(herstinfo):
        os.replace(herstinfo, os.path.join(in_bme, "softcarrier_HERSTINFO.CSV"))

    xml_zip = os.path.join(in_bme, "XML.ZIP")
    if os.path.exists(xml_zip):
        p("Softcarrier: Entpacke XML.ZIP ...")
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        _run_7zip(seven_z, xml_zip, root, p=p)
        src = os.path.join(root, "soft-carrier.xml")
        if os.path.exists(src):
            os.replace(src, os.path.join(in_bme, "soft-carrier.xml"))
        os.remove(xml_zip)

        # Kategorie-Check: neue SOC-Kategorien vs. custom_categories.csv
        try:
            from lib.category_check import check_new_categories
            import config as _cfg
            check_new_categories(
                os.path.join(in_bme, "soft-carrier.xml"), "SOC",
                _cfg.BASE_DIR, "Softcarrier", progress_cb=p)
        except Exception as e:
            p(f"Kategorie-Check übersprungen: {e}", tag="dim")

    # DATA.ZIP entpacken
    data_zip = os.path.join(in_bme, "DATA.ZIP")
    if not os.path.exists(data_zip):
        data_zip = os.path.join(in_bme, "data.zip")
    if os.path.exists(data_zip):
        p("Softcarrier: Entpacke DATA.ZIP ...")
        _run_7zip(seven_z, data_zip, in_bme, p=p)
        os.remove(data_zip)

    for name in ("DATA.CSV", "data.csv"):
        src = os.path.join(in_bme, name)
        if os.path.exists(src):
            os.replace(src, os.path.join(in_bme, "softcarrier_data.csv"))
            break

    # PREVIEW.ZIP entpacken → soc_bilder/
    preview_zip = os.path.join(in_bme, "PREVIEW.ZIP")
    if not os.path.exists(preview_zip):
        preview_zip = os.path.join(in_bme, "preview.zip")
    if os.path.exists(preview_zip):
        p("Softcarrier: Entpacke PREVIEW.ZIP ...")
        # Altes Stagingverzeichnis leeren
        for old in glob_ci(img_dir, "jpg"):
            os.remove(old)
        _run_7zip(seven_z, preview_zip, img_dir, p=p)
        os.remove(preview_zip)
        jpg_count = len(glob_ci(img_dir, "jpg"))
        p(f"Softcarrier: {jpg_count} Vorschaubilder entpackt.", tag="ok")
    else:
        p("Softcarrier: PREVIEW.ZIP nicht gefunden – überspringe Bilder.", tag="warn")
        img_dir = None

    p("Softcarrier abgeschlossen.", tag="ok")

    # TAB-Features + GPSR in soft-carrier_merge.xml zusammenführen
    from tasks.softcarrier_merge import run as run_merge
    run_merge(progress_cb=p, file_progress_cb=fp)

    from tasks.others import dedup_xmls
    dedup_xmls([os.path.join(in_bme, "soft-carrier.xml"),
                os.path.join(in_bme, "soft-carrier_merge.xml")],
               progress_cb=p, file_progress_cb=fp)

    from tasks.others import upload_bmecat_xmls
    upload_bmecat_xmls(
        [os.path.join(in_bme, "soft-carrier_merge.xml")],
        progress_cb=p, file_progress_cb=fp
    )

    # Bilder-Upload ist jetzt ein separater Task ("Softcarrier – Bilder")
    # und wird NICHT mehr hier aufgerufen.


def run_bilder(progress_cb=None, file_progress_cb=None):
    """
    Softcarrier-Bilder auf Allago + OfficeXL hochladen (Delta-Upload).
    Eigenständiger Task – blockiert nicht den Nordwest-Upload.
    """
    p  = progress_cb      or (lambda m, **kw: None)
    fp = file_progress_cb or None

    img_dir = os.path.join(DIRS["in_bme"], "soc_bilder")
    if os.path.isdir(img_dir) and glob_ci(img_dir, "jpg"):
        _upload_bilder(img_dir, p, fp)
    else:
        p("Softcarrier Bilder: Verzeichnis leer oder nicht vorhanden – "
          "bitte zuerst 'Softcarrier – Komplett' ausführen.", tag="warn")



def download_only(progress_cb=None, file_progress_cb=None):
    """Nur Download-Phase — für parallele Ausführung."""
    cfg    = CONNECTIONS["softcarrier"]
    in_bme = DIRS["in_bme"]
    p      = progress_cb      or (lambda m, **kw: None)
    fp     = file_progress_cb or None
    client = make_client(cfg)
    client.connect()
    try:
        client.download("Lagerbestand/lagerbestand.csv",          in_bme, progress_cb=p, file_progress_cb=fp)
        client.download("Artikeldaten deutsch/FULL/XML.ZIP",      in_bme, progress_cb=p, file_progress_cb=fp)
        client.download("Artikeldaten deutsch/FULL/HERSTINFO.CSV",in_bme, progress_cb=p, file_progress_cb=fp)
        client.download("Artikeldaten deutsch/FULL/DATA.ZIP",     in_bme, progress_cb=p, file_progress_cb=fp)
        client.download("Artikeldaten deutsch/FULL/PREVIEW.ZIP",  in_bme, progress_cb=p, file_progress_cb=fp)
    finally:
        client.disconnect()
    p("Softcarrier Download abgeschlossen.")
