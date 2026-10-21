#!/usr/bin/env python3
# tools/brg_masse_to_features.py – Büroring-Maßdatei → postprocess_features.csv
#
# Büroring liefert Artikelmaße als CSV (UTF-8 mit BOM, Semikolon):
#     artnr;laenge;breite;hoehe;gewicht
#     AIR2899555003;165 mm;65 mm;65 mm;"0,253 kg"
#     ALBDD5GM;1.010 mm;630 mm;115 mm;"11,8 kg"
#
# Dieses Skript wandelt sie in das generische Format von
# postprocess_features.csv (BASE_DIR) um, das beim VENDOSYS-Export als
# zusätzliche ARTICLE_FEATURES eingetragen wird:
#     product_id;supplier_pid;fname;fvalue;funit
#     BRGAIR2899555003;AIR2899555003;Länge;165;mm
#     BRGAIR2899555003;AIR2899555003;Gewicht;0.253;kg
#
# Werte werden normalisiert: Tausenderpunkt entfernt ("1.010 mm" → 1010),
# Dezimalkomma → Punkt ("0,253 kg" → 0.253), Einheit nach FUNIT.
#
# Aufruf im BASE_DIR:
#   python tools/brg_masse_to_features.py "BRG-Artikelmaße.csv"
#       → schreibt/aktualisiert postprocess_features.csv (bestehende Zeilen
#         anderer Quellen bleiben erhalten; Zeilen mit gleichem product_id
#         + fname werden ersetzt)
#   Optionen:
#     --prefix BRG        Lieferantenpräfix für product_id (Standard: BRG)
#     --out DATEI         Zieldatei (Standard: postprocess_features.csv)
#     --decimal comma     Dezimalkomma statt Punkt im FVALUE

import argparse
import csv
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Spalte in der Büroring-Datei → (FNAME, FUNIT)
COLUMN_MAP = {
    "laenge":  ("Länge",   "mm"),
    "breite":  ("Breite",  "mm"),
    "hoehe":   ("Höhe",    "mm"),
    "tiefe":   ("Tiefe",   "mm"),
    "gewicht": ("Gewicht", "kg"),
}

FIELDS = ["product_id", "supplier_pid", "fname", "fvalue", "funit"]

_NUM_RE = re.compile(r"^\s*([-+]?[\d.,]+)\s*([A-Za-zµ%²³]*)\s*$")


def parse_value(raw: str, default_unit: str, decimal: str = "point") -> tuple:
    """
    "1.010 mm" → ("1010", "mm"); "0,253 kg" → ("0.253", "kg"); "165 mm" → ("165", "mm").
    Nicht-numerische Werte werden unverändert mit der Standard-Einheit übernommen.
    """
    raw = (raw or "").strip()
    if not raw:
        return "", ""
    m = _NUM_RE.match(raw)
    if not m:
        return raw, default_unit
    num, unit = m.group(1), (m.group(2) or default_unit)
    # Deutsches Format: Punkt = Tausender, Komma = Dezimal
    if "," in num:
        num = num.replace(".", "").replace(",", ".")
    elif num.count(".") == 1 and len(num.split(".")[1]) == 3:
        num = num.replace(".", "")          # 1.010 → 1010
    elif num.count(".") > 1:
        num = num.replace(".", "")
    # Überflüssige Nullen: "11.800" bleibt, "0.2530" → 0.253, "165.0" → 165
    if "." in num:
        num = num.rstrip("0").rstrip(".") or "0"
    if decimal == "comma":
        num = num.replace(".", ",")
    return num, unit


def read_brg(path: str) -> list:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                reader = csv.DictReader(f, delimiter=";")
                rows = [{(k or "").strip().lower(): (v or "").strip()
                         for k, v in r.items()} for r in reader]
            if rows and "artnr" not in rows[0]:
                raise SystemExit(f"Spalte 'artnr' fehlt in {path} – gefunden: {list(rows[0])}")
            return rows
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"Datei nicht lesbar: {path}")


def read_existing(path: str) -> list:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        return [{k: (v or "").strip() for k, v in r.items() if k} for r in reader]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", help="Büroring-Maßdatei (artnr;laenge;breite;hoehe;gewicht)")
    ap.add_argument("--prefix", default="BRG", help="Lieferantenpräfix für product_id")
    ap.add_argument("--out", default=str(ROOT / "postprocess_features.csv"))
    ap.add_argument("--decimal", choices=("point", "comma"), default="point")
    args = ap.parse_args()

    src = read_brg(args.input)
    new_rows, skipped = [], 0
    for r in src:
        artnr = r.get("artnr", "")
        if not artnr or artnr.startswith("#"):
            skipped += 1
            continue
        pid = f"{args.prefix}{artnr}"
        for col, (fname, unit) in COLUMN_MAP.items():
            if col not in r:
                continue
            val, funit = parse_value(r[col], unit, args.decimal)
            if not val:
                continue
            new_rows.append({"product_id": pid, "supplier_pid": artnr,
                             "fname": fname, "fvalue": val, "funit": funit})

    # Bestehende Datei einlesen; Zeilen mit gleichem product_id+fname ersetzen
    existing = read_existing(args.out)
    new_keys = {(r["product_id"].upper(), r["fname"].lower()) for r in new_rows}
    kept = [r for r in existing
            if ((r.get("product_id") or "").upper(), (r.get("fname") or "").lower()) not in new_keys]
    replaced = len(existing) - len(kept)

    with open(args.out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, delimiter=";", extrasaction="ignore")
        w.writeheader()
        for r in kept + new_rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})

    arts = len({r["product_id"] for r in new_rows})
    print(f"{os.path.basename(args.input)}: {len(src)} Zeilen gelesen, {skipped} übersprungen")
    print(f"→ {len(new_rows)} Features für {arts} Artikel")
    if existing:
        print(f"   {replaced} vorhandene Zeilen ersetzt, {len(kept)} andere beibehalten")
    print(f"Geschrieben: {args.out}")
    print("Wirksam beim nächsten VENDOSYS-Export (Postprocessing).")


if __name__ == "__main__":
    main()
