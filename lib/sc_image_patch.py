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
# Integration in softcarrier_merge.py (nur im <MIME>-Block mit
# MIME_TYPE=image/*, der Artikel hat daneben meist noch einen
# application/pdf-Block fürs Datenblatt, der unangetastet bleiben muss):
#   <MIME_SOURCE>39672.jpg</MIME_SOURCE> → <MIME_SOURCE>39672_302.jpg</MIME_SOURCE>

import csv
import logging
import threading
import time
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from io import BytesIO
from pathlib import Path

log = logging.getLogger(__name__)

BASE_URL      = "https://www.softcarrier.de"
THUMB_URL     = BASE_URL + "/hbimg/search/{aid}.jpg"
HASH_SIZE     = 16
MAX_DIFF      = 12
IMAGE_EXT     = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
PATCH_FILENAME = "sc_image_patch.csv"

# dist-Sentinel für per GROUP_TIMEOUT aufgegebene Gruppen (siehe run_matching):
# eigener Wert statt -1 ("kein Treffer"), damit ein Resume solche Gruppen
# erneut versucht statt sie dauerhaft als erledigt zu betrachten.
TIMEOUT_DIST = -3


class _CircuitBreaker:
    """
    Thread-sicherer Schalter gegen serverseitiges Rate-Limiting/Blocking.

    Live-Erfahrung: softcarrier.de blockt/drosselt nach einiger Zeit so
    stark, dass praktisch jede Anfrage fehlschlägt – ohne Gegenmaßnahme
    würde jede einzelne Gruppe trotzdem einzeln bis zu GROUP_TIMEOUT (180s)
    lang erfolglos versuchen, was einen kompletten Lauf auf nur wenige
    hundert Artikel begrenzt und ~20 manuelle Neustarts nötig gemacht hätte.

    Nach `fail_threshold` Fehlschlägen IN FOLGE (über alle Worker hinweg)
    geht der Schalter für `cooldown`s "auf" – währenddessen werden neue
    Thumbnail-Requests gar nicht erst versucht (sofortiger Fehlschlag statt
    Timeout), der Lauf pausiert praktisch von selbst. Nach Ablauf der
    Cooldown-Zeit macht der Schalter automatisch wieder zu und der Lauf
    versucht es von selbst erneut – kein manueller Neustart nötig.
    """

    def __init__(self, fail_threshold: int = 8, cooldown: float = 300.0):
        self._fail_threshold = fail_threshold
        self._cooldown       = cooldown
        self._lock            = threading.Lock()
        self._consecutive_fails = 0
        self._cooldown_until    = 0.0
        self._cooldowns_hit     = 0

    def blocked(self) -> bool:
        with self._lock:
            return time.time() < self._cooldown_until

    def record_success(self):
        with self._lock:
            self._consecutive_fails = 0

    def record_failure(self, p=None):
        with self._lock:
            self._consecutive_fails += 1
            if (self._consecutive_fails >= self._fail_threshold
                    and time.time() >= self._cooldown_until):
                self._cooldown_until = time.time() + self._cooldown
                self._consecutive_fails = 0
                self._cooldowns_hit += 1
                if p:
                    p(f"  ⏸ {self._fail_threshold} Anfragen in Folge fehlgeschlagen – "
                      f"pausiere {self._cooldown / 60:.0f} Min. (vermutlich "
                      f"Rate-Limiting bei softcarrier.de), danach automatischer "
                      f"Weiterlauf ...", tag="warn")


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


def _phash_from_url(url: str, http_session, breaker: "_CircuitBreaker" = None,
                    p=None) -> object:
    if breaker is not None and breaker.blocked():
        # Läuft gerade eine Cooldown-Pause (siehe _CircuitBreaker) – gar
        # nicht erst versuchen, spart Zeit und schont den Server zusätzlich.
        return None
    try:
        r = http_session.get(url, timeout=8)
        if r.status_code == 200:
            h = _phash_from_bytes(r.content)
            if breaker is not None:
                breaker.record_success()
            return h
        if breaker is not None:
            breaker.record_failure(p)
        return None
    except Exception:
        if breaker is not None:
            breaker.record_failure(p)
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
    Findet Artikel im BMEcat-XML, wo mehrere Artikel dieselbe Bild-MIME_SOURCE
    teilen. Gibt [{supplier_aid, mime_source, folder}, ...] zurück.

    Ein Artikel hat pro Bild UND pro Datenblatt (PDF) je einen eigenen
    <MIME>-Block in <MIME_INFO>, z.B.:
        <MIME><MIME_TYPE>image/jpeg</MIME_TYPE><MIME_SOURCE>39672.jpg</MIME_SOURCE>...</MIME>
        <MIME><MIME_TYPE>application/pdf</MIME_TYPE><MIME_SOURCE>39672.pdf</MIME_SOURCE>...</MIME>
    Muss also gezielt den Bild-Block treffen (MIME_TYPE beginnt mit "image/"),
    sonst würden PDF-Dateinamen fälschlich als Bild-Duplikate behandelt.
    """
    import re
    AID_PAT = re.compile(r'(?i)<supplier_aid>(.*?)</supplier_aid>')
    SRC_PAT = re.compile(
        r'(?is)<mime>\s*<mime_type>\s*image/[^<]*</mime_type>\s*'
        r'<mime_source>(.*?)</mime_source>')
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

def _match_group(folder: str, aids: list, entries: list, http_session,
                 breaker: "_CircuitBreaker" = None, p=None) -> list[dict]:
    results = []

    thumb_hashes: dict = {}
    breaker_skipped: set = set()
    for aid in aids:
        if breaker is not None and breaker.blocked():
            # Cooldown läuft gerade – nicht mal versuchen und auch nicht
            # extra pausieren, das würde die Gruppe nur unnötig in die Länge
            # ziehen ohne jeden Nutzen. dist muss später TIMEOUT_DIST sein
            # (retry-fähig), nicht -1 (dauerhaft "kein Treffer").
            breaker_skipped.add(aid)
            continue
        h = _phash_from_url(THUMB_URL.format(aid=aid), http_session,
                            breaker=breaker, p=p)
        if h is not None:
            thumb_hashes[aid] = h
            # Etwas mehr Pause als vorher (war 0.03s) – 4 Worker feuern sonst
            # zu viele Anfragen in kurzer Zeit gegen softcarrier.de, was dort
            # Rate-Limiting/Verbindungsabbrüche auslösen kann. Nicht zu hoch
            # gewählt: bei ~50.000 Artikeln macht sich jede zusätzliche 0,01s
            # bereits mit mehreren Minuten Gesamtlaufzeit bemerkbar.
            time.sleep(0.08)
        else:
            # Fehlgeschlagener Download (Timeout, Verbindungsabbruch, 404 …):
            # deutlich länger pausieren statt sofort weiterzufeuern – sonst
            # hämmert der Worker bei serverseitigem Rate-Limiting ungebremst
            # weiter gegen denselben Server und verschärft das Problem.
            time.sleep(2.0)

    local = []
    for entry in entries:
        data = _load_image_bytes(entry)
        if data:
            h = _phash_from_bytes(data)
            if h is not None:
                local.append((entry, h))

    for aid in aids:
        if aid in breaker_skipped:
            results.append({"aid": aid, "folder": folder, "entry": None,
                            "dist": TIMEOUT_DIST})
            continue
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
        # imagehash-Subtraktion liefert oft numpy.int64 statt Python int –
        # sqlite3 erkennt den Typ nicht zuverlässig und kann ihn je nach
        # Version stillschweigend als BLOB (bytes) statt INTEGER speichern
        # (Absturz später beim Lesen, siehe flush_csv()). Deshalb hier schon
        # explizit auf einen echten Python-int casten.
        results.append({"aid": aid, "folder": folder, "entry": best_entry, "dist": int(best_dist)})

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
        # Nur 1 Retry, kurzer Backoff: ein abgebrochenes Thumbnail bedeutet
        # nur "kein Treffer" für diesen Artikel, kein Grund für lange Retry-
        # Ketten – bei serverseitigem Rate-Limiting (RemoteDisconnected)
        # kostet jeder Fehlversuch sonst mehrere Sekunden, multipliziert mit
        # zehntausenden Artikeln macht das den Lauf gefühlt unendlich lang.
        max_retries=Retry(total=1, backoff_factor=0.3,
                          status_forcelist=[429, 500, 502, 503, 504]),
        pool_connections=workers, pool_maxsize=workers))
    http.headers["User-Agent"] = "Mozilla/5.0 (compatible; SC-Matcher/2.0)"

    breaker = _CircuitBreaker(fail_threshold=8, cooldown=300.0)

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

    # dist=-3 (TIMEOUT_DIST, siehe unten) zählt bewusst NICHT als erledigt:
    # das markiert Gruppen, die wegen GROUP_TIMEOUT aufgegeben wurden (z.B.
    # bei serverseitigem Rate-Limiting) – die sollen beim nächsten Lauf
    # erneut versucht werden, nicht dauerhaft als "kein Treffer" gelten.
    done_aids = {r[0] for r in conn.execute("SELECT aid FROM results WHERE dist != -3")}
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
                # Verteidigung gegen kaputte/fremde Altdaten in der Resume-
                # Checkpoint-DB (z.B. aus einem früheren, fehlerhaften Lauf):
                # dist muss eine Ganzzahl sein, sonst als "kein Treffer"
                # behandeln statt den ganzen Lauf mit einem TypeError
                # abzuschießen.
                try:
                    dist = int(dist)
                except (TypeError, ValueError):
                    dist = -2
                qual = ("gut"     if 0 <= dist <= MAX_DIFF // 2 else
                        "ok"      if 0 <= dist <= MAX_DIFF       else
                        "schwach" if dist > MAX_DIFF             else "kein")
                w.writerow([aid, rec["mime_source"], fld, img, dist, qual])
        tmp.replace(Path(out_csv))

    # Harte Zeitgrenze pro Gruppe: lokale ZIP-Lesevorgänge (_load_image_bytes)
    # haben – anders als die HTTP-Requests – KEINEN Timeout. Ein einzelner
    # kaputter/unerreichbarer Eintrag in einer der großen ZIP-Dateien kann
    # einen Worker-Thread dadurch für immer blockieren. Da alle Gruppen
    # sofort als Futures eingereicht werden, aber nur `workers` Threads sie
    # abarbeiten, würde ein einzelner hängender Worker nach und nach den
    # gesamten Lauf lahmlegen, sobald alle Worker in je eine solche Gruppe
    # laufen. GROUP_TIMEOUT bricht das Warten auf eine einzelne Gruppe ab
    # (der Thread selbst lässt sich in Python nicht killen, bleibt also
    # belegt – aber der Lauf blockiert nicht mehr komplett und wird fertig).
    GROUP_TIMEOUT = 180  # Sekunden

    # Kein "with ThreadPoolExecutor(...) as pool" – dessen __exit__ ruft
    # shutdown(wait=True) auf und würde bis zum Ende des Funktionskörpers
    # blockieren, bis WIRKLICH alle Worker-Threads fertig sind – inklusive
    # eines für immer blockierten. Das würde die ganze GROUP_TIMEOUT-Logik
    # unten aushebeln. shutdown(wait=False) am Ende gibt den Pool frei, ohne
    # auf hängende Threads zu warten (die bleiben bis Prozessende offen,
    # sind aber harmlos – nur ein paar OS-Threads).
    pool = ThreadPoolExecutor(max_workers=workers)
    futs = {
        pool.submit(_match_group, folder,
                    [r["supplier_aid"] for r in recs],
                    index[folder], http, breaker, p): (folder, recs)
        for folder, recs in todo.items()
    }
    submitted_at = {fut: time.time() for fut in futs}
    pending = set(futs.keys())

    def _record_failure(folder, recs, reason, dist=-1):
        with db_lock:
            for r in recs:
                conn.execute(
                    "INSERT OR REPLACE INTO results(aid,folder,img,dist) VALUES(?,?,?,?)",
                    (r["supplier_aid"], folder, "", dist))
                counters["none"] += 1
            conn.commit()
            counters["done"] += 1
        log.warning("Gruppe %s übersprungen (%s)", folder, reason)

    last_flushed_at = 0
    last_logged_at  = 0

    while pending:
        done, pending = wait(pending, timeout=5, return_when=FIRST_COMPLETED)

        for fut in done:
            folder, recs = futs[fut]
            try:
                results = fut.result()
            except Exception as e:
                _record_failure(folder, recs, f"Fehler: {e}")
                continue

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

        # Gruppen, die seit GROUP_TIMEOUT noch nicht fertig sind (egal ob
        # schon laufend oder noch gar nicht gestartet, weil alle Worker
        # belegt sind), aufgeben – der Lauf soll fertig werden statt endlos
        # zu warten. dist=TIMEOUT_DIST statt -1: das ist möglicherweise nur
        # ein vorübergehendes Problem (z.B. Rate-Limiting bei softcarrier.de,
        # das sich später wieder legt) – die Gruppe soll beim nächsten Lauf
        # erneut versucht werden, nicht dauerhaft als "kein Treffer" gelten
        # (siehe done_aids-Filter oben).
        now = time.time()
        for fut in [f for f in pending if now - submitted_at[f] > GROUP_TIMEOUT]:
            pending.discard(fut)
            folder, recs = futs[fut]
            _record_failure(folder, recs, f"Timeout nach {GROUP_TIMEOUT}s", dist=TIMEOUT_DIST)

        if counters["done"] - last_flushed_at >= 50:
            flush_csv()
            last_flushed_at = counters["done"]
        if counters["done"] - last_logged_at >= 10:
            # Häufigere, aber leichtgewichtige Fortschrittsmeldung (nur
            # Log-Zeile, kein CSV-Flush) – bei langsamem/gedrosseltem
            # Netzwerkzugriff sonst minutenlang ohne sichtbare Rückmeldung.
            p(f"  [{counters['done']:,}/{len(todo):,}]  "
              f"Treffer: {counters['match']:,}  Leer: {counters['none']:,}")
            last_logged_at = counters["done"]

    pool.shutdown(wait=False)
    flush_csv()
    conn.close()
    if breaker._cooldowns_hit:
        p(f"  ⏸ {breaker._cooldowns_hit}× wegen Rate-Limiting pausiert – "
          f"bitte diesen Task bei Bedarf einfach erneut starten, "
          f"bereits erledigte Artikel werden übersprungen.", tag="warn")
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
