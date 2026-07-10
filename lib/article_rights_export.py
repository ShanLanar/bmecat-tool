# lib/article_rights_export.py – Artikelrechte-Export für Allago + OfficeXL
#
# Ersetzt die alte SQL-Query/Velocity-Template-Lösung des abgelösten Shop-Systems.
# Erzeugt pro Katalog je eine Datei für Allago und eine für OfficeXL (Oxl) mit
# der Liste der SKUs (= product_id), die in diesem Katalog freigeschaltet
# werden sollen.
#
# Verzeichnisstruktur: <out_dir>/<Allago|Oxl>/<Katalognummer>.csv
# (z.B. export_artikelrechte/Allago/57.csv, export_artikelrechte/Oxl/102.csv) –
# ein Ordner je Zielsystem. Die Katalognummern sind je Zielsystem eindeutig
# (57/78/56/299/79/197/198 bei Allago, 102/97/91/129/88/107/108 bei Oxl),
# überschneiden sich also nicht.
#
# Format je Datei: Kopfzeile "sku", danach eine product_id pro Zeile (kein
# Trennzeichen, keine Anführungszeichen – exakt wie das alte Velocity-Template).
#
# Filter für alle Kataloge: active=1 UND online=1 (wie ONLINE-Flag im
# VENDOSYS-Export).

import csv
import logging
import os
from typing import Callable

from lib.article_db import open_db

log = logging.getLogger(__name__)

# (katalog_code, supplier_name, allago_id, oxl_id)
_SIMPLE_CATALOGS = [
    ("AS", "Nordwest Arbeitsschutz",   57,  102),
    ("WS", "Nordwest Werkstatt",       78,   97),
    ("WZ", "Nordwest Werkzeugtechnik", 56,   91),
    ("BRG", "Büroring",               299,  129),
]

_GREEN_CATALOG = ("GREEN", "Büroring", 79, 88)
_GREEN_FNAME = "Be Green"
# Beobachtete Wahr-Werte für "Be green" in der DB: Rohcode (CAA016), übersetzt
# (Ja) und Boolean aus dem BMEcat-Rohtext (true). Alles case-insensitive.
_GREEN_TRUE_VALUES = {"ja", "true", "caa016", "1", "wahr"}

# Softcarrier wird per Katalog-Gruppen-ID aufgeteilt (siehe _load_it_groups)
_FR_CATALOG = ("FR", "Softcarrier", 197, 107)   # NICHT in it_groups
_IT_CATALOG = ("IT", "Softcarrier", 198, 108)   # IN it_groups


def _load_it_groups(base_dir: str) -> set:
    path = os.path.join(base_dir, 'softcarrier_it_groups.csv')
    if not os.path.exists(path):
        return set()
    with open(path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        return {(row.get('group_id') or '').strip() for row in reader if row.get('group_id')}


def _active_skus(con, supplier_name: str) -> list:
    rows = con.execute("""
        SELECT a.product_id
        FROM articles a
        JOIN suppliers s ON s.id = a.supplier_id
        WHERE s.supplier_name = ? AND a.active = 1 AND a.online = 1
        ORDER BY a.product_id
    """, (supplier_name,)).fetchall()
    return [r['product_id'] for r in rows]


def _green_skus(con, supplier_name: str) -> list:
    all_rows = con.execute("""
        SELECT a.product_id, f.fvalue
        FROM articles a
        JOIN suppliers s ON s.id = a.supplier_id
        JOIN article_features f ON f.article_id = a.id
        WHERE s.supplier_name = ? AND a.active = 1 AND a.online = 1
          AND LOWER(f.fname) = LOWER(?)
    """, (supplier_name, _GREEN_FNAME)).fetchall()
    skus = sorted({r['product_id'] for r in all_rows
                   if (r['fvalue'] or '').strip().lower() in _GREEN_TRUE_VALUES})
    return skus


def _softcarrier_split_skus(con, it_groups: set) -> tuple:
    rows = con.execute("""
        SELECT a.product_id, a.catalog_group_id
        FROM articles a
        JOIN suppliers s ON s.id = a.supplier_id
        WHERE s.supplier_name = 'Softcarrier' AND a.active = 1 AND a.online = 1
        ORDER BY a.product_id
    """).fetchall()
    it_skus, fr_skus = [], []
    for r in rows:
        if (r['catalog_group_id'] or '').strip() in it_groups:
            it_skus.append(r['product_id'])
        else:
            fr_skus.append(r['product_id'])
    return fr_skus, it_skus


def _write_file(out_dir: str, target: str, catalog_id: int, skus: list) -> str:
    """Dateiname = Zielsystem-Katalognummer, in einem Ordner je Zielsystem
    (Allago/Oxl) – die Katalognummern sind je Zielsystem eindeutig."""
    subdir = os.path.join(out_dir, target)
    os.makedirs(subdir, exist_ok=True)
    path = os.path.join(subdir, f"{catalog_id}.csv")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("sku\n")
        for sku in skus:
            f.write(sku + "\n")
    return path


def export_article_rights(db_path: str, base_dir: str, out_dir: str,
                          progress_cb: Callable = None) -> dict:
    """
    Exportiert Artikelrechte-Dateien für Allago + OfficeXL.
    Gibt {katalog: {"allago": N, "oxl": N, "allago_path":..., "oxl_path":...}} zurück.
    """
    p = progress_cb or (lambda m, **kw: None)

    os.makedirs(out_dir, exist_ok=True)
    con = open_db(db_path)

    it_groups = _load_it_groups(base_dir)
    if not it_groups:
        p("Artikelrechte: softcarrier_it_groups.csv leer/fehlt – "
          "alle Softcarrier-Artikel gehen als FR (Freizeit) raus", tag="warn")

    stats = {}

    for code, supplier_name, allago_id, oxl_id in _SIMPLE_CATALOGS:
        skus = _active_skus(con, supplier_name)
        allago_path = _write_file(out_dir, "Allago", allago_id, skus)
        oxl_path    = _write_file(out_dir, "Oxl", oxl_id, skus)
        stats[code] = {"count": len(skus), "allago_path": allago_path, "oxl_path": oxl_path}
        p(f"Artikelrechte {code}: {len(skus)} Artikel -> Allago/{os.path.basename(allago_path)} / "
          f"Oxl/{os.path.basename(oxl_path)}", tag="ok")

    # BRG Green
    code, supplier_name, allago_id, oxl_id = _GREEN_CATALOG
    skus = _green_skus(con, supplier_name)
    allago_path = _write_file(out_dir, "Allago", allago_id, skus)
    oxl_path    = _write_file(out_dir, "Oxl", oxl_id, skus)
    stats[code] = {"count": len(skus), "allago_path": allago_path, "oxl_path": oxl_path}
    p(f"Artikelrechte {code}: {len(skus)} Artikel -> Allago/{os.path.basename(allago_path)} / "
      f"Oxl/{os.path.basename(oxl_path)}", tag="ok")

    # Softcarrier FR/IT-Split
    fr_skus, it_skus = _softcarrier_split_skus(con, it_groups)
    for (code, supplier_name, allago_id, oxl_id), skus in (
        (_FR_CATALOG, fr_skus), (_IT_CATALOG, it_skus)
    ):
        allago_path = _write_file(out_dir, "Allago", allago_id, skus)
        oxl_path    = _write_file(out_dir, "Oxl", oxl_id, skus)
        stats[code] = {"count": len(skus), "allago_path": allago_path, "oxl_path": oxl_path}
        p(f"Artikelrechte {code}: {len(skus)} Artikel -> Allago/{os.path.basename(allago_path)} / "
          f"Oxl/{os.path.basename(oxl_path)}", tag="ok")

    return stats
