# lib/mindest_abgleich.py – Mindestmengen-Abgleich → 32WQS_conditionsfile.csv
#
# Liest das neueste Mindest-Abgleich_*.xlsx aus BASE_DIR (Tabelle1, Spalten L:M),
# vergleicht mit der aktuellen availability-data-catalog-32WQS.csv und schreibt
# 32WQS_conditionsfile.csv ins gleiche Verzeichnis.
#
# Filter-Logik:
#   AID in Mindest-Tabelle  → Export wenn STOCK >= Mindestmenge
#   AID nicht in Tabelle    → Export wenn STOCK > 0
#
# Regulierungs-Merkmale (GPSR-Hersteller, WEEE, Batterieverordnung,
# Datengesetz ...): gepflegte Datei BASE_DIR/32WQS_conditions_features.csv
# im Unite-Conditionsfile-Format (SUPPLIER_AID;FEATURE_NAME1;FEATURE_VALUE1;
# FEATURE_UNIT1;...). Die Merkmale werden je exportierter SUPPLIER_AID
# angehängt; Artikel ohne Eintrag bekommen leere Merkmalsspalten.

import os
import glob
import csv
import logging

log = logging.getLogger(__name__)

_MINDEST_PATTERN = "Mindest-Abgleich_*.xlsx"
_CONDITIONS_FILE = "32WQS_conditionsfile.csv"
# Gepflegte Regulierungs-Merkmale je Artikel (GPSR-Hersteller, WEEE,
# Batterieverordnung, Datengesetz ...) im BASE_DIR – gleiches Spaltenformat
# wie die Unite-Conditionsfile: SUPPLIER_AID;FEATURE_NAME1;FEATURE_VALUE1;
# FEATURE_UNIT1;... Wird je SUPPLIER_AID in die conditionsfile gemischt.
_FEATURES_FILE = "32WQS_conditions_features.csv"


def load_condition_features(base_dir: str, progress_cb=None) -> tuple[dict, int]:
    """
    Liest 32WQS_conditions_features.csv (optional).

    Returns:
        ({SUPPLIER_AID_UPPER: [(name, value, unit), ...]}, max_features)
        max_features = Anzahl FEATURE-Tripel in der Kopfzeile (Spaltenbreite
        der Ausgabe); (dict leer, 0) wenn die Datei fehlt.
    """
    p = progress_cb or (lambda m, **kw: None)
    path = os.path.join(base_dir, _FEATURES_FILE)
    if not os.path.exists(path):
        return {}, 0
    feats: dict = {}
    max_cols = 0
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                reader = csv.reader(f, delimiter=";")
                header = next(reader, None) or []
                # Anzahl Tripel aus der Kopfzeile (FEATURE_NAMEn)
                max_cols = sum(1 for h in header if h.strip().upper().startswith("FEATURE_NAME"))
                for row in reader:
                    if not row or not row[0].strip():
                        continue
                    aid = row[0].strip()
                    triples = []
                    for i in range(1, len(row) - 2, 3):
                        name = row[i].strip()
                        if not name:
                            continue
                        value = row[i + 1].strip() if i + 1 < len(row) else ""
                        unit  = row[i + 2].strip() if i + 2 < len(row) else ""
                        triples.append((name, value, unit))
                    feats[aid.upper()] = triples
                    max_cols = max(max_cols, len(triples))
            break
        except UnicodeDecodeError:
            feats, max_cols = {}, 0
            continue
    p(f"Conditions-Merkmale: {len(feats)} Artikel aus {_FEATURES_FILE} "
      f"(bis zu {max_cols} Merkmale je Artikel)")
    return feats, max_cols


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
                             out_path: str, progress_cb=None,
                             features: dict = None, max_features: int = 0) -> dict:
    """
    Abgleich Availability-CSV gegen Mindest-Tabelle → conditionsfile.

    Regeln (iteriert über Availability-CSV):
    - AID in Mindest-Tabelle:  Export wenn STOCK >= Mindestmenge
    - AID nicht in Tabelle:    Export wenn STOCK > 0
    - STOCK = 0 ohne Mindest:  kein Export

    features/max_features (optional, siehe load_condition_features): je
    exportierter SUPPLIER_AID werden die Regulierungs-Merkmale als
    FEATURE_NAMEn/FEATURE_VALUEn/FEATURE_UNITn-Spalten angehängt; Artikel
    ohne Eintrag bekommen leere Merkmalsspalten.

    Returns:
        dict: {"exported": n, "below_minimum": n, "zero_stock": n, "total": n,
               "with_features": n}
    """
    p = progress_cb or (lambda m, **kw: None)
    features = features or {}
    header = ["SUPPLIER_AID"]
    for i in range(1, max_features + 1):
        header += [f"FEATURE_NAME{i}", f"FEATURE_VALUE{i}", f"FEATURE_UNIT{i}"]

    avail = load_availability(avail_csv)
    if not avail:
        p(f"Availability-CSV nicht gefunden oder leer: {avail_csv}", tag="warn")
        # Leere conditionsfile mit nur Header schreiben
        with open(out_path, "w", encoding="utf-8", newline="") as f:
            f.write(";".join(header) + "\n")
        return {"exported": 0, "below_minimum": 0, "zero_stock": 0, "total": 0,
                "with_features": 0}

    exported     = []
    n_below      = 0
    n_zero       = 0

    for aid, stock in avail.items():
        aid_upper = aid.upper()

        if aid_upper in mindest_table:
            # Individuelle Mindestmenge aus Spalte M für diese AID
            # (=SVERWEIS-Zweig der Excel-Formel: WENN(B<SVERWEIS(A;L:M;2;0)...).
            threshold = mindest_table[aid_upper]
            if stock >= threshold:
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
    n_feat = 0
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";", lineterminator="\n",
                       quoting=csv.QUOTE_MINIMAL)
        w.writerow(header)
        for aid in exported:
            row = [aid]
            triples = features.get(aid.upper(), [])
            if triples:
                n_feat += 1
            for name, value, unit in triples[:max_features]:
                row += [name, value, unit]
            row += [""] * (len(header) - len(row))
            w.writerow(row)

    stats = {
        "exported":      len(exported),
        "below_minimum": n_below,
        "zero_stock":    n_zero,
        "total":         len(avail),
        "with_features": n_feat,
    }

    p(f"Conditionsfile: {len(exported)} Artikel exportiert "
      f"({n_below} unter Mindestmenge, "
      f"{n_zero} ohne Mindest und Bestand=0"
      + (f", {n_feat} mit Regulierungs-Merkmalen, {len(exported) - n_feat} ohne"
         if max_features else "")
      + f") → {os.path.basename(out_path)}")

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

    # 4. Regulierungs-Merkmale (optional, BASE_DIR/32WQS_conditions_features.csv)
    features, max_features = load_condition_features(base_dir, progress_cb=p)
    if not features:
        p(f"Keine {_FEATURES_FILE} in {base_dir} – conditionsfile ohne "
          f"Regulierungs-Merkmale.", tag="dim")

    # 5. Generieren
    return generate_conditionsfile(avail_csv, mindest_table, out_path,
                                    progress_cb=p, features=features,
                                    max_features=max_features)
