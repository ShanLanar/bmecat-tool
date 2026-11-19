# lib/category_tree.py – Kategoriebäume aus custom_categories.csv (Shop-Export)
#
# custom_categories.csv ist der Kategorien-Export des Shops (VENDOSYS):
# alle Bäume in einer Datei – der eigene Zentralshop-Baum (numerische Codes)
# und die importierten Lieferantenbäume (BRG…, SOC…, NDW…), mit
#   category_code          Code (bei Lieferanten: Präfix + GROUP_ID des BMEcat)
#   original_name/parent   wie geliefert
#   name/parent            aktueller Stand im Shop (umbenannt / umgehängt)
#   online                 1/0
#   product_category_code  ZIEL: die Artikel dieser Kategorie werden im Shop in
#                          dieser (anderen) Kategorie gezeigt – das "Ummappen".
#                          Typisch: Lieferantenkategorie → Zentralshop-Kategorie.
#
# Dieses Modul liest/schreibt die Datei verlustfrei (alle Spalten, Reihenfolge,
# Kodierung bleiben) und baut daraus die Baumstruktur samt Artikelzahlen aus
# der Artikel-DB. GUI: lib/kategorien_tab.py.

import csv
import re
import os
import shutil
from datetime import datetime

_FILE = "custom_categories.csv"
_ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")


class Node:
    __slots__ = ("code", "name", "parent", "online", "target", "original_name",
                 "original_parent", "children", "row", "direct", "total", "mapped_in")

    def __init__(self, row: dict):
        self.row = row
        self.code = (row.get("category_code") or "").strip()
        self.name = (row.get("name") or row.get("original_name") or "").strip()
        self.parent = (row.get("parent") or "").strip()
        self.online = (row.get("online") or "1").strip() != "0"
        self.target = (row.get("product_category_code") or "").strip()
        self.original_name = (row.get("original_name") or "").strip()
        self.original_parent = (row.get("original_parent") or "").strip()
        self.children: list = []
        self.direct = 0        # Artikel direkt in dieser Kategorie (DB)
        self.total = 0         # inkl. Unterkategorien
        self.mapped_in = 0     # Artikel, die per Ziel-Mapping hierher kommen (inkl. Unterbaum)

    @property
    def key(self) -> str:
        return self.code.upper()


def load_rows(base_dir: str) -> tuple:
    """Returns (rows, fieldnames, encoding). Fehlt die Datei → ([], [], 'cp1252')."""
    return load_file(os.path.join(base_dir, _FILE))


def load_file(path: str) -> tuple:
    """Beliebige Kategorien-Datei im Shop-Format lesen → (rows, fieldnames, encoding)."""
    if not os.path.exists(path):
        return [], [], "cp1252"
    for enc in _ENCODINGS:
        try:
            with open(path, "r", encoding=enc, errors="strict", newline="") as f:
                reader = csv.DictReader(f, delimiter=";")
                rows = [dict(r) for r in reader]
                fields = list(reader.fieldnames or [])
            if "category_code" not in fields:
                raise ValueError(f"Spalte 'category_code' fehlt in {_FILE}: {fields}")
            return rows, fields, enc
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{_FILE} ist in keiner bekannten Kodierung lesbar")


def save_rows(base_dir: str, rows: list, fieldnames: list, encoding: str,
              logs_dir: str = None) -> str:
    """Schreibt die Datei zurück (gleiche Spalten/Kodierung); Backup nach logs/."""
    return write_file(os.path.join(base_dir, _FILE), rows, fieldnames, encoding, logs_dir)


def write_file(path: str, rows: list, fieldnames: list, encoding: str,
               logs_dir: str = None) -> str:
    """Kategorien-Datei im Shop-Format schreiben (Quoting/Zeilenende wie Shop-Export)."""
    if logs_dir and os.path.exists(path):
        os.makedirs(logs_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(path, os.path.join(logs_dir, f"custom_categories_backup_{ts}.csv"))
    # Zeilenende wie in der Originaldatei (Shop-Export: LF)
    nl = "\n"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if os.path.exists(path):
        with open(path, "rb") as f:
            head = f.read(65536)
        nl = "\r\n" if b"\r\n" in head else "\n"
    tmp = path + ".tmp"
    with open(tmp, "w", encoding=encoding, errors="replace", newline="") as f:
        f.write(";".join(fieldnames) + nl)
        for r in rows:
            f.write(";".join(_quote(r.get(k)) for k in fieldnames) + nl)
    os.replace(tmp, path)
    return path


_NEEDS_QUOTE = re.compile(r'[ ;"\r\n]')   # Shop quotet nur bei Leerzeichen/Trenner/Quote


def _quote(value) -> str:
    """
    Quoting wie im Shop-Export: Felder mit Leerzeichen oder Sonderzeichen in
    Anführungszeichen, reine Wörter/Zahlen nicht – damit die zurückgeschriebene
    Datei bis auf die geänderten Zeilen byteidentisch bleibt.
    """
    s = "" if value is None else str(value)
    if not _NEEDS_QUOTE.search(s):
        return s
    return '"' + s.replace('"', '""') + '"'


def build_tree(rows: list) -> tuple:
    """Returns (nodes {KEY: Node}, roots [Node]) – Reihenfolge wie in der Datei."""
    nodes: dict = {}
    for r in rows:
        n = Node(r)
        if not n.code or n.code.startswith("#"):
            continue
        nodes.setdefault(n.key, n)
    roots = []
    for n in nodes.values():
        pk = n.parent.upper()
        if pk and pk in nodes and pk != n.key:
            nodes[pk].children.append(n)
        else:
            roots.append(n)
    return nodes, roots


def path_of(nodes: dict, code: str, sep: str = "\\") -> str:
    names, seen = [], set()
    k = (code or "").strip().upper()
    while k and k in nodes and k not in seen:
        seen.add(k)
        names.append(nodes[k].name)
        k = nodes[k].parent.upper()
    return sep.join(reversed(names))


def root_of(nodes: dict, code: str):
    k = (code or "").strip().upper()
    seen = set()
    while k in nodes and k not in seen:
        seen.add(k)
        pk = nodes[k].parent.upper()
        if not pk or pk not in nodes:
            return nodes[k]
        k = pk
    return None


def load_article_counts(db_path: str) -> dict:
    """
    {EXPORT_CODE_UPPER: anzahl aktiver Artikel} aus der Artikel-DB.
    Export-Code = Lieferantenpräfix + group_id (wie im VENDOSYS-Export und in
    custom_categories.csv); Präfix = product_id − supplier_pid eines Artikels.
    """
    from lib.article_db import open_db
    counts: dict = {}
    con = open_db(db_path)
    try:
        prefixes = {}
        for r in con.execute("""
            SELECT a.supplier_id, a.product_id, a.supplier_pid
            FROM articles a
            WHERE a.id IN (SELECT MIN(id) FROM articles WHERE active=1 AND supplier_pid<>'' GROUP BY supplier_id)
        """):
            pid, spid = r["product_id"] or "", r["supplier_pid"] or ""
            prefixes[r["supplier_id"]] = pid[:-len(spid)] if spid and pid.endswith(spid) else ""
        for r in con.execute("""
            SELECT n.supplier_id, n.group_id, COUNT(a.id) AS cnt
            FROM catalog_nodes n
            JOIN article_catalog_map m ON m.catalog_node_id = n.id
            JOIN articles a ON a.id = m.article_id AND a.active = 1
            GROUP BY n.id
        """):
            pre = prefixes.get(r["supplier_id"], "")
            gid = (r["group_id"] or "").strip()
            code = gid if (pre and gid.upper().startswith(pre.upper())) else pre + gid
            counts[code.upper()] = counts.get(code.upper(), 0) + int(r["cnt"])
    finally:
        con.close()
    return counts


def apply_counts(nodes: dict, roots: list, counts: dict):
    """direct/total je Knoten setzen; mapped_in = Artikel, die per Ziel hierher gemappt sind."""
    for n in nodes.values():
        n.direct = counts.get(n.key, 0)
        n.total = 0
        n.mapped_in = 0

    def _sum(n: Node) -> int:
        n.total = n.direct + sum(_sum(c) for c in n.children)
        return n.total
    for r in roots:
        _sum(r)

    # Mapping-Ziel: Artikel der Quelle (inkl. Unterbaum) landen im Ziel
    incoming: dict = {}
    for n in nodes.values():
        if n.target and n.target.upper() in nodes and n.target.upper() != n.key:
            incoming[n.target.upper()] = incoming.get(n.target.upper(), 0) + n.total

    def _sum_in(n: Node) -> int:
        n.mapped_in = incoming.get(n.key, 0) + sum(_sum_in(c) for c in n.children)
        return n.mapped_in
    for r in roots:
        _sum_in(r)


def sources_for(nodes: dict, code: str) -> list:
    """Alle Knoten, deren Ziel (product_category_code) == code."""
    k = (code or "").strip().upper()
    return [n for n in nodes.values() if n.target.upper() == k and n.key != k]


def articles_in(db_path: str, code: str, limit: int = 500) -> list:
    """[(product_id, description_short)] der aktiven Artikel direkt in dieser Kategorie."""
    from lib.article_db import open_db
    code = (code or "").strip()
    out = []
    con = open_db(db_path)
    try:
        rows = con.execute("""
            SELECT a.product_id, a.description_short, a.supplier_pid, n.group_id
            FROM catalog_nodes n
            JOIN article_catalog_map m ON m.catalog_node_id = n.id
            JOIN articles a ON a.id = m.article_id AND a.active = 1
            WHERE UPPER(n.group_id) = UPPER(?) OR UPPER(?) LIKE '%' || UPPER(n.group_id)
            ORDER BY a.product_id LIMIT ?
        """, (code, code, limit * 4)).fetchall()
        for r in rows:
            pid, spid, gid = r["product_id"] or "", r["supplier_pid"] or "", r["group_id"] or ""
            pre = pid[:-len(spid)] if spid and pid.endswith(spid) else ""
            export_code = gid if gid.upper().startswith(pre.upper()) else pre + gid
            if export_code.upper() == code.upper():
                out.append((pid, r["description_short"] or ""))
                if len(out) >= limit:
                    break
    finally:
        con.close()
    return out


def diff_rows(old_rows: list, new_rows: list) -> dict:
    """
    Vergleich zweier Kategorien-Dateien (Shop-Format) nach category_code:
    {"added": [codes], "removed": [codes], "target_changed": [(code, alt, neu)],
     "renamed": [(code, alt, neu)], "moved": [(code, alt, neu)]}
    """
    def _idx(rows):
        out = {}
        for r in rows:
            c = (r.get("category_code") or "").strip()
            if c and not c.startswith("#"):
                out.setdefault(c.upper(), r)
        return out
    a, b = _idx(old_rows), _idx(new_rows)
    res = {"added": sorted(set(b) - set(a)), "removed": sorted(set(a) - set(b)),
           "target_changed": [], "renamed": [], "moved": []}
    for k in sorted(set(a) & set(b)):
        ra, rb = a[k], b[k]
        for col, key in (("product_category_code", "target_changed"), ("name", "renamed"),
                         ("parent", "moved")):
            va, vb = (ra.get(col) or "").strip(), (rb.get(col) or "").strip()
            if va != vb:
                res[key].append((rb.get("category_code"), va, vb))
    return res


def changed_targets(old_rows: list, new_rows: list) -> list:
    """Nur die Ziel-Änderungen (für den Export-Hinweis)."""
    return diff_rows(old_rows, new_rows)["target_changed"]


def is_descendant(nodes: dict, code: str, ancestor: str) -> bool:
    """True, wenn code unterhalb von ancestor liegt (oder gleich ist)."""
    k, a, seen = (code or "").upper(), (ancestor or "").upper(), set()
    while k and k in nodes and k not in seen:
        if k == a:
            return True
        seen.add(k)
        k = nodes[k].parent.upper()
    return False


def move_node(nodes: dict, roots: list, code: str, new_parent: str) -> str:
    """
    Knoten (mit Unterbaum) unter new_parent hängen. Returns Fehlertext oder "".
    Ändert Node.parent, row["parent"] und die children-Listen.
    """
    n = nodes.get((code or "").upper())
    t = nodes.get((new_parent or "").upper())
    if not n or not t:
        return "Knoten nicht gefunden."
    if n is t or is_descendant(nodes, t.code, n.code):
        return "Eine Kategorie kann nicht unter sich selbst oder einen eigenen Unterknoten verschoben werden."
    if n.parent.upper() == t.key:
        return ""
    old = nodes.get(n.parent.upper())
    if old and n in old.children:
        old.children.remove(n)
    elif n in roots:
        roots.remove(n)
    n.parent = t.code
    n.row["parent"] = t.code
    t.children.append(n)
    return ""
