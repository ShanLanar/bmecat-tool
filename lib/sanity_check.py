# lib/sanity_check.py – Artikel-Datenqualität und Cross-Supplier-Abgleich
#
# Fokus: Datenvollständigkeit, nicht Preise.
#   1. Per-Katalog: EAN-Abdeckung, fehlende Felder, Duplikate, Beschreibungsqualität
#   2. Cross-Supplier: Lücken die ein anderer Lieferant füllen könnte
#
# Streaming-Reads (zeilenweiser Parser), auch für 470+ MB XMLs.

import os
import re
import json
import logging
from datetime import datetime
from pathlib import Path
from collections import defaultdict

log = logging.getLogger(__name__)

# ── Extraktion ────────────────────────────────────────────────────────────────

_AID_PAT = re.compile(r"<SUPPLIER_AID>(.*?)</SUPPLIER_AID>", re.IGNORECASE)
_EAN_PAT = re.compile(
    r"<(?:EAN|INTERNATIONAL_PID[^>]*)>(.*?)</(?:EAN|INTERNATIONAL_PID)>",
    re.IGNORECASE)
_MFR_PAT = re.compile(r"<MANUFACTURER_NAME>(.*?)</MANUFACTURER_NAME>", re.IGNORECASE)
_DSH_PAT = re.compile(r"<DESCRIPTION_SHORT>(.*?)</DESCRIPTION_SHORT>", re.IGNORECASE)
_DLG_PAT = re.compile(r"<DESCRIPTION_LONG>(.*?)</DESCRIPTION_LONG>", re.IGNORECASE)
_MIM_PAT = re.compile(r"<MIME_SOURCE>(.*?)</MIME_SOURCE>", re.IGNORECASE)


def extract_catalog_data(xml_path: str, progress_cb=None) -> list:
    """
    Extrahiert Artikel-Metadaten aus einer BMEcat-XML.
    Unterstützt sowohl mehrzeilige als auch einzeilige (minifizierte) XMLs.
    """
    p = progress_cb or (lambda m, **kw: None)
    articles = []

    if not os.path.exists(xml_path):
        return articles

    from lib.utils import iter_articles

    def _strip_html(text: str) -> str:
        import html as _html
        text = _html.unescape(text)
        text = re.sub(r"<[^>]+>", " ", text)
        return " ".join(text.split())

    for art_block in iter_articles(xml_path):
        current = {
            "aid": None, "ean": None, "manufacturer": None,
            "desc_short": None, "desc_long": None, "has_image": False,
        }

        m = _AID_PAT.search(art_block)
        if m:
            current["aid"] = m.group(1).strip()

        m = _EAN_PAT.search(art_block)
        if m:
            val = m.group(1).strip()
            if val and val.isdigit() and val not in ("0",):
                current["ean"] = val

        if "MIME_SOURCE" in art_block.upper():
            current["has_image"] = True

        for field, pat in [
            ("manufacturer", re.compile(r'<MANUFACTURER_NAME>(.*?)</MANUFACTURER_NAME>', re.I | re.S)),
            ("desc_short",   re.compile(r'<DESCRIPTION_SHORT>(.*?)</DESCRIPTION_SHORT>', re.I | re.S)),
            ("desc_long",    re.compile(r'<DESCRIPTION_LONG>(.*?)</DESCRIPTION_LONG>',   re.I | re.S)),
        ]:
            fm = pat.search(art_block)
            if fm:
                current[field] = _strip_html(fm.group(1)) or None

        if current.get("aid"):
            articles.append(current)

    return articles


# ── Per-Katalog-Prüfung ──────────────────────────────────────────────────────

def check_single_catalog(articles: list, catalog_name: str) -> dict:
    """Datenqualität für einen einzelnen Katalog."""
    total = len(articles)
    if total == 0:
        return {"total": 0}

    no_ean   = [a for a in articles if not a["ean"]]
    no_mfr   = [a for a in articles if not a["manufacturer"]]
    no_dlong = [a for a in articles if not a["desc_long"]]
    no_dshrt = [a for a in articles if not a["desc_short"]]
    no_img   = [a for a in articles if not a["has_image"]]

    # Duplikate
    aid_counts = defaultdict(int)
    for a in articles:
        aid_counts[a["aid"]] += 1
    duplicates = {aid: n for aid, n in aid_counts.items() if n > 1}

    # Beschreibungsqualität: DESCRIPTION_SHORT < 5 Zeichen = vermutlich leer/Platzhalter
    short_desc_weak = [a for a in articles
                       if a["desc_short"] and len(a["desc_short"]) < 5]

    # Hersteller-Verteilung (Top 10)
    mfr_counts = defaultdict(int)
    for a in articles:
        mfr_counts[a.get("manufacturer") or "(ohne)"] += 1
    top_mfr = sorted(mfr_counts.items(), key=lambda x: -x[1])[:10]

    # EAN-Qualität: Länge prüfen (EAN-13 = 13 Stellen, EAN-8 = 8 Stellen)
    bad_ean = [a for a in articles
               if a["ean"] and len(a["ean"]) not in (8, 13, 14)]

    # GTIN-Prüfziffer validieren (GS1-Standard)
    from lib.utils import gtin_valid, gtin_fix
    invalid_gtin = []
    fixable_gtin = []
    for a in articles:
        if a["ean"] and len(a["ean"]) in (8, 13, 14):
            if not gtin_valid(a["ean"]):
                fixed = gtin_fix(a["ean"])
                if fixed and fixed != a["ean"]:
                    fixable_gtin.append({"aid": a["aid"], "ean": a["ean"], "fix": fixed})
                else:
                    invalid_gtin.append({"aid": a["aid"], "ean": a["ean"]})

    ean_pct   = round((1 - len(no_ean) / total) * 100, 1)
    mfr_pct   = round((1 - len(no_mfr) / total) * 100, 1)
    dlong_pct = round((1 - len(no_dlong) / total) * 100, 1)
    img_pct   = round((1 - len(no_img) / total) * 100, 1)

    return {
        "catalog":        catalog_name,
        "total":          total,
        "ean_coverage":   ean_pct,
        "mfr_coverage":   mfr_pct,
        "dlong_coverage": dlong_pct,
        "image_coverage": img_pct,
        "no_ean":         len(no_ean),
        "no_manufacturer": len(no_mfr),
        "no_desc_long":   len(no_dlong),
        "no_desc_short":  len(no_dshrt),
        "no_image":       len(no_img),
        "duplicate_aids": len(duplicates),
        "bad_ean_format": len(bad_ean),
        "invalid_gtin":   len(invalid_gtin),
        "fixable_gtin":   len(fixable_gtin),
        "weak_desc_short": len(short_desc_weak),
        "top_manufacturers": top_mfr,
        "examples": {
            "no_ean":       [a["aid"] for a in no_ean[:5]],
            "no_mfr":       [a["aid"] for a in no_mfr[:5]],
            "no_desc_long": [a["aid"] for a in no_dlong[:5]],
            "duplicates":   list(duplicates.keys())[:5],
            "bad_ean":      [{"aid": a["aid"], "ean": a["ean"]} for a in bad_ean[:5]],
            "invalid_gtin": invalid_gtin[:5],
            "fixable_gtin": fixable_gtin[:5],
        },
    }


# ── Cross-Supplier-Abgleich ──────────────────────────────────────────────────

def check_cross_supplier(catalogs: dict) -> dict:
    """
    Findet Datenlücken die ein anderer Lieferant füllen könnte (via EAN/GTIN).

    Prüft: manufacturer, desc_long, has_image.
    Kein Preisvergleich – B2B-Preise sind nicht direkt vergleichbar.
    """
    # EAN → {catalog_name: article_data}
    ean_index = defaultdict(dict)
    for cat_name, articles in catalogs.items():
        for art in articles:
            if art.get("ean"):
                ean_index[art["ean"]][cat_name] = art

    shared = {ean: suppliers for ean, suppliers in ean_index.items()
              if len(suppliers) > 1}

    # Lücken finden: pro Feld, pro Artikel
    fillable_fields = ("manufacturer", "desc_long")
    gaps_by_field = defaultdict(list)

    for ean, suppliers in shared.items():
        for field in fillable_fields:
            has     = [cat for cat, s in suppliers.items() if s.get(field)]
            missing = [cat for cat, s in suppliers.items() if not s.get(field)]
            if has and missing:
                source = suppliers[has[0]]
                target = suppliers[missing[0]]

                # Für Hersteller: phonetischen Vergleich nutzen
                # (verhindert "Leitz" als Lücke wenn "LEITZ GmbH" schon da ist)
                if field == "manufacturer" and target.get("manufacturer"):
                    from lib.utils import mfr_matches
                    if mfr_matches(source[field], target["manufacturer"]):
                        continue  # phonetisch identisch → keine echte Lücke

                gaps_by_field[field].append({
                    "ean":         ean,
                    "source":      has[0],
                    "source_aid":  source["aid"],
                    "target":      missing[0],
                    "target_aid":  target["aid"],
                    "value":       (source[field] or "")[:100],
                })

    # Bild-Lücken separat (has_image ist bool)
    image_gaps = []
    for ean, suppliers in shared.items():
        has     = [cat for cat, s in suppliers.items() if s.get("has_image")]
        missing = [cat for cat, s in suppliers.items() if not s.get("has_image")]
        if has and missing:
            image_gaps.append({
                "ean":        ean,
                "has_image":  has,
                "no_image":   missing,
                "aid":        suppliers[missing[0]]["aid"],
            })

    # Zusammenfassung: wie viele Lücken könnte man füllen, gruppiert nach Richtung
    fill_matrix = defaultdict(lambda: defaultdict(int))
    for field, gaps in gaps_by_field.items():
        for gap in gaps:
            fill_matrix[f"{gap['source']} → {gap['target']}"][field] += 1

    return {
        "total_unique_eans": len(ean_index),
        "shared_eans":       len(shared),
        "fillable_gaps": {
            field: len(gaps) for field, gaps in gaps_by_field.items()
        },
        "image_gaps":        len(image_gaps),
        "fill_matrix":       dict(fill_matrix),
        "top_gaps": {
            field: gaps[:15] for field, gaps in gaps_by_field.items()
        },
        "top_image_gaps":    image_gaps[:15],
    }


# ── Orchestrierung ────────────────────────────────────────────────────────────

DEFAULT_CATALOGS = {
    "Büroring":        "bueroring_merged.xml",
    "Softcarrier":     "soft-carrier_merge.xml",
    "Nordwest Arbeit": "arbeitsschutz.xml",
    "Nordwest Werkst": "werkstatt.xml",
    "Nordwest Werkzg": "werkzeugtechnik.xml",
}


def run_sanity_check(progress_cb=None, file_progress_cb=None):
    """
    Artikel-Datenqualität prüfen + Cross-Supplier-Lücken finden.
    Registriert als Extras-Task.
    """
    from config import DIRS
    p = progress_cb or (lambda m, **kw: None)
    in_bme = DIRS["in_bme"]
    log_dir = DIRS["logs"]

    p("Artikel-Sanity-Check gestartet ...")

    catalogs = {}
    single_results = {}

    for label, filename in DEFAULT_CATALOGS.items():
        path = os.path.join(in_bme, filename)
        if not os.path.exists(path):
            p(f"  {label}: übersprungen ({filename} nicht vorhanden)", tag="dim")
            continue

        p(f"  {label}: Lese {filename} ...")
        articles = extract_catalog_data(path, progress_cb=p)

        if not articles:
            p(f"  {label}: keine Artikel gefunden", tag="warn")
            continue

        catalogs[label] = articles
        r = check_single_catalog(articles, label)
        single_results[label] = r

        # Kompakte Log-Ausgabe
        p(f"  {label}: {r['total']} Artikel  │  "
          f"EAN {r['ean_coverage']}%  │  "
          f"Hersteller {r['mfr_coverage']}%  │  "
          f"Langtext {r['dlong_coverage']}%  │  "
          f"Bilder {r['image_coverage']}%",
          tag="ok" if r["ean_coverage"] > 80 else "warn")

        if r["duplicate_aids"] > 0:
            p(f"    ⚠ {r['duplicate_aids']} doppelte SUPPLIER_AIDs", tag="warn")
        if r["bad_ean_format"] > 0:
            p(f"    ⚠ {r['bad_ean_format']} EANs mit ungewöhnlicher Länge", tag="warn")
        if r["invalid_gtin"] > 0:
            p(f"    ⚠ {r['invalid_gtin']} EANs mit falscher Prüfziffer (GS1)", tag="warn")
        if r["fixable_gtin"] > 0:
            p(f"    ⚠ {r['fixable_gtin']} EANs auto-fixbar (nur letzte Stelle falsch):",
              tag="warn")
            for ex in r["examples"].get("fixable_gtin", [])[:3]:
                p(f"      {ex['aid']}: {ex['ean']} → {ex['fix']}", tag="warn")

    # Cross-Supplier-Abgleich
    if len(catalogs) >= 2:
        p("")
        p("Cross-Supplier-Abgleich (EAN/GTIN) ...")
        cross = check_cross_supplier(catalogs)

        p(f"  {cross['total_unique_eans']} eindeutige EANs gesamt, "
          f"{cross['shared_eans']} bei mehreren Lieferanten")

        # Füllbare Lücken
        for field, count in cross.get("fillable_gaps", {}).items():
            nice = {"manufacturer": "Hersteller", "desc_long": "Langbeschreibung"}.get(field, field)
            p(f"  {count} Artikel: {nice} fehlt bei einem Lieferant, "
              f"anderer hat die Daten", tag="info")

        if cross["image_gaps"] > 0:
            p(f"  {cross['image_gaps']} Artikel: Bild fehlt bei einem, "
              f"anderer hat eins", tag="info")

        # Füll-Matrix: wohin fließen die meisten Daten?
        matrix = cross.get("fill_matrix", {})
        if matrix:
            p("  Füll-Potenzial (Quelle → Ziel):")
            for direction, fields in sorted(matrix.items(),
                                             key=lambda x: -sum(x[1].values())):
                total = sum(fields.values())
                detail = ", ".join(f"{f}: {n}" for f, n in fields.items())
                p(f"    {direction}: {total} Felder ({detail})", tag="dim")

        # Beispiele
        for field, gaps in cross.get("top_gaps", {}).items():
            if gaps:
                nice = {"manufacturer": "Hersteller", "desc_long": "Langbeschreibung"}.get(field, field)
                p(f"  Beispiele {nice}:")
                for g in gaps[:3]:
                    val = g['value'][:60] + ('...' if len(g['value']) > 60 else '')
                    p(f"    EAN {g['ean']}: {g['source']} hat \"{val}\" → "
                      f"fehlt bei {g['target']} ({g['target_aid']})", tag="dim")
    else:
        cross = {}
        p("Cross-Supplier-Abgleich übersprungen (weniger als 2 Kataloge).", tag="dim")

    # JSON-Report
    report = {
        "zeitpunkt": datetime.now().isoformat(),
        "kataloge": single_results,
        "cross_supplier": cross,
    }
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(log_dir, f"sanity_{ts}.json")
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        p(f"Sanity-Report: {os.path.basename(report_path)}", tag="dim")
    except Exception as e:
        p(f"Report konnte nicht geschrieben werden: {e}", tag="warn")

    p("Artikel-Sanity-Check abgeschlossen.", tag="ok")

    # Dashboard automatisch aktualisieren
    try:
        from lib.dashboard import generate_dashboard
        dash_path = generate_dashboard(log_dir, progress_cb=p)
        if dash_path:
            p(f"Dashboard öffnen: {dash_path}", tag="dim")
    except Exception as e:
        p(f"Dashboard-Generierung übersprungen: {e}", tag="dim")

    return report
