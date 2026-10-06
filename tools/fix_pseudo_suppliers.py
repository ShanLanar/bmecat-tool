#!/usr/bin/env python3
# tools/fix_pseudo_suppliers.py – Pseudo-Lieferanten aus der Artikel-DB entfernen
#
# Hintergrund: lib/db_importer.py:import_xml() fiel bei nicht lesbarer
# supplier_config.yaml (z.B. neuer Rechner ohne PyYAML) still auf den
# XML-Dateinamen als Lieferantennamen zurück. Dadurch entstanden in der
# suppliers-Tabelle Einträge wie "bueroring_merged", "soft-carrier_merge",
# "arbeitsschutz", "werkstatt", "werkzeugtechnik" – mit jeweils einer
# kompletten Dublette aller Artikel des echten Lieferanten (ohne Präfix in
# product_id). Der Importer bricht in diesem Fall jetzt ab; dieses Skript
# räumt die bereits angelegten Dubletten weg.
#
# Betroffen sind ausschließlich Lieferanten, deren Name exakt dem Basisnamen
# einer Pipeline-XML aus tasks/db_import.py:IMPORT_SOURCES entspricht.
# Manuell importierte Kataloge (z.B. "Kaenguruh") bleiben unangetastet.
#
# Aufruf im BASE_DIR:
#   python tools/fix_pseudo_suppliers.py            -> nur anzeigen (Dry-Run)
#   python tools/fix_pseudo_suppliers.py --delete   -> wirklich löschen
# Vorher sichert das Skript die DB nach backups/ (wie der Lauf-Backup).

import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config
from lib.article_db import open_db
from tasks.db_import import IMPORT_SOURCES

PSEUDO_NAMES = sorted({
    os.path.splitext(xml)[0]
    for files in IMPORT_SOURCES.values()
    for xml in files
})

ARTICLE_CHILD_TABLES = (
    "article_prices", "article_features", "article_mimes", "article_keywords",
    "article_references", "article_udx", "article_catalog_map",
)


def _de(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def main():
    do_delete = "--delete" in sys.argv[1:]
    con = open_db(config.DB_PATH)

    placeholders = ",".join("?" * len(PSEUDO_NAMES))
    sups = con.execute(
        f"SELECT id, supplier_name FROM suppliers WHERE supplier_name IN ({placeholders}) "
        f"ORDER BY supplier_name", PSEUDO_NAMES).fetchall()

    if not sups:
        print("Keine Pseudo-Lieferanten gefunden – nichts zu tun.")
        print("Geprüft wurden:", ", ".join(PSEUDO_NAMES))
        con.close()
        return

    print(f"{len(sups)} Pseudo-Lieferant(en) gefunden:")
    total_articles = 0
    for s in sups:
        n_art = con.execute("SELECT COUNT(*) FROM articles WHERE supplier_id=?",
                            (s["id"],)).fetchone()[0]
        n_cat = con.execute("SELECT COUNT(*) FROM catalog_nodes WHERE supplier_id=?",
                            (s["id"],)).fetchone()[0]
        total_articles += n_art
        print(f"  - {s['supplier_name']:<22} {_de(n_art):>9} Artikel, {_de(n_cat):>7} Katalogknoten")

    if not do_delete:
        print()
        print("Dry-Run – nichts gelöscht. Zum Löschen: python tools/fix_pseudo_suppliers.py --delete")
        con.close()
        return

    # Sicherung
    backup_dir = os.path.join(config.BASE_DIR, "backups")
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(backup_dir, f"article_db_vor_pseudo_cleanup_{stamp}.sqlite")
    con.close()
    shutil.copy2(config.DB_PATH, backup_path)
    print(f"\nSicherung: {backup_path}")
    con = open_db(config.DB_PATH)

    ids = [s["id"] for s in sups]
    id_ph = ",".join("?" * len(ids))
    with con:
        for tbl in ARTICLE_CHILD_TABLES:
            con.execute(
                f"DELETE FROM {tbl} WHERE article_id IN "
                f"(SELECT id FROM articles WHERE supplier_id IN ({id_ph}))", ids)
        n_art = con.execute(f"DELETE FROM articles WHERE supplier_id IN ({id_ph})", ids).rowcount
        n_cat = con.execute(f"DELETE FROM catalog_nodes WHERE supplier_id IN ({id_ph})", ids).rowcount
        n_sup = con.execute(f"DELETE FROM suppliers WHERE id IN ({id_ph})", ids).rowcount
    print(f"Gelöscht: {n_sup} Lieferant(en), {_de(n_art)} Artikel, {_de(n_cat)} Katalogknoten")

    con.execute("VACUUM")
    con.close()
    print("Fertig. Lieferanten-Statistik/Viewer zeigen jetzt nur noch echte Lieferanten.")


if __name__ == "__main__":
    main()
