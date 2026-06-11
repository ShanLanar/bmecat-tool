# lib/parallel.py – Parallele Download-Ausführung
#
# Ermöglicht es, Download-Phasen mehrerer Lieferanten gleichzeitig auszuführen,
# während Merge/Upload-Phasen weiterhin sequenziell laufen.
#
# Verwendung in einem Task:
#   from lib.parallel import run_parallel
#
#   def download_bueroring(p, fp): ...
#   def download_softcarrier(p, fp): ...
#   def download_nordwest(p, fp): ...
#
#   results = run_parallel([
#       ("Büroring",    download_bueroring,    p, fp),
#       ("Softcarrier", download_softcarrier,  p, fp),
#       ("Nordwest",    download_nordwest,     p, fp),
#   ], progress_cb=p)

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

log = logging.getLogger(__name__)


def run_parallel(tasks: list, max_workers: int = 3,
                 progress_cb=None) -> dict:
    """
    Führt mehrere Funktionen parallel aus.

    Args:
        tasks: Liste von Tupeln (name, fn, *args)
            fn wird als fn(*args) aufgerufen
        max_workers: Maximale Anzahl paralleler Threads
        progress_cb: Log-Callback

    Returns:
        dict: {name: {"ok": bool, "error": str|None, "result": any}}

    Beispiel:
        results = run_parallel([
            ("Download A", download_a, p, fp),
            ("Download B", download_b, p, fp),
        ], progress_cb=p)
    """
    p = progress_cb or (lambda m, **kw: None)
    results = {}

    if not tasks:
        return results

    p(f"Starte {len(tasks)} parallele Downloads (max {max_workers} gleichzeitig) ...")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_name = {}
        for task_def in tasks:
            name = task_def[0]
            fn   = task_def[1]
            args = task_def[2:]

            future = executor.submit(_safe_call, fn, args)
            future_to_name[future] = name

        for future in as_completed(future_to_name):
            name = future_to_name[future]
            ok, error, result = future.result()

            results[name] = {
                "ok":     ok,
                "error":  error,
                "result": result,
            }

            if ok:
                p(f"  ✓ {name} abgeschlossen", tag="ok")
            else:
                p(f"  ✗ {name} fehlgeschlagen: {error}", tag="err")

    n_ok  = sum(1 for r in results.values() if r["ok"])
    n_err = sum(1 for r in results.values() if not r["ok"])
    p(f"Parallele Downloads abgeschlossen: {n_ok} OK, {n_err} Fehler")

    return results


def _safe_call(fn, args):
    """Ruft fn(*args) auf und fängt Exceptions ab."""
    try:
        result = fn(*args)
        return True, None, result
    except Exception as e:
        log.exception("Paralleler Task fehlgeschlagen: %s", e)
        return False, str(e), None
