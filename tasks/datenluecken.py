# tasks/datenluecken.py – Datenlücken je Marke auswerten
#
# Zählt für alle aktiven Artikel, welche Pflichtwerte fehlen, und gruppiert
# nach Marke (MANUFACTURER_NAME) und Lieferant. Geprüft werden die Features
# aus config.GAP_CHECK_FEATURES (Standard: Länge, Breite, Höhe, Gewicht,
# Ursprungsland) sowie Bild (mind. ein Bild-MIME) und Langbeschreibung.
#
# Zusätzlich: wie viele der Lücken ließen sich aus den EIGENEN Katalogen
# füllen – ein anderer Lieferant führt denselben Artikel (gleiche EAN) und hat
# den Wert. Das ist die Entscheidungsgrundlage, ob sich ein Crossfill-Task,
# Icecat oder Herstellerseiten lohnen.
#
# Ausgabe (logs/):
#   datenluecken_marken_<ts>.csv   – je Marke+Lieferant: Artikel, fehlt_<Wert>,
#                                    fuellbar_<Wert> (per EAN aus anderem Lieferanten)
#   datenluecken_artikel_<ts>.csv  – je Artikel mit mind. einer Lücke:
#                                    fehlende Werte, EAN, Spender-Artikel (falls vorhanden)

import csv
import os
from collections import defaultdict
from datetime import datetime
from typing import Callable

import config as _cfg
from lib.article_db import open_db

_DEFAULT_FEATURES = ["Länge", "Breite", "Höhe", "Gewicht", "Ursprungsland"]
_IMAGE_EXT = (".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff", ".webp", ".bmp")


def _features_to_check() -> list:
    cfg = getattr(_cfg, "GAP_CHECK_FEATURES", None)
    return [str(f).strip() for f in cfg if str(f).strip()] if cfg else list(_DEFAULT_FEATURES)


def _slug(name: str) -> str:
    return (name.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
            .replace("ß", "ss").replace(" ", "_"))


def run(progress_cb: Callable = None, file_progress_cb: Callable = None) -> dict:
    p = progress_cb or (lambda m, **kw: None)
    feats = _features_to_check()
    checks = feats + ["Bild", "Langbeschreibung"]
    p(f"Datenlücken: prüfe {', '.join(checks)} für alle aktiven Artikel …")

    con = open_db(_cfg.DB_PATH)
    try:
        arts = con.execute("""
            SELECT a.id, a.product_id, a.ean, a.manufacturer_name, a.description_long,
                   s.supplier_name
            FROM articles a JOIN suppliers s ON s.id = a.supplier_id
            WHERE a.active = 1
        """).fetchall()
        p(f"  {len(arts)} aktive Artikel")

        # Vorhandene Feature-Werte (nur die geprüften Namen, nicht leer)
        lower_names = {f.lower(): f for f in feats}
        ph = ",".join("?" * len(lower_names))
        has_feat = defaultdict(set)      # article_id → {feature_name}
        for aid, fname in con.execute(
                f"SELECT article_id, fname FROM article_features "
                f"WHERE LOWER(TRIM(fname)) IN ({ph}) AND TRIM(COALESCE(fvalue,'')) <> ''",
                tuple(lower_names)):
            has_feat[aid].add(lower_names[fname.strip().lower()])

        has_img = set()
        for aid, src, mt in con.execute(
                "SELECT article_id, mime_source, mime_type FROM article_mimes "
                "WHERE TRIM(COALESCE(mime_source,'')) <> ''"):
            if (mt or "").lower().startswith("image/") or (src or "").lower().endswith(_IMAGE_EXT):
                has_img.add(aid)
    finally:
        con.close()

    # Welche Werte hat jeder Artikel? → je Check ein Set der Artikel-IDs mit Wert
    def _present(a) -> set:
        s = set(has_feat.get(a["id"], ()))
        if a["id"] in has_img:
            s.add("Bild")
        if (a["description_long"] or "").strip():
            s.add("Langbeschreibung")
        return s

    present = {a["id"]: _present(a) for a in arts}

    # EAN → Artikel anderer Lieferanten (Spender). EANs, die bei EINEM
    # Lieferanten mehrfach vorkommen (Verpackungsvarianten), zählen nicht.
    by_ean = defaultdict(list)
    for a in arts:
        ean = (a["ean"] or "").strip()
        if len(ean) >= 8 and ean.isdigit():
            by_ean[ean].append(a)
    ambiguous = set()
    for ean, lst in by_ean.items():
        seen = set()
        for a in lst:
            if a["supplier_name"] in seen:
                ambiguous.add(ean)
                break
            seen.add(a["supplier_name"])

    summary = defaultdict(lambda: {"artikel": 0, **{f"fehlt_{c}": 0 for c in checks},
                                   **{f"fuellbar_{c}": 0 for c in checks}})
    detail_rows = []
    total_missing = defaultdict(int)
    total_fillable = defaultdict(int)
    n = len(arts)
    for i, a in enumerate(arts, 1):
        brand = (a["manufacturer_name"] or "").strip() or "(ohne Marke)"
        key = (brand, a["supplier_name"])
        row = summary[key]
        row["artikel"] += 1
        have = present[a["id"]]
        missing = [c for c in checks if c not in have]
        if not missing:
            continue
        ean = (a["ean"] or "").strip()
        donors = [d for d in by_ean.get(ean, []) if d["supplier_name"] != a["supplier_name"]] \
            if ean and ean not in ambiguous else []
        fillable, donor_pids = [], []
        for c in missing:
            row[f"fehlt_{c}"] += 1
            total_missing[c] += 1
            d = next((d for d in donors if c in present[d["id"]]), None)
            if d:
                row[f"fuellbar_{c}"] += 1
                total_fillable[c] += 1
                fillable.append(c)
                if d["product_id"] not in donor_pids:
                    donor_pids.append(d["product_id"])
        detail_rows.append([a["product_id"], a["supplier_name"], brand, ean,
                            ", ".join(missing), ", ".join(fillable), ", ".join(donor_pids)])
        if file_progress_cb and (i % 5000 == 0 or i == n):
            try:
                file_progress_cb(i, n)
            except Exception:
                pass

    logs = _cfg.DIRS.get("logs", ".")
    os.makedirs(logs, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    sum_path = os.path.join(logs, f"datenluecken_marken_{ts}.csv")
    det_path = os.path.join(logs, f"datenluecken_artikel_{ts}.csv")

    cols = (["marke", "lieferant", "artikel", "artikel_mit_luecke"]
            + [f"fehlt_{_slug(c)}" for c in checks] + [f"fuellbar_{_slug(c)}" for c in checks])
    with open(sum_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(cols)
        # Artikel mit mindestens einer Lücke je Marke/Lieferant
        gaps_per_key = defaultdict(int)
        for r in detail_rows:
            gaps_per_key[(r[2], r[1])] += 1
        ordered = sorted(summary.items(), key=lambda kv: -gaps_per_key.get(kv[0], 0))
        for (brand, sup), r in ordered:
            w.writerow([brand, sup, r["artikel"], gaps_per_key.get((brand, sup), 0)]
                       + [r[f"fehlt_{c}"] for c in checks] + [r[f"fuellbar_{c}"] for c in checks])
    with open(det_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["product_id", "lieferant", "marke", "ean", "fehlt", "fuellbar_per_ean", "spender"])
        w.writerows(detail_rows)

    p(f"Datenlücken: {len(detail_rows)} von {n} aktiven Artikeln mit mindestens einer Lücke; "
      f"{len(ambiguous)} EANs wegen Mehrfachbelegung beim selben Lieferanten nicht als Spender genutzt",
      tag="ok")
    for c in checks:
        m, fl = total_missing[c], total_fillable[c]
        p(f"  {c:<18} fehlt bei {m:>7}   davon per EAN aus eigenem Katalog füllbar: {fl:>6}"
          + (f" ({fl * 100 // m} %)" if m else ""))
    top = sorted(gaps_per_key.items(), key=lambda kv: -kv[1])[:15]
    if top:
        p("  Marken mit den meisten Lückenartikeln:")
        for (brand, sup), cnt in top:
            p(f"    {cnt:>6}  {brand}  [{sup}]", tag="dim")
    p(f"→ {os.path.basename(sum_path)}  |  {os.path.basename(det_path)}", tag="ok")
    return {"articles": n, "with_gaps": len(detail_rows),
            "missing": dict(total_missing), "fillable": dict(total_fillable),
            "summary_file": sum_path, "detail_file": det_path}
