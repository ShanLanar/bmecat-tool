# lib/sc_image_patch.py – Softcarrier Bild-Patch via pHash-Matching
#
# Problem: MIME_SOURCE in Softcarrier-BMEcat enthält nur einen Ordnernamen
# (z.B. "39672.jpg"). Mehrere Farbvarianten im gleichen Ordner teilen dadurch
# zufällig das gleiche Bild. Die /htmlkat/koepfe/-ZIPs enthalten die richtigen
# variantenspezifischen Bilder (301.jpg, 302.jpg …), aber der BMEcat sagt
# nicht welches Bild zu welchem Artikel gehört.
#
# Lösung: pHash-Vergleich zwischen öffentlichen Artikelthumbnails
# (hbimg/search/{aid}.jpg) und den Bilddateien aus den lokalen ZIPs.
#
# Ausgabe: sc_image_patch.csv in BASE_DIR
#   supplier_aid ; old_mime_source ; new_folder ; new_image ; hamming_dist ; qualitaet
#
# Integration in softcarrier_merge.py:
#   <SOURCE>39672.jpg</SOURCE> → <SOURCE>39672_302.jpg</SOURCE>  (pro Artikel)

import csv
import logging
import time
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path

log = logging.getLogger(__name__)

BASE_URL      = "https://www.softcarrier.de"
THUMB_URL     = BASE_URL + "/hbimg/search/{aid}.jpg"
HASH_SIZE     = 16
MAX_DIFF      = 12
IMAGE_EXT     = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
PATCH_FILENAME = "sc_image_patch.csv"


# ── Abhängigkeits-Check ───────────────────────────────────────────────────────

def check_deps() -> list[str]:
    """Gibt fehlende Pakete zurück (leere Liste = alles ok)."""
    missing = []
    try:
        import requests  # noqa
    except ImportError:
        missing.append("requests")
    try:
        from PIL import Image  # noqa
        import imagehash       # noqa
    except ImportError:
        missing.append("Pillow imagehash")
    return missing


# ── Index aufbauen ────────────────────────────────────────────────────────────

def build_index(zip_dir: Path = None, img_dir: Path = None) -> dict:
    """
    Baut {folder_name: [(zip_path_or_None, entry_path), ...]} auf.
    Validiert: Eintrag wird nur aufgenommen wenn Pfad '{folder}/{datei}' entspricht.
    """
    index: dict = defaultdict(list)
    total = 0

    if zip_dir:
        zips = sorted(zip_dir.glob("*.zip"))
        if not zips:
            zips = sorted(zip_dir.glob("**/*.zip"))
        for zp in zips:
            size_gb = zp.stat().st_size / 1024 ** 3
            log.info("  Index: %s (%.2f GB)...", zp.name, size_gb)
            try:
                with zipfile.ZipFile(zp, 'r') as zf:
                    for entry in zf.infolist():
                        if entry.is_dir():
                            continue
                        path  = entry.filename.replace('\\', '/')
                        parts = [x for x in path.split('/') if x]
                        if len(parts) < 2:
                            continue
                        folder   = parts[-2]
                        filename = parts[-1]
                        if Path(filename).suffix.lower() not in IMAGE_EXT:
                            continue
                        index[folder].append((str(zp), entry.filename))
                        total += 1
            except Exception as e:
                log.warning("  Fehler %s: %s", zp.name, e)

    elif img_dir:
        for fd in img_dir.iterdir():
            if not fd.is_dir():
                continue
            for img in fd.iterdir():
                if img.suffix.lower() in IMAGE_EXT:
                    index[fd.name].append((None, str(img)))
                    total += 1

    log.info("Index: %d Ordner, %d Bilder", len(index), total)
    if index:
        sizes = sorted(len(v) for v in index.values())
        log.info("Bilder/Ordner: min=%d median=%d max=%d",
                 sizes[0], sizes[len(sizes) // 2], sizes[-1])
    return dict(index)


# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def _load_image_bytes(entry: tuple) -> bytes | None:
    zip_path, name = entry
    try:
        if zip_path is None:
            return Path(name).read_bytes()
        with zipfile.ZipFile(zip_path, 'r') as zf:
            return zf.read(name)
    except Exception as e:
        log.debug("Ladefehler %s: %s", name, e)
        return None


def _phash_from_bytes(data: bytes):
    try:
        from PIL import Image
        import imagehash
        return imagehash.phash(Image.open(BytesIO(data)).convert("RGB"),
                               hash_size=HASH_SIZE)
    except Exception:
        return None


def _phash_from_url(url: str, http_session) -> object:
    try:
        r = http_session.get(url, timeout=15)
        return _phash_from_bytes(r.content) if r.status_code == 200 else None
    except Exception:
        return None


def _entry_filename(entry: tuple, folder: str) -> str:
    """Gibt Dateiname zurück, wenn der Eintrag wirklich im erwarteten Ordner liegt."""
    zip_path, name = entry
    if zip_path is None:
        p = Path(name)
        return p.name if p.parent.name == folder else ""
    parts = [x for x in name.replace('\\', '/').split('/') if x]
    if len(parts) < 2 or parts[-2] != folder:
        return ""
    return parts[-1]


# ── Analyse: betroffene Artikel finden ───────────────────────────────────────

def find_affected(xml_path: str) -> list[dict]:
    """
    Findet Artikel im BMEcat-XML, wo mehrere Artikel dieselbe MIME_SOURCE teilen.
    Gibt [{supplier_aid, mime_source, folder}, ...] zurück.
    """
    import re
    AID_PAT = re.compile(r'(?i)<supplier_aid>(.*?)</supplier_aid>')
    SRC_PAT = re.compile(r'(?i)<source>(.*?)</source>')
    ART_PAT = re.compile(r'(?is)<article[\s>].*?</article>')

    groups: dict = defaultdict(list)
    content = Path(xml_path).read_text(encoding='utf-8', errors='replace')
    for m in ART_PAT.finditer(content):
        art  = m.group(0)
        aid_m = AID_PAT.search(art)
        if not aid_m:
            continue
        src_m = SRC_PAT.search(art)
        if not src_m:
            continue
        aid    = aid_m.group(1).strip()
        src    = src_m.group(1).strip()
        folder = Path(src).stem
        groups[src].append({"supplier_aid": aid, "mime_source": src, "folder": folder})

    affected = []
    for mime_source, items in groups.items():
        if len(items) > 1:
            affected.extend(items)
    return affected


# ── pHash-Matching einer Gruppe ───────────────────────────────────────────────

def _match_group(folder: str, aids: list, entries: list, http_session) -> list[dict]:
    results = []

    thumb_hashes: dict = {}
    for aid in aids:
        h = _phash_from_url(THUMB_URL.format(aid=aid), http_session)
        if h is not None:
            thumb_hashes[aid] = h
        time.sleep(0.03)

    local = []
    for entry in entries:
        data = _load_image_bytes(entry)
        if data:
            h = _phash_from_bytes(data)
            if h is not None:
                local.append((entry, h))

    for aid in aids:
        th = thumb_hashes.get(aid)
        if th is None or not local:
            results.append({"aid": aid, "folder": folder, "entry": None, "dist": -1})
            continue
        best_entry, best_dist = None, MAX_DIFF + 1
        for entry, lh in local:
            d = th - lh
            if d < best_dist:
                best_dist, best_entry = d, entry
            if d == 0:
                break
        results.append({"aid": aid, "folder": folder, "entry": best_entry, "dist": best_dist})

    return results


# ── Vollständiges Matching ────────────────────────────────────────────────────

def run_matching(index: dict, affected: list[dict], out_csv: str,
                 workers: int = 4, progress_cb=None) -> dict:
    """
    pHash-Matching für alle betroffenen Artikel.
    Schreibt out_csv (und eine SQLite-Checkpoint-DB daneben).
    Gibt Zähler-Dict zurück: {match, none, done}.
    """
    missing = check_deps()
    if missing:
        raise ImportError(f"Fehlende Pakete: {', '.join(missing)} — bitte installieren")

    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    import sqlite3
    from threading import Lock

    p = progress_cb or (lambda m, **kw: None)

    http = requests.Session()
    http.mount("https://", HTTPAdapter(
        max_retries=Retry(total=3, backoff_factor=1,
                          status_forcelist=[429, 500, 502, 503, 504]),
        pool_connections=workers, pool_maxsize=workers))
    http.headers["User-Agent"] = "Mozilla/5.0 (compatible; SC-Matcher/2.0)"

    # Artikel nach Ordner gruppieren
    groups: dict = defaultdict(list)
    no_index = []
    for rec in affected:
        folder = rec.get("folder", Path(rec.get("mime_source", "")).stem)
        if folder in index:
            groups[folder].append(rec)
        else:
            no_index.append(rec)

    p(f"  Gruppen mit ZIP-Index: {len(groups):,} ({sum(len(v) for v in groups.values()):,} Artikel)")
    p(f"  Ohne Ordner im Index:  {len(no_index):,} Artikel")

    # Checkpoint-DB
    db_path = Path(out_csv).with_suffix(".db")
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("""CREATE TABLE IF NOT EXISTS results
                    (aid TEXT PRIMARY KEY, folder TEXT, img TEXT,
                     dist INTEGER, ts TEXT DEFAULT (datetime('now')))""")
    conn.commit()

    done_aids = {r[0] for r in conn.execute("SELECT aid FROM results")}
    todo = {f: recs for f, recs in groups.items()
            if not all(r["supplier_aid"] in done_aids for r in recs)}
    skipped = len(groups) - len(todo)
    if skipped:
        p(f"  Resume: {skipped:,} Gruppen bereits abgeschlossen")

    for rec in no_index:
        if rec["supplier_aid"] not in done_aids:
            conn.execute("INSERT OR IGNORE INTO results(aid,folder,img,dist) VALUES(?,?,?,?)",
                         (rec["supplier_aid"], rec.get("mime_source", ""), "", -2))
    conn.commit()

    db_lock = Lock()
    counters = {"match": 0, "none": 0, "done": 0}

    def flush_csv():
        rows = {r[0]: (r[1], r[2], r[3])
                for r in conn.execute("SELECT aid, folder, img, dist FROM results")}
        tmp = Path(out_csv).with_suffix(".tmp")
        with open(tmp, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f, delimiter=';')
            w.writerow(["supplier_aid", "old_mime_source", "new_folder", "new_image",
                        "hamming_dist", "qualitaet"])
            for rec in affected:
                aid = rec["supplier_aid"]
                fld, img, dist = rows.get(aid, ("", "", -2))
                qual = ("gut"     if 0 <= dist <= MAX_DIFF // 2 else
                        "ok"      if 0 <= dist <= MAX_DIFF       else
                        "schwach" if dist > MAX_DIFF             else "kein")
                w.writerow([aid, rec["mime_source"], fld, img, dist, qual])
        tmp.replace(Path(out_csv))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {
            pool.submit(_match_group, folder,
                        [r["supplier_aid"] for r in recs],
                        index[folder], http): (folder, recs)
            for folder, recs in todo.items()
        }
        for fut in as_completed(futs):
            folder, recs = futs[fut]
            try:
                results = fut.result()
            except Exception as e:
                log.error("Gruppe %s: %s", folder, e)
                results = [{"aid": r["supplier_aid"], "folder": folder,
                            "entry": None, "dist": -1} for r in recs]

            with db_lock:
                for r in results:
                    entry = r.get("entry")
                    img   = _entry_filename(entry, folder) if entry else ""
                    dist  = r.get("dist", -1)
                    conn.execute(
                        "INSERT OR REPLACE INTO results(aid,folder,img,dist) VALUES(?,?,?,?)",
                        (r["aid"], folder, img, dist))
                    if img and 0 <= dist <= MAX_DIFF:
                        counters["match"] += 1
                    else:
                        counters["none"] += 1
                conn.commit()
                counters["done"] += 1
                if counters["done"] % 50 == 0:
                    flush_csv()
                    p(f"  [{counters['done']:,}/{len(todo):,}]  "
                      f"Treffer: {counters['match']:,}  Leer: {counters['none']:,}")

    flush_csv()
    conn.close()
    return counters


# ── Patch-Map laden ───────────────────────────────────────────────────────────

def load_patch_map(csv_path: str) -> dict:
    """
    Lädt sc_image_patch.csv und gibt {supplier_aid: (new_folder, new_image)} zurück.
    Nur Einträge mit qualitaet 'gut' oder 'ok' werden übernommen.
    Gibt leeres Dict zurück wenn Datei fehlt.
    """
    result = {}
    if not Path(csv_path).exists():
        return result
    try:
        with open(csv_path, encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f, delimiter=';'):
                if row.get("qualitaet", "") not in ("gut", "ok"):
                    continue
                aid = row.get("supplier_aid", "").strip()
                fld = row.get("new_folder", "").strip()
                img = row.get("new_image", "").strip()
                if aid and fld and img:
                    result[aid] = (fld, img)
        log.info("Bild-Patch-Map geladen: %d Einträge aus %s",
                 len(result), Path(csv_path).name)
    except Exception as e:
        log.warning("Bild-Patch-Map konnte nicht geladen werden: %s", e)
    return result
