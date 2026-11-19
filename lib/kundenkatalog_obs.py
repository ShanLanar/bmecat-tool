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


def load_catmapping(cur, warn: Callable) -> dict:
    """{(MP_WGR, MP_UWGR): (MP_CATCODE, MP_BEZ)}"""
    rows = _q(cur, "SELECT MP_WGR, MP_UWGR, MP_CATCODE, MP_BEZ FROM user_catmapping", (), "user_catmapping", warn)
    out = {}
    for r in rows:
        key = ((r.get("MP_WGR") or "").strip(), (r.get("MP_UWGR") or "").strip())
        out[key] = ((r.get("MP_CATCODE") or "").strip(), (r.get("MP_BEZ") or "").strip())
    return out


def fetch_obs_articles(cfg: dict, aids: list, progress_cb: Callable = None) -> tuple:
    """
    aids: Bestellnummern (A_BESTNR1). Returns (articles, stats).
    articles: [dict] im Format von query_by_ids (+ kk_source="obs", kk_path).
    """
    p = progress_cb or (lambda m, **kw: None)
    warn = lambda m: p(m, tag="warn")
    if not aids:
        return [], {}
    con = _connect(cfg)
    arts: dict = {}
    stats = {"artikel": 0, "p_arti": 0, "p_merkmale": 0, "p_bilder": 0, "artikel_merkmale": 0,
             "ean": 0, "exttext": 0, "catmapping": 0, "inaktiv": 0}
    try:
        cur = con.cursor()
        catmap = load_catmapping(cur, warn)

        # 1) Stammdaten
        for chunk in _chunks(aids):
            ph = ",".join(["%s"] * len(chunk))
            rows = _q(cur, f"""
                SELECT A_NR, A_BESTNR1, A_LIEFER1, A_NAME1, A_NAME2, A_EAN, A_HERSTELLERNR,
                       A_HERSTELLERNAME, A_WGR, A_WGRU, A_EINHEIT, A_MENGEINH, A_SUCHTEXT,
                       A_LANGTEXTANSI, A_URLAND, A_AGEWICHT, A_INAKTIV, DELETED, A_MWSTSCHL
                FROM artikel WHERE A_BESTNR1 IN ({ph})""", tuple(chunk), "artikel", warn)
            for r in rows:
                aid = (r.get("A_BESTNR1") or "").strip()
                if not aid or aid.lower() in arts:
                    continue
                if (r.get("DELETED") or "0").strip() == "1":
                    continue
                if (r.get("A_INAKTIV") or "0").strip() == "1":
                    stats["inaktiv"] += 1
                short = " ".join(x for x in ((r.get("A_NAME1") or "").strip(), (r.get("A_NAME2") or "").strip()) if x)
                art = {
                    "id": None, "kk_source": "obs",
                    "product_id": aid, "supplier_pid": aid, "obs_nr": (r.get("A_NR") or "").strip(),
                    "obs_liefnr": (r.get("A_LIEFER1") or "").strip(),
                    "supplier_name": "OBS",
                    "description_short": short,
                    "description_long": _plain(r.get("A_SUCHTEXT")) or "",
                    "ean": (r.get("A_EAN") or "").strip(),
                    "manufacturer_aid": (r.get("A_HERSTELLERNR") or "").strip(),
                    "manufacturer_name": (r.get("A_HERSTELLERNAME") or "").strip(),
                    "delivery_time": "",
                    "order_unit": "C62", "content_unit": "C62", "no_cu_per_ou": "1",
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
                arts[aid.lower()] = art
        stats["artikel"] = len(arts)
        p(f"  OBS artikel: {len(arts)} von {len(aids)} Bestellnummern gefunden "
          f"({stats['inaktiv']} inaktiv, {stats['catmapping']} mit Kategorie-Mapping)")
        if not arts:
            return [], stats

        by_nr = {a["obs_nr"]: a for a in arts.values() if a["obs_nr"]}
        keys = list(arts.values())

        # 2) Lieferantenkatalog-Spiegel p_arti (Langtext, EAN, Hersteller-Nr, Gewicht)
        for chunk in _chunks(keys):
            ph = ",".join(["%s"] * len(chunk))
            rows = _q(cur, f"""
                SELECT NR, LIEFNR, BEZ1, BEZ2, LANGTEXT, EAN, HERSTARTNR, GEWICHT, VERPAMENGE
                FROM p_arti WHERE NR IN ({ph})""", tuple(a["supplier_pid"] for a in chunk), "p_arti", warn)
            for r in rows:
                a = arts.get((r.get("NR") or "").strip().lower())
                if not a:
                    continue
                if a["obs_liefnr"] and (r.get("LIEFNR") or "").strip() not in ("", a["obs_liefnr"]):
                    continue
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
                tuple(a["supplier_pid"] for a in chunk), "p_merkmale", warn)
            for r in rows:
                a = arts.get((r.get("PM_NR") or "").strip().lower())
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
                tuple(a["supplier_pid"] for a in chunk), "p_bilder", warn)
            rank = {"normal": 0, "detail": 1, "thumbnail": 2}
            tmp: dict = {}
            for r in rows:
                a = arts.get((r.get("BESTNR") or "").strip().lower())
                if not a:
                    continue
                if a["obs_liefnr"] and (r.get("LIEFNR") or "").strip() not in ("", a["obs_liefnr"]):
                    continue
                tmp.setdefault(a["supplier_pid"].lower(), []).append(
                    (rank.get((r.get("TYP") or "").strip(), 9), (r.get("PFAD") or "").strip()))
            for key, lst in tmp.items():
                a = arts[key]
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
        for a in keys:
            for f in a["features"]:
                f.setdefault("funit", "")
                f.setdefault("forder", 0)
        p(f"  OBS Zusatzdaten: {stats['p_arti']} p_arti, {stats['p_merkmale']} p_merkmale-Features, "
          f"{stats['artikel_merkmale']} OBS-Merkmale, {stats['ean']} EANs, {stats['exttext']} Texte, "
          f"{stats['p_bilder']} Bilder", tag="dim")
    finally:
        con.close()
    return list(arts.values()), stats
