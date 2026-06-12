# tasks/channel_mapping.py – Kanal-Kategorie-Mapping verwalten
#
# Vergleicht custom_categories.csv mit channels/channel_category_mapping.csv.
# Neue Kategorien werden automatisch (leer) eingetragen.
# Schreibt einen Lücken-Report nach logs/.

import csv
import logging
import os
from datetime import datetime

import config as _cfg
from lib.channel_mapping import (
    CHANNELS, CHANNEL_LABELS,
    add_missing_to_mapping, find_unmapped, load_category_mappings, mapping_path,
)

log = logging.getLogger(__name__)

_CAT_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")


def _load_custom_categories(base_dir: str) -> list:
    """Lädt custom_categories.csv → [{code, name}], überspringt Kommentare."""
    path = os.path.join(base_dir, "custom_categories.csv")
    if not os.path.exists(path):
        return []
    for enc in _CAT_ENCODINGS:
        try:
            cats = []
            with open(path, "r", encoding=enc, errors="strict") as f:
                reader = csv.DictReader(f, delimiter=";")
                for row in reader:
                    code = (row.get("category_code") or "").strip()
                    if not code or code.startswith("#"):
                        continue
                    name = (
                        row.get("name") or row.get("group_name") or
                        row.get("category_name") or ""
                    ).strip()
                    cats.append({"code": code, "name": name})
            return cats
        except (UnicodeDecodeError, KeyError):
            continue
    return []


def _write_unmapped_report(base_dir: str, unmapped: dict,
                            mappings: dict, known: list) -> str:
    """Schreibt logs/unmapped_channel_categories_DATUM.csv und gibt Pfad zurück."""
    logs_dir = _cfg.DIRS.get("logs", base_dir)
    os.makedirs(logs_dir, exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(logs_dir, f"unmapped_channel_categories_{ts}.csv")

    names_by_code = {c["code"].upper(): c.get("name", "") for c in known}

    # Alle Codes die in mindestens einem Kanal fehlen
    missing_codes: set = set()
    for codes in unmapped.values():
        missing_codes.update(c.upper() for c in codes)

    header = ["supplier_category_code", "supplier_category_name"] + [
        CHANNEL_LABELS[ch] for ch in CHANNELS
    ]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(header)
        for code in sorted(missing_codes):
            entry = mappings.get(code, {})
            row = [code, names_by_code.get(code, "")]
            for ch in CHANNELS:
                val = entry.get(ch, "")
                row.append(val or "")
            writer.writerow(row)

    return path


def run(progress_cb=None):
    """
    Haupttask: Kanal-Mapping-Datei aktuell halten und Lücken berichten.

    Ablauf:
      1. custom_categories.csv laden
      2. Neue Codes in channels/channel_category_mapping.csv eintragen (leer)
      3. Für jeden Kanal melden wie viele Codes noch unmapped sind
      4. Bei Lücken → Lücken-Report nach logs/ schreiben
    """
    p        = progress_cb or (lambda m, **kw: None)
    base_dir = _cfg.BASE_DIR

    p("Kanal-Mapping: lade Kategorien ...")
    known = _load_custom_categories(base_dir)

    if not known:
        p("Kanal-Mapping: custom_categories.csv nicht gefunden oder leer — "
          "bitte zuerst Kategorien anlegen.", tag="warn")
        return

    p(f"Kanal-Mapping: {len(known)} interne Kategorien aus custom_categories.csv.")

    # Bestehende Mappings laden und fehlende Codes eintragen
    existing   = load_category_mappings(base_dir)
    new_cats   = [c for c in known if c["code"].upper() not in existing]
    mpath      = mapping_path(base_dir)
    file_exist = os.path.exists(mpath)

    if new_cats:
        added = add_missing_to_mapping(base_dir, new_cats)
        if not file_exist:
            p(f"Kanal-Mapping: {mpath} neu angelegt, "
              f"{added} Kategorien eingetragen.", tag="ok")
        else:
            p(f"Kanal-Mapping: {added} neue Kategorien eingetragen.")
    else:
        p("Kanal-Mapping: Mapping-Datei ist aktuell.")

    # Mappings nach dem Ergänzen neu laden
    mappings = load_category_mappings(base_dir)
    codes    = [c["code"] for c in known]
    unmapped = find_unmapped(mappings, codes)

    # Zusammenfassung pro Kanal
    total  = len(codes)
    has_gaps = False
    for ch in CHANNELS:
        n_miss   = len(unmapped[ch])
        n_mapped = total - n_miss
        label    = CHANNEL_LABELS[ch]
        if n_miss:
            p(f"  {label}: {n_mapped}/{total} gemappt, "
              f"{n_miss} noch offen.", tag="warn")
            has_gaps = True
        else:
            p(f"  {label}: {n_mapped}/{total} ✓", tag="ok")

    if not has_gaps:
        p("Kanal-Mapping: alle Kategorien vollständig gemappt.", tag="ok")
    else:
        report = _write_unmapped_report(base_dir, unmapped, mappings, known)
        p(f"Kanal-Mapping: Lücken-Report → {os.path.basename(report)}", tag="warn")
        p("Bitte channels/channel_category_mapping.csv öffnen und "
          "fehlende IDs eintragen.", tag="dim")
