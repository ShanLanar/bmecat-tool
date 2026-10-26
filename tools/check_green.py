#!/usr/bin/env python3
# tools/check_green.py – Diagnose für den Green-Katalog (Allago 79 / Oxl 88)
#
# Zeigt, welche "Be Green"-Werte in der Artikel-DB stehen und wie viele
# Artikel die Katalogbedingung (Büroring, active=1, online=1, Wert = wahr)
# erfüllen. Aufruf im BASE_DIR:  python tools/check_green.py

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config
from lib.article_db import open_db
from lib.article_rights_export import _GREEN_FNAME, _GREEN_TRUE_VALUES, _green_skus, _load_green_rules


def main():
    con = open_db(config.DB_PATH)

    print("1) Feature-Namen, die 'green' enthalten (alle Lieferanten):")
    rows = con.execute("""
        SELECT s.supplier_name, f.fname, COUNT(*) AS n
        FROM article_features f
        JOIN articles a ON a.id = f.article_id
        JOIN suppliers s ON s.id = a.supplier_id
        WHERE LOWER(f.fname) LIKE '%green%'
        GROUP BY s.supplier_name, f.fname ORDER BY n DESC
    """).fetchall()
    if not rows:
        print("   -> KEIN Feature mit 'green' im Namen in der DB!")
    for r in rows:
        print(f"   {r['supplier_name']:<28} {r['fname']!r:<24} {r['n']:>8}")

    print(f"\n2) Werte von '{_GREEN_FNAME}' bei Büroring (active/online aufgeschlüsselt):")
    rows = con.execute("""
        SELECT f.fvalue, a.active, a.online, COUNT(*) AS n
        FROM article_features f
        JOIN articles a ON a.id = f.article_id
        JOIN suppliers s ON s.id = a.supplier_id
        WHERE s.supplier_name = 'Büroring' AND LOWER(f.fname) = LOWER(?)
        GROUP BY f.fvalue, a.active, a.online ORDER BY n DESC
    """, (_GREEN_FNAME,)).fetchall()
    if not rows:
        print("   -> keine Zeilen (Feature 'Be Green' nicht mehr vorhanden?) – siehe Regeln in 4).")
    for r in rows:
        ok = (r['fvalue'] or '').strip().lower() in _GREEN_TRUE_VALUES
        print(f"   fvalue={r['fvalue']!r:<16} active={r['active']} online={r['online']} "
              f"n={r['n']:>7}   {'<- zählt als WAHR' if ok else ''}")

    print("\n3) Lieferanten in der DB:")
    for r in con.execute("SELECT supplier_name, COUNT(*) n FROM suppliers s "
                         "JOIN articles a ON a.supplier_id = s.id GROUP BY supplier_name"):
        print(f"   {r['supplier_name']!r:<30} {r['n']:>8} Artikel")

    rules = _load_green_rules(str(ROOT))
    print("\n4) Green-Regeln (mindestens eine muss zutreffen):")
    for fn, vals in rules:
        print(f"   {fn!r}: {'jeder nicht-leere Wert' if vals is None else sorted(vals)}")
        rows = con.execute("""
            SELECT a.active, a.online, COUNT(DISTINCT a.id) AS n
            FROM article_features f JOIN articles a ON a.id = f.article_id
            JOIN suppliers s ON s.id = a.supplier_id
            WHERE s.supplier_name = 'Büroring' AND LOWER(f.fname) = ?
            GROUP BY a.active, a.online""", (fn.lower(),)).fetchall()
        for r in rows:
            print(f"      active={r['active']} online={r['online']}  {r['n']} Artikel")
    skus = _green_skus(con, "Büroring", rules)
    print(f"\n5) Ergebnis: {len(skus)} Artikel würden in Allago/79.csv und Oxl/88.csv landen.")
    print("   Beispiele:", ", ".join(skus[:10]) or "-")
    con.close()


if __name__ == "__main__":
    main()
