# lib/description_quality_report.py – Datenqualitäts-Report: Beschreibungen
#
# Prüft alle aktiven Artikel in der Artikel-DB auf fehlende/zu kurze
# DESCRIPTION_SHORT/DESCRIPTION_LONG sowie identische Kurz-/Langbeschreibung.
# Grundlage für die Marktplatz-Datenqualität (Unite, Brickfox-Kanäle: Conrad/
# Kaufland/Netto, Otto) – lieferantenübergreifend, arbeitet auf der DB nach
# dem Import statt auf einzelnen XMLs.

import csv
import os
from datetime import datetime

MIN_SHORT_LEN = 20   # unter dieser Länge gilt DESCRIPTION_SHORT als "zu kurz"
MIN_LONG_LEN  = 80   # unter dieser Länge gilt DESCRIPTION_LONG als "zu kurz"


def _problems(short: str, long_: str) -> list[str]:
    short = (short or "").strip()
    long_ = (long_ or "").strip()
    problems = []
    if not short:
        problems.append("Kurzbeschreibung fehlt")
    elif len(short) < MIN_SHORT_LEN:
        problems.append("Kurzbeschreibung zu kurz")
    if not long_:
        problems.append("Langbeschreibung fehlt")
    elif len(long_) < MIN_LONG_LEN:
        problems.append("Langbeschreibung zu kurz")
    if short and long_ and short.lower() == long_.lower():
        problems.append("Kurz- und Langbeschreibung identisch")
    return problems


def generate_report(db_path: str, out_dir: str, progress_cb=None) -> dict:
    """
    Prüft alle aktiven Artikel in der DB auf Beschreibungs-Lücken und
    schreibt eine CSV mit den betroffenen Artikeln.

    Returns:
        dict: {total, affected, by_supplier, by_problem, report_path}
    """
    p = progress_cb or (lambda m, **kw: None)

    from lib.article_db import open_db
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Artikel-DB nicht gefunden: {db_path}")

    con = open_db(db_path)
    rows = con.execute("""
        SELECT a.product_id, a.ean, a.description_short, a.description_long,
               s.supplier_name
        FROM articles a
        JOIN suppliers s ON s.id = a.supplier_id
        WHERE a.active = 1
        ORDER BY s.supplier_name, a.product_id
    """).fetchall()
    con.close()

    p(f"Datenqualität Beschreibungen: prüfe {len(rows):,} aktive Artikel ..."
      .replace(",", "."))

    affected    = []
    by_supplier = {}
    by_problem  = {}
    for r in rows:
        problems = _problems(r["description_short"], r["description_long"])
        if not problems:
            continue
        affected.append({
            "product_id":    r["product_id"],
            "ean":           r["ean"],
            "supplier_name": r["supplier_name"],
            "len_short":     len((r["description_short"] or "").strip()),
            "len_long":      len((r["description_long"] or "").strip()),
            "problems":      problems,
        })
        by_supplier[r["supplier_name"]] = by_supplier.get(r["supplier_name"], 0) + 1
        for pr in problems:
            by_problem[pr] = by_problem.get(pr, 0) + 1

    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(out_dir, f"qualitaet_beschreibungen_{ts}.csv")

    with open(report_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["Artikel-Nr", "EAN", "Lieferant",
                          "Länge Kurzbeschr.", "Länge Langbeschr.", "Probleme"])
        for a in affected:
            writer.writerow([
                a["product_id"], a["ean"], a["supplier_name"],
                a["len_short"], a["len_long"], "; ".join(a["problems"]),
            ])

    p(f"Datenqualität Beschreibungen: {len(affected):,} von {len(rows):,} Artikeln betroffen"
      .replace(",", "."), tag="warn" if affected else "ok")
    for supplier, n in sorted(by_supplier.items(), key=lambda x: -x[1]):
        p(f"  {supplier}: {n:,}".replace(",", "."))
    for problem, n in sorted(by_problem.items(), key=lambda x: -x[1]):
        p(f"  {problem}: {n:,}".replace(",", "."))
    p(f"Bericht: {report_path}", tag="ok")

    return {
        "total":       len(rows),
        "affected":    len(affected),
        "by_supplier": by_supplier,
        "by_problem":  by_problem,
        "report_path": report_path,
    }
