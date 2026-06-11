# tasks/parallel_download.py – Parallele Downloads aller Lieferanten
#
# Lädt Büroring, Softcarrier und Nordwest gleichzeitig herunter.
# Spart ~3 Minuten gegenüber sequenziellem Ablauf.
#
# Wichtig: Nur Download-Phase. Merge/Upload laufen danach sequenziell
# in den jeweiligen Einzel-Tasks.

import logging
from lib.parallel import run_parallel

log = logging.getLogger(__name__)


def run(progress_cb=None, file_progress_cb=None):
    """
    Alle drei Lieferanten gleichzeitig herunterladen.

    Danach müssen die Einzel-Tasks (Büroring, Softcarrier, Nordwest)
    mit deaktiviertem Download laufen — oder separat gemanagte Tasks.
    """
    p  = progress_cb      or (lambda m, **kw: None)
    fp = file_progress_cb or None

    from tasks.bueroring   import download_sources as dl_br
    from tasks.softcarrier import download_only    as dl_sc
    from tasks.nordwest    import download_only    as dl_nw

    p("Starte parallele Downloads: Büroring + Softcarrier + Nordwest ...")

    results = run_parallel([
        ("Büroring",    dl_br, p, fp),
        ("Softcarrier", dl_sc, p, fp),
        ("Nordwest",    dl_nw, p, fp),
    ], max_workers=3, progress_cb=p)

    failed = [name for name, r in results.items() if not r["ok"]]
    if failed:
        p(f"⚠ Download fehlgeschlagen: {', '.join(failed)}", tag="warn")
        p("Tipp: Betroffene Lieferanten-Tasks einzeln ausführen um Details zu sehen.",
          tag="dim")
    else:
        p("Alle Downloads erfolgreich. Jetzt Einzel-Tasks für Merge/Upload starten.",
          tag="ok")

    return results
