# lib/unite_price_update.py – Mercateo-Unite: Preise im BME-1.2-Katalog aktualisieren
#
# Liest Preise per SQL aus dem ERP (MySQL) und patcht damit die ARTICLE_PRICE-
# Knoten (price_type="net_list") im vorhandenen BME-1.2-Katalog-XML aus in_BME,
# ohne den Rest der Datei (Struktur, andere Preistypen, Formatierung) anzufassen.

import os
import re
import glob
import shutil

_PRICE_LIST_SQL = """\
SELECT DISTINCT a.a_bestnr1 AS supplier_aid
    , mw.MW_SATZ/100 AS tax
    , min(pl_vk1) AS price_amount
    , 'EUR' AS currency
    , '1' AS lower_bound
    , 'net_list' AS price_type
FROM arti_pl AS pl
    JOIN artikel AS a ON a.A_NR = pl.PL_ARTNR
    JOIN s_mwst AS mw ON mw.MW_NR = a.A_MWSTSCHL
WHERE pl.PL_NR IN ({placeholders})
GROUP BY a.a_bestnr1
"""

_ARTICLE_RE = re.compile(r"<ARTICLE\b.*?</ARTICLE>", re.DOTALL)
_AID_RE = re.compile(r"<SUPPLIER_AID>(.*?)</SUPPLIER_AID>", re.DOTALL)
_NET_LIST_PRICE_RE = re.compile(
    r'(<ARTICLE_PRICE\s+price_type="net_list"[^>]*>)(.*?)(</ARTICLE_PRICE>)',
    re.DOTALL,
)
_PRICE_AMOUNT_RE = re.compile(r"(<PRICE_AMOUNT>)(.*?)(</PRICE_AMOUNT>)", re.DOTALL)
_TAX_RE = re.compile(r"(<TAX>)(.*?)(</TAX>)", re.DOTALL)


def find_latest_catalog_xml(in_dir: str, pattern: str) -> str | None:
    """Findet die neueste Katalog-XML in in_BME (Dateiname trägt ein Datum)."""
    files = glob.glob(os.path.join(in_dir, pattern))
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def fetch_price_list(conn_cfg: dict, price_list_nrs, progress_cb=None) -> dict:
    """
    Holt die Preisliste(n) aus dem ERP (MySQL) und liefert
    {supplier_aid: {"price_amount": float, "tax": float, "currency": "EUR"}}.
    Bei mehreren Preislisten-Nummern gewinnt je Artikel der niedrigste Preis
    (MIN(pl_vk1), serverseitig per GROUP BY).
    """
    p = progress_cb or (lambda m, **kw: None)
    import pymysql

    if isinstance(price_list_nrs, (int, str)):
        price_list_nrs = [price_list_nrs]
    placeholders = ", ".join(["%s"] * len(price_list_nrs))
    sql = _PRICE_LIST_SQL.format(placeholders=placeholders)

    con = pymysql.connect(
        host=conn_cfg["host"],
        user=conn_cfg["user"],
        password=conn_cfg["password"],
        database=conn_cfg["database"],
        port=int(conn_cfg.get("port", 3306)),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with con.cursor() as cur:
            cur.execute(sql, tuple(price_list_nrs))
            rows = cur.fetchall()
    finally:
        con.close()

    prices = {}
    for row in rows:
        aid = str(row["supplier_aid"]).strip()
        if not aid:
            continue
        prices[aid] = {
            "price_amount": row["price_amount"],
            "tax": row["tax"],
            "currency": row.get("currency", "EUR"),
        }

    nrs_str = ", ".join(str(n) for n in price_list_nrs)
    p(f"Unite-Preisupdate: {len(prices)} Preise aus ERP-Preisliste(n) {nrs_str} geladen.")
    return prices


def update_prices_in_xml(xml_path: str, prices: dict, progress_cb=None) -> dict:
    """
    Patcht PRICE_AMOUNT/TAX der ARTICLE_PRICE[price_type="net_list"]-Knoten je
    Artikel (Match über SUPPLIER_AID). Artikel ohne passenden net_list-Preis-
    knoten im XML werden übersprungen (kein Neuanlegen von Knoten), damit die
    Katalogstruktur unangetastet bleibt.

    Returns:
        dict: {"updated": n, "not_in_prices": n, "no_price_node": n, "total_articles": n}
    """
    p = progress_cb or (lambda m, **kw: None)

    with open(xml_path, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()

    updated = 0
    not_in_prices = 0
    no_price_node = 0
    total = 0

    def _patch_article(match: re.Match) -> str:
        nonlocal updated, not_in_prices, no_price_node, total
        block = match.group(0)
        total += 1

        aid_match = _AID_RE.search(block)
        aid = aid_match.group(1).strip() if aid_match else ""
        if not aid or aid not in prices:
            not_in_prices += 1
            return block

        price = prices[aid]
        price_str = f'{float(price["price_amount"]):.2f}'
        tax_str = f'{float(price["tax"]):.2f}' if price.get("tax") is not None else None

        price_match = _NET_LIST_PRICE_RE.search(block)
        if not price_match:
            no_price_node += 1
            return block

        node = price_match.group(0)
        node = _PRICE_AMOUNT_RE.sub(lambda m: f"{m.group(1)}{price_str}{m.group(3)}", node, count=1)
        if tax_str is not None:
            node = _TAX_RE.sub(lambda m: f"{m.group(1)}{tax_str}{m.group(3)}", node, count=1)

        updated += 1
        return block[:price_match.start()] + node + block[price_match.end():]

    new_raw = _ARTICLE_RE.sub(_patch_article, raw)

    backup_path = xml_path + ".bak"
    shutil.copy2(xml_path, backup_path)
    with open(xml_path, "w", encoding="utf-8") as f:
        f.write(new_raw)

    p(f"Unite-Preisupdate: {updated} von {total} Artikeln im Katalog aktualisiert "
      f"({not_in_prices} ohne ERP-Preis, {no_price_node} ohne net_list-Preisknoten). "
      f"Backup: {os.path.basename(backup_path)}", tag="ok")

    return {
        "updated": updated,
        "not_in_prices": not_in_prices,
        "no_price_node": no_price_node,
        "total_articles": total,
    }
