# lib/first_run.py – Erstinstallation und Update-Schutz
#
# Kopiert fehlende Konfigurations-Dateien aus templates/ in BASE_DIR.
# Wird beim Start aufgerufen. Existierende Dateien werden NIE überschrieben.
# So bleiben Nutzerdaten bei Updates erhalten.

import os
import shutil
import logging

log = logging.getLogger(__name__)

# Dateien die beim Erstinstall angelegt werden (aus templates/)
TEMPLATE_FILES = [
    "postprocess_blacklist.csv",
    "postprocess_fname_blacklist.csv",
    "postprocess_prices.csv",
    "postprocess_price_types.csv",
    "postprocess_media_global.csv",
    "postprocess_media.csv",
    "postprocess_reference_types.csv",
    "postprocess_categories.csv",
    "postprocess_crosssell.csv",
    "postprocess_suffixes.csv",
    "postprocess_catalog_remap.csv",
    "fusage_3_features.csv",
    "supplier_priority.csv",
    "udx_fields.csv",
    "fname_renames.csv",
    "fvalue_renames.csv",
    "keyword_dictionary.csv",
    "supplier_config.yaml",
    "softcarrier_it_groups.csv",
]


def initialize(base_dir: str, progress_cb=None) -> list[str]:
    """
    Kopiert fehlende Dateien aus templates/ nach base_dir.
    Gibt Liste der neu angelegten Dateien zurück.
    Existierende Dateien werden nicht angetastet.
    """
    p = progress_cb or (lambda m, **kw: None)
    template_dir = os.path.join(base_dir, "templates")
    created = []

    if not os.path.isdir(template_dir):
        log.debug("templates/ nicht gefunden – kein Erstinstall nötig")
        return created

    for fname in TEMPLATE_FILES:
        dst = os.path.join(base_dir, fname)
        src = os.path.join(template_dir, fname)

        if os.path.exists(dst):
            continue   # Nutzerdatei vorhanden → nie überschreiben

        if not os.path.exists(src):
            continue   # Kein Template → überspringen

        try:
            shutil.copy2(src, dst)
            created.append(fname)
            log.info(f"Erstinstall: {fname} angelegt")
        except Exception as e:
            log.warning(f"Erstinstall: {fname} konnte nicht kopiert werden: {e}")

    if created:
        p(f"Erstinstall: {len(created)} Konfigurations-Dateien angelegt "
          f"({', '.join(created[:3])}"
          f"{'...' if len(created) > 3 else ''})",
          tag="ok")

    return created
