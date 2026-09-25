#!/usr/bin/env python3
# tools/fix_softcarrier_mime_prefix.py – Einmalige Korrektur des doppelten
# "SOC"-Präfixes bei Softcarrier-Bild-MIME_SOURCE (siehe Commit-Historie:
# tasks/softcarrier_merge.py hängt beim Schreiben von soft-carrier_merge.xml
# bereits "SOC" an die Bild-MIME_SOURCE an, lib/db_importer.py übernahm den
# Wert bisher unverändert in die DB, lib/db_exporter.py:_add_prefix() hat
# beim Export nochmal "SOC" angehängt -> "SOCSOC....jpg").
#
# Der Import-Fix (lib/db_importer.py:strip_mime_source_prefix) korrigiert das
# für alle Softcarrier-Artikel automatisch beim nächsten regulären Import
# (Content-Hash schließt MIME-Daten ein, ändert sich, Zeile wird neu
# geschrieben). NICHT abgedeckt: Artikel, die Softcarrier inzwischen
# komplett aus dem Katalog genommen hat (kommen nicht mehr in der Feed-Datei
# vor, werden also nie erneut geparst, active=0). Dieses Skript korrigiert
# genau diese (und zur Sicherheit alle) betroffenen Zeilen direkt in der DB,
# unabhängig vom active-Status.
#
# Aufruf (einmalig, im BASE_DIR):  python tools/fix_softcarrier_mime_prefix.py
# Idempotent: ein zweiter Aufruf findet nichts mehr zu korrigieren.

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config
from lib.article_db import open_db


def main():
    con = open_db(config.DB_PATH)

    rows = con.execute("""
        SELECT m.id, m.mime_source
        FROM article_mimes m
        JOIN articles a ON a.id = m.article_id
        JOIN suppliers s ON s.id = a.supplier_id
        WHERE s.supplier_name = 'Softcarrier'
          AND m.mime_type LIKE 'image/%'
          AND m.mime_source LIKE 'SOC%'
    """).fetchall()

    if not rows:
        print("Nichts zu korrigieren – keine Softcarrier-Bild-MIME_SOURCE mit SOC-Präfix in der DB gefunden.")
        con.close()
        return

    print(f"{len(rows):,} betroffene Zeile(n) gefunden.".replace(",", "."))
    for row in rows:
        fixed = row["mime_source"][len("SOC"):]
        con.execute("UPDATE article_mimes SET mime_source=? WHERE id=?", (fixed, row["id"]))
    con.commit()
    con.close()
    print(f"{len(rows):,} Zeile(n) korrigiert (SOC-Präfix entfernt).".replace(",", "."))


if __name__ == "__main__":
    main()
