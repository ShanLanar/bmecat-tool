# tasks/softcarrier_img_patch.py – Softcarrier Bild-Patch (pHash-Matching)
#
# Einmalig ausführen wenn die Softcarrier-Bild-ZIPs lokal vorliegen.
# Erzeugt sc_image_patch.csv in BASE_DIR:
#   supplier_aid ; old_mime_source ; new_folder ; new_image ; hamming_dist ; qualitaet
#
# Die CSV wird danach von softcarrier_merge.py automatisch geladen und
# patcht MIME_SOURCE pro Artikel:
#   <SOURCE>39672.jpg</SOURCE>  →  <SOURCE>39672_302.jpg</SOURCE>
#
# Voraussetzungen:
#   • Softcarrier-Bild-ZIPs lokal unter DIRS["sc_bilder_zips"] oder
#     entpackter Ordner unter DIRS["sc_bilder_dir"]
#   • pip install Pillow imagehash requests (einmalig)
#   • soft-carrier.xml bereits in in_BME/ (für affected-Analyse)
#
# Laufzeit: ~30–90 Minuten für ~51.000 Artikel (4 Worker, inkl. Thumbnail-Download)

import os
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def run(progress_cb=None):
    from config import BASE_DIR, DIRS
    from lib.sc_image_patch import (
        build_index, find_affected, run_matching,
        PATCH_FILENAME, check_deps
    )

    p = progress_cb or (lambda m, **kw: None)

    p("┌─ Softcarrier Bild-Patch (pHash-Matching) ──────────────────")
    p("│  Ziel: MIME_SOURCE per Artikel eindeutig machen")
    p("│  Quelle:  Bild-ZIPs (GRAPHIK1-9.ZIP) lokal")
    p("│  Matching: pHash vs. Thumbnails auf softcarrier.de")
    p(f"│  Ausgabe: {PATCH_FILENAME}  (in BASE_DIR)")
    p("└────────────────────────────────────────────────────────────")

    # Abhängigkeiten prüfen
    missing = check_deps()
    if missing:
        raise RuntimeError(
            f"Fehlende Python-Pakete: {', '.join(missing)}\n"
            f"Bitte installieren: py -m pip install {' '.join(missing)}"
        )

    # Bildquell-Verzeichnis ermitteln
    zip_dir = None
    img_dir = None

    sc_zips = DIRS.get("sc_bilder_zips", "")
    sc_dir  = DIRS.get("sc_bilder_dir", "")

    if sc_zips and os.path.isdir(sc_zips):
        zip_dir = Path(sc_zips)
        p(f"  ZIP-Verzeichnis: {sc_zips}")
    elif sc_dir and os.path.isdir(sc_dir):
        img_dir = Path(sc_dir)
        p(f"  Bildverzeichnis (entpackt): {sc_dir}")
    else:
        raise FileNotFoundError(
            "Kein Bildverzeichnis konfiguriert.\n"
            "Bitte in config_user.json setzen:\n"
            "  DIRS.sc_bilder_zips = 'C:\\\\Pfad\\\\zu\\\\GRAPHIK-ZIPs'\n"
            "  (oder DIRS.sc_bilder_dir für entpackten Ordner)"
        )

    # soft-carrier.xml für Analyse der betroffenen Artikel
    in_bme   = DIRS["in_bme"]
    xml_path = os.path.join(in_bme, "soft-carrier.xml")

    if not os.path.exists(xml_path):
        raise FileNotFoundError(
            f"soft-carrier.xml nicht gefunden: {xml_path}\n"
            "Bitte zuerst Softcarrier-Download ausführen."
        )

    p(f"  Analysiere betroffene Artikel aus {os.path.basename(xml_path)} ...")
    from lib.sc_image_patch import find_affected
    affected = find_affected(xml_path)
    p(f"  → {len(affected):,} Artikel mit mehrdeutiger MIME_SOURCE", tag="ok")

    if not affected:
        p("  Keine mehrdeutigen MIME_SOURCE gefunden – nichts zu patchen.", tag="ok")
        return

    # ZIP-Index aufbauen
    p("  Baue Bild-Index aus ZIPs ...")
    index = build_index(zip_dir=zip_dir, img_dir=img_dir)
    if not index:
        raise RuntimeError(
            "Keine Bilder im angegebenen Verzeichnis gefunden.\n"
            "Bitte prüfen ob GRAPHIK1.ZIP ... GRAPHIK9.ZIP vorhanden sind."
        )

    out_csv = os.path.join(BASE_DIR, PATCH_FILENAME)

    # Matching
    workers = DIRS.get("sc_bilder_workers", 4)
    p(f"  Starte pHash-Matching ({workers} Worker) ...")
    p("  Lädt Thumbnails von softcarrier.de – Netzwerkzugriff erforderlich ...")
    counters = run_matching(index, affected, out_csv,
                            workers=int(workers), progress_cb=p)

    p(f"  Gut/OK:      {counters['match']:,}", tag="ok")
    p(f"  Kein Match:  {counters['none']:,}",
      tag="warn" if counters["none"] > 1000 else "ok")
    p(f"  Patch-CSV:   {out_csv}", tag="ok")
    p("Softcarrier Bild-Patch abgeschlossen.", tag="ok")
    p("→ Beim nächsten Softcarrier-Merge wird die Patch-CSV automatisch angewendet.")
