# tasks/setup_check.py – Vollständige Setup-Prüfung ohne Netzwerkzugriff
#
# Zeigt auf einen Blick: Git-Stand, Tools, Verbindungen, Pflicht- und
# optionale Dateien, Verzeichnisse, Datenbank und BMEcat-Quelldateien.
# Ideal nach dem Klonen auf einem neuen Rechner oder nach einem Update.

import os
import logging

log = logging.getLogger(__name__)


def _ok(exists):
    return "✓" if exists else "✗ FEHLT"


def _opt(exists):
    return "✓" if exists else "–"


def _tag(exists, required=True):
    if exists:
        return "ok"
    return "warn" if required else "dim"


def run(progress_cb=None):
    from config import BASE_DIR, DIRS, TOOLS, CONNECTIONS, MERGE, AVAILABILITY_FILE
    p = progress_cb or (lambda m, **kw: None)

    p("╔══════════════════════════════════════════════════════════════╗")
    p("║  SETUP-CHECK – Vollständige Umgebungsprüfung                ║")
    p("╚══════════════════════════════════════════════════════════════╝")
    p(f"  Arbeitsverzeichnis: {BASE_DIR}")

    # ── Git-Info ──────────────────────────────────────────────────────────────
    p("")
    p("── Git ─────────────────────────────────────────────────────────")
    try:
        import subprocess
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=BASE_DIR, stderr=subprocess.DEVNULL, text=True).strip()
        commit = subprocess.check_output(
            ["git", "log", "-1", "--format=%h %s"],
            cwd=BASE_DIR, stderr=subprocess.DEVNULL, text=True).strip()
        remote = subprocess.check_output(
            ["git", "remote", "get-url", "origin"],
            cwd=BASE_DIR, stderr=subprocess.DEVNULL, text=True).strip()
        p(f"  Branch:  {branch}", tag="ok")
        p(f"  Commit:  {commit}")
        p(f"  Remote:  {remote}")
    except Exception as e:
        p(f"  Git-Info nicht verfügbar: {e}", tag="dim")

    # ── Tools ────────────────────────────────────────────────────────────────
    p("")
    p("── Tools ───────────────────────────────────────────────────────")
    seven_z  = TOOLS.get("7zip",   "")
    winscp   = TOOLS.get("winscp", "")
    sz_ok    = bool(seven_z)  and os.path.exists(seven_z)
    wsc_ok   = bool(winscp)   and os.path.exists(winscp)
    p(f"  {_ok(sz_ok):<10} 7-Zip    {seven_z}", tag=_tag(sz_ok, required=True))
    p(f"  {_opt(wsc_ok):<10} WinSCP   {winscp}", tag=_tag(wsc_ok, required=False))

    # ── Verbindungen ─────────────────────────────────────────────────────────
    p("")
    p("── Verbindungen (Passwort gesetzt?) ────────────────────────────")
    conn_checks = [
        ("bueroring",            "sftp.bueroring.de",        True),
        ("softcarrier",          "ftp.softcarrier.com",      True),
        ("nordwest",             "filehub.configo.de",       True),
        ("brickfox_bmecat",      "abe.brickfox.net (XML)",   True),
        ("brickfox_csv_erp",     "abe.brickfox.net (ERP)",   True),
        ("brickfox_csv_exchange","abe.brickfox.net (Exch.)", True),
        ("mercateo",             "sftp.unite.services",      False),
        ("allago_images",        "Allago Bilder",            False),
        ("officexl_images",      "OfficeXL Bilder",          False),
        ("systeam",              "ftp.systeam.de",           False),
        ("soennecken",           "ftpshop.soennecken.de",    False),
    ]
    for key, label, required in conn_checks:
        conn = CONNECTIONS.get(key, {})
        has_pw = bool(conn.get("password", "").strip())
        mark   = _ok(has_pw) if required else _opt(has_pw)
        tag    = _tag(has_pw, required)
        p(f"  {mark:<10} {label}", tag=tag)

    # ── Pflicht-Dateien ───────────────────────────────────────────────────────
    p("")
    p("── Pflicht-Dateien (BASE_DIR) ───────────────────────────────────")
    required_files = [
        (MERGE.get("keywords", "keywords_exploded.csv"), "Keywords für Volltextsuche"),
        ("Bestand_und_Preise.xlsx",                      "Excel-Vorlage Bestand+Preis"),
        ("fname_renames.csv",                            "Feature-Namen-Mapping"),
        ("fvalue_renames.csv",                           "Feature-Werte-Mapping"),
    ]
    any_missing = False
    for fname, desc in required_files:
        exists = os.path.exists(os.path.join(BASE_DIR, fname))
        if not exists:
            any_missing = True
        p(f"  {_ok(exists):<10} {fname:<38} {desc}", tag=_tag(exists))

    # ── Optionale Dateien ─────────────────────────────────────────────────────
    p("")
    p("── Optionale Dateien (BASE_DIR) ─────────────────────────────────")
    optional_files = [
        ("custom_categories.csv",          "Eigene Kategorie-Namen"),
        ("postprocess_blacklist.csv",       "Artikel-Blacklist"),
        ("postprocess_prices.csv",          "Preisformeln je Artikel"),
        ("postprocess_price_types.csv",     "Globale Preis-Typ-Regeln"),
        ("postprocess_categories.csv",      "Kategorie-Overrides"),
        ("postprocess_media_global.csv",    "MIME/Referenz-Korrekturen"),
        ("fusage_3_features.csv",           "FUSAGE-Varianten-Features"),
        ("supplier_priority.csv",           "EAN-Dedup Prioritäten"),
        ("channel_category_mapping.csv",    "Kanal-Mapping (Lieferanten-Codes)"),
        ("eclass_channel_mapping.csv",      "Kanal-Mapping (ECLASS)"),
        ("sc_image_patch.csv",              "Softcarrier Bild-Patch (pHash)"),
    ]
    for fname, desc in optional_files:
        exists = os.path.exists(os.path.join(BASE_DIR, fname))
        p(f"  {_opt(exists):<10} {fname:<38} {desc}", tag=_tag(exists, required=False))

    # ── Verzeichnisse ─────────────────────────────────────────────────────────
    p("")
    p("── Verzeichnisse ────────────────────────────────────────────────")
    dir_checks = [
        ("in_bme",   "BMEcat-XMLs und ZIPs"),
        ("in",       "Bilder (JPGs)"),
        ("in2",      "Bilder-ZIPs (Büroring)"),
        ("vertrieb", "Eigene Vertriebsbilder"),
        ("logs",     "Logs und Backups"),
    ]
    for key, desc in dir_checks:
        path   = DIRS.get(key, "")
        exists = bool(path) and os.path.isdir(path)
        p(f"  {_ok(exists):<10} {os.path.basename(path) or key:<22} {path}", tag=_tag(exists))

    from config import EXPORT_DIR
    exp_ok = os.path.isdir(EXPORT_DIR)
    p(f"  {_ok(exp_ok):<10} export_vendosys          {EXPORT_DIR}", tag=_tag(exp_ok))

    # ── Datenbank ─────────────────────────────────────────────────────────────
    p("")
    p("── Datenbank ────────────────────────────────────────────────────")
    from config import DB_PATH
    db_ok   = os.path.exists(DB_PATH)
    db_size = f"{os.path.getsize(DB_PATH) / 1024 / 1024:.1f} MB" if db_ok else "–"
    p(f"  {_opt(db_ok):<10} article_db.sqlite  ({db_size})", tag="ok" if db_ok else "dim")

    # ── BMEcat-Quelldateien ───────────────────────────────────────────────────
    p("")
    p("── BMEcat-Quelldateien (in_BME/) ────────────────────────────────")
    in_bme = DIRS.get("in_bme", "")
    bme_files = [
        (MERGE.get("udx_src",   "bueroring.xml"),        "Büroring ABE + ECLASS", False),
        (MERGE.get("basis_src", "bueroring_basis.xml"),  "Büroring Hauptkatalog", False),
        (MERGE.get("out_file",  "bueroring_merged.xml"), "Büroring Merge-Output", False),
        ("soft-carrier.xml",                              "Softcarrier",           False),
        (AVAILABILITY_FILE,                               "Availability-CSV",      False),
    ]
    for fname, desc, req in bme_files:
        path   = os.path.join(in_bme, fname)
        exists = os.path.exists(path)
        size   = f"{os.path.getsize(path) / 1024 / 1024:.0f} MB" if exists else "–"
        p(f"  {_opt(exists):<10} {fname:<36} {size}", tag="ok" if exists else "dim")

    # ── Zusammenfassung ───────────────────────────────────────────────────────
    p("")
    p("────────────────────────────────────────────────────────────────")
    if not sz_ok:
        p("  ✗ 7-Zip fehlt – Entpacken nicht möglich!", tag="warn")
    if any_missing:
        p("  ✗ Pflichtdateien fehlen – Büroring-Task wird fehlschlagen.", tag="warn")
    missing_pw = [k for k, _, req in conn_checks
                  if req and not CONNECTIONS.get(k, {}).get("password", "").strip()]
    if missing_pw:
        p(f"  ✗ Passwörter fehlen: {', '.join(missing_pw)}", tag="warn")
        p("    → Konfiguration → Verbindungen → Passwörter eintragen", tag="warn")
    if sz_ok and not any_missing and not missing_pw:
        p("  ✓ Alles OK – Tool einsatzbereit.", tag="ok")
    p("────────────────────────────────────────────────────────────────")

    problems = []
    if not sz_ok:
        problems.append("7-Zip fehlt")
    if any_missing:
        problems.append("Pflichtdateien fehlen")
    if missing_pw:
        problems.append(f"Passwörter fehlen ({', '.join(missing_pw)})")
    if problems:
        raise RuntimeError(
            "Setup unvollständig: " + " | ".join(problems) +
            " – Setup-Check abwählen um zu überspringen."
        )
