# lib/eclass_catalog.py – eClass-Katalog-Lookup
#
# Lädt eclass_catalog.csv (erzeugt von tasks/eclass_catalog_scrape.py)
# und bietet Lookup-Funktionen für Code → Name, Hierarchie usw.
#
# Columns in eclass_catalog.csv:
#   version ; code ; name_de ; name_en ; level ; parent_code

import csv
import logging
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

CATALOG_FILENAME = "eclass_catalog.csv"

# Cache: {(catalog_path) → EclassCatalog}
_catalog_cache: dict = {}


class EclassCatalog:
    """
    In-Memory-Lookup für eClass-Codes.
    Bevorzugt die neueste Version wenn mehrere vorhanden.
    """

    def __init__(self, rows: list[dict]):
        # Alle Codes nach Version gruppieren
        self._by_version: dict[str, dict[str, dict]] = {}
        for row in rows:
            v    = row.get("version", "")
            code = row.get("code", "").strip()
            if not code:
                continue
            if v not in self._by_version:
                self._by_version[v] = {}
            self._by_version[v][code] = row

        # Flache Suche über alle Versionen (neueste bevorzugt)
        self._flat: dict[str, dict] = {}
        for v in reversed(sorted(self._by_version)):
            for code, row in self._by_version[v].items():
                if code not in self._flat:
                    self._flat[code] = row

        self.versions = sorted(self._by_version)
        log.info("eClass-Katalog: %d Codes in %d Versionen geladen",
                 len(self._flat), len(self.versions))

    # ── Kernfunktionen ─────────────────────────────────────────────────────────

    def name(self, code: str, lang: str = "de", version: str = None) -> str:
        """
        Gibt Bezeichnung für einen eClass-Code zurück.
        lang: 'de' oder 'en'
        """
        row = self._lookup(code, version)
        if not row:
            return ""
        field = "name_de" if lang == "de" else "name_en"
        return row.get(field, "") or row.get("name_de", "")

    def level(self, code: str) -> str:
        """'24' → 'segment', '24-22' → 'hauptgruppe', …"""
        row = self._lookup(code)
        if row:
            return row.get("level", "")
        depth = code.count("-")
        return {0: "segment", 1: "hauptgruppe", 2: "gruppe", 3: "klasse"}.get(depth, "")

    def parent(self, code: str) -> str:
        """'24-22-09-01' → '24-22-09'"""
        row = self._lookup(code)
        if row:
            return row.get("parent_code", "")
        parts = code.split("-")
        return "-".join(parts[:-1]) if len(parts) > 1 else ""

    def hierarchy(self, code: str, version: str = None) -> list[dict]:
        """
        Gibt die vollständige Hierarchie für einen Code zurück:
        [segment, hauptgruppe, gruppe, klasse] (bis zur Tiefe des Codes).
        Jedes Element: {code, name_de, name_en, level}
        """
        result = []
        parts  = code.split("-")
        for i in range(1, len(parts) + 1):
            partial = "-".join(parts[:i])
            row = self._lookup(partial, version)
            if row:
                result.append({
                    "code":    partial,
                    "name_de": row.get("name_de", ""),
                    "name_en": row.get("name_en", ""),
                    "level":   row.get("level", ""),
                })
            else:
                result.append({"code": partial, "name_de": "", "name_en": "", "level": ""})
        return result

    def enrich(self, code: str, version: str = None) -> dict:
        """
        Gibt vollständige Info für einen Code zurück:
        {code, name_de, name_en, level, parent_code,
         segment_code, segment_name, gruppe_code, gruppe_name, ...}
        Nützlich für DB-Import und Reports.
        """
        row     = self._lookup(code, version) or {}
        hier    = self.hierarchy(code, version)
        result  = dict(row)

        level_names = ["segment", "hauptgruppe", "gruppe", "klasse"]
        for i, entry in enumerate(hier):
            prefix = level_names[i] if i < len(level_names) else f"level{i}"
            result[f"{prefix}_code"] = entry["code"]
            result[f"{prefix}_name"] = entry["name_de"]

        return result

    def search(self, query: str, version: str = None,
               lang: str = "de") -> list[dict]:
        """
        Volltextsuche in Bezeichnungen.
        Gibt bis zu 100 Treffer zurück: [{code, name_de, name_en, level}]
        """
        q      = query.lower()
        field  = "name_de" if lang == "de" else "name_en"
        pool   = self._by_version.get(version, self._flat) if version else self._flat
        hits   = []
        for code, row in pool.items():
            if q in row.get(field, "").lower():
                hits.append(row)
            if len(hits) >= 100:
                break
        return hits

    def known(self) -> bool:
        return bool(self._flat)

    # ── Interner Lookup ────────────────────────────────────────────────────────

    def _lookup(self, code: str, version: str = None) -> dict | None:
        code = code.strip()
        if version:
            return self._by_version.get(version, {}).get(code)
        return self._flat.get(code)


# ── Laden ─────────────────────────────────────────────────────────────────────

def load_catalog(base_dir: str = None) -> EclassCatalog:
    """
    Lädt eclass_catalog.csv aus BASE_DIR.
    Gibt leeres Catalog-Objekt zurück wenn Datei fehlt (kein Crash).
    Cached nach Pfad.
    """
    if base_dir is None:
        try:
            import config as _cfg
            base_dir = _cfg.BASE_DIR
        except Exception:
            base_dir = "."

    csv_path = str(Path(base_dir) / CATALOG_FILENAME)

    if csv_path in _catalog_cache:
        return _catalog_cache[csv_path]

    rows = []
    try:
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f, delimiter=";"))
        log.info("eClass-Katalog geladen: %d Einträge aus %s", len(rows), csv_path)
    except FileNotFoundError:
        log.debug("eClass-Katalog nicht gefunden: %s", csv_path)
    except Exception as e:
        log.warning("eClass-Katalog Ladefehler: %s", e)

    cat = EclassCatalog(rows)
    _catalog_cache[csv_path] = cat
    return cat


def invalidate_cache():
    """Cache leeren (nach erneutem Scrapen)."""
    _catalog_cache.clear()
