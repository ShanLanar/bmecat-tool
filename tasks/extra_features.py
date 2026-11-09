# tasks/extra_features.py – Zusatz-Features (postprocess_features.csv) in die DB
#
# Beim DB-Import (lib/db_importer.py) werden die Zusatz-Features automatisch
# übernommen. Dieser Task spielt sie in die BEREITS vorhandenen Artikel ein,
# ohne auf den nächsten Import zu warten: gleichnamige Features werden
# ersetzt, neue hinten angehängt (lib/db_postprocess._apply_extra_features).
#
# Geänderte Artikel bekommen ein neues last_changed und einen geleerten
# content_hash – der nächste DB-Import schreibt sie damit einmal neu (mit
# denselben Zusatz-Features, danach wieder stabil).

import os
from typing import Callable

import config as _cfg
from lib.article_db import open_db, transaction, _now
from lib.db_postprocess import (_load_extra_features, _apply_extra_features,
                                apply_derived_features, _ORIGIN_FNAME)

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

    con = open_db(_cfg.DB_PATH)
    try:
        arts = con.execute(
            "SELECT id, product_id, supplier_pid FROM articles").fetchall()
        # Artikel mit Ursprungsland → Kandidaten für die Ursprungsregion
        origin_ids = {r[0] for r in con.execute(
            "SELECT DISTINCT article_id FROM article_features WHERE LOWER(fname)=?",
            (_ORIGIN_FNAME,))}
        targets = []
        matched_keys = set()
        for a in arts:
            k_pid, k_spid = (a["product_id"] or "").upper(), (a["supplier_pid"] or "").upper()
            extra = by_pid.get(k_pid) or by_spid.get(k_spid)
            if extra:
                matched_keys.add(k_pid if k_pid in by_pid else k_spid)
            if extra or a["id"] in origin_ids:
                targets.append((a["id"], a["product_id"], extra or []))
        p(f"Zusatz-Features: {len(targets)} von {len(arts)} DB-Artikeln zu prüfen "
          f"({len(origin_ids)} mit Ursprungsland)")

        changed = unchanged = 0
        now = _now()
        batch = 500
        for i in range(0, len(targets), batch):
            chunk = targets[i:i + batch]
            with transaction(con):
                for art_id, pid, extra in chunk:
                    cur = [dict(r) for r in con.execute(
                        "SELECT fname, fvalue, funit, fusage, forder, fsearchable, "
                        "fselectable, value_index FROM article_features "
                        "WHERE article_id=? ORDER BY forder, id", (art_id,))]
                    new = _apply_extra_features(cur, extra) if extra else cur
                    new = apply_derived_features(new)
                    if _norm(new) == _norm(cur):
                        unchanged += 1
                        continue
                    con.execute("DELETE FROM article_features WHERE article_id=?", (art_id,))
                    con.executemany(
                        "INSERT INTO article_features(article_id, fname, fvalue, funit, "
                        "fusage, forder, fsearchable, fselectable, value_index) "
                        "VALUES (?,?,?,?,?,?,?,?,?)",
                        [(art_id,) + tuple(f.get(c, 0 if c not in ("fname", "fvalue", "funit") else "")
                                           for c in _FEAT_COLS) for f in new])
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
      + (f", {not_in_db} CSV-Artikel nicht in der DB" if not_in_db > 0 else ""), tag="ok")
    return {"changed": changed, "unchanged": unchanged, "not_in_db": max(not_in_db, 0)}
