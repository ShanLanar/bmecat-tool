# lib/article_db.py – Artikel-Datenbank (SQLite)
#
# Normalisiertes Schema mit Änderungsverfolgung.
# Jeder Import-Lauf aktualisiert content_hash + last_seen.
# Geänderte Artikel erhalten ein neues last_changed-Datum.

import hashlib
import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

log = logging.getLogger(__name__)

SCHEMA_VERSION = 5


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── Schema ────────────────────────────────────────────────────────────────────

DDL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS suppliers (
    id               INTEGER PRIMARY KEY,
    supplier_name    TEXT NOT NULL,
    supplier_code    TEXT DEFAULT '',
    supplier_aid     TEXT DEFAULT '',
    supplier_alt_aid TEXT DEFAULT '',
    UNIQUE(supplier_name, supplier_code)
);

CREATE TABLE IF NOT EXISTS articles (
    id                          INTEGER PRIMARY KEY,
    supplier_id                 INTEGER NOT NULL REFERENCES suppliers(id),
    supplier_pid                TEXT NOT NULL,
    product_id                  TEXT NOT NULL,
    ean                         TEXT DEFAULT '',
    product_type                TEXT DEFAULT 'SINGLE',
    category                    TEXT DEFAULT '',
    variation_group             TEXT DEFAULT '',
    description_short           TEXT DEFAULT '',
    description_long            TEXT DEFAULT '',
    manufacturer_aid            TEXT DEFAULT '',
    manufacturer_name           TEXT DEFAULT '',
    delivery_time               TEXT DEFAULT '',
    order_unit                  TEXT DEFAULT 'PCE',
    content_unit                TEXT DEFAULT 'PCE',
    content_unit_amount         TEXT DEFAULT '',
    no_cu_per_ou                TEXT DEFAULT '1',
    price_quantity              TEXT DEFAULT '1',
    quantity_min                TEXT DEFAULT '1',
    quantity_interval           TEXT DEFAULT '1',
    deposit                     TEXT DEFAULT '',
    price_type                  TEXT DEFAULT 'net_customer',
    price_amount                REAL,
    price_currency              TEXT DEFAULT 'EUR',
    tax                         INTEGER DEFAULT 19,
    lower_bound                 INTEGER DEFAULT 1,
    valid_start_date            TEXT DEFAULT '',
    valid_end_date              TEXT DEFAULT '',
    online                      INTEGER DEFAULT 1,
    searchable                  INTEGER DEFAULT 1,
    reference_feature_system    TEXT DEFAULT '',
    reference_feature_group_id  TEXT DEFAULT '',
    catalog_group_id            TEXT DEFAULT '',
    catalog_sub_group_id        TEXT DEFAULT '',
    content_hash                TEXT NOT NULL,
    first_seen                  TEXT NOT NULL,
    last_changed                TEXT NOT NULL,
    last_seen                   TEXT NOT NULL,
    UNIQUE(supplier_id, supplier_pid)
);

CREATE TABLE IF NOT EXISTS article_features (
    id          INTEGER PRIMARY KEY,
    article_id  INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    fname       TEXT NOT NULL,
    fvalue      TEXT DEFAULT '',
    funit       TEXT DEFAULT '',
    fusage      INTEGER DEFAULT 1,
    forder      INTEGER DEFAULT 0,
    fsearchable INTEGER DEFAULT 1,
    fselectable INTEGER DEFAULT 0,
    value_index INTEGER DEFAULT 0   -- bei Multi-Value-Features: 0, 1, 2, ...
);

CREATE TABLE IF NOT EXISTS article_mimes (
    id           INTEGER PRIMARY KEY,
    article_id   INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    mime_type    TEXT DEFAULT '',
    mime_source  TEXT DEFAULT '',
    mime_purpose TEXT DEFAULT '',
    mime_desc    TEXT DEFAULT '',
    mime_alt     TEXT DEFAULT '',
    mime_order   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS article_keywords (
    id          INTEGER PRIMARY KEY,
    article_id  INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    keyword     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS article_references (
    id          INTEGER PRIMARY KEY,
    article_id  INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    ref_type    TEXT DEFAULT 'similar',
    art_id_to   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS article_udx (
    id          INTEGER PRIMARY KEY,
    article_id  INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    key         TEXT NOT NULL,
    value       TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_art_product_id   ON articles(product_id);
CREATE INDEX IF NOT EXISTS idx_art_ean          ON articles(ean);
CREATE INDEX IF NOT EXISTS idx_art_last_changed ON articles(last_changed);
CREATE INDEX IF NOT EXISTS idx_art_supplier     ON articles(supplier_id);
CREATE INDEX IF NOT EXISTS idx_feat_article     ON article_features(article_id);
CREATE INDEX IF NOT EXISTS idx_mime_article     ON article_mimes(article_id);
CREATE INDEX IF NOT EXISTS idx_udx_article      ON article_udx(article_id);
CREATE INDEX IF NOT EXISTS idx_kw_article       ON article_keywords(article_id);
CREATE INDEX IF NOT EXISTS idx_ref_article      ON article_references(article_id);

CREATE TABLE IF NOT EXISTS catalog_nodes (
    id              INTEGER PRIMARY KEY,
    supplier_id     INTEGER NOT NULL REFERENCES suppliers(id),
    group_id        TEXT NOT NULL,
    parent_group_id TEXT DEFAULT '',
    name            TEXT DEFAULT '',
    description     TEXT DEFAULT '',
    node_order      INTEGER DEFAULT 0,
    node_type       TEXT DEFAULT 'node',
    last_updated    TEXT NOT NULL,
    UNIQUE(supplier_id, group_id)
);

CREATE TABLE IF NOT EXISTS article_catalog_map (
    id              INTEGER PRIMARY KEY,
    article_id      INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    catalog_node_id INTEGER NOT NULL REFERENCES catalog_nodes(id),
    UNIQUE(article_id)
);

CREATE INDEX IF NOT EXISTS idx_catnode_supplier ON catalog_nodes(supplier_id);
CREATE INDEX IF NOT EXISTS idx_catnode_parent   ON catalog_nodes(supplier_id, parent_group_id);
CREATE INDEX IF NOT EXISTS idx_artcat_article   ON article_catalog_map(article_id);
CREATE INDEX IF NOT EXISTS idx_artcat_node      ON article_catalog_map(catalog_node_id);
"""


# ── Verbindung ────────────────────────────────────────────────────────────────

def open_db(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    con = sqlite3.connect(db_path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    # Performance-PRAGMAs MÜSSEN VOR DDL gesetzt werden (nicht innerhalb Transaction)
    con.execute("PRAGMA synchronous  = NORMAL")    # sicher mit WAL, ~3-5× schnellere Writes
    con.execute("PRAGMA cache_size   = -65536")    # 64 MB Page-Cache
    con.execute("PRAGMA mmap_size    = 268435456") # 256 MB Memory-Mapped I/O
    con.execute("PRAGMA temp_store   = MEMORY")    # Temp-Tabellen im RAM
    con.executescript(DDL)
    _migrate(con)
    con.commit()
    return con


def _migrate(con: sqlite3.Connection):
    row = con.execute("SELECT version FROM schema_version").fetchone()
    current = row["version"] if row else 0
    if current < 4:
        # v4: catalog_nodes + article_catalog_map
        con.executescript("""
            CREATE TABLE IF NOT EXISTS catalog_nodes (
                id INTEGER PRIMARY KEY, supplier_id INTEGER NOT NULL,
                group_id TEXT NOT NULL, parent_group_id TEXT DEFAULT '',
                name TEXT DEFAULT '', description TEXT DEFAULT '',
                node_order INTEGER DEFAULT 0, node_type TEXT DEFAULT 'node',
                last_updated TEXT NOT NULL,
                UNIQUE(supplier_id, group_id));
            CREATE TABLE IF NOT EXISTS article_catalog_map (
                id INTEGER PRIMARY KEY,
                article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
                catalog_node_id INTEGER NOT NULL,
                UNIQUE(article_id));
            CREATE INDEX IF NOT EXISTS idx_catnode_supplier ON catalog_nodes(supplier_id);
            CREATE INDEX IF NOT EXISTS idx_catnode_parent   ON catalog_nodes(supplier_id, parent_group_id);
            CREATE INDEX IF NOT EXISTS idx_artcat_article   ON article_catalog_map(article_id);
        """)
    if current < 3:
        # v3: funit + value_index in article_features
        cols = [r[1] for r in con.execute("PRAGMA table_info(article_features)").fetchall()]
        if "funit" not in cols:
            con.execute("ALTER TABLE article_features ADD COLUMN funit TEXT DEFAULT ''")
        if "value_index" not in cols:
            con.execute("ALTER TABLE article_features ADD COLUMN value_index INTEGER DEFAULT 0")
    if current < 5:
        # v5: fehlende Indizes für Stale-Cleanup, Keyword-Suche, Hersteller-Filter
        con.executescript("""
            CREATE INDEX IF NOT EXISTS idx_art_last_seen
                ON articles(supplier_id, last_seen);
            CREATE INDEX IF NOT EXISTS idx_kw_keyword
                ON article_keywords(keyword);
            CREATE INDEX IF NOT EXISTS idx_art_manufacturer
                ON articles(manufacturer_name);
            CREATE INDEX IF NOT EXISTS idx_artcat_node
                ON article_catalog_map(catalog_node_id);
        """)
    con.execute("DELETE FROM schema_version")
    con.execute("INSERT INTO schema_version VALUES (?)", (SCHEMA_VERSION,))


@contextmanager
def transaction(con: sqlite3.Connection):
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise


# ── Catalog-Baum ─────────────────────────────────────────────────────────────

def upsert_catalog_node(con, supplier_id: int, group_id: str,
                         parent_group_id: str = '', name: str = '',
                         description: str = '', node_order: int = 0,
                         node_type: str = 'node',
                         preserve_structure: bool = True) -> int:
    """
    Legt Catalog-Knoten an oder aktualisiert ihn. Gibt id zurück.
    preserve_structure=True (Standard): parent_group_id wird bei Updates NICHT
    überschrieben — manuelle Umstrukturierungen bleiben erhalten.
    preserve_structure=False: vollständiger Overwrite inkl. parent_group_id.
    """
    now = _now()
    existing = con.execute(
        "SELECT id FROM catalog_nodes WHERE supplier_id=? AND group_id=?",
        (supplier_id, group_id)).fetchone()
    if existing:
        if preserve_structure:
            con.execute(
                "UPDATE catalog_nodes SET name=?, description=?, "
                "node_order=?, node_type=?, last_updated=? WHERE id=?",
                (name, description, node_order, node_type, now, existing["id"]))
        else:
            con.execute(
                "UPDATE catalog_nodes SET parent_group_id=?, name=?, description=?, "
                "node_order=?, node_type=?, last_updated=? WHERE id=?",
                (parent_group_id, name, description, node_order, node_type, now, existing["id"]))
        return existing["id"]
    cur = con.execute(
        "INSERT INTO catalog_nodes(supplier_id, group_id, parent_group_id, name, "
        "description, node_order, node_type, last_updated) VALUES (?,?,?,?,?,?,?,?)",
        (supplier_id, group_id, parent_group_id, name, description, node_order, node_type, now))
    return cur.lastrowid


def assign_article_catalog(con, article_id: int, catalog_node_id: int):
    """Ordnet Artikel einem Catalog-Knoten zu (ersetzt bestehende Zuordnung)."""
    con.execute(
        "INSERT OR REPLACE INTO article_catalog_map(article_id, catalog_node_id) VALUES (?,?)",
        (article_id, catalog_node_id))


def get_catalog_node(con, supplier_id: int, group_id: str) -> dict | None:
    row = con.execute(
        "SELECT * FROM catalog_nodes WHERE supplier_id=? AND group_id=?",
        (supplier_id, group_id)).fetchone()
    return dict(row) if row else None


def get_catalog_path(con, catalog_node_id: int) -> list[dict]:
    """Gibt den Pfad von Root bis zum Knoten zurück: [root, ..., node]."""
    path = []
    node = con.execute("SELECT * FROM catalog_nodes WHERE id=?",
                        (catalog_node_id,)).fetchone()
    if not node:
        return []
    path.insert(0, dict(node))
    visited = {node["id"]}
    while node["parent_group_id"] and node["parent_group_id"] not in ("0", ""):
        parent = con.execute(
            "SELECT * FROM catalog_nodes WHERE supplier_id=? AND group_id=?",
            (node["supplier_id"], node["parent_group_id"])).fetchone()
        if not parent or parent["id"] in visited:
            break
        path.insert(0, dict(parent))
        visited.add(parent["id"])
        node = parent
    return path


def get_catalog_tree(con, supplier_id: int) -> list[dict]:
    """Gibt alle Catalog-Knoten für einen Lieferanten zurück, sortiert nach Ebene."""
    rows = con.execute(
        "SELECT * FROM catalog_nodes WHERE supplier_id=? ORDER BY node_order, name",
        (supplier_id,)).fetchall()
    return [dict(r) for r in rows]


def rename_catalog_node(con, catalog_node_id: int, new_name: str):
    """Benennt einen Catalog-Knoten um."""
    con.execute("UPDATE catalog_nodes SET name=?, last_updated=? WHERE id=?",
                (new_name, _now(), catalog_node_id))


def move_catalog_node(con, catalog_node_id: int, new_parent_group_id: str):
    """Verschiebt einen Catalog-Knoten unter einen anderen Elternknoten."""
    con.execute(
        "UPDATE catalog_nodes SET parent_group_id=?, last_updated=? WHERE id=?",
        (new_parent_group_id, _now(), catalog_node_id))


def reassign_articles_to_node(con, from_node_id: int, to_node_id: int):
    """Verschiebt alle Artikel von einem Catalog-Knoten zu einem anderen."""
    con.execute(
        "UPDATE article_catalog_map SET catalog_node_id=? WHERE catalog_node_id=?",
        (to_node_id, from_node_id))


def get_article_catalog_node(con, article_id: int) -> dict | None:
    """Gibt den Catalog-Knoten für einen Artikel zurück."""
    row = con.execute(
        "SELECT cn.* FROM article_catalog_map acm "
        "JOIN catalog_nodes cn ON cn.id = acm.catalog_node_id "
        "WHERE acm.article_id=?", (article_id,)).fetchone()
    return dict(row) if row else None


def catalog_stats(con, supplier_id: int = None) -> dict:
    """Gibt Statistiken über den Katalogbaum zurück."""
    where = "WHERE supplier_id=?" if supplier_id else ""
    params = (supplier_id,) if supplier_id else ()
    total  = con.execute(f"SELECT COUNT(*) FROM catalog_nodes {where}", params).fetchone()[0]
    leaves = con.execute(
        f"SELECT COUNT(*) FROM catalog_nodes {where} {'AND' if supplier_id else 'WHERE'} node_type='leaf'",
        params).fetchone()[0] if supplier_id else con.execute(
        "SELECT COUNT(*) FROM catalog_nodes WHERE node_type='leaf'").fetchone()[0]
    mapped = con.execute("SELECT COUNT(*) FROM article_catalog_map").fetchone()[0]
    return {"nodes": total, "leaves": leaves, "articles_mapped": mapped}


# ── Hashing ───────────────────────────────────────────────────────────────────

def _article_hash(article: dict) -> str:
    """SHA256 über alle inhaltlichen Felder (ohne Tracking-Timestamps)."""
    skip = {"content_hash", "first_seen", "last_changed", "last_seen", "id", "supplier_id"}
    payload = {k: v for k, v in article.items() if k not in skip}
    # Unter-Listen kanonisch sortieren
    for key in ("features", "mimes", "keywords", "references", "udx"):
        if key in payload and isinstance(payload[key], list):
            payload[key] = sorted(
                payload[key],
                key=lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False)
            )
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── Supplier ──────────────────────────────────────────────────────────────────

def get_or_create_supplier(con: sqlite3.Connection,
                            supplier_name: str,
                            supplier_code: str = "",
                            supplier_aid: str = "",
                            supplier_alt_aid: str = "") -> int:
    row = con.execute(
        "SELECT id FROM suppliers WHERE supplier_name=? AND supplier_code=?",
        (supplier_name, supplier_code)
    ).fetchone()
    if row:
        return row["id"]
    cur = con.execute(
        "INSERT INTO suppliers(supplier_name, supplier_code, supplier_aid, supplier_alt_aid) "
        "VALUES (?,?,?,?)",
        (supplier_name, supplier_code, supplier_aid, supplier_alt_aid)
    )
    return cur.lastrowid


# ── Upsert ────────────────────────────────────────────────────────────────────

def upsert_article(con: sqlite3.Connection, supplier_id: int, article: dict) -> tuple[str, int]:
    """
    Fügt Artikel ein oder aktualisiert ihn.
    Gibt zurück: ('new'|'updated'|'unchanged', article_id)
    """
    now = _now()
    article["content_hash"] = _article_hash(article)
    pid = article["supplier_pid"]

    existing = con.execute(
        "SELECT id, content_hash FROM articles WHERE supplier_id=? AND supplier_pid=?",
        (supplier_id, pid)
    ).fetchone()

    if existing:
        if existing["content_hash"] == article["content_hash"]:
            con.execute(
                "UPDATE articles SET last_seen=? WHERE id=?",
                (now, existing["id"])
            )
            return "unchanged", existing["id"]
        # Geändert: Artikel-Hauptzeile aktualisieren
        art_id = existing["id"]
        con.execute("""
            UPDATE articles SET
                product_id=:product_id, ean=:ean, product_type=:product_type,
                category=:category, variation_group=:variation_group,
                description_short=:description_short, description_long=:description_long,
                manufacturer_aid=:manufacturer_aid, manufacturer_name=:manufacturer_name,
                delivery_time=:delivery_time,
                order_unit=:order_unit, content_unit=:content_unit,
                content_unit_amount=:content_unit_amount, no_cu_per_ou=:no_cu_per_ou,
                price_quantity=:price_quantity, quantity_min=:quantity_min,
                quantity_interval=:quantity_interval, deposit=:deposit,
                price_type=:price_type, price_amount=:price_amount,
                price_currency=:price_currency, tax=:tax, lower_bound=:lower_bound,
                valid_start_date=:valid_start_date, valid_end_date=:valid_end_date,
                online=:online, searchable=:searchable,
                reference_feature_system=:reference_feature_system,
                reference_feature_group_id=:reference_feature_group_id,
                catalog_group_id=:catalog_group_id, catalog_sub_group_id=:catalog_sub_group_id,
                content_hash=:content_hash, last_changed=:last_changed, last_seen=:last_seen
            WHERE id=:id
        """, {**article, "last_changed": now, "last_seen": now, "id": art_id})
        status = "updated"
    else:
        cur = con.execute("""
            INSERT INTO articles(
                supplier_id, supplier_pid, product_id, ean, product_type,
                category, variation_group, description_short, description_long,
                manufacturer_aid, manufacturer_name, delivery_time,
                order_unit, content_unit, content_unit_amount, no_cu_per_ou,
                price_quantity, quantity_min, quantity_interval, deposit,
                price_type, price_amount, price_currency, tax, lower_bound,
                valid_start_date, valid_end_date, online, searchable,
                reference_feature_system, reference_feature_group_id,
                catalog_group_id, catalog_sub_group_id,
                content_hash, first_seen, last_changed, last_seen
            ) VALUES (
                :supplier_id, :supplier_pid, :product_id, :ean, :product_type,
                :category, :variation_group, :description_short, :description_long,
                :manufacturer_aid, :manufacturer_name, :delivery_time,
                :order_unit, :content_unit, :content_unit_amount, :no_cu_per_ou,
                :price_quantity, :quantity_min, :quantity_interval, :deposit,
                :price_type, :price_amount, :price_currency, :tax, :lower_bound,
                :valid_start_date, :valid_end_date, :online, :searchable,
                :reference_feature_system, :reference_feature_group_id,
                :catalog_group_id, :catalog_sub_group_id,
                :content_hash, :first_seen, :last_changed, :last_seen
            )
        """, {**article,
              "supplier_id": supplier_id,
              "first_seen": now, "last_changed": now, "last_seen": now})
        art_id = cur.lastrowid
        status = "new"

    # Sub-Tabellen neu schreiben
    for tbl in ("article_features", "article_mimes", "article_keywords",
                "article_references", "article_udx"):
        con.execute(f"DELETE FROM {tbl} WHERE article_id=?", (art_id,))

    for f in article.get("features", []):
        con.execute(
            "INSERT INTO article_features(article_id,fname,fvalue,funit,fusage,forder,fsearchable,fselectable,value_index) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (art_id, f.get("fname",""), f.get("fvalue",""), f.get("funit",""),
             f.get("fusage",1), f.get("forder",0),
             f.get("fsearchable",1), f.get("fselectable",0),
             f.get("value_index",0))
        )
    for m in article.get("mimes", []):
        con.execute(
            "INSERT INTO article_mimes(article_id,mime_type,mime_source,mime_purpose,mime_desc,mime_alt,mime_order) "
            "VALUES (?,?,?,?,?,?,?)",
            (art_id, m.get("mime_type",""), m.get("mime_source",""),
             m.get("mime_purpose",""), m.get("mime_desc",""),
             m.get("mime_alt",""), m.get("mime_order",0))
        )
    for kw in article.get("keywords", []):
        con.execute(
            "INSERT INTO article_keywords(article_id,keyword) VALUES (?,?)",
            (art_id, kw)
        )
    for ref in article.get("references", []):
        con.execute(
            "INSERT INTO article_references(article_id,ref_type,art_id_to) VALUES (?,?,?)",
            (art_id, ref.get("ref_type","similar"), ref.get("art_id_to",""))
        )
    for u in article.get("udx", []):
        con.execute(
            "INSERT INTO article_udx(article_id,key,value) VALUES (?,?,?)",
            (art_id, u.get("key",""), u.get("value",""))
        )
    return status, art_id


# ── Abfragen ──────────────────────────────────────────────────────────────────

def query_changed(con: sqlite3.Connection,
                  date_from: str, date_to: str,
                  supplier_name: str = None) -> list[dict]:
    """
    Gibt alle Artikel zurück, deren last_changed im Zeitraum liegt.
    date_from / date_to: ISO-Strings, z.B. '2026-06-01' oder '2026-06-01T00:00:00+00:00'
    Optionaler Filter: supplier_name
    """
    sql = """
        SELECT a.*, s.supplier_name, s.supplier_code, s.supplier_aid, s.supplier_alt_aid,
               cn.name  AS catalog_node_name,
               cn.group_id AS catalog_node_group_id,
               acm.catalog_node_id AS _catalog_node_id
        FROM articles a
        JOIN suppliers s ON s.id = a.supplier_id
        LEFT JOIN article_catalog_map acm ON acm.article_id = a.id
        LEFT JOIN catalog_nodes cn ON cn.id = acm.catalog_node_id
        WHERE a.last_changed >= ? AND a.last_changed <= ?
    """
    params = [date_from, date_to]
    if supplier_name:
        sql += " AND s.supplier_name = ?"
        params.append(supplier_name)
    sql += " ORDER BY s.supplier_name, a.product_id"

    rows = con.execute(sql, params).fetchall()
    result = []
    for row in rows:
        art = dict(row)
        art_id = art["id"]
        art["features"]   = [dict(r) for r in con.execute(
            "SELECT fname,fvalue,funit,fusage,forder,fsearchable,fselectable,value_index "
            "FROM article_features WHERE article_id=? ORDER BY forder, fname, value_index", (art_id,))]
        art["mimes"]      = [dict(r) for r in con.execute(
            "SELECT mime_type,mime_source,mime_purpose,mime_desc,mime_alt,mime_order "
            "FROM article_mimes WHERE article_id=? ORDER BY mime_order", (art_id,))]
        art["keywords"]   = [r["keyword"] for r in con.execute(
            "SELECT keyword FROM article_keywords WHERE article_id=?", (art_id,))]
        art["references"] = [dict(r) for r in con.execute(
            "SELECT ref_type,art_id_to FROM article_references WHERE article_id=?", (art_id,))]
        art["udx"]        = [dict(r) for r in con.execute(
            "SELECT key,value FROM article_udx WHERE article_id=?", (art_id,))]
        result.append(art)
    return result


_SQL_CHUNK_SIZE = 500   # SQLite-Limit für IN(...)-Variablen ist 999 (ältere Versionen) / 32766 (neuere)


def query_by_ids(con: sqlite3.Connection, article_ids: list[int]) -> list[dict]:
    """Lädt Artikel anhand einer ID-Liste (für gefilterten Export aus dem Viewer).
    Große Listen werden in Chunks aufgeteilt (SQLite-Limit für IN(...)-Variablen)."""
    if not article_ids:
        return []

    result = []
    for i in range(0, len(article_ids), _SQL_CHUNK_SIZE):
        chunk = article_ids[i:i + _SQL_CHUNK_SIZE]
        placeholders = ','.join('?' * len(chunk))
        sql = f"""
            SELECT a.*, s.supplier_name, s.supplier_code, s.supplier_aid, s.supplier_alt_aid,
                   cn.name  AS catalog_node_name,
                   cn.group_id AS catalog_node_group_id,
                   acm.catalog_node_id AS _catalog_node_id
            FROM articles a
            JOIN suppliers s ON s.id = a.supplier_id
            LEFT JOIN article_catalog_map acm ON acm.article_id = a.id
            LEFT JOIN catalog_nodes cn ON cn.id = acm.catalog_node_id
            WHERE a.id IN ({placeholders})
            ORDER BY s.supplier_name, a.product_id
        """
        rows = con.execute(sql, chunk).fetchall()
        for row in rows:
            art = dict(row)
            art_id = art["id"]
            art["features"]   = [dict(r) for r in con.execute(
                "SELECT fname,fvalue,funit,fusage,forder,fsearchable,fselectable,value_index "
                "FROM article_features WHERE article_id=? ORDER BY forder, fname, value_index", (art_id,))]
            art["mimes"]      = [dict(r) for r in con.execute(
                "SELECT mime_type,mime_source,mime_purpose,mime_desc,mime_alt,mime_order "
                "FROM article_mimes WHERE article_id=? ORDER BY mime_order", (art_id,))]
            art["keywords"]   = [r["keyword"] for r in con.execute(
                "SELECT keyword FROM article_keywords WHERE article_id=?", (art_id,))]
            art["references"] = [dict(r) for r in con.execute(
                "SELECT ref_type,art_id_to FROM article_references WHERE article_id=?", (art_id,))]
            art["udx"]        = [dict(r) for r in con.execute(
                "SELECT key,value FROM article_udx WHERE article_id=?", (art_id,))]
            result.append(art)
    return result


def stats(con: sqlite3.Connection) -> dict:
    total    = con.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    by_sup   = con.execute(
        "SELECT s.supplier_name, COUNT(*) as n "
        "FROM articles a JOIN suppliers s ON s.id=a.supplier_id "
        "GROUP BY s.supplier_name ORDER BY s.supplier_name"
    ).fetchall()
    return {
        "total": total,
        "by_supplier": {r["supplier_name"]: r["n"] for r in by_sup}
    }
