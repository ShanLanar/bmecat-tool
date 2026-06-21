# tasks/convert_mssql_csv.py – SSMS-CSV-Export in Standard-Format konvertieren
#
# Eingabe (SSMS-Export ohne Header, DE+EN als Duplikate):
#   eclass_code ; bezeichnung ; ebene ; version
#   20000000    ; Packmittel  ; 1     ; 4.0
#   20000000    ; Packaging   ; 1     ; 4.0
#
# Ausgabe:
#   version;code;name_de;name_en;level;parent_code
#   "4.0";"20";"Packmittel";"Packaging";"segment";""
#
# CLI:
#   py tasks/convert_mssql_csv.py Ergebnisse.csv
#   py tasks/convert_mssql_csv.py Ergebnisse.csv --out eclass_catalog_mssql.csv

import argparse
import re
import sys
from pathlib import Path

LEVELS     = {1: "segment", 2: "hauptgruppe", 3: "gruppe", 4: "klasse"}
CSV_HEADER = "version;code;name_de;name_en;level;parent_code"

# Zeilen die übersprungen werden (Versions-Header und leere Werte)
_SKIP_RE     = re.compile(r'^(?:eClass|UNSPSC)\s', re.IGNORECASE)
_DE_UMLAUT   = re.compile(r'[äöüÄÖÜß]')
_DE_STOPWORD = re.compile(
    r'\b(und|oder|von|der|die|das|des|den|dem|für|mit|bei|nach|aus|auf|im|'
    r'ein|eine|einer|eines|zum|zur|sowie|als|auch|ist|sind|wird|werden|'
    r'nicht|bzw|inkl|zzgl|je|laut)\b', re.IGNORECASE)

def _is_german(text: str) -> bool:
    return bool(_DE_UMLAUT.search(text) or _DE_STOPWORD.search(text))


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

def _escape(v: str) -> str:
    return '"' + v.replace('"', '""') + '"'


def convert(in_path: str, out_path: str) -> int:
    # Sammle alle Einträge pro (version, code8)
    # Wert: [name1, name2] — bis zu zwei Bezeichnungen (DE + EN)
    entries: dict[tuple, list[str]] = {}
    levels:  dict[tuple, int]       = {}
    skipped = 0

    with open(in_path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if not line:
                continue
            parts = line.split(";")
            if len(parts) < 4:
                skipped += 1
                continue

            code8       = parts[0].strip().strip('"')
            bezeichnung = parts[1].strip().strip('"')
            ebene_raw   = parts[2].strip().strip('"')
            version     = parts[3].strip().strip('"')

            # Versions-Header (eClass 4.0;NULL;NULL;NULL) und leere Zeilen überspringen
            if _SKIP_RE.match(code8) or bezeichnung in ("NULL", "") or not code8:
                skipped += 1
                continue
            try:
                ebene = int(ebene_raw)
            except ValueError:
                skipped += 1
                continue

            key = (version, code8)
            entries.setdefault(key, []).append(bezeichnung)
            levels[key] = ebene

    # DE/EN ermitteln:
    # eClass-Versionen (4.x, 5.x, 6.x, 7.x, 8.x, 9.x ...) → kein Duplikat → immer DE
    # UNSPSC (13.1) → Duplikate → Umlaute/ß → DE, sonst → EN
    rows = []
    for (version, code8), names in entries.items():
        is_unspsc = version.startswith("13.")
        out_version = ("UNSPSC " + version) if is_unspsc else version
        if not is_unspsc:
            # eClass: alles DE, kein EN
            name_de = names[0]
            name_en = ""
        elif len(names) == 1:
            name_de = names[0] if _is_german(names[0]) else ""
            name_en = names[0] if not _is_german(names[0]) else ""
        else:
            # UNSPSC Duplikate: Deutsch erkennen, Rest ist EN
            de_names = [n for n in names if _is_german(n)]
            en_names = [n for n in names if not _is_german(n)]
            name_de  = de_names[0] if de_names else ""
            name_en  = en_names[0] if en_names else ""

        parent8 = parent_code8(code8)
        rows.append({
            "version":     out_version,
            "code":        code8_to_eclass(code8),
            "name_de":     name_de,
            "name_en":     name_en,
            "level":       LEVELS.get(levels[(version, code8)], "klasse"),
            "parent_code": code8_to_eclass(parent8) if parent8 else "",
        })

    # Sortieren: Version numerisch, dann Code
    def sort_key(r):
        try:
            v = tuple(int(x) for x in r["version"].split("."))
        except ValueError:
            v = (999,)
        return (v, r["code"])

    rows.sort(key=sort_key)

    tmp = Path(out_path).with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        f.write(CSV_HEADER + "\r\n")
        for r in rows:
            line = ";".join(_escape(r[c]) for c in CSV_HEADER.split(";"))
            f.write(line + "\r\n")
    tmp.replace(Path(out_path))

    print(f"  {len(rows):,} Einträge → {out_path}"
          + (f"  ({skipped} übersprungen)" if skipped else ""))
    return len(rows)


def _cli():
    ap = argparse.ArgumentParser(
        description="SSMS-CSV (DE+EN Duplikate) → Standard eClass CSV")
    ap.add_argument("input",  help="SSMS-Export CSV")
    ap.add_argument("--out",  default="eclass_catalog_mssql.csv")
    args = ap.parse_args()

    if not Path(args.input).exists():
        print(f"Datei nicht gefunden: {args.input}", file=sys.stderr)
        sys.exit(1)

    convert(args.input, args.out)


if __name__ == "__main__":
    _cli()
