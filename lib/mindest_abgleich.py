# lib/mindest_abgleich.py – Mindestmengen-Abgleich → 32WQS_conditionsfile.csv
#
# Liest das neueste Mindest-Abgleich_*.xlsx aus BASE_DIR (Tabelle1, Spalten L:M),
# vergleicht mit der aktuellen availability-data-catalog-32WQS.csv und schreibt
# 32WQS_conditionsfile.csv ins gleiche Verzeichnis.
#
# Filter-Logik:
#   AID in Mindest-Tabelle  → Export wenn STOCK >= Mindestmenge
#   AID nicht in Tabelle    → Export immer (keine Mindestanforderung)

import os
import glob
import csv
import logging

log = logging.getLogger(__name__)

MINIMUM_STOCK = 10  # Globale Mindestmenge für alle Mindest-Artikel
_MINDEST_PATTERN = "Mindest-Abgleich_*.xlsx"
_CONDITIONS_FILE = "32WQS_conditionsfile.csv"


def find_latest_mindest_xlsx(base_dir: str) -> str | None:
    """Findet das neueste Mindest-Abgleich_*.xlsx im Basisverzeichnis."""
    pattern = os.path.join(base_dir, _MINDEST_PATTERN)
    files = glob.glob(pattern)
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def load_mindest_table(xlsx_path: str, progress_cb=None) -> dict:
    """
    Liest die Mindestmengen-Tabelle aus Tabelle1, Spalten L (Index 11) und M (Index 12).
    Überspringt Zeile 1 (Header).

    Returns:
        dict: {supplier_aid_upper: mindestmenge_int}
    """
    p = progress_cb or (lambda m, **kw: None)
    import openpyxl
    table = {}

    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb.active

    header_skipped = False
    for row in ws.iter_rows(min_col=12, max_col=13, values_only=True):
        artikel, minimum = row[0], row[1]

        if not header_skipped:
            header_skipped = True
            continue

        if artikel is None:
            continue

        aid = str(artikel).strip()
        if not aid:
            continue

        try:
            mindest = int(minimum) if minimum is not None else 0
        except (ValueError, TypeError):
            mindest = 0

        table[aid.upper()] = mindest

    wb.close()
    p(f"Mindest-Tabelle: {len(table)} Einträge geladen aus {os.path.basename(xlsx_path)}")
    return table


def load_availability(avail_csv: str) -> dict:
    """
    Liest die Availability-CSV (SUPPLIER_AID;STOCK).

    Returns:
        dict: {supplier_aid: stock_int}
    """
    data = {}
    if not os.path.exists(avail_csv):
        return data

    with open(avail_csv, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(";")
            aid = parts[0].strip()
            if not aid or aid.upper() == "SUPPLIER_AID":
                continue
            try:
                stock = int(parts[1].strip()) if len(parts) > 1 else 0
            except (ValueError, IndexError):
                stock = 0
            data[aid] = stock

    return data


def generate_conditionsfile(avail_csv: str, mindest_table: dict,
                             out_path: str, progress_cb=None) -> dict:
    """
    Abgleich Availability-CSV gegen Mindest-Tabelle → conditionsfile.

    Regeln (iteriert über Availability-CSV):
    - AID in Mindest-Tabelle:  Export wenn STOCK >= Mindestmenge
    - AID nicht in Tabelle:    Export wenn STOCK > 0
    - STOCK = 0 ohne Mindest:  kein Export

    Returns:
        dict: {"exported": n, "below_minimum": n, "zero_stock": n, "total": n}
    """
    p = progress_cb or (lambda m, **kw: None)

    avail = load_availability(avail_csv)
    if not avail:
        p(f"Availability-CSV nicht gefunden oder leer: {avail_csv}", tag="warn")
        # Leere conditionsfile mit nur Header schreiben
        with open(out_path, "w", encoding="utf-8", newline="") as f:
            f.write("SUPPLIER_AID\n")
        return {"exported": 0, "below_minimum": 0, "zero_stock": 0, "total": 0}

    exported     = []
    n_below      = 0
    n_zero       = 0

    for aid, stock in avail.items():
        aid_upper = aid.upper()

        if aid_upper in mindest_table:
            if stock >= MINIMUM_STOCK:
                exported.append(aid)
            else:
                n_below += 1
        else:
            # Kein Mindesteintrag: nur wenn Bestand > 0
            if stock > 0:
                exported.append(aid)
            else:
                n_zero += 1

    exported.sort()
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        f.write("SUPPLIER_AID\n")
        for aid in exported:
            f.write(aid + "\n")

    stats = {
        "exported":      len(exported),
        "below_minimum": n_below,
        "zero_stock":    n_zero,
        "total":         len(avail),
    }

    p(f"Conditionsfile: {len(exported)} Artikel exportiert "
      f"({n_below} unter Mindestmenge, "
      f"{n_zero} ohne Mindest und Bestand=0) "
      f"→ {os.path.basename(out_path)}")

    return stats


def run_mindest_abgleich(avail_csv: str, base_dir: str = None,
                          progress_cb=None) -> dict:
    """
    Vollständiger Mindest-Abgleich-Workflow:
    1. Neuestes Mindest-Abgleich_*.xlsx finden
    2. Mindest-Tabelle laden (Spalten L:M)
    3. Availability-CSV laden
    4. Conditionsfile schreiben (gleicher Ordner wie Availability-CSV)

    Wird nach jedem Availability-CSV-Update aufgerufen.
    """
    p = progress_cb or (lambda m, **kw: None)

    if base_dir is None:
        try:
            import config
            base_dir = config.BASE_DIR
        except Exception:
            base_dir = os.path.dirname(avail_csv)

    # 1. Mindest-Excel finden
    xlsx_path = find_latest_mindest_xlsx(base_dir)
    if not xlsx_path:
        p(f"Kein {_MINDEST_PATTERN} in {base_dir} – Abgleich übersprungen.",
          tag="warn")
        return {}

    p(f"Mindest-Abgleich: {os.path.basename(xlsx_path)}")

    # 2. Mindest-Tabelle laden
    try:
        mindest_table = load_mindest_table(xlsx_path, progress_cb=p)
    except Exception as e:
        p(f"Mindest-Tabelle konnte nicht gelesen werden: {e}", tag="warn")
        return {}

    if not mindest_table:
        p("Mindest-Tabelle leer – Abgleich übersprungen.", tag="warn")
        return {}

    # 3. Conditionsfile-Pfad: gleicher Ordner wie Availability-CSV
    out_dir  = os.path.dirname(avail_csv)
    out_path = os.path.join(out_dir, _CONDITIONS_FILE)

    # 4. Generieren
    return generate_conditionsfile(avail_csv, mindest_table, out_path,
                                    progress_cb=p)
