# lib/utils.py – Gemeinsame Hilfsfunktionen
#
# Zentralisiert:
#   - run_7zip()              (war 5× dupliziert in tasks/)
#   - glob_case_insensitive() (Windows: *.JPG und *.jpg = gleiche Dateien)
#   - VERSION                 (zentrale Versionsnummer)

import os
import glob as _glob
import subprocess
import logging

log = logging.getLogger(__name__)

VERSION = "1.1.0"


def run_7zip(seven_z: str, zip_path: str, out_dir: str,
             filter_: str = None, p=None, timeout: int = 600) -> bool:
    """
    Entpackt ein Archiv mit 7-Zip.

    Args:
        seven_z:   Pfad zur 7z.exe
        zip_path:  Archiv-Datei
        out_dir:   Zielverzeichnis
        filter_:   Dateifilter (z.B. "*.xml", "*.csv")
        p:         progress_cb für Log-Ausgaben
        timeout:   Timeout in Sekunden (Standard: 600)

    Returns:
        True bei Erfolg, False bei Fehler
    """
    if not os.path.exists(seven_z):
        if p:
            p(f"7-Zip nicht gefunden: {seven_z}", tag="warn")
        return False
    cmd = [seven_z, "e", zip_path, f"-o{out_dir}", "-y"]
    if filter_:
        cmd.append(filter_)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0 and p:
            p(f"7-Zip Fehler (Code {r.returncode}): {r.stderr.strip()}", tag="warn")
        return r.returncode == 0
    except subprocess.TimeoutExpired:
        if p:
            p(f"7-Zip Timeout nach {timeout}s!", tag="warn")
        return False
    except Exception as e:
        if p:
            p(f"7-Zip Exception: {e}", tag="warn")
        return False


def glob_ci(directory: str, extension: str) -> list:
    """
    Case-insensitiver Glob mit automatischer Deduplizierung.

    Auf Windows liefern *.JPG und *.jpg identische Ergebnisse.
    Diese Funktion gibt eine deduplizierte, sortierte Liste zurück.

    Args:
        directory:  Verzeichnis
        extension:  Dateiendung ohne Punkt (z.B. "jpg", "xml", "csv")

    Returns:
        Sortierte Liste eindeutiger Dateipfade

    Beispiel:
        jpgs = glob_ci(img_dir, "jpg")
    """
    ext_lower = extension.lower().lstrip(".")
    ext_upper = extension.upper().lstrip(".")
    results = (
        _glob.glob(os.path.join(directory, f"*.{ext_lower}")) +
        _glob.glob(os.path.join(directory, f"*.{ext_upper}"))
    )
    return sorted(set(results))


def xml_escape(s: str) -> str:
    """
    Escaped XML-Sonderzeichen in Text-Content.

    & → &amp;  (MUSS zuerst, sonst werden die anderen Ersetzungen doppelt-escaped)
    < → &lt;
    > → &gt;
    " → &quot;
    """
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;"))


def xml_fix_ampersands(text: str) -> str:
    """
    Repariert nackte & in XML-Text, ohne bereits korrekte Entities zu brechen.

    'Clic & Go'         → 'Clic &amp; Go'
    '&amp;'             → '&amp;'            (bleibt)
    '&lt;'              → '&lt;'             (bleibt)
    'A & B &amp; C'     → 'A &amp; B &amp; C'
    """
    import re
    # Matcht & das NICHT von einem gültigen Entity-Pattern gefolgt wird.
    # Wichtig: auch Sequenzen wie &amp;amp; entstehen wenn Quelle bereits &amp;
    # enthält – deshalb die vollständige Named-Entity-Liste prüfen.
    return re.sub(
        r'&(?!amp;|lt;|gt;|quot;|apos;|nbsp;|copy;|reg;|trade;|mdash;|ndash;'
        r'|laquo;|raquo;|hellip;|euro;|#\d+;|#x[0-9a-fA-F]+;)',
        '&amp;', text)


def detect_encoding(path: str) -> str:
    """
    Erkennt das Encoding einer Datei zuverlässig.

    Reihenfolge:
    1. BOM-Check (UTF-8-BOM, UTF-16)
    2. XML-Deklaration (<?xml encoding="..."?>)
    3. UTF-8-Validität (strikt, ohne Fehlertoleranz)
    4. chardet-Analyse mit hoher Konfidenz (>0.85)
    5. Fallback: cp1252

    Gibt immer ein gültiges Python-Encoding zurück.
    """
    import re as _re
    with open(path, "rb") as f:
        raw = f.read(32768)

    # 1. BOM
    if raw.startswith(b'\xef\xbb\xbf'):
        return "utf-8-sig"
    if raw.startswith(b'\xff\xfe'):
        return "utf-16-le"
    if raw.startswith(b'\xfe\xff'):
        return "utf-16-be"

    # 2. XML-Deklaration
    xml_enc = _re.search(rb'<\?xml[^>]+encoding=["\']([^"\']+)["\']', raw[:200])
    if xml_enc:
        enc = xml_enc.group(1).decode("ascii", errors="ignore").lower()
        enc_map = {"iso-8859-1": "latin-1", "iso8859-1": "latin-1",
                   "windows-1252": "cp1252", "utf-8": "utf-8"}
        return enc_map.get(enc, enc)

    # 3. Strenger UTF-8-Test
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass

    # 4. chardet (optional)
    try:
        import chardet
        result = chardet.detect(raw)
        enc        = (result.get("encoding") or "").lower()
        confidence = result.get("confidence", 0)
        if confidence >= 0.85 and enc:
            enc_map = {
                "iso-8859-1": "latin-1", "iso-8859-2": "latin-2",
                "windows-1252": "cp1252", "ascii": "utf-8",
            }
            return enc_map.get(enc, enc)
    except ImportError:
        pass

    # 5. Fallback
    return "cp1252"

def check_dependencies() -> list:
    """Prüft ob alle benötigten Python-Pakete installiert sind (ohne sie zu laden)."""
    import importlib.util
    return [pkg for pkg in ("paramiko", "openpyxl")
            if importlib.util.find_spec(pkg) is None]


def file_hash(path: str) -> str:
    """
    Berechnet SHA-256 Hash einer Datei (chunked, speicherschonend).
    Gibt den Hex-String zurück.
    """
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def timed(label: str = ""):
    """
    Decorator/Contextmanager: misst Laufzeit und schreibt sie in den Lauf-Report.

    Als Decorator:
        @timed("Merge Phase 2")
        def merge_xml(...): ...

    Als Contextmanager:
        with timed("XML-Sanitize"):
            sanitize_xml(path)
    """
    import time
    import functools

    class _Timer:
        def __init__(self, lbl):
            self._label = lbl
            self._start = None
            self._elapsed = None

        def __enter__(self):
            self._start = time.perf_counter()
            return self

        def __exit__(self, *args):
            self._elapsed = time.perf_counter() - self._start
            _record_timing(self._label, self._elapsed)
            return False

        def __call__(self, fn):
            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                t0 = time.perf_counter()
                result = fn(*args, **kwargs)
                _record_timing(self._label or fn.__name__,
                               time.perf_counter() - t0)
                return result
            return wrapper

    return _Timer(label)


# Globale Timing-Registry für den aktuellen Lauf
_run_timings: list = []


def _record_timing(label: str, elapsed: float):
    _run_timings.append({"label": label, "seconds": round(elapsed, 3)})


def get_run_timings() -> list:
    """Gibt alle gemessenen Zeiten zurück und leert die Registry."""
    global _run_timings
    result = list(_run_timings)
    _run_timings = []
    return result


def gtin_valid(ean: str) -> bool:
    """
    Prüft die GS1-Prüfziffer einer EAN-8, EAN-13 oder EAN-14.
    Gibt False für ungültige Länge oder Nicht-Ziffern zurück.

    Algorithmus: abwechselnde Gewichtung 1/3, Summe mod 10 == 0.
    """
    if not ean or not ean.isdigit() or len(ean) not in (8, 13, 14):
        return False
    digits = [int(d) for d in ean]
    # Gewichtung: bei gerader Länge beginnt Position 0 mit 1, sonst mit 3
    weight_first = 3 if len(digits) % 2 == 0 else 1
    total = sum(
        d * (weight_first if i % 2 == 0 else (4 - weight_first))
        for i, d in enumerate(digits[:-1])
    )
    check = (10 - (total % 10)) % 10
    return check == digits[-1]


def gtin_fix(ean: str) -> str | None:
    """
    Versucht eine fehlerhafte EAN zu korrigieren (letzte Stelle).
    Gibt die korrigierte EAN zurück oder None wenn nicht fixbar.
    """
    if not ean or not ean.isdigit() or len(ean) not in (8, 13, 14):
        return None
    digits = [int(d) for d in ean]
    weight_first = 3 if len(digits) % 2 == 0 else 1
    total = sum(
        d * (weight_first if i % 2 == 0 else (4 - weight_first))
        for i, d in enumerate(digits[:-1])
    )
    correct_check = (10 - (total % 10)) % 10
    if correct_check == digits[-1]:
        return ean  # bereits korrekt
    # Nur letzte Stelle war falsch → fixbar
    return ean[:-1] + str(correct_check)


import re as _re_utils

_COMPANY_SUFFIX = _re_utils.compile(
    r'\b(GmbH|AG|KG|OHG|eV|Inc|Ltd|LLC|Corp|BV|NV|SA|SL|SAS|SPA|'
    r'Deutschland|Europe|International|Group|Holding|Vertriebs|GmbhCoKG)\b.*$',
    _re_utils.IGNORECASE)


def mfr_normalize(name: str) -> str:
    """Entfernt Rechtsform-/Regionssuffixe für Vergleichszwecke."""
    name = _COMPANY_SUFFIX.sub("", name).strip()
    return _re_utils.sub(r"[^\w]", "", name).upper()


def mfr_phonetik(name: str) -> str:
    """
    Kölner Phonetik für Herstellernamen — aus ahnen_master übernommen.
    Findet Übereinstimmungen trotz Schreibvarianten:
      "CASIO", "CASIO Europe GmbH" → gleicher Code "48"

    Gibt einen kurzen phonetischen Code zurück.
    """
    s = mfr_normalize(name)
    s = s.replace("AE", "A").replace("OE", "O").replace("UE", "U")
    s = s.replace("Ä", "A").replace("Ö", "O").replace("Ü", "U")
    s = _re_utils.sub(r"[^A-Z]", "", s)
    if not s:
        return ""
    _codes = {
        **dict.fromkeys("AEIOUHJWY", "0"),
        **dict.fromkeys("BP", "1"),
        **dict.fromkeys("DT", "2"),
        **dict.fromkeys("FVW", "3"),
        **dict.fromkeys("CGKQ", "4"),
        **dict.fromkeys("SZX", "8"),
        "L": "5", "M": "6", "N": "6", "R": "7",
    }
    code, prev = "", ""
    for c in s:
        d = _codes.get(c, "")
        if d and d != prev:
            code += d
        prev = d
    return code.replace("0", "") or "0"


def mfr_matches(a: str, b: str) -> bool:
    """
    Prüft ob zwei Herstellernamen phonetisch übereinstimmen.
    Schnelle Vorbedingung: mindestens 3 gemeinsame Anfangsbuchstaben.
    """
    na, nb = mfr_normalize(a), mfr_normalize(b)
    if not na or not nb:
        return False
    # Schnell-Check: erster Buchstabe muss gleich sein
    if na[0] != nb[0]:
        return False
    return mfr_phonetik(a) == mfr_phonetik(b)


# ── Lauf-Cache (in-memory, wird pro Programmstart neu aufgebaut) ──────────────

_run_cache: dict = {}


def cache_get(key: str):
    """Liest einen Wert aus dem Lauf-Cache."""
    return _run_cache.get(key)


def cache_set(key: str, value):
    """Speichert einen Wert im Lauf-Cache."""
    _run_cache[key] = value
    return value


def cache_clear():
    """Leert den gesamten Lauf-Cache."""
    _run_cache.clear()


def iter_articles(xml_path: str):  # noqa
    """
    Robuster Artikel-Iterator für BMEcat-XML.
    Funktioniert sowohl mit mehrzeiligen als auch einzeiligen (minimierten) XMLs.

    Yields: str (vollständiger <ARTICLE>...</ARTICLE> Block)
    """
    import re
    ART_OPEN  = re.compile(r'<ARTICLE[\s>]', re.IGNORECASE)
    ART_CLOSE = re.compile(r'</ARTICLE>',     re.IGNORECASE)

    in_art = False
    buf    = []
    depth  = 0   # für verschachtelte Tags (selten aber möglich)

    if not os.path.exists(xml_path):
        return
    with open(xml_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            # Einzeilige XML: mehrere Artikel auf einer Zeile
            # Zerlegen an </ARTICLE> Grenzen
            while True:
                if not in_art:
                    m = ART_OPEN.search(line)
                    if not m:
                        break
                    line = line[m.start():]
                    in_art = True
                    buf    = []
                    depth  = 1

                close_m = ART_CLOSE.search(line)
                if not close_m:
                    buf.append(line)
                    break
                else:
                    # Alles bis einschließlich </ARTICLE> puffern
                    end = close_m.end()
                    buf.append(line[:end])
                    yield "".join(buf)
                    # Rest der Zeile weiterverarbeiten
                    line   = line[end:]
                    in_art = False
                    buf    = []
                    depth  = 0
