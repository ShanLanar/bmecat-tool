# lib/diff_report.py – Artikel-Diff zwischen Läufen
#
# Vergleicht eine frisch erzeugte BMEcat-XML mit dem vorherigen Stand:
#   - Neue Artikel (SUPPLIER_AID neu)
#   - Gelöschte Artikel (SUPPLIER_AID fehlt)
#   - Preisänderungen (ARTICLE_PRICE geändert)
#
# Arbeitsweise:
#   1. Vor dem Upload: Snapshot der AIDs + Preise aus der bestehenden Datei (Backup)
#   2. Nach dem Merge: Snapshot der neuen Datei
#   3. Vergleich → diff_report_{datei}_{datum}.json
#
# Performance: Regex-basiert, verarbeitet 470 MB XML in ~5 Sekunden.

import os
import re
import json
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

# Regex für schnelle AID + Preis-Extraktion
_AID_PAT   = re.compile(r"<SUPPLIER_AID>(.*?)</SUPPLIER_AID>", re.IGNORECASE)
_PRICE_PAT = re.compile(
    r"<ARTICLE_PRICE[^>]*type\s*=\s*\"net_list\"[^>]*>.*?"
    r"<PRICE_AMOUNT>(.*?)</PRICE_AMOUNT>.*?</ARTICLE_PRICE>",
    re.IGNORECASE | re.DOTALL)
_ARTICLE_BLOCK = re.compile(
    r"<ARTICLE[\s>](.*?)</ARTICLE>",
    re.IGNORECASE | re.DOTALL)


def extract_article_snapshot(xml_path: str, progress_cb=None) -> dict:
    """
    Extrahiert AIDs und Preise aus einer BMEcat-XML (streaming, zeilenweise).
    Auch für 470+ MB Dateien geeignet ohne alles in RAM zu laden.

    Returns:
        dict: {supplier_aid: {"price": float_or_None}}
    """
    p = progress_cb or (lambda m, **kw: None)
    snapshot = {}

    if not os.path.exists(xml_path):
        return snapshot

    # Zeilenweiser State-Machine-Parser
    in_article = False
    current_aid = None
    current_price = None

    try:
        with open(xml_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                upper = line.upper()

                # Artikel-Anfang: <ARTICLE> oder <ARTICLE ... >, aber nicht <ARTICLE_PRICE> etc.
                if re.search(r"<ARTICLE[\s>]", upper) and "</ARTICLE" not in upper:
                    in_article = True
                    current_aid = None
                    current_price = None
                    continue

                if in_article:
                    # AID extrahieren
                    if current_aid is None:
                        m = _AID_PAT.search(line)
                        if m:
                            current_aid = m.group(1).strip()

                    # Preis extrahieren (erste PRICE_AMOUNT im Artikel)
                    if current_price is None and "PRICE_AMOUNT" in upper:
                        m = re.search(
                            r"<PRICE_AMOUNT>(.*?)</PRICE_AMOUNT>",
                            line, re.IGNORECASE)
                        if m:
                            try:
                                current_price = float(
                                    m.group(1).strip().replace(",", "."))
                            except (ValueError, AttributeError):
                                pass

                    # Artikel-Ende
                    if re.search(r"</ARTICLE[\s>]", upper):
                        if current_aid:
                            snapshot[current_aid] = {"price": current_price}
                        in_article = False

    except Exception as e:
        p(f"Diff: Kann {os.path.basename(xml_path)} nicht lesen: {e}", tag="warn")

    return snapshot


def compare_snapshots(old: dict, new: dict) -> dict:
    """
    Vergleicht zwei Snapshots.

    Returns:
        dict mit:
            added:   [aid, ...]          – neue Artikel
            removed: [aid, ...]          – gelöschte Artikel
            price_changed: [{aid, old_price, new_price}, ...]
            unchanged: int               – Anzahl unveränderter Artikel
    """
    old_aids = set(old.keys())
    new_aids = set(new.keys())

    added   = sorted(new_aids - old_aids)
    removed = sorted(old_aids - new_aids)

    price_changed = []
    unchanged = 0

    for aid in old_aids & new_aids:
        old_price = old[aid].get("price")
        new_price = new[aid].get("price")
        if old_price != new_price and (old_price is not None or new_price is not None):
            price_changed.append({
                "aid":       aid,
                "old_price": old_price,
                "new_price": new_price,
            })
        else:
            unchanged += 1

    return {
        "added":         added,
        "removed":       removed,
        "price_changed": price_changed,
        "unchanged":     unchanged,
    }


def create_diff_report(xml_path: str, backup_dir: str = None,
                       progress_cb=None) -> dict | None:
    """
    Erzeugt einen Diff-Report für eine XML-Datei.

    Vergleicht die aktuelle Datei mit dem letzten Backup.
    Erstellt dann ein neues Backup für den nächsten Lauf.

    Args:
        xml_path:   Pfad zur aktuellen XML
        backup_dir: Verzeichnis für Backups (Standard: logs/diff_backups/)
        progress_cb: Log-Callback

    Returns:
        Diff-Dict oder None wenn kein vorheriger Stand vorhanden
    """
    p = progress_cb or (lambda m, **kw: None)
    basename = os.path.basename(xml_path)
    stem = os.path.splitext(basename)[0]

    if backup_dir is None:
        try:
            import config
            backup_dir = os.path.join(config.DIRS["logs"], "diff_backups")
        except Exception:
            backup_dir = os.path.join(os.path.dirname(xml_path), "diff_backups")

    Path(backup_dir).mkdir(parents=True, exist_ok=True)

    snapshot_file = os.path.join(backup_dir, f"{stem}_snapshot.json")

    # 1. Aktuellen Stand extrahieren
    p(f"Diff: Extrahiere Artikel aus {basename} ...")
    new_snapshot = extract_article_snapshot(xml_path, progress_cb=p)

    if not new_snapshot:
        p(f"Diff: Keine Artikel in {basename} – überspringe.", tag="warn")
        return None

    # 2. Vorherigen Stand laden (wenn vorhanden)
    old_snapshot = {}
    if os.path.exists(snapshot_file):
        try:
            with open(snapshot_file, "r", encoding="utf-8") as f:
                old_snapshot = json.load(f)
        except Exception:
            old_snapshot = {}

    # 3. Vergleich
    if old_snapshot:
        diff = compare_snapshots(old_snapshot, new_snapshot)

        n_add = len(diff["added"])
        n_rem = len(diff["removed"])
        n_chg = len(diff["price_changed"])
        n_unc = diff["unchanged"]

        p(f"Diff {basename}: +{n_add} neu, -{n_rem} gelöscht, "
          f"~{n_chg} Preisänderungen, ={n_unc} unverändert")

        if n_add > 0:
            p(f"  Beispiele neu: {', '.join(diff['added'][:5])}"
              f"{'...' if n_add > 5 else ''}", tag="ok")
        if n_rem > 0:
            p(f"  Beispiele gelöscht: {', '.join(diff['removed'][:5])}"
              f"{'...' if n_rem > 5 else ''}", tag="warn")
        if n_chg > 0:
            examples = diff["price_changed"][:3]
            for ex in examples:
                p(f"  Preisänderung: {ex['aid']}  "
                  f"{ex['old_price']} → {ex['new_price']}", tag="info")

        # Report als JSON speichern
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = os.path.join(backup_dir, f"diff_{stem}_{ts}.json")
        report_data = {
            "datei":      basename,
            "zeitpunkt":  datetime.now().isoformat(),
            "artikel_alt": len(old_snapshot),
            "artikel_neu": len(new_snapshot),
            "hinzugefuegt": n_add,
            "entfernt":     n_rem,
            "preisaenderungen": n_chg,
            "unveraendert": n_unc,
            "details": {
                "added":   diff["added"][:100],      # max 100 pro Kategorie
                "removed": diff["removed"][:100],
                "price_changed": diff["price_changed"][:100],
            }
        }
        try:
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(report_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.warning("Diff-Report konnte nicht geschrieben werden: %s", e)
    else:
        p(f"Diff {basename}: Erster Lauf – kein Vergleich möglich, "
          f"Baseline mit {len(new_snapshot)} Artikeln gespeichert.")
        diff = None

    # 4. Neuen Snapshot als Backup speichern
    try:
        with open(snapshot_file, "w", encoding="utf-8") as f:
            json.dump(new_snapshot, f, ensure_ascii=False)
    except Exception as e:
        log.warning("Snapshot konnte nicht geschrieben werden: %s", e)

    return diff
