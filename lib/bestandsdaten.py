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

    with open(output_path, "w", encoding="utf-8", newline="") as out:
        out.write("SUPPLIER_AID;STOCK\n")
        for aid, stock in entries.items():
            out.write(f"{aid};{stock}\n")
        lines_written = 1 + len(entries)

    log.info(f"Bestandsdaten geschrieben: {output_path} ({lines_written} Zeilen)")
    if progress_cb:
        progress_cb(f"Bestandsdaten erzeugt: {lines_written} Zeilen → {os.path.basename(output_path)}")

    return output_path
