#!/usr/bin/env python3
# tools/find_dead_code.py – Vulture-Wrapper, der die Task-Registry kennt
#
# lib/task_registry.py registriert Task-Funktionen als String
# ("modul.pfad:funktionsname"), von lib/task_registry.py:call_task() per
# importlib + getattr dynamisch aufgerufen. Vulture (statische Analyse)
# sieht solche String-Referenzen nicht und meldet JEDE Task-Funktion
# fälschlich als "unused" – das macht das rohe vulture-Ergebnis für diese
# Codebase unbrauchbar (34 Task-Einträge = 34+ Fehlalarme).
#
# Dieses Skript filtert genau diese bekannten TASKS-Ziele aus dem
# vulture-Ergebnis heraus, damit nur echte Kandidaten übrig bleiben – wie
# einst tasks/others.py:run_bilder, das jahrelang unregistriert und daher
# tatsächlich tot war (Büroring-Bilder-Upload lief deswegen nie).
#
# Aufruf:  python tools/find_dead_code.py
# Exit-Code 1 wenn noch ungeprüfte Funde übrig sind (für CI/Pre-Commit
# geeignet), sonst 0.

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_FN_RE = re.compile(r'"fn":\s*"([\w.]+):(\w+)"')
_UNUSED_RE = re.compile(
    r"^(?P<path>[^:]+):(?P<line>\d+): unused (?:function|method) '(?P<name>\w+)'"
)


def registered_targets() -> set[tuple[str, str]]:
    """Liest alle "fn": "modul:funktion"-Einträge aus TASKS."""
    src = (ROOT / "lib" / "task_registry.py").read_text(encoding="utf-8")
    return set(_FN_RE.findall(src))


def module_name(py_path: Path) -> str:
    rel = py_path.relative_to(ROOT).with_suffix("")
    return ".".join(rel.parts)


def main() -> int:
    targets = registered_targets()

    result = subprocess.run(
        ["vulture", ".", "--min-confidence", "60", "--exclude", "demos"],
        cwd=ROOT, capture_output=True, text=True,
    )
    if result.returncode not in (0, 1, 3):
        print(result.stderr, file=sys.stderr)
        print("vulture konnte nicht ausgeführt werden (installiert? "
              "pip install vulture).", file=sys.stderr)
        return 2

    kept, suppressed = [], []
    for line in result.stdout.splitlines():
        m = _UNUSED_RE.match(line)
        if not m:
            kept.append(line)  # andere Fundtypen (Imports, Variablen ...) unverändert
            continue
        mod = module_name(ROOT / m["path"])
        if (mod, m["name"]) in targets:
            suppressed.append(line)
        else:
            kept.append(line)

    print(f"{len(kept)} Fund(e), {len(suppressed)} bekannte "
          f"Task-Registry-Ziele automatisch unterdrückt.\n")
    if kept:
        print("\n".join(kept))
    else:
        print("Keine offenen Funde.")
    return 1 if kept else 0


if __name__ == "__main__":
    sys.exit(main())
