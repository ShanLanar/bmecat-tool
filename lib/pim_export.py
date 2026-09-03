# lib/pim_export.py – PIM-Artikelexport (Softcarrier) – Ablösung altes PIM
#
# Erzeugt PIM-Artikelexport_aktiv.txt / PIM-Artikelexport_inaktiv.txt im Format
# des abgelösten PIM-Systems (Semikolon-CSV, alle Felder in Anführungszeichen).
#
# Spalten:
#   artikelnummer;prefix;kurztext;langtext;ean;hersteller;hersteller_artnr;
#   lieferzeit;bestelleinheit;inhaltseinheit;verpackungsmenge;preiseinheit;
#   minimalemenge;intervalmenge;kategorie_id;kategorie_name;ober_kategorie_id;
#   ober_kategorie_name;mwst;ek_staffel_1..6;ek_menge_1..6;vk_staffel_1..6;
#   vk_menge_1..6;is_active
#
# EK (net_list) kommt direkt aus article_prices (mehrstufig, siehe Schema v6).
# VK (nrp) wird je EK-Stufe live über postprocess_prices.csv berechnet
# (gleiche Formel-Logik wie im VENDOSYS-Export), nicht separat gespeichert.
#
# is_active: articles.active (1 = im letzten Import gesehen, 0 = aus dem
# BMEcat verschwunden / soft-deleted).

import csv
import logging
import os
from typing import Callable

from lib.article_db import open_db
from lib.db_postprocess import build_price_rule_index, match_price_rule

log = logging.getLogger(__name__)

MAX_TIERS = 6

_COLUMNS = [
    "artikelnummer", "prefix", "kurztext", "langtext", "ean", "hersteller",
    "hersteller_artnr", "lieferzeit", "bestelleinheit", "inhaltseinheit",
    "verpackungsmenge", "preiseinheit", "minimalemenge", "intervalmenge",
    "kategorie_id", "kategorie_name", "ober_kategorie_id", "ober_kategorie_name",
    "mwst",
    "ek_staffel_1", "ek_menge_1", "ek_staffel_2", "ek_menge_2",
    "ek_staffel_3", "ek_menge_3", "ek_staffel_4", "ek_menge_4",
    "ek_staffel_5", "ek_menge_5", "ek_staffel_6", "ek_menge_6",
    "vk_staffel_1", "vk_menge_1", "vk_staffel_2", "vk_menge_2",
    "vk_staffel_3", "vk_menge_3", "vk_staffel_4", "vk_menge_4",
    "vk_staffel_5", "vk_menge_5", "vk_staffel_6", "vk_menge_6",
    "is_active",
]


def _decimal_comma(value) -> str:
    """Formatiert wie das alte PIM: Dezimalpunkt -> Komma. '' bei None/leer."""
    if value is None or value == '':
        return ''
    if isinstance(value, float):
        return f"{value:.2f}".replace('.', ',')
    return str(value).replace('.', ',')


def _tax_to_comma(tax_int) -> str:
    """DB speichert tax als Ganzzahl-Prozent (19). mwst-Spalte im alten
    PIM-Format braucht die Dezimalform mit Komma (0,19)."""
    try:
        return f"{int(tax_int) / 100:.2f}".replace('.', ',')
    except (TypeError, ValueError):
        return ''


def _load_articles(con, product_id_pattern: str) -> list[dict]:
    """Lädt alle Artikel deren product_id auf das Muster passt, inkl. Katalog-Zuordnung."""
    rows = con.execute("""
        SELECT a.id, a.supplier_id, a.supplier_pid, a.product_id, a.ean, a.manufacturer_name,
               a.manufacturer_aid, a.delivery_time, a.order_unit, a.content_unit,
               a.no_cu_per_ou, a.price_quantity, a.quantity_min, a.quantity_interval,
               a.tax, a.active, s.supplier_name,
               acm.catalog_node_id AS _catalog_node_id
        FROM articles a
        JOIN suppliers s ON s.id = a.supplier_id
        LEFT JOIN article_catalog_map acm ON acm.article_id = a.id
        WHERE a.product_id LIKE ?
        ORDER BY a.product_id
    """, (product_id_pattern,)).fetchall()
    return [dict(r) for r in rows]


def _load_catalog_index(con, supplier_ids: set) -> tuple[dict, dict]:
    """
    Lädt alle Catalog-Knoten der beteiligten Lieferanten EINMAL in den Speicher.
    Gibt (by_id, by_supplier_and_group) zurück – vermeidet N+1-Queries beim
    Auflösen der Katalog-Hierarchie pro Artikel.
    """
    by_id: dict = {}
    by_group: dict = {}
    if not supplier_ids:
        return by_id, by_group
    placeholders = ','.join('?' * len(supplier_ids))
    rows = con.execute(
        f"SELECT * FROM catalog_nodes WHERE supplier_id IN ({placeholders})",
        list(supplier_ids)
    ).fetchall()
    for r in rows:
        d = dict(r)
        by_id[d['id']] = d
        by_group[(d['supplier_id'], d['group_id'])] = d
    return by_id, by_group


def _resolve_catalog_path(by_id: dict, by_group: dict, node_id) -> list[dict]:
    """In-Memory-Äquivalent zu get_catalog_path(), ohne DB-Zugriff pro Artikel."""
    node = by_id.get(node_id)
    if not node:
        return []
    path = [node]
    visited = {node['id']}
    cur = node
    while cur.get('parent_group_id') and cur['parent_group_id'] not in ('0', ''):
        parent = by_group.get((cur['supplier_id'], cur['parent_group_id']))
        if not parent or parent['id'] in visited:
            break
        path.insert(0, parent)
        visited.add(parent['id'])
        cur = parent
    return path


def _catalog_names(by_id: dict, by_group: dict, catalog_node_id) -> tuple:
    """Gibt (kategorie_id, kategorie_name, ober_kategorie_id, ober_kategorie_name) zurück."""
    if not catalog_node_id:
        return '', '', '', ''
    path = _resolve_catalog_path(by_id, by_group, catalog_node_id)
    if not path:
        return '', '', '', ''
    if len(path) >= 2:
        leaf, parent = path[-1], path[-2]
        return leaf['group_id'], leaf['name'], parent['group_id'], parent['name']
    leaf = path[0]
    return leaf['group_id'], leaf['name'], leaf['group_id'], leaf['name']


def _load_all_prices(con, product_id_pattern: str) -> dict:
    """
    Lädt ALLE Preisstufen der betroffenen Artikel in EINER Query.
    Gibt {article_id: {price_type: [{'lower_bound','price_amount'}, ...]}} zurück.
    """
    rows = con.execute("""
        SELECT ap.article_id, ap.price_type, ap.lower_bound, ap.price_amount
        FROM article_prices ap
        JOIN articles a ON a.id = ap.article_id
        WHERE a.product_id LIKE ?
        ORDER BY ap.article_id, ap.price_type, ap.lower_bound
    """, (product_id_pattern,)).fetchall()
    result: dict = {}
    for r in rows:
        result.setdefault(r['article_id'], {}).setdefault(r['price_type'], []).append(
            {'lower_bound': r['lower_bound'], 'price_amount': r['price_amount']})
    return result


def _build_row(art: dict, price_rule_exact: dict, price_rule_wildcard: list,
              prices_by_article: dict, cat_by_id: dict, cat_by_group: dict) -> dict:
    pid      = art['supplier_pid']
    prod_id  = art['product_id']
    prefix   = prod_id[:-len(pid)] if pid and prod_id.endswith(pid) else ''

    kat_id, kat_name, ober_id, ober_name = _catalog_names(
        cat_by_id, cat_by_group, art.get('_catalog_node_id'))

    ek_tiers = prices_by_article.get(art['id'], {}).get('net_list', [])[:MAX_TIERS]
    rule = match_price_rule(price_rule_exact, price_rule_wildcard, prod_id, art['supplier_name'])

    row = {
        "artikelnummer":     pid,
        "prefix":            prefix,
        "kurztext":          "",
        "langtext":          "",
        "ean":               art.get('ean', ''),
        "hersteller":        art.get('manufacturer_name', ''),
        "hersteller_artnr":  art.get('manufacturer_aid', ''),
        "lieferzeit":        _decimal_comma(art.get('delivery_time', '')),
        "bestelleinheit":    art.get('order_unit', ''),
        "inhaltseinheit":    art.get('content_unit', ''),
        "verpackungsmenge":  art.get('no_cu_per_ou', ''),
        "preiseinheit":      art.get('price_quantity', ''),
        "minimalemenge":     art.get('quantity_min', ''),
        "intervalmenge":     art.get('quantity_interval', ''),
        "kategorie_id":      kat_id,
        "kategorie_name":    kat_name,
        "ober_kategorie_id": ober_id,
        "ober_kategorie_name": ober_name,
        "mwst":              _tax_to_comma(art.get('tax', 19)),
        "is_active":         str(art.get('active', 1)),
    }

    for i in range(MAX_TIERS):
        n = i + 1
        if i < len(ek_tiers):
            ek_amount = ek_tiers[i]['price_amount']
            ek_lb     = ek_tiers[i]['lower_bound']
            row[f"ek_staffel_{n}"] = _decimal_comma(ek_amount)
            row[f"ek_menge_{n}"]   = str(ek_lb)
        else:
            row[f"ek_staffel_{n}"] = ""
            row[f"ek_menge_{n}"]   = ""

        if n == 1:
            if i < len(ek_tiers) and rule and ek_amount is not None:
                vk_amount = rule['fn'](ek_amount)
                row["vk_staffel_1"] = _decimal_comma(vk_amount)
                row["vk_menge_1"]   = str(ek_lb)
            else:
                row["vk_staffel_1"] = ""
                row["vk_menge_1"]   = ""
        else:
            # Staffeln 2-6 (vk) werden nicht befüllt – auf 0 statt leer.
            row[f"vk_staffel_{n}"] = "0"
            row[f"vk_menge_{n}"]   = "0"

    return row


def export_pim(db_path: str, base_dir: str, out_dir: str,
               product_id_prefix: str = "SOC",
               progress_cb: Callable = None) -> dict:
    """
    Exportiert alle Artikel mit product_id-Präfix `product_id_prefix` (Standard: SOC)
    in zwei Dateien: PIM-Artikelexport_aktiv.txt und PIM-Artikelexport_inaktiv.txt.

    Gibt Statistik zurück: {"aktiv": N, "inaktiv": M, "ohne_preisregel": K}
    """
    p = progress_cb or (lambda m, **kw: None)

    os.makedirs(out_dir, exist_ok=True)
    con = open_db(db_path)

    from lib.db_postprocess import _load_price_rules
    price_rules = _load_price_rules(base_dir)
    price_rule_exact, price_rule_wildcard = build_price_rule_index(price_rules)
    p(f"PIM-Export: {len(price_rules)} Preisformeln geladen "
      f"({len(price_rule_exact)} exakt, {len(price_rule_wildcard)} Wildcard)")

    articles = _load_articles(con, f"{product_id_prefix}%")
    total = len(articles)
    p(f"PIM-Export: {total:,} Artikel mit Präfix '{product_id_prefix}' gefunden".replace(",", "."))

    p("PIM-Export: lade Preisstufen und Katalog-Hierarchie ...")
    prices_by_article = _load_all_prices(con, f"{product_id_prefix}%")
    supplier_ids = {a['supplier_id'] for a in articles}
    cat_by_id, cat_by_group = _load_catalog_index(con, supplier_ids)

    rows_active, rows_inactive = [], []
    no_rule = 0
    progress_step = max(1, total // 20)   # ~20 Fortschritts-Meldungen
    for idx, art in enumerate(articles, start=1):
        if idx % progress_step == 0 or idx == total:
            p(f"PIM-Export: {idx:,} / {total:,} Artikel verarbeitet".replace(",", "."))
        row = _build_row(art, price_rule_exact, price_rule_wildcard, prices_by_article, cat_by_id, cat_by_group)
        if row["vk_staffel_1"] == "":
            no_rule += 1
        if art.get('active', 1):
            rows_active.append(row)
        else:
            rows_inactive.append(row)

    active_path   = os.path.join(out_dir, "PIM-Artikelexport_aktiv.txt")
    inactive_path = os.path.join(out_dir, "PIM-Artikelexport_inaktiv.txt")

    for path, rows in ((active_path, rows_active), (inactive_path, rows_inactive)):
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=_COLUMNS, delimiter=";",
                                     quoting=csv.QUOTE_ALL)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    p(f"PIM-Export: {len(rows_active)} aktiv -> {os.path.basename(active_path)}", tag="ok")
    p(f"PIM-Export: {len(rows_inactive)} inaktiv -> {os.path.basename(inactive_path)}", tag="ok")
    if no_rule:
        p(f"PIM-Export: {no_rule} Artikel ohne passende Preisformel "
          f"(vk-Spalten leer)", tag="warn")

    return {
        "aktiv":           len(rows_active),
        "inaktiv":         len(rows_inactive),
        "ohne_preisregel": no_rule,
        "active_path":     active_path,
        "inactive_path":   inactive_path,
    }
