# config.py – Zentrale Konfiguration für BMEcat Download-Tool
# Alle Pfade und Zugangsdaten hier anpassen.

import os
import sys

# ── Basispfad ──────────────────────────────────────────────────────────────────
# Automatisch: Verzeichnis der Exe (kompiliert) oder von config.py (Skript-Modus).
# Alle Arbeitsverzeichnisse (in_BME/, logs/, etc.) werden darin angelegt.
# Kein manuelles Anpassen nötig — Tool einfach irgendwo entpacken und starten.
if getattr(sys, "frozen", False):
    # PyInstaller-Exe: __file__ zeigt ins Temp-Verzeichnis (_MEI...), nicht zur Exe.
    # sys.executable ist der tatsaechliche Pfad der .exe.
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Datenbank & Export ────────────────────────────────────────────────────────
DB_PATH    = os.path.join(BASE_DIR, "article_db.sqlite")
EXPORT_DIR = os.path.join(BASE_DIR, "export_vendosys")

DIRS = {
    "in":         os.path.join(BASE_DIR, "in"),
    "in2":        os.path.join(BASE_DIR, "in2"),
    "in_bme":     os.path.join(BASE_DIR, "in_BME"),
    "vertrieb":   os.path.join(BASE_DIR, "in_vertrieb"),
    "logs":       os.path.join(BASE_DIR, "logs"),
    "sql":        os.path.join(BASE_DIR, "sql"),
    "unzip":      os.path.join(BASE_DIR, "unzip"),
    "pim_export": os.path.join(BASE_DIR, "pim_export"),
    "article_rights": os.path.join(BASE_DIR, "export_artikelrechte"),
    "brickfox":   os.path.join(BASE_DIR, "brickfox"),
    "ndw_share":  r"\\obs.abe-brands.de\OBS\data\DOWNLOADS\780104811",
    "pim_export_mgmt_share": r"\\mgmt.abe-brands.de\daten\06_Alle\Austausch\S.Berlin",
    "pim_export_obs_share":  r"\\obs.abe-brands.de\obs\data\DOWNLOADS\780102150",
}

TOOLS = {
    "7zip":   r"C:\Program Files\7-Zip\7z.exe",
    "winscp": r"C:\Program Files (x86)\WinSCP\WinSCP.com",
}

# ── FTP / SFTP Zugangsdaten ────────────────────────────────────────────────────
# Passwörter hier LEER lassen — sie werden über den Konfigurations-Editor
# in config_user.json gespeichert (gitignored).
# Beim ersten Start: Konfiguration → Verbindungen → Passwörter eintragen.

CONNECTIONS = {
    "bueroring": {
        "host":     "sftp.bueroring.de",
        "user":     "400446-w",
        "password": "",
        "protocol": "sftp",
        "port":     22,
    },
    "nordwest": {
        "host":     "filehub.configo.de",
        "user":     "abe_admin",
        "password": "",
        "protocol": "sftp",
        "port":     22,
    },
    "softcarrier": {
        "host":     "ftp.softcarrier.com",
        "user":     "ABE-GmbH",
        "password": "",
        "protocol": "ftp",
        "port":     21,
    },
    "systeam": {
        "host":     "ftp.systeam.de",
        "user":     "137942",
        "password": "",
        "protocol": "ftp",
        "port":     21,
    },
    "soennecken": {
        "host":     "ftpshop.soennecken.de",
        "user":     "3637700",
        "password": "",
        "protocol": "sftp",
        "port":     22,
    },
    "allago_images": {
        "host":     "217.71.221.27",
        "user":     "wwwadmin",
        "password": "",
        "protocol": "ftp",
        "port":     21,
        "remote_path_thumbs":    "/sites/images/allago/thumbnails/generate/",
        "remote_path_category":  "/sites/images/allago/category/",
        "remote_path_products":  "/sites/products/catalog_products/",
        "remote_path_documents": "/sites/product_files/",
    },
    "officexl_images": {
        "host":     "217.71.221.26",
        "user":     "wwwadmin",
        "password": "",
        "protocol": "ftp",
        "port":     21,
        "remote_path_thumbs":    "/sites/images/officexl/thumbnails/generate/",
        "remote_path_category":  "/sites/images/officexl/category/",
        "remote_path_products":  "/sites/products/catalog_products/",
        "remote_path_documents": "/sites/product_files/",
    },
    "mercateo": {
        "host":     "sftp.unite.services",
        "user":     "KaenguruhDE",
        "password": "",
        "protocol": "sftp",
        "port":     22,
        "remote_path": "/catalog/32WQS/",
    },
    "backup": {
        "host":     "",
        "user":     "",
        "password": "",
        "protocol": "sftp",
        "port":     22,
        "remote_path": "/",
        "_comment": "Ziel für Backup/Restore (config_user.json, .fernet.key, "
                    "article_db.sqlite, live editierte Config-CSVs – alles was "
                    "nicht in Git liegt). Für Server-Umzug per FTP.",
    },
    "erp_mysql": {
        "host":     "",
        "user":     "",
        "password": "",
        "database": "",
        "protocol": "mysql",
        "port":     3306,
        "_comment": "ERP-DB für Preisabgleich Mercateo-Unite (Preislisten MERCATEO_PRICE_LIST_NRS)",
    },
    "brickfox_bmecat": {
        "host":     "abe.brickfox.net",
        "user":     "c_abe_ftp_2",
        "password": "",
        "protocol": "ftp",
        "port":     21,
        "remote_path": "/incoming",
        "_comment": "BMEcat-XMLs → Brickfox /incoming",
    },
    "brickfox_csv_erp": {
        "host":     "abe.brickfox.net",
        "user":     "c_abe_ftp_3",
        "password": "",
        "protocol": "ftp",
        "port":     21,
        "remote_path": "/incoming",
        "_comment": "Nur v_stock, v_price – schneller ERP-Import",
    },
    "brickfox_csv_exchange": {
        "host":     "abe.brickfox.net",
        "user":     "c_abe_ftp_5",
        "password": "",
        "protocol": "ftp",
        "port":     21,
        "remote_path": "/incoming",
        "_comment": "Stammdaten, Attribute, Kanalzuweisung – langsamer",
    },
}

# ── Statische Artikel für Bestandsdaten (aus PS1 portiert) ────────────────────
# Vollständige Liste in lib/bestandsdaten.py
AVAILABILITY_FILE   = "availability-data-catalog-32WQS.csv"

# ── Mercateo-Unite: Preislisten im ERP für Preis-Update im BME-1.2-Katalog ────
MERCATEO_PRICE_LIST_NRS = [601307, 471153]
# Dateiname des BME-1.2-Katalogs in in_BME (Datum wechselt) – Suchmuster für Task
MERCATEO_CATALOG_XML_PATTERN = "kaenguruh und bunte ware *.xml"

# ── BMEcat-Merge ──────────────────────────────────────────────────────────────
MERGE = {
    "udx_src":   r"bueroring.xml",           # ABE-Datei (UDX + ECLASS-Features)
    "basis_src": r"bueroring_basis.xml",     # Hauptkatalog
    "out_file":  r"bueroring_merged.xml",    # Ausgabe
    "keywords":  r"keywords_exploded.csv",   # Keywords-Tabelle (relativ zu BASE_DIR)
}

# ── ATP-Bestandsdaten (OBS-Archiv) ────────────────────────────────────────────
# Netzwerkpfad zum Archivverzeichnis mit 102_atp*.zip-Dateien
ATP_ARCHIVE_DIR = r"\\obs.abe-brands.de\OBS\data\VERFUG\Archiv"

# ── KI-Anreicherung (optional) ────────────────────────────────────────────────
AI_ENRICHMENT = {
    "enabled":        False,    # Gesamt-Schalter
    "model":          "claude-haiku-4-5-20251001",
    "max_articles":   200,      # max. Artikel pro Lauf (Kostenkontrolle)
    "min_desc_len":   20,       # Kurzbeschreibungen kürzer → Kandidat
    "tasks": {
        "improve_desc_short": True,
        "improve_desc_long":  True,
        "normalize_mfr":      True,
        "suggest_keywords":   True,
    }
}

# ── BFSG-Barrierefreiheit (optional) ─────────────────────────────────────────
# Einzelne Schritte per True/False steuerbar
BFSG = {
    "enabled":          False,  # Gesamt-Schalter — auf True setzen zum Aktivieren
    "alt_text":         True,   # MIME_ALT aus DESCRIPTION_SHORT befüllen
    "clean_desc_short": True,   # AID-Suffix wie "(CASFX87DEX)" aus Titeln entfernen
    "remove_html":      True,   # &lt;br&gt; und HTML-Tags aus DESCRIPTION_LONG
    "foreign_keywords": False,  # Fremdsprachige Keywords entfernen (langdetect nötig)
}
# Auf enabled=True setzen und SMTP-Daten eintragen um nach jedem Lauf
# eine Zusammenfassung per Mail zu erhalten (Standard: nur bei Fehlern).
NOTIFICATION = {
    "enabled":    False,
    "smtp_host":  "smtp.example.com",
    "smtp_port":  587,
    "smtp_user":  "",
    "smtp_pass":  "",
    "smtp_tls":   True,
    "from":       "bmecat-tool@abe-brands.de",
    "to":         ["admin@abe-brands.de"],
    "on_success": False,          # True = auch bei fehlerfreiem Lauf senden
}

# ── Artikel-Schwellwerte für XML-Validierung ──────────────────────────────────
# Warnung wenn die Artikelanzahl in einer Datei unter diesen Wert fällt.
ARTICLE_THRESHOLDS = {
    "bueroring_merged.xml":    20000,
    "soft-carrier_merge.xml":  60000,
    "arbeitsschutz.xml":        5000,
    "werkstatt.xml":           10000,
    "werkzeugtechnik.xml":     40000,
}
