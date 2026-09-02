# tasks/bueroring.py
import os, glob, json, shutil, logging, subprocess
from pathlib import Path
from lib.ftp_client import make_client
from lib.bestandsdaten import erstelle_bestandsdaten
from lib.utils import run_7zip as _run_7zip
from config import CONNECTIONS, DIRS, TOOLS, AVAILABILITY_FILE

log = logging.getLogger(__name__)

# Delta-Snapshot für den Dokumenten-Upload (Dateiname → Größe des letzten
# erfolgreichen Uploads) – br-documents.zip enthält jedes Mal den kompletten
# Bestand, ein Zeitstempel-Vergleich funktioniert nach dem Entpacken nicht
# (Dateien sind dann immer "gerade eben" erstellt).
_DOC_SNAPSHOT_FILE = os.path.join(DIRS.get("logs", "."), "bueroring_dokumente_snapshot.json")


def _load_doc_snapshot() -> dict:
    try:
        with open(_DOC_SNAPSHOT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_doc_snapshot(snapshot: dict):
    Path(os.path.dirname(_DOC_SNAPSHOT_FILE)).mkdir(parents=True, exist_ok=True)
    try:
        with open(_DOC_SNAPSHOT_FILE, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False)
    except Exception as e:
        log.warning("Dokumenten-Snapshot konnte nicht gespeichert werden: %s", e)


def _doc_delta(doc_paths: list, previous: dict) -> tuple[list, dict]:
    """Vergleicht doc_paths (Dateiname → Größe) mit dem letzten Snapshot."""
    current = {}
    changed = []
    for path in doc_paths:
        bn   = os.path.basename(path)
        size = os.path.getsize(path)
        current[bn] = size
        if bn not in previous or previous[bn] != size:
            changed.append(path)
    return changed, current


def _unzip_and_rename(zip_path: str, out_dir: str, dst_name: str,
                      seven_z: str, p):
    """
    Entpackt zip_path nach out_dir via subprocess (mit Fehlerausgabe),
    findet die neu entstandene Datei per Vorher/Nachher-Vergleich
    und benennt sie in dst_name um.
    """
    import subprocess

    if not os.path.exists(zip_path):
        p(f"  ZIP nicht gefunden: {os.path.basename(zip_path)}", tag="warn")
        return False

    if not os.path.exists(seven_z):
        p(f"  7-Zip nicht gefunden: {seven_z}", tag="warn")
        p(f"  Bitte Pfad unter Konfiguration → Tools korrigieren.", tag="warn")
        return False

    # Vorher-Snapshot aller Dateien im Zielverzeichnis
    before = set(os.listdir(out_dir))

    p(f"  7-Zip: entpacke {os.path.basename(zip_path)} ...")
    try:
        result = subprocess.run(
            [seven_z, "e", zip_path, f"-o{out_dir}", "-y"],
            capture_output=True, text=True, timeout=300
        )
        # 7-Zip Ausgabe ins Log (nur relevante Zeilen)
        for line in result.stdout.splitlines():
            line = line.strip()
            if line and not line.startswith("-") and "Everything is Ok" not in line:
                p(f"    {line}")
        if result.returncode != 0:
            p(f"  7-Zip Fehler (Code {result.returncode}):", tag="warn")
            for line in result.stderr.splitlines():
                if line.strip():
                    p(f"    {line.strip()}", tag="warn")
    except subprocess.TimeoutExpired:
        p("  7-Zip Timeout nach 300s!", tag="warn")
        return False
    except Exception as e:
        p(f"  7-Zip Exception: {e}", tag="warn")
        return False

    os.remove(zip_path)

    # Nachher-Snapshot: neue Dateien ermitteln
    after = set(os.listdir(out_dir))
    new   = after - before
    p(f"  Neue Dateien nach Entpacken: {sorted(new) or '(keine)'}")

    dst = os.path.join(out_dir, dst_name)
    new.discard(dst_name)

    if not new:
        if os.path.exists(dst):
            p(f"  → {dst_name} (bereits vorhanden)", tag="ok")
            return True
        p(f"  Keine neue Datei gefunden nach Entpacken!", tag="warn")
        return False

    # Erste neue Datei nehmen (bevorzuge .xml)
    xml_new = [f for f in new if f.lower().endswith(".xml")]
    src_name = (xml_new or sorted(new))[0]
    if len(new) > 1:
        p(f"  Mehrere neue Dateien: {sorted(new)} – nehme {src_name}", tag="warn")

    src = os.path.join(out_dir, src_name)
    if os.path.exists(dst):
        os.remove(dst)
    os.replace(src, dst)
    p(f"  {src_name} → {dst_name}", tag="ok")
    return True


def download_sources(progress_cb=None, file_progress_cb=None):
    """
    Lädt nur die beiden BMEcat-ZIPs herunter und benennt sie um:
      br-ek_DE_BMEcat_DEU_ABE.zip → bueroring.xml        (UDX + ECLASS)
      bf-ek_DE_BMEcat_DEU.zip     → bueroring_basis.xml  (Hauptkatalog)

    Wird vom Merge-Task aufgerufen wenn Quelldateien fehlen –
    ohne Bilder, Bestand oder Dokumente mitzuladen.
    """
    cfg     = CONNECTIONS["bueroring"]
    in_bme  = DIRS["in_bme"]
    seven_z = TOOLS["7zip"]
    p  = progress_cb      or (lambda m, **kw: None)
    fp = file_progress_cb or None

    from config import MERGE
    udx_name   = MERGE["udx_src"]
    basis_name = MERGE["basis_src"]

    client = make_client(cfg)
    client.connect()
    try:
        client.download("downloads/bueroforum/br-ek_DE_BMEcat_DEU_ABE.zip",
                        in_bme, progress_cb=p, file_progress_cb=fp)
        client.download("downloads/bueroforum/bf-ek_DE_BMEcat_DEU.zip",
                        in_bme, progress_cb=p, file_progress_cb=fp)
    finally:
        client.disconnect()

    p("Entpacke ABE-ZIP ...")
    _unzip_and_rename(os.path.join(in_bme, "br-ek_DE_BMEcat_DEU_ABE.zip"),
                      in_bme, udx_name, seven_z, p)

    p("Entpacke Basis-ZIP ...")
    _unzip_and_rename(os.path.join(in_bme, "bf-ek_DE_BMEcat_DEU.zip"),
                      in_bme, basis_name, seven_z, p)


# Rückwärtskompatibilität
def download_basis(progress_cb=None, file_progress_cb=None):
    download_sources(progress_cb=progress_cb, file_progress_cb=file_progress_cb)


def run(progress_cb=None, file_progress_cb=None):
    """
    Büroring Standard-Task:
    Download (BMEcat + Bestand) → Merge + Keywords → Brickfox-Upload
    Bestand+Preis (Excel → Brickfox): eigenständiger Task bueroring_bestand.run()
    Bilder und Dokumente: separater Task run_bilder_dokumente()
    """
    cfg     = CONNECTIONS["bueroring"]
    in_bme  = DIRS["in_bme"]
    seven_z = TOOLS["7zip"]
    p  = progress_cb       or (lambda m, **kw: None)
    fp = file_progress_cb  or None

    from config import MERGE
    basis_name = MERGE["basis_src"]
    udx_name   = MERGE["udx_src"]

    # ── Datenfluss-Übersicht ──────────────────────────────────────────────────
    p("╔══════════════════════════════════════════════════════════╗")
    p("║  BÜRORING – Vollständiger Task                          ║")
    p("╠══════════════════════════════════════════════════════════╣")
    p("║  QUELLEN (Download von sftp.bueroring.de)               ║")
    p(f"║    ↓ br-ek_DE_BMEcat_DEU_ABE.zip → {udx_name:<22} ║")
    p(f"║    ↓ bf-ek_DE_BMEcat_DEU.zip     → {basis_name:<22} ║")
    p("║    ↓ br-bestand.zip → availability-data-catalog-32WQS  ║")
    p("║    ↓ /400446/stock/BestandBueroring.csv                ║")
    p("╠══════════════════════════════════════════════════════════╣")
    p("║  VERARBEITUNG                                           ║")
    p(f"║    ⚙ Merge: {udx_name} + {basis_name}")
    p(f"║      → bueroring_merged.xml                            ║")
    p("║    ⚙ Keywords, FNAME/FVALUE, Enrichment, DB-Import     ║")
    p("╠══════════════════════════════════════════════════════════╣")
    p("║  UPLOADS (→ abe.brickfox.net)                          ║")
    p("║    ↑ bueroring_merged.xml  → /incoming/bueroring.xml   ║")
    p("║      (FTP c_abe_ftp_2)                                  ║")
    p("╠══════════════════════════════════════════════════════════╣")
    p("║  Bestand+Preis (Excel → Brickfox CSV) läuft NICHT mehr  ║")
    p("║  hier mit – eigenständiger Task 'Büroring – Bestand+     ║")
    p("║  Preis' im Vorbereitung-Bereich.                        ║")
    p("╚══════════════════════════════════════════════════════════╝")

    # ── Preflight: lokale Konfigurationsdateien prüfen ────────────────────────
    import config as _cfg
    _base = _cfg.BASE_DIR
    _required = [
        ("keywords_exploded.csv",      "Keywords für Volltextsuche"),
        ("fname_renames.csv",          "Feature-Namen-Mapping"),
        ("fvalue_renames.csv",         "Feature-Werte-Mapping"),
    ]
    _optional = [
        ("custom_categories.csv",      "Eigene Kategorie-Namen"),
        ("postprocess_blacklist.csv",  "Artikel-Blacklist"),
        ("postprocess_offline.csv",    "Artikel-Offline-Liste (ONLINE=0)"),
        ("postprocess_prices.csv",     "Preisformeln"),
        ("channel_category_mapping.csv","Kanal-Kategorie-Mapping"),
    ]
    _missing_required = []
    p("Preflight – lokale Dateien:")
    for fname, desc in _required:
        exists = os.path.exists(os.path.join(_base, fname))
        mark   = "✓" if exists else "✗ FEHLT"
        tag    = "ok" if exists else "warn"
        p(f"  {mark:<8} {fname}  ({desc})", tag=tag)
        if not exists:
            _missing_required.append(fname)
    for fname, desc in _optional:
        exists = os.path.exists(os.path.join(_base, fname))
        mark   = "✓" if exists else "–"
        tag    = "ok" if exists else "dim"
        p(f"  {mark:<8} {fname}  ({desc})", tag=tag)
    _tool_ok = os.path.exists(seven_z)
    p(f"  {'✓' if _tool_ok else '✗ FEHLT':<8} 7-Zip ({seven_z})",
      tag="ok" if _tool_ok else "warn")
    if not _tool_ok:
        _missing_required.append("7-Zip")
    if _missing_required:
        p(f"Fehlende Pflichtdateien: {', '.join(_missing_required)}", tag="warn")

    # ── Download: nur BMEcat-ZIPs + Bestand ───────────────────────────────────
    client = make_client(cfg)
    client.connect()
    try:
        client.download("downloads/bueroforum/br-ek_DE_BMEcat_DEU_ABE.zip",
                        in_bme, progress_cb=p, file_progress_cb=fp)
        client.download("downloads/bueroforum/bf-ek_DE_BMEcat_DEU.zip",
                        in_bme, progress_cb=p, file_progress_cb=fp)
        client.download("downloads/bueroforum/br-bestand.zip",
                        in_bme, progress_cb=p, file_progress_cb=fp)
        client.download("/400446/stock/BestandBueroring.csv",
                        in_bme, progress_cb=p, file_progress_cb=fp)
    finally:
        client.disconnect()

    # Entpacken
    p("Bueroring: Entpacke ABE-BMEcat ...")
    _unzip_and_rename(os.path.join(in_bme, "br-ek_DE_BMEcat_DEU_ABE.zip"),
                      in_bme, udx_name, seven_z, p)

    p("Bueroring: Entpacke Basis-BMEcat ...")
    _unzip_and_rename(os.path.join(in_bme, "bf-ek_DE_BMEcat_DEU.zip"),
                      in_bme, basis_name, seven_z, p)

    # Kategorie-Check: neue Kategorien vs. custom_categories.csv melden
    try:
        from lib.category_check import check_new_categories
        import config as _cfg
        check_new_categories(
            os.path.join(in_bme, basis_name), "BRG",
            _cfg.BASE_DIR, "Büroring", progress_cb=p)
    except Exception as e:
        p(f"Kategorie-Check übersprungen: {e}", tag="dim")

    p("Bueroring: Entpacke Bestand ...")
    zip_best = os.path.join(in_bme, "br-bestand.zip")
    if os.path.exists(zip_best):
        _run_7zip(seven_z, zip_best, in_bme, "*.csv", p)
        if os.path.exists(zip_best):
            os.remove(zip_best)

    # Availability-CSV
    p("Bueroring: Erzeuge Availability-CSV ...")
    out_csv = os.path.join(in_bme, AVAILABILITY_FILE)
    erstelle_bestandsdaten(in_bme, out_csv, progress_cb=p)

    # Plausibilitäts-Check: Zeilenanzahl
    if os.path.exists(out_csv):
        with open(out_csv, "r", encoding="utf-8", errors="replace") as _f:
            row_count = sum(1 for _ in _f) - 1  # Header abziehen
        if row_count < 10000:
            p(f"⚠ Availability-CSV: nur {row_count} Zeilen "
              f"(erwartet >30.000) – Lieferantendaten prüfen!", tag="warn")
        else:
            p(f"Availability-CSV: {row_count} Zeilen.", tag="dim")

    # ATP-Merge: Lagerbestände aus OBS-Archiv einspielen
    try:
        from lib.atp import run_atp_merge
        p("ATP-Bestandsdaten: Suche neueste Archiv-Datei ...")
        run_atp_merge(out_csv, progress_cb=p)
    except Exception as e:
        p(f"ATP-Merge übersprungen: {e}", tag="warn")

    # Mindest-Abgleich → 32WQS_conditionsfile.csv
    try:
        from lib.mindest_abgleich import run_mindest_abgleich
        run_mindest_abgleich(out_csv, progress_cb=p)
    except Exception as e:
        p(f"Mindest-Abgleich übersprungen: {e}", tag="warn")

    # Upload → Mercateo-Unite /catalog/32WQS (Availability + Conditionsfile)
    try:
        from tasks.others import upload_mercateo_files
        conditions_csv = os.path.join(in_bme, "32WQS_conditionsfile.csv")
        upload_mercateo_files([out_csv, conditions_csv], progress_cb=p, file_progress_cb=fp)
    except Exception as e:
        p(f"Mercateo-Upload übersprungen: {e}", tag="warn")

    # ── Merge + Keywords ──────────────────────────────────────────────────────
    p("Bueroring: starte Merge + Keywords ...")
    from tasks.bmecat_merge import run as run_merge
    run_merge(progress_cb=p, file_progress_cb=fp)

    from tasks.db_import import run_for_supplier
    run_for_supplier('bueroring', progress_cb=p)

    # Bestand+Preis (Excel → Products/CsvExchange → Brickfox) läuft nicht mehr
    # automatisch mit – eigenständiger Task tasks.bueroring_bestand:run(),
    # damit Preis-/Bestandsupdates ohne XML-Download/-Merge/-Upload laufen können.

    # ── Brickfox-Upload: bueroring_merged.xml als bueroring.xml ──────────────
    from tasks.others import upload_bmecat_xmls
    upload_bmecat_xmls(
        [os.path.join(in_bme, MERGE["out_file"])],
        progress_cb=p, file_progress_cb=fp
    )

    p("Bueroring abgeschlossen.", tag="ok")


def run_bilder_dokumente(progress_cb=None, file_progress_cb=None):
    """
    Büroring Extra-Task: Bilder + Dokumente herunterladen, entpacken und mit
    BRG-Präfix versehen. Wird nicht täglich benötigt – nur bei Bedarf.

    Bilder: nur Download/Entpacken/Umbenennen – der eigentliche Bilder-Upload
    zu Allago + OfficeXL läuft als eigener Task ("Bilder-Upload"), analog zu
    Softcarrier (Download/Umbenennen blockiert damit nicht den Upload).
    Dokumente: werden direkt hier zusätzlich zu Allago + OfficeXL
    (remote_path_documents = /sites/product_files/) hochgeladen, da es
    keinen separaten Delta-Upload-Task für Dokumente gibt.
    """
    cfg     = CONNECTIONS["bueroring"]
    in_bme  = DIRS["in_bme"]
    in2     = DIRS["in2"]
    in_dir  = DIRS["in"]
    seven_z = TOOLS["7zip"]
    p  = progress_cb       or (lambda m, **kw: None)
    fp = file_progress_cb  or None

    client = make_client(cfg)
    client.connect()
    try:
        client.download("downloads/bueroforum/br-images.zip",
                        in2, progress_cb=p, file_progress_cb=fp)
        client.download("downloads/bueroforum/br-documents.zip",
                        in_bme, progress_cb=p, file_progress_cb=fp)
    finally:
        client.disconnect()

    p("Bueroring: Entpacke Bilder ...")
    for zf in glob.glob(os.path.join(in2, "br*.zip")):
        _run_7zip(seven_z, zf, in2, "*.jpg", p)
        for jpg in glob.glob(os.path.join(in2, "*.jpg")):
            shutil.move(jpg, os.path.join(in_dir, "BRG" + os.path.basename(jpg)))
        if os.path.exists(zf):
            os.remove(zf)

    p("Bueroring: Entpacke Dokumente ...")
    doc_zip = os.path.join(in_bme, "br-documents.zip")
    doc_paths = []
    if os.path.exists(doc_zip):
        before = set(os.listdir(in_bme))
        _run_7zip(seven_z, doc_zip, in_bme, None, p)
        new_docs = sorted(set(os.listdir(in_bme)) - before)
        for name in new_docs:
            src = os.path.join(in_bme, name)
            if not os.path.isfile(src):
                continue
            dst = os.path.join(in_dir, "BRG" + name)
            shutil.move(src, dst)
            doc_paths.append(dst)
        if os.path.exists(doc_zip):
            os.remove(doc_zip)
        p(f"Bueroring: {len(doc_paths)} Dokument(e) entpackt und mit BRG-Präfix versehen.",
          tag="ok")
    else:
        p("Bueroring: br-documents.zip nicht gefunden – Dokumente übersprungen.",
          tag="warn")

    if doc_paths:
        # Delta-Filter: br-documents.zip enthält jedes Mal den kompletten
        # Bestand, nicht nur Neues – und die frisch entpackten Dateien haben
        # IMMER den aktuellen Zeitstempel (Entpacken = jetzt), ein Zeitstempel-
        # Vergleich wie beim Bilder-Upload liefe also nie an. Stattdessen
        # Dateigröße gegen den letzten erfolgreichen Snapshot vergleichen –
        # gleiches Prinzip wie der bestehende Softcarrier-Bilder-Snapshot.
        changed_paths, new_snapshot = _doc_delta(doc_paths, _load_doc_snapshot())
        skipped = len(doc_paths) - len(changed_paths)
        if skipped:
            p(f"Bueroring: {skipped} Dokument(e) unverändert seit letztem "
              f"Upload – übersprungen.", tag="dim")

        if changed_paths:
            for conn_key, label in [("allago_images", "Allago"), ("officexl_images", "OfficeXL")]:
                dcfg = CONNECTIONS[conn_key]
                p(f"Bueroring: lade {len(changed_paths)} Dokument(e) → {label} "
                  f"({dcfg['remote_path_documents']}) ...")
                dcl = make_client(dcfg)
                dcl.connect()
                try:
                    for doc_path in changed_paths:
                        dcl.upload(doc_path, dcfg["remote_path_documents"],
                                  progress_cb=p, file_progress_cb=fp)
                finally:
                    dcl.disconnect()
                p(f"  {label}: {len(changed_paths)} Dokument(e) hochgeladen.", tag="ok")

            # Snapshot erst NACH erfolgreichem Upload auf beiden Servern speichern
            _save_doc_snapshot(new_snapshot)
        else:
            p("Bueroring: keine geänderten Dokumente – Upload übersprungen.", tag="dim")

    p("Bueroring Bilder+Dokumente abgeschlossen.", tag="ok")
