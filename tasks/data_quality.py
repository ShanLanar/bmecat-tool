# tasks/data_quality.py – Datenqualitäts-Reports für Marktplätze
#
# Prüft die Artikel-DB (lieferantenübergreifend, nach dem letzten Import)
# auf Lücken, die auf Marktplätzen (Unite, Brickfox-Kanäle: Conrad/Kaufland/
# Netto, Otto) zu schlechterer Sichtbarkeit oder Ablehnung führen können.

import os
from config import DB_PATH, DIRS


def run_description_quality(progress_cb=None, file_progress_cb=None) -> dict:
    p = progress_cb or (lambda m, **kw: None)

    from lib.description_quality_report import generate_report
    out_dir = DIRS.get("logs", ".")
    result  = generate_report(DB_PATH, out_dir, progress_cb=p)

    try:
        import subprocess
        subprocess.Popen(f'explorer "{out_dir}"', shell=True)
    except Exception:
        pass

    return result
