# lib/db_exporter.py – DB → VENDOSYS_CAT XML-Export
#
# Exportiert geänderte Artikel als einzelne VENDOSYS_CAT XML-Dateien.
# Dateiname: {product_id}_{timestamp}.xml
# Liest UDX-Feldzuordnung aus udx_fields.csv im BASE_DIR.

import csv
import logging
import os
from datetime import datetime, timezone
from typing import Callable
from xml.sax.saxutils import escape as xml_escape

import csv as _csv
from lib.article_db import open_db, query_changed, query_by_ids, get_catalog_path, get_catalog_node
from lib.db_postprocess import PostProcessor, apply_ean_dedup, load_supplier_priority

log = logging.getLogger(__name__)

_TODAY = datetime.now(timezone.utc).strftime('%Y-%m-%d')
_TS    = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')


# ── UDX-Feldzuordnung ─────────────────────────────────────────────────────────

def _load_udx_fields(base_dir: str) -> dict:
    """
    udx_fields.csv: Spalten fname, udx_key
    Mappt Feature-FNAME → UDX-Schlüssel für die USER_DEFINED_EXTENSIONS.
    """
    path = os.path.join(base_dir, 'udx_fields.csv')
    if not os.path.exists(path):
        return {}
    result = {}
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                fname   = (row.get('fname') or '').strip()
                udx_key = (row.get('udx_key') or '').strip()
                if fname and udx_key:
                    result[fname.upper()] = udx_key
    except Exception as e:
        log.warning(f"udx_fields.csv Fehler: {e}")
    return result


def _load_catalog_remap(base_dir: str) -> list[dict]:
    """
    Liest postprocess_catalog_remap.csv.
    Gibt [{supplier, source_group_id, target_group_id}] zurück.
    """
    path = os.path.join(base_dir, 'postprocess_catalog_remap.csv')
    if not os.path.exists(path):
        return []
    rules = []
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            for row in _csv.DictReader(f):
                src = (row.get('source_group_id') or '').strip()
                tgt = (row.get('target_group_id') or '').strip()
                if src and tgt and not src.startswith('#'):
                    rules.append({
                        'supplier':         (row.get('supplier') or '').strip(),
                        'source_group_id':  src,
                        'target_group_id':  tgt,
                    })
    except Exception as e:
        import logging; logging.getLogger(__name__).warning(f"catalog_remap Fehler: {e}")
    return rules


def _apply_catalog_remap(group_id: str, supplier: str, rules: list) -> str:
    """Gibt remappten group_id zurück, oder unverändert wenn keine Regel passt."""
    for rule in rules:
        if rule['supplier'] and rule['supplier'].lower() != supplier.lower():
            continue
        if rule['source_group_id'] == group_id:
            return rule['target_group_id']
    return group_id


# ── Präfix-Helfer ────────────────────────────────────────────────────────────

def _load_prefix_map(base_dir: str) -> dict:
    """Lädt {supplier_name: prefix} aus supplier_config.yaml als Fallback."""
    try:
        import yaml
        with open(os.path.join(base_dir, 'supplier_config.yaml'),
                  encoding='utf-8') as f:
            cfg = yaml.safe_load(f)
        result = {}
        for _key, sup in cfg.get('suppliers', {}).items():
            prefix = sup.get('prefix', '')
            if not prefix:
                continue
            # Einfacher Lieferant
            for name_key in ('db_supplier_name', 'label'):
                name = sup.get(name_key, '')
                if name:
                    result[name] = prefix
            # Nordwest: mehrere XML → mehrere Supplier-Namen
            for name in sup.get('db_supplier_names', {}).values():
                result[name] = prefix
        return result
    except Exception:
        return {}


def _supplier_prefix(art: dict, prefix_map: dict = None) -> str:
    """
    Leitet das Lieferantenpräfix (NDW/SOC/BRG...) ab.
    Primär: product_id − supplier_pid (z.B. NDW2000379997 − 2000379997 = NDW).
    Fallback: supplier_config.yaml über supplier_name.
    """
    pid = art.get('supplier_pid', '')
    prd = art.get('product_id', '')
    if pid and prd and prd.endswith(pid):
        return prd[:-len(pid)]
    # Fallback für alte/defekte Einträge (supplier_pid leer)
    if prefix_map:
        return prefix_map.get(art.get('supplier_name', ''), '')
    return ''


def _extract_filename(source: str) -> str:
    """
    Extrahiert den reinen Dateinamen aus einer URL oder einem Pfad.
    'https://img.nordwest.com/tn700/L_11331.jpg' → 'L_11331.jpg'
    'some/path/file.jpg'                          → 'file.jpg'
    '18443.jpg'                                   → '18443.jpg'
    """
    if not source:
        return source
    import posixpath
    from urllib.parse import urlparse
    if '://' in source:
        return posixpath.basename(urlparse(source).path)
    # Windows- oder Unix-Pfad
    return posixpath.basename(source.replace('\\', '/'))


def _add_prefix(value: str, prefix: str) -> str:
    """
    Hängt Präfix immer vorn an.
    MIME_SOURCE und ART_ID_TO werden in der DB ohne Präfix gespeichert
    (direkt aus dem Lieferanten-XML). Der Exporter setzt es immer.
    BRGBRG... bei Büroring-Eigenmarken ist deshalb korrekt und gewollt.
    """
    if not value or not prefix:
        return value
    return prefix + value


def _add_prefix_if_missing(value: str, prefix: str) -> str:
    """
    Hängt Präfix nur vorn an, wenn noch nicht vorhanden (case-insensitiv).
    Für Katalog-IDs: GROUP_ID im Katalogbaum kann ohne Präfix gespeichert sein
    (z.B. 'Einwegoverall' statt 'NDWEinwegoverall'), während
    ARTICLE_TO_CATALOGGROUP_MAP/CATALOG_SUB_GROUP_ID ihn bereits hat.
    """
    if not value or not prefix:
        return value
    if value.upper().startswith(prefix.upper()):
        return value
    return prefix + value


# ── XML-Helpers ───────────────────────────────────────────────────────────────

def _cdata(text: str) -> str:
    if text is None:
        return ''
    text = str(text)
    if any(c in text for c in '<>&"\''):
        return f'<![CDATA[{text}]]>'
    return text


def _elem(tag: str, value, cdata: bool = False, indent: int = 4) -> str:
    sp  = ' ' * indent
    val = '' if (value is None or str(value).strip() == '') else str(value)
    if cdata and val:
        return f'{sp}<{tag}><![CDATA[{val}]]></{tag}>\n'
    return f'{sp}<{tag}>{xml_escape(val)}</{tag}>\n'


# ── Artikel → XML ─────────────────────────────────────────────────────────────

def _render_article(art: dict, udx_map: dict, con=None, remap_rules: list = None, prefix_map: dict = None) -> str:
    pid     = art.get('product_id', '')
    sup_pid = art.get('supplier_pid', '')
    suffix  = art.get('_aid_suffix', '')

    # SUPPLIER_AID mit Suffix
    sup_aid = f"{sup_pid}{suffix}"

    sup    = art.get('supplier_name', '')
    prefix = _supplier_prefix(art, prefix_map)

    lines = ['<?xml version="1.0" encoding="UTF-8"?>\n',
             '<VENDOSYS_CAT version="1.0">\n',
             '  <HEADER>\n',
             '    <GENERATOR_INFO>PDT</GENERATOR_INFO>\n',
             f'    <GENERATION_DATE>{_TODAY}</GENERATION_DATE>\n',
             '    <LANGUAGE>deu</LANGUAGE>\n',
             '  </HEADER>\n',
             '  <ARTICLE mode="update">\n',
             '    <SUPPLIER>\n',
             f'      <SUPPLIER_NAME><![CDATA[{art.get("supplier_name","")}]]></SUPPLIER_NAME>\n',
             f'      <SUPPLIER_CODE>{xml_escape(art.get("supplier_code",""))}</SUPPLIER_CODE>\n',
             f'      <SUPPLIER_AID>{xml_escape(sup_aid)}</SUPPLIER_AID>\n',
             f'      <SUPPLIER_ALT_AID><![CDATA[{art.get("supplier_alt_aid","")}]]></SUPPLIER_ALT_AID>\n',
             '    </SUPPLIER>\n',
             '    <CATALOGS>\n',
             '    </CATALOGS>\n',
             '    <ARTICLE_DETAILS>\n',
             f'      <PRODUCT_ID><![CDATA[{pid}]]></PRODUCT_ID>\n',
             f'      <EAN>{xml_escape(art.get("ean",""))}</EAN>\n',
             f'      <PRODUCT_TYPE>{xml_escape(art.get("product_type","SINGLE"))}</PRODUCT_TYPE>\n',
             f'      <CATEGORY>{xml_escape(art.get("category",""))}</CATEGORY>\n',
             f'      <VARIATION_GROUP><![CDATA[{art.get("variation_group", pid)}]]></VARIATION_GROUP>\n',
             f'      <DESCRIPTION_SHORT><![CDATA[{art.get("description_short","")}]]></DESCRIPTION_SHORT>\n',
             f'      <DESCRIPTION_LONG><![CDATA[{art.get("description_long","")}]]></DESCRIPTION_LONG>\n',
             f'      <MANUFACTURER_AID>{xml_escape(art.get("manufacturer_aid",""))}</MANUFACTURER_AID>\n',
             f'      <MANUFACTURER_NAME><![CDATA[{art.get("manufacturer_name","")}]]></MANUFACTURER_NAME>\n',
             f'      <DELIVERY_TIME>{xml_escape(str(art.get("delivery_time","") or ""))}</DELIVERY_TIME>\n',
             ]

    # Keywords
    kws = art.get('keywords', [])
    if kws:
        lines.append('      <KEYWORDS>\n')
        lines.append(f'        <KEYWORD>{xml_escape(",".join(kws))}</KEYWORD>\n')
        lines.append('      </KEYWORDS>\n')

    lines.append('    </ARTICLE_DETAILS>\n')

    # REFERENCE_FEATURES
    lines += [
        '    <REFERENCE_FEATURES>\n',
        f'      <REFERENCE_FEATURE_SYSTEM_NAME>{xml_escape(art.get("reference_feature_system",""))}</REFERENCE_FEATURE_SYSTEM_NAME>\n',
        f'      <REFERENCE_FEATURE_GROUP_ID>{xml_escape(art.get("reference_feature_group_id",""))}</REFERENCE_FEATURE_GROUP_ID>\n',
        '    </REFERENCE_FEATURES>\n',
    ]

    # ARTICLE_FEATURES
    features = art.get('features', [])
    if features:
        lines.append('    <ARTICLE_FEATURES>\n')
        for f in features:
            fval  = f.get('fvalue', '') or ''
            funit = f.get('funit', '') or ''
            ford  = f.get('forder', '')
            lines += [
                '      <FEATURE>\n',
                f'        <FNAME><![CDATA[{f["fname"]}]]></FNAME>\n',
                f'        <FVALUE><![CDATA[{fval}]]></FVALUE>\n',
            ]
            if funit:
                lines.append(f'        <FUNIT>{xml_escape(funit)}</FUNIT>\n')
            lines += [
                f'        <FUSAGE>{f.get("fusage",1)}</FUSAGE>\n',
                f'        <FORDER>{ford if ford else ""}</FORDER>\n',
                f'        <FSEARCHABLE>{f.get("fsearchable",1)}</FSEARCHABLE>\n',
                f'        <FSELECTABLE>{f.get("fselectable",0)}</FSELECTABLE>\n',
                '      </FEATURE>\n',
            ]
        lines.append('    </ARTICLE_FEATURES>\n')

    # ARTICLE_ORDER_DETAILS
    lines += [
        '    <ARTICLE_ORDER_DETAILS>\n',
        f'      <ORDER_UNIT>{xml_escape(art.get("order_unit","PCE"))}</ORDER_UNIT>\n',
        f'      <CONTENT_UNIT>{xml_escape(art.get("content_unit","PCE"))}</CONTENT_UNIT>\n',
        f'      <CONTENT_UNIT_AMOUNT>{xml_escape(str(art.get("content_unit_amount","") or ""))}</CONTENT_UNIT_AMOUNT>\n',
        f'      <NO_CU_PER_OU>{xml_escape(str(art.get("no_cu_per_ou","1")))}</NO_CU_PER_OU>\n',
        f'      <PRICE_QUANTITY>{xml_escape(str(art.get("price_quantity","1")))}</PRICE_QUANTITY>\n',
        f'      <QUANTITY_MIN>{xml_escape(str(art.get("quantity_min","1")))}</QUANTITY_MIN>\n',
        f'      <QUANTITY_INTERVAL>{xml_escape(str(art.get("quantity_interval","1")))}</QUANTITY_INTERVAL>\n',
        f'      <DEPOSIT>{xml_escape(str(art.get("deposit","") or ""))}</DEPOSIT>\n',
        '    </ARTICLE_ORDER_DETAILS>\n',
    ]

    # ARTICLE_PRICE_DETAILS – nur gültige nrp-Preise (net_customer)
    lines += ['    <ARTICLE_PRICE_DETAILS>\n']

    # Preis-Validierung
    price_type = art.get('price_type', '')
    price = art.get('price_amount')
    valid_start = art.get('valid_start_date', '').strip()
    valid_end = art.get('valid_end_date', '').strip()

    # Nur exportieren wenn: nrp-Preis UND (kein Datum ODER gültig zum Export-Zeitpunkt)
    is_valid = True
    skip_reason = None

    if price_type.lower() != 'nrp':
        is_valid = False
        skip_reason = f"price_type={price_type} (nicht nrp)"
    elif price is None or (isinstance(price, float) and price == 0):
        is_valid = False
        skip_reason = f"price={price} (kein oder 0-Preis)"
    else:
        # Datumsprüfung gegen Export-Zeit (nur Datum, YYYY-MM-DD)
        export_now = datetime.now(timezone.utc).date().isoformat()
        if valid_start and valid_start > export_now:
            is_valid = False
            skip_reason = f"valid_start={valid_start} (in Zukunft)"
        elif valid_end and valid_end < export_now:
            is_valid = False
            skip_reason = f"valid_end={valid_end} (in Vergangenheit)"

    if is_valid:
        price_str = f"{price:.2f}" if isinstance(price, float) else str(price or '')
        # TAX: DB speichert als Integer (19 = 19/100 = 0.19), Export braucht dezimal
        tax_val = art.get('tax', 19)
        tax_decimal = f"{tax_val / 100:.2f}" if isinstance(tax_val, int) else str(tax_val)
        lines += [
            '      <ARTICLE_PRICE price_type="net_customer">\n',
            f'        <VALID_START_DATE>{xml_escape(valid_start)}</VALID_START_DATE>\n',
            f'        <VALID_END_DATE>{xml_escape(valid_end)}</VALID_END_DATE>\n',
            f'        <PRICE_AMOUNT>{price_str}</PRICE_AMOUNT>\n',
            f'        <PRICE_CURRENCY>{xml_escape(art.get("price_currency","EUR"))}</PRICE_CURRENCY>\n',
            f'        <TAX>{tax_decimal}</TAX>\n',
            f'        <LOWER_BOUND>{art.get("lower_bound",1)}</LOWER_BOUND>\n',
            '      </ARTICLE_PRICE>\n',
        ]
    elif skip_reason:
        # Debug-Kommentar für fehlende Preise (nur lokal sichtbar, nicht exportiert)
        log.debug(f"Skip price export für {pid}: {skip_reason}")

    lines += ['    </ARTICLE_PRICE_DETAILS>\n']

    # ARTICLE_AVAILABILITY_DETAILS
    lines += [
        '    <ARTICLE_AVAILABILITY_DETAILS>\n',
        f'      <ONLINE>{art.get("online",1)}</ONLINE>\n',
        f'      <SEARCHABLE>{art.get("searchable",1)}</SEARCHABLE>\n',
        '    </ARTICLE_AVAILABILITY_DETAILS>\n',
    ]

    # MIME_INFO – image/jpeg mit mime_purpose=normal wird zu thumbnail+detail
    mimes = art.get('mimes', [])
    if mimes:
        lines.append('    <MIME_INFO>\n')
        for m in mimes:
            mime_src = _add_prefix(_extract_filename(m.get('mime_source', '') or ''), prefix)
            mime_type = m.get('mime_type', '')
            mime_purpose = m.get('mime_purpose', '')

            # Determine purposes to export: jpeg/normal → [thumbnail, detail, normal]
            purposes = []
            if mime_type.lower() == 'image/jpeg' and mime_purpose.lower() == 'normal':
                purposes = ['thumbnail', 'detail', 'normal']
            else:
                purposes = [mime_purpose] if mime_purpose else ['']

            # Export each purpose as separate MIME entry
            for purpose in purposes:
                lines += [
                    '      <MIME>\n',
                    f'        <MIME_TYPE>{xml_escape(mime_type)}</MIME_TYPE>\n',
                    f'        <MIME_SOURCE>{xml_escape(mime_src)}</MIME_SOURCE>\n',
                    f'        <MIME_PURPOSE>{xml_escape(purpose)}</MIME_PURPOSE>\n',
                    f'        <MIME_DESC><![CDATA[{m.get("mime_desc","")}]]></MIME_DESC>\n',
                    f'        <MIME_ALT><![CDATA[{m.get("mime_alt","")}]]></MIME_ALT>\n',
                    f'        <MIME_ORDER>{m.get("mime_order",0)}</MIME_ORDER>\n',
                    '      </MIME>\n',
                ]
        lines.append('    </MIME_INFO>\n')

    # ARTICLE_REFERENCE (Crossselling)
    for ref in art.get('references', []):
        art_id_to = _add_prefix(ref.get('art_id_to', ''), prefix)
        lines += [
            f'    <ARTICLE_REFERENCE type="{xml_escape(ref.get("ref_type","similar"))}">\n',
            f'      <ART_ID_TO><![CDATA[{art_id_to}]]></ART_ID_TO>\n',
            '    </ARTICLE_REFERENCE>\n',
        ]

    # USER_DEFINED_EXTENSIONS (aus udx-Tabelle + Feature-Mapping)
    udx_entries: dict[str, str] = {}

    # UDX aus DB
    for u in art.get('udx', []):
        udx_entries[u['key']] = u.get('value', '')

    # Features die laut udx_fields.csv als UDX exportiert werden
    for f in features:
        mapped_key = udx_map.get(f['fname'].upper())
        if mapped_key:
            udx_entries[mapped_key] = f.get('fvalue', '') or ''

    if udx_entries:
        lines.append('    <USER_DEFINED_EXTENSIONS>\n')
        for key, val in udx_entries.items():
            lines.append(f'      <UDX.{xml_escape(key)}>{_cdata(val)}</UDX.{xml_escape(key)}>\n')
        lines.append('    </USER_DEFINED_EXTENSIONS>\n')

    lines.append('  </ARTICLE>\n')

    # ARTICLE_TO_CATALOGGROUP_MAP – aus Katalogbaum oder Fallback auf flat strings
    grp = art.get('catalog_group_id', '')
    sub = art.get('catalog_sub_group_id', '')
    if con is not None:
        node_id = art.get('_catalog_node_id')
        if node_id:
            path = get_catalog_path(con, node_id)
            if len(path) >= 2:
                grp = path[-2]['group_id']
                sub = path[-1]['group_id']
            elif len(path) == 1:
                grp = path[0]['group_id']
                sub = path[0]['group_id']
    # Präfix auf CATALOG_SUB_GROUP_ID setzen (GROUP_ID im Baum kann ohne Präfix sein)
    # CATALOG_GROUP_ID (Root-Code wie 'AS') erhält keinen Präfix
    sub = _add_prefix_if_missing(sub, prefix)
    # Export-Zeit-Remap anwenden
    if remap_rules:
        grp = _apply_catalog_remap(grp, sup, remap_rules)
        sub = _apply_catalog_remap(sub, sup, remap_rules)
    if grp or sub:
        lines += [
            '  <ARTICLE_TO_CATALOGGROUP_MAP>\n',
            f'    <ART_ID><![CDATA[{pid}]]></ART_ID>\n',
            f'    <CATALOG_GROUP_ID>{xml_escape(grp)}</CATALOG_GROUP_ID>\n',
            f'    <CATALOG_SUB_GROUP_ID>{xml_escape(sub)}</CATALOG_SUB_GROUP_ID>\n',
            '  </ARTICLE_TO_CATALOGGROUP_MAP>\n',
        ]

    lines.append('</VENDOSYS_CAT>\n')
    return ''.join(lines)


# ── Export-Einstiegspunkt ─────────────────────────────────────────────────────

def _cleanup_export_dir(export_dir: str, keep_days: int = 7,
                        progress_cb=None):
    """Löscht XML-Dateien im Export-Verzeichnis die älter als keep_days sind."""
    from datetime import datetime, timedelta
    from pathlib import Path
    p = progress_cb or (lambda m, **kw: None)
    cutoff = datetime.now() - timedelta(days=keep_days)
    removed = 0
    try:
        for f in Path(export_dir).glob("*.xml"):
            if f.stat().st_mtime < cutoff.timestamp():
                f.unlink()
                removed += 1
        if removed:
            p(f"Export-Cleanup: {removed} veraltete XML-Dateien gelöscht "
              f"(älter als {keep_days} Tage)", tag="dim")
    except Exception as exc:
        log.warning(f"Export-Cleanup Fehler: {exc}")


_SQL_CHUNK_SIZE = 500   # SQLite-Limit für IN(...)-Variablen


def _track_export_date(con, product_ids: list[str]):
    """Schreibt last_export_date in die articles-Tabelle."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(articles)")]
        if 'last_export_date' not in cols:
            con.execute("ALTER TABLE articles ADD COLUMN last_export_date TEXT")
        for i in range(0, len(product_ids), _SQL_CHUNK_SIZE):
            chunk = product_ids[i:i + _SQL_CHUNK_SIZE]
            placeholders = ','.join('?' * len(chunk))
            con.execute(
                f"UPDATE articles SET last_export_date=? "
                f"WHERE product_id IN ({placeholders})",
                [now] + chunk)
        con.commit()
    except Exception as exc:
        log.warning(f"last_export_date Fehler: {exc}")


def _check_price_delta(con, pid: str, new_price) -> str | None:
    """
    Vergleicht neuen Preis mit zuletzt exportiertem Preis.
    Gibt Warnungstext zurück wenn Änderung > 200%, sonst None.
    """
    if not isinstance(new_price, (int, float)) or new_price <= 0:
        return None
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(articles)")]
        if 'last_exported_price' not in cols:
            con.execute(
                "ALTER TABLE articles ADD COLUMN last_exported_price REAL")
            con.commit()
            return None
        row = con.execute(
            "SELECT last_exported_price FROM articles WHERE product_id=?",
            (pid,)).fetchone()
        if not row or row[0] is None:
            return None
        old_price = row[0]
        if old_price <= 0:
            return None
        ratio = new_price / old_price
        if ratio > 3.0 or ratio < 0.33:
            pct = int((ratio - 1) * 100)
            sign = "+" if pct > 0 else ""
            return (f"Preisdelta {pid}: {old_price:.2f} € → {new_price:.2f} € "
                    f"({sign}{pct} %) – bitte prüfen")
    except Exception as exc:
        log.debug(f"Preisdelta-Check Fehler: {exc}")
    return None


def _update_exported_price(con, product_ids_prices: list[tuple]):
    """Schreibt last_exported_price für die exportierten Artikel."""
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(articles)")]
        if 'last_exported_price' not in cols:
            con.execute(
                "ALTER TABLE articles ADD COLUMN last_exported_price REAL")
        for pid, price in product_ids_prices:
            con.execute(
                "UPDATE articles SET last_exported_price=? WHERE product_id=?",
                (price, pid))
        con.commit()
    except Exception as exc:
        log.warning(f"last_exported_price Fehler: {exc}")


def export_changed(db_path: str, base_dir: str, export_dir: str,
                   date_from: str, date_to: str,
                   supplier_name: str = None,
                   article_ids: list = None,
                   progress_cb: Callable = None) -> dict:
    """
    Exportiert Artikel als VENDOSYS_CAT XML.
    article_ids: wenn gesetzt, werden genau diese Artikel exportiert
                 (gefilterter Export aus dem Viewer).
                 Sonst: alle im Zeitraum geänderten Artikel.
    """
    p = progress_cb or (lambda m, **kw: None)

    os.makedirs(export_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')

    # Export-Cleanup: Dateien älter als EXPORT_KEEP_DAYS Tage löschen
    _cleanup_export_dir(export_dir, keep_days=7, progress_cb=p)

    # Atomarer Export: erst in Staging-Verzeichnis schreiben,
    # dann nach Abschluss in Ziel-Verzeichnis verschieben
    staging_dir = os.path.join(export_dir, f"_staging_{ts}")
    os.makedirs(staging_dir, exist_ok=True)

    con        = open_db(db_path)
    udx_map    = _load_udx_fields(base_dir)
    post        = PostProcessor(base_dir)
    remap_rules = _load_catalog_remap(base_dir)
    prefix_map  = _load_prefix_map(base_dir)

    if article_ids is not None:
        p(f"DB-Export: exportiere {len(article_ids)} gefilterte Artikel ...")
        articles = query_by_ids(con, article_ids)
    else:
        p(f"DB-Export: lade geänderte Artikel ({date_from} – {date_to}) ...")
        articles = query_changed(con, date_from, date_to, supplier_name)
    # Catalog-Node-IDs anreichern
    for art in articles:
        row = con.execute(
            "SELECT catalog_node_id FROM article_catalog_map WHERE article_id=?",
            (art['id'],)).fetchone()
        art['_catalog_node_id'] = row['catalog_node_id'] if row else None
    p(f"DB-Export: {len(articles)} Artikel geladen")

    # EAN-Crosslieferant-Deduplizierung
    priority = load_supplier_priority(base_dir)
    articles  = apply_ean_dedup(articles, priority)
    p(f"DB-Export: {len(articles)} Artikel nach EAN-Dedup")

    stats        = {'exported': 0, 'blacklisted': 0, 'errors': 0}
    exported_pids: list[tuple] = []   # (product_id, price_amount)

    total_articles = len(articles)
    progress_step  = max(1, total_articles // 20)   # ~20 Fortschritts-Meldungen

    for idx, art in enumerate(articles, start=1):
        pid = art.get('product_id', 'UNKNOWN')
        if idx % progress_step == 0 or idx == total_articles:
            p(f"DB-Export: {idx:,} / {total_articles:,} Artikel verarbeitet "
              f"({stats['exported']:,} exportiert)".replace(",", "."))
        try:
            processed = post.process(art)
            if processed is None:
                stats['blacklisted'] += 1
                continue

            if processed.get('_price_zero'):
                stats.setdefault('price_zero', 0)
                stats['price_zero'] += 1
            # Preisdelta-Warnung
            new_price = processed.get('price_amount')
            delta_warn = _check_price_delta(con, pid, new_price)
            if delta_warn:
                p(f"⚠ {delta_warn}", tag="warn")
                stats.setdefault('price_delta_warnings', 0)
                stats['price_delta_warnings'] += 1

            xml_content = _render_article(processed, udx_map, con=con, remap_rules=remap_rules, prefix_map=prefix_map)
            filename    = f"{pid}_{ts}.xml"
            out_path    = os.path.join(staging_dir, filename)

            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(xml_content)

            exported_pids.append((pid, new_price))
            stats['exported'] += 1
        except Exception as exc:
            log.warning(f"Export-Fehler {pid}: {exc}")
            stats['errors'] += 1

    # Staging → Ziel verschieben (atomar auf demselben Volume)
    import glob as _glob
    moved_files = []
    if stats['errors'] == 0 or stats['exported'] > 0:
        for src_file in _glob.glob(os.path.join(staging_dir, "*.xml")):
            dst_file = os.path.join(export_dir, os.path.basename(src_file))
            os.replace(src_file, dst_file)
            moved_files.append(dst_file)
    try:
        os.rmdir(staging_dir)
    except Exception:
        pass

    # ZIP-Archiv aus den frisch exportierten Dateien bauen, Einzeldateien löschen
    zip_path = None
    if moved_files:
        import zipfile
        zip_path = os.path.join(export_dir, f"export_{ts}.zip")
        p(f"DB-Export: packe {len(moved_files):,} Dateien → "
          f"{os.path.basename(zip_path)} ...".replace(",", "."))
        try:
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for f in moved_files:
                    zf.write(f, arcname=os.path.basename(f))
            for f in moved_files:
                os.remove(f)
            p(f"DB-Export: ZIP erstellt ({os.path.getsize(zip_path) / 1024 / 1024:.1f} MB)",
              tag='ok')
        except Exception as exc:
            log.warning(f"ZIP-Erstellung fehlgeschlagen: {exc}")
            p(f"⚠ ZIP-Erstellung fehlgeschlagen, Einzeldateien bleiben liegen: {exc}",
              tag='warn')
            zip_path = None

    # last_export_date + last_exported_price in DB schreiben
    if exported_pids:
        pids_only = [p for p, _ in exported_pids]
        _track_export_date(con, pids_only)
        _update_exported_price(con, exported_pids)

    stats['zip_path'] = zip_path
    p(f"DB-Export abgeschlossen: {stats['exported']} Dateien → {export_dir}",
      tag='ok')
    if stats['blacklisted']:
        p(f"  Blacklist: {stats['blacklisted']} Artikel übersprungen", tag='dim')
    if stats['errors']:
        p(f"  Fehler: {stats['errors']}", tag='warn')
    if stats.get('price_zero', 0):
        p(f"  ⚠ {stats['price_zero']} Artikel mit Preis ≤ 0 – prüfen!", tag='warn')
    if stats.get('price_delta_warnings', 0):
        p(f"  ⚠ {stats['price_delta_warnings']} Preissprünge > 200 % – prüfen!",
          tag='warn')

    return stats
