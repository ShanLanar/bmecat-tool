# lib/task_registry.py – Task-Definitionen und Ausführungs-Infrastruktur
#
# Ausgelagert aus main.py damit die GUI-Datei schlank bleibt.
# main.py importiert: TASKS, call_task, validate_config

import os
import importlib
import inspect
import logging

log = logging.getLogger(__name__)

# ── Task-Liste ────────────────────────────────────────────────────────────────

TASKS = [
    # ── Vorbereitung ──────────────────────────────────────────────────────────
    {
        "id":      "setup_check",
        "name":    "Setup-Check",
        "desc":    "Git-Stand, Tools, Passwörter, Pflichtdateien und Verzeichnisse prüfen – kein Netzwerkzugriff",
        "fn":      "tasks.setup_check:run",
        "default": True,
        "group":   "Vorbereitung",
    },
    {
        "id":      "cleanup",
        "name":    "Aufräumen",
        "desc":    "Alte XML/CSV/ZIP in in_BME und JPGs in in2 löschen",
        "fn":      "tasks.cleanup:run",
        "default": True,
        "group":   "Vorbereitung",
    },
    {
        "id":      "parallel_download",
        "name":    "Alle Downloads (parallel)",
        "desc":    "Büroring + Softcarrier + Nordwest gleichzeitig herunterladen (~3 Min Ersparnis)",
        "fn":      "tasks.parallel_download:run",
        "default": False,
        "group":   "Vorbereitung",
    },
    # ── Täglich ───────────────────────────────────────────────────────────────
    {
        "id":      "bueroring_bestand",
        "name":    "Büroring – Bestand+Preis",
        "desc":    "Excel patchen + Products/CsvExchange erzeugen + Brickfox-Upload – eigenständig, ohne BMEcat-Download/-Merge/-Upload",
        "fn":      "tasks.bueroring_bestand:run",
        "default": False,
        "group":   "Täglich",
    },
    {
        "id":      "article_rights",
        "name":    "Artikelrechte-Export (Allago + OfficeXL)",
        "desc":    "SKU-Listen je Katalog (AS/WS/WZ/BRG/GREEN/FR/IT) für Allago + OfficeXL erzeugen (Ablösung altes SQL/Velocity)",
        "fn":      "tasks.article_rights:run",
        "default": False,
        "group":   "Täglich",
    },
    {
        "id":      "bestandsdaten",
        "name":    "Bestandsdaten (nur CSV)",
        "desc":    "Availability-CSV aus br-bestand.csv erzeugen (kein FTP)",
        "fn":      "tasks.others:run_bestandsdaten_only",
        "default": False,
        "group":   "Täglich",
    },
    {
        "id":      "ebay_bestand_revise",
        "name":    "eBay – Bestand aus BestandBueroring.csv",
        "desc":    "eBay-edit-price-quantity-template.csv (BASE_DIR) + BestandBueroring.csv (in_BME) einlesen → eBay-Revise_<Datum>.csv (Bestand aktualisiert) + eBay-end_<Datum>.csv (Bestand 0) in BASE_DIR/eBay",
        "fn":      "tasks.ebay:run_bestand_revise",
        "default": False,
        "group":   "Täglich",
    },
    {
        "id":      "unite_price_update",
        "name":    "Mercateo-Unite – Preise aus ERP aktualisieren",
        "desc":    "Preise per SQL aus dem ERP (CONNECTIONS['erp_mysql']) laden und in den BME-1.2-Katalog aus in_BME (z.B. 'kaenguruh und bunte ware *.xml') einpatchen",
        "fn":      "tasks.unite:run_update_prices",
        "default": False,
        "group":   "Täglich",
    },
    # ── Büroring ──────────────────────────────────────────────────────────────
    {
        "id":      "bueroring",
        "name":    "Büroring – Komplett",
        "desc":    "Download + Merge + Keywords + Brickfox-Upload (ohne Bestand+Preis)",
        "fn":      "tasks.bueroring:run",
        "default": True,
        "group":   "Büroring",
    },
    {
        "id":      "bueroring_bilder",
        "name":    "Büroring – Bilder + Dokumente",
        "desc":    "Bilder und Dokumente herunterladen und entpacken (nicht täglich nötig)",
        "fn":      "tasks.bueroring:run_bilder_dokumente",
        "default": False,
        "group":   "Büroring",
    },
    {
        "id":      "bmecat_merge",
        "name":    "Büroring – Merge (manuell)",
        "desc":    "Merge + Keywords ohne Download (Fallback)",
        "fn":      "tasks.bmecat_merge:run",
        "default": False,
        "group":   "Büroring",
    },
    # ── Softcarrier ───────────────────────────────────────────────────────────
    {
        "id":      "softcarrier",
        "name":    "Softcarrier – Komplett",
        "desc":    "Download + Merge (Features/GPSR) + Brickfox-Upload (ohne Bilder)",
        "fn":      "tasks.softcarrier:run",
        "default": True,
        "group":   "Softcarrier",
    },
    {
        "id":      "softcarrier_merge",
        "name":    "Softcarrier – Merge (manuell)",
        "desc":    "TAB-Features + GPSR ohne Download (Fallback)",
        "fn":      "tasks.softcarrier_merge:run",
        "default": False,
        "group":   "Softcarrier",
    },
    {
        "id":      "softcarrier_img_patch",
        "name":    "Softcarrier – Bild-Patch",
        "desc":    "Mehrdeutige MIME_SOURCE auflösen: pHash-Matching lokaler Bild-ZIPs gegen Thumbnails. Einmalig ausführen wenn GRAPHIK-ZIPs vorliegen.",
        "fn":      "tasks.softcarrier_img_patch:run",
        "default": False,
        "group":   "Softcarrier",
    },
    # ── Nordwest ──────────────────────────────────────────────────────────────
    {
        "id":      "nordwest",
        "name":    "Nordwest – Komplett",
        "desc":    "Download + UDX-Konvertierung + KIP-CSV + Brickfox-Upload",
        "fn":      "tasks.nordwest:run",
        "default": True,
        "group":   "Nordwest",
    },
    # ── Systeam ───────────────────────────────────────────────────────────────
    {
        "id":      "systeam",
        "name":    "Systeam – Download",
        "desc":    "BMECAT_137942.ZIP herunterladen und entpacken",
        "fn":      "tasks.systeam:run",
        "default": False,
        "group":   "Systeam",
    },
    # ── Soennecken ────────────────────────────────────────────────────────────
    {
        "id":      "soennecken",
        "name":    "Soennecken – Download",
        "desc":    "BMEcat-XML + Bilder-Archiv herunterladen",
        "fn":      "tasks.others:run_soennecken",
        "default": False,
        "group":   "Soennecken",
    },
    # ── Bilder ────────────────────────────────────────────────────────────────
    {
        "id":      "softcarrier_bilder",
        "name":    "Softcarrier – Bilder (Delta)",
        "desc":    "Nur geänderte Bilder auf Allago + OfficeXL hochladen",
        "fn":      "tasks.softcarrier:run_bilder",
        "default": True,
        "group":   "Bilder",
    },
    # ── Extras ────────────────────────────────────────────────────────────────
    {
        "id":      "pim_export",
        "name":    "PIM-Artikelexport (Softcarrier)",
        "desc":    "PIM-Artikelexport_aktiv.txt / _inaktiv.txt aus der Artikel-DB erzeugen (Ablösung altes PIM)",
        "fn":      "tasks.pim_export:run",
        "default": False,
        "group":   "Extras",
    },
    {
        "id":      "fname_analyse",
        "name":    "FNAME-Analyse",
        "desc":    "Alle FNAMEs aus XMLs extrahieren, Kollisionen prüfen, fname_alle.csv erzeugen",
        "fn":      "tasks.fname_analyse:run",
        "default": False,
        "group":   "Extras",
    },
    {
        "id":      "data_quality",
        "name":    "Datenqualität – Marktplatz-Reifegrad",
        "desc":    "Beschreibungen, GPSR-Herstellerdaten und Bilder über alle Lieferanten prüfen (CSV-Report)",
        "fn":      "tasks.data_quality:run",
        "default": False,
        "group":   "Extras",
    },
    {
        "id":      "cleanup_logs",
        "name":    "Alte Logs löschen",
        "desc":    "Logs + Export-CSVs älter als 30 Tage entfernen",
        "fn":      "tasks.cleanup:cleanup_logs",
        "default": False,
        "group":   "Extras",
    },
    {
        "id":      "sanity_check",
        "name":    "Artikel-Sanity-Check",
        "desc":    "Datenqualität prüfen + Cross-Supplier-Vergleich (EAN/Lücken/Bilder)",
        "fn":      "lib.sanity_check:run_sanity_check",
        "default": False,
        "group":   "Extras",
    },
    {
        "id":      "dashboard",
        "name":    "Cross-Filling Dashboard",
        "desc":    "HTML-Dashboard aus letztem Sanity-Report aktualisieren",
        "fn":      "lib.dashboard:run_dashboard_task",
        "default": False,
        "group":   "Extras",
    },
    {
        "id":      "trend_report",
        "name":    "Lauf-Trend-Report",
        "desc":    "Laufzeit und Fehler der letzten 30 Läufe visualisieren",
        "fn":      "lib.dashboard:run_trend_task",
        "default": False,
        "group":   "Extras",
    },
    {
        "id":      "ki_anreicherung",
        "name":    "KI-Anreicherung",
        "desc":    "Artikeldaten mit Claude-KI verbessern (erfordert AI_ENRICHMENT aktiviert)",
        "fn":      "lib.ai_enrichment:run_ai_enrichment_task",
        "default": False,
        "group":   "Extras",
    },
    # ── Marktplätze ───────────────────────────────────────────────────────────
    {
        "id":      "eclass_analyse",
        "name":    "ECLASS-Analyse",
        "desc":    "ECLASS-5/9-Kategorien je Artikel aus BMEcat auflösen (channels/article_eclass_categories.csv)",
        "fn":      "lib.eclass_intelligence:run",
        "default": False,
        "group":   "Marktplätze",
    },
    {
        "id":      "eclass_catalog_scrape",
        "name":    "eClass-Katalog scrapen",
        "desc":    "Vollständigen eClass-Katalog von eclass.eu laden (alle Versionen, alle Ebenen) → eclass_catalog.csv. Einmalig ausführen. Benötigt Selenium + Chrome.",
        "fn":      "tasks.eclass_catalog_scrape:run",
        "default": False,
        "group":   "Marktplätze",
    },
    {
        "id":      "eclass_channel_map",
        "name":    "ECLASS → Kanal-Mapping",
        "desc":    "ECLASS-Endknoten lieferantenübergreifend zu Marktplatz-Kategorien mappen (nach ECLASS-Analyse)",
        "fn":      "tasks.eclass_channel_map:run",
        "default": False,
        "group":   "Marktplätze",
    },
    {
        "id":      "channel_mapping",
        "name":    "Kanal-Kategorie-Mapping",
        "desc":    "Lieferanten-Kategorien zu Marktplatz-Kanälen mappen (eBay, Kaufland, Conrad, ManoMano, Unite)",
        "fn":      "tasks.channel_mapping:run",
        "default": False,
        "group":   "Marktplätze",
    },
    {
        "id":      "ebay_sku_liste",
        "name":    "eBay – SKU-Liste verarbeiten",
        "desc":    "ebay_sku_liste.csv (Vertrieb) einlesen → automatisch in Neuanlage/Revise/Beenden aufteilen",
        "fn":      "tasks.ebay:run_sku_liste",
        "default": False,
        "group":   "Marktplätze",
    },
    {
        "id":      "ebay_revise_sync",
        "name":    "eBay – Bestand & Preis aktualisieren",
        "desc":    "ebay_revise_download.csv (eBay-eigener Report) einlesen → Bestand/Preis aller aktiven Angebote auffrischen",
        "fn":      "tasks.ebay:run_revise_sync",
        "default": False,
        "group":   "Marktplätze",
    },
    {
        "id":      "ebay_learn_category",
        "name":    "eBay – Kategorie-Mapping aus Altdatei lernen",
        "desc":    "ebay_kategorie_lernen.csv (alte, ausgefüllte Draft-Datei) einlesen → channel_category_mapping.csv (ebay-Spalte) befüllen",
        "fn":      "tasks.ebay:run_learn_category_map",
        "default": False,
        "group":   "Marktplätze",
    },
]

TASK_GROUP_ORDER = {
    "Vorbereitung": 0,
    "Täglich":      1,
    "Büroring":     2,
    "Softcarrier":  3,
    "Nordwest":     4,
    "Systeam":      5,
    "Soennecken":   6,
    "Bilder":       7,
    "Upload":       8,
    "Extras":       9,
    "Marktplätze":  10,
}


# ── Task-Ausführung ───────────────────────────────────────────────────────────

def call_task(fn_spec: str, progress_cb, file_progress_cb=None):
    """Importiert und ruft eine Task-Funktion via 'module:function' Spec auf."""
    module_path, func_name = fn_spec.rsplit(":", 1)
    mod = importlib.import_module(module_path)
    fn  = getattr(mod, func_name)
    sig = inspect.signature(fn)
    if "file_progress_cb" in sig.parameters:
        fn(progress_cb=progress_cb, file_progress_cb=file_progress_cb)
    else:
        fn(progress_cb=progress_cb)


# ── Config-Validierung ────────────────────────────────────────────────────────

def validate_config() -> list[str]:
    """Prüft ob alle benötigten Config-Keys vorhanden sind. Gibt Warnungen zurück."""
    import config
    problems = []

    for key in ("in_bme", "in", "in2", "logs"):
        if key not in config.DIRS:
            problems.append(f"DIRS['{key}'] fehlt")

    if "7zip" not in config.TOOLS:
        problems.append("TOOLS['7zip'] fehlt")
    elif not os.path.exists(config.TOOLS["7zip"]):
        problems.append(f"7-Zip nicht gefunden: {config.TOOLS['7zip']}")

    for key in ("bueroring", "softcarrier", "nordwest", "brickfox_bmecat"):
        if key not in config.CONNECTIONS:
            problems.append(f"CONNECTIONS['{key}'] fehlt")
        else:
            conn = config.CONNECTIONS[key]
            for field in ("host", "user", "password"):
                if not conn.get(field):
                    problems.append(f"CONNECTIONS['{key}']['{field}'] fehlt oder leer")

    return problems


# ── Monkey-Patches für Signatur-Vereinheitlichung ─────────────────────────────
# Wird beim Import dieses Moduls einmalig angewendet.

def apply_patches(run_bestandsdaten_only_fn=None):
    """
    Vereinheitlicht Task-Signaturen. Muss einmalig aus main.py aufgerufen
    werden, nachdem run_bestandsdaten_only dort definiert wurde.
    """
    try:
        import tasks.cleanup as _cleanup_mod
        _orig = _cleanup_mod.cleanup_logs

        def _cleanup_logs_wrapped(progress_cb=None):
            _orig(max_days=30, progress_cb=progress_cb)

        _cleanup_mod.cleanup_logs = _cleanup_logs_wrapped
    except Exception as e:
        log.debug(f"Patch cleanup_logs fehlgeschlagen: {e}")

    if run_bestandsdaten_only_fn is not None:
        try:
            import tasks.others as _others_mod
            _others_mod.run_bestandsdaten_only = run_bestandsdaten_only_fn
        except Exception as e:
            log.debug(f"Patch run_bestandsdaten_only fehlgeschlagen: {e}")
