# tasks/bueroring_bestand.py
#
# Ablauf:
#   1. availability-data-catalog-32WQS.csv lesen
#      → Reiter "Bestand" in Bestand_und_Preise.xlsx ersetzen
#   2. Reiter "Master" als CSV exportieren:
#      · v_stock aus "Bestand"
#      · keinerlei Preis- oder Flag-Patching
#   3. CSV hochladen auf:
#      · brickfox_csv_erp      (c_abe_ftp_3) – Preise + Bestand, schnell
#      · brickfox_csv_exchange  (c_abe_ftp_5) – Stammdaten

import os
import logging
import csv
from datetime import datetime

log = logging.getLogger(__name__)

EXCEL_NAME = "Bestand_und_Preise.xlsx"


def _norm(x):
    import pandas as pd
    if pd.isna(x):
        return None
    return str(x).strip()


# Erlaubte Felder für CsvERP (c_abe_ftp_3) – strikt nur diese
ERP_FIELDS = [
    "p_id", "p_extern_id", "p_item_number",
    "v_id", "v_extern_id", "v_item_number", "v_ean",
    "v_price", "v_priceDEF", "v_priceEUR",          # Preis-Varianten
    "v_rrp",   "v_rrpDEF",  "v_rrpEUR",             # UVP-Varianten
    "v_delivery_time", "v_delivery_timeDEDE",        # Lieferzeit-Varianten
    "v_stock", "v_third_party_stock",                # Bestand
]

# Für CsvExchange (c_abe_ftp_5): keine Preis- und Bestandsfelder
EXCHANGE_EXCLUDE_PREFIXES = ("v_price", "v_rrp", "v_stock", "v_third_party_stock",
                             "v_delivery_time")


def _filter_erp(df):
    """Behält nur ERP-erlaubte Spalten + alle v_price/v_stock/v_rrp/v_delivery_time Varianten."""
    keep = []
    for col in df.columns:
        col_lower = col.lower()
        # Exakter Match oder Präfix-Match für parametrisierte Felder
        if any(col_lower == f or col_lower.startswith(f) for f in ERP_FIELDS):
            keep.append(col)
    return df[keep] if keep else df


def _filter_exchange(df):
    """Entfernt Preis-, Bestand- und Lieferzeit-Spalten."""
    keep = [col for col in df.columns
            if not any(col.lower().startswith(p)
                       for p in EXCHANGE_EXCLUDE_PREFIXES)]
    return df[keep] if keep else df


def _vlookup_map(src_df, col_idx=1):
    """
    Baut einmalig eine Key→Value-Lookup-Series aus src_df (Spalte 0 → Spalte
    col_idx), analog zu IFERROR(VLOOKUP(key, src!A:B, 2, 0), 0) – aber als
    Hash-Lookup statt einer Zeilen-für-Zeilen-Suche je Master-Artikel.
    Bei doppelten Keys gewinnt die erste Zeile (wie VLOOKUP).
    """
    import pandas as pd
    key_col = src_df.columns[0]
    val_col = src_df.columns[col_idx]
    keys = src_df[key_col].astype(str).str.strip()
    lookup = (pd.DataFrame({key_col: keys, val_col: src_df[val_col]})
                .dropna(subset=[key_col])
                .drop_duplicates(key_col, keep="first")
                .set_index(key_col)[val_col])
    return lookup


def _patch_and_export(excel_path: str, csv_in_path: str,
                      out_dir: str, p) -> tuple:
    """
    Liest alle XLSX-Reiter, berechnet VLOOKUPs in Python nach,
    patcht v_stock aus der Bestands-CSV und exportiert zwei CSVs.
    Gibt (erp_path, exchange_path) zurück.
    """
    import pandas as pd
    import openpyxl

    p(f"Lese {os.path.basename(excel_path)} ...")

    # BytesIO-Workaround: openpyxl kann bei manchen Windows-Pfaden
    # nicht direkt öffnen – als Bytes einlesen und via BytesIO übergeben
    import io
    with open(excel_path, "rb") as fh:
        excel_bytes = io.BytesIO(fh.read())

    # Alle Quell-Reiter laden
    all_sheets = pd.read_excel(excel_bytes, sheet_name=None,
                                engine="openpyxl", dtype=str)
    for name, df in all_sheets.items():
        p(f"  Reiter '{name}': {len(df)} Zeilen, {len(df.columns)} Spalten")

    master = all_sheets.get("Master")
    if master is None:
        raise KeyError("Reiter 'Master' nicht gefunden")
    if "p_item_number" not in master.columns:
        raise KeyError("Spalte 'p_item_number' fehlt im Master-Reiter")

    master["p_item_number"] = master["p_item_number"].map(_norm)

    # Bestands-CSV einlesen
    p(f"Lese {os.path.basename(csv_in_path)} ...")
    with open(csv_in_path, encoding="utf-8", errors="replace") as f:
        first = f.readline().strip()
    if first.upper().startswith("SUPPLIER_AID"):
        bestand_csv = pd.read_csv(csv_in_path, sep=";", dtype=str)
    else:
        bestand_csv = pd.read_csv(csv_in_path, sep=";", dtype=str,
                                   header=None, names=["SUPPLIER_AID", "STOCK"])
    bestand_csv["SUPPLIER_AID"] = bestand_csv["SUPPLIER_AID"].map(_norm)

    # v_stock aus Bestands-CSV patchen
    stock_map = (bestand_csv.dropna(subset=["SUPPLIER_AID"])
                             .drop_duplicates("SUPPLIER_AID", keep="last")
                             .set_index("SUPPLIER_AID")["STOCK"])
    if "v_stock" not in master.columns:
        master["v_stock"] = "0"
    stock_new = master["p_item_number"].map(stock_map)
    master.loc[stock_new.notna(), "v_stock"] = stock_new[stock_new.notna()].values
    # NaN → "0"
    master["v_stock"] = (master["v_stock"].fillna("0")
                                          .replace("", "0")
                                          .replace("nan", "0")
                                          .replace("None", "0"))
    p(f"  v_stock Treffer: {int(stock_new.notna().sum())}")

    # VLOOKUPs nachberechnen: Spaltenname → (Quell-Reiter, Spaltenindex)
    # Alle Preis-Spalten die VLOOKUP-Formeln haben
    vlookup_cols = {
        "v_price[cr_de]":  ("v_attributesconrad",      1),
        "v_price[kl_de]":  ("v_attributeskaufland_de", 1),
        "v_price[kl_at]":  ("v_attributeskaufland_at", 1),
        "v_price[kl_fr]":  ("v_attributeskaufland_fr", 1),
        "v_price[ne_de]":  ("v_attributesnetto_de",    1),
    }
    for col, (sheet, cidx) in vlookup_cols.items():
        if col not in master.columns:
            continue
        src = all_sheets.get(sheet)
        if src is None:
            p(f"  Reiter '{sheet}' fehlt – {col} wird 0 gesetzt", tag="warn")
            master[col] = "0"
            continue
        lookup = _vlookup_map(src, cidx)
        master[col] = master["p_item_number"].map(lookup)
        # NaN / leer → "0"
        master[col] = (master[col].fillna("0")
                                   .replace("", "0")
                                   .replace("nan", "0")
                                   .replace("None", "0"))
        n = (master[col] != "0").sum()
        p(f"  {col}: {n} Treffer")

    # IF-Flags: marketplace = 1 wenn Preis != 0
    flag_map = {
        "p_attributes[marketplace_1][de]":  "v_price[cr_de]",
        "p_attributes[marketplace_4][de]":  "v_price[kl_de]",
        "p_attributes[marketplace_13][de]": "v_price[ne_de]",
        # Marktkauf – Untermarktplatz von Netto DE, teilt sich dessen Preisspalte:
        # sobald ein netto_de-Preis existiert, auch auf 16 anbieten.
        "p_attributes[marketplace_16][de]": "v_price[ne_de]",
    }
    for flag, price_col in flag_map.items():
        if flag in master.columns and price_col in master.columns:
            master[flag] = master[price_col].apply(
                lambda v: "1" if str(v) not in ("0", "", "None", "nan") else "0")
            n = (master[flag] == "1").sum()
            p(f"  {flag}: {n} aktiv")

    # Bestand-Reiter in XLSX zurückschreiben
    p("Schreibe Bestand-Reiter zurück in XLSX ...")
    with open(excel_path, "rb") as fh:
        wb_buf = io.BytesIO(fh.read())
    wb = openpyxl.load_workbook(wb_buf)
    ws = wb["Bestand"]
    ws.delete_rows(1, ws.max_row)
    ws.append(["SUPPLIER_AID", "STOCK"])
    for _, row in bestand_csv.iterrows():
        ws.append([row["SUPPLIER_AID"], row["STOCK"]])
    wb.save(excel_path)
    wb.close()

    ts = datetime.now().strftime("%Y%m%d%H%M%S")

    # CsvERP (c_abe_ftp_3) – Präfix "Products"
    erp_df   = _filter_erp(master)
    erp_name = f"Products_bueroring_{ts}.csv"
    erp_path = os.path.join(out_dir, erp_name)
    erp_df.to_csv(erp_path, index=False, sep=";", encoding="utf-8",
                  quoting=csv.QUOTE_ALL, escapechar="\\")
    p(f"CSV ERP: {erp_name}  ({os.path.getsize(erp_path):,} Bytes)  "
      f"[{len(erp_df.columns)} Spalten]", tag="ok")

    # CsvExchange (c_abe_ftp_5) – Präfix "csv_autoimport"
    exc_df   = _filter_exchange(master)
    exc_name = f"csv_autoimport_bueroring_{ts}.csv"
    exc_path = os.path.join(out_dir, exc_name)
    exc_df.to_csv(exc_path, index=False, sep=";", encoding="utf-8",
                  quoting=csv.QUOTE_ALL, escapechar="\\")
    p(f"CSV Exchange: {exc_name}  ({os.path.getsize(exc_path):,} Bytes)  "
      f"[{len(exc_df.columns)} Spalten]", tag="ok")

    return erp_path, exc_path


def run(progress_cb=None, file_progress_cb=None):
    from config import DIRS, CONNECTIONS, AVAILABILITY_FILE
    from lib.ftp_client import make_client

    p  = progress_cb      or (lambda m, **kw: None)
    fp = file_progress_cb or None

    import config as _cfg
    base   = _cfg.BASE_DIR
    in_bme = DIRS["in_bme"]

    p("┌─ Büroring Bestand+Preis ───────────────────────────────────")
    p(f"│  Eingabe:  {EXCEL_NAME}  (BASE_DIR)")
    p(f"│            {AVAILABILITY_FILE}")
    p("│  ↓ lädt:    /400446/stock/BestandBueroring.csv")
    p("│  ↓ erzeugt: Products_bueroring_{{ts}}.csv")
    p("│             csv_autoimport_bueroring_{{ts}}.csv")
    p("│  Uploads:")
    p("│    ↑ Products_*.csv        → abe.brickfox.net/incoming (c_abe_ftp_3 ERP)")
    p("│    ↑ csv_autoimport_*.csv  → abe.brickfox.net/incoming (c_abe_ftp_5 Exchange)")
    p("└────────────────────────────────────────────────────────────")

    p("Lade BestandBueroring.csv ...")
    cfg_brg = CONNECTIONS["bueroring"]
    cl_brg = make_client(cfg_brg)
    cl_brg.connect()
    try:
        cl_brg.download("/400446/stock/BestandBueroring.csv",
                        in_bme, progress_cb=p, file_progress_cb=fp)
    finally:
        cl_brg.disconnect()

    excel_ok = os.path.exists(os.path.join(base, EXCEL_NAME))
    avail_ok = (os.path.exists(os.path.join(base, AVAILABILITY_FILE))
                or os.path.exists(os.path.join(in_bme, AVAILABILITY_FILE)))
    p(f"  {'✓' if excel_ok else '✗ FEHLT':<8} {EXCEL_NAME}",
      tag="ok" if excel_ok else "warn")
    p(f"  {'✓' if avail_ok else '– wird erzeugt':<8} {AVAILABILITY_FILE}",
      tag="ok" if avail_ok else "dim")

    excel_path = os.path.join(base, EXCEL_NAME)

    csv_in_path = os.path.join(base, AVAILABILITY_FILE)
    if not os.path.exists(csv_in_path):
        csv_in_path = os.path.join(in_bme, AVAILABILITY_FILE)

    if not os.path.exists(excel_path):
        raise FileNotFoundError(f"{EXCEL_NAME} nicht gefunden: {excel_path}")

    if not os.path.exists(csv_in_path):
        p(f"{AVAILABILITY_FILE} nicht gefunden – erzeuge via Büroring-Bestand ...")
        from main import run_bestandsdaten_only
        run_bestandsdaten_only(progress_cb=p)
        csv_in_path = os.path.join(in_bme, AVAILABILITY_FILE)
        if not os.path.exists(csv_in_path):
            raise FileNotFoundError(f"{AVAILABILITY_FILE} konnte nicht erzeugt werden.")

    erp_csv, exc_csv = _patch_and_export(excel_path, csv_in_path, base, p)

    # CsvERP (c_abe_ftp_3) – nur Preise + Bestand, schnelle Verarbeitung
    p("Upload → Brickfox CsvERP (c_abe_ftp_3) ...")
    cfg_erp = CONNECTIONS["brickfox_csv_erp"]
    cl = make_client(cfg_erp)
    cl.connect()
    try:
        cl.upload(erp_csv, cfg_erp["remote_path"], progress_cb=p, file_progress_cb=fp)
    finally:
        cl.disconnect()

    # CsvExchange (c_abe_ftp_5) – Stammdaten ohne Preis/Bestand
    p("Upload → Brickfox CsvExchange (c_abe_ftp_5) ...")
    cfg_exc = CONNECTIONS["brickfox_csv_exchange"]
    cl2 = make_client(cfg_exc)
    cl2.connect()
    try:
        cl2.upload(exc_csv, cfg_exc["remote_path"], progress_cb=p, file_progress_cb=fp)
    finally:
        cl2.disconnect()

    p("Bueroring-Bestand abgeschlossen.", tag="ok")