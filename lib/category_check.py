# lib/category_check.py – Neue Lieferanten-Kategorien erkennen
#
# Liest CATALOG_STRUCTURE/GROUP_ID aus BMEcat-XMLs,
# vergleicht gegen custom_categories.csv und meldet unbekannte Kategorien.
#
# Präfix-Logik (kein Unterstrich):
#   Büroring    → BRG + GROUP_ID
#   Nordwest    → NDW + GROUP_ID
#   Softcarrier → SOC + GROUP_ID

import os
import re
import csv
import logging

log = logging.getLogger(__name__)

_CUSTOM_CAT_FILE = "custom_categories.csv"
_CUSTOM_CAT_ENCODINGS = ("cp1252", "utf-8-sig", "utf-8", "latin-1")

_CAT_STRUCT_PAT  = re.compile(
    r'<CATALOG_STRUCTURE[^>]*>(.*?)</CATALOG_STRUCTURE>',
    re.IGNORECASE | re.DOTALL)
_GROUP_ID_PAT    = re.compile(r'<GROUP_ID>(.*?)</GROUP_ID>',   re.IGNORECASE)
_GROUP_NAME_PAT  = re.compile(r'<GROUP_NAME>(.*?)</GROUP_NAME>', re.IGNORECASE)
_PARENT_ID_PAT   = re.compile(r'<PARENT_ID>(.*?)</PARENT_ID>', re.IGNORECASE)
_ARTICLE_PAT     = re.compile(r'<ARTICLE[\s>]', re.IGNORECASE)


# ── Bekannte Kategorien laden ─────────────────────────────────────────────────

def load_known_categories(base_dir: str) -> set:
    """
    Liest alle category_code-Werte aus custom_categories.csv.
    Ergebnis wird für den aktuellen Lauf gecacht (lib.utils.cache_get/set).
    """
    from lib.utils import cache_get, cache_set
    cache_key = f"known_categories:{base_dir}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    csv_path = os.path.join(base_dir, _CUSTOM_CAT_FILE)
    if not os.path.exists(csv_path):
        log.warning("custom_categories.csv nicht gefunden: %s", csv_path)
        return cache_set(cache_key, set())

    codes = set()
    for enc in _CUSTOM_CAT_ENCODINGS:
        try:
            with open(csv_path, "r", encoding=enc, errors="strict") as f:
                reader = csv.DictReader(f, delimiter=";")
                for row in reader:
                    code = (row.get("category_code") or "").strip()
                    if code:
                        codes.add(code.upper())
            break
        except (UnicodeDecodeError, KeyError):
            continue

    return cache_set(cache_key, codes)


# ── Kategorien aus BMEcat-XML extrahieren ─────────────────────────────────────

def extract_categories_from_xml(xml_path: str, prefix: str) -> list:
    """
    Extrahiert alle CATALOG_STRUCTURE-Einträge aus einer BMEcat-XML.

    Liest nur den Header-Bereich (bis zum ersten <ARTICLE>), da CATALOG_STRUCTURE
    immer vor den Artikeln steht. Effizient auch für 470-MB-Dateien.

    Returns:
        Liste von dicts: [{code, name, parent_id}]
        code = Präfix + GROUP_ID  (z.B. "BRG64640")
    """
    if not os.path.exists(xml_path):
        return []

    pfx = prefix.upper()
    categories = []
    header_parts = []
    header_size = 0
    MAX_HEADER = 20 * 1024 * 1024  # 20 MB — reicht für alle Kategorien

    with open(xml_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            m_art = _ARTICLE_PAT.search(line)
            if m_art:
                # Noch den Teil vor dem ersten <ARTICLE> mitnehmen
                header_parts.append(line[:m_art.start()])
                break
            header_parts.append(line)
            header_size += len(line)
            if header_size > MAX_HEADER:
                break

    header = "".join(header_parts)

    for m in _CAT_STRUCT_PAT.finditer(header):
        block  = m.group(1)
        gid_m  = _GROUP_ID_PAT.search(block)
        if not gid_m:
            continue
        gid    = gid_m.group(1).strip()
        name_m = _GROUP_NAME_PAT.search(block)
        par_m  = _PARENT_ID_PAT.search(block)
        categories.append({
            "code":      pfx + gid,
            "group_id":  gid,
            "name":      name_m.group(1).strip() if name_m else "",
            "parent_id": par_m.group(1).strip()  if par_m  else "",
        })

    return categories


# ── Vergleich und Bericht ─────────────────────────────────────────────────────

def check_new_categories(xml_path: str, prefix: str, base_dir: str,
                          supplier_label: str,
                          progress_cb=None) -> list:
    """
    Vergleicht die Kategorien in xml_path mit custom_categories.csv.
    Gibt Liste neuer (unbekannter) Kategorien zurück.
    """
    p = progress_cb or (lambda m, **kw: None)

    known    = load_known_categories(base_dir)
    cats     = extract_categories_from_xml(xml_path, prefix)

    if not cats:
        p(f"{supplier_label} Kategorien: keine CATALOG_STRUCTURE gefunden in "
          f"{os.path.basename(xml_path)}", tag="dim")
        return []

    new_cats = [c for c in cats if c["code"].upper() not in known]

    p(f"{supplier_label} Kategorien: {len(cats)} gesamt, "
      f"{len(cats) - len(new_cats)} bekannt, "
      f"{len(new_cats)} neu")

    if new_cats:
        p(f"  ⚠ Neue {supplier_label}-Kategorien — bitte in custom_categories.csv "
          f"aufnehmen:", tag="warn")
        for c in sorted(new_cats, key=lambda x: x["code"]):
            parent_str = f" (Parent: {c['parent_id']})" if c["parent_id"] else ""
            p(f"    {c['code']}  →  {c['name']}{parent_str}", tag="warn")

    return new_cats


# ── Mehrere XMLs zusammen prüfen (z.B. Nordwest) ─────────────────────────────

def check_supplier_categories(xml_paths: list, prefix: str, base_dir: str,
                               supplier_label: str, progress_cb=None) -> list:
    """
    Prüft mehrere XMLs (z.B. Nordwest hat 3 Kataloge) zusammen.
    Dedupliziert Kategorien über alle Dateien hinweg.
    """
    p = progress_cb or (lambda m, **kw: None)
    known = load_known_categories(base_dir)

    all_cats = {}
    for xml_path in xml_paths:
        if not os.path.exists(xml_path):
            continue
        for c in extract_categories_from_xml(xml_path, prefix):
            all_cats[c["code"].upper()] = c

    new_cats = [c for code, c in all_cats.items() if code not in known]

    p(f"{supplier_label} Kategorien: {len(all_cats)} gesamt "
      f"(aus {len(xml_paths)} Dateien), "
      f"{len(all_cats) - len(new_cats)} bekannt, "
      f"{len(new_cats)} neu")

    if new_cats:
        p(f"  ⚠ Neue {supplier_label}-Kategorien — bitte in custom_categories.csv "
          f"aufnehmen:", tag="warn")
        for c in sorted(new_cats, key=lambda x: x["code"]):
            parent_str = f" (Parent: {c['parent_id']})" if c["parent_id"] else ""
            p(f"    {c['code']}  →  {c['name']}{parent_str}", tag="warn")

    return new_cats
