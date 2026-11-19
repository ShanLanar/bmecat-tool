# lib/kundenkatalog.py – Kundenkataloge (BMEcat 1.2) aus Preisliste + Artikel-DB
#
# Ein Kundenkatalog ist durch ein PROFIL beschrieben (kundenkataloge/<name>.json):
#   Kopfdaten (CATALOG_ID/-NAME/-VERSION, Lieferant = wir, Käufer), die
#   ERP-Preisliste(n) (PL-Nummer), aus der die Artikelmenge UND der Preis
#   kommen (price_type nrp), Lieferanten-Reihenfolge für die Stammdaten,
#   Baum-Einstellungen und Ausgabeformat.
#
# Erzeugung (generate):
#   1. Preisliste aus dem ERP (lib.unite_price_update.fetch_price_list):
#      {a_bestnr1: price, tax} → Artikelmenge des Katalogs.
#   2. Je Artikelnummer der Artikel aus der Artikel-DB (supplier_pid = a_bestnr1,
#      aktiv); bei mehreren Lieferanten entscheidet die Reihenfolge im Profil,
#      sonst supplier_priority.csv. Nicht gefundene Nummern → Report
#      (Kandidaten für die OBS-Quelle, Stufe 2).
#   3. Kategoriebaum: Zentralshop-Baum aus custom_categories.csv (Reiter
#      "Kategorien"). Die Lieferantenkategorie des Artikels wird über das
#      Ziel-Mapping (product_category_code) in den Zentralshop gehängt; ohne
#      Mapping wird der Lieferanten-Pfad unter die Zentralshop-Wurzel gehängt
#      (Bäume ohne gemeinsame Wurzel → Wurzel des Zentralshops).
#   4. BMEcat 1.2 nach DIRS["export_kundenkataloge"]/<profil>/<CATALOG_ID>_<ts>.xml;
#      jede Erzeugung bleibt als Archiv liegen; Vergleich zum Vorlauf im Log.
#
# Weitere Ausgabeformate (Ariba CIF, Conrad-Excel) sind als Renderer vorgesehen:
# render_* bekommt dieselbe Artikel-/Baumstruktur (siehe RENDERERS).

import csv
import glob
import json
import os
import re
from datetime import datetime
from typing import Callable

from lib.utils import xml_escape as _xml_escape_raw

# Zeichen, die in XML 1.0 nicht erlaubt sind (Steuerzeichen außer Tab/LF/CR):
# kommen aus DB-/OBS-Texten (RTF-Reste, Trennzeichen) und lassen den Import
# beim Kunden mit "kein XML-Dokument … referenced at line …" abbrechen.
_XML_INVALID = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def xml_escape(s) -> str:
    return _xml_escape_raw(_XML_INVALID.sub("", "" if s is None else str(s)))

PROFILE_DIRNAME = "kundenkataloge"
EXPORT_DIRNAME = "export_kundenkataloge"

DEFAULT_PROFILE = {
    "name":             "",            # Profilname = Dateiname
    "catalog_id":       "",
    "catalog_name":     "",
    "catalog_version":  "1.0",
    "language":         "deu",
    "currency":         "EUR",
    "mime_root":        "",
    "price_lists":      "",            # PL-Nummern, Komma-getrennt (niedrigster Preis gewinnt)
    "price_type":       "nrp",
    "price_mode":       "netto",       # netto | brutto (Preis in der XML)
    "suppliers":        "",            # Lieferanten-Reihenfolge (Namen, Komma); leer = supplier_priority.csv
    "sources":          "db,obs",      # Datenquellen in Reihenfolge: db (Artikel-DB), obs (ERP, nur was die DB nicht hat)
    "aid_mode":         "native",      # native (supplier_pid) | product_id (mit Präfix)
    "root_code":        "1",           # Zentralshop-Wurzel in custom_categories.csv
    "group_system_id":  "ZENTRALSHOP",
    "group_system_name": "Zentralshop",
    "include_features": True,
    "include_mimes":    True,
    "include_keywords": True,
    "include_udx":      False,
    "format":           "bmecat12",
    "postprocess":      True,          # normales Shop-Postprocessing (lib/db_postprocess) auf DB-Artikel
    "supplier": {"id_type": "iln", "id": "", "name": "", "name2": "", "contact": "",
                 "street": "", "zip": "", "city": "", "country": "DE", "phone": "",
                 "fax": "", "email": "", "url": ""},
    "buyer":    {"name": "", "name2": "", "contact": "", "street": "", "zip": "",
                 "city": "", "country": "DE"},
    "notes":            "",
    "last_run":         "",
    "last_file":        "",
}


# ── Profile ──────────────────────────────────────────────────────────────────

def profile_dir(base_dir: str) -> str:
    d = os.path.join(base_dir, PROFILE_DIRNAME)
    os.makedirs(d, exist_ok=True)
    return d


def _safe_name(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", (name or "").strip()) or "profil"


def list_profiles(base_dir: str) -> list:
    out = []
    for path in sorted(glob.glob(os.path.join(profile_dir(base_dir), "*.json"))):
        try:
            out.append(load_profile(path))
        except Exception:
            continue
    return out


def load_profile(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    prof = json.loads(json.dumps(DEFAULT_PROFILE))
    for k, v in data.items():
        if isinstance(v, dict) and isinstance(prof.get(k), dict):
            prof[k].update(v)
        else:
            prof[k] = v
    prof.setdefault("name", os.path.splitext(os.path.basename(path))[0])
    prof["_path"] = path
    return prof


def save_profile(base_dir: str, prof: dict) -> str:
    name = _safe_name(prof.get("name"))
    path = os.path.join(profile_dir(base_dir), f"{name}.json")
    data = {k: v for k, v in prof.items() if not k.startswith("_")}
    data["name"] = name
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    old = prof.get("_path")
    if old and os.path.abspath(old) != os.path.abspath(path) and os.path.exists(old):
        os.remove(old)
    prof["_path"] = path
    return path


def delete_profile(prof: dict):
    p = prof.get("_path")
    if p and os.path.exists(p):
        os.remove(p)


def export_dir(prof: dict) -> str:
    import config as _cfg
    base = _cfg.DIRS.get("export_kundenkataloge") or os.path.join(_cfg.BASE_DIR, EXPORT_DIRNAME)
    d = os.path.join(base, _safe_name(prof.get("name")))
    os.makedirs(d, exist_ok=True)
    return d


def archive_files(prof: dict) -> list:
    """[(pfad, mtime)] der bisher erzeugten Kataloge, neueste zuerst."""
    files = glob.glob(os.path.join(export_dir(prof), "*.*"))
    files = [f for f in files if not f.endswith((".tmp", ".csv"))]
    return sorted(((f, os.path.getmtime(f)) for f in files), key=lambda x: -x[1])


# ── Preisliste ───────────────────────────────────────────────────────────────

def _parse_lists(s: str) -> list:
    return [int(x) for x in re.split(r"[,\s;]+", str(s or "")) if x.strip().isdigit()]


def load_prices(prof: dict, p: Callable) -> dict:
    """{aid_lower: {"aid": original, "price": float, "tax": float}} aus dem ERP."""
    import config as _cfg
    nrs = _parse_lists(prof.get("price_lists"))
    if not nrs:
        raise ValueError("Keine Preislisten-Nummer im Profil.")
    cfg = _cfg.CONNECTIONS.get("erp_mysql", {})
    if not cfg.get("host") or not cfg.get("user") or not cfg.get("database"):
        raise ValueError("ERP-Zugang (CONNECTIONS['erp_mysql']) ist nicht konfiguriert.")
    from lib.unite_price_update import fetch_price_list
    raw = fetch_price_list(cfg, nrs, progress_cb=p)
    out = {}
    brutto = (prof.get("price_mode") or "netto").lower() == "brutto"
    for aid, d in raw.items():
        try:
            amount = float(d["price_amount"])
            tax = float(d.get("tax") or 0)
        except (TypeError, ValueError):
            continue
        if amount <= 0:
            continue
        if brutto:
            amount = amount * (1 + tax)
        out[aid.strip().lower()] = {"aid": aid.strip(), "price": round(amount, 2), "tax": tax}
    p(f"Preisliste {', '.join(map(str, nrs))}: {len(out)} Artikel mit Preis > 0")
    return out


# ── Artikel aus der DB ───────────────────────────────────────────────────────

def _supplier_order(prof: dict, base_dir: str) -> dict:
    """{supplier_name_lower: rang} – kleiner = bevorzugt."""
    names = [s.strip() for s in (prof.get("suppliers") or "").split(",") if s.strip()]
    if names:
        return {n.lower(): i for i, n in enumerate(names)}
    from lib.db_postprocess import load_supplier_priority
    return {k.lower(): v for k, v in load_supplier_priority(base_dir).items()}


def resolve_articles(db_path: str, base_dir: str, prof: dict, prices: dict, p: Callable) -> tuple:
    """
    Ordnet jeder Preislisten-Artikelnummer einen DB-Artikel zu.
    Returns (articles [dict mit 'kk_price'], missing [aid]).
    """
    from lib.article_db import open_db, query_by_ids
    order = _supplier_order(prof, base_dir)
    only = {n.strip().lower() for n in (prof.get("suppliers") or "").split(",") if n.strip()}
    con = open_db(db_path)
    try:
        rows = con.execute("""
            SELECT a.id, a.supplier_pid, a.product_id, s.supplier_name
            FROM articles a JOIN suppliers s ON s.id = a.supplier_id
            WHERE a.active = 1 AND a.supplier_pid <> ''
        """).fetchall()
        by_pid: dict = {}
        for r in rows:
            sup = (r["supplier_name"] or "").lower()
            if only and sup not in only:
                continue
            by_pid.setdefault((r["supplier_pid"] or "").strip().lower(), []).append(
                (order.get(sup, 999), r["id"], r["product_id"]))
        chosen, missing = [], []
        for key, pr in prices.items():
            cands = by_pid.get(key)
            if not cands:
                missing.append(pr["aid"])
                continue
            cands.sort()
            chosen.append((cands[0][1], pr))
        p(f"Artikel-DB: {len(chosen)} von {len(prices)} Preislisten-Artikeln gefunden, "
          f"{len(missing)} nicht in der DB")
        arts = []
        ids = [c[0] for c in chosen]
        price_by_id = {c[0]: c[1] for c in chosen}
        for i in range(0, len(ids), 500):
            for art in query_by_ids(con, ids[i:i + 500]):
                art["kk_price"] = price_by_id[art["id"]]
                arts.append(art)
            p(f"  … {min(i + 500, len(ids))}/{len(ids)} Artikel geladen", tag="dim")
        # Katalogpfad je Artikel (DB-Baum, Export-Codes mit Präfix)
        from lib.article_db import get_catalog_path
        from lib.db_exporter import _supplier_prefix, _add_prefix_if_missing
        path_cache = {}
        for art in arts:
            nid = art.get("_catalog_node_id")
            if not nid:
                art["kk_path"] = []
                continue
            if nid not in path_cache:
                pre = _supplier_prefix(art)
                nodes_ = get_catalog_path(con, nid)
                path_cache[nid] = ([(_add_prefix_if_missing(n["group_id"], pre), n["name"] or n["group_id"])
                                    for n in nodes_],
                                   bool(nodes_) and (nodes_[0].get("parent_group_id") or "") in ("", "0"))
            art["kk_path"], art["kk_path_has_root"] = path_cache[nid]
    finally:
        con.close()
    return arts, missing


# ── Kategoriebaum ────────────────────────────────────────────────────────────

class TreeBuilder:
    """
    Baut den Katalogbaum des Kundenkatalogs aus dem Zentralshop (custom_categories.csv)
    und hängt nicht gemappte Lieferanten-Pfade unter die Zentralshop-Wurzel.
    """

    def __init__(self, base_dir: str, root_code: str, p: Callable):
        from lib import category_tree as ct
        rows, _f, _e = ct.load_rows(base_dir)
        self.nodes, self.roots = ct.build_tree(rows)
        self.ct = ct
        self.root_code = (root_code or "1").strip()
        self.root = self.nodes.get(self.root_code.upper())
        if not self.root:
            p(f"Zentralshop-Wurzel '{self.root_code}' nicht in custom_categories.csv – "
              f"Baum wird nur aus den Lieferantenpfaden gebildet.", tag="warn")
        self.used: dict = {}        # code → (name, parent_code)
        self.stats = {"mapped": 0, "zentralshop": 0, "hung": 0, "db_path": 0, "none": 0}

    def _resolve_target(self, code: str) -> str:
        """Ziel-Kette (product_category_code) bis zum Ende verfolgen."""
        k, seen = code.upper(), set()
        while k in self.nodes and self.nodes[k].target and k not in seen:
            seen.add(k)
            t = self.nodes[k].target.upper()
            if t not in self.nodes or t == k:
                break
            k = t
        return k

    def _in_root(self, key: str) -> bool:
        r = self.ct.root_of(self.nodes, key)
        return bool(self.root and r is self.root)

    def _add_chain(self, key: str):
        """Knoten + alle Vorfahren (im custom-Baum) in used aufnehmen."""
        k, seen = key, set()
        while k in self.nodes and k not in seen:
            seen.add(k)
            n = self.nodes[k]
            pk = n.parent.upper()
            if self.root and n is self.root:
                self.used[n.code] = (n.name, "")
                return
            if not pk or pk not in self.nodes:
                # fremde Wurzel (BRG1, SOC1, NDW1 …): wird durch die Zentralwurzel
                # ersetzt – der Knoten selbst erscheint nicht im Katalog
                if self.root:
                    self.used[self.root.code] = (self.root.name, "")
                if n.code in self.used:
                    del self.used[n.code]
                return
            parent_node = self.nodes[pk]
            parent_is_foreign_root = (not parent_node.parent.upper()
                                      or parent_node.parent.upper() not in self.nodes) \
                and not (self.root and parent_node is self.root)
            self.used[n.code] = (n.name, self.root.code if (parent_is_foreign_root and self.root) else parent_node.code)
            k = pk

    def group_for(self, art: dict) -> str:
        """GROUP_ID für den Artikel bestimmen und Baum ergänzen."""
        path = art.get("kk_path") or []
        if not path:
            self.stats["none"] += 1
            return ""
        leaf_code = path[-1][0]
        key = leaf_code.upper()
        if key in self.nodes:
            target = self._resolve_target(key)
            if target != key:
                self.stats["mapped"] += 1
                self._add_chain(target)
                return self.nodes[target].code
            if self._in_root(key):
                self.stats["zentralshop"] += 1
            else:
                self.stats["hung"] += 1
            self._add_chain(key)
            return self.nodes[key].code
        # Nicht in custom_categories: DB-Pfad unter Zentralshop-Wurzel hängen
        self.stats["db_path"] += 1
        parent = self.root.code if self.root else ""
        if self.root:
            self.used[self.root.code] = (self.root.name, "")
        if len(path) > 1 and art.get("kk_path_has_root", True):
            path = path[1:]          # Lieferanten-Wurzel durch Zentralwurzel ersetzen
        for code, name in path:
            if code not in self.used:
                self.used[code] = (name, parent)
            parent = code
        return path[-1][0]

    def structure_xml(self, group_system_id: str, group_system_name: str) -> str:
        if not self.used:
            return ""
        children = {}
        for code, (_n, parent) in self.used.items():
            children.setdefault(parent, []).append(code)
        lines = ["    <CATALOG_GROUP_SYSTEM>",
                 f"      <GROUP_SYSTEM_ID>{xml_escape(group_system_id)}</GROUP_SYSTEM_ID>",
                 f"      <GROUP_SYSTEM_NAME>{xml_escape(group_system_name)}</GROUP_SYSTEM_NAME>"]
        order = []
        def _walk(code):
            order.append(code)
            for ch in sorted(children.get(code, []), key=lambda c: self.used[c][0].lower()):
                _walk(ch)
        for root in [c for c, (_n, par) in self.used.items() if not par]:
            _walk(root)
        for code in order:
            name, parent = self.used[code]
            typ = "root" if not parent else ("leaf" if not children.get(code) else "node")
            lines += [f'      <CATALOG_STRUCTURE type="{typ}">',
                      f"        <GROUP_ID>{xml_escape(code)}</GROUP_ID>",
                      f"        <GROUP_NAME>{xml_escape(name)}</GROUP_NAME>",
                      f"        <PARENT_ID>{xml_escape(parent) if parent else '0'}</PARENT_ID>",
                      "      </CATALOG_STRUCTURE>"]
        lines.append("    </CATALOG_GROUP_SYSTEM>")
        return "\n".join(lines) + "\n"


# ── BMEcat 1.2 ───────────────────────────────────────────────────────────────

def _el(tag: str, val, ind: int) -> str:
    if val is None or str(val) == "":
        return ""
    return f"{' ' * ind}<{tag}>{xml_escape(str(val))}</{tag}>\n"


def _address(kind: str, d: dict, ind: int) -> str:
    sp = " " * ind
    out = f'{sp}<ADDRESS type="{kind}">\n'
    for tag, key in (("NAME", "name"), ("NAME2", "name2"), ("CONTACT", "contact"), ("STREET", "street"),
                     ("ZIP", "zip"), ("CITY", "city"), ("STATE", "state"), ("COUNTRY", "country"),
                     ("PHONE", "phone"), ("FAX", "fax"), ("EMAIL", "email"), ("URL", "url")):
        out += _el(tag, d.get(key), ind + 2)
    return out + f"{sp}</ADDRESS>\n"


def header_xml(prof: dict, now: datetime) -> str:
    sup, buy = prof.get("supplier") or {}, prof.get("buyer") or {}
    out = ["<?xml version='1.0' encoding='UTF-8'?>",
           '<!DOCTYPE BMECAT SYSTEM "bmecat_new_catalog_1_2.dtd">',
           '<BMECAT version="1.2">', "  <HEADER>",
           "    <GENERATOR_INFO>BMEcat-Tool Kundenkatalog</GENERATOR_INFO>", "    <CATALOG>",
           _el("LANGUAGE", prof.get("language") or "deu", 6).rstrip("\n"),
           _el("CATALOG_ID", prof.get("catalog_id"), 6).rstrip("\n"),
           _el("CATALOG_VERSION", prof.get("catalog_version") or "1.0", 6).rstrip("\n"),
           _el("CATALOG_NAME", prof.get("catalog_name") or prof.get("name"), 6).rstrip("\n"),
           '      <DATETIME type="generation_date">',
           f"        <DATE>{now:%Y-%m-%d}</DATE>", f"        <TIME>{now:%H:%M:%S}</TIME>",
           "      </DATETIME>",
           _el("CURRENCY", prof.get("currency") or "EUR", 6).rstrip("\n")]
    if prof.get("mime_root"):
        out.append(_el("MIME_ROOT", prof["mime_root"], 6).rstrip("\n"))
    out = [l for l in out if l]
    out.append("    </CATALOG>")
    if buy.get("name"):
        out.append("    <BUYER>")
        out.append(_el("BUYER_NAME", buy.get("name"), 6).rstrip("\n"))
        out.append(_address("buyer", buy, 6).rstrip("\n"))
        out.append("    </BUYER>")
    out.append("    <SUPPLIER>")
    if sup.get("id"):
        out.append(f'      <SUPPLIER_ID type="{xml_escape(sup.get("id_type") or "iln")}">'
                   f'{xml_escape(sup["id"])}</SUPPLIER_ID>')
    out.append(_el("SUPPLIER_NAME", sup.get("name") or "", 6).rstrip("\n") or "      <SUPPLIER_NAME></SUPPLIER_NAME>")
    out.append(_address("supplier", sup, 6).rstrip("\n"))
    out.append("    </SUPPLIER>")
    out.append("  </HEADER>")
    out.append("  <T_NEW_CATALOG>")
    return "\n".join(out) + "\n"


def _aid(art: dict, prof: dict) -> str:
    return art.get("product_id", "") if prof.get("aid_mode") == "product_id" else (art.get("supplier_pid") or art.get("product_id", ""))


def article_xml(art: dict, prof: dict) -> str:
    aid = _aid(art, prof)
    pr = art["kk_price"]
    L = ["    <ARTICLE>", f"      <SUPPLIER_AID>{xml_escape(aid)}</SUPPLIER_AID>", "      <ARTICLE_DETAILS>"]
    L.append(_el("DESCRIPTION_SHORT", art.get("description_short"), 8).rstrip("\n"))
    L.append(_el("DESCRIPTION_LONG", art.get("description_long"), 8).rstrip("\n"))
    L.append(_el("EAN", art.get("ean"), 8).rstrip("\n"))
    L.append(_el("MANUFACTURER_AID", art.get("manufacturer_aid"), 8).rstrip("\n"))
    L.append(_el("MANUFACTURER_NAME", art.get("manufacturer_name"), 8).rstrip("\n"))
    L.append(_el("DELIVERY_TIME", art.get("delivery_time"), 8).rstrip("\n"))
    if prof.get("include_keywords", True):
        for kw in art.get("keywords") or []:
            L.append(_el("KEYWORD", kw, 8).rstrip("\n"))
    L.append("      </ARTICLE_DETAILS>")
    feats = art.get("features") or [] if prof.get("include_features", True) else []
    if feats:
        L.append("      <ARTICLE_FEATURES>")
        L.append(_el("REFERENCE_FEATURE_SYSTEM_NAME", art.get("reference_feature_system") or "udf_ABE-1.0", 8).rstrip("\n"))
        L.append(_el("REFERENCE_FEATURE_GROUP_ID", art.get("reference_feature_group_id"), 8).rstrip("\n"))
        for f in feats:
            if not (f.get("fname") or "").strip():
                continue
            L.append("        <FEATURE>")
            L.append(_el("FNAME", f.get("fname"), 10).rstrip("\n"))
            L.append(_el("FVALUE", f.get("fvalue") or "", 10).rstrip("\n") or "          <FVALUE></FVALUE>")
            L.append(_el("FUNIT", f.get("funit"), 10).rstrip("\n"))
            L.append("        </FEATURE>")
        L.append("      </ARTICLE_FEATURES>")
    L.append("      <ARTICLE_ORDER_DETAILS>")
    L.append(_el("ORDER_UNIT", art.get("order_unit") or "C62", 8).rstrip("\n"))
    L.append(_el("CONTENT_UNIT", art.get("content_unit") or "", 8).rstrip("\n"))
    L.append(_el("NO_CU_PER_OU", art.get("no_cu_per_ou") or "1", 8).rstrip("\n"))
    L.append(_el("PRICE_QUANTITY", art.get("price_quantity") or "1", 8).rstrip("\n"))
    L.append(_el("QUANTITY_MIN", art.get("quantity_min") or "1", 8).rstrip("\n"))
    L.append(_el("QUANTITY_INTERVAL", art.get("quantity_interval") or "1", 8).rstrip("\n"))
    L.append("      </ARTICLE_ORDER_DETAILS>")
    L.append("      <ARTICLE_PRICE_DETAILS>")
    L.append(f'        <ARTICLE_PRICE price_type="{xml_escape(prof.get("price_type") or "nrp")}">')
    L.append(f"          <PRICE_AMOUNT>{pr['price']:.2f}</PRICE_AMOUNT>")
    L.append(f"          <PRICE_CURRENCY>{xml_escape(prof.get('currency') or 'EUR')}</PRICE_CURRENCY>")
    L.append(f"          <TAX>{pr['tax']:.2f}</TAX>")
    L.append("          <LOWER_BOUND>1</LOWER_BOUND>")
    L.append("        </ARTICLE_PRICE>")
    L.append("      </ARTICLE_PRICE_DETAILS>")
    mimes = art.get("mimes") or [] if prof.get("include_mimes", True) else []
    if mimes:
        L.append("      <MIME_INFO>")
        for m in mimes:
            if not (m.get("mime_source") or "").strip():
                continue
            L.append("        <MIME>")
            L.append(_el("MIME_TYPE", m.get("mime_type"), 10).rstrip("\n"))
            L.append(_el("MIME_SOURCE", m.get("mime_source"), 10).rstrip("\n"))
            L.append(_el("MIME_DESCR", m.get("mime_desc"), 10).rstrip("\n"))
            L.append(_el("MIME_ALT", m.get("mime_alt"), 10).rstrip("\n"))
            L.append(_el("MIME_PURPOSE", m.get("mime_purpose"), 10).rstrip("\n"))
            L.append(_el("MIME_ORDER", m.get("mime_order"), 10).rstrip("\n"))
            L.append("        </MIME>")
        L.append("      </MIME_INFO>")
    if prof.get("include_udx") and art.get("udx"):
        L.append("      <USER_DEFINED_EXTENSIONS>")
        for u in art["udx"]:
            key = re.sub(r"[^A-Za-z0-9_.]", "_", u.get("key") or "")
            if key:
                L.append(f"        <UDX.{key}>{xml_escape(u.get('value') or '')}</UDX.{key}>")
        L.append("      </USER_DEFINED_EXTENSIONS>")
    L.append("    </ARTICLE>")
    return "\n".join(l for l in L if l) + "\n"


def render_bmecat12(prof: dict, arts: list, tree: TreeBuilder, out_path: str, p: Callable) -> dict:
    now = datetime.now()
    maps = []
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(header_xml(prof, now))
        # Baum zuerst bestimmen (Artikel-Zuordnung), dann schreiben
        for art in arts:
            art["kk_group"] = tree.group_for(art)
        f.write(tree.structure_xml(prof.get("group_system_id") or "ZENTRALSHOP",
                                   prof.get("group_system_name") or "Zentralshop"))
        for i, art in enumerate(arts, 1):
            f.write(article_xml(art, prof))
            if art.get("kk_group"):
                maps.append((_aid(art, prof), art["kk_group"]))
            if i % 2000 == 0:
                p(f"  … {i}/{len(arts)} Artikel geschrieben", tag="dim")
        for aid, grp in maps:
            f.write("    <ARTICLE_TO_CATALOGGROUP_MAP>\n"
                    f"      <ART_ID>{xml_escape(aid)}</ART_ID>\n"
                    f"      <CATALOG_GROUP_ID>{xml_escape(grp)}</CATALOG_GROUP_ID>\n"
                    "    </ARTICLE_TO_CATALOGGROUP_MAP>\n")
        f.write("  </T_NEW_CATALOG>\n</BMECAT>\n")
    os.replace(tmp, out_path)
    return {"articles": len(arts), "groups": len(tree.used), "mapped": len(maps), "tree": dict(tree.stats)}


RENDERERS = {
    "bmecat12": ("BMEcat 1.2 (XML)", ".xml", render_bmecat12),
}


# ── Archiv-Vergleich ─────────────────────────────────────────────────────────

_AID_RE = re.compile(r"<SUPPLIER_AID>(.*?)</SUPPLIER_AID>")
_PRICE_RE = re.compile(r"<PRICE_AMOUNT>(.*?)</PRICE_AMOUNT>")


def _snapshot(path: str) -> dict:
    """{aid: erster Preis} aus einer erzeugten BMEcat-Datei."""
    out = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            aid = None
            for line in f:
                m = _AID_RE.search(line)
                if m:
                    aid = m.group(1)
                    out.setdefault(aid, None)
                    continue
                m = _PRICE_RE.search(line)
                if m and aid and out.get(aid) is None:
                    out[aid] = m.group(1)
    except Exception:
        pass
    return out


def compare_with_previous(prof: dict, new_path: str) -> dict:
    files = [f for f, _ in archive_files(prof) if os.path.abspath(f) != os.path.abspath(new_path)
             and f.endswith(".xml")]
    if not files:
        return {}
    prev = files[0]
    a, b = _snapshot(prev), _snapshot(new_path)
    return {"previous": prev,
            "added": sorted(set(b) - set(a)), "removed": sorted(set(a) - set(b)),
            "price_changed": sorted(k for k in set(a) & set(b) if a[k] != b[k])}


# ── Hauptfunktion ────────────────────────────────────────────────────────────

def generate(prof: dict, progress_cb: Callable = None, file_progress_cb: Callable = None) -> dict:
    import config as _cfg
    p = progress_cb or (lambda m, **kw: None)
    fmt = prof.get("format") or "bmecat12"
    if fmt not in RENDERERS:
        raise ValueError(f"Unbekanntes Format '{fmt}' – verfügbar: {', '.join(RENDERERS)}")
    label, ext, renderer = RENDERERS[fmt]
    p(f"Kundenkatalog '{prof.get('name')}' ({label}) …")

    prices = load_prices(prof, p)
    sources = [s.strip().lower() for s in (prof.get("sources") or "db").split(",") if s.strip()]
    arts, missing = [], list(pr["aid"] for pr in prices.values())
    if "db" in sources:
        arts, missing = resolve_articles(_cfg.DB_PATH, _cfg.BASE_DIR, prof, prices, p)
        for a in arts:
            a["kk_source"] = "db"
    obs_stats = {}
    if "obs" in sources and missing:
        p(f"OBS-Quelle: {len(missing)} Artikel aus dem ERP laden …")
        try:
            from lib.kundenkatalog_obs import fetch_obs_articles
            obs_arts, obs_stats = fetch_obs_articles(_cfg.CONNECTIONS.get("erp_mysql", {}), missing, progress_cb=p)
        except Exception as exc:
            p(f"OBS-Quelle fehlgeschlagen: {exc}", tag="warn")
            obs_arts = []
        found = {a["supplier_pid"].lower() for a in obs_arts}
        for a in obs_arts:
            a["kk_price"] = prices[a["supplier_pid"].lower()]
        arts.extend(obs_arts)
        missing = [m for m in missing if m.lower() not in found]
        p(f"OBS-Quelle: {len(obs_arts)} Artikel übernommen, {len(missing)} bleiben ohne Daten")
    # Normales Shop-Postprocessing für DB-Artikel (Blacklist, Offline-Liste,
    # Zusatz-Features, Maße, Marken, FNAME-Blacklist, Medienregeln, Hook) –
    # Preis kommt aus der Preisliste, Preisregeln/SOC-Preispflicht greifen nicht.
    if prof.get("postprocess", True) and any(a.get("kk_source") == "db" for a in arts):
        from lib.db_postprocess import PostProcessor
        pp = PostProcessor(_cfg.BASE_DIR)
        kept, dropped_bl, dropped_off = [], 0, 0
        for a in arts:
            if a.get("kk_source") != "db":
                kept.append(a)
                continue
            a["_price_rule_applied"] = True
            a.setdefault("online", 1)
            res = pp.process(a)
            if res is None:
                dropped_bl += 1
                continue
            if not res.get("online", 1):
                dropped_off += 1
                continue
            for k in ("kk_price", "kk_path", "kk_path_has_root", "kk_source"):
                res[k] = a.get(k)
            if res.get("catalog_sub_group_id") and res.get("catalog_sub_group_id") != a.get("catalog_sub_group_id"):
                res["kk_path"] = [(res["catalog_sub_group_id"], res["catalog_sub_group_id"])]
                res["kk_path_has_root"] = False
            kept.append(res)
        p(f"Postprocessing: {len(kept)} Artikel, {dropped_bl} per Blacklist/Hook entfernt, "
          f"{dropped_off} per Offline-Liste entfernt")
        arts = kept
    arts.sort(key=lambda a: _aid(a, prof))
    tree = TreeBuilder(_cfg.BASE_DIR, prof.get("root_code"), p)

    # Artikel ohne Kategorie: Nachschlag im OBS (artikel.A_WGR/A_WGRU → user_catmapping,
    # p_arti → p_wgr → BMECATWGR/OBS-Warengruppe)
    no_path = [a for a in arts if not a.get("kk_path")]
    if no_path and "obs" in sources:
        try:
            from lib.kundenkatalog_obs import lookup_categories
            found_paths = lookup_categories(_cfg.CONNECTIONS.get("erp_mysql", {}),
                                            [a["supplier_pid"] for a in no_path],
                                            set(tree.nodes), progress_cb=p)
            n_ok = 0
            for a in no_path:
                pth = found_paths.get((a.get("supplier_pid") or "").lower())
                if pth:
                    a["kk_path"], a["kk_path_has_root"] = pth, False
                    n_ok += 1
            p(f"Kategorie-Nachschlag im OBS: {n_ok} von {len(no_path)} Artikeln zugeordnet")
        except Exception as exc:
            p(f"Kategorie-Nachschlag im OBS übersprungen: {exc}", tag="warn")

    out_dir = export_dir(prof)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    cid = _safe_name(prof.get("catalog_id") or prof.get("name"))
    out_path = os.path.join(out_dir, f"{cid}_{ts}{ext}")
    stats = renderer(prof, arts, tree, out_path, p)
    ts_ = tree.stats
    p(f"Baum: {stats['groups']} Gruppen – {ts_['mapped']} Artikel per Mapping im Zentralshop, "
      f"{ts_['zentralshop']} direkt im Zentralshop, {ts_['hung']} über Lieferantenbaum unter der Wurzel, "
      f"{ts_['db_path']} aus DB-Pfad, {ts_['none']} ohne Kategorie", tag="dim")

    if missing:
        mpath = os.path.join(out_dir, f"{cid}_{ts}_fehlend.csv")
        with open(mpath, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["a_bestnr1", "preis"])
            for aid in missing:
                w.writerow([aid, prices[aid.lower()]["price"]])
        p(f"{len(missing)} Preislisten-Artikel weder in der Artikel-DB noch im OBS gefunden → "
          f"{os.path.basename(mpath)}", tag="warn")

    no_cat = [a for a in arts if not a.get("kk_group")]
    if no_cat:
        npath = os.path.join(out_dir, f"{cid}_{ts}_ohne_kategorie.csv")
        with open(npath, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["supplier_aid", "quelle", "bezeichnung", "obs_wgr", "obs_wgru", "db_lieferant"])
            for a in no_cat:
                w.writerow([_aid(a, prof), a.get("kk_source", ""), a.get("description_short", ""),
                            a.get("obs_wgr", ""), a.get("obs_wgru", ""),
                            a.get("supplier_name", "") if a.get("kk_source") == "db" else ""])
        p(f"{len(no_cat)} Artikel ohne Kategorie → {os.path.basename(npath)} "
          f"(OBS: Warengruppe in user_catmapping ergänzen)", tag="warn")

    diff = compare_with_previous(prof, out_path)
    if diff:
        p(f"Vergleich mit {os.path.basename(diff['previous'])}: {len(diff['added'])} neu, "
          f"{len(diff['removed'])} entfallen, {len(diff['price_changed'])} Preisänderungen")
    size = os.path.getsize(out_path) / 1024 / 1024
    p(f"Kundenkatalog geschrieben: {out_path} ({stats['articles']} Artikel, {size:.1f} MB)", tag="ok")

    prof["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    prof["last_file"] = out_path
    try:
        save_profile(_cfg.BASE_DIR, prof)
    except Exception:
        pass
    stats["obs"] = sum(1 for a in arts if a.get("kk_source") == "obs")
    stats["obs_stats"] = obs_stats
    return {"file": out_path, "missing": len(missing), "diff": diff, **stats}
