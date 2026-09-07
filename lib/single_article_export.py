# lib/single_article_export.py – Einzelartikel aus der PIM-DB in eine
# bestehende BMEcat-1.2-Katalog-XML exportieren.
#
# Anders als lib/db_exporter.py (VENDOSYS_CAT-Delta-Export für den PIM-
# Downstream-Import) baut dieses Modul einen eigenständigen <ARTICLE>-Block
# im Standard-BMEcat-1.2-Format (SUPPLIER_AID als direktes Kind von ARTICLE,
# wie in bueroring_merged.xml / soft-carrier_merge.xml) und fügt ihn
# chirurgisch in eine vorhandene Katalog-Datei ein – analog zum Preis-Patch
# in lib/unite_price_update.py: bestehenden Block mit gleicher SUPPLIER_AID
# ersetzen, sonst neuen Block anhängen. Rest der Datei bleibt unangetastet.

import os
import re
import shutil
from xml.sax.saxutils import escape as xml_escape

from lib.article_db import get_catalog_path, get_article_prices, query_by_ids
from lib.db_exporter import (
    _supplier_prefix, _add_prefix, _add_prefix_if_missing, _extract_filename,
)


def load_full_article(con, article_id: int) -> dict | None:
    """
    Lädt einen Artikel komplett (Details, Features, Mimes, Keywords,
    Referenzen, UDX, alle Preisstufen) für render_article_block().
    """
    rows = query_by_ids(con, [article_id])
    if not rows:
        return None
    art = rows[0]
    art["prices"] = get_article_prices(con, article_id)
    return art

_ARTICLE_RE = re.compile(r"<ARTICLE\b.*?</ARTICLE>", re.DOTALL)
_AID_RE     = re.compile(r"<SUPPLIER_AID>(.*?)</SUPPLIER_AID>", re.DOTALL)
_MAP_RE     = re.compile(r"<ARTICLE_TO_CATALOGGROUP_MAP\b.*?</ARTICLE_TO_CATALOGGROUP_MAP>",
                         re.DOTALL)
_ART_ID_RE  = re.compile(r"<ART_ID>(.*?)</ART_ID>", re.DOTALL)


def _cdata(text) -> str:
    if text is None:
        return ""
    text = str(text)
    if any(c in text for c in "<>&\"'"):
        return f"<![CDATA[{text}]]>"
    return text


def render_article_block(art: dict, con=None, prefix_map: dict = None) -> tuple[str, str | None]:
    """
    Baut aus einem vollständig geladenen Artikel-Dict (wie von
    lib.article_db.query_by_ids() geliefert – inkl. features/mimes/keywords/
    references/udx) einen eigenständigen <ARTICLE>...</ARTICLE>-Block plus
    optional einen <ARTICLE_TO_CATALOGGROUP_MAP>-Block.

    Gibt (article_xml, catalog_map_xml_or_None) zurück.
    """
    pid     = art.get("product_id", "")
    sup     = art.get("supplier_name", "")
    prefix  = _supplier_prefix(art, prefix_map)
    aid     = pid  # SUPPLIER_AID = PRODUCT_ID (eindeutig über alle Lieferanten hinweg)

    lines = [
        f'<ARTICLE mode="new">\n',
        f'  <SUPPLIER_AID>{xml_escape(aid)}</SUPPLIER_AID>\n',
        '  <ARTICLE_DETAILS>\n',
        f'    <PRODUCT_ID>{_cdata(pid)}</PRODUCT_ID>\n',
        f'    <EAN>{xml_escape(art.get("ean","") or "")}</EAN>\n',
        f'    <PRODUCT_TYPE>{xml_escape(art.get("product_type","SINGLE"))}</PRODUCT_TYPE>\n',
        f'    <DESCRIPTION_SHORT>{_cdata(art.get("description_short",""))}</DESCRIPTION_SHORT>\n',
        f'    <DESCRIPTION_LONG>{_cdata(art.get("description_long",""))}</DESCRIPTION_LONG>\n',
        f'    <MANUFACTURER_AID>{xml_escape(art.get("manufacturer_aid","") or "")}</MANUFACTURER_AID>\n',
        f'    <MANUFACTURER_NAME>{_cdata(art.get("manufacturer_name",""))}</MANUFACTURER_NAME>\n',
        f'    <DELIVERY_TIME>{xml_escape(str(art.get("delivery_time","") or ""))}</DELIVERY_TIME>\n',
    ]

    kws = art.get("keywords", [])
    if kws:
        lines.append('    <KEYWORDS>\n')
        for kw in kws:
            lines.append(f'      <KEYWORD>{_cdata(kw)}</KEYWORD>\n')
        lines.append('    </KEYWORDS>\n')

    lines.append('  </ARTICLE_DETAILS>\n')

    if art.get("reference_feature_system") or art.get("reference_feature_group_id"):
        lines += [
            '  <REFERENCE_FEATURES>\n',
            f'    <REFERENCE_FEATURE_SYSTEM_NAME>{xml_escape(art.get("reference_feature_system",""))}</REFERENCE_FEATURE_SYSTEM_NAME>\n',
            f'    <REFERENCE_FEATURE_GROUP_ID>{xml_escape(art.get("reference_feature_group_id",""))}</REFERENCE_FEATURE_GROUP_ID>\n',
            '  </REFERENCE_FEATURES>\n',
        ]

    features = art.get("features", [])
    if features:
        lines.append('  <ARTICLE_FEATURES>\n')
        for f in features:
            lines += [
                '    <FEATURE>\n',
                f'      <FNAME>{_cdata(f.get("fname",""))}</FNAME>\n',
                f'      <FVALUE>{_cdata(f.get("fvalue","") or "")}</FVALUE>\n',
            ]
            if f.get("funit"):
                lines.append(f'      <FUNIT>{xml_escape(f["funit"])}</FUNIT>\n')
            lines += [
                f'      <FUSAGE>{f.get("fusage",1)}</FUSAGE>\n',
                f'      <FORDER>{f.get("forder") or ""}</FORDER>\n',
                f'      <FSEARCHABLE>{f.get("fsearchable",1)}</FSEARCHABLE>\n',
                f'      <FSELECTABLE>{f.get("fselectable",0)}</FSELECTABLE>\n',
                '    </FEATURE>\n',
            ]
        lines.append('  </ARTICLE_FEATURES>\n')

    lines += [
        '  <ARTICLE_ORDER_DETAILS>\n',
        f'    <ORDER_UNIT>{xml_escape(art.get("order_unit","PCE"))}</ORDER_UNIT>\n',
        f'    <CONTENT_UNIT>{xml_escape(art.get("content_unit","PCE"))}</CONTENT_UNIT>\n',
        f'    <CONTENT_UNIT_AMOUNT>{xml_escape(str(art.get("content_unit_amount","") or ""))}</CONTENT_UNIT_AMOUNT>\n',
        f'    <NO_CU_PER_OU>{xml_escape(str(art.get("no_cu_per_ou","1") or "1"))}</NO_CU_PER_OU>\n',
        f'    <PRICE_QUANTITY>{xml_escape(str(art.get("price_quantity","1") or "1"))}</PRICE_QUANTITY>\n',
        f'    <QUANTITY_MIN>{xml_escape(str(art.get("quantity_min","1") or "1"))}</QUANTITY_MIN>\n',
        f'    <QUANTITY_INTERVAL>{xml_escape(str(art.get("quantity_interval","1") or "1"))}</QUANTITY_INTERVAL>\n',
        f'    <DEPOSIT>{xml_escape(str(art.get("deposit","") or ""))}</DEPOSIT>\n',
        '  </ARTICLE_ORDER_DETAILS>\n',
    ]

    # ARTICLE_PRICE_DETAILS – alle Preisstufen aus article_prices (falls per
    # get_article_prices() mitgeladen); Fallback auf den Einzelpreis-Satz aus
    # der articles-Zeile selbst, wenn keine Zeilen in article_prices vorliegen.
    prices = art.get("prices") or []
    if not prices and art.get("price_amount") is not None:
        prices = [{
            "price_type":       art.get("price_type", "net_customer"),
            "lower_bound":      art.get("lower_bound", 1),
            "price_amount":     art.get("price_amount"),
            "price_currency":   art.get("price_currency", "EUR"),
            "tax":              art.get("tax", 19),
            "valid_start_date": art.get("valid_start_date", ""),
            "valid_end_date":   art.get("valid_end_date", ""),
        }]

    lines.append('  <ARTICLE_PRICE_DETAILS>\n')
    for pr in prices:
        amount = pr.get("price_amount")
        if amount is None:
            continue
        amount_str = f"{float(amount):.2f}"
        lines += [
            f'    <ARTICLE_PRICE price_type="{xml_escape(pr.get("price_type","net_customer"))}">\n',
            f'      <PRICE_AMOUNT>{amount_str}</PRICE_AMOUNT>\n',
            f'      <PRICE_CURRENCY>{xml_escape(pr.get("price_currency","EUR"))}</PRICE_CURRENCY>\n',
            f'      <TAX>{pr.get("tax",19)}</TAX>\n',
            f'      <LOWER_BOUND>{pr.get("lower_bound",1)}</LOWER_BOUND>\n',
        ]
        if pr.get("valid_start_date"):
            lines.append(f'      <VALID_START_DATE>{xml_escape(pr["valid_start_date"])}</VALID_START_DATE>\n')
        if pr.get("valid_end_date"):
            lines.append(f'      <VALID_END_DATE>{xml_escape(pr["valid_end_date"])}</VALID_END_DATE>\n')
        lines.append('    </ARTICLE_PRICE>\n')
    lines.append('  </ARTICLE_PRICE_DETAILS>\n')

    is_online = 1 if (art.get("online", 1) and art.get("active", 1)) else 0
    lines += [
        '  <ARTICLE_AVAILABILITY_DETAILS>\n',
        f'    <ONLINE>{is_online}</ONLINE>\n',
        f'    <SEARCHABLE>{art.get("searchable",1)}</SEARCHABLE>\n',
        '  </ARTICLE_AVAILABILITY_DETAILS>\n',
    ]

    mimes = art.get("mimes", [])
    if mimes:
        lines.append('  <MIME_INFO>\n')
        for m in mimes:
            mime_src = _add_prefix(_extract_filename(m.get("mime_source", "") or ""), prefix)
            lines += [
                '    <MIME>\n',
                f'      <MIME_TYPE>{xml_escape(m.get("mime_type","") or "")}</MIME_TYPE>\n',
                f'      <MIME_SOURCE>{xml_escape(mime_src)}</MIME_SOURCE>\n',
                f'      <MIME_PURPOSE>{xml_escape(m.get("mime_purpose","") or "")}</MIME_PURPOSE>\n',
                f'      <MIME_DESC>{_cdata(m.get("mime_desc",""))}</MIME_DESC>\n',
                f'      <MIME_ALT>{_cdata(m.get("mime_alt",""))}</MIME_ALT>\n',
                f'      <MIME_ORDER>{m.get("mime_order",0)}</MIME_ORDER>\n',
                '    </MIME>\n',
            ]
        lines.append('  </MIME_INFO>\n')

    for ref in art.get("references", []):
        art_id_to = _add_prefix(ref.get("art_id_to", ""), prefix)
        lines += [
            f'  <ARTICLE_REFERENCE type="{xml_escape(ref.get("ref_type","similar"))}">\n',
            f'    <ART_ID_TO>{_cdata(art_id_to)}</ART_ID_TO>\n',
            '  </ARTICLE_REFERENCE>\n',
        ]

    udx_rows = art.get("udx", [])
    if udx_rows:
        lines.append('  <USER_DEFINED_EXTENSIONS>\n')
        for u in udx_rows:
            key = u.get("key", "")
            if not key:
                continue
            lines.append(f'    <UDX.{xml_escape(key)}>{_cdata(u.get("value",""))}</UDX.{xml_escape(key)}>\n')
        lines.append('  </USER_DEFINED_EXTENSIONS>\n')

    lines.append('</ARTICLE>')
    article_xml = "".join(lines)

    # ARTICLE_TO_CATALOGGROUP_MAP – über den Katalogbaum, sonst Fallback auf
    # die flachen catalog_group_id/catalog_sub_group_id-Spalten.
    grp = art.get("catalog_group_id", "") or ""
    sub = art.get("catalog_sub_group_id", "") or ""
    node_id = art.get("_catalog_node_id")
    if con is not None and node_id:
        path = get_catalog_path(con, node_id)
        if len(path) >= 2:
            grp = path[-2]["group_id"]
            sub = path[-1]["group_id"]
        elif len(path) == 1:
            grp = path[0]["group_id"]
            sub = path[0]["group_id"]
    sub = _add_prefix_if_missing(sub, prefix)

    catalog_map_xml = None
    if grp or sub:
        catalog_map_xml = (
            '<ARTICLE_TO_CATALOGGROUP_MAP>\n'
            f'  <ART_ID>{_cdata(pid)}</ART_ID>\n'
            f'  <CATALOG_GROUP_ID>{xml_escape(grp)}</CATALOG_GROUP_ID>\n'
            f'  <CATALOG_SUB_GROUP_ID>{xml_escape(sub)}</CATALOG_SUB_GROUP_ID>\n'
            '</ARTICLE_TO_CATALOGGROUP_MAP>'
        )

    return article_xml, catalog_map_xml


def insert_or_replace_article(xml_path: str, aid: str, article_xml: str,
                              catalog_map_xml: str | None = None,
                              progress_cb=None) -> dict:
    """
    Fügt article_xml in xml_path ein: ersetzt den bestehenden <ARTICLE>-Block
    mit gleicher SUPPLIER_AID (Text-Vergleich, getrimmt), oder hängt einen
    neuen Block direkt nach dem letzten vorhandenen </ARTICLE> an. Analog für
    catalog_map_xml über <ART_ID> in <ARTICLE_TO_CATALOGGROUP_MAP>-Blöcken.

    Legt vor jeder Änderung ein .bak neben xml_path an (nicht überschrieben,
    falls schon vorhanden – einmal pro Prozess).

    Gibt {"article": "replaced"|"inserted", "catalog_map": "replaced"|"inserted"|None,
          "backup": path} zurück.
    """
    p = progress_cb or (lambda m, **kw: None)

    with open(xml_path, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()

    result = {"article": None, "catalog_map": None, "backup": None}

    # ── ARTICLE-Block ────────────────────────────────────────────────────────
    replaced = False

    def _replace_if_match(m: re.Match) -> str:
        nonlocal replaced
        block = m.group(0)
        aid_m = _AID_RE.search(block)
        existing_aid = aid_m.group(1).strip() if aid_m else ""
        if existing_aid == aid.strip():
            replaced = True
            return article_xml
        return block

    new_raw = _ARTICLE_RE.sub(_replace_if_match, raw, count=0)

    if replaced:
        result["article"] = "replaced"
    else:
        last_end = None
        for m in _ARTICLE_RE.finditer(new_raw):
            last_end = m.end()
        if last_end is not None:
            new_raw = new_raw[:last_end] + "\n" + article_xml + new_raw[last_end:]
        else:
            # Keine ARTICLE-Blöcke gefunden – Datei ist evtl. leer/anderes Format.
            new_raw = new_raw.rstrip() + "\n" + article_xml + "\n"
        result["article"] = "inserted"

    # ── ARTICLE_TO_CATALOGGROUP_MAP-Block ───────────────────────────────────
    if catalog_map_xml:
        map_replaced = False

        def _replace_map_if_match(m: re.Match) -> str:
            nonlocal map_replaced
            block = m.group(0)
            id_m = _ART_ID_RE.search(block)
            existing_id = id_m.group(1).strip() if id_m else ""
            if existing_id == aid.strip():
                map_replaced = True
                return catalog_map_xml
            return block

        new_raw2 = _MAP_RE.sub(_replace_map_if_match, new_raw, count=0)

        if map_replaced:
            new_raw = new_raw2
            result["catalog_map"] = "replaced"
        else:
            last_end = None
            for m in _MAP_RE.finditer(new_raw2):
                last_end = m.end()
            if last_end is not None:
                new_raw = new_raw2[:last_end] + "\n" + catalog_map_xml + new_raw2[last_end:]
            else:
                # Keine vorhandenen Katalog-Zuordnungen – direkt nach dem
                # gerade eingefügten/ersetzten ARTICLE-Block anhängen.
                idx = new_raw.find(article_xml)
                if idx >= 0:
                    insert_at = idx + len(article_xml)
                    new_raw = new_raw[:insert_at] + "\n" + catalog_map_xml + new_raw[insert_at:]
                else:
                    new_raw = new_raw2.rstrip() + "\n" + catalog_map_xml + "\n"
            result["catalog_map"] = "inserted"

    backup_path = xml_path + ".bak"
    shutil.copy2(xml_path, backup_path)
    with open(xml_path, "w", encoding="utf-8") as f:
        f.write(new_raw)
    result["backup"] = backup_path

    p(f"Einzelartikel-Export: {aid} → {os.path.basename(xml_path)} "
      f"(Artikel {result['article']}"
      + (f", Katalogzuordnung {result['catalog_map']}" if result['catalog_map'] else "")
      + f"). Backup: {os.path.basename(backup_path)}", tag="ok")

    return result
