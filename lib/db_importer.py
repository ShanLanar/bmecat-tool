# lib/db_importer.py – BMEcat XML → Artikel-Datenbank
#
# Liest verarbeitete BMEcat-XMLs (nach Transform + Dedup) und importiert
# sie in die Artikel-Datenbank. Unterstützt Büroring, Nordwest, Softcarrier.
#
# Supplier-Konfiguration kommt aus supplier_config.yaml (db_supplier_name,
# db_supplier_alt_aid, prefix).

import logging
import os
import re
import xml.etree.ElementTree as ET
from typing import Callable

from lib.article_db import (get_or_create_supplier, open_db, transaction,
                             upsert_article, upsert_catalog_node,
                             assign_article_catalog, get_catalog_node, _now)

log = logging.getLogger(__name__)

_NS_RE           = re.compile(r'\{[^}]*\}')
_CAT_STRUCT_PAT  = re.compile(
    r'<CATALOG_STRUCTURE([^>]*)>(.*?)</CATALOG_STRUCTURE>', re.IGNORECASE | re.DOTALL)
_TYPE_ATTR_PAT   = re.compile(r"""type=["'](\w+)["']""", re.IGNORECASE)
_GROUP_ID_PAT    = re.compile(r'<GROUP_ID[^>]*>(.*?)</GROUP_ID>', re.IGNORECASE)
_GROUP_NAME_PAT  = re.compile(r'<GROUP_NAME[^>]*>(.*?)</GROUP_NAME>', re.IGNORECASE)
_PARENT_ID_PAT   = re.compile(r'<PARENT_ID[^>]*>(.*?)</PARENT_ID>', re.IGNORECASE)
_GROUP_DESC_PAT  = re.compile(r'<GROUP_DESCRIPTION[^>]*>(.*?)</GROUP_DESCRIPTION>', re.IGNORECASE | re.DOTALL)
_GROUP_ORD_PAT   = re.compile(r'<GROUP_ORDER[^>]*>(.*?)</GROUP_ORDER>', re.IGNORECASE)


def _tag(elem) -> str:
    return _NS_RE.sub('', elem.tag)


import posixpath as _posixpath
from urllib.parse import urlparse as _urlparse


def _clean_source(source: str) -> str:
    """Extrahiert reinen Dateinamen aus URL oder Pfad (wird beim Import bereinigt)."""
    if not source:
        return source
    if '://' in source:
        return _posixpath.basename(_urlparse(source).path)
    return _posixpath.basename(source.replace('\\', '/'))


def _txt(elem, path: str, default: str = '') -> str:
    node = elem.find(path)
    if node is None:
        return default
    return (node.text or '').strip()


# ── Supplier-Konfiguration ────────────────────────────────────────────────────

def _load_supplier_map(base_dir: str) -> dict:
    """
    Gibt {xml_filename: {supplier_name, supplier_alt_aid, prefix, product_id_prefix}} zurück.
    Liest aus supplier_config.yaml.
    """
    try:
        import yaml
        cfg_path = os.path.join(base_dir, 'supplier_config.yaml')
        with open(cfg_path, encoding='utf-8') as f:
            cfg = yaml.safe_load(f)
    except Exception as e:
        log.warning(f"supplier_config.yaml nicht lesbar: {e}")
        return {}

    result = {}
    for key, sup in cfg.get('suppliers', {}).items():
        prefix = sup.get('prefix', key.upper())
        # Nordwest: mehrere XMLs mit unterschiedlichen Supplier-Namen
        if 'db_supplier_names' in sup:
            for xml_file, sname in sup['db_supplier_names'].items():
                result[xml_file] = {
                    'supplier_name':    sname,
                    'supplier_alt_aid': sup.get('db_supplier_alt_aids', {}).get(xml_file, ''),
                    'prefix':           prefix,
                }
        else:
            for xml_file in sup.get('xml_files', []):
                result[xml_file] = {
                    'supplier_name':    sup.get('db_supplier_name', sup.get('label', key)),
                    'supplier_alt_aid': sup.get('db_supplier_alt_aid', ''),
                    'prefix':           prefix,
                }
    return result


# ── BMEcat-Parser ─────────────────────────────────────────────────────────────

def _import_catalog(con, xml_path: str, supplier_id: int, prefix: str,
                    progress_cb=None) -> int:
    """
    Importiert CATALOG_STRUCTURE-Einträge aus einer BMEcat-XML in catalog_nodes.
    Liest nur den Header-Bereich (vor dem ersten <ARTICLE>).
    Gibt Anzahl importierter Knoten zurück.
    """
    p = progress_cb or (lambda m, **kw: None)
    MAX_HEADER = 20 * 1024 * 1024

    header_parts = []
    header_size  = 0
    article_pat  = re.compile(r'<ARTICLE[\s>]', re.IGNORECASE)

    try:
        with open(xml_path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                if article_pat.search(line):
                    break
                header_parts.append(line)
                header_size += len(line)
                if header_size > MAX_HEADER:
                    break
    except Exception as e:
        p(f"Katalog-Import Lesefehler: {e}", tag='warn')
        return 0

    header = ''.join(header_parts)
    count  = 0

    for m in _CAT_STRUCT_PAT.finditer(header):
        attrs, block = m.group(1), m.group(2)

        gid_m = _GROUP_ID_PAT.search(block)
        if not gid_m:
            continue
        group_id = gid_m.group(1).strip()

        type_m   = _TYPE_ATTR_PAT.search(attrs)
        name_m   = _GROUP_NAME_PAT.search(block)
        par_m    = _PARENT_ID_PAT.search(block)
        desc_m   = _GROUP_DESC_PAT.search(block)
        ord_m    = _GROUP_ORD_PAT.search(block)

        node_type       = type_m.group(1).lower() if type_m else 'node'
        name            = name_m.group(1).strip() if name_m else group_id
        parent_group_id = par_m.group(1).strip()  if par_m  else ''
        if parent_group_id in ('0', ''):
            parent_group_id = ''
        description = desc_m.group(1).strip() if desc_m else ''
        # CDATA entfernen
        description = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', description, flags=re.DOTALL)
        try:
            node_order = int(ord_m.group(1).strip()) if ord_m else 0
        except ValueError:
            node_order = 0

        upsert_catalog_node(con, supplier_id, group_id, parent_group_id,
                            name, description, node_order, node_type)
        count += 1

    if count:
        p(f"Katalog: {count} Knoten importiert ({os.path.basename(xml_path)})")
    return count


def _parse_article(art_elem, prefix: str) -> dict:
    """Parst ein <ARTICLE>-Element in ein Artikel-Dict."""

    # Artikel-ID: BMEcat 1.2 = SUPPLIER_AID, BMEcat 2005 = SUPPLIER_PID
    supplier_pid = (
        _txt(art_elem, 'SUPPLIER_AID')
        or _txt(art_elem, 'ARTICLE_DETAILS/SUPPLIER_AID')
        or _txt(art_elem, 'SUPPLIER_PID')
        or _txt(art_elem, 'ARTICLE_DETAILS/SUPPLIER_PID')
        or ''
    )

    det = art_elem.find('ARTICLE_DETAILS') or art_elem

    # Keywords (können mehrfach vorkommen oder als kommasep. Liste)
    keywords = []
    for kw_elem in art_elem.findall('./ARTICLE_DETAILS/KEYWORD') + art_elem.findall('./KEYWORD'):
        text = (kw_elem.text or '').strip()
        if text:
            for part in text.split(','):
                part = part.strip()
                if part:
                    keywords.append(part)
    # Deduplizieren, Reihenfolge erhalten
    seen = set()
    keywords = [k for k in keywords if not (k in seen or seen.add(k))]

    # Features
    features = []
    for feat_set in art_elem.findall('./ARTICLE_FEATURES'):
        for feat in feat_set.findall('FEATURE'):
            fname = _txt(feat, 'FNAME')
            if not fname:
                continue
            funit       = _txt(feat, 'FUNIT')
            fusage      = int(_txt(feat, 'FUSAGE') or 1)
            forder      = int(_txt(feat, 'FORDER') or 0) if _txt(feat, 'FORDER') else 0
            fsearchable = int(_txt(feat, 'FSEARCHABLE') or 1)
            fselectable = int(_txt(feat, 'FSELECTABLE') or 0)
            # Multi-Value: alle FVALUE-Kinder einzeln speichern (wie product_feature_value)
            fvalues = [(child.text or '').strip()
                       for child in feat if _tag(child) == 'FVALUE']
            if not fvalues:
                fvalues = ['']
            for idx, fval in enumerate(fvalues):
                features.append({
                    'fname':       fname,
                    'fvalue':      fval,
                    'funit':       funit,
                    'fusage':      fusage,
                    'forder':      forder,
                    'fsearchable': fsearchable,
                    'fselectable': fselectable,
                    'value_index': idx,
                })

    # ECLASS-Referenz
    ref_feat = art_elem.find('./ARTICLE_FEATURES')
    ref_sys  = _txt(ref_feat, 'REFERENCE_FEATURE_SYSTEM_NAME') if ref_feat else ''
    ref_grp  = _txt(ref_feat, 'REFERENCE_FEATURE_GROUP_ID')   if ref_feat else ''

    # Preis
    price_elem = art_elem.find('./ARTICLE_PRICE_DETAILS/ARTICLE_PRICE')
    price_type     = (price_elem.get('price_type', 'net_customer') if price_elem is not None else 'net_customer')
    price_amount   = _txt(price_elem, 'PRICE_AMOUNT')   if price_elem is not None else ''
    price_currency = _txt(price_elem, 'PRICE_CURRENCY') if price_elem is not None else 'EUR'
    tax_str        = _txt(price_elem, 'TAX')             if price_elem is not None else '19'
    lower_bound    = _txt(price_elem, 'LOWER_BOUND')     if price_elem is not None else '1'
    valid_start    = _txt(price_elem, 'VALID_START_DATE') if price_elem is not None else ''
    valid_end      = _txt(price_elem, 'VALID_END_DATE')   if price_elem is not None else ''

    try:
        price_float = float(price_amount.replace(',', '.')) if price_amount else None
    except ValueError:
        price_float = None
    try:
        tax_int = int(float(tax_str)) if tax_str else 19
    except ValueError:
        tax_int = 19
    try:
        lb_int = int(float(lower_bound)) if lower_bound else 1
    except ValueError:
        lb_int = 1

    # Bestelldetails
    od = art_elem.find('./ARTICLE_ORDER_DETAILS') or ET.Element('x')

    # Verfügbarkeit
    av = art_elem.find('./ARTICLE_AVAILABILITY_DETAILS') or ET.Element('x')

    # MIME_INFO
    mimes = []
    for mime in art_elem.findall('./MIME_INFO/MIME'):
        mimes.append({
            'mime_type':    _txt(mime, 'MIME_TYPE'),
            'mime_source':  _clean_source(_txt(mime, 'MIME_SOURCE')),
            'mime_purpose': _txt(mime, 'MIME_PURPOSE'),
            'mime_desc':    _txt(mime, 'MIME_DESC'),
            'mime_alt':     _txt(mime, 'MIME_ALT'),
            'mime_order':   int(_txt(mime, 'MIME_ORDER') or 0),
        })

    # ARTICLE_REFERENCE (Crossselling etc.)
    references = []
    for ref in art_elem.findall('./ARTICLE_REFERENCE'):
        art_id_to = _txt(ref, 'ART_ID_TO')
        if art_id_to:
            references.append({
                'ref_type':  ref.get('type', 'similar'),
                'art_id_to': art_id_to,
            })

    # UDX (USER_DEFINED_EXTENSIONS)
    udx = []
    udx_elem = art_elem.find('./USER_DEFINED_EXTENSIONS')
    if udx_elem is not None:
        for child in udx_elem:
            key = _tag(child).replace('UDX.', '')
            val = (child.text or '').strip()
            udx.append({'key': key, 'value': val})

    # Catalog-Mapping (in Büroring/Nordwest oft im ARTICLE_TO_CATALOGGROUP_MAP
    # auf Root-Ebene – wird hier per product_id verknüpft, falls im Parent gesetzt)
    ean = _txt(det, 'EAN')

    product_id = f"{prefix}{supplier_pid}" if prefix else supplier_pid

    return {
        'supplier_pid':                supplier_pid,
        'product_id':                  product_id,
        'ean':                         ean,
        'product_type':                _txt(det, 'PRODUCT_TYPE') or 'SINGLE',
        'category':                    _txt(det, 'CATEGORY'),
        'variation_group':             _txt(det, 'VARIATION_GROUP') or product_id,
        'description_short':           _txt(det, 'DESCRIPTION_SHORT'),
        'description_long':            _txt(det, 'DESCRIPTION_LONG'),
        'manufacturer_aid':            _txt(det, 'MANUFACTURER_AID'),
        'manufacturer_name':           _txt(det, 'MANUFACTURER_NAME'),
        'delivery_time':               _txt(det, 'DELIVERY_TIME'),
        'order_unit':                  _txt(od, 'ORDER_UNIT') or 'PCE',
        'content_unit':                _txt(od, 'CONTENT_UNIT') or 'PCE',
        'content_unit_amount':         _txt(od, 'CONTENT_UNIT_AMOUNT'),
        'no_cu_per_ou':                _txt(od, 'NO_CU_PER_OU') or '1',
        'price_quantity':              _txt(od, 'PRICE_QUANTITY') or '1',
        'quantity_min':                _txt(od, 'QUANTITY_MIN') or '1',
        'quantity_interval':           _txt(od, 'QUANTITY_INTERVAL') or '1',
        'deposit':                     _txt(od, 'DEPOSIT'),
        'price_type':                  price_type,
        'price_amount':                price_float,
        'price_currency':              price_currency,
        'tax':                         tax_int,
        'lower_bound':                 lb_int,
        'valid_start_date':            valid_start,
        'valid_end_date':              valid_end,
        'online':                      int(_txt(av, 'ONLINE') or 1),
        'searchable':                  int(_txt(av, 'SEARCHABLE') or 1),
        'reference_feature_system':    ref_sys,
        'reference_feature_group_id':  ref_grp,
        'catalog_group_id':            '',   # wird ggf. per ARTICLE_TO_CATALOGGROUP_MAP gesetzt
        'catalog_sub_group_id':        '',
        'features':                    features,
        'mimes':                       mimes,
        'keywords':                    keywords,
        'references':                  references,
        'udx':                         udx,
    }


# ── Import-Einstiegspunkt ─────────────────────────────────────────────────────

def import_xml(db_path: str, xml_path: str, base_dir: str,
               progress_cb: Callable = None) -> dict:
    """
    Importiert eine verarbeitete BMEcat-XML-Datei in die Datenbank.
    Gibt Import-Statistik zurück.
    """
    p = progress_cb or (lambda m, **kw: None)
    xml_name = os.path.basename(xml_path)

    # Supplier-Konfiguration
    sup_map   = _load_supplier_map(base_dir)
    sup_cfg   = sup_map.get(xml_name, {})
    sup_name  = sup_cfg.get('supplier_name', xml_name.replace('.xml', ''))
    sup_altid = sup_cfg.get('supplier_alt_aid', '')
    prefix    = sup_cfg.get('prefix', '')

    p(f"DB-Import [{sup_name}]: lese {xml_name} ...")

    con = open_db(db_path)
    import_start = _now()   # Zeitstempel für Stale-Cleanup
    supplier_id = get_or_create_supplier(con, sup_name,
                                         supplier_alt_aid=sup_altid)

    # Katalogbaum importieren
    with transaction(con):
        _import_catalog(con, xml_path, supplier_id, prefix, progress_cb=p)

    # ARTICLE_TO_CATALOGGROUP_MAP sammeln via iterparse (kein Full-Memory-Load)
    catalog_map: dict[str, tuple[str, str]] = {}
    try:
        for _ev, _el in ET.iterparse(xml_path, events=('end',)):
            if _tag(_el) == 'ARTICLE_TO_CATALOGGROUP_MAP':
                raw_aid = (_txt(_el, 'ART_ID') or '').strip()
                aid = raw_aid.replace(prefix, '', 1) if prefix and raw_aid.startswith(prefix) else raw_aid
                grp = _txt(_el, 'CATALOG_GROUP_ID')
                sub = _txt(_el, 'CATALOG_SUB_GROUP_ID')
                if aid:
                    catalog_map[aid] = (grp, sub)
                _el.clear()
    except Exception as exc:
        log.debug(f"catalog_map Sammlung: {exc}")

    stats = {'new': 0, 'updated': 0, 'unchanged': 0, 'errors': 0}
    batch_size = 500
    batch = []

    def _flush(batch):
        with transaction(con):
            for art in batch:
                try:
                    status, art_id = upsert_article(con, supplier_id, art)
                    stats[status] += 1
                    # Katalog-Knoten zuordnen (art_id direkt aus upsert, kein Extra-SELECT)
                    sub_gid = art.get('catalog_sub_group_id') or art.get('catalog_group_id', '')
                    if sub_gid and art_id:
                        node = get_catalog_node(con, supplier_id, sub_gid)
                        if node:
                            assign_article_catalog(con, art_id, node['id'])
                except Exception as exc:
                    log.warning(f"Upsert-Fehler {art.get('supplier_pid','?')}: {exc}")
                    stats['errors'] += 1

    # Streaming-Parse (iterparse für große Dateien)
    ctx = ET.iterparse(xml_path, events=('end',))
    for event, elem in ctx:
        if _tag(elem) != 'ARTICLE':
            continue
        try:
            art = _parse_article(elem, prefix)
            # Catalog-Mapping eintragen
            pid = art['supplier_pid']
            if pid in catalog_map:
                art['catalog_group_id'], art['catalog_sub_group_id'] = catalog_map[pid]
            batch.append(art)
            if len(batch) >= batch_size:
                _flush(batch)
                batch.clear()
        except Exception as exc:
            log.warning(f"Parse-Fehler: {exc}")
            stats['errors'] += 1
        finally:
            elem.clear()

    if batch:
        _flush(batch)

    # Stale-Cleanup: Artikel dieses Lieferanten die in diesem Lauf nicht
    # angefasst wurden (last_seen < import_start) → veraltet oder aus Katalog entfernt
    dropped_articles: list[dict] = []
    try:
        # Erst die IDs/product_ids holen bevor gelöscht wird
        stale_rows = con.execute(
            "SELECT product_id FROM articles WHERE supplier_id=? AND last_seen < ?",
            (supplier_id, import_start)
        ).fetchall()
        dropped_articles = [{"product_id": r["product_id"],
                             "supplier_name": sup_name} for r in stale_rows]
        with transaction(con):
            deleted = con.execute(
                "DELETE FROM articles WHERE supplier_id=? AND last_seen < ?",
                (supplier_id, import_start)
            ).rowcount
        if deleted:
            p(f"DB-Import [{sup_name}]: {deleted} Artikel nicht mehr im Katalog "
              f"→ entfernt", tag="dim")
            for a in dropped_articles[:5]:
                p(f"  entfernt: {a['product_id']}", tag="dim")
                # Dropped-Event an Collector weiterleiten
                try:
                    p("", tag="dim", _dropped=a)
                except TypeError:
                    pass   # progress_cb unterstützt _dropped nicht → ok
            if len(dropped_articles) > 5:
                p(f"  … und {len(dropped_articles)-5} weitere", tag="dim")
    except Exception as exc:
        log.warning(f"Stale-Cleanup Fehler: {exc}")
        dropped_articles = []

    total = stats['new'] + stats['updated'] + stats['unchanged']
    p(f"DB-Import [{sup_name}]: {total} Artikel "
      f"(+{stats['new']} neu, ~{stats['updated']} geändert, "
      f"={stats['unchanged']} unverändert, !{stats['errors']} Fehler)", tag='ok')
    # last_import_date für diesen Lieferanten/XML aktualisieren
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(suppliers)")]
        if 'last_import_date' not in cols:
            con.execute("ALTER TABLE suppliers ADD COLUMN last_import_date TEXT")
        if 'last_import_xml' not in cols:
            con.execute("ALTER TABLE suppliers ADD COLUMN last_import_xml TEXT")
        con.execute(
            "UPDATE suppliers SET last_import_date=?, last_import_xml=? WHERE id=?",
            (_now(), xml_name, supplier_id))
        con.commit()
    except Exception as exc:
        log.debug(f"last_import_date Fehler: {exc}")

    stats["dropped"] = dropped_articles
    return stats
