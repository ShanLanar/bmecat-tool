# lib/channel_mapping.py – Kategorie-Mapping für Marktplatz-Kanäle
#
# Bildet interne Lieferanten-Kategoriecodes auf die Kategoriesysteme
# der Zielmarktplätze ab (eBay, Kaufland, Conrad/Mirakl, ManoMano/Mirakl, Unite).
#
# Mapping-Datei:  <BASE_DIR>/channels/channel_category_mapping.csv
# Template:       templates/channel_category_mapping.csv

import csv
import logging
import os

log = logging.getLogger(__name__)

# Kanonische Kanal-IDs — Reihenfolge ist auch die Spaltenreihenfolge in der CSV
CHANNELS = ("ebay", "kaufland", "mirakl_conrad", "mirakl_mano", "unite")

CHANNEL_LABELS = {
    "ebay":          "eBay",
    "kaufland":      "Kaufland",
    "mirakl_conrad": "Conrad (Mirakl)",
    "mirakl_mano":   "ManoMano (Mirakl)",
    "unite":         "Unite/Mercateo",
}

# CSV-Spaltenname → interner Kanalschlüssel
_COLUMN_MAP = {
    "ebay_category_id":      "ebay",
    "kaufland_category_id":  "kaufland",
    "mirakl_conrad_category":"mirakl_conrad",
    "mirakl_mano_category":  "mirakl_mano",
    "unite_category":        "unite",
}

_MAPPING_RELPATH = os.path.join("channels", "channel_category_mapping.csv")
_ENCODINGS       = ("utf-8-sig", "utf-8", "cp1252", "latin-1")


def mapping_path(base_dir: str) -> str:
    return os.path.join(base_dir, _MAPPING_RELPATH)


def load_category_mappings(base_dir: str) -> dict:
    """
    Lädt channels/channel_category_mapping.csv.

    Returns:
        {supplier_category_code_upper: {"name": str, "ebay": str, ...}}
        Leeres Dict wenn Datei nicht existiert oder leer ist.
    """
    path = mapping_path(base_dir)
    if not os.path.exists(path):
        log.debug("Kein Kanal-Mapping gefunden: %s", path)
        return {}

    mappings: dict = {}
    for enc in _ENCODINGS:
        try:
            with open(path, "r", encoding=enc, errors="strict") as f:
                sample = f.read(4096)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=",;")
                except csv.Error:
                    dialect = csv.excel
                f.seek(0)
                reader = csv.DictReader(f, dialect=dialect)
                for row in reader:
                    code = (row.get("supplier_category_code") or "").strip()
                    if not code or code.startswith("#"):
                        continue
                    entry: dict = {"name": (row.get("supplier_category_name") or "").strip()}
                    for col, ch_key in _COLUMN_MAP.items():
                        entry[ch_key] = (row.get(col) or "").strip()
                    mappings[code.upper()] = entry
            if mappings:
                log.info("Kanal-Mapping: %d Kategorien geladen", len(mappings))
            return mappings
        except (UnicodeDecodeError, KeyError):
            continue

    log.warning("Kanal-Mapping konnte nicht gelesen werden: %s", path)
    return {}


def fill_channel_category(base_dir: str, channel: str, updates: dict) -> int:
    """
    Befüllt NUR leere Zellen der angegebenen Kanal-Spalte in
    channel_category_mapping.csv. Vorhandene Werte werden nie überschrieben
    (manuelle Korrekturen bleiben erhalten). Codes, die noch gar nicht in der
    Datei stehen, werden zuerst über add_missing_to_mapping() ergänzt.

    Args:
        channel:  Kanalschlüssel aus CHANNELS (z.B. "ebay")
        updates:  {supplier_category_code: neuer_wert}

    Returns:
        Anzahl tatsächlich befüllter Zellen.
    """
    path = mapping_path(base_dir)
    if not os.path.exists(path):
        add_missing_to_mapping(
            base_dir, [{"code": c, "name": ""} for c in updates])

    col = next((c for c, ch in _COLUMN_MAP.items() if ch == channel), None)
    if not col:
        return 0

    rows, fieldnames = [], None
    for enc in _ENCODINGS:
        try:
            with open(path, "r", encoding=enc, errors="strict", newline="") as f:
                sample = f.read(4096)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=",;")
                except csv.Error:
                    dialect = csv.excel
                f.seek(0)
                reader = csv.DictReader(f, dialect=dialect)
                fieldnames = reader.fieldnames
                rows = list(reader)
            break
        except (UnicodeDecodeError, KeyError):
            continue
    if not rows or not fieldnames:
        return 0

    known_codes = {(r.get("supplier_category_code") or "").upper() for r in rows}
    missing = [{"code": c, "name": ""} for c in updates
               if c.upper() not in known_codes and not c.startswith("#")]
    if missing:
        add_missing_to_mapping(base_dir, missing)
        # Neu angehängte Zeilen mit einlesen
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, delimiter=";")
            fieldnames = reader.fieldnames
            rows = list(reader)

    filled = 0
    for row in rows:
        code = (row.get("supplier_category_code") or "").strip()
        if not code or code.startswith("#"):
            continue
        new_val = updates.get(code.upper()) or updates.get(code)
        if new_val and not (row.get(col) or "").strip():
            row[col] = new_val
            filled += 1

    if filled:
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
            writer.writeheader()
            writer.writerows(rows)

    return filled


def get_channel_category(mappings: dict, supplier_cat_code: str, channel: str) -> str:
    """Gibt die Kanal-Kategorie-ID zurück. Leerer String wenn nicht gemappt."""
    return mappings.get(supplier_cat_code.upper(), {}).get(channel, "")


def find_unmapped(mappings: dict, category_codes: list,
                  channels: list | None = None) -> dict:
    """
    Findet Codes ohne gültiges Mapping für jeden Kanal.

    Args:
        mappings:        Ergebnis von load_category_mappings()
        category_codes:  Zu prüfende Lieferanten-Kategoriecodes
        channels:        Zu prüfende Kanäle (None = alle)

    Returns:
        {channel_key: [codes_without_mapping]}
    """
    check_channels = channels or list(CHANNELS)
    result: dict[str, list] = {ch: [] for ch in check_channels}

    for code in category_codes:
        entry = mappings.get(code.upper(), {})
        for ch in check_channels:
            if not entry.get(ch):
                result[ch].append(code)

    return result


def add_missing_to_mapping(base_dir: str, new_categories: list) -> int:
    """
    Fügt Kategorien, die noch nicht in der Mapping-Datei stehen, als Leerzeilen an.
    Legt Datei + Verzeichnis an falls nicht vorhanden.

    Args:
        base_dir:        Projektwurzel
        new_categories:  [{code, name}] — nur neue werden geschrieben

    Returns:
        Anzahl neu hinzugefügter Zeilen
    """
    channels_dir = os.path.join(base_dir, "channels")
    os.makedirs(channels_dir, exist_ok=True)
    path = mapping_path(base_dir)

    header = [
        "supplier_category_code", "supplier_category_name",
        "ebay_category_id", "kaufland_category_id",
        "mirakl_conrad_category", "mirakl_mano_category", "unite_category",
    ]

    file_exists = os.path.exists(path)
    added = 0

    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")

        if not file_exists:
            writer.writerow(header)
            writer.writerow([
                "# Präfix: BRG=Büroring | SOC=Softcarrier | NDW=Nordwest",
                "# Name (informativ)",
                "# eBay Leaf-ID (z.B. 162800)",
                "# Kaufland-Kategorie-ID",
                "# Conrad (Mirakl) Kategoriecode",
                "# ManoMano (Mirakl) Kategoriecode",
                "# Unite/Mercateo (UNSPSC oder eigener Code)",
            ])

        for cat in new_categories:
            writer.writerow([cat["code"], cat.get("name", ""), "", "", "", "", ""])
            added += 1

    return added


# ── ECLASS-gekeytes Kanal-Mapping ─────────────────────────────────────────────
#
# Brücke ECLASS → Marktplatz: Eine ECLASS-Endknoten-ID wird EINMAL pro Kanal
# gemappt und gilt dann lieferantenübergreifend für alle Artikel mit dieser
# ECLASS-Klassifikation. Deutlich weniger Pflegeaufwand als pro Lieferant-Code.

_ECLASS_MAPPING_RELPATH = os.path.join("channels", "eclass_channel_mapping.csv")

_ECLASS_HEADER = [
    "eclass_id", "eclass_version", "eclass_name",
    "example_article", "article_count",
    "ebay_category_id", "kaufland_category_id",
    "mirakl_conrad_category", "mirakl_mano_category", "unite_category",
]


def eclass_mapping_path(base_dir: str) -> str:
    return os.path.join(base_dir, _ECLASS_MAPPING_RELPATH)


def load_eclass_mappings(base_dir: str) -> dict:
    """
    Lädt channels/eclass_channel_mapping.csv.

    Returns:
        {eclass_id_upper: {"version": str, "name": str, "ebay": str, ...}}
    """
    path = eclass_mapping_path(base_dir)
    if not os.path.exists(path):
        log.debug("Kein ECLASS-Kanal-Mapping gefunden: %s", path)
        return {}

    mappings: dict = {}
    for enc in _ENCODINGS:
        try:
            with open(path, "r", encoding=enc, errors="strict") as f:
                sample = f.read(4096)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=",;")
                except csv.Error:
                    dialect = csv.excel
                f.seek(0)
                reader = csv.DictReader(f, dialect=dialect)
                for row in reader:
                    eid = (row.get("eclass_id") or "").strip()
                    if not eid or eid.startswith("#"):
                        continue
                    entry: dict = {
                        "version": (row.get("eclass_version") or "").strip(),
                        "name":    (row.get("eclass_name") or "").strip(),
                    }
                    for col, ch_key in _COLUMN_MAP.items():
                        entry[ch_key] = (row.get(col) or "").strip()
                    mappings[eid.upper()] = entry
            if mappings:
                log.info("ECLASS-Kanal-Mapping: %d Kategorien geladen", len(mappings))
            return mappings
        except (UnicodeDecodeError, KeyError):
            continue

    log.warning("ECLASS-Kanal-Mapping konnte nicht gelesen werden: %s", path)
    return {}


def add_missing_eclass_mappings(base_dir: str, new_leaves: list) -> int:
    """
    Fügt ECLASS-Endknoten, die noch nicht in der Mapping-Datei stehen,
    als Leerzeilen an. Legt Datei + Verzeichnis an falls nicht vorhanden.

    Args:
        base_dir:    Projektwurzel
        new_leaves:  [{eclass_id, eclass_version, eclass_name, example, count}]

    Returns:
        Anzahl neu hinzugefügter Zeilen
    """
    channels_dir = os.path.join(base_dir, "channels")
    os.makedirs(channels_dir, exist_ok=True)
    path = eclass_mapping_path(base_dir)

    file_exists = os.path.exists(path)
    added = 0

    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")

        if not file_exists:
            writer.writerow(_ECLASS_HEADER)
            writer.writerow([
                "# z.B. 24-23-05-01", "# ECLASS-5 oder ECLASS-9",
                "# Klartext (informativ)", "# Beispielartikel", "# Anzahl Artikel",
                "# eBay Leaf-ID", "# Kaufland-Kategorie",
                "# Conrad (Mirakl)", "# ManoMano (Mirakl)", "# Unite/Mercateo",
            ])

        for lf in new_leaves:
            writer.writerow([
                lf["eclass_id"], lf.get("eclass_version", ""),
                lf.get("eclass_name", ""), lf.get("example", ""),
                lf.get("count", ""), "", "", "", "", "",
            ])
            added += 1

    return added


def get_channel_category_by_eclass(mappings: dict, eclass_id: str,
                                   channel: str) -> str:
    """Marktplatz-Kategorie für eine ECLASS-ID. Leer wenn nicht gemappt."""
    return mappings.get((eclass_id or "").upper(), {}).get(channel, "")
