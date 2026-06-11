import os
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyse_fnames.py – BMEcat FNAME-Analyse + Kollisionserkennung

Liest alle konfigurierten BMEcat-XMLs, extrahiert alle FNAMEs,
erkennt Kollisionen innerhalb von Artikeln und erzeugt:

  1. fname_report.txt    – Übersichtstabelle (Datei → FNAMEs)
  2. fname_mapping.csv   – Editierbare Mapping-Tabelle
                           (FNAME_original → FNAME_pim)
  3. fname_collisions.txt– Artikel mit doppelten FNAMEs nach Mapping

Ablauf:
  python analyse_fnames.py
  → Verzeichnis wählen (wo die XMLs liegen)
  → Dateien werden analysiert
  → Ausgaben im gleichen Verzeichnis

Nach dem Editieren von fname_mapping.csv kann das Umbenennen
direkt hier gestartet werden (Option im Dialog).
"""

import os
import re
import csv
import sys
from pathlib import Path
from collections import defaultdict

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext
    HAS_TK = True
except ImportError:
    HAS_TK = False


# ── Konfiguration ─────────────────────────────────────────────────────────────

# Welche XMLs analysieren (Dateiname → Lieferant-Label)
XML_FILES = {
    "bueroring.xml":       "Büroring (UDX/ECLASS-9.0)",
    "bueroring_basis.xml": "Büroring Basis (udf_BRjCat / ECLASS-9.1)",
    "soft-carrier.xml":    "Softcarrier",
    "systeam.xml":         "Systeam",
    "arbeitsschutz.xml":   "Nordwest Arbeitsschutz (udf_NDW)",
    "werkstatt.xml":       "Nordwest Werkstatt (udf_NDW)",
    "werkzeugtechnik.xml": "Nordwest Werkzeug (udf_NDW)",
    "bueroring_basis.xml": "Büroring Basis",
    "merged.xml":          "Merged (Büroring kombiniert)",
}

# Regex
_ARTICLE_PAT  = re.compile(r'(?is)<article[\s>].*?</article>')
_AID_PAT      = re.compile(r'(?is)<supplier_aid>(.*?)</supplier_aid>')
_AF_PAT       = re.compile(r'(?is)<article_features.*?</article_features>')
_REFSYS_PAT   = re.compile(r'(?is)<reference_feature_system_name>(.*?)</reference_feature_system_name>')
_FNAME_PAT    = re.compile(r'(?is)<fname>(.*?)</fname>')
_FVALUE_PAT   = re.compile(r'(?is)<fvalue>(.*?)</fvalue>')
_FDESCR_PAT   = re.compile(r'(?is)<fdescr>(.*?)</fdescr>')


# ── Analyse ───────────────────────────────────────────────────────────────────

def analyse_file(xml_path: str) -> dict:
    """
    Liest eine XML-Datei und gibt zurück:
    {
      "fname_counts":  {fname: count},           # wie oft kommt jeder fname vor
      "fname_sources": {fname: {ref_system, …}}, # in welchen Feature-Systemen
      "articles":      [{aid, fnames: [fname,…]}],# pro Artikel
      "collisions":    [{aid, fname, count}],     # doppelte FNAMEs pro Artikel
      "total_articles": int,
    }
    """
    content = Path(xml_path).read_text(encoding="utf-8", errors="replace")

    fname_counts  = defaultdict(int)
    fname_sources = defaultdict(set)
    articles      = []
    collisions    = []

    for art_m in _ARTICLE_PAT.finditer(content):
        article = art_m.group()
        aid_m   = _AID_PAT.search(article)
        aid     = aid_m.group(1).strip() if aid_m else "?"

        art_fnames = []
        for af_m in _AF_PAT.finditer(article):
            block  = af_m.group()
            refsys = ""
            rs_m   = _REFSYS_PAT.search(block)
            if rs_m:
                refsys = rs_m.group(1).strip()

            for fn_m in _FNAME_PAT.finditer(block):
                fname = fn_m.group(1).strip()
                fname_counts[fname] += 1
                if refsys:
                    fname_sources[fname].add(refsys)
                art_fnames.append(fname)

        # Kollisionen innerhalb dieses Artikels
        seen = defaultdict(int)
        for f in art_fnames:
            seen[f] += 1
        for f, cnt in seen.items():
            if cnt > 1:
                collisions.append({"aid": aid, "fname": f, "count": cnt})

        articles.append({"aid": aid, "fnames": art_fnames})

    return {
        "fname_counts":   dict(fname_counts),
        "fname_sources":  {k: sorted(v) for k, v in fname_sources.items()},
        "articles":       articles,
        "collisions":     collisions,
        "total_articles": len(articles),
    }


def analyse_directory(directory: str) -> dict:
    """Analysiert alle konfigurierten XMLs im Verzeichnis."""
    results = {}
    for filename, label in XML_FILES.items():
        path = os.path.join(directory, filename)
        if os.path.exists(path):
            print(f"  Analysiere {filename} ...")
            results[filename] = {
                "label":  label,
                "path":   path,
                **analyse_file(path),
            }
        else:
            print(f"  Überspringe {filename} (nicht gefunden)")
    return results


# ── Ausgabe ───────────────────────────────────────────────────────────────────

def write_report(results: dict, out_dir: str):
    """fname_report.txt – Übersichtstabelle."""
    path = os.path.join(out_dir, "fname_report.txt")
    with open(path, "w", encoding="utf-8") as f:

        f.write("=" * 80 + "\n")
        f.write("BMEcat FNAME-Analyse\n")
        f.write("=" * 80 + "\n\n")

        for filename, data in results.items():
            f.write(f"\n{'─' * 70}\n")
            f.write(f"  {data['label']}\n")
            f.write(f"  Datei:    {filename}\n")
            f.write(f"  Artikel:  {data['total_articles']}\n")
            f.write(f"  FNAMEs:   {len(data['fname_counts'])} eindeutige\n")
            if data["collisions"]:
                f.write(f"  ⚠ Kollisionen in {len(data['collisions'])} Artikeln\n")
            f.write(f"{'─' * 70}\n\n")

            # Tabelle: FNAME | Anzahl | Feature-Systeme
            col1 = max((len(fn) for fn in data["fname_counts"]), default=20)
            col1 = min(max(col1, 20), 60)
            header = f"  {'FNAME':<{col1}}  {'Anzahl':>7}  Feature-System\n"
            f.write(header)
            f.write("  " + "-" * (col1 + 30) + "\n")

            for fname, count in sorted(data["fname_counts"].items(),
                                       key=lambda x: x[0].lower()):
                sources = ", ".join(data["fname_sources"].get(fname, []))
                f.write(f"  {fname:<{col1}}  {count:>7}  {sources}\n")

        # Globale Duplikate über alle Dateien
        f.write(f"\n{'=' * 80}\n")
        f.write("GLOBALE FNAME-ÜBERSCHNEIDUNGEN (gleicher Name in mehreren Dateien)\n")
        f.write(f"{'=' * 80}\n\n")

        # Alle FNAMEs mit ihren Dateien sammeln
        global_map = defaultdict(list)
        for filename, data in results.items():
            for fname in data["fname_counts"]:
                global_map[fname].append(filename)

        overlaps = {f: files for f, files in global_map.items() if len(files) > 1}
        if overlaps:
            col1 = max((len(f) for f in overlaps), default=20)
            col1 = min(col1, 60)
            for fname, files in sorted(overlaps.items(), key=lambda x: x[0].lower()):
                f.write(f"  {fname:<{col1}}  →  {', '.join(files)}\n")
        else:
            f.write("  Keine Überschneidungen gefunden.\n")

    print(f"  Bericht:  {path}")
    return path


def _apply_rename_rules(fname: str, refsys: str, filename: str) -> str:
    """
    Wendet die gleichen Umbenennungsregeln an wie der Merge-Prozess,
    damit die Auswertung die finalen PIM-Namen zeigt.

    Regeln:
    - ECLASS-9.1 in Basisdatei: FNAME bleibt (Umbenennung passiert im Merge per FDESCR)
    - ECLASS-9.0 aus bueroring.xml: FNAME=Code → wird zu "FDESCR (Code)" im Merge
      → hier nur markieren, da FDESCR nicht im fname_counts verfügbar
    - udf_BRjCat / udf_NDW: unveränderter FNAME
    """
    return fname   # Rohdaten; Merge-Umbenennung nicht vorab simulierbar ohne FDESCR


def write_mapping_csv(results: dict, out_dir: str) -> str:
    """
    fname_mapping.csv – Editierbare Mapping-Tabelle pro Datei.
    Spalten: FNAME_original, FNAME_pim, Datei, Lieferant, Feature_System, Anzahl, Notiz
    FNAME_pim ist vorbelegt mit FNAME_original (= keine Änderung).
    """
    path = os.path.join(out_dir, "fname_mapping.csv")

    rows = []
    seen = set()
    for filename, data in results.items():
        label = data["label"]
        for fname, count in sorted(data["fname_counts"].items(),
                                   key=lambda x: x[0].lower()):
            key = (fname, filename)
            if key not in seen:
                seen.add(key)
                sources = ", ".join(data["fname_sources"].get(fname, []))
                rows.append({
                    "FNAME_original": fname,
                    "FNAME_pim":      fname,
                    "Datei":          filename,
                    "Lieferant":      label,
                    "Feature_System": sources,
                    "Anzahl":         count,
                    "Notiz":          "",
                })

    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "FNAME_original", "FNAME_pim", "Datei",
            "Lieferant", "Feature_System", "Anzahl", "Notiz"
        ], delimiter=";")
        writer.writeheader()
        writer.writerows(rows)

    print(f"  Mapping:  {path}")
    return path


def write_consolidated_csv(results: dict, out_dir: str) -> str:
    """
    fname_alle.csv – Konsolidierte Liste aller FNAMEs über alle Dateien.

    Spalten:
      FNAME | FNAME_pim | Datei | Lieferant | Feature_System | Anzahl_Artikel

    Zeilen sind nach FNAME sortiert. Jede FNAME+Datei-Kombination erscheint
    genau einmal. Damit ist die Liste direkt als Mapping-Vorlage nutzbar.
    """
    path = os.path.join(out_dir, "fname_alle.csv")

    rows = []
    for filename, data in results.items():
        label = data["label"]
        for fname, count in data["fname_counts"].items():
            sources = ", ".join(data["fname_sources"].get(fname, []))
            rows.append({
                "FNAME":           fname,
                "FNAME_pim":       fname,   # ← hier editieren für PIM-Import
                "Datei":           filename,
                "Lieferant":       label,
                "Feature_System":  sources,
                "Anzahl_Artikel":  count,
            })

    # Sortierung: FNAME alphabetisch, dann Datei
    rows.sort(key=lambda r: (r["FNAME"].lower(), r["Datei"]))

    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "FNAME", "FNAME_pim", "Datei", "Lieferant",
            "Feature_System", "Anzahl_Artikel"
        ], delimiter=";")
        writer.writeheader()
        writer.writerows(rows)

    print(f"  Konsolidiert: {path}  ({len(rows)} Zeilen)")
    return path
    """
    fname_mapping.csv – Editierbare Mapping-Tabelle.
    Spalten: FNAME_original, Datei, Lieferant, FNAME_pim, Notiz
    FNAME_pim ist vorbelegt mit FNAME_original (= keine Änderung).
    """
    path = os.path.join(out_dir, "fname_mapping.csv")

    rows = []
    seen = set()
    for filename, data in results.items():
        label = data["label"]
        for fname, count in sorted(data["fname_counts"].items(),
                                   key=lambda x: x[0].lower()):
            key = (fname, filename)
            if key not in seen:
                seen.add(key)
                sources = ", ".join(data["fname_sources"].get(fname, []))
                rows.append({
                    "FNAME_original": fname,
                    "FNAME_pim":      fname,   # ← hier editieren
                    "Datei":          filename,
                    "Lieferant":      label,
                    "Feature_System": sources,
                    "Anzahl":         count,
                    "Notiz":          "",
                })

    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "FNAME_original", "FNAME_pim", "Datei",
            "Lieferant", "Feature_System", "Anzahl", "Notiz"
        ], delimiter=";")
        writer.writeheader()
        writer.writerows(rows)

    print(f"  Mapping:  {path}")
    return path


def write_collisions(results: dict, out_dir: str):
    """fname_collisions.txt – Artikel mit doppelten FNAMEs."""
    path = os.path.join(out_dir, "fname_collisions.txt")
    total = sum(len(d["collisions"]) for d in results.values())

    with open(path, "w", encoding="utf-8") as f:
        f.write("=" * 80 + "\n")
        f.write(f"FNAME-KOLLISIONEN INNERHALB VON ARTIKELN ({total} gefunden)\n")
        f.write("=" * 80 + "\n\n")

        if total == 0:
            f.write("  Keine Kollisionen gefunden.\n")
        else:
            for filename, data in results.items():
                if not data["collisions"]:
                    continue
                f.write(f"\n{'─' * 70}\n")
                f.write(f"  Katalog:  {data['label']}\n")
                f.write(f"  Datei:    {filename}\n")
                f.write(f"  Anzahl:   {len(data['collisions'])} Kollisionen\n")
                f.write(f"{'─' * 70}\n\n")

                col_aid   = max((len(c['aid'])   for c in data['collisions']), default=10)
                col_fname = max((len(c['fname']) for c in data['collisions']), default=10)
                col_aid   = min(col_aid,   40)
                col_fname = min(col_fname, 60)

                f.write(f"  {'AID':<{col_aid}}  {'FNAME':<{col_fname}}  Anzahl\n")
                f.write(f"  {'-'*col_aid}  {'-'*col_fname}  ------\n")
                for c in sorted(data["collisions"],
                                key=lambda x: (x['aid'], x['fname'])):
                    f.write(f"  {c['aid']:<{col_aid}}  {c['fname']:<{col_fname}}  {c['count']}x\n")

    print(f"  Kollisionen: {path}")
    return path


# ── Mapping anwenden ──────────────────────────────────────────────────────────

def apply_mapping(mapping_csv: str, xml_dir: str, progress_fn=print):
    """
    Liest fname_mapping.csv und benennt FNAMEs in den XMLs um
    wo FNAME_original ≠ FNAME_pim.

    Prüft danach ob Kollisionen entstanden sind und warnt.
    """
    # Mapping laden: {(fname_original, datei): fname_pim}
    mapping = {}
    with open(mapping_csv, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f, delimiter=";"):
            orig = row["FNAME_original"].strip()
            pim  = row["FNAME_pim"].strip()
            datei = row["Datei"].strip()
            if orig and pim and orig != pim:
                mapping[(orig, datei)] = pim

    if not mapping:
        progress_fn("Keine Umbenennungen definiert (FNAME_original = FNAME_pim überall).")
        return

    progress_fn(f"{len(mapping)} Umbenennungen geladen.")

    for filename in set(d for _, d in mapping.keys()):
        xml_path = os.path.join(xml_dir, filename)
        if not os.path.exists(xml_path):
            progress_fn(f"  Überspringe {filename} (nicht gefunden)")
            continue

        data_label = XML_FILES.get(filename, filename)
        content  = Path(xml_path).read_text(encoding="utf-8", errors="replace")
        original = content
        count    = 0

        # Nur innerhalb von ARTICLE_FEATURES-Blöcken ersetzen
        def _rewrite_af(m):
            nonlocal count
            block = m.group()
            for (orig, f), pim in mapping.items():
                if f != filename:
                    continue
                # Exakter FNAME-Match (case-sensitive, mit Wortgrenzen)
                pat = re.compile(
                    r'(?s)(<fname>)' + re.escape(orig) + r'(</fname>)',
                    re.IGNORECASE)
                new_block, n = pat.subn(
                    lambda mm: mm.group(1) + pim + mm.group(2), block)
                if n:
                    block  = new_block
                    count += n
            return block

        new_content = _AF_PAT.sub(_rewrite_af, content)

        if new_content != original:
            temp = xml_path + ".bak"
            Path(temp).write_text(original, encoding="utf-8")   # Backup
            Path(xml_path).write_text(new_content, encoding="utf-8")
            progress_fn(f"  {filename}: {count} FNAMEs umbenannt (Backup: .bak)")

            # Kollisions-Check nach Umbenennung
            result = analyse_file(xml_path)
            if result["collisions"]:
                progress_fn(f"  ⚠ {filename} ({data_label}): "
                            f"{len(result['collisions'])} Kollisionen nach Umbenennung!")
                for c in result["collisions"][:10]:
                    progress_fn(f"      AID {c['aid']}: '{c['fname']}' {c['count']}x")
                if len(result["collisions"]) > 10:
                    progress_fn(f"      ... und {len(result['collisions'])-10} weitere")
            else:
                progress_fn(f"  {filename}: keine Kollisionen ✓")
        else:
            progress_fn(f"  {filename}: keine Änderungen")


# ── GUI ───────────────────────────────────────────────────────────────────────

def run_gui():
    root = tk.Tk()
    root.title("BMEcat FNAME-Analyse")
    root.geometry("700x520")
    root.configure(bg="#1e1e2e")

    BG = "#1e1e2e"; BG2 = "#2a2a3e"; FG = "#cdd6f4"
    ACCENT = "#7c7cf8"; GREEN = "#50fa7b"

    tk.Label(root, text="BMEcat FNAME-Analyse",
             font=("Segoe UI Semibold", 13), bg=BG2, fg=ACCENT,
             pady=10).pack(fill="x")

    # Verzeichnis
    dir_frame = tk.Frame(root, bg=BG, pady=6, padx=12)
    dir_frame.pack(fill="x")
    tk.Label(dir_frame, text="XML-Verzeichnis:", font=("Segoe UI", 10),
             bg=BG, fg=FG).pack(side="left")
    dir_var = tk.StringVar(value=os.path.join(os.path.dirname(os.path.abspath(__file__)), "in_BME"))
    tk.Entry(dir_frame, textvariable=dir_var, font=("Consolas", 9),
             bg="#232336", fg=FG, insertbackground=FG,
             relief="flat", bd=4, width=50).pack(side="left", padx=6)

    def browse():
        d = filedialog.askdirectory(title="XML-Verzeichnis wählen")
        if d: dir_var.set(d)
    tk.Button(dir_frame, text="…", command=browse,
              bg=ACCENT, fg="#fff", relief="flat", padx=6).pack(side="left")

    # Log
    log = scrolledtext.ScrolledText(root, font=("Consolas", 9),
                                    bg="#13131f", fg=FG, relief="flat",
                                    state="disabled", height=18)
    log.pack(fill="both", expand=True, padx=12, pady=6)
    log.tag_config("ok",   foreground=GREEN)
    log.tag_config("warn", foreground="#f1fa8c")

    def p(msg, tag=""):
        log.config(state="normal")
        log.insert("end", msg + "\n", tag)
        log.see("end")
        log.config(state="disabled")
        root.update()

    # Buttons
    btn_frame = tk.Frame(root, bg=BG2, pady=8, padx=12)
    btn_frame.pack(fill="x")

    def do_analyse():
        d = dir_var.get()
        if not os.path.isdir(d):
            messagebox.showerror("Fehler", f"Verzeichnis nicht gefunden:\n{d}")
            return
        p(f"Analysiere {d} ...")
        results = analyse_directory(d)
        if not results:
            p("Keine XML-Dateien gefunden.", "warn")
            return
        write_report(results, d)
        write_mapping_csv(results, d)
        write_collisions(results, d)
        write_consolidated_csv(results, d)
        total_fnames = sum(len(r["fname_counts"]) for r in results.values())
        total_coll   = sum(len(r["collisions"])   for r in results.values())
        p(f"\nFertig. {len(results)} Dateien, {total_fnames} FNAME-Einträge gesamt.", "ok")
        if total_coll:
            p(f"⚠ {total_coll} Kollisionen gefunden → fname_collisions.txt", "warn")
        p(f"→ fname_alle.csv        (alle FNAMEs, konsolidiert)")
        p(f"→ fname_report.txt      (Übersicht pro Datei)")
        p(f"→ fname_mapping.csv     (Mapping-Vorlage pro Datei)")
        p(f"→ fname_collisions.txt  (Kollisionen)")

    def do_apply():
        d = dir_var.get()
        mapping_path = os.path.join(d, "fname_mapping.csv")
        if not os.path.exists(mapping_path):
            messagebox.showerror("Fehler",
                "fname_mapping.csv nicht gefunden.\nBitte erst Analyse ausführen.")
            return
        if not messagebox.askyesno("Umbenennungen anwenden",
            "FNAMEs in den XMLs gemäß fname_mapping.csv umbenennen?\n"
            "Backups (.bak) werden angelegt."):
            return
        p("\nWende Mapping an ...")
        apply_mapping(mapping_path, d, progress_fn=p)
        p("Fertig.", "ok")

    for text, cmd in [("▶  Analysieren", do_analyse),
                      ("✎  Mapping anwenden", do_apply)]:
        tk.Button(btn_frame, text=text, command=cmd,
                  font=("Segoe UI", 10), bg=ACCENT, fg="#fff",
                  relief="flat", padx=12, pady=5, cursor="hand2"
                  ).pack(side="left", padx=4)

    tk.Button(btn_frame, text="Öffnen",
              command=lambda: os.startfile(dir_var.get())
                              if os.path.isdir(dir_var.get()) else None,
              font=("Segoe UI", 8), bg="#2a2a3e", fg=FG,
              relief="flat", padx=8, pady=3).pack(side="right", padx=4)

    root.mainloop()


# ── CLI-Fallback ──────────────────────────────────────────────────────────────

def run_cli():
    if len(sys.argv) < 2:
        print("Verwendung: python analyse_fnames.py <xml-verzeichnis>")
        print("         oder: python analyse_fnames.py <xml-verzeichnis> apply")
        sys.exit(1)

    d = sys.argv[1]
    if not os.path.isdir(d):
        print(f"Verzeichnis nicht gefunden: {d}")
        sys.exit(1)

    if len(sys.argv) >= 3 and sys.argv[2] == "apply":
        apply_mapping(os.path.join(d, "fname_mapping.csv"), d)
    else:
        results = analyse_directory(d)
        write_report(results, d)
        write_mapping_csv(results, d)
        write_collisions(results, d)


if __name__ == "__main__":
    if HAS_TK and len(sys.argv) == 1:
        run_gui()
    else:
        run_cli()


# ── Task-Wrapper für main.py ──────────────────────────────────────────────────

def run(progress_cb=None, file_progress_cb=None):
    """
    Wird von main.py als Task aufgerufen.
    Analysiert in_BME und schreibt Ausgaben dorthin.
    Öffnet danach den Ordner im Explorer.
    """
    from config import DIRS
    p = progress_cb or (lambda m, **kw: None)
    d = DIRS["in_bme"]

    if not os.path.isdir(d):
        raise FileNotFoundError(f"Verzeichnis nicht gefunden: {d}")

    p(f"FNAME-Analyse: {d} ...")
    results = analyse_directory(d)

    if not results:
        p("Keine XML-Dateien gefunden.", tag="warn")
        return

    write_report(results, d)
    write_mapping_csv(results, d)
    write_collisions(results, d)
    write_consolidated_csv(results, d)

    total_fnames = sum(len(r["fname_counts"]) for r in results.values())
    total_coll   = sum(len(r["collisions"])   for r in results.values())

    p(f"Fertig: {len(results)} Dateien, {total_fnames} FNAME-Einträge.", tag="ok")
    if total_coll:
        p(f"⚠ {total_coll} Kollisionen → fname_collisions.txt", tag="warn")
    p(f"Ausgaben in: {d}")

    # Ordner öffnen
    try:
        import subprocess
        subprocess.Popen(f'explorer "{d}"', shell=True)
    except Exception:
        pass
