# tasks/nordwest.py
import os, glob, shutil, datetime, logging
from lib.ftp_client import make_client
from lib.utils import run_7zip as _run_7zip
from config import CONNECTIONS, DIRS, TOOLS


log = logging.getLogger(__name__)

NDW_CATALOGS = [
    ("arbeitsschutz.zip",   "bmecat.xml", "arbeitsschutz.xml"),
    ("werkstatt.zip",       "bmecat.xml", "werkstatt.xml"),
    ("werkzeugtechnik.zip", "bmecat.xml", "werkzeugtechnik.xml"),
]


def run(progress_cb=None, file_progress_cb=None):
    cfg     = CONNECTIONS["nordwest"]
    in_bme  = DIRS["in_bme"]
    ndw_sh  = DIRS["ndw_share"]
    seven_z = TOOLS["7zip"]
    p  = progress_cb      or (lambda m, **kw: None)
    fp = file_progress_cb or None

    client = make_client(cfg)
    client.connect()
    try:
        client.download("NDW/*.zip", in_bme, progress_cb=p, file_progress_cb=fp)
    finally:
        client.disconnect()

    for zip_name, xml_in, xml_out in NDW_CATALOGS:
        zp = os.path.join(in_bme, zip_name)
        if os.path.exists(zp):
            p(f"Nordwest: Entpacke {zip_name} ...")
            _run_7zip(seven_z, zp, in_bme, "*.xml", p)
            src = os.path.join(in_bme, xml_in)
            dst = os.path.join(in_bme, xml_out)
            if os.path.exists(src):
                os.replace(src, dst)  # replace statt rename: funktioniert auch wenn dst existiert

    # Kategorie-Check: neue NDW-Kategorien vs. custom_categories.csv
    try:
        from lib.category_check import check_supplier_categories
        import config as _cfg
        ndw_xmls = [os.path.join(in_bme, xml_out)
                    for _, _, xml_out in NDW_CATALOGS]
        check_supplier_categories(
            ndw_xmls, "NDW", _cfg.BASE_DIR, "Nordwest", progress_cb=p)
    except Exception as e:
        p(f"Kategorie-Check übersprungen: {e}", tag="dim")

    # UDX-Blöcke in allen drei XMLs in normale FEATURE-Blöcke umwandeln
    p("Nordwest: Konvertiere UDX → Features ...")
    from lib.bmecat_merge import convert_udx_to_features
    for _, _, xml_out in NDW_CATALOGS:
        xml_path = os.path.join(in_bme, xml_out)
        if os.path.exists(xml_path):
            convert_udx_to_features(xml_path, progress_cb=p)

    # FNAME-Transforms (vor Dedup, damit Rename-Duplikate erfasst werden)
    from lib.fname_transforms import apply_fname_transforms
    import config as _cfg
    for _, _, xml_out in NDW_CATALOGS:
        xml_path = os.path.join(in_bme, xml_out)
        if os.path.exists(xml_path):
            apply_fname_transforms(xml_path, _cfg.BASE_DIR, progress_cb=p)

    # Deduplizierung
    from tasks.others import dedup_xmls
    dedup_xmls([os.path.join(in_bme, xml_out) for _, _, xml_out in NDW_CATALOGS],
               progress_cb=p, file_progress_cb=fp)

    kip_zip = os.path.join(in_bme, "kip.zip")
    if os.path.exists(kip_zip):
        p("Nordwest: Entpacke KIP-CSV ...")
        _run_7zip(seven_z, kip_zip, in_bme, "artikel_t2.csv", p)
        datum = datetime.date.today().strftime("%d%m%Y")
        src   = os.path.join(in_bme, "artikel_t2.csv")
        dst   = os.path.join(in_bme, f"NDW{datum}.csv")
        if os.path.exists(src):
            os.replace(src, dst)
            if os.path.isdir(ndw_sh):
                shutil.move(dst, os.path.join(ndw_sh, os.path.basename(dst)))
                p(f"Nordwest: KIP-CSV -> {ndw_sh}", tag="ok")

        # Bestandsliste (Spalte 1 = native Artikelnummer ohne "NDW"-Präfix)
        p("Nordwest: Entpacke Bestandsliste ...")
        _run_7zip(seven_z, kip_zip, in_bme, "bestaende.csv", p)
        bestand_csv = os.path.join(in_bme, "bestaende.csv")
        if os.path.exists(bestand_csv):
            import config as _cfg
            from lib.bestandsdaten import import_nordwest_stock
            import_nordwest_stock(bestand_csv, _cfg.DB_PATH, progress_cb=p)
            os.remove(bestand_csv)

    for zf in glob.glob(os.path.join(in_bme, "*.zip")):
        os.remove(zf)

    p("Nordwest abgeschlossen.", tag="ok")

    from tasks.db_import import run_for_supplier
    run_for_supplier('nordwest', progress_cb=p)

    from tasks.others import upload_bmecat_xmls
    upload_bmecat_xmls(
        [os.path.join(in_bme, xml_out) for _, _, xml_out in NDW_CATALOGS],
        progress_cb=p, file_progress_cb=fp
    )


def download_only(progress_cb=None, file_progress_cb=None):
    """Nur Download-Phase — für parallele Ausführung."""
    cfg    = CONNECTIONS["nordwest"]
    in_bme = DIRS["in_bme"]
    p      = progress_cb      or (lambda m, **kw: None)
    fp     = file_progress_cb or None
    client = make_client(cfg)
    client.connect()
    try:
        client.download("NDW/*.zip", in_bme, progress_cb=p, file_progress_cb=fp)
    finally:
        client.disconnect()
    p("Nordwest Download abgeschlossen.")
