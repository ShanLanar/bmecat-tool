# lib/bestandsdaten.py – Port von BestandsdatenErzeugen_noxls.ps1
#
# Liest in_BME/br-bestand.csv, fügt statische Artikel hinzu,
# schreibt availability-data-catalog-32WQS.csv.

import csv
import os
import logging

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Statische Artikel (vollständig aus PS1 extrahiert)
# Format: "SUPPLIER_AID;STOCK"
# ──────────────────────────────────────────────────────────────────────────────
# Statische Artikel aus externer CSV geladen (lib/static_articles.csv)
import pathlib as _pl
_STATIC_CSV = _pl.Path(__file__).parent / "static_articles.csv"

def _load_static_articles() -> str:
    """
    Liest static_articles.csv.
    Suchpfade (in dieser Reihenfolge):
      1. BASE_DIR/static_articles.csv  (vom Benutzer pflegbar)
      2. lib/static_articles.csv       (Standardlieferung)
    """
    candidates = [_STATIC_CSV]
    try:
        import config as _cfg
        base = _pl.Path(_cfg.BASE_DIR) / "static_articles.csv"
        candidates = [base, _STATIC_CSV]  # BASE_DIR hat Vorrang
    except Exception:
        pass

    for path in candidates:
        try:
            if path.exists():
                lines = path.read_text(encoding="utf-8").splitlines()
                data_lines = [l for l in lines[1:] if l.strip()]
                return "\n".join(data_lines)
        except Exception:
            continue
    return ""

STATIC_ARTICLES = _load_static_articles()


def erstelle_bestandsdaten(in_bme_dir: str, output_path: str,
                            progress_cb=None) -> str:
    """
    Port von BestandsdatenErzeugen_noxls.ps1.

    - Liest in_BME/br-bestand.csv
    - Schreibt SUPPLIER_AID;STOCK-Zeilen aus CSV + statische Artikel
    - Gibt den Pfad der erzeugten Datei zurück
    """
    csv_path = os.path.join(in_bme_dir, "br-bestand.csv")
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Bestandsdatei nicht gefunden: {csv_path}")

    # Zieldatei ggf. vorher löschen
    if os.path.exists(output_path):
        os.remove(output_path)

    # ── 1. Dynamische Zeilen aus CSV ──────────────────────────────────────────
    # Büroring liefert diese Datei nicht immer als UTF-8 (typisch bei älteren
    # Windows/ERP-Exports: cp1252). Bei hart codiertem UTF-8+errors="replace"
    # werden Umlaute in Artikelnummern (z.B. "HÄF...", "RÖS...") unwiderruflich
    # durch U+FFFD ersetzt, sobald geschrieben ist die Original-ID futsch –
    # solche Artikel matchen dann nie mehr gegen die availability-CSV.
    try:
        with open(csv_path, encoding="utf-8") as f:
            raw = f.readlines()
    except UnicodeDecodeError:
        with open(csv_path, encoding="cp1252", errors="replace") as f:
            raw = f.readlines()

    # Header-Erkennung (identisch zur PS1-Logik)
    if raw and not raw[0].strip().upper().startswith("SUPPLIER_AID;STOCK"):
        raw = ["SUPPLIER_AID;STOCK;OTHER\n"] + raw

    reader = csv.DictReader(
        (r.strip() for r in raw),
        fieldnames=["SUPPLIER_AID", "PRICE_CURRENCY", "OTHER"],
        delimiter=";"
    )
    # Dict statt direkt schreiben: Artikel können sowohl im echten Feed als
    # auch in static_articles.csv stehen (z.B. fixer Bestand für bestimmte
    # Artikel). Ohne Dedup landete die AID doppelt in der Ausgabedatei –
    # abhängig davon, welche Zeile ein Konsument zuerst liest, gewann mal
    # der echte, mal der fixe Bestand. static_articles.csv gewinnt jetzt
    # immer, weil es zuletzt angewendet wird.
    entries: dict[str, str] = {}
    for row in reader:
        aid   = (row.get("SUPPLIER_AID") or "").strip()
        stock = (row.get("PRICE_CURRENCY") or "").strip()
        if aid and stock and aid != "SUPPLIER_AID":
            entries[aid] = stock

    # ── 2. Statische Artikel überschreiben/ergänzen ───────────────────────────
    for line in STATIC_ARTICLES.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        aid, _, stock = line.partition(";")
        if aid and stock:
            entries[aid] = stock

    # ── 3. Bestände auch in der Artikel-DB hinterlegen (für Abgleich) ─────────
    # br-bestand.csv liefert die Artikelnummern OHNE das Präfix "BRG", das
    # supplier_pid in der DB verwendet – daher direkter Match über
    # supplier_pid statt product_id (siehe update_stock() in article_db.py).
    try:
        import config as _cfg
        from lib.article_db import open_db, get_or_create_supplier, update_stock
        if os.path.exists(_cfg.DB_PATH):
            con = open_db(_cfg.DB_PATH)
            supplier_id = get_or_create_supplier(con, "Büroring")
            n = update_stock(con, supplier_id, entries)
            con.close()
            if progress_cb:
                progress_cb(f"Bestände in DB aktualisiert: {n} Artikel (Büroring)")
    except Exception as e:
        log.warning(f"Bestand-DB-Update übersprungen: {e}")
        if progress_cb:
            progress_cb(f"Bestand-DB-Update übersprungen: {e}", tag="warn")

    with open(output_path, "w", encoding="utf-8", newline="") as out:
        out.write("SUPPLIER_AID;STOCK\n")
        for aid, stock in entries.items():
            out.write(f"{aid};{stock}\n")
        lines_written = 1 + len(entries)

    log.info(f"Bestandsdaten geschrieben: {output_path} ({lines_written} Zeilen)")
    if progress_cb:
        progress_cb(f"Bestandsdaten erzeugt: {lines_written} Zeilen → {os.path.basename(output_path)}")

    return output_path


def import_nordwest_stock(csv_path: str, db_path: str, progress_cb=None) -> int:
    """
    Liest bestaende.csv (aus der Nordwest kip.zip, Spalten
    "NW-Katalogartikelnummer;EAN;Produktbezeichnung;Bestand") und schreibt
    die Bestände in die Artikel-DB. Die Artikelnummer ist die native ID OHNE
    das Präfix "NDW", wie supplier_pid in der DB.

    Nordwest wird in der DB als drei getrennte Lieferanten geführt
    (Arbeitsschutz/Werkstatt/Werkzeugtechnik – je eigener eClass-Katalog),
    die Bestandsliste deckt aber offenbar alle Kataloge gemeinsam ab. Der
    Bestand wird deshalb gegen alle drei versucht; UPDATE trifft ohnehin nur
    dort, wo die Artikelnummer für den jeweiligen Lieferanten existiert
    (siehe update_stock() in article_db.py).

    Gibt die Gesamtzahl aktualisierter Artikel zurück.
    """
    p = progress_cb or (lambda m, **kw: None)
    if not os.path.exists(csv_path):
        return 0

    try:
        with open(csv_path, encoding="utf-8-sig") as f:
            raw = f.read()
    except UnicodeDecodeError:
        with open(csv_path, encoding="cp1252", errors="replace") as f:
            raw = f.read()

    entries: dict[str, str] = {}
    reader = csv.DictReader(raw.splitlines(), delimiter=";")
    for row in reader:
        aid   = (row.get("NW-Katalogartikelnummer") or "").strip()
        stock = (row.get("Bestand") or "").strip()
        if aid and stock:
            entries[aid] = stock

    if not entries:
        p("Nordwest-Bestand: keine Einträge in bestaende.csv gefunden", tag="warn")
        return 0

    try:
        from lib.article_db import open_db, get_or_create_supplier, update_stock
        from lib.supplier_config import get_supplier
        sup_names = list((get_supplier("nordwest").get("db_supplier_names") or {}).values())
        if not sup_names:
            sup_names = ["Nordwest Arbeitsschutz", "Nordwest Werkstatt", "Nordwest Werkzeugtechnik"]

        con = open_db(db_path)
        total = 0
        for name in sup_names:
            supplier_id = get_or_create_supplier(con, name)
            n = update_stock(con, supplier_id, entries)
            total += n
            p(f"Nordwest-Bestand: {n} Artikel aktualisiert ({name})")
        con.close()
        return total
    except Exception as e:
        log.warning(f"Nordwest-Bestand-DB-Update übersprungen: {e}")
        p(f"Nordwest-Bestand-DB-Update übersprungen: {e}", tag="warn")
        return 0


def import_softcarrier_stock(csv_path: str, db_path: str, progress_cb=None) -> int:
    """
    Liest die Softcarrier-Lagerbestandsdatei (FTP-Ordner "Lagerbestand",
    lagerbestand.csv). Format ist Pipe-getrennt mit einer Kopfzeile:
        artikelnr|lagerbestand <Datum> <Uhrzeit>|liefertermin
    Artikelnummer UND Bestand sind darin mit führenden Nullen aufgefüllt
    (z.B. "000000000000002735" / "0000000003") – supplier_pid in der DB
    ist die native ID ohne führende Nullen, daher werden beide getrimmt.
    """
    p = progress_cb or (lambda m, **kw: None)
    if not os.path.exists(csv_path):
        return 0

    try:
        with open(csv_path, encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
    except UnicodeDecodeError:
        with open(csv_path, encoding="cp1252", errors="replace") as f:
            lines = f.read().splitlines()

    entries: dict[str, str] = {}
    for line in lines[1:]:  # Kopfzeile überspringen
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) < 2:
            continue
        aid   = parts[0].strip().lstrip("0") or "0"
        stock = parts[1].strip().lstrip("0") or "0"
        if aid:
            entries[aid] = stock

    if not entries:
        p("Softcarrier-Bestand: keine Einträge in Lagerbestand-Datei gefunden", tag="warn")
        return 0

    try:
        from lib.article_db import open_db, get_or_create_supplier, update_stock
        con = open_db(db_path)
        supplier_id = get_or_create_supplier(con, "Softcarrier")
        n = update_stock(con, supplier_id, entries)
        con.close()
        p(f"Softcarrier-Bestand: {n} Artikel aktualisiert")
        return n
    except Exception as e:
        log.warning(f"Softcarrier-Bestand-DB-Update übersprungen: {e}")
        p(f"Softcarrier-Bestand-DB-Update übersprungen: {e}", tag="warn")
        return 0
