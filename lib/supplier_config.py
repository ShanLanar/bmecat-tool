# lib/supplier_config.py – Lieferantenkonfiguration aus supplier_config.yaml laden
#
# Lädt supplier_config.yaml, fällt bei Fehler auf config.py-Werte zurück.
# Einstiegspunkt: get_supplier(name) oder get_all_suppliers()

import os
import logging

log = logging.getLogger(__name__)
_cache: dict | None = None


def _yaml_path() -> str:
    try:
        import config
        return os.path.join(config.BASE_DIR, "supplier_config.yaml")
    except Exception:
        return os.path.join(os.path.dirname(__file__), "..", "supplier_config.yaml")


def load_supplier_config() -> dict:
    """Lädt supplier_config.yaml (gecacht für den Lauf)."""
    global _cache
    if _cache is not None:
        return _cache

    path = _yaml_path()
    if not os.path.exists(path):
        log.warning("supplier_config.yaml nicht gefunden: %s", path)
        _cache = {"suppliers": {}}
        return _cache

    try:
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        _cache = data or {"suppliers": {}}
    except ImportError:
        # PyYAML nicht installiert → einfacher Fallback
        log.warning("PyYAML nicht installiert — supplier_config.yaml nicht geladen. "
                    "pip install pyyaml")
        _cache = {"suppliers": {}}
    except Exception as e:
        log.warning("supplier_config.yaml Ladefehler: %s", e)
        _cache = {"suppliers": {}}

    return _cache


def get_supplier(name: str) -> dict:
    """
    Gibt die Konfiguration eines Lieferanten zurück.

    Returns:
        dict mit allen Feldern oder {} wenn Lieferant nicht bekannt.
    """
    cfg = load_supplier_config()
    return cfg.get("suppliers", {}).get(name, {})


def get_all_suppliers() -> dict:
    """Gibt alle konfigurierten Lieferanten zurück."""
    return load_supplier_config().get("suppliers", {})


def get_enabled_suppliers() -> dict:
    """Gibt nur aktive Lieferanten zurück."""
    return {k: v for k, v in get_all_suppliers().items()
            if v.get("enabled", True)}


def get_min_articles(supplier: str, xml_file: str = None) -> int:
    """
    Gibt die Mindest-Artikelzahl für einen Lieferanten zurück.
    Fällt auf ARTICLE_THRESHOLDS in config.py zurück.
    """
    # Zuerst supplier_config.yaml
    sup = get_supplier(supplier)
    if sup and "min_articles" in sup:
        return sup["min_articles"]

    # Fallback: config.py ARTICLE_THRESHOLDS (nach Dateiname)
    if xml_file:
        try:
            import config
            return getattr(config, "ARTICLE_THRESHOLDS", {}).get(xml_file, 0)
        except Exception:
            pass

    return 0


def get_category_prefix(supplier: str) -> str:
    """Gibt den Kategorie-Präfix für einen Lieferanten zurück (z.B. 'BRG')."""
    sup = get_supplier(supplier)
    return sup.get("prefix", supplier.upper()[:3])
