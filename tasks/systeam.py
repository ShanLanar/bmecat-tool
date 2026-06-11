# tasks/systeam.py
import os, logging
from lib.ftp_client import make_client
from lib.utils import run_7zip as _run_7zip
from config import CONNECTIONS, DIRS, TOOLS

log = logging.getLogger(__name__)


def run(progress_cb=None, file_progress_cb=None):
    cfg     = CONNECTIONS["systeam"]
    in_bme  = DIRS["in_bme"]
    seven_z = TOOLS["7zip"]
    p  = progress_cb      or (lambda m, **kw: None)
    fp = file_progress_cb or None

    client = make_client(cfg)
    client.connect()
    try:
        client.download("PRICE/BMECAT*.zip", in_bme,
                        progress_cb=p, file_progress_cb=fp)
    finally:
        client.disconnect()

    zip_path = os.path.join(in_bme, "BMECAT_137942.ZIP")
    if os.path.exists(zip_path):
        p("Systeam: Entpacke ZIP ...")
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        _run_7zip(seven_z, zip_path, root, p=p)
        src = os.path.join(root, "A137942.txt")
        if os.path.exists(src):
            os.replace(src, os.path.join(in_bme, "systeam.xml"))
        os.remove(zip_path)

    p("Systeam abgeschlossen.", tag="ok")

    # FNAME-Transforms (vor Dedup, damit Rename-Duplikate erfasst werden)
    from lib.fname_transforms import apply_fname_transforms
    import config as _cfg
    systeam_xml = os.path.join(in_bme, "systeam.xml")
    if os.path.exists(systeam_xml):
        apply_fname_transforms(systeam_xml, _cfg.BASE_DIR, progress_cb=p)

    from tasks.others import dedup_xmls
    dedup_xmls([os.path.join(in_bme, "systeam.xml")],
               progress_cb=p, file_progress_cb=fp)
