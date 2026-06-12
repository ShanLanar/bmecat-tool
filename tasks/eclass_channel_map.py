# tasks/eclass_channel_map.py – Brücke ECLASS → Marktplatz-Kanäle
#
# Liest die ECLASS-Endknoten aus channels/article_eclass_categories.csv
# (erzeugt vom Task "ECLASS-Analyse") und pflegt daraus
# channels/eclass_channel_mapping.csv: jede ECLASS-Kategorie wird EINMAL pro
# Kanal gemappt und gilt dann lieferantenübergreifend.

import csv
import logging
import os
from datetime import datetime

import config as _cfg
from lib.channel_mapping import (
    CHANNELS, CHANNEL_LABELS,
    add_missing_eclass_mappings, eclass_mapping_path,
    find_unmapped, load_eclass_mappings,
)
from lib.eclass_intelligence import collect_leaf_usage

log = logging.getLogger(__name__)

_ARTICLE_CSV_REL = os.path.join("channels", "article_eclass_categories.csv")


def _write_gap_report(base_dir: str, unmapped: dict,
                      mappings: dict, usage: dict) -> str:
    """Schreibt logs/unmapped_eclass_categories_DATUM.csv (nach Nutzung sortiert)."""
    logs_dir = _cfg.DIRS.get("logs", base_dir)
    os.makedirs(logs_dir, exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(logs_dir, f"unmapped_eclass_categories_{ts}.csv")

    # Codes die in mindestens einem Kanal fehlen
    missing: set = set()
    for codes in unmapped.values():
        missing.update(codes)

    # Häufig genutzte Kategorien zuerst → größter Hebel beim manuellen Mappen
    ordered = sorted(missing,
                     key=lambda eid: usage.get(eid, {}).get("count", 0),
                     reverse=True)

    header = ["eclass_id", "eclass_version", "eclass_name", "article_count"] + [
        CHANNEL_LABELS[ch] for ch in CHANNELS
    ]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(header)
        for eid in ordered:
            u     = usage.get(eid, {})
            entry = mappings.get(eid.upper(), {})
            row = [eid, u.get("eclass_version", ""),
                   u.get("eclass_name", ""), u.get("count", "")]
            row += [entry.get(ch, "") for ch in CHANNELS]
            writer.writerow(row)

    return path


def run(progress_cb=None):
    """
    Task: ECLASS-Endknoten zu Marktplatz-Kanälen mappen.

    Ablauf:
      1. article_eclass_categories.csv lesen (vom Task "ECLASS-Analyse")
      2. Genutzte ECLASS-Endknoten + Häufigkeit sammeln
      3. Neue Endknoten in eclass_channel_mapping.csv eintragen (leer)
      4. Lücken pro Kanal melden + Lücken-Report (nach Nutzung sortiert)
    """
    p        = progress_cb or (lambda m, **kw: None)
    base_dir = _cfg.BASE_DIR
    art_csv  = os.path.join(base_dir, _ARTICLE_CSV_REL)

    if not os.path.exists(art_csv):
        p("ECLASS→Kanal: bitte zuerst 'ECLASS-Analyse' ausführen "
          "(channels/article_eclass_categories.csv fehlt).", tag="warn")
        return

    p("ECLASS→Kanal: lade ECLASS-Endknoten ...")
    usage = collect_leaf_usage(art_csv)

    if not usage:
        p("ECLASS→Kanal: keine ECLASS-Endknoten gefunden — Artikel haben "
          "evtl. keine ECLASS-Klassifikation.", tag="warn")
        return

    total_articles = sum(u["count"] for u in usage.values())
    p(f"ECLASS→Kanal: {len(usage)} eindeutige ECLASS-Kategorien "
      f"({total_articles} Artikel) in Verwendung.")

    # Neue Endknoten eintragen
    existing = load_eclass_mappings(base_dir)
    new_leaves = [
        {"eclass_id": eid, "eclass_version": u["eclass_version"],
         "eclass_name": u["eclass_name"], "example": u["example"],
         "count": u["count"]}
        for eid, u in sorted(usage.items())
        if eid.upper() not in existing
    ]
    path       = eclass_mapping_path(base_dir)
    file_exist = os.path.exists(path)

    if new_leaves:
        added = add_missing_eclass_mappings(base_dir, new_leaves)
        if not file_exist:
            p(f"ECLASS→Kanal: {os.path.basename(path)} neu angelegt, "
              f"{added} Kategorien eingetragen.", tag="ok")
        else:
            p(f"ECLASS→Kanal: {added} neue Kategorien eingetragen.")
    else:
        p("ECLASS→Kanal: Mapping-Datei ist aktuell.")

    # Lücken pro Kanal
    mappings = load_eclass_mappings(base_dir)
    codes    = list(usage.keys())
    unmapped = find_unmapped(mappings, codes)

    total    = len(codes)
    has_gaps = False
    for ch in CHANNELS:
        miss   = len(unmapped[ch])
        mapped = total - miss
        if miss:
            p(f"  {CHANNEL_LABELS[ch]}: {mapped}/{total} gemappt, "
              f"{miss} offen.", tag="warn")
            has_gaps = True
        else:
            p(f"  {CHANNEL_LABELS[ch]}: {mapped}/{total} ✓", tag="ok")

    if not has_gaps:
        p("ECLASS→Kanal: alle ECLASS-Kategorien vollständig gemappt.", tag="ok")
    else:
        report = _write_gap_report(base_dir, unmapped, mappings, usage)
        p(f"ECLASS→Kanal: Lücken-Report → {os.path.basename(report)}", tag="warn")
        p("Bitte channels/eclass_channel_mapping.csv öffnen und IDs eintragen "
          "(häufigste Kategorien zuerst).", tag="dim")
