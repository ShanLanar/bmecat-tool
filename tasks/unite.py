# tasks/unite.py – Mercateo-Unite Tasks
#
# Preis-Update: aktualisiert die ARTICLE_PRICE[net_list]-Knoten im BME-1.2-
# Katalog aus BASE_DIR (Dateiname z.B. "kaenguruh und bunte ware 2026-08-26.xml")
# mit Preisen aus dem ERP (MySQL, Preislisten MERCATEO_PRICE_LIST_NRS) und lädt
# den aktualisierten Katalog anschließend zu Mercateo-Unite hoch (gleiches Ziel
# wie availability-data-catalog-32WQS.csv / 32WQS_conditionsfile.csv).
#
# WICHTIG: liegt bewusst in BASE_DIR statt in_BME – "Aufräumen" löscht
# unconditional jede *.xml/*.csv/*.zip in in_BME, diese Datei ist aber eine
# dauerhaft gepflegte Vorlage (wird bei jedem Lauf weiter angereichert),
# kein Download-Zwischenstand. Gleiche Logik wie Bestand_und_Preise.xlsx
# und eBay-edit-price-quantity-template.csv, die aus demselben Grund
# ebenfalls in BASE_DIR liegen.
#
# ERP-Zugangsdaten: config.CONNECTIONS["erp_mysql"] (Passwort über den
# Konfigurations-Editor in config_user.json setzen, siehe config.py).

import os
from config import (
    BASE_DIR, CONNECTIONS, MERCATEO_PRICE_LIST_NRS, MERCATEO_CATALOG_XML_PATTERN,
)


def run_update_prices(progress_cb=None, file_progress_cb=None) -> dict:
    """Mercateo-Unite: Preise im BME-1.2-Katalog aus dem ERP aktualisieren + hochladen."""
    p  = progress_cb      or (lambda m, **kw: None)
    fp = file_progress_cb or None
    from lib.unite_price_update import (
        find_latest_catalog_xml, fetch_price_list, update_prices_in_xml,
    )

    xml_path = find_latest_catalog_xml(BASE_DIR, MERCATEO_CATALOG_XML_PATTERN)
    if not xml_path:
        p(f"Unite-Preisupdate: keine Datei nach Muster "
          f"'{MERCATEO_CATALOG_XML_PATTERN}' in BASE_DIR gefunden.", tag="warn")
        p("Bitte den BME-1.2-Katalog (z.B. 'kaenguruh und bunte ware "
          "2026-08-26.xml') direkt nach BASE_DIR legen (NICHT in_BME – wird "
          "sonst von 'Aufräumen' gelöscht).", tag="warn")
        return {}

    cfg = CONNECTIONS["erp_mysql"]
    if not cfg.get("host") or not cfg.get("user") or not cfg.get("database"):
        p("Unite-Preisupdate: ERP-Zugangsdaten (CONNECTIONS['erp_mysql']) sind "
          "noch nicht vollständig konfiguriert – bitte über Konfiguration → "
          "Verbindungen eintragen.", tag="warn")
        return {}

    p(f"Unite-Preisupdate: Katalog {os.path.basename(xml_path)}")
    prices = fetch_price_list(cfg, MERCATEO_PRICE_LIST_NRS, progress_cb=p)
    if not prices:
        p("Unite-Preisupdate: keine Preise aus ERP erhalten – abgebrochen.", tag="warn")
        return {}

    result = update_prices_in_xml(xml_path, prices, progress_cb=p)

    from tasks.others import upload_mercateo_files
    upload_mercateo_files([xml_path], progress_cb=p, file_progress_cb=fp)

    return result
