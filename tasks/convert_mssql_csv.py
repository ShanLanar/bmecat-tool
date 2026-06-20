# tasks/convert_mssql_csv.py – SSMS-CSV-Export in Standard-Format konvertieren
#
# Eingabe (SSMS-Export, kein Header):
#   eclass_code ; bezeichnung ; ebene ; version
#   20000000    ; Packmittel  ; 1     ; 4.0
#
# Ausgabe:
#   version;code;name_de;name_en;level;parent_code
#   "4.0";"20";"Packmittel";"";"segment";""
#
# CLI:
#   py tasks/convert_mssql_csv.py Ergebnisse.csv
#   py tasks/convert_mssql_csv.py Ergebnisse.csv --out eclass_catalog_mssql.csv

import argparse
import csv
import sys
from pathlib import Path

LEVELS = {1: "segment", 2: "hauptgruppe", 3: "gruppe", 4: "klasse"}
CSV_HEADER = ["version", "code", "name_de", "name_en", "level", "parent_code"]


def _is_zero(pair: str) -> bool:
    return pair == "00"

def code8_to_eclass(code8: str) -> str:
    s = str(code8).lower().ljust(8, "0")[:8]
    seg, hg, gr, kl = s[0:2], s[2:4], s[4:6], s[6:8]
    if _is_zero(hg): return seg
    if _is_zero(gr): return f"{seg}-{hg}"
    if _is_zero(kl): return f"{seg}-{hg}-{gr}"
    return f"{seg}-{hg}-{gr}-{kl}"

def parent_code8(code8: str) -> str:
    s = str(code8).lower().ljust(8, "0")[:8]
    hg, gr, kl = s[2:4], s[4:6], s[6:8]
    if _is_zero(hg): return ""
    if _is_zero(gr): return s[0:2] + "000000"
    if _is_zero(kl): return s[0:4] + "0000"
    return s[0:6] + "00"


def convert(in_path: str, out_path: str) -> int:
    rows = []
    skipped = 0

    with open(in_path, newline="", encoding="utf-8-sig") as f:
        # Header-Zeile überspringen falls vorhanden
        sample = f.read(200)
        f.seek(0)
        has_header = sample.lstrip().startswith("eclass") or sample.lstrip().startswith('"eclass')
        reader = csv.reader(f, delimiter=";")
        if has_header:
            next(reader)

        for lineno, row in enumerate(reader, start=1):
            if len(row) < 4:
                skipped += 1
                continue
            eclass_code = row[0].strip().strip('"')
            bezeichnung = row[1].strip().strip('"')
            ebene_raw   = row[2].strip().strip('"')
            version     = row[3].strip().strip('"')

            if not eclass_code or not ebene_raw:
                skipped += 1
                continue
            try:
                ebene = int(ebene_raw)
            except ValueError:
                skipped += 1
                continue

            parent8 = parent_code8(eclass_code)
            rows.append({
                "version":     version,
                "code":        code8_to_eclass(eclass_code),
                "name_de":     bezeichnung,
                "name_en":     "",
                "level":       LEVELS.get(ebene, "klasse"),
                "parent_code": code8_to_eclass(parent8) if parent8 else "",
            })

    # Nach Version + Code sortieren
    rows.sort(key=lambda r: (r["version"], r["code"]))

    tmp = Path(out_path).with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_HEADER, delimiter=";",
                           extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(Path(out_path))

    print(f"  {len(rows):,} Einträge → {out_path}"
          + (f" ({skipped} übersprungen)" if skipped else ""))
    return len(rows)


def _cli():
    ap = argparse.ArgumentParser(
        description="SSMS-CSV → Standard eClass CSV konvertieren")
    ap.add_argument("input",  help="SSMS-Export CSV (eclass;bezeichnung;ebene;version)")
    ap.add_argument("--out",  help="Ausgabedatei (Standard: eclass_catalog_mssql.csv)",
                    default="eclass_catalog_mssql.csv")
    args = ap.parse_args()

    if not Path(args.input).exists():
        print(f"Datei nicht gefunden: {args.input}", file=sys.stderr)
        sys.exit(1)

    n = convert(args.input, args.out)
    print(f"Fertig: {n:,} Einträge")


if __name__ == "__main__":
    _cli()
