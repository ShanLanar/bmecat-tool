# lib/eclass_intelligence.py – ECLASS-Kategorie-Auflösung aus BMEcat
#
# Liest ECLASS-Klassifikationen (5.x und 9.x) aus den ARTICLE_FEATURES eines
# BMEcat und ermittelt pro Artikel die beste Kategorie.
#
# Priorität:  ECLASS-5 (Endknoten) > ECLASS-9 (Endknoten)
#             > Artikelbezeichnung (Feature) > Feature-Heuristik
#
# Angepasst aus einem Prototyp (multichannel_suite/eclass_intelligence.py):
#   - Streaming via iterparse statt ET.parse() — speichersicher bei 470-MB-XMLs
#   - Namespace-agnostisch (lokaler Tag-Name) — funktioniert mit/ohne xmlns
#   - Version-flexibel: erkennt ECLASS-5.1.4, ECLASS-9.0, ECLASS-9.1 etc.
#   - Schreibt nach channels/ statt hartcodierter Pfade
#
# Herkunft: BMEcat enthält pro Artikel z.B.
#   <ARTICLE_FEATURES>
#     <REFERENCE_FEATURE_SYSTEM_NAME>ECLASS-9.1</REFERENCE_FEATURE_SYSTEM_NAME>
#     <REFERENCE_FEATURE_GROUP_ID>24-23-05-01</REFERENCE_FEATURE_GROUP_ID>
#   </ARTICLE_FEATURES>

import csv
import logging
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

_NS_RE = re.compile(r"\{[^}]*\}")
# Erste Zahl nach "ECLASS" bestimmt die Generation (5 oder 9)
_ECLASS_GEN_RE = re.compile(r"ECLASS[^0-9]*(\d+)", re.IGNORECASE)

# Features, die bei fehlendem ECLASS zur Disambiguierung helfen
_HINT_FEATURES = ("Farbe", "Größe", "Material", "Gewicht", "Breite", "Länge", "Tiefe")


def _local(tag: str) -> str:
    """Lokaler Tag-Name ohne Namespace ({http://...}ARTICLE → ARTICLE)."""
    return _NS_RE.sub("", tag)


def _iter_local(elem, name: str):
    """Iteriert alle Nachfahren mit passendem lokalem Tag-Namen."""
    for child in elem.iter():
        if _local(child.tag) == name:
            yield child


def _first_text(elem, name: str) -> str:
    """Text des ersten Nachfahren mit passendem lokalem Tag-Namen."""
    for child in elem.iter():
        if _local(child.tag) == name:
            return (child.text or "").strip()
    return ""


def _eclass_generation(system_name: str) -> int | None:
    """ECLASS-5.1.4 → 5, ECLASS-9.1 → 9, sonst None."""
    m = _ECLASS_GEN_RE.search(system_name or "")
    return int(m.group(1)) if m else None


# ── Hierarchie / Endknoten-Erkennung ──────────────────────────────────────────

def _leaf_nodes(ids: set) -> tuple[set, set]:
    """
    Bestimmt aus einer Menge vorkommender ECLASS-IDs alle Ebenen und Endknoten.

    ECLASS-Struktur: 24-23-05-01
      24 = Segment, 24-23 = Hauptgruppe, 24-23-05 = Gruppe, 24-23-05-01 = Klasse.
    Ein Knoten ist Endknoten, wenn keine längere ID ihn als Präfix hat.

    Returns: (alle_ebenen, endknoten)
    """
    all_levels: set = set()
    for cid in ids:
        parts = cid.split("-")
        for i in range(1, len(parts) + 1):
            all_levels.add("-".join(parts[:i]))

    # Jeder echte Präfix-Vorfahre ist ein Nicht-Endknoten
    non_leaf: set = set()
    for lid in all_levels:
        parts = lid.split("-")
        for i in range(1, len(parts)):
            non_leaf.add("-".join(parts[:i]))

    return all_levels, (all_levels - non_leaf)


# ── Ergebnis-Datenmodell ──────────────────────────────────────────────────────

@dataclass
class ArticleCategory:
    supplier_aid: str
    eclass_5_id: str = ""
    eclass_5_leaf: bool = False
    eclass_9_id: str = ""
    eclass_9_leaf: bool = False
    br_category: str = ""           # aus Feature "Artikelbezeichnung"
    br_category_type: str = ""      # aus Feature "Artikeltypbezeichnung"
    fallback_category: str = ""
    fallback_reason: str = ""
    resolution_method: str = "unknown"  # eclass_5|eclass_9|br_category|fallback
    confidence: float = 0.0


_CSV_HEADER = [
    "SUPPLIER_AID", "ECLASS_5_ID", "ECLASS_5_ENDKNOTEN",
    "ECLASS_9_ID", "ECLASS_9_ENDKNOTEN",
    "BR_KATEGORIE", "BR_TYP", "FALLBACK", "GRUND", "METHODE", "KONFIDENZ",
]


def _row(cat: ArticleCategory) -> list:
    return [
        cat.supplier_aid,
        cat.eclass_5_id,
        "Ja" if cat.eclass_5_leaf else "Nein",
        cat.eclass_9_id,
        "Ja" if cat.eclass_9_leaf else "Nein",
        cat.br_category,
        cat.br_category_type,
        cat.fallback_category,
        cat.fallback_reason,
        cat.resolution_method,
        f"{cat.confidence:.0%}",
    ]


# ── Analyse einer einzelnen BMEcat-Datei ──────────────────────────────────────

def _empty_stats() -> dict:
    return {
        "total": 0, "by_method": {},
        "high": 0, "medium": 0, "low": 0,
        "both_eclass": 0, "only_5": 0, "only_9": 0, "no_eclass": 0,
    }


def _collect_eclass_ids(xml_path: str) -> dict:
    """Pass 1: sammelt vorkommende ECLASS-IDs je System-Name (Streaming)."""
    versions: dict[str, set] = {}
    for _ev, elem in ET.iterparse(xml_path, events=("end",)):
        if _local(elem.tag) != "ARTICLE":
            continue
        for af in _iter_local(elem, "ARTICLE_FEATURES"):
            sysname = _first_text(af, "REFERENCE_FEATURE_SYSTEM_NAME")
            gid     = _first_text(af, "REFERENCE_FEATURE_GROUP_ID")
            if sysname and gid:
                versions.setdefault(sysname, set()).add(gid)
        elem.clear()
    return versions


def _resolve_article(article) -> ArticleCategory:
    """Liest ECLASS-IDs + Features eines ARTICLE-Elements (ohne Leaf-Wertung)."""
    aid = _first_text(article, "SUPPLIER_AID")
    cat = ArticleCategory(supplier_aid=aid)
    cat._sys5 = ""   # interner Merker für Leaf-Prüfung
    cat._sys9 = ""

    features: dict[str, str] = {}
    for af in _iter_local(article, "ARTICLE_FEATURES"):
        sysname = _first_text(af, "REFERENCE_FEATURE_SYSTEM_NAME")
        gid     = _first_text(af, "REFERENCE_FEATURE_GROUP_ID")
        if sysname and gid:
            gen = _eclass_generation(sysname)
            if gen == 5:
                cat.eclass_5_id, cat._sys5 = gid, sysname
            elif gen == 9:
                cat.eclass_9_id, cat._sys9 = gid, sysname
        for feat in _iter_local(af, "FEATURE"):
            fname  = _first_text(feat, "FNAME")
            fvalue = _first_text(feat, "FVALUE")
            if fname:
                features[fname] = fvalue

    cat.br_category      = features.get("Artikelbezeichnung", "")
    cat.br_category_type = features.get("Artikeltypbezeichnung", "")
    cat._features = features
    return cat


def _grade(cat: ArticleCategory, leaves: dict):
    """Setzt Leaf-Flags, Auflösungsmethode und Konfidenz."""
    if cat.eclass_5_id and cat.eclass_5_id in leaves.get(cat._sys5, set()):
        cat.eclass_5_leaf = True
    if cat.eclass_9_id and cat.eclass_9_id in leaves.get(cat._sys9, set()):
        cat.eclass_9_leaf = True

    if cat.eclass_5_leaf:
        cat.resolution_method, cat.confidence = "eclass_5", 1.0
    elif cat.eclass_9_leaf:
        cat.resolution_method, cat.confidence = "eclass_9", 1.0
    elif cat.br_category:
        cat.fallback_category = cat.br_category
        cat.fallback_reason   = "no_eclass_leaf"
        cat.resolution_method, cat.confidence = "fallback", 0.7
    else:
        hint = _disambiguate(cat._features)
        if hint:
            cat.fallback_category = hint
            cat.fallback_reason   = "feature_based"
            cat.resolution_method, cat.confidence = "fallback", 0.5


def _disambiguate(features: dict) -> str:
    """Baut aus Merkmal-Features einen Kategorie-Hinweis."""
    hints = [features.get("Artikelbezeichnung", "")]
    hints += [f"{k}: {features[k]}" for k in _HINT_FEATURES if features.get(k)]
    hints = [h for h in hints if h]
    return " | ".join(hints) if len(hints) > 1 else ""


def _tally(stats: dict, cat: ArticleCategory):
    stats["total"] += 1
    m = cat.resolution_method
    stats["by_method"][m] = stats["by_method"].get(m, 0) + 1
    if   cat.confidence >= 0.8: stats["high"]   += 1
    elif cat.confidence >= 0.5: stats["medium"] += 1
    else:                       stats["low"]    += 1
    if   cat.eclass_5_id and cat.eclass_9_id: stats["both_eclass"] += 1
    elif cat.eclass_5_id:                     stats["only_5"]      += 1
    elif cat.eclass_9_id:                     stats["only_9"]      += 1
    else:                                     stats["no_eclass"]   += 1


def analyze_bmecat(xml_path: str, writer, stats: dict) -> int:
    """
    Analysiert eine BMEcat-Datei und schreibt eine Zeile je Artikel in `writer`.
    Aggregiert Kennzahlen in `stats`. Gibt die Artikelanzahl zurück.

    Speichersicher: zwei Streaming-Durchläufe (iterparse), kein Full-Load.
    """
    # Pass 1: ECLASS-IDs sammeln und Endknoten je System-Name bestimmen
    versions = _collect_eclass_ids(xml_path)
    leaves   = {sysname: _leaf_nodes(ids)[1] for sysname, ids in versions.items()}

    # Pass 2: pro Artikel auflösen und streamen
    count = 0
    for _ev, elem in ET.iterparse(xml_path, events=("end",)):
        if _local(elem.tag) != "ARTICLE":
            continue
        cat = _resolve_article(elem)
        if cat.supplier_aid:
            _grade(cat, leaves)
            writer.writerow(_row(cat))
            _tally(stats, cat)
            count += 1
        elem.clear()
    return count


# ── Endknoten-Nutzung aus dem Artikel-CSV sammeln ─────────────────────────────

def collect_leaf_usage(csv_path: str) -> dict:
    """
    Liest channels/article_eclass_categories.csv und sammelt die tatsächlich
    aufgelösten ECLASS-Endknoten (Methode eclass_5/eclass_9).

    Returns:
        {eclass_id: {"eclass_version", "count", "example", "eclass_name"}}
        Nur Artikel mit echtem ECLASS-Endknoten; Fallback/unknown wird ignoriert.
    """
    usage: dict = {}
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            method = (row.get("METHODE") or "").strip()
            if method == "eclass_5":
                eid, ver = (row.get("ECLASS_5_ID") or "").strip(), "ECLASS-5"
            elif method == "eclass_9":
                eid, ver = (row.get("ECLASS_9_ID") or "").strip(), "ECLASS-9"
            else:
                continue
            if not eid:
                continue

            u = usage.get(eid)
            name = (row.get("BR_KATEGORIE") or "").strip()
            if u is None:
                usage[eid] = {
                    "eclass_version": ver,
                    "count":          1,
                    "example":        (row.get("SUPPLIER_AID") or "").strip(),
                    "eclass_name":    name,
                }
            else:
                u["count"] += 1
                if not u["eclass_name"] and name:
                    u["eclass_name"] = name
    return usage


# ── Task-Einstieg ─────────────────────────────────────────────────────────────

def run(progress_cb=None):
    """
    Task: ECLASS-Kategorien aus allen BMEcat-XMLs in in_BME auflösen.

    Schreibt channels/article_eclass_categories.csv (eine Zeile je Artikel)
    und meldet eine Statistik (Konfidenz, ECLASS-Abdeckung, Methoden).
    """
    p = progress_cb or (lambda m, **kw: None)
    import config as _cfg

    in_bme       = _cfg.DIRS["in_bme"]
    channels_dir = os.path.join(_cfg.BASE_DIR, "channels")
    os.makedirs(channels_dir, exist_ok=True)
    out_csv = os.path.join(channels_dir, "article_eclass_categories.csv")

    if not os.path.isdir(in_bme):
        p(f"ECLASS: Verzeichnis fehlt: {in_bme}", tag="warn")
        return

    xmls = sorted(
        os.path.join(in_bme, f) for f in os.listdir(in_bme)
        if f.lower().endswith(".xml")
    )
    if not xmls:
        p(f"ECLASS: keine XML-Dateien in {in_bme} gefunden.", tag="warn")
        return

    p(f"ECLASS-Analyse: {len(xmls)} XML-Datei(en) ...")
    stats = _empty_stats()
    analyzed_files = 0

    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(_CSV_HEADER)

        for xml_path in xmls:
            name = os.path.basename(xml_path)
            try:
                n = analyze_bmecat(xml_path, writer, stats)
                if n:
                    p(f"  {name}: {n} Artikel", tag="dim")
                    analyzed_files += 1
                else:
                    p(f"  {name}: keine Artikel/ECLASS", tag="dim")
            except ET.ParseError as e:
                p(f"  {name}: XML-Fehler übersprungen ({e})", tag="warn")
            except Exception as e:
                p(f"  {name}: Fehler übersprungen ({e})", tag="warn")

    if stats["total"] == 0:
        p("ECLASS: keine Artikel analysiert.", tag="warn")
        return

    total = stats["total"]
    with_5 = stats["only_5"] + stats["both_eclass"]
    with_9 = stats["only_9"] + stats["both_eclass"]
    p(f"ECLASS-Analyse abgeschlossen: {total} Artikel aus "
      f"{analyzed_files} Datei(en) → {os.path.basename(out_csv)}", tag="ok")
    p(f"  ECLASS-5: {with_5} | ECLASS-9: {with_9} | "
      f"beide: {stats['both_eclass']} | ohne: {stats['no_eclass']}")
    p(f"  Konfidenz – hoch: {stats['high']}, "
      f"mittel: {stats['medium']}, niedrig: {stats['low']}")
    for method, cnt in sorted(stats["by_method"].items(),
                              key=lambda x: x[1], reverse=True):
        p(f"    {method:12} {cnt:>7}  ({100*cnt/total:4.1f} %)", tag="dim")
    if stats["no_eclass"]:
        p(f"  ⚠ {stats['no_eclass']} Artikel ohne ECLASS – "
          f"per Feature-Fallback kategorisiert.", tag="dim")
