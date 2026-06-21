# tasks/merge_catalogs.py – Alle eClass/UNSPSC-Katalog-CSVs zusammenführen
#
# Liest beliebig viele Standard-Katalog-CSVs und fügt sie zu einer Datei zusammen.
# Duplikate (gleiche version + code) werden dedupliziert (erster Eintrag gewinnt).
#
# CLI — explizite Dateiliste:
#   py tasks/merge_catalogs.py eclass_catalog_5.14.csv eclass_catalog_7.0.csv ...
#
# CLI — Glob-Muster (alle Katalog-CSVs im aktuellen Verzeichnis):
#   py tasks/merge_catalogs.py --glob "eclass_catalog_*.csv"
#   py tasks/merge_catalogs.py --glob "eclass_catalog_*.csv" --out eclass_catalog.csv
#
# Sortierung: Version numerisch (z. B. 4.0 < 5.1 < 9.0 < 13.1 < UNv260801),
#             dann Code lexikografisch.

import argparse
import csv
import glob as _glob
import sys
from pathlib import Path

CSV_HEADER = ["version", "code", "name_de", "name_en", "level", "parent_code"]
DEFAULT_OUT = "eclass_catalog.csv"

# Versionsname-Korrekturen: Scraper-Formularwert → kanonischer Name
_VERSION_ALIASES = {
    "5.14":  "5.1.4",
}

def _normalize_version(v: str) -> str:
    return _VERSION_ALIASES.get(v, v)


def _version_sort_key(v: str):
    """Numerische Versionssortierung: '4.0' < '9.0' < '13.1' < 'UNv260801'."""
    try:
        parts = [int(x) for x in v.replace("UNv", "999.").split(".")]
        return (0, parts)
    except ValueError:
        return (1, [v])


def merge(in_paths: list[str], out_path: str, progress_cb=None) -> int:
    p = progress_cb or print

    seen:  dict[tuple, dict] = {}   # (version, code) → row
    order: list[tuple]       = []   # Reihenfolge für Sortierung

    for path in in_paths:
        if not Path(path).exists():
            p(f"  [SKIP] Datei nicht gefunden: {path}")
            continue
        with open(path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, delimiter=";")
            if reader.fieldnames is None:
                p(f"  [SKIP] Leere Datei: {path}")
                continue
            before = len(seen)
            for row in reader:
                ver = _normalize_version(row.get("version", "").strip())
                key = (ver, row.get("code", "").strip())
                if key not in seen:
                    r = {k: row.get(k, "").strip() for k in CSV_HEADER}
                    r["version"] = ver
                    seen[key] = r
                    order.append(key)
            added = len(seen) - before
        p(f"  {added:>7,} neu  ← {Path(path).name}  (gesamt {len(seen):,})")

    if not seen:
        p("  Keine Einträge gefunden.")
        return 0

    # Sortieren: Version numerisch, dann Code
    order.sort(key=lambda k: (_version_sort_key(k[0]), k[1]))

    tmp = Path(out_path).with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_HEADER, delimiter=";",
                           extrasaction="ignore", quoting=csv.QUOTE_ALL)
        w.writeheader()
        for key in order:
            w.writerow(seen[key])
    tmp.replace(Path(out_path))

    p(f"\n  Gespeichert: {out_path}  ({len(order):,} Einträge)")
    return len(order)


def _cli():
    ap = argparse.ArgumentParser(
        description="Mehrere Katalog-CSVs zusammenführen")
    ap.add_argument("files", nargs="*",
                    help="Katalog-CSV-Dateien (alternativ --glob)")
    ap.add_argument("--glob", dest="pattern", default=None,
                    help='Glob-Muster, z. B. "eclass_catalog_*.csv"')
    ap.add_argument("--out",  default=DEFAULT_OUT,
                    help=f"Ausgabe-CSV (Standard: {DEFAULT_OUT})")
    args = ap.parse_args()

    paths = list(args.files)
    if args.pattern:
        paths += sorted(_glob.glob(args.pattern))

    if not paths:
        print("Keine Eingabedateien angegeben (--glob oder Positionsargumente).",
              file=sys.stderr)
        sys.exit(1)

    # Ausgabe-Datei aus Eingabeliste ausschließen
    out_abs = str(Path(args.out).resolve())
    paths = [p for p in paths if str(Path(p).resolve()) != out_abs]

    print(f"  Merge von {len(paths)} Datei(en) → {args.out}")
    merge(paths, args.out)


if __name__ == "__main__":
    _cli()
