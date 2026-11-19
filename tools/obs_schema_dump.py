#!/usr/bin/env python3
# tools/obs_schema_dump.py – Struktur der OBS/ERP-Datenbank (MySQL) auslesen
#
# Schreibt logs/obs_schema_<ts>.txt mit allen Tabellen, die zu Artikeln,
# Preislisten, Texten, Warengruppen oder Kunden gehören könnten: Spaltennamen,
# Typen, Zeilenzahl und je Tabelle 3 Beispielzeilen (gekürzt). Grundlage für
# den Reiter "Kundenkataloge" (BMEcat aus OBS-Daten erzeugen).
#
# Zugangsdaten: config.CONNECTIONS["erp_mysql"] (wie beim Unite-Preisupdate).
# Aufruf im BASE_DIR:   py tools/obs_schema_dump.py [--all] [--like MUSTER]
#   --all          alle Tabellen statt nur der Artikel-/Preis-/Kundentabellen
#   --like MUSTER  zusätzliches Namensmuster (SQL LIKE, z.B. "%lager%")

import argparse
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_PATTERNS = ["%arti%", "%pl%", "%preis%", "%text%", "%wg%", "%waren%", "%grupp%",
             "%kund%", "%ean%", "%herst%", "%liefer%", "%bild%", "%mwst%", "%einheit%",
             "%katalog%", "%merkmal%", "%eigensch%"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--like", action="append", default=[])
    ap.add_argument("--rows", type=int, default=3)
    args = ap.parse_args()

    import config as _cfg
    from lib.config_editor import apply_overrides
    apply_overrides()          # config_user.json (Konfig-Editor) wie beim App-Start einlesen
    import pymysql
    cfg = _cfg.CONNECTIONS.get("erp_mysql", {})
    if not cfg.get("host"):
        sys.exit("CONNECTIONS['erp_mysql'] ist nicht konfiguriert (Konfiguration → Verbindungen).")
    con = pymysql.connect(host=cfg["host"], user=cfg["user"], password=cfg["password"],
                          database=cfg["database"], port=int(cfg.get("port", 3306)),
                          charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)
    out_dir = _cfg.DIRS.get("logs", ROOT)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"obs_schema_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
    db = cfg["database"]
    with con.cursor() as cur, open(path, "w", encoding="utf-8") as f:
        cur.execute("SELECT TABLE_NAME, TABLE_ROWS FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME", (db,))
        tables = cur.fetchall()
        f.write(f"OBS-Schema {db} @ {cfg['host']} – {datetime.now():%Y-%m-%d %H:%M}\n")
        f.write(f"{len(tables)} Tabellen insgesamt\n\n")
        pats = [] if args.all else _PATTERNS + args.like
        for t in tables:
            name = t["TABLE_NAME"]
            if pats and not any(_like(name, p) for p in pats):
                continue
            f.write(f"=== {name}  (~{t['TABLE_ROWS']} Zeilen)\n")
            cur.execute("SELECT COLUMN_NAME, COLUMN_TYPE, COLUMN_KEY, COLUMN_COMMENT "
                        "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s "
                        "ORDER BY ORDINAL_POSITION", (db, name))
            cols = cur.fetchall()
            for c in cols:
                key = f" [{c['COLUMN_KEY']}]" if c["COLUMN_KEY"] else ""
                cm = f"  -- {c['COLUMN_COMMENT']}" if c["COLUMN_COMMENT"] else ""
                f.write(f"  {c['COLUMN_NAME']:<32} {c['COLUMN_TYPE']}{key}{cm}\n")
            if args.rows and t["TABLE_ROWS"]:
                try:
                    cur.execute(f"SELECT * FROM `{name}` LIMIT %s", (args.rows,))
                    for r in cur.fetchall():
                        f.write("  > " + " | ".join(f"{k}={_short(v)}" for k, v in r.items()
                                                    if v not in (None, "", 0)) + "\n")
                except Exception as exc:
                    f.write(f"  (Beispielzeilen nicht lesbar: {exc})\n")
            f.write("\n")
    con.close()
    print(f"Geschrieben: {path}")


def _like(name: str, pat: str) -> bool:
    import fnmatch
    return fnmatch.fnmatch(name.lower(), pat.lower().replace("%", "*"))


def _short(v) -> str:
    s = str(v).replace("\n", " ")
    return s if len(s) <= 40 else s[:37] + "…"


if __name__ == "__main__":
    main()
