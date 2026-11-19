# lib/kundenkatalog_obs.py – Artikel aus dem OBS (ERP, MySQL) für Kundenkataloge
#
# Zweite Datenquelle für lib/kundenkatalog.py: Preislisten-Artikel, die nicht
# in der Artikel-DB stehen, werden versuchsweise aus dem OBS gelesen und in
# dieselbe Artikelstruktur gebracht wie DB-Artikel (query_by_ids-Format).
#
# Schlüssel ist die Bestellnummer artikel.A_BESTNR1 (= SUPPLIER_AID der
# Preisliste, siehe lib/unite_price_update._PRICE_LIST_SQL).
#
# Quellen je Artikel (OBS-Tabellen laut obs_schema_dump):
#   artikel            A_NR, A_NAME1/A_NAME2 (Kurztext), A_EAN, A_HERSTELLERNR,
#                      A_HERSTELLERNAME, A_WGR/A_WGRU (Warengruppe), A_LIEFER1,
#                      A_BESTNR1, A_EINHEIT, A_MENGEINH, A_SUCHTEXT, A_URLAND,
#                      A_AGEWICHT, A_INAKTIV, DELETED
#   p_arti             Lieferantenkatalog-Spiegel (NR=Bestellnr, LIEFNR):
#                      LANGTEXT, BEZ1/BEZ2, EAN, HERSTARTNR, GEWICHT, VERPAMENGE
#   p_merkmale         Features des Lieferantenkatalogs (PM_NR, PM_LIEFNR)
#   p_bilder           Bilder (PFAD, TYP normal/detail/thumbnail)
#   artikel_merkmale   OBS-eigene Merkmale → s_merkmale.M_FNAME / s_merkmale_werte.MW_FVALUE
#   ean                weitere EANs (E_NR = A_NR)
#   arti_exttext       Artikeltexte (EA_ARTNR = A_NR, EA_TYP 9103)
#   user_catmapping    Warengruppe → Shop-Kategorie: MP_WGR=A_WGR, MP_UWGR=A_WGRU
#                      → MP_CATCODE (Code in custom_categories.csv), MP_BEZ
#
# Jede Teilabfrage ist optional: schlägt sie fehl (Tabelle/Spalte anders als
# erwartet), wird gewarnt und der Katalog ohne diese Daten erzeugt.

import re
from typing import Callable

_CHUNK = 400


def _connect(cfg: dict):
    import pymysql
    return pymysql.connect(host=cfg["host"], user=cfg["user"], password=cfg["password"],
                           database=cfg["database"], port=int(cfg.get("port", 3306)),
                           charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)


def _chunks(seq, n=_CHUNK):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _q(cur, sql: str, params, label: str, warn: Callable) -> list:
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    except Exception as exc:
        warn(f"  OBS {label}: Abfrage fehlgeschlagen – {exc}")
        return []


_RTF_PAT = re.compile(r"^\s*\{\\rtf")
_TAG_PAT = re.compile(r"<[^>]+>")


def _plain(text) -> str:
    """RTF/HTML grob in Klartext; leer bei RTF ohne brauchbaren Inhalt."""
    s = (text or "")
    if isinstance(s, bytes):
        s = s.decode("cp1252", errors="replace")
    s = s.strip()
    if not s:
        return ""
    if _RTF_PAT.match(s):
        s = re.sub(r"\\par[d]?", "\n", s)
        s = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: bytes.fromhex(m.group(1)).decode("cp1252", "replace"), s)
        s = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", s)
        s = s.replace("{", "").replace("}", "")
    s = _TAG_PAT.sub(" ", s)
    import html
    s = html.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


# BMEcat-Einheit aus s_einh (SE_NR = artikel.A_EINHEIT → SE_EDIFAKT); "St" ist in
# OBS der Stück-Code, BMEcat/Vorlage nutzen C62.
_EDIFAKT_FIX = {"ST": "C62", "PCE": "C62", "": "C62"}


def load_units(cur, warn: Callable) -> dict:
    rows = _q(cur, "SELECT SE_NR, SE_EDIFAKT FROM s_einh", (), "s_einh", warn)
    out = {}
    for r in rows:
        nr = (r.get("SE_NR") or "").strip()
        edi = (r.get("SE_EDIFAKT") or "").strip().upper()
        if nr:
            out[nr] = _EDIFAKT_FIX.get(edi, edi)
    return out


# eClass-/UDF-codierte Merkmalsnamen (BAF302003, AAO847002 …) – ohne Klartext
# für den Kunden wertlos, Klartext-Varianten kommen aus p_merkmale.
_CODE_NAME = re.compile(r"^[A-Z]{3}\d{6}$")


def fetch_price_list_full(cfg: dict, price_list_nrs: list, progress_cb: Callable = None) -> dict:
    """
    Preisliste(n) mit allen Artikelnummern des OBS-Artikels:
    {A_NR: {"nr", "artnr", "bestnr": [A_BESTNR1..5], "ean", "price", "tax"}}
    Bei mehreren Listen gewinnt je Artikel der niedrigste PL_VK1.
    """
    p = progress_cb or (lambda m, **kw: None)
    ph = ", ".join(["%s"] * len(price_list_nrs))
    sql = f"""
        SELECT a.A_NR, a.A_ARTNR, a.A_BESTNR1, a.A_BESTNR2, a.A_BESTNR3, a.A_BESTNR4, a.A_BESTNR5,
               a.A_EAN, mw.MW_SATZ / 100 AS tax, MIN(pl.PL_VK1) AS price
        FROM arti_pl pl
        JOIN artikel a ON a.A_NR = pl.PL_ARTNR
        LEFT JOIN s_mwst mw ON mw.MW_NR = a.A_MWSTSCHL
        WHERE pl.PL_NR IN ({ph})
        GROUP BY a.A_NR"""
    con = _connect(cfg)
    out = {}
    try:
        cur = con.cursor()
        cur.execute(sql, tuple(price_list_nrs))
        for r in cur.fetchall():
            nr = (r.get("A_NR") or "").strip()
            if not nr:
                continue
            bestnr = [(r.get(f"A_BESTNR{i}") or "").strip() for i in range(1, 6)]
            out[nr] = {"nr": nr, "artnr": (r.get("A_ARTNR") or "").strip(),
                       "bestnr": [b for b in bestnr if b], "ean": (r.get("A_EAN") or "").strip(),
                       "price": r.get("price"), "tax": r.get("tax")}
    finally:
        con.close()
    p(f"Preisliste(n) {', '.join(map(str, price_list_nrs))}: {len(out)} Artikel im ERP")
    return out


def load_catmapping(cur, warn: Callable) -> dict:
    """{(MP_WGR, MP_UWGR): (MP_CATCODE, MP_BEZ)}"""
    rows = _q(cur, "SELECT MP_WGR, MP_UWGR, MP_CATCODE, MP_BEZ FROM user_catmapping", (), "user_catmapping", warn)
    out = {}
    for r in rows:
        key = ((r.get("MP_WGR") or "").strip(), (r.get("MP_UWGR") or "").strip())
        out[key] = ((r.get("MP_CATCODE") or "").strip(), (r.get("MP_BEZ") or "").strip())
    return out


def fetch_obs_articles(cfg: dict, entries: list, progress_cb: Callable = None) -> tuple:
    """
    entries: Preislisten-Einträge (fetch_price_list_full: nr, artnr, bestnr, …).
    Returns (articles, stats); articles im Format von query_by_ids
    (+ kk_source="obs", kk_nr=A_NR, kk_path). SUPPLIER_AID = A_ARTNR, sonst
    A_BESTNR1, sonst A_NR. Lieferantenkatalog-Daten (p_*) über A_BESTNR1.
    """
    p = progress_cb or (lambda m, **kw: None)
    warn = lambda m: p(m, tag="warn")
    if not entries:
        return [], {}
    by_entry_nr = {e["nr"]: e for e in entries}
    aids = list(by_entry_nr)
    con = _connect(cfg)
    arts: dict = {}
    stats = {"artikel": 0, "p_arti": 0, "p_merkmale": 0, "p_bilder": 0, "artikel_merkmale": 0,
             "ean": 0, "exttext": 0, "catmapping": 0, "inaktiv": 0}
    try:
        cur = con.cursor()
        catmap = load_catmapping(cur, warn)
        units = load_units(cur, warn)

        # 1) Stammdaten
        for chunk in _chunks(aids):
            ph = ",".join(["%s"] * len(chunk))
            rows = _q(cur, f"""
                SELECT A_NR, A_BESTNR1, A_LIEFER1, A_NAME1, A_NAME2, A_EAN, A_HERSTELLERNR,
                       A_HERSTELLERNAME, A_WGR, A_WGRU, A_EINHEIT, A_MENGEINH, A_SUCHTEXT,
                       A_LANGTEXTANSI, A_URLAND, A_AGEWICHT, A_INAKTIV, DELETED, A_MWSTSCHL
                FROM artikel WHERE A_NR IN ({ph})""", tuple(chunk), "artikel", warn)
            for r in rows:
                nr = (r.get("A_NR") or "").strip()
                e = by_entry_nr.get(nr)
                if not e or nr.lower() in arts:
                    continue
                bestnr = (r.get("A_BESTNR1") or "").strip()
                aid = e.get("artnr") or (e.get("bestnr") or [""])[0] or bestnr or nr
                if (r.get("DELETED") or "0").strip() == "1":
                    continue
                if (r.get("A_INAKTIV") or "0").strip() == "1":
                    stats["inaktiv"] += 1
                short = " ".join(x for x in ((r.get("A_NAME1") or "").strip(), (r.get("A_NAME2") or "").strip()) if x)
                art = {
                    "id": None, "kk_source": "obs", "kk_nr": nr,
                    "product_id": aid, "supplier_pid": aid, "obs_nr": nr, "obs_bestnr": bestnr,
                    "obs_liefnr": (r.get("A_LIEFER1") or "").strip(),
                    "supplier_name": "OBS",
                    "description_short": short,
                    "description_long": "",
                    "obs_suchtext": re.sub(r"\s*\n\s*", "\n", _plain(r.get("A_SUCHTEXT")) or "").strip(),
                    "ean": (r.get("A_EAN") or "").strip(),
                    "manufacturer_aid": (r.get("A_HERSTELLERNR") or "").strip(),
                    "manufacturer_name": (r.get("A_HERSTELLERNAME") or "").strip(),
                    "delivery_time": "",
                    "order_unit": units.get((r.get("A_EINHEIT") or "").strip(), "C62"),
                    "content_unit": units.get((r.get("A_EINHEIT") or "").strip(), "C62"),
                    "no_cu_per_ou": "1",
                    "obs_wgr": (r.get("A_WGR") or "").strip(), "obs_wgru": (r.get("A_WGRU") or "").strip(),
                    "price_quantity": str(int(r["A_MENGEINH"])) if r.get("A_MENGEINH") else "1",
                    "quantity_min": "1", "quantity_interval": "1",
                    "reference_feature_system": "udf_OBS-1.0", "reference_feature_group_id": "",
                    "features": [], "mimes": [], "keywords": [], "references": [], "udx": [],
                    "kk_path": [],
                }
                land = (r.get("A_URLAND") or "").strip()
                if land:
                    art["features"].append({"fname": "Ursprungsland", "fvalue": land, "funit": ""})
                gew = r.get("A_AGEWICHT")
                if gew and float(gew) > 0:
                    art["features"].append({"fname": "Gewicht", "fvalue": f"{float(gew):g}", "funit": "kg"})
                wg = ((r.get("A_WGR") or "").strip(), (r.get("A_WGRU") or "").strip())
                cm = catmap.get(wg) or catmap.get((wg[0], ""))
                if cm and cm[0]:
                    art["kk_path"] = [(cm[0], cm[1] or cm[0])]
                    stats["catmapping"] += 1
                arts[nr.lower()] = art
        stats["artikel"] = len(arts)
        p(f"  OBS artikel: {len(arts)} von {len(aids)} Artikelnummern gefunden "
          f"({stats['inaktiv']} inaktiv, {stats['catmapping']} mit Kategorie-Mapping)")
        if not arts:
            return [], stats

        by_nr = {a["obs_nr"]: a for a in arts.values() if a["obs_nr"]}
        by_best = {}
        for a in arts.values():
            if a["obs_bestnr"]:
                by_best.setdefault(a["obs_bestnr"].lower(), a)
        keys = [a for a in arts.values() if a["obs_bestnr"]]

        # 2) Lieferantenkatalog-Spiegel p_arti (Langtext, EAN, Hersteller-Nr, Gewicht)
        for chunk in _chunks(keys):
            ph = ",".join(["%s"] * len(chunk))
            rows = _q(cur, f"""
                SELECT NR, LIEFNR, BEZ1, BEZ2, LANGTEXT, EAN, HERSTARTNR, GEWICHT, VERPAMENGE
                FROM p_arti WHERE NR IN ({ph})""", tuple(a["obs_bestnr"] for a in chunk), "p_arti", warn)
            # Zeile des Hauptlieferanten (A_LIEFER1) bevorzugen, sonst irgendeine
            rows.sort(key=lambda r: 0 if (r.get("LIEFNR") or "").strip() == (by_best.get((r.get("NR") or "").strip().lower()) or {}).get("obs_liefnr") else 1)
            done = set()
            for r in rows:
                key = (r.get("NR") or "").strip().lower()
                a = by_best.get(key)
                if not a or key in done:
                    continue
                done.add(key)
                stats["p_arti"] += 1
                lt = _plain(r.get("LANGTEXT"))
                if lt:
                    a["description_long"] = lt
                if not a["ean"] and (r.get("EAN") or "").strip():
                    a["ean"] = r["EAN"].strip()
                if not a["manufacturer_aid"] and (r.get("HERSTARTNR") or "").strip():
                    a["manufacturer_aid"] = r["HERSTARTNR"].strip()
                if not a["description_short"]:
                    a["description_short"] = " ".join(x for x in (_plain(r.get("BEZ1")), _plain(r.get("BEZ2"))) if x)
                g = r.get("GEWICHT")
                if g and float(g) > 0 and not any(f["fname"] == "Gewicht" for f in a["features"]):
                    a["features"].append({"fname": "Gewicht", "fvalue": f"{float(g):g}", "funit": "kg"})

        # 3) Features aus p_merkmale
        for chunk in _chunks(keys):
            ph = ",".join(["%s"] * len(chunk))
            rows = _q(cur, f"""
                SELECT PM_NR, PM_LIEFNR, PM_NAME, PM_WERT, PM_UNIT, PM_LFDNR, PM_ECLASSVERSION
                FROM p_merkmale WHERE PM_NR IN ({ph}) ORDER BY PM_NR, PM_LFDNR""",
                tuple(a["obs_bestnr"] for a in chunk), "p_merkmale", warn)
            for r in rows:
                a = by_best.get((r.get("PM_NR") or "").strip().lower())
                if not a:
                    continue
                if a["obs_liefnr"] and (r.get("PM_LIEFNR") or "").strip() not in ("", a["obs_liefnr"]):
                    continue
                name = (r.get("PM_NAME") or "").strip()
                val = (r.get("PM_WERT") or "").strip()
                if not name or not val:
                    continue
                if any(f["fname"].lower() == name.lower() for f in a["features"]):
                    continue
                a["features"].append({"fname": name, "fvalue": val, "funit": (r.get("PM_UNIT") or "").strip()})
                if r.get("PM_ECLASSVERSION") and a["reference_feature_system"] == "udf_OBS-1.0":
                    a["reference_feature_system"] = r["PM_ECLASSVERSION"].strip()
                stats["p_merkmale"] += 1

        # 4) OBS-eigene Merkmale (artikel_merkmale → s_merkmale / s_merkmale_werte)
        nrs = list(by_nr)
        for chunk in _chunks(nrs):
            ph = ",".join(["%s"] * len(chunk))
            rows = _q(cur, f"""
                SELECT am.AM_ARTNR, m.M_FNAME, w.MW_FVALUE, am.AM_FORDER
                FROM artikel_merkmale am
                JOIN s_merkmale m ON m.M_ID = am.AM_FNAME_ID
                LEFT JOIN s_merkmale_werte w ON w.SYS_UID = am.AM_FVALUE_ID
                WHERE am.AM_ARTNR IN ({ph}) ORDER BY am.AM_ARTNR, am.AM_FORDER""",
                tuple(chunk), "artikel_merkmale", warn)
            for r in rows:
                a = by_nr.get((r.get("AM_ARTNR") or "").strip())
                name, val = (r.get("M_FNAME") or "").strip(), (r.get("MW_FVALUE") or "").strip()
                if not a or not name or not val:
                    continue
                if name.upper() in ("GTIN", "EAN"):
                    if not a["ean"]:
                        a["ean"] = val
                    continue              # EAN steht im EAN-Feld, nicht als Merkmal
                if _CODE_NAME.match(name):
                    stats["codes_skipped"] = stats.get("codes_skipped", 0) + 1
                    continue
                if any(f["fname"].lower() == name.lower() for f in a["features"]):
                    continue
                a["features"].append({"fname": name, "fvalue": val, "funit": ""})
                stats["artikel_merkmale"] += 1

        # 5) EAN-Tabelle (falls A_EAN leer)
        need = [nr for nr, a in by_nr.items() if not a["ean"]]
        for chunk in _chunks(need):
            ph = ",".join(["%s"] * len(chunk))
            rows = _q(cur, f"SELECT E_NR, E_EAN FROM ean WHERE E_NR IN ({ph})", tuple(chunk), "ean", warn)
            for r in rows:
                a = by_nr.get((r.get("E_NR") or "").strip())
                if a and not a["ean"] and (r.get("E_EAN") or "").strip():
                    a["ean"] = r["E_EAN"].strip()
                    stats["ean"] += 1

        # 6) Artikeltexte (falls noch kein Langtext)
        need = [nr for nr, a in by_nr.items() if not a["description_long"]]
        for chunk in _chunks(need):
            ph = ",".join(["%s"] * len(chunk))
            rows = _q(cur, f"SELECT EA_ARTNR, EA_TEXT, EA_TYP FROM arti_exttext WHERE EA_ARTNR IN ({ph})",
                      tuple(chunk), "arti_exttext", warn)
            for r in rows:
                a = by_nr.get((r.get("EA_ARTNR") or "").strip())
                t = _plain(r.get("EA_TEXT"))
                if a and t and not a["description_long"]:
                    a["description_long"] = t
                    stats["exttext"] += 1

        # 7) Bilder aus p_bilder (normal zuerst)
        for chunk in _chunks(keys):
            ph = ",".join(["%s"] * len(chunk))
            rows = _q(cur, f"""
                SELECT BESTNR, LIEFNR, TYP, PFAD FROM p_bilder
                WHERE BESTNR IN ({ph}) AND TYP IN ('normal', 'detail', 'thumbnail')""",
                tuple(a["obs_bestnr"] for a in chunk), "p_bilder", warn)
            rank = {"normal": 0, "detail": 1, "thumbnail": 2}
            tmp: dict = {}
            for r in rows:
                a = by_best.get((r.get("BESTNR") or "").strip().lower())
                if not a:
                    continue
                if a["obs_liefnr"] and (r.get("LIEFNR") or "").strip() not in ("", a["obs_liefnr"]):
                    continue
                tmp.setdefault(a["obs_bestnr"].lower(), []).append(
                    (rank.get((r.get("TYP") or "").strip(), 9), (r.get("PFAD") or "").strip()))
            for key, lst in tmp.items():
                a = by_best[key]
                seen = set()
                for i, (_rk, pfad) in enumerate(sorted(lst), 1):
                    if not pfad or pfad in seen:
                        continue
                    seen.add(pfad)
                    ext = pfad.rsplit(".", 1)[-1].lower() if "." in pfad else ""
                    mt = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif",
                          "pdf": "application/pdf"}.get(ext, "image/jpeg")
                    a["mimes"].append({"mime_type": mt, "mime_source": pfad, "mime_purpose": "normal",
                                       "mime_desc": "", "mime_alt": "", "mime_order": i})
                    stats["p_bilder"] += 1
        for a in arts.values():
            if not a["description_long"]:
                a["description_long"] = a.get("obs_suchtext") or ""
                if a["description_long"]:
                    stats["suchtext"] = stats.get("suchtext", 0) + 1
            for f in a["features"]:
                f.setdefault("funit", "")
                f.setdefault("forder", 0)
        p(f"  OBS Zusatzdaten: {stats['p_arti']} p_arti, {stats['p_merkmale']} p_merkmale-Features, "
          f"{stats['artikel_merkmale']} OBS-Merkmale, {stats['ean']} EANs, {stats['exttext']} Texte, "
          f"{stats['p_bilder']} Bilder, {stats.get('codes_skipped', 0)} codierte Merkmale übersprungen, "
          f"{stats.get('suchtext', 0)} Langtexte nur aus Suchtext", tag="dim")
    finally:
        con.close()
    return list(arts.values()), stats


# ── Kategorie-Nachschlag (für Artikel ohne Kategorie aus DB oder OBS) ────────

def _resolve_code(code: str, known: set, prefixes: list) -> str:
    """Code mit/ohne Lieferantenpräfix gegen custom_categories prüfen."""
    c = (code or "").strip()
    if not c:
        return ""
    if c.upper() in known:
        return c
    for pre in prefixes:
        if (pre + c).upper() in known:
            return pre + c
    return ""


def lookup_categories(cfg: dict, nrs: list, known_codes: set, progress_cb: Callable = None) -> dict:
    """
    {A_NR: [(code, name)]} – Kategorie je OBS-Artikelnummer:
      1. artikel.A_WGR/A_WGRU → user_catmapping.MP_CATCODE
      2. p_arti.HWGR/WGR + LIEFNR → p_wgr.BMECATWGR (Lieferantenkategorie, mit Präfix
         gegen custom_categories geprüft) bzw. p_wgr.OBSWGR/OBSWGRU → user_catmapping
    """
    p = progress_cb or (lambda m, **kw: None)
    warn = lambda m: p(m, tag="warn")
    if not nrs:
        return {}
    known = {k.upper() for k in known_codes}
    aids = [n for n in nrs if n]
    # Präfixe aus den Lieferanten-Wurzeln (BRG1 → BRG, SOC1 → SOC, NDW1 → NDW …)
    prefixes = sorted({k[:-1] for k in known if k.endswith("1") and k[:-1].isalpha() and 2 <= len(k) - 1 <= 4})
    out: dict = {}
    con = _connect(cfg)
    try:
        cur = con.cursor()
        catmap = load_catmapping(cur, warn)
        info: dict = {}
        for chunk in _chunks(aids):
            ph = ",".join(["%s"] * len(chunk))
            for r in _q(cur, f"SELECT A_BESTNR1, A_NR, A_LIEFER1, A_WGR, A_WGRU FROM artikel "
                            f"WHERE A_NR IN ({ph})", tuple(chunk), "artikel (Kategorie)", warn):
                key = (r.get("A_NR") or "").strip()
                if key and key not in info:
                    info[key] = r
        for key, r in info.items():
            wg = ((r.get("A_WGR") or "").strip(), (r.get("A_WGRU") or "").strip())
            cm = catmap.get(wg) or catmap.get((wg[0], ""))
            if cm and cm[0]:
                out[key] = [(cm[0], cm[1] or cm[0])]
        rest = [k for k in info if k not in out]
        if rest:
            pw: dict = {}
            for r in _q(cur, "SELECT LIEFNR, HWGR, UWGR, OBSWGR, OBSWGRU, BMECATWGR, WGRNAME FROM p_wgr", (),
                        "p_wgr", warn):
                pw[((r.get("LIEFNR") or "").strip(), (r.get("HWGR") or "").strip(), (r.get("UWGR") or "").strip())] = r
            for chunk in _chunks(rest):
                ph = ",".join(["%s"] * len(chunk))
                best2nr = {(info[k].get("A_BESTNR1") or "").strip().lower(): k for k in chunk
                           if (info[k].get("A_BESTNR1") or "").strip()}
                if not best2nr:
                    continue
                ph = ",".join(["%s"] * len(best2nr))
                for r in _q(cur, f"SELECT NR, LIEFNR, HWGR, WGR FROM p_arti WHERE NR IN ({ph})",
                            tuple(info[k]["A_BESTNR1"] for k in best2nr.values()), "p_arti (Kategorie)", warn):
                    key = best2nr.get((r.get("NR") or "").strip().lower())
                    if not key or key in out:
                        continue
                    lief = (r.get("LIEFNR") or "").strip()
                    w = pw.get((lief, (r.get("HWGR") or "").strip(), (r.get("WGR") or "").strip())) \
                        or pw.get((lief, (r.get("HWGR") or "").strip(), ""))
                    if not w:
                        continue
                    code = _resolve_code(w.get("BMECATWGR"), known, prefixes)
                    if code:
                        out[key] = [(code, (w.get("WGRNAME") or code).strip())]
                        continue
                    cm = catmap.get(((w.get("OBSWGR") or "").strip(), (w.get("OBSWGRU") or "").strip()))
                    if cm and cm[0]:
                        out[key] = [(cm[0], cm[1] or cm[0])]
    finally:
        con.close()
    return out
