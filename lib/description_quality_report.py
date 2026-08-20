# lib/description_quality_report.py – Datenqualitäts-Report
#
# Prüft alle aktiven Artikel in der Artikel-DB (lieferantenübergreifend, nach
# dem letzten Import) auf Lücken, die auf Marktplätzen (Unite, Brickfox-
# Kanäle: Conrad/Kaufland/Netto, Otto) zu schlechterer Sichtbarkeit oder
# Ablehnung führen können:
#
#   1. Kurz-/Langbeschreibung: fehlt, zu kurz, oder Kurz == Lang
#   2. GPSR-Herstellerdaten:   Name fehlt, oder keine Kontaktmöglichkeit
#                              (weder E-Mail noch vollständige Anschrift)
#   3. Bilder:                 kein Bild hinterlegt
#
# GPSR-Daten liegen als FEATURE mit FNAME "GPSR Hersteller <Feld>" vor
# (einheitliche Namensgebung über Nordwest/Softcarrier hinweg, siehe
# fname_renames.csv bzw. tasks/softcarrier_merge.py).

import csv
import os
from datetime import datetime

MIN_SHORT_LEN = 20   # unter dieser Länge gilt DESCRIPTION_SHORT als "zu kurz"
MIN_LONG_LEN  = 80   # unter dieser Länge gilt DESCRIPTION_LONG als "zu kurz"

_GPSR_PREFIX = "gpsr hersteller "


def _description_problems(short: str, long_: str) -> list[str]:
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


def _gpsr_problems(gpsr: dict) -> list[str]:
    """gpsr: {feldname_lower: wert} z.B. {'name': 'ACME GmbH', 'straße': '...'}."""
    if not gpsr:
        return ["GPSR: keine Herstellerdaten"]
    problems = []
    if not gpsr.get("name"):
        problems.append("GPSR: Herstellername fehlt")
    has_email = bool(gpsr.get("e-mail") or gpsr.get("email"))
    has_address = bool(gpsr.get("straße") and gpsr.get("plz") and gpsr.get("ort"))
    if not has_email and not has_address:
        problems.append("GPSR: keine Kontaktmöglichkeit (E-Mail/Anschrift)")
    return problems


def _image_problems(mime_count: int) -> list[str]:
    return ["Kein Bild hinterlegt"] if mime_count == 0 else []


def generate_report(db_path: str, out_dir: str, progress_cb=None) -> dict:
    """
    Prüft alle aktiven Artikel in der DB (Beschreibungen, GPSR-Herstellerdaten,
    Bilder) und schreibt eine CSV mit den betroffenen Artikeln.

    Returns:
        dict: {total, affected, by_supplier, by_problem, report_path}
    """
    p = progress_cb or (lambda m, **kw: None)

    from lib.article_db import open_db
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Artikel-DB nicht gefunden: {db_path}")

    con = open_db(db_path)
    rows = con.execute("""
        SELECT a.id, a.product_id, a.ean, a.description_short, a.description_long,
               s.supplier_name
        FROM articles a
        JOIN suppliers s ON s.id = a.supplier_id
        WHERE a.active = 1
        ORDER BY s.supplier_name, a.product_id
    """).fetchall()

    p(f"Datenqualität: prüfe {len(rows):,} aktive Artikel ...".replace(",", "."))

    # GPSR-Feature-Werte je Artikel (nur GPSR-Hersteller-* Features, gebündelt
    # statt N+1-Abfrage pro Artikel)
    gpsr_by_article: dict[int, dict] = {}
    for r in con.execute("""
        SELECT article_id, fname, fvalue FROM article_features
        WHERE fname LIKE 'GPSR Hersteller%' AND fvalue != ''
    """):
        fname = (r["fname"] or "").strip().lower()
        if not fname.startswith(_GPSR_PREFIX):
            continue
        field = fname[len(_GPSR_PREFIX):].strip()
        gpsr_by_article.setdefault(r["article_id"], {})[field] = r["fvalue"]

    # Bilder-Anzahl je Artikel
    mime_count_by_article: dict[int, int] = {
        r["article_id"]: r["n"] for r in con.execute(
            "SELECT article_id, COUNT(*) AS n FROM article_mimes GROUP BY article_id")
    }
    con.close()

    affected    = []
    by_supplier = {}
    by_problem  = {}
    for r in rows:
        art_id = r["id"]
        problems = (
            _description_problems(r["description_short"], r["description_long"])
            + _gpsr_problems(gpsr_by_article.get(art_id, {}))
            + _image_problems(mime_count_by_article.get(art_id, 0))
        )
        if not problems:
            continue
        affected.append({
            "product_id":    r["product_id"],
            "ean":           r["ean"],
            "supplier_name": r["supplier_name"],
            "len_short":     len((r["description_short"] or "").strip()),
            "len_long":      len((r["description_long"] or "").strip()),
            "n_images":      mime_count_by_article.get(art_id, 0),
            "problems":      problems,
        })
        by_supplier[r["supplier_name"]] = by_supplier.get(r["supplier_name"], 0) + 1
        for pr in problems:
            by_problem[pr] = by_problem.get(pr, 0) + 1

    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(out_dir, f"datenqualitaet_{ts}.csv")

    with open(report_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["Artikel-Nr", "EAN", "Lieferant",
                          "Länge Kurzbeschr.", "Länge Langbeschr.",
                          "Bilder", "Probleme"])
        for a in affected:
            writer.writerow([
                a["product_id"], a["ean"], a["supplier_name"],
                a["len_short"], a["len_long"], a["n_images"],
                "; ".join(a["problems"]),
            ])

    p(f"Datenqualität: {len(affected):,} von {len(rows):,} Artikeln betroffen"
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
