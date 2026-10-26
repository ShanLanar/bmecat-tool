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

# Regeln für den Green-Katalog: (FNAME, erlaubte Werte oder None).
#   None  = jeder nicht-leere Wert zählt (ein Artikel mit mindestens einem
#           solchen Feature gehört in den Katalog)
#   set   = nur diese Werte (case-insensitive) zählen als "wahr"
# Ein Artikel ist "green", wenn mindestens EINE Regel zutrifft.
# Büroring liefert seit Oktober 2026 statt "Be Green" das Feature
# "Umweltfreundliches Merkmal" (ggf. mehrfach je Artikel, z.B. "Blauer Engel").
# Optional überschreibbar per green_catalog_features.csv im BASE_DIR
# (Spalten: fname;fvalue – fvalue leer = jeder Wert).
_GREEN_RULES_DEFAULT = [
    (_GREEN_FNAME, _GREEN_TRUE_VALUES),
    ("Umweltfreundliches Merkmal", None),
]


def _load_green_rules(base_dir: str) -> list:
    path = os.path.join(base_dir, 'green_catalog_features.csv')
    if not os.path.exists(path):
        return list(_GREEN_RULES_DEFAULT)
    rules: dict = {}
    try:
        with open(path, 'r', encoding='utf-8-sig', newline='') as f:
            sample = f.read(2048); f.seek(0)
            delim = ';' if sample.count(';') >= sample.count(',') else ','
            for row in csv.DictReader(f, delimiter=delim):
                fname = (row.get('fname') or '').strip()
                if not fname or fname.startswith('#'):
                    continue
                fvalue = (row.get('fvalue') or '').strip().lower()
                key = fname.lower()
                if fvalue:
                    if rules.get(key, set()) is None:
                        continue          # bereits "jeder Wert"
                    rules.setdefault(key, set()).add(fvalue)
                else:
                    rules[key] = None
    except Exception as e:
        log.warning(f"green_catalog_features.csv nicht lesbar ({e}) – Standardregeln")
        return list(_GREEN_RULES_DEFAULT)
    if not rules:
        return list(_GREEN_RULES_DEFAULT)
    return [(k, v) for k, v in rules.items()]

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


def _green_skus(con, supplier_name: str, rules: list = None) -> list:
    """Artikel (active+online) des Lieferanten, auf die mindestens eine Green-Regel zutrifft."""
    rules = rules if rules is not None else list(_GREEN_RULES_DEFAULT)
    if not rules:
        return []
    placeholders = ",".join("?" * len(rules))
    all_rows = con.execute(f"""
        SELECT a.product_id, f.fname, f.fvalue
        FROM articles a
        JOIN suppliers s ON s.id = a.supplier_id
        JOIN article_features f ON f.article_id = a.id
        WHERE s.supplier_name = ? AND a.active = 1 AND a.online = 1
          AND LOWER(f.fname) IN ({placeholders})
    """, (supplier_name, *[fn.lower() for fn, _ in rules])).fetchall()
    allowed = {fn.lower(): vals for fn, vals in rules}
    skus = set()
    for r in all_rows:
        vals = allowed.get((r['fname'] or '').lower())
        val = (r['fvalue'] or '').strip().lower()
        if not val:
            continue
        if vals is None or val in vals:
            skus.add(r['product_id'])
    return sorted(skus)


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
    rules = _load_green_rules(base_dir)
    p("Artikelrechte GREEN-Regeln: " + "; ".join(
        f"{fn} = {'beliebiger Wert' if v is None else '/'.join(sorted(v))}" for fn, v in rules), tag="dim")
    skus = _green_skus(con, supplier_name, rules)
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
