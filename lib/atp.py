# lib/atp.py – ATP-Bestandsdaten laden und in Availability-CSV einspielen
#
# Quelle: \\obs.abe-brands.de\OBS\data\VERFUG\Archiv\102_atp*.zip
# Format atp.txt (Tab-separiert, kein Header):
#   Spalte 1: AID          (z.B. "001094022")
#   Spalte 2: Lagerbestand (z.B. "       409" – führende Leerzeichen)
#   Spalte 3: EAN          (z.B. "8021684126789", kann leer sein)
#   Spalte 4: Datum        (z.B. "30.05.2026", optional – Lieferdatum)
#
# Merge-Strategie: ATP-Bestand hat Vorrang vor br-bestand.csv.
# Neue AIDs aus ATP die noch nicht in der CSV sind werden angehängt.

import os
import glob
import zipfile
import logging

log = logging.getLogger(__name__)

# Netzwerkpfad zum ATP-Archiv (konfigurierbar über config.py ATP_ARCHIVE_DIR)
_DEFAULT_ATP_DIR = r"\\obs.abe-brands.de\OBS\data\VERFUG\Archiv"
_ATP_ZIP_PATTERN = "102_atp*.zip"


def get_atp_archive_dir() -> str:
    try:
        import config
        return getattr(config, "ATP_ARCHIVE_DIR", _DEFAULT_ATP_DIR)
    except Exception:
        return _DEFAULT_ATP_DIR


def find_latest_atp_zip(archive_dir: str = None, progress_cb=None) -> str | None:
    """
    Findet das neueste 102_atp*.zip im Archivverzeichnis.
    Sortiert nach Änderungsdatum (neueste zuerst).

    Returns:
        Pfad zur neuesten ZIP-Datei oder None wenn keine gefunden.
    """
    p = progress_cb or (lambda m, **kw: None)
    d = archive_dir or get_atp_archive_dir()

    if not os.path.isdir(d):
        p(f"ATP-Archiv nicht erreichbar: {d}", tag="warn")
        return None

    pattern = os.path.join(d, _ATP_ZIP_PATTERN)
    files = glob.glob(pattern)
    if not files:
        p(f"Keine {_ATP_ZIP_PATTERN}-Dateien in {d}", tag="warn")
        return None

    latest = max(files, key=os.path.getmtime)
    p(f"ATP: neueste Datei: {os.path.basename(latest)}", tag="dim")
    return latest


def load_atp_from_zip(zip_path: str, progress_cb=None) -> dict:
    """
    Liest atp.txt aus einem ZIP-Archiv und parst die Daten.

    Returns:
        dict: {aid_string: {"quantity": int, "ean": str|None, "date": str|None}}
    """
    p = progress_cb or (lambda m, **kw: None)
    data = {}

    if not os.path.exists(zip_path):
        p(f"ATP-ZIP nicht gefunden: {zip_path}", tag="warn")
        return data

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            # atp.txt suchen (case-insensitiv)
            atp_names = [n for n in zf.namelist() if "atp" in n.lower() and n.lower().endswith(".txt")]
            if not atp_names:
                p(f"Keine atp.txt in {os.path.basename(zip_path)}", tag="warn")
                return data

            atp_name = atp_names[0]
            with zf.open(atp_name) as f:
                for line_bytes in f:
                    # Encoding: meist CP1252/Windows-1252 bei deutschen Systemen
                    line = line_bytes.decode("cp1252", errors="replace").rstrip("\r\n")
                    if not line.strip():
                        continue

                    parts = line.split("\t")
                    aid = parts[0].strip() if parts else ""
                    if not aid:
                        continue

                    try:
                        qty = int(parts[1].strip()) if len(parts) > 1 and parts[1].strip() else 0
                    except (ValueError, IndexError):
                        qty = 0

                    ean  = parts[2].strip() if len(parts) > 2 else ""
                    date = parts[3].strip() if len(parts) > 3 else ""

                    data[aid] = {
                        "quantity": qty,
                        "ean":      ean  or None,
                        "date":     date or None,
                    }

    except zipfile.BadZipFile:
        p(f"Defekte ZIP-Datei: {zip_path}", tag="warn")

    p(f"ATP: {len(data)} Artikel geladen aus {os.path.basename(zip_path)}")
    return data


def merge_atp_into_availability(avail_csv: str, atp_data: dict,
                                 progress_cb=None) -> dict:
    """
    Spielt ATP-Bestandsdaten in die Availability-CSV ein.

    Merge-Regeln:
    - AID in ATP + CSV: ATP-Bestand überschreibt CSV-Bestand
    - AID nur in ATP:   Artikel wird am Ende der CSV angehängt
    - AID nur in CSV:   Unverändert (statische Artikel, Sonderartikel, etc.)

    Args:
        avail_csv: Pfad zur availability-data-catalog-32WQS.csv
        atp_data:  {aid: {"quantity": int, ...}}

    Returns:
        dict: {"updated": n, "added": n, "unchanged": n}
    """
    p = progress_cb or (lambda m, **kw: None)

    if not os.path.exists(avail_csv):
        p(f"Availability-CSV nicht gefunden: {avail_csv}", tag="warn")
        return {"updated": 0, "added": 0, "unchanged": 0}

    if not atp_data:
        p("ATP-Daten leer – kein Merge.", tag="warn")
        return {"updated": 0, "added": 0, "unchanged": 0}

    # CSV einlesen
    original_rows = []
    with open(avail_csv, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if line:
                original_rows.append(line)

    # Merge
    aid_seen   = set()
    new_rows   = []
    n_updated  = 0
    n_unchanged = 0

    for row in original_rows:
        parts = row.split(";")
        aid   = parts[0].strip() if parts else ""

        if aid and aid in atp_data:
            atp_qty = atp_data[aid]["quantity"]
            new_rows.append(f"{aid};{atp_qty}")
            aid_seen.add(aid)
            n_updated += 1
        else:
            new_rows.append(row)
            if aid:
                n_unchanged += 1

    # Neue AIDs aus ATP anhängen (nicht in CSV vorhanden)
    n_added = 0
    for aid, info in sorted(atp_data.items()):
        if aid not in aid_seen:
            new_rows.append(f"{aid};{info['quantity']}")
            n_added += 1

    # Zurückschreiben
    with open(avail_csv, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(new_rows) + "\n")

    p(f"ATP-Merge: {n_updated} aktualisiert, "
      f"{n_added} neu hinzugefügt, "
      f"{n_unchanged} unverändert.")

    return {"updated": n_updated, "added": n_added, "unchanged": n_unchanged}


def run_atp_merge(avail_csv: str, archive_dir: str = None,
                  progress_cb=None) -> dict:
    """
    Vollständiger ATP-Workflow: ZIP finden → laden → in CSV einspielen.

    Wird aus tasks/bueroring_bestand.py aufgerufen.

    Returns:
        Merge-Statistik oder {} bei Fehler.
    """
    p = progress_cb or (lambda m, **kw: None)

    zip_path = find_latest_atp_zip(archive_dir, progress_cb=p)
    if not zip_path:
        return {}

    atp_data = load_atp_from_zip(zip_path, progress_cb=p)
    if not atp_data:
        return {}

    return merge_atp_into_availability(avail_csv, atp_data, progress_cb=p)
