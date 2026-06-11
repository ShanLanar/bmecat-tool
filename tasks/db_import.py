# tasks/db_import.py – DB-Import-Task
#
# Wird nach jedem Lieferanten-Task aufgerufen.
# Liest die verarbeiteten XMLs aus in_BME/ und importiert sie in die DB.

import logging
import os
from typing import Callable

import config as _cfg
from lib.db_importer import import_xml

log = logging.getLogger(__name__)

# Mapping: xml-Dateiname → wird per supplier_config.yaml aufgelöst
IMPORT_SOURCES = {
    'bueroring':  ['bueroring_merged.xml'],
    'nordwest':   ['arbeitsschutz.xml', 'werkstatt.xml', 'werkzeugtechnik.xml'],
    'softcarrier': ['soft-carrier_merge.xml'],
}


def run_for_supplier(supplier_key: str,
                     progress_cb: Callable = None,
                     file_progress_cb: Callable = None):
    """Importiert alle XMLs eines bestimmten Lieferanten."""
    p  = progress_cb or (lambda m, **kw: None)
    in_bme = _cfg.DIRS['in_bme']

    xml_files = IMPORT_SOURCES.get(supplier_key, [])
    if not xml_files:
        p(f"DB-Import: kein Mapping für Lieferant '{supplier_key}'", tag='warn')
        return

    total_stats = {'new': 0, 'updated': 0, 'unchanged': 0, 'errors': 0}
    for xml_name in xml_files:
        xml_path = os.path.join(in_bme, xml_name)
        if not os.path.exists(xml_path):
            p(f"DB-Import: {xml_name} nicht gefunden, übersprungen", tag='dim')
            continue
        stats = import_xml(
            db_path=_cfg.DB_PATH,
            xml_path=xml_path,
            base_dir=_cfg.BASE_DIR,
            progress_cb=p,
        )
        for k in total_stats:
            total_stats[k] += stats.get(k, 0)

    return total_stats


def run_all(progress_cb: Callable = None, file_progress_cb: Callable = None):
    """Importiert alle aktiven Lieferanten."""
    p = progress_cb or (lambda m, **kw: None)
    for key in IMPORT_SOURCES:
        run_for_supplier(key, progress_cb=p)
