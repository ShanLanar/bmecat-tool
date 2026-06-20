# tasks/translate_unspsc.py – UNSPSC name_en → name_de via Claude API
#
# Liest eine Standard-Katalog-CSV, übersetzt alle UNSPSC-13.1-Einträge
# (name_en → name_de) und speichert die ergänzte Datei.
#
# Voraussetzung:
#   py -m pip install anthropic
#   Umgebungsvariable: ANTHROPIC_API_KEY
#
# CLI:
#   py tasks/translate_unspsc.py eclass_catalog_mssql.csv
#   py tasks/translate_unspsc.py eclass_catalog_mssql.csv --out eclass_catalog_mssql_de.csv
#   py tasks/translate_unspsc.py eclass_catalog_mssql.csv --version 13.1 --batch 80

import argparse
import csv
import os
import sys
import time
from pathlib import Path

CSV_HEADER   = ["version", "code", "name_de", "name_en", "level", "parent_code"]
UNSPSC_VER   = "13.1"
DEFAULT_BATCH = 60
MODEL         = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = (
    "Du bist ein präziser Übersetzer für technische Produktkategorien. "
    "Übersetze englische Bezeichnungen aus dem UNSPSC-Klassifikationssystem ins Deutsche. "
    "Antworte NUR mit den übersetzten Bezeichnungen, eine pro Zeile, in derselben Reihenfolge wie die Eingabe. "
    "Keine Erklärungen, keine Nummerierung, keine Zusatzinformationen."
)


def _translate_batch(client, names: list[str]) -> list[str]:
    """Übersetzt eine Liste englischer UNSPSC-Namen ins Deutsche."""
    user_msg = "\n".join(names)
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )
    lines = response.content[0].text.strip().splitlines()
    # Sicherheitscheck: Anthropic gibt manchmal leere Zeilen zurück
    lines = [l.strip() for l in lines if l.strip()]
    if len(lines) != len(names):
        # Fallback: Originalnamen behalten, Fehler loggen
        print(f"  [WARN] Batch-Mismatch: {len(names)} Eingaben, {len(lines)} Ausgaben – Original bleibt")
        return names
    return lines


def translate(in_csv: str, out_csv: str, version: str = UNSPSC_VER,
              batch_size: int = DEFAULT_BATCH, progress_cb=None):
    p = progress_cb or print

    try:
        import anthropic
    except ImportError:
        raise RuntimeError("py -m pip install anthropic")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("Umgebungsvariable ANTHROPIC_API_KEY nicht gesetzt")

    client = anthropic.Anthropic(api_key=api_key)

    # CSV einlesen
    with open(in_csv, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        rows = list(reader)

    # Zu übersetzende Indizes ermitteln
    to_translate = [
        i for i, r in enumerate(rows)
        if r.get("version", "").strip() == version and r.get("name_en", "").strip()
    ]
    total = len(to_translate)
    p(f"  {total:,} UNSPSC-{version}-Einträge mit name_en gefunden")

    if total == 0:
        p("  Nichts zu übersetzen.")
        _write_csv(rows, out_csv)
        return 0

    # Batchweise übersetzen
    done = 0
    retries = 3
    for start in range(0, total, batch_size):
        batch_idx = to_translate[start : start + batch_size]
        names_en  = [rows[i]["name_en"].strip() for i in batch_idx]

        for attempt in range(1, retries + 1):
            try:
                names_de = _translate_batch(client, names_en)
                break
            except Exception as exc:
                wait = 2 ** attempt
                p(f"  [WARN] Versuch {attempt} fehlgeschlagen ({exc}), warte {wait}s …")
                time.sleep(wait)
        else:
            p("  [ERROR] Batch übersprungen nach Wiederholungsversuchen")
            continue

        for i, de in zip(batch_idx, names_de):
            rows[i]["name_de"] = de

        done += len(batch_idx)
        p(f"  {done:,}/{total:,} übersetzt …")

        # Kurze Pause um Rate-Limits zu vermeiden
        if done < total:
            time.sleep(0.5)

    _write_csv(rows, out_csv)
    p(f"  Gespeichert: {out_csv}")
    return done


def _write_csv(rows: list[dict], out_csv: str):
    tmp = Path(out_csv).with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_HEADER, delimiter=";",
                           extrasaction="ignore", quoting=csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(Path(out_csv))


def _cli():
    ap = argparse.ArgumentParser(
        description=f"UNSPSC name_en → name_de Übersetzung via Claude ({MODEL})")
    ap.add_argument("input",          help="Standard-Katalog-CSV (Eingabe)")
    ap.add_argument("--out",          default=None,
                    help="Ausgabe-CSV (Standard: Eingabe überschreiben)")
    ap.add_argument("--version",      default=UNSPSC_VER,
                    help=f"UNSPSC-Version (Standard: {UNSPSC_VER})")
    ap.add_argument("--batch",        type=int, default=DEFAULT_BATCH,
                    help=f"Einträge pro API-Aufruf (Standard: {DEFAULT_BATCH})")
    args = ap.parse_args()

    if not Path(args.input).exists():
        print(f"Datei nicht gefunden: {args.input}", file=sys.stderr)
        sys.exit(1)

    out = args.out or args.input
    n = translate(args.input, out, version=args.version, batch_size=args.batch)
    print(f"\nFertig: {n:,} Übersetzungen → {out}")


if __name__ == "__main__":
    _cli()
