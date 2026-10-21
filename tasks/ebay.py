# tasks/ebay.py – eBay File-Exchange Tasks
#
# Eingabedateien werden manuell in in_BME abgelegt (kein FTP-Download – die
# SKU-Liste kommt vom Vertrieb, der Revise-Report von eBay selbst):
#   ebay_sku_liste.csv        – Task A: SKU-Liste → Neuanlage / Revise / Beenden
#   ebay_revise_download.csv  – Task B: eBay-eigener Report → Bestand/Preis sync
#   ebay_kategorie_lernen.csv – Task C: alte, ausgefüllte Draft-Datei →
#                                ebay_category_map.csv lernen
#   eBay-edit-price-quantity-template.csv (BASE_DIR) – Task D: aktive Angebote
#                                + BestandBueroring.csv (in_BME) → Revise/End
#
# Ausgabedateien landen in export_dir/ebay/ mit sprechendem Namen + Timestamp
# (z.B. eBay_Neuanlage_20260427_143012.csv) – Task D landet stattdessen direkt
# in BASE_DIR/eBay/ (eBay-Revise_<Datum_Uhrzeit>.csv / eBay-end_<Datum_Uhrzeit>.csv).

import os
from config import DB_PATH, DIRS, BASE_DIR, EXPORT_DIR

_IMAGE_BASE = "https://www.officexl.de/whitelabels/officexl/images/thumbnails/zoom"


def _out_dir() -> str:
    d = os.path.join(EXPORT_DIR, "ebay")
    os.makedirs(d, exist_ok=True)
    return d


def run_sku_liste(progress_cb=None, file_progress_cb=None) -> dict:
    """Task A: manuelle SKU-Liste (Vertrieb) → Neuanlage/Revise/Beenden."""
    p = progress_cb or (lambda m, **kw: None)
    from lib.ebay_export import process_sku_list

    in_path = os.path.join(DIRS["in_bme"], "ebay_sku_liste.csv")
    if not os.path.exists(in_path):
        p(f"eBay-SKU-Liste: Datei nicht gefunden: {in_path}", tag="warn")
        p("Bitte SKU-Liste (eine SKU pro Zeile) als 'ebay_sku_liste.csv' "
          "nach in_BME legen.", tag="warn")
        return {}

    return process_sku_list(in_path, DB_PATH, BASE_DIR, _out_dir(), _IMAGE_BASE,
                            progress_cb=p)


def run_revise_sync(progress_cb=None, file_progress_cb=None) -> dict:
    """Task B: von eBay heruntergeladener Revise-Report → Bestand/Preis sync."""
    p = progress_cb or (lambda m, **kw: None)
    from lib.ebay_export import sync_active_listings

    in_path = os.path.join(DIRS["in_bme"], "ebay_revise_download.csv")
    if not os.path.exists(in_path):
        p(f"eBay-Revise-Report: Datei nicht gefunden: {in_path}", tag="warn")
        p("Bitte den von eBay heruntergeladenen Report als "
          "'ebay_revise_download.csv' nach in_BME legen.", tag="warn")
        return {}

    return sync_active_listings(in_path, DB_PATH, _out_dir(), progress_cb=p)


def run_learn_category_map(progress_cb=None, file_progress_cb=None) -> dict:
    """Task C: alte, bereits ausgefüllte Draft-Datei → ebay_category_map.csv lernen."""
    p = progress_cb or (lambda m, **kw: None)
    from lib.ebay_export import learn_category_map

    in_path = os.path.join(DIRS["in_bme"], "ebay_kategorie_lernen.csv")
    if not os.path.exists(in_path):
        p(f"eBay-Kategorie-Lernen: Datei nicht gefunden: {in_path}", tag="warn")
        p("Bitte eine alte, bereits mit Category ID ausgefüllte Draft-Datei "
          "als 'ebay_kategorie_lernen.csv' nach in_BME legen.", tag="warn")
        return {}

    return learn_category_map(in_path, DB_PATH, BASE_DIR, progress_cb=p)


def _fetch_edi_bestand(edi_path: str, dest_path: str, p) -> bool:
    """
    Kopiert BestandBueroring.csv vom EDI-Netzlaufwerk nach dest_path (in_BME).
    Nicht erreichbar/fehlend → Warnung, vorhandene in_BME-Datei bleibt.
    """
    import shutil
    import datetime as _dt
    try:
        if not os.path.isfile(edi_path):
            p(f"eBay-Bestand-Revise: EDI-Datei nicht gefunden: {edi_path} "
              f"– verwende vorhandene BestandBueroring_EDI.csv, falls vorhanden.", tag="warn")
            return False
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        tmp = dest_path + ".tmp"
        shutil.copy2(edi_path, tmp)
        from lib.utils import safe_replace
        safe_replace(tmp, dest_path, p=p)
        stamp = _dt.datetime.fromtimestamp(os.path.getmtime(dest_path))
        size  = f"{os.path.getsize(dest_path):,}".replace(",", ".")
        p(f"eBay-Bestand-Revise: EDI-Bestand übernommen → BestandBueroring_EDI.csv "
          f"(Stand {stamp:%d.%m.%Y %H:%M}, {size} Bytes).", tag="ok")
        return True
    except Exception as e:
        p(f"eBay-Bestand-Revise: EDI-Datei konnte nicht kopiert werden ({e}) "
          f"– verwende vorhandene BestandBueroring_EDI.csv, falls vorhanden.", tag="warn")
        return False


def _collect_bestand_paths(p) -> list:
    """
    EDI-Bestand vom Netzlaufwerk nach in_BME holen (eigene Datei) und die
    vorhandenen Bestandsdateien in Prioritätsreihenfolge (EDI vor FTP)
    zurückgeben. Leere Liste = keine Bestandsdatei vorhanden (Warnung im Log).
    """
    bestand_ftp = os.path.join(DIRS["in_bme"], "BestandBueroring.csv")
    bestand_edi = os.path.join(DIRS["in_bme"], "BestandBueroring_EDI.csv")

    # Zweiten Bestand vom EDI-Netzlaufwerk holen (DIRS.brg_bestand_edi,
    # Reiter "Pfade"). Wird als eigene Datei BestandBueroring_EDI.csv nach
    # in_BME kopiert – die per FTP geladene BestandBueroring.csv bleibt
    # unangetastet. Beide werden zusammengeführt, EDI hat Vorrang.
    edi_src = (DIRS.get("brg_bestand_edi") or "").strip()
    if edi_src:
        _fetch_edi_bestand(edi_src, bestand_edi, p)
    else:
        p("eBay-Bestand: kein EDI-Pfad konfiguriert (Pfade → brg_bestand_edi) "
          "– nur FTP-Bestand.", tag="dim")

    paths = [pth for pth in (bestand_edi, bestand_ftp) if os.path.exists(pth)]
    if not paths:
        p(f"eBay-Bestand: keine Bestandsdatei gefunden ({bestand_ftp}, {bestand_edi})",
          tag="warn")
        p("Bitte den Büroring-Download ausführen (lädt BestandBueroring.csv nach "
          "in_BME) und/oder den EDI-Pfad prüfen.", tag="warn")
    elif len(paths) < 2:
        p(f"eBay-Bestand: nur eine Bestandsdatei vorhanden: "
          f"{os.path.basename(paths[0])}", tag="warn")
    return paths


def run_bestand_revise(progress_cb=None, file_progress_cb=None) -> dict:
    """
    Task D: aktive eBay-Angebote (eBay-edit-price-quantity-template.csv,
    BASE_DIR) + BestandBueroring_EDI.csv (vom EDI-Laufwerk DIRS.brg_bestand_edi
    nach in_BME kopiert) + BestandBueroring.csv (per FTP, in_BME); beide
    zusammengeführt, EDI hat Vorrang →
    eBay-Revise_<Datum_Uhrzeit>.csv (Bestand aktualisiert) + eBay-end_<Datum_Uhrzeit>.csv
    (Bestand 0) in BASE_DIR/eBay.
    """
    p = progress_cb or (lambda m, **kw: None)
    from lib.ebay_export import build_revise_end_from_bestand

    template_path = os.path.join(BASE_DIR, "eBay-edit-price-quantity-template.csv")

    if not os.path.exists(template_path):
        p(f"eBay-Bestand-Revise: Datei nicht gefunden: {template_path}", tag="warn")
        p("Bitte die aktuellen aktiven Angebote als "
          "'eBay-edit-price-quantity-template.csv' nach BASE_DIR legen.", tag="warn")
        return {}

    bestand_paths = _collect_bestand_paths(p)
    if not bestand_paths:
        return {}

    out_dir = os.path.join(BASE_DIR, "eBay")
    return build_revise_end_from_bestand(template_path, bestand_paths, out_dir,
                                         progress_cb=p)


# ══════════════════════════════════════════════════════════════════════════════
# eBay API (Trading API, OAuth) – siehe lib/ebay_api.py
# ══════════════════════════════════════════════════════════════════════════════

def _ebay_cfg(p):
    from config import CONNECTIONS
    from lib.ebay_api import resolve_config
    env, cfg = resolve_config(CONNECTIONS)
    p(f"eBay API: Umgebung {env.upper()} "
      f"({'Testsystem, keine echten Angebote' if env == 'sandbox' else 'LIVE – echte Angebote'})",
      tag="warn" if env == "production" else "dim")
    return env, cfg


def _write_report(name: str, header: list, rows: list) -> str:
    import csv
    from datetime import datetime
    out_dir = os.path.join(BASE_DIR, "eBay")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{name}_{datetime.now():%Y%m%d_%H%M}.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(header)
        w.writerows(rows)
    return path


def run_api_listings(progress_cb=None, file_progress_cb=None) -> dict:
    """
    Nur lesend: aktive Angebote per API abrufen, als CSV ablegen und – falls
    vorhanden – mit eBay-edit-price-quantity-template.csv (BASE_DIR) vergleichen.
    """
    p = progress_cb or (lambda m, **kw: None)
    from lib.ebay_api import get_active_listings, get_user, EbayError
    try:
        env, cfg = _ebay_cfg(p)
        u = get_user(cfg)
        p(f"eBay API: angemeldet als {u.get('user_id', '?')}")
        items = get_active_listings(cfg, progress_cb=p)
    except EbayError as e:
        p(f"eBay API: {e}", tag="err")
        return {}

    with_sku = [i for i in items if i["sku"]]
    p(f"eBay API: {len(items)} aktive Angebote, davon {len(with_sku)} mit SKU, "
      f"{len(items) - len(with_sku)} ohne SKU", tag="ok")
    path = _write_report("ebay_api_angebote",
                         ["item_id", "sku", "title", "quantity", "quantity_sold", "price", "currency", "listing_type"],
                         [[i[k] for k in ("item_id", "sku", "title", "quantity", "quantity_sold",
                                          "price", "currency", "listing_type")] for i in items])
    p(f"Liste: {os.path.basename(path)}")

    # Vergleich mit dem manuell heruntergeladenen Template
    template_path = os.path.join(BASE_DIR, "eBay-edit-price-quantity-template.csv")
    if os.path.exists(template_path):
        import csv
        try:
            with open(template_path, encoding="utf-8-sig") as f:
                raw = f.read()
        except UnicodeDecodeError:
            with open(template_path, encoding="cp1252", errors="replace") as f:
                raw = f.read()
        lines = raw.splitlines()
        if lines and lines[0].startswith("#INFO"):
            lines = lines[1:]
        tpl = {(r.get("Item number") or "").strip(): r
               for r in csv.DictReader(lines, delimiter=";")}
        api = {i["item_id"]: i for i in items}
        only_tpl = sorted(set(tpl) - set(api))
        only_api = sorted(set(api) - set(tpl))
        qty_diff = [(iid, tpl[iid].get("Available quantity", ""), api[iid]["quantity"])
                    for iid in set(tpl) & set(api)
                    if (tpl[iid].get("Available quantity") or "").strip() != str(api[iid]["quantity"])]
        sku_diff = [(iid, tpl[iid].get("Custom label (SKU)", ""), api[iid]["sku"])
                    for iid in set(tpl) & set(api)
                    if (tpl[iid].get("Custom label (SKU)") or "").strip() != api[iid]["sku"]]
        price_diff = [(iid, (tpl[iid].get("Start price") or "").strip(), api[iid]["price"])
                      for iid in set(tpl) & set(api)
                      if _price_differs((tpl[iid].get("Start price") or "").replace(",", "."), api[iid]["price"])]
        p(f"Vergleich mit Template ({len(tpl)} Angebote): "
          f"{len(only_tpl)} nur im Template, {len(only_api)} nur per API, "
          f"{len(qty_diff)} Mengen-Abweichungen, {len(price_diff)} Preis-Abweichungen, "
          f"{len(sku_diff)} SKU-Abweichungen",
          tag="ok" if not (only_tpl or only_api or sku_diff or price_diff) else "warn")
        if price_diff:
            p("Preis-Abweichungen (Template / aktuell bei eBay) – diese Preise würde "
              "'eBay – Bestand per API aktualisieren' setzen:", tag="warn")
        for iid, a, b in sorted(price_diff):
            p(f"  Preis {iid}  {api[iid]['sku']:<18} Template {a} / eBay {b}", tag="dim")
        for iid in only_tpl[:10]:
            p(f"  nur Template: {iid}", tag="dim")
        for iid in only_api[:10]:
            p(f"  nur API:      {iid}  {api[iid]['sku']}  {api[iid]['title'][:50]}", tag="dim")
        for iid, a, b in qty_diff[:10]:
            p(f"  Menge {iid}: Template {a} / API {b}", tag="dim")
        for iid, a, b in sku_diff[:10]:
            p(f"  SKU   {iid}: Template '{a}' / API '{b}'", tag="dim")
    else:
        p("Kein Template zum Vergleich vorhanden (eBay-edit-price-quantity-template.csv).", tag="dim")
    return {"total": len(items), "with_sku": len(with_sku), "file": path}


def _load_template_prices(p) -> dict:
    """
    Preise aus eBay-edit-price-quantity-template.csv (BASE_DIR):
    {item_id: "12.34"}. Die Datei ist der eBay-Export der aktiven Angebote;
    wird dort "Start price" geändert, sendet der API-Task den neuen Preis.
    Fehlt die Datei → {} (Preise bleiben unverändert).
    """
    import csv
    path = os.path.join(BASE_DIR, "eBay-edit-price-quantity-template.csv")
    if not os.path.exists(path):
        p("Kein eBay-edit-price-quantity-template.csv im Stammverzeichnis – Preise bleiben "
          "wie bei eBay.", tag="dim")
        return {}
    try:
        with open(path, encoding="utf-8-sig") as f:
            raw = f.read()
    except UnicodeDecodeError:
        with open(path, encoding="cp1252", errors="replace") as f:
            raw = f.read()
    lines = raw.splitlines()
    if lines and lines[0].startswith("#INFO"):
        lines = lines[1:]
    prices = {}
    for r in csv.DictReader(lines, delimiter=";"):
        iid = (r.get("Item number") or "").strip()
        price = (r.get("Start price") or "").strip().replace(",", ".")
        if iid and price:
            try:
                prices[iid] = f"{float(price):.2f}"
            except ValueError:
                pass
    import datetime as _dt
    stamp = _dt.datetime.fromtimestamp(os.path.getmtime(path))
    p(f"Preisquelle: eBay-edit-price-quantity-template.csv ({len(prices)} Preise, "
      f"Stand {stamp:%d.%m.%Y %H:%M})")
    return prices


def _price_differs(a: str, b: str) -> bool:
    try:
        return abs(float(a) - float(b)) >= 0.005
    except (TypeError, ValueError):
        return False


def _plan_api_changes(items: list, stock_map: dict, prices: dict = None) -> tuple[list, list, dict]:
    """
    Returns (revise, end, stats).
      revise: [{item_id, sku, old, quantity, price_old, price}]  – quantity/price None = unverändert
      end:    [{item_id, sku, old}]
    Preis wird nur gesetzt, wenn er im Template vom aktuellen eBay-Preis abweicht.
    """
    prices = prices or {}
    revise, end = [], []
    stats = {"no_sku": 0, "not_in_bestand": 0, "unchanged": 0, "price_changes": 0}
    for it in items:
        sku = it["sku"]
        iid = it["item_id"]
        new_price = prices.get(iid)
        price_change = new_price is not None and _price_differs(new_price, it["price"])
        if not sku:
            stats["no_sku"] += 1
            if price_change:   # Preisänderung auch ohne SKU möglich (Item number reicht)
                revise.append({"item_id": iid, "sku": sku, "old": it["quantity"], "quantity": None,
                               "price_old": it["price"], "price": new_price})
                stats["price_changes"] += 1
            continue
        if sku not in stock_map:
            stats["not_in_bestand"] += 1
            if price_change:
                revise.append({"item_id": iid, "sku": sku, "old": it["quantity"], "quantity": None,
                               "price_old": it["price"], "price": new_price})
                stats["price_changes"] += 1
            continue
        stock = stock_map[sku]
        if stock <= 0:
            end.append({"item_id": iid, "sku": sku, "old": it["quantity"]})
            continue
        qty_change = stock != it["quantity"]
        if qty_change or price_change:
            revise.append({"item_id": iid, "sku": sku, "old": it["quantity"],
                           "quantity": stock if qty_change else None,
                           "price_old": it["price"], "price": new_price if price_change else None})
            if price_change:
                stats["price_changes"] += 1
        else:
            stats["unchanged"] += 1
    return revise, end, stats


def run_api_bestand(progress_cb=None, file_progress_cb=None, live: bool = False) -> dict:
    """
    Bestand der aktiven eBay-Angebote per API aktualisieren.
    live=False: Probelauf – nur Plan (Log + CSV), nichts wird gesendet.
    live=True:  ReviseInventoryStatus (neue Menge) / EndFixedPriceItem (Bestand 0).
    """
    p = progress_cb or (lambda m, **kw: None)
    from lib.ebay_api import (get_active_listings, revise_inventory_status,
                              end_fixed_price_item, EbayError)
    from lib.ebay_export import load_stock_map

    mode = "LIVE" if live else "PROBELAUF"
    p(f"eBay API Bestand – {mode}")
    bestand_paths = _collect_bestand_paths(p)
    if not bestand_paths:
        return {}
    stock_map = load_stock_map(bestand_paths, p)

    try:
        env, cfg = _ebay_cfg(p)
        items = get_active_listings(cfg, progress_cb=p)
    except EbayError as e:
        p(f"eBay API: {e}", tag="err")
        return {}

    prices = _load_template_prices(p)
    revise, end, stats = _plan_api_changes(items, stock_map, prices)
    n_qty = sum(1 for r in revise if r["quantity"] is not None)
    p(f"{len(items)} aktive Angebote: {n_qty} Menge ändern, {stats['price_changes']} Preis ändern, "
      f"{len(end)} beenden, {stats['unchanged']} unverändert, {stats['no_sku']} ohne SKU, "
      f"{stats['not_in_bestand']} SKU nicht im Bestand",
      tag="ok")
    _show = revise if not live else revise[:20]
    for r in _show:
        parts = []
        if r["quantity"] is not None:
            parts.append(f"Menge {r['old']} → {r['quantity']}")
        if r["price"] is not None:
            parts.append(f"Preis {r['price_old']} → {r['price']}")
        p(f"  Revise {r['item_id']}  {r['sku']:<18} {', '.join(parts)}", tag="dim")
    for e in end[:15]:
        p(f"  Ende   {e['item_id']}  {e['sku']:<18} {e['old']} → 0", tag="dim")
    if len(revise) > len(_show) or len(end) > 15:
        p("  … (vollständig im Report)", tag="dim")

    _hdr = ["aktion", "item_id", "sku", "menge_alt", "menge_neu", "preis_alt", "preis_neu", "status", "meldung"]
    rows = [["revise", r["item_id"], r["sku"], r["old"],
             r["quantity"] if r["quantity"] is not None else "",
             r["price_old"], r["price"] if r["price"] is not None else "", "", ""] for r in revise] + \
           [["end", e["item_id"], e["sku"], e["old"], 0, "", "", "", ""] for e in end]
    result = {"total": len(items), "revise": len(revise), "end": len(end), **stats,
              "sent": 0, "failed": 0, "live": live}

    if not live:
        path = _write_report("ebay_api_probelauf", _hdr, rows)
        p(f"Probelauf-Report: {os.path.basename(path)} – es wurde NICHTS gesendet.", tag="ok")
        result["file"] = path
        return result

    if not revise and not end:
        p("Keine Änderungen – nichts zu senden.", tag="ok")
        return result

    # ── Senden ────────────────────────────────────────────────────────────────
    sent = failed = 0
    status = {}
    if revise:
        p(f"Sende {len(revise)} Änderungen (ReviseInventoryStatus, je 4 pro Aufruf) ...")
        res = revise_inventory_status(cfg, [{"item_id": r["item_id"], "quantity": r["quantity"],
                                             "price": r["price"]} for r in revise])
        for r in res:
            status[r["item_id"]] = ("OK" if r["ok"] else "FEHLER", r["message"])
            if r["ok"]:
                sent += 1
            else:
                failed += 1
                p(f"  ✗ {r['item_id']}: {r['message']}", tag="err")
    if end:
        p(f"Beende {len(end)} Angebote (EndFixedPriceItem) ...")
        for i, e in enumerate(end, 1):
            r = end_fixed_price_item(cfg, e["item_id"])
            status[r["item_id"]] = ("OK" if r["ok"] else "FEHLER", r["message"])
            if r["ok"]:
                sent += 1
            else:
                failed += 1
                p(f"  ✗ {r['item_id']}: {r['message']}", tag="err")
            if file_progress_cb:
                try:
                    file_progress_cb(i, len(end))
                except Exception:
                    pass
    for row in rows:
        st = status.get(str(row[1]))
        if st:
            row[7], row[8] = st
    path = _write_report("ebay_api_live", _hdr, rows)
    p(f"Gesendet: {sent} OK, {failed} Fehler – Report: {os.path.basename(path)}",
      tag="ok" if not failed else "warn")
    result.update({"sent": sent, "failed": failed, "file": path})
    return result


def run_api_bestand_dry(progress_cb=None, file_progress_cb=None) -> dict:
    return run_api_bestand(progress_cb, file_progress_cb, live=False)


def run_api_bestand_live(progress_cb=None, file_progress_cb=None) -> dict:
    return run_api_bestand(progress_cb, file_progress_cb, live=True)


def run_sandbox_test_listings(progress_cb=None, file_progress_cb=None) -> dict:
    """
    Nur Sandbox: 3 Testangebote mit echten SKUs aus den Bestandsdateien anlegen,
    damit der Bestands-Task dort etwas zum Aktualisieren hat.
    """
    p = progress_cb or (lambda m, **kw: None)
    from lib.ebay_api import add_test_listing, EbayError
    from lib.ebay_export import load_stock_map
    try:
        env, cfg = _ebay_cfg(p)
    except EbayError as e:
        p(f"eBay API: {e}", tag="err")
        return {}
    if env != "sandbox":
        p("Testangebote werden nur in der Sandbox angelegt – Umgebung steht auf production. "
          "Konfiguration → Verbindungen → ebay → environment = sandbox", tag="err")
        return {}
    paths = _collect_bestand_paths(p)
    stock = load_stock_map(paths, p) if paths else {}
    skus = [s for s, q in stock.items() if q > 0][:3] or ["TEST-SKU-1", "TEST-SKU-2", "TEST-SKU-3"]
    created = []
    for sku in skus:
        try:
            iid = add_test_listing(cfg, sku, f"Testartikel {sku} (Sandbox)", quantity=99)
            created.append((iid, sku))
            p(f"  angelegt: {iid}  SKU {sku}  Menge 99", tag="ok")
        except EbayError as e:
            p(f"  ✗ {sku}: {e}", tag="err")
    p(f"{len(created)} Testangebote angelegt. Danach: 'eBay API – Bestand aktualisieren (Probelauf)'.",
      tag="ok" if created else "warn")
    return {"created": created}
