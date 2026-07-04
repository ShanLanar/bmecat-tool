# lib/fname_transforms.py – FNAME/FVALUE-Transformationen für BMEcat-XMLs
#
# Läuft als Post-Processing-Schritt nach dem Merge.
# Konfiguration via CSV-Dateien in BASE_DIR:
#
#   fname_renames.csv   — Spalten: from,to  (FNAME-Umbenennung)
#   fvalue_renames.csv  — Spalten: from,to  (FVALUE-Umbenennung, z.B. CAA016→Ja)
#
# Feste Regeln (immer aktiv):
#   • (0173-...) aus FNAMEs entfernen
#   • FNAME "Marke": MANUFACTURER_NAME ergänzen oder Feature verwerfen

import re
import os
import csv
import logging
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

# ── Patterns ──────────────────────────────────────────────────────────────────

_ECLASS_ID_PAT  = re.compile(r'\s*\([^)]*0173[^)]*\)', re.IGNORECASE)
_FNAME_PAT      = re.compile(r'(<FNAME>)(.*?)(</FNAME>)', re.IGNORECASE | re.DOTALL)
_FVALUE_PAT     = re.compile(r'(<FVALUE>)(.*?)(</FVALUE>)', re.IGNORECASE | re.DOTALL)
_FEATURE_PAT    = re.compile(r'<FEATURE\b[^>]*>.*?</FEATURE>', re.IGNORECASE | re.DOTALL)
_MFR_NAME_PAT   = re.compile(r'<MANUFACTURER_NAME>(.*?)</MANUFACTURER_NAME>', re.IGNORECASE)
_ART_DETAILS_END = re.compile(r'</ARTICLE_DETAILS>', re.IGNORECASE)
_ARTICLE_PAT    = re.compile(r'<ARTICLE\b[^>]*>.*?</ARTICLE>', re.IGNORECASE | re.DOTALL)


# ── Konfiguration laden ───────────────────────────────────────────────────────

def load_rename_csv(path: str) -> dict:
    """
    Liest eine CSV mit from,to-Spalten.
    Erkennt automatisch Komma- oder Semikolon-Delimiter
    (deutsches Excel speichert Semikolon).
    Gibt {from_upper: to} zurück.
    """
    mapping = {}
    if not os.path.exists(path):
        return mapping
    with open(path, "r", encoding="utf-8-sig") as f:
        sample = f.read(4096)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;")
        except csv.Error:
            dialect = csv.excel  # Fallback: Komma
        f.seek(0)
        reader = csv.DictReader(f, dialect=dialect)
        for row in reader:
            src = (row.get("from") or "").strip()
            dst = (row.get("to") or "").strip()
            if src and dst:
                mapping[src.upper()] = dst
    return mapping


def load_transforms(base_dir: str) -> tuple[dict, dict]:
    """
    Lädt fname_renames.csv und fvalue_renames.csv aus BASE_DIR.
    Erstellt Beispieldateien falls nicht vorhanden.

    Returns:
        (fname_map, fvalue_map) — beide: {from_upper: to}
    """
    fname_path  = os.path.join(base_dir, "fname_renames.csv")
    fvalue_path = os.path.join(base_dir, "fvalue_renames.csv")

    # Beispieldateien anlegen wenn nicht vorhanden
    if not os.path.exists(fname_path):
        Path(fname_path).write_text(
            "from,to\n"
            "# Beispiel: Ursprungsland,Herkunftsland\n"
            "# Zeilen mit # werden ignoriert\n",
            encoding="utf-8"
        )

    if not os.path.exists(fvalue_path):
        # Bekannte ECLASS-Wertcodes und Einheitencodes vorbefüllen
        Path(fvalue_path).write_text(
            "from,to\n"
            "# ── Boolesche ECLASS-Werte ──────────────────────────────────\n"
            "CAA016,Ja\n"
            "CAA017,Nein\n"
            "# ── ECLASS-Einheitencodes (UN/CEFACT) ───────────────────────\n"
            "C62,Stück\n"
            "PR,Paar\n"
            "SET,Set\n"
            "MTK,m²\n"
            "MTQ,m³\n"
            "MTR,m\n"
            "CMT,cm\n"
            "MMT,mm\n"
            "INH,Zoll\n"
            "KGM,kg\n"
            "GRM,g\n"
            "MGM,mg\n"
            "LTR,l\n"
            "MLT,ml\n"
            "CLT,cl\n"
            "CMQ,cm³\n"
            "MMQ,mm³\n"
            "WTT,W\n"
            "KWT,kW\n"
            "VLT,V\n"
            "AMP,A\n"
            "MAM,mA\n"
            "HZ,Hz\n"
            "KHZ,kHz\n"
            "MHZ,MHz\n"
            "CEL,°C\n"
            "FAH,°F\n"
            "BAR,bar\n"
            "PAL,Pa\n"
            "MIN,min\n"
            "SEC,s\n"
            "HUR,h\n"
            "DAY,Tag\n"
            "MON,Monat\n"
            "ANN,Jahr\n"
            "RPM,U/min\n"
            "DBM,dB\n"
            "PCT,Prozent\n",
            encoding="utf-8"
        )

    fname_map  = {k: v for k, v in load_rename_csv(fname_path).items()
                  if not k.startswith("#")}
    fvalue_map = {k: v for k, v in load_rename_csv(fvalue_path).items()
                  if not k.startswith("#")}

    return fname_map, fvalue_map


# ── Einzelne Feature-Transformation ──────────────────────────────────────────

def transform_feature(feature_block: str, fname_map: dict, fvalue_map: dict) -> tuple[str, str | None]:
    """
    Wendet alle Transformationen auf einen einzelnen <FEATURE>-Block an.

    Returns:
        (transformed_block, marke_value_or_none)
        - transformed_block: transformierter Block, oder "" wenn verworfen
        - marke_value_or_none: FVALUE wenn FNAME=Marke, sonst None
    """
    # FNAME extrahieren und transformieren
    fname_m = _FNAME_PAT.search(feature_block)
    if not fname_m:
        return feature_block, None

    fname_raw = fname_m.group(2).strip()

    # 1. (0173-...) entfernen
    fname_clean = _ECLASS_ID_PAT.sub("", fname_raw).strip()

    # 2. Aus FNAME-Rename-Map
    fname_new = fname_map.get(fname_clean.upper(), fname_clean)

    # FVALUE extrahieren und transformieren
    fvalue_m = _FVALUE_PAT.search(feature_block)
    fvalue_raw = fvalue_m.group(2).strip() if fvalue_m else ""

    # 3. FVALUE-Rename (z.B. CAA016→Ja)
    fvalue_new = fvalue_map.get(fvalue_raw.upper(), fvalue_raw)

    # Block mit neuen Werten aufbauen
    block = _FNAME_PAT.sub(
        lambda m: m.group(1) + fname_new + m.group(3),
        feature_block, count=1)
    if fvalue_m:
        block = _FVALUE_PAT.sub(
            lambda m: m.group(1) + fvalue_new + m.group(3),
            block, count=1)

    # 4. FNAME == "Marke" → Signal zurückgeben
    if fname_new.strip().lower() == "marke":
        return "", fvalue_new  # Block verwerfen, Wert zurückgeben

    return block, None


# ── Artikel-Transformation ────────────────────────────────────────────────────

def transform_article(article: str, fname_map: dict, fvalue_map: dict) -> str:
    """
    Transformiert alle FEATURE-Blöcke in einem <ARTICLE>-Block.

    Marke-Logik:
    - Hat der Artikel bereits MANUFACTURER_NAME → Marke-Feature verwerfen
    - Hat er keins → MANUFACTURER_NAME in ARTICLE_DETAILS einfügen
    """
    # Bestehendes MANUFACTURER_NAME prüfen
    mfr_m = _MFR_NAME_PAT.search(article)
    has_mfr = mfr_m is not None

    marke_values = []  # gesammelte Marke-FVALUEs

    def _process_feature(m):
        block, marke_val = transform_feature(m.group(), fname_map, fvalue_map)
        if marke_val is not None:
            marke_values.append(marke_val)
            return ""  # Feature verwerfen
        return block

    article = _FEATURE_PAT.sub(_process_feature, article)

    # Marke-Handling: MANUFACTURER_NAME einfügen wenn noch nicht vorhanden
    if marke_values and not has_mfr:
        mfr_value = marke_values[0]  # ersten Wert nehmen
        mfr_tag   = f"<MANUFACTURER_NAME>{mfr_value}</MANUFACTURER_NAME>"
        # In ARTICLE_DETAILS einfügen (vor </ARTICLE_DETAILS>)
        article = _ART_DETAILS_END.sub(
            lambda m: mfr_tag + "\n" + m.group(),
            article, count=1)

    return article


# ── Haupt-Funktion ────────────────────────────────────────────────────────────

def apply_fname_transforms(xml_path: str, base_dir: str,
                            progress_cb=None) -> dict:
    """
    Wendet FNAME/FVALUE-Transformationen auf eine BMEcat-XML an.
    Verarbeitet Artikel-weise (streaming mit Puffer pro Artikel).

    Schritte pro FEATURE-Block:
    1. (0173-...) aus FNAME entfernen
    2. fname_renames.csv anwenden
    3. fvalue_renames.csv anwenden (CAA016→Ja, CAA017→Nein)
    4. FNAME "Marke" → MANUFACTURER_NAME ergänzen oder verwerfen

    Returns:
        dict: Statistiken
    """
    p = progress_cb or (lambda m, **kw: None)

    if not os.path.exists(xml_path):
        p(f"FNAME-Transform: Datei nicht gefunden: {xml_path}", tag="warn")
        return {}

    fname_map, fvalue_map = load_transforms(base_dir)
    p(f"FNAME-Transforms: {len(fname_map)} FNAME-, "
      f"{len(fvalue_map)} FVALUE-Umbenennungen geladen.")
    fname_path = os.path.join(base_dir, "fname_renames.csv")
    if len(fname_map) == 0 and os.path.exists(fname_path):
        p(f"⚠ fname_renames.csv vorhanden aber leer oder unlesbar "
          f"(Semikolon statt Komma? Falsche Kodierung?): {fname_path}", tag="warn")

    tmp_path = xml_path + ".fname_tmp"

    n_features    = 0
    n_fname_clean = 0
    n_fname_ren   = 0
    n_fvalue_ren  = 0
    n_marke_mfr   = 0
    n_marke_drop  = 0

    # Streaming: Artikel einzeln puffern und transformieren
    _ART_OPEN  = re.compile(r'<ARTICLE\b', re.IGNORECASE)
    _ART_CLOSE = re.compile(r'</ARTICLE>', re.IGNORECASE)

    in_article  = False
    art_buf     = []

    def _process_and_flush(art_buf_lines):
        nonlocal n_features, n_fname_clean, n_fname_ren, n_fvalue_ren
        nonlocal n_marke_mfr, n_marke_drop

        article = "".join(art_buf_lines)
        features_before = len(_FEATURE_PAT.findall(article))

        # MANUFACTURER_NAME vorher prüfen
        had_mfr = bool(_MFR_NAME_PAT.search(article))

        # Marke-FVALUEs sammeln (temporär)
        marke_vals = []

        def _proc_feat(m):
            nonlocal n_features, n_fname_clean, n_fname_ren, n_fvalue_ren
            block = m.group()
            fn_m  = _FNAME_PAT.search(block)
            if not fn_m:
                return block

            fname_raw   = fn_m.group(2).strip()
            fname_clean = _ECLASS_ID_PAT.sub("", fname_raw).strip()
            if fname_clean != fname_raw:
                n_fname_clean += 1

            fname_new = fname_map.get(fname_clean.upper(), fname_clean)
            if fname_new != fname_clean:
                n_fname_ren += 1

            fv_m      = _FVALUE_PAT.search(block)
            fvalue_raw = fv_m.group(2).strip() if fv_m else ""
            fvalue_new = fvalue_map.get(fvalue_raw.upper(), fvalue_raw)
            if fvalue_new != fvalue_raw:
                n_fvalue_ren += 1

            n_features += 1

            # Block rekonstruieren
            block = _FNAME_PAT.sub(
                lambda x: x.group(1) + fname_new + x.group(3), block, count=1)
            if fv_m:
                block = _FVALUE_PAT.sub(
                    lambda x: x.group(1) + fvalue_new + x.group(3), block, count=1)

            if fname_new.strip().lower() == "marke":
                marke_vals.append(fvalue_new)
                return ""

            return block

        article = _FEATURE_PAT.sub(_proc_feat, article)

        if marke_vals:
            if had_mfr:
                n_marke_drop += len(marke_vals)
            else:
                mfr_tag = f"<MANUFACTURER_NAME>{marke_vals[0]}</MANUFACTURER_NAME>"
                article = _ART_DETAILS_END.sub(
                    lambda m: mfr_tag + "\n" + m.group(), article, count=1)
                n_marke_mfr += 1

        return article

    from lib.utils import iter_articles

    # Header lesen (alles vor dem ersten Artikel)
    header_buf = []
    with open(xml_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if _ART_OPEN.search(line):
                break
            header_buf.append(line)

    # Footer lesen (alles nach dem letzten Artikel)
    footer_buf = []
    with open(xml_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    last_art_end = content.rfind("</ARTICLE>")
    if last_art_end >= 0:
        footer = content[last_art_end + len("</ARTICLE>"):]
    else:
        footer = ""

    with open(tmp_path, "w", encoding="utf-8") as writer:
        writer.write("".join(header_buf))
        for art_block in iter_articles(xml_path):
            writer.write(_process_and_flush([art_block]))
        writer.write(footer)

    shutil.move(tmp_path, xml_path)

    stats = {
        "features_processed": n_features,
        "fname_cleaned":      n_fname_clean,
        "fname_renamed":      n_fname_ren,
        "fvalue_renamed":     n_fvalue_ren,
        "marke_as_mfr":       n_marke_mfr,
        "marke_dropped":      n_marke_drop,
    }

    p(f"FNAME-Transforms: {n_features} Features verarbeitet — "
      f"{n_fname_clean}× (0173-...) entfernt, "
      f"{n_fname_ren}× FNAME umbenannt, "
      f"{n_fvalue_ren}× FVALUE umbenannt, "
      f"{n_marke_mfr}× Marke→MANUFACTURER_NAME, "
      f"{n_marke_drop}× Marke verworfen.",
      tag="ok")

    return stats


# ── FNAME-Konsistenz-Report ───────────────────────────────────────────────────

_NORM_PUNCT_PAT = re.compile(r'[\s:._\-]+')


def _normalize_fname(fname: str) -> str:
    """Normalisiert einen FNAME für den Gruppenvergleich (Groß/Klein, Whitespace, Satzzeichen)."""
    return _NORM_PUNCT_PAT.sub(' ', fname.strip().lower()).strip()


def report_fname_consistency(xml_path: str, base_dir: str, log_dir: str,
                              progress_cb=None) -> str | None:
    """
    Scannt alle FNAMEs (nach Anwendung von fname_renames.csv) und gruppiert
    sie normalisiert (Groß/Klein, Whitespace, Satzzeichen egal). Gruppen mit
    mehr als einer verbliebenen Schreibweise sind Kandidaten für weitere
    Einträge in fname_renames.csv.

    Schreibt logs/fname_consistency_YYYYMMDD_HHMMSS.csv, wenn Kandidaten
    gefunden wurden. Gibt den Pfad zurück, oder None wenn nichts zu melden ist.
    """
    from lib.utils import iter_articles
    from datetime import datetime

    p = progress_cb or (lambda m, **kw: None)

    if not os.path.exists(xml_path):
        return None

    fname_map, _ = load_transforms(base_dir)

    # normalized_key -> {variant: count}
    groups: dict[str, dict[str, int]] = {}

    for art_block in iter_articles(xml_path):
        for feat_block in _FEATURE_PAT.findall(art_block):
            fn_m = _FNAME_PAT.search(feat_block)
            if not fn_m:
                continue
            fname_raw   = fn_m.group(2).strip()
            fname_clean = _ECLASS_ID_PAT.sub("", fname_raw).strip()
            fname_final = fname_map.get(fname_clean.upper(), fname_clean)
            if not fname_final:
                continue
            key = _normalize_fname(fname_final)
            variants = groups.setdefault(key, {})
            variants[fname_final] = variants.get(fname_final, 0) + 1

    # Nur Gruppen mit >1 verbliebener Schreibweise sind Kandidaten
    candidates = {k: v for k, v in groups.items() if len(v) > 1}
    if not candidates:
        p("FNAME-Konsistenz: keine uneinheitlichen Schreibweisen gefunden.", tag="dim")
        return None

    os.makedirs(log_dir, exist_ok=True)
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(log_dir, f"fname_consistency_{ts}.csv")

    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["normalized_key", "variant", "count", "vorschlag_to"])
        for key, variants in sorted(candidates.items(),
                                     key=lambda kv: -sum(kv[1].values())):
            sorted_variants = sorted(variants.items(), key=lambda kv: -kv[1])
            suggestion = sorted_variants[0][0]   # häufigste Schreibweise als Vorschlag
            for variant, count in sorted_variants:
                writer.writerow([key, variant, count, suggestion])

    p(f"FNAME-Konsistenz: {len(candidates)} Gruppen mit uneinheitlicher Schreibweise "
      f"→ {os.path.basename(out_path)}", tag="warn")
    return out_path
