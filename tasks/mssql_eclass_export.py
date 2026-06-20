# tasks/mssql_eclass_export.py – eClass-Kategorien aus MSSQL-Archiv exportieren
#
# Quelle: [brskatel].[bur_core].[eclass_kategorien]
# Ziel:   eclass_catalog_mssql.csv  (gleiche Struktur wie eclass_catalog_scrape.py)
#
# Voraussetzung:
#   py -m pip install pyodbc
#
# CLI:
#   py tasks/mssql_eclass_export.py
#   py tasks/mssql_eclass_export.py --server localhost --db brskatel

import argparse
import csv
import logging
from pathlib import Path

log = logging.getLogger(__name__)

CATALOG_FILENAME = "eclass_catalog_mssql.csv"
CSV_HEADER       = ["version", "code", "name_de", "name_en", "level", "parent_code"]
LEVELS           = {1: "segment", 2: "hauptgruppe", 3: "gruppe", 4: "klasse"}

# Versionen die aus der MSSQL-DB stammen (zur Dokumentation)
MSSQL_VERSIONS = ["4.0", "4.1", "5.1", "5.1.1", "5.1.4", "6.2"]


# ── Code-Hilfsfunktionen ──────────────────────────────────────────────────────

def code8_to_eclass(code8: str) -> str:
    """'20010101' → '20-01-01-01'"""
    s = str(code8).zfill(8)
    seg, hg, gr, kl = s[0:2], s[2:4], s[4:6], s[6:8]
    if hg == "00": return seg
    if gr == "00": return f"{seg}-{hg}"
    if kl == "00": return f"{seg}-{hg}-{gr}"
    return f"{seg}-{hg}-{gr}-{kl}"


def parent_code8(code8: str) -> str:
    """Gibt den 8-stelligen Parent-Code zurück, oder '' für Segmente."""
    s = str(code8).zfill(8)
    if s[2:8] == "000000": return ""           # Segment → kein Parent
    if s[4:8] == "0000":   return s[0:2] + "000000"   # HG → Segment
    if s[6:8] == "00":     return s[0:4] + "0000"     # Gruppe → HG
    return s[0:6] + "00"                               # Klasse → Gruppe


# ── Export ────────────────────────────────────────────────────────────────────

def export(server: str, database: str, out_csv: str, progress_cb=None):
    p = progress_cb or log.info

    try:
        import pyodbc
    except ImportError:
        raise RuntimeError("py -m pip install pyodbc")

    conn_str = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"Trusted_Connection=yes;"
        f"TrustServerCertificate=yes;"
    )

    p(f"  Verbinde mit {server}/{database} ...")
    with pyodbc.connect(conn_str) as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT kennung, bezeichnung, ebene, version, sprache
            FROM   [bur_core].[eclass_kategorien]
            WHERE  sprache IN ('de', 'en')
              AND  kennung IS NOT NULL
              AND  ebene   IS NOT NULL
            ORDER BY eclass, kennung
        """)

        rows_de: dict[tuple, dict] = {}   # (version, kennung) → row
        rows_en: dict[tuple, str]  = {}   # (version, kennung) → name_en

        for kennung, bezeichnung, ebene, version, sprache in cursor.fetchall():
            key = (str(version), str(kennung))
            if sprache == "de":
                rows_de[key] = {
                    "version":     str(version),
                    "code":        code8_to_eclass(kennung),
                    "name_de":     bezeichnung or "",
                    "name_en":     "",
                    "level":       LEVELS.get(int(ebene), "klasse"),
                    "parent_code": code8_to_eclass(parent_code8(kennung))
                                   if parent_code8(kennung) else "",
                }
            elif sprache == "en":
                rows_en[key] = bezeichnung or ""

    # Englische Namen eintragen
    for key, name_en in rows_en.items():
        if key in rows_de:
            rows_de[key]["name_en"] = name_en

    result = list(rows_de.values())
    p(f"  {len(result):,} Einträge gelesen")

    # Nach Version + Code sortieren
    result.sort(key=lambda r: (r["version"], r["code"]))

    Path(out_csv).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(out_csv).with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_HEADER, delimiter=";",
                           extrasaction="ignore")
        w.writeheader()
        w.writerows(result)
    tmp.replace(Path(out_csv))

    p(f"  Gespeichert: {out_csv}")
    return result


# ── Task-Einstieg ─────────────────────────────────────────────────────────────

def run(progress_cb=None):
    import config as _cfg
    p = progress_cb or (lambda m, **kw: None)

    p("┌─ eClass-Export aus MSSQL-Archiv ───────────────────────────")
    p("│  Quelle: [brskatel].[bur_core].[eclass_kategorien]")
    p(f"│  Ausgabe: {CATALOG_FILENAME}")
    p("└────────────────────────────────────────────────────────────")

    out_csv = str(Path(_cfg.BASE_DIR) / CATALOG_FILENAME)
    results = export(
        server=getattr(_cfg, "MSSQL_SERVER", "localhost"),
        database=getattr(_cfg, "MSSQL_DB", "brskatel"),
        out_csv=out_csv,
        progress_cb=p,
    )
    if results:
        p(f"  Gesamt: {len(results):,} Einträge", tag="ok")
    else:
        p("  Keine Daten.", tag="error")


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cli():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    ap = argparse.ArgumentParser(description="eClass-Export aus MSSQL-Archiv")
    ap.add_argument("--server", default="localhost")
    ap.add_argument("--db",     default="brskatel")
    ap.add_argument("--out",    default=CATALOG_FILENAME)
    args = ap.parse_args()

    results = export(args.server, args.db, args.out,
                     progress_cb=lambda m, **_: print(m))
    print(f"\nFertig: {len(results):,} Einträge → {args.out}")


if __name__ == "__main__":
    _cli()
