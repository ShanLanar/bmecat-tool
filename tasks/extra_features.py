# tasks/extra_features.py – Zusatz-Features + Marken in die DB
#
# Beim DB-Import (lib/db_importer.py) werden Zusatz-Features
# (postprocess_features.csv), abgeleitete Features (Ursprungsregion) und
# Marken-Umbenennungen (postprocess_brands.csv) automatisch übernommen.
# Dieser Task spielt sie in die BEREITS vorhandenen Artikel ein, ohne auf den
# nächsten Import zu warten: gleichnamige Features werden ersetzt, neue hinten
# angehängt (lib/db_postprocess._apply_extra_features); MANUFACTURER_NAME und
# die Features Marke/Hersteller werden laut Regeln umbenannt.
#
# Geänderte Artikel bekommen ein neues last_changed und einen geleerten
# content_hash – der nächste DB-Import schreibt sie damit einmal neu (mit
# denselben Werten, danach wieder stabil).

import os
from typing import Callable

import config as _cfg
from lib.article_db import open_db, transaction, _now
from lib.db_postprocess import (_load_extra_features, _apply_extra_features,
                                apply_derived_features, _ORIGIN_FNAME,
                                _load_brand_rules, rename_brand, _BRAND_FNAMES,
                                _target_units)
from lib.dimension_normalize import normalize_dimension_features, _carriers

_FEAT_COLS = ("fname", "fvalue", "funit", "fusage", "forder",
              "fsearchable", "fselectable", "value_index")


def _norm(features: list) -> list:
    return sorted(
        (str(f.get("fname") or ""), str(f.get("fvalue") or ""), str(f.get("funit") or ""))
        for f in features
    )


def run(progress_cb: Callable = None, file_progress_cb: Callable = None) -> dict:
    p = progress_cb or (lambda m, **kw: None)

    path = os.path.join(_cfg.BASE_DIR, "postprocess_features.csv")
    by_pid, by_spid = ({}, {})
    if os.path.exists(path):
        by_pid, by_spid = _load_extra_features(_cfg.BASE_DIR)
        p(f"Zusatz-Features: {len(by_pid) + len(by_spid)} Artikel in postprocess_features.csv")
    else:
        p(f"Zusatz-Features: {path} nicht gefunden – nur abgeleitete Features "
          f"(Ursprungsregion).", tag="dim")
    brand_rules = _load_brand_rules(_cfg.BASE_DIR)
    if brand_rules:
        p(f"Marken: {len(brand_rules)} Regeln in postprocess_brands.csv")

    con = open_db(_cfg.DB_PATH)
    try:
        arts = con.execute(
            "SELECT id, product_id, supplier_pid, manufacturer_name FROM articles").fetchall()
        # Artikel mit Ursprungsland → Kandidaten für die Ursprungsregion
        origin_ids = {r[0] for r in con.execute(
            "SELECT DISTINCT article_id FROM article_features WHERE LOWER(fname)=?",
            (_ORIGIN_FNAME,))}
        # Artikel mit Marke/Hersteller-Feature → Kandidaten für Marken-Regeln
        brand_feat_ids = set()
        if brand_rules:
            ph = ",".join("?" * len(_BRAND_FNAMES))
            brand_feat_ids = {r[0] for r in con.execute(
                f"SELECT DISTINCT article_id FROM article_features WHERE LOWER(fname) IN ({ph})",
                _BRAND_FNAMES)}
        # Artikel mit Maß-Features ohne Einheit, Nullwert oder Träger-Feature
        # (Maßeinheit/Gewichtseinheit) → Kandidaten für die Maß-Normalisierung
        dim_names = tuple(_target_units())
        ph = ",".join("?" * len(dim_names))
        dim_ids = {r[0] for r in con.execute(
            f"SELECT DISTINCT article_id FROM article_features WHERE LOWER(TRIM(fname)) IN ({ph}) "
            f"AND (TRIM(COALESCE(funit,''))='' OR fvalue LIKE '%,%' OR TRIM(fvalue) IN ('0','0.0','0,000','0.000'))",
            dim_names)}
        car_names = tuple(_carriers())
        ph = ",".join("?" * len(car_names))
        dim_ids |= {r[0] for r in con.execute(
            f"SELECT DISTINCT article_id FROM article_features WHERE LOWER(TRIM(fname)) IN ({ph})",
            car_names)}
        targets = []
        matched_keys = set()
        for a in arts:
            k_pid, k_spid = (a["product_id"] or "").upper(), (a["supplier_pid"] or "").upper()
            extra = by_pid.get(k_pid) or by_spid.get(k_spid)
            if extra:
                matched_keys.add(k_pid if k_pid in by_pid else k_spid)
            new_brand = rename_brand(a["manufacturer_name"] or "", a["product_id"], brand_rules) \
                if brand_rules else None
            if (extra or a["id"] in origin_ids or new_brand is not None
                    or a["id"] in brand_feat_ids or a["id"] in dim_ids):
                targets.append((a["id"], a["product_id"], extra or [], new_brand))
        p(f"Zusatz-Features: {len(targets)} von {len(arts)} DB-Artikeln zu prüfen "
          f"({len(origin_ids)} mit Ursprungsland, {len(dim_ids)} mit Maßen zum Vereinheitlichen"
          + (f", {len(brand_feat_ids)} mit Marke/Hersteller-Feature" if brand_rules else "") + ")")

        changed = unchanged = brands = 0
        now = _now()
        batch = 500
        for i in range(0, len(targets), batch):
            chunk = targets[i:i + batch]
            with transaction(con):
                for art_id, pid, extra, new_brand in chunk:
                    cur = [dict(r) for r in con.execute(
                        "SELECT fname, fvalue, funit, fusage, forder, fsearchable, "
                        "fselectable, value_index FROM article_features "
                        "WHERE article_id=? ORDER BY forder, id", (art_id,))]
                    new, _ = normalize_dimension_features(cur)
                    new = _apply_extra_features(new, extra) if extra else new
                    new = apply_derived_features(new)
                    if brand_rules:
                        new = [dict(f) for f in new]
                        for f in new:
                            if (f.get("fname") or "").strip().lower() in _BRAND_FNAMES:
                                nv = rename_brand(f.get("fvalue") or "", pid, brand_rules)
                                if nv is not None:
                                    f["fvalue"] = nv
                    feats_changed = _norm(new) != _norm(cur)
                    if not feats_changed and new_brand is None:
                        unchanged += 1
                        continue
                    if feats_changed:
                        con.execute("DELETE FROM article_features WHERE article_id=?", (art_id,))
                        con.executemany(
                            "INSERT INTO article_features(article_id, fname, fvalue, funit, "
                            "fusage, forder, fsearchable, fselectable, value_index) "
                            "VALUES (?,?,?,?,?,?,?,?,?)",
                            [(art_id,) + tuple(f.get(c, 0 if c not in ("fname", "fvalue", "funit") else "")
                                               for c in _FEAT_COLS) for f in new])
                    if new_brand is not None:
                        con.execute("UPDATE articles SET manufacturer_name=? WHERE id=?",
                                    (new_brand, art_id))
                        brands += 1
                    con.execute(
                        "UPDATE articles SET last_changed=?, content_hash='' WHERE id=?",
                        (now, art_id))
                    changed += 1
            if file_progress_cb:
                try:
                    file_progress_cb(min(i + batch, len(targets)), len(targets))
                except Exception:
                    pass
            p(f"  {min(i + batch, len(targets))}/{len(targets)} geprüft, {changed} geändert")
    finally:
        con.close()

    not_in_db = sum(1 for k in list(by_pid) + list(by_spid) if k not in matched_keys)
    p(f"Zusatz-Features: {changed} Artikel aktualisiert, {unchanged} bereits aktuell"
      + (f", {brands} Marken (MANUFACTURER_NAME) umbenannt" if brands else "")
      + (f", {not_in_db} CSV-Artikel nicht in der DB" if not_in_db > 0 else ""), tag="ok")
    return {"changed": changed, "unchanged": unchanged, "brands": brands,
            "not_in_db": max(not_in_db, 0)}
