# lib/ebay_export.py – eBay File-Exchange Export (Neuanlage / Revise / Beenden)
#
# Erzeugt aus der Artikel-DB die drei eBay File-Exchange-Formate:
#   1. Draft-Template   (Neuanlage – Action=Draft)
#   2. Revise-Template  (Bestand/Preis – Action=Revise, auch Reaktivierung
#                        ausgelaufener Auktionen mit bekannter ItemID)
#   3. End-Template     (Beenden – Action=End, EndingReason=NotAvailable)
#
# SKU = supplier_pid (native Artikel-ID ohne Lieferanten-Präfix wie BRG/NDW).
# Welche SKU bereits bei eBay existiert (und mit welcher ItemID), merkt sich
# die ebay_listings-Tabelle (article_db.py) – befüllt beim Einlesen eines von
# eBay heruntergeladenen Revise-Reports (dort stehen SKU+ItemID authoritativ).

import csv
import logging
import os
import re
from datetime import datetime

log = logging.getLogger(__name__)

# ── eBay-Template-Header (aus echten File-Exchange-Exporten übernommen) ────────

_DRAFT_INFO_LINES = [
    "#INFO;Version=0.0.2;Template= eBay-draft-listings-template_DE",
    "#INFO Action und Category ID sind erforderliche Felder. 1) Stellen Sie Action "
    "auf Draft ein. 2) Die Kategorie-ID für Ihre Angebote finden Sie hier: "
    "https://pages.ebay.com/sellerinformation/news/categorychanges.html",
    "#INFO Nachdem Sie Ihren Entwurf erfolgreich im Berichte-Tab Ihres "
    "Verkäufer-Cockpit Pro heruntergeladen haben;können Sie die Entwürfe hier zu "
    "aktiven Angeboten vervollständigen: https://www.ebay.de/sh/lst/drafts",
    "#INFO",
]

_DRAFT_HEADER = [
    "Action(SiteID=Germany|Country=DE|Currency=EUR|Version=1193|CC=UTF-8)",
    "Custom label (SKU)", "Category ID", "Title", "UPC", "Price", "Quantity",
    "Item photo URL", "Condition ID", "Description", "Format",
    "C:Produktart", "C:Material", "C:Farbe", "C:Format", "C:Packungsgröße",
    "C:Marke", "C:Herstellernummer", "C:EAN", "C:Modell", "C:Bandbreite",
    "C:Bandlänge", "C:Farbe Text", "C:Farbe Hintergrund", "C:Kompatible Geräte",
    "C:Anwendungsbereich", "C:Inhalt", "C:Anzahl Fächer", "C:Breite", "C:Höhe",
    "C:Anzahl", "C:Rückenbreite", "C:Mechanik", "C:Stärke", "C:Oberfläche",
    "C:Lochung", "C:Lagigkeit", "C:Blattgröße", "C:Anzahl Blatt",
    "C:Anzahl Rollen", "C:Reiter", "C:Anzahl Ringe", "C:Norm",
    "C:Material Gehäuse", "C:Batteriegröße", "C:Chemie", "C:Spannung",
    "C:Kapazität", "C:Speicherkapazität", "C:USB-Version", "C:Kompatibles Modell",
    "C:Max. Traglast", "C:VESA", "C:Volumen", "C:Außenmaß Länge",
    "C:Außenmaß Breite", "C:Außenmaß Höhe", "C:Wellpappe", "C:Steril",
    "C:Anzahl Stellen", "C:Stromversorgung", "C:Druckfunktion", "C:Innenmaß",
    "C:Länge", "C:Material Klinge", "C:Händigkeit", "C:Anzahl Blätter/Tabs",
    "C:Anschlusstyp", "C:Ausgangsleistung", "C:Kabellänge",
    "C:Schreibgeschwindigkeit", "C:Druckbar", "C:Verpackung", "C:Größe",
    "C:Durchmesser", "C:Abmessungen", "C:Münzfächer", "C:Scheinabteile",
    "C:Schloss", "C:Aufnahmeformat", "C:Linierung", "C:Drucktechnologie",
    "C:Druckformat", "C:Konnektivität", "C:Druckgeschwindigkeit",
    "C:Zellenzahl", "C:Anschluss", "C:Etikettengröße", "C:Etiketten je Bogen",
    "C:Anzahl Bogen", "C:Warnschutzklasse", "C:Fassungsvermögen",
    "C:Wandmontage", "C:Anzahl Steckdosen", "C:Überspannungsschutz",
    "C:Schalter", "C:Anschluss A", "C:Anschluss B", "C:Kategorie",
    "C:Geschwindigkeitsklasse", "C:Lesegeschwindigkeit", "C:Material Rahmen",
    "C:Tönung", "C:Schutzklasse", "C:Ventil", "C:Schnittstelle",
    "C:Formfaktor", "C:Leistung", "C:Klingenlänge", "C:Einbandmaterial",
    "C:Anzahl Seiten", "C:Schnittart", "C:Sicherheitsstufe",
    "C:Max. Blattkapazität", "C:Behältervolumen", "C:Reichweite",
    "C:Farbe Laserstrahl", "C:Bildformat", "C:Ausrichtung", "C:Grammatur",
    "C:Abdruckgröße", "C:Strichstärke", "C:Farbe Tinte", "C:Farbe Gehäuse",
    "C:Verschluss", "C:Fenster", "C:Layout", "C:Akkulaufzeit", "C:Auflösung",
    "C:Autofokus", "C:Sprache", "C:FSK", "C:Kompatible Drucker",
    "C:Seitenleistung", "C:Saugleistung", "C:Staubbeutel", "C:Typ",
    "C:Max. Laminierbreite", "C:Max. Folienstärke", "C:Schriftband",
    "C:Anzahl Etiketten", "C:Nutzfläche", "C:Türverschluss", "C:Druckfarbe",
    "C:Tierart", "C:Röstgrad", "C:Kaffeespezialität",
    "DomesticShippingService-1:Option", "DomesticShippingService-1:Cost",
    "DomesticShippingService-1:AdditionalCost", "ListingType", "StartPrice",
    "BuyItNowPrice",
]
_C_COLUMNS = [h for h in _DRAFT_HEADER if h.startswith("C:")]

_REVISE_INFO_LINE = ("#INFO;Version=1.0.0;"
                     "Template= eBay-active-revise-price-quantity-download_DE")
_REVISE_HEADER = [
    "Action", "Category name", "Item number", "Title", "Listing site",
    "Currency", "Start price", "Buy It Now price", "Available quantity",
    "Relationship", "Relationship details", "Custom label (SKU)",
]

_END_HEADER = ["Action", "ItemID", "EndingReason"]

# Standard-Versandkonditionen (aus bisherigen Batches übernommen)
_DEFAULT_SHIPPING = {
    "option": "Paket national",
    "cost": "7.95",
    "additional_cost": "0",
}


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


# ── Mapping-Dateien ─────────────────────────────────────────────────────────
#
# Die Kataloggruppe -> eBay-Kategorie-Zuordnung nutzt die bereits vorhandene,
# kanalübergreifende Mapping-Datei channels/channel_category_mapping.csv
# (lib/channel_mapping.py, Spalte ebay_category_id) statt einer eigenen –
# damit die Pflege an EINER Stelle passiert (gilt auch für Kaufland/Conrad/
# ManoMano/Unite) und der bestehende "Kanal-Kategorie-Mapping"-Task die
# Lücken weiterhin zuverlässig meldet.

def _load_category_map(base_dir: str) -> dict:
    """Kataloggruppe (Leaf-group_id, = supplier_category_code) -> eBay Category ID."""
    from lib.channel_mapping import load_category_mappings, get_channel_category
    mappings = load_category_mappings(base_dir)
    return {code: get_channel_category(mappings, code, "ebay")
            for code in mappings if get_channel_category(mappings, code, "ebay")}


def _load_feature_map(base_dir: str) -> dict:
    """
    FNAME -> eBay C:-Spaltenname, nur für Ausnahmen zur (häufigen) 1:1-
    Namensgleichheit zwischen FNAME und C:-Spalte (z.B. FNAME "Farbe" passt
    automatisch auf Spalte "C:Farbe", ohne Eintrag hier nötig zu sein).
    """
    path = os.path.join(base_dir, "ebay_feature_map.csv")
    result = {}
    if not os.path.exists(path):
        return result
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f, delimiter=";"):
            fname = (row.get("fname") or "").strip()
            col = (row.get("ebay_column") or "").strip()
            if fname and col:
                result[fname.lower()] = col
    return result


def _leaf_group_id(art: dict) -> str:
    return (art.get("catalog_node_group_id") or art.get("catalog_sub_group_id")
            or art.get("catalog_group_id") or "")


# ── Zeilen-Aufbau ─────────────────────────────────────────────────────────────

def _image_url(art: dict, image_base: str, prefix_map: dict) -> str:
    """Bild Prio 1 (niedrigste mime_order) mit mime_purpose=normal."""
    from lib.db_exporter import _supplier_prefix, _extract_filename, _add_prefix

    mimes = [m for m in (art.get("mimes") or [])
             if (m.get("mime_purpose") or "").strip().lower() == "normal"]
    if not mimes:
        return ""
    mimes.sort(key=lambda m: m.get("mime_order", 0))
    prefix = _supplier_prefix(art, prefix_map)
    fname = _add_prefix(_extract_filename(mimes[0].get("mime_source", "") or ""), prefix)
    if not fname:
        return ""
    return image_base.rstrip("/") + "/" + fname


def _feature_values(art: dict, feature_map: dict) -> dict:
    """eBay-Spaltenname (Klartext ohne 'C:', lowercase) -> FVALUE."""
    values = {}
    for f in art.get("features", []):
        fname = (f.get("fname") or "").strip()
        if not fname:
            continue
        col_name = feature_map.get(fname.lower(), fname)
        key = col_name.lower()
        if key not in values:   # erster Wert gewinnt (Multi-Value-Features)
            values[key] = f.get("fvalue", "")
    return values


def build_draft_row(art: dict, category_map: dict, feature_map: dict,
                    image_base: str, prefix_map: dict,
                    shipping: dict = None) -> list:
    shipping = shipping or _DEFAULT_SHIPPING
    price = art.get("price_amount")
    price_str = f"{price:.2f}" if isinstance(price, (int, float)) else ""
    values = _feature_values(art, feature_map)
    ean = art.get("ean", "")

    row = {
        _DRAFT_HEADER[0]: "Draft",
        "Custom label (SKU)": art.get("supplier_pid", ""),
        "Category ID": category_map.get(_leaf_group_id(art).upper(), ""),
        "Title": art.get("description_short", ""),
        "UPC": ean,
        "Price": price_str,
        "Quantity": art.get("stock_qty") or "",
        "Item photo URL": _image_url(art, image_base, prefix_map),
        "Condition ID": "NEW",
        "Description": art.get("description_long") or art.get("description_short", ""),
        "DomesticShippingService-1:Option": shipping.get("option", ""),
        "DomesticShippingService-1:Cost": shipping.get("cost", ""),
        "DomesticShippingService-1:AdditionalCost": shipping.get("additional_cost", "0"),
        "ListingType": "FixedPrice",
    }
    for col in _C_COLUMNS:
        name = col[2:]
        if name == "Marke":
            row[col] = art.get("manufacturer_name", "")
        elif name == "Herstellernummer":
            row[col] = art.get("manufacturer_aid", "")
        elif name == "EAN":
            row[col] = ean
        else:
            row[col] = values.get(name.lower(), "")

    return [row.get(h, "") for h in _DRAFT_HEADER]


def build_revise_row(art: dict, listing: dict) -> list:
    price = art.get("price_amount")
    price_str = f"{price:.2f}" if isinstance(price, (int, float)) else ""
    return [
        "Revise",
        listing.get("category_name", ""),
        listing.get("item_id", ""),
        art.get("description_short", ""),
        "DE",
        "EUR",
        price_str,
        "",
        art.get("stock_qty") or "0",
        "", "",
        art.get("supplier_pid", ""),
    ]


def build_end_row(item_id: str, reason: str = "NotAvailable") -> list:
    return ["End", item_id, reason]


# ── CSV-Schreiber ─────────────────────────────────────────────────────────────

def _write_csv(path: str, info_lines: list, header: list, rows: list):
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        for line in info_lines:
            f.write(line + "\n")
        writer.writerow(header)
        for row in rows:
            writer.writerow(row)


# ── SKU-Liste einlesen ────────────────────────────────────────────────────────

def _read_sku_list(path: str) -> list:
    try:
        with open(path, encoding="utf-8-sig") as f:
            raw = f.read()
    except UnicodeDecodeError:
        with open(path, encoding="cp1252", errors="replace") as f:
            raw = f.read()

    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    if lines and re.sub(r'["\']', '', lines[0]).strip().lower() in (
            "sku", "custom label (sku)", "custom label"):
        lines = lines[1:]

    skus = []
    for line in lines:
        first = re.split(r"[;,\t]", line)[0].strip().strip('"')
        if first:
            skus.append(first)
    return skus


# ── Task A: SKU-Liste (Vertrieb) → Neuanlage / Revise ─────────────────────────

def process_sku_list(sku_csv_path: str, db_path: str, base_dir: str, out_dir: str,
                     image_base: str, progress_cb=None) -> dict:
    """
    Liest eine manuell zusammengestellte SKU-Liste und trennt sie danach,
    ob die SKU laut ebay_listings-Registry schon bei eBay existiert:
      - unbekannt        → eBay_Neuanlage_<ts>.csv (Draft-Template)
      - bekannt, Bestand > 0 → eBay_Revise_<ts>.csv (Revise/Reaktivierung)
      - bekannt, Bestand = 0 → eBay_Beenden_<ts>.csv (End)
    """
    p = progress_cb or (lambda m, **kw: None)
    os.makedirs(out_dir, exist_ok=True)

    skus = _read_sku_list(sku_csv_path)
    p(f"eBay-SKU-Liste: {len(skus)} SKUs gelesen.")
    if not skus:
        return {"total": 0}

    from lib.article_db import open_db, get_ebay_listings, query_by_supplier_pids
    con = open_db(db_path)

    articles = query_by_supplier_pids(con, skus)
    by_pid = {}
    for art in articles:
        by_pid.setdefault(art["supplier_pid"], art)  # erster Treffer gewinnt

    listings = get_ebay_listings(con, skus)

    category_map = _load_category_map(base_dir)
    feature_map  = _load_feature_map(base_dir)
    from lib.db_exporter import _load_prefix_map
    prefix_map = _load_prefix_map(base_dir)

    not_found, new_rows, revise_rows, end_rows = [], [], [], []
    no_category = []

    for sku in skus:
        art = by_pid.get(sku)
        if not art:
            not_found.append(sku)
            continue

        listing = listings.get(sku)
        stock = 0
        try:
            stock = int(float(str(art.get("stock_qty") or "0").replace(",", ".")))
        except ValueError:
            stock = 0

        if listing:
            if stock > 0:
                revise_rows.append(build_revise_row(art, listing))
            else:
                end_rows.append(build_end_row(listing["item_id"]))
        else:
            if stock <= 0:
                p(f"  {sku}: übersprungen (Bestand 0, noch nicht bei eBay)", tag="warn")
                continue
            row = build_draft_row(art, category_map, feature_map, image_base, prefix_map)
            if not row[2]:  # Category ID leer
                no_category.append(sku)
            new_rows.append(row)

    ts = _now_stamp()
    out = {}
    if new_rows:
        path = os.path.join(out_dir, f"eBay_Neuanlage_{ts}.csv")
        _write_csv(path, _DRAFT_INFO_LINES, _DRAFT_HEADER, new_rows)
        out["neuanlage"] = path
        p(f"eBay Neuanlage: {len(new_rows)} Artikel → {os.path.basename(path)}", tag="ok")
    if revise_rows:
        path = os.path.join(out_dir, f"eBay_Revise_{ts}.csv")
        _write_csv(path, [_REVISE_INFO_LINE], _REVISE_HEADER, revise_rows)
        out["revise"] = path
        p(f"eBay Revise/Reaktivierung: {len(revise_rows)} Artikel → {os.path.basename(path)}", tag="ok")
    if end_rows:
        path = os.path.join(out_dir, f"eBay_Beenden_{ts}.csv")
        _write_csv(path, [], _END_HEADER, end_rows)
        out["beenden"] = path
        p(f"eBay Beenden (Bestand 0): {len(end_rows)} Artikel → {os.path.basename(path)}", tag="ok")
    if not_found:
        p(f"⚠ {len(not_found)} SKU(s) nicht in der Artikel-DB gefunden: "
          f"{', '.join(not_found[:20])}" + (" ..." if len(not_found) > 20 else ""),
          tag="warn")
    if no_category:
        p(f"⚠ {len(no_category)} neue Artikel ohne eBay-Kategorie (Category ID leer) – "
          f"ebay_category_map.csv ergänzen: {', '.join(no_category[:20])}"
          + (" ..." if len(no_category) > 20 else ""), tag="warn")

    return {
        "total": len(skus), "neuanlage": len(new_rows), "revise": len(revise_rows),
        "beenden": len(end_rows), "not_found": len(not_found),
        "no_category": len(no_category), "files": out,
    }


# ── Task B: eBay-eigener Revise-Report → Bestand/Preis auffrischen ────────────

def sync_active_listings(download_csv_path: str, db_path: str, out_dir: str,
                         progress_cb=None) -> dict:
    """
    Liest den von eBay heruntergeladenen 'eBay-active-revise-price-quantity-
    download_DE'-Report (enthält SKU + ItemID + Category name authoritativ),
    aktualisiert daraus die ebay_listings-Registry und schreibt Price/
    Quantity aus der DB zurück – Artikel mit Bestand 0 landen stattdessen in
    einer End-Datei statt mit Quantity=0 revised zu werden.
    """
    p = progress_cb or (lambda m, **kw: None)
    os.makedirs(out_dir, exist_ok=True)

    try:
        with open(download_csv_path, encoding="utf-8-sig") as f:
            raw = f.read()
    except UnicodeDecodeError:
        with open(download_csv_path, encoding="cp1252", errors="replace") as f:
            raw = f.read()

    lines = raw.splitlines()
    if lines and lines[0].startswith("#INFO"):
        lines = lines[1:]
    reader = csv.DictReader(lines, delimiter=";")

    listing_rows, skus = [], []
    for row in reader:
        sku = (row.get("Custom label (SKU)") or "").strip()
        item_id = (row.get("Item number") or "").strip()
        if not sku or not item_id:
            continue
        listing_rows.append({
            "sku": sku, "item_id": item_id,
            "category_name": (row.get("Category name") or "").strip(),
            "status": "active",
        })
        skus.append(sku)

    p(f"eBay-Revise-Report: {len(listing_rows)} aktive Angebote gelesen.")
    if not listing_rows:
        return {"total": 0}

    from lib.article_db import (open_db, upsert_ebay_listings, get_ebay_listings,
                                query_by_supplier_pids, set_ebay_listing_status)
    con = open_db(db_path)
    n_registry = upsert_ebay_listings(con, listing_rows)
    p(f"eBay-Registry aktualisiert: {n_registry} SKU→ItemID-Zuordnungen.", tag="dim")

    listings = get_ebay_listings(con, skus)
    articles = query_by_supplier_pids(con, skus, active_only=False)
    by_pid = {}
    for art in articles:
        by_pid.setdefault(art["supplier_pid"], art)

    revise_rows, end_rows, missing = [], [], []
    ended_skus = []
    for sku in skus:
        art = by_pid.get(sku)
        listing = listings.get(sku)
        if not art or not listing:
            missing.append(sku)
            continue
        stock = 0
        try:
            stock = int(float(str(art.get("stock_qty") or "0").replace(",", ".")))
        except ValueError:
            stock = 0
        if stock > 0 and art.get("active", 1):
            revise_rows.append(build_revise_row(art, listing))
        else:
            end_rows.append(build_end_row(listing["item_id"]))
            ended_skus.append(sku)

    if ended_skus:
        set_ebay_listing_status(con, ended_skus, "ended")

    ts = _now_stamp()
    out = {}
    if revise_rows:
        path = os.path.join(out_dir, f"eBay_Revise_{ts}.csv")
        _write_csv(path, [_REVISE_INFO_LINE], _REVISE_HEADER, revise_rows)
        out["revise"] = path
        p(f"eBay Revise: {len(revise_rows)} Artikel aktualisiert → {os.path.basename(path)}", tag="ok")
    if end_rows:
        path = os.path.join(out_dir, f"eBay_Beenden_{ts}.csv")
        _write_csv(path, [], _END_HEADER, end_rows)
        out["beenden"] = path
        p(f"eBay Beenden (Bestand 0/nicht mehr aktiv): {len(end_rows)} Artikel → "
          f"{os.path.basename(path)}", tag="ok")
    if missing:
        p(f"⚠ {len(missing)} SKU(s) aus dem eBay-Report nicht (mehr) in der Artikel-DB: "
          f"{', '.join(missing[:20])}" + (" ..." if len(missing) > 20 else ""), tag="warn")

    return {
        "total": len(listing_rows), "revise": len(revise_rows),
        "beenden": len(end_rows), "missing": len(missing), "files": out,
    }


# ── Bootstrap: Kategorie-Mapping aus alten, bereits ausgefüllten Batches ──────

def learn_category_map(history_csv_path: str, db_path: str, base_dir: str,
                       progress_cb=None) -> dict:
    """
    Liest eine alte, bereits manuell mit Category ID befüllte Draft-Datei und
    lernt daraus catalog_group_id -> eBay Category ID (über die SKU der
    jeweiligen Zeile). Schreibt NUR in bisher leere ebay_category_id-Zellen
    von channels/channel_category_mapping.csv – vorhandene (auch von Hand für
    andere Kanäle wie Kaufland/Conrad gepflegte) Werte bleiben unangetastet.
    """
    p = progress_cb or (lambda m, **kw: None)

    try:
        with open(history_csv_path, encoding="utf-8-sig") as f:
            raw = f.read()
    except UnicodeDecodeError:
        with open(history_csv_path, encoding="cp1252", errors="replace") as f:
            raw = f.read()

    lines = [l for l in raw.splitlines() if l and not l.startswith("#INFO")]
    if not lines:
        return {"learned": 0}
    reader = csv.DictReader(lines, delimiter=";")

    sku_to_category = {}
    for row in reader:
        sku = (row.get("Custom label (SKU)") or "").strip()
        cat = (row.get("Category ID") or "").strip()
        if sku and cat:
            sku_to_category[sku] = cat

    p(f"eBay-Kategorie-Lernen: {len(sku_to_category)} SKUs mit Category ID in Altdatei.")
    if not sku_to_category:
        return {"learned": 0}

    from lib.article_db import open_db, query_by_supplier_pids
    con = open_db(db_path)
    articles = query_by_supplier_pids(con, list(sku_to_category.keys()), active_only=False)

    learned = {}   # group_id -> {category_id: {"count": n}}
    for art in articles:
        cat = sku_to_category.get(art["supplier_pid"])
        gid = _leaf_group_id(art)
        if not cat or not gid:
            continue
        entry = learned.setdefault(gid.upper(), {})
        entry.setdefault(cat, {"count": 0})
        entry[cat]["count"] += 1

    # Bei uneindeutigen Fällen (mehrere Category IDs für dieselbe Gruppe):
    # die häufigste gewinnt.
    updates = {}
    for gid, cats in learned.items():
        best_cat, _best = max(cats.items(), key=lambda kv: kv[1]["count"])
        updates[gid] = best_cat

    from lib.channel_mapping import fill_channel_category
    filled = fill_channel_category(base_dir, "ebay", updates)

    p(f"eBay-Kategorie-Lernen: {len(updates)} Kataloggruppen aus Altdatei erkannt, "
      f"{filled} leere Zellen in channel_category_mapping.csv befüllt.", tag="ok")
    return {"learned": filled}
