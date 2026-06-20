# tasks/convert_unspsc_xlsx.py – UNSPSC Excel (UNvXXXXXX) → Standard-Katalog-CSV
#
# Eingabe:  offizielle UNSPSC-Excel-Datei (z. B. unspscenglishv260801.1.xlsx)
#           Spalten: Version | Key | Segment | Segment Title | ... | Family | ...
#                    | Class | ... | Commodity | Commodity Title | ...
#
# Ausgabe:  version;code;name_de;name_en;level;parent_code
#           (name_de leer — ggf. nachträglich mit translate_unspsc.py befüllen)
#
# Voraussetzung:
#   py -m pip install openpyxl
#
# CLI:
#   py tasks/convert_unspsc_xlsx.py unspscenglishv260801.1.xlsx
#   py tasks/convert_unspsc_xlsx.py unspscenglishv260801.1.xlsx --out eclass_catalog_unspsc.csv
#   py tasks/convert_unspsc_xlsx.py unspscenglishv260801.1.xlsx --version UNv260801

import argparse
import csv
import sys
from pathlib import Path

CSV_HEADER = ["version", "code", "name_de", "name_en", "level", "parent_code"]
LEVELS     = {1: "segment", 2: "hauptgruppe", 3: "gruppe", 4: "klasse"}

# Spalten-Indizes im Excel (0-basiert, ab Datenzeile)
_COL_SEG      = 2   # Segment code (int)
_COL_SEG_NAME = 3   # Segment Title
_COL_FAM      = 5   # Family code
_COL_FAM_NAME = 6   # Family Title
_COL_CLS      = 8   # Class code
_COL_CLS_NAME = 9   # Class Title
_COL_COM      = 11  # Commodity code
_COL_COM_NAME = 12  # Commodity Title
_HEADER_ROW   = 13  # 1-basiert → Index 12 (0-basiert)


def _zfill8(code) -> str:
    return str(int(code)).zfill(8)

def _code_to_eclass(code8: str) -> str:
    seg, hg, gr, kl = code8[0:2], code8[2:4], code8[4:6], code8[6:8]
    if hg == "00": return seg
    if gr == "00": return f"{seg}-{hg}"
    if kl == "00": return f"{seg}-{hg}-{gr}"
    return f"{seg}-{hg}-{gr}-{kl}"

def _parent_eclass(code8: str) -> str:
    seg, hg, gr, kl = code8[0:2], code8[2:4], code8[4:6], code8[6:8]
    if hg == "00": return ""
    if gr == "00": return _code_to_eclass(seg + "000000")
    if kl == "00": return _code_to_eclass(seg + hg + "0000")
    return _code_to_eclass(seg + hg + gr + "00")

def _safe(row, idx):
    try:
        v = row[idx]
        return str(v).strip() if v is not None else ""
    except IndexError:
        return ""


def convert(in_path: str, out_path: str, version_override: str | None = None,
            progress_cb=None) -> int:
    p = progress_cb or print

    try:
        import openpyxl
    except ImportError:
        raise RuntimeError("py -m pip install openpyxl")

    p(f"  Lese {in_path} …")
    wb = openpyxl.load_workbook(in_path, read_only=True, data_only=True)
    ws = wb.active

    # Einträge sammeln — je Ebene deduplizieren
    seen:    dict[str, dict] = {}   # code8 → row-dict
    version: str             = ""

    for row_idx, row in enumerate(ws.iter_rows(values_only=True)):
        if row_idx < _HEADER_ROW:       # Header + Titelzeilen überspringen
            continue
        if not row[_COL_SEG]:
            continue

        # Version aus erster Datenspalte
        if not version:
            version = version_override or _safe(row, 0) or "UNv260801"

        # Alle 4 Ebenen extrahieren (soweit vorhanden)
        levels_in_row = [
            (_COL_SEG, _COL_SEG_NAME, 1),
            (_COL_FAM, _COL_FAM_NAME, 2),
            (_COL_CLS, _COL_CLS_NAME, 3),
            (_COL_COM, _COL_COM_NAME, 4),
        ]
        for col_code, col_name, lvl in levels_in_row:
            raw = _safe(row, col_code)
            if not raw or raw == "0":
                break
            try:
                code8 = _zfill8(raw)
            except ValueError:
                break
            if code8 in seen:
                continue
            name_en = _safe(row, col_name)
            if not name_en:
                continue
            seen[code8] = {
                "version":     version,
                "code":        _code_to_eclass(code8),
                "name_de":     "",
                "name_en":     name_en,
                "level":       LEVELS[lvl],
                "parent_code": _parent_eclass(code8),
            }

    wb.close()
    p(f"  {len(seen):,} eindeutige Einträge extrahiert")

    # Sortieren: Segment → Hauptgruppe → Gruppe → Klasse
    rows = sorted(seen.values(), key=lambda r: r["code"])

    tmp = Path(out_path).with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_HEADER, delimiter=";",
                           extrasaction="ignore", quoting=csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(Path(out_path))

    p(f"  Gespeichert: {out_path}")
    return len(rows)


def _cli():
    ap = argparse.ArgumentParser(
        description="UNSPSC Excel → Standard-Katalog-CSV (name_de leer)")
    ap.add_argument("input",       help="UNSPSC Excel-Datei (.xlsx)")
    ap.add_argument("--out",       default="eclass_catalog_unspsc.csv")
    ap.add_argument("--version",   default=None,
                    help="Version überschreiben (Standard: aus Excel-Daten)")
    args = ap.parse_args()

    if not Path(args.input).exists():
        print(f"Datei nicht gefunden: {args.input}", file=sys.stderr)
        sys.exit(1)

    n = convert(args.input, args.out, version_override=args.version)
    print(f"\nFertig: {n:,} Einträge → {args.out}")


if __name__ == "__main__":
    _cli()
