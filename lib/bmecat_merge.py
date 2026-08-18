# lib/bmecat_merge.py – BMEcat 1.2 Merge
#
# Zwei Quellen → eine merged.xml:
#
#   udx_src   (Büroring br-ek_DE_BMEcat_DEU_ABE.xml)
#             → enthält UDX-Blöcke und ECLASS-9.0-Features
#
#   basis_src (Büroring bf-ek_DE_BMEcat_DEU.xml)
#             → Hauptkatalog, wird als Grundlage verwendet
#
# Was passiert:
#   Phase 0a – ECLASS-Features aus udx_src extrahieren, FNAME umbenennen:
#              "<FNAME>EF000001</FNAME>" + "<FDESCR>Breite</FDESCR>"
#              → "<FNAME>Breite (EF000001)</FNAME>"
#              Verhindert Namenskollisionen beim späteren Import.
#
#   Phase 0b – UDX-Blöcke (<USER_DEFINED_EXTENSIONS>…</USER_DEFINED_EXTENSIONS>)
#              aus udx_src per AID indexieren.
#
#   Phase 1  – basis_src 1:1 nach out_file kopieren (Größenprüfung).
#
#   Phase 2  – out_file zeilenweise einlesen → temp_file schreiben:
#              · Nach </ARTICLE_FEATURES>  → umbenannte ECLASS-Features anhängen
#              · Vor/nach </article>       → UDX-Block einfügen (falls nicht vorhanden)
#              temp_file → out_file ersetzen.

import re
import os
import shutil
import logging
from lib.utils import xml_escape as _xml_escape
from pathlib import Path

log = logging.getLogger(__name__)


# ── Regex-Muster (case-insensitive, DOTALL) ───────────────────────────────────

_AID_PAT      = re.compile(r'(?is)<supplier_aid>(.*?)</supplier_aid>')
_FEATURE_PAT  = re.compile(r'(?is)<feature.*?</feature>')
_FNAME_PAT    = re.compile(r'(?is)<FNAME>(.*?)</FNAME>')
_FDESCR_PAT   = re.compile(r'(?is)<FDESCR>(.*?)</FDESCR>')
_UDX_PAT      = re.compile(r'(?is)<USER_DEFINED_EXTENSIONS.*?</USER_DEFINED_EXTENSIONS>')
_ART_FEAT_END = re.compile(r'(?i)</article_features>')
_ART_FEAT_BEG = re.compile(r'(?i)<article_features[\s>]')
_UDX_END      = re.compile(r'(?i)</user_defined_extensions>')
_ART_END      = re.compile(r'(?i)</article>')
_ART_BEGIN    = re.compile(r'(?i)<article[\s>]')
_AID_LINE     = re.compile(r'(?i)<supplier_aid>(.*?)</supplier_aid>')
_REF_SYS_PAT  = re.compile(r'(?i)<reference_feature_system_name>(.*?)</reference_feature_system_name>')
_ECLASS91_PAT = re.compile(r'(?i)eclass-?9\.1')   # matcht "ECLASS-9.1", "eclass9.1" etc.
_FNAME_LINE   = re.compile(r'(?i)(<FNAME>)(.*?)(</FNAME>)')
_FDESCR_LINE  = re.compile(r'(?i)(<FDESCR>)(.*?)(</FDESCR>)')
_ARTICLE_PAT  = re.compile(r'(?is)<article[\s>].*?</article>')


def _rename_feature(block: str) -> str:
    """
    Für ECLASS-9.0-Features aus udx_src:
    FNAME=Code + FDESCR=Klartext → FNAME="Klartext (Code)"

    Büroring liefert bei manchen Features FNAME bereits als Klartext,
    identisch mit FDESCR (z.B. FNAME=FDESCR="GTIN"). In dem Fall macht
    das Anhängen keinen Sinn ("GTIN (GTIN)") – und verhindert obendrein,
    dass ein gleichnamiges Feature aus einem anderen Block (z.B. jCat)
    beim FNAME-Dedup noch als Duplikat erkannt wird, weil der Name durch
    die Umbenennung nicht mehr exakt übereinstimmt.
    """
    n_m = _FNAME_PAT.search(block)
    d_m = _FDESCR_PAT.search(block)
    if n_m and d_m:
        old_name = n_m.group(1).strip()
        descr    = d_m.group(1).strip()
        if descr.lower() != old_name.lower():
            new_name = f"{descr} ({old_name})"
            block    = _FNAME_PAT.sub(f"<FNAME>{new_name}</FNAME>", block, count=1)
    return block


def _rename_eclass91_block(block: str) -> str:
    """
    Für ECLASS-9.1-Features in der Basisdatei:
    FNAME=Code (z.B. 0173-1#02-AAD931#004) + FDESCR=Klartext
    → FNAME="Klartext (Code)"
    Identisch zur 9.0-Logik, aber separat benannt für Klarheit.
    """
    return _rename_feature(block)


# ── Phase 0 ───────────────────────────────────────────────────────────────────

def _extract_phase0(udx_src: str, progress_cb) -> tuple[dict, dict, dict]:
    """
    Liest udx_src (ABE-Datei) und liefert:
      eclass_feats: { aid → { refsys → [feature_block, …] } }
                    Features gruppiert nach REFERENCE_FEATURE_SYSTEM_NAME,
                    FNAME umbenannt zu "FDESCR (FNAME)"
      udx_blocks:   { aid → udx_block_string }
    """
    p = progress_cb
    p("Phase 0: Lese ABE-Quelle …")

    content = Path(udx_src).read_text(encoding="utf-8", errors="replace")

    eclass_feats: dict[str, dict] = {}
    udx_blocks:   dict[str, str]  = {}

    art_pat = re.compile(r'(?is)<article[\s>].*?</article>')
    af_pat  = re.compile(r'(?is)<article_features.*?</article_features>')

    for art_match in art_pat.finditer(content):
        article = art_match.group()

        aid_m = _AID_PAT.search(article)
        if not aid_m:
            continue
        aid = aid_m.group(1).strip().lower()

        # Features pro Feature-System sammeln
        for af_m in af_pat.finditer(article):
            block  = af_m.group()
            rs_m   = _REF_SYS_PAT.search(block)
            refsys = rs_m.group(1).strip() if rs_m else "unknown"

            is_udf_brj = "udf_brjcat" in refsys.lower()

            if is_udf_brj:
                # udf_BRjCat: Features unverändert (kein FNAME-Rename)
                feats = [f.group() for f in _FEATURE_PAT.finditer(block)]
            else:
                # ECLASS-Features: FNAME → "FDESCR (FNAME)"
                feats = [_rename_feature(f.group())
                         for f in _FEATURE_PAT.finditer(block)]

            if feats:
                if aid not in eclass_feats:
                    eclass_feats[aid] = {}
                if refsys not in eclass_feats[aid]:
                    eclass_feats[aid][refsys] = []
                eclass_feats[aid][refsys].extend(feats)

        # UDX
        udx_m = _UDX_PAT.search(article)
        if udx_m:
            udx_blocks[aid] = udx_m.group()

    total_feats = sum(len(rs) for d in eclass_feats.values() for rs in d.values())
    p(f"  ECLASS-Features: {len(eclass_feats)} Artikel ({total_feats} Blöcke)")
    p(f"  UDX-Blöcke:      {len(udx_blocks)} Artikel")
    return eclass_feats, udx_blocks


# ── Phase 1 ───────────────────────────────────────────────────────────────────

def _copy_basis(basis_src: str, out_file: str, progress_cb):
    p = progress_cb
    p(f"Phase 1: Kopiere Basisdatei → {os.path.basename(out_file)} …")
    shutil.copy2(basis_src, out_file)
    orig_size = os.path.getsize(basis_src)
    copy_size = os.path.getsize(out_file)
    p(f"  Original: {orig_size:,} Bytes  |  Kopie: {copy_size:,} Bytes")
    if orig_size != copy_size:
        raise RuntimeError(
            f"Kopie hat andere Größe! ({copy_size} ≠ {orig_size})")


# ── Phase 2 ───────────────────────────────────────────────────────────────────

# Erkennt ob ein ARTICLE_FEATURES-Block mindestens ein <feature> enthält
_HAS_FEATURE = re.compile(r'(?is)<feature[\s>]')


def _merge_phase2(out_file: str, temp_file: str,
                  eclass_feats: dict, udx_blocks: dict,
                  progress_cb) -> int:
    """
    Liest out_file (Basisdatei-Kopie) zeilenweise, schreibt nach temp_file.

    Operationen pro ARTICLE_FEATURES-Block:
      a) udf_BRjCat-Block (hat <feature>): unverändert, Duplikate entfernen
      b) Leerer ECLASS-Block (kein <feature>): passende Features aus ABE einfügen,
         FNAME = "FDESCR (FNAME)"
      c) ECLASS-9.1-Block mit Features: FNAME-Umbenennung + dedup
      d) Alle anderen (ECLASS-5.x leer, unbekannt): unverändert

    Vor </article>: UDX-Block einfügen falls Basis keinen hat.
    Deduplizierung per FNAME (case-insensitiv) innerhalb jedes Artikels.
    """
    p = progress_cb
    p("Phase 2: Schreibe merged.xml ...")

    inserted_feats = 0
    inserted_udx   = 0
    renamed_91     = 0
    filled_empty   = 0

    with open(out_file, encoding="utf-8", errors="replace") as reader, \
         open(temp_file, "w", encoding="utf-8") as writer:

        in_art      = False
        current_aid = ""
        udx_done    = False
        seen_fnames = set()

        in_af     = False
        af_buf    = []
        af_refsys = ""

        def flush_af_buf():
            nonlocal renamed_91, filled_empty, inserted_feats
            if not af_buf:
                return
            block_str  = "".join(af_buf)
            is_udf_brj = "udf_brjcat" in af_refsys.lower()
            is_udf     = "udf_" in af_refsys.lower()
            is_91      = bool(_ECLASS91_PAT.search(af_refsys))
            has_feats  = bool(_HAS_FEATURE.search(block_str))
            aid        = current_aid

            if is_udf_brj:
                # udf_BRjCat-Block aus Basisdatei:
                # 1. Vorhandene Features behalten (dedup)
                # 2. Fehlende Features aus ABE ergänzen
                def _dedup_base(m):
                    fn_m = _FNAME_PAT.search(m.group())
                    if not fn_m:
                        return m.group()
                    key = fn_m.group(1).strip().lower()
                    if key in seen_fnames:
                        return ""
                    seen_fnames.add(key)
                    return m.group()
                new_block = _FEATURE_PAT.sub(_dedup_base, block_str)

                # ABE-Features für diesen Refsys ergänzen (fehlende)
                abe_udf = eclass_feats.get(aid, {}).get(af_refsys, [])
                to_add  = []
                for fb in abe_udf:
                    fn_m = _FNAME_PAT.search(fb)
                    if not fn_m:
                        continue
                    key = fn_m.group(1).strip().lower()
                    if key not in seen_fnames:
                        seen_fnames.add(key)
                        to_add.append(fb)

                if to_add:
                    end_tag = "</article_features>"
                    idx     = new_block.lower().rfind(end_tag)
                    if idx >= 0:
                        new_block = (new_block[:idx]
                                     + "\n".join(to_add) + "\n"
                                     + new_block[idx:])
                    inserted_feats += len(to_add)
                    filled_empty   += 1

                writer.write(new_block)

            elif is_udf:
                # Andere udf_*-Blöcke: dedup, unverändert
                def _dedup_udf(m):
                    fn_m = _FNAME_PAT.search(m.group())
                    if not fn_m:
                        return m.group()
                    key = fn_m.group(1).strip().lower()
                    if key in seen_fnames:
                        return ""
                    seen_fnames.add(key)
                    return m.group()
                writer.write(_FEATURE_PAT.sub(_dedup_udf, block_str))

            elif not has_feats:
                # Leerer ECLASS-Block: passende ABE-Features einfügen
                abe_for_sys = eclass_feats.get(aid, {}).get(af_refsys, [])
                if abe_for_sys:
                    end_tag = "</article_features>"
                    idx     = block_str.lower().rfind(end_tag)
                    if idx >= 0:
                        to_insert = []
                        for fb in abe_for_sys:
                            fn_m = _FNAME_PAT.search(fb)
                            if not fn_m:
                                continue
                            key = fn_m.group(1).strip().lower()
                            if key not in seen_fnames:
                                seen_fnames.add(key)
                                to_insert.append(fb)
                        if to_insert:
                            new_block = (block_str[:idx]
                                         + "\n".join(to_insert) + "\n"
                                         + block_str[idx:])
                            writer.write(new_block)
                            filled_empty   += 1
                            inserted_feats += len(to_insert)
                        else:
                            writer.write(block_str)
                    else:
                        writer.write(block_str)
                else:
                    writer.write(block_str)

            elif is_91 and has_feats:
                # ECLASS-9.1 mit Features: FNAME umbenennen + dedup
                def _ren91(m):
                    renamed = _rename_eclass91_block(m.group())
                    fn_m = _FNAME_PAT.search(renamed)
                    if not fn_m:
                        return renamed
                    key = fn_m.group(1).strip().lower()
                    if key in seen_fnames:
                        return ""
                    seen_fnames.add(key)
                    return renamed
                new_block = _FEATURE_PAT.sub(_ren91, block_str)
                if new_block != block_str:
                    renamed_91 += 1
                writer.write(new_block)

            else:
                # Sonstige: unverändert
                writer.write(block_str)

            af_buf.clear()

        for line in reader:
            clean = line.strip().lower()

            if _ART_BEGIN.search(clean):
                in_art      = True
                current_aid = ""
                udx_done    = False
                seen_fnames = set()

            if in_art and not current_aid:
                aid_m = _AID_LINE.search(line)
                if aid_m:
                    current_aid = aid_m.group(1).strip().lower()

            if in_art and not udx_done and _UDX_END.search(clean):
                udx_done = True

            if in_art and _ART_END.search(clean):
                flush_af_buf()
                if not udx_done and current_aid in udx_blocks:
                    udx_xml = udx_blocks[current_aid]
                    writer.write(udx_xml)
                    if not udx_xml.endswith("\n"):
                        writer.write("\n")
                    inserted_udx += 1
                in_art = False

            if _ART_FEAT_BEG.search(clean):
                in_af     = True
                af_refsys = ""
                af_buf.clear()

            if in_af:
                af_buf.append(line)
                rs_m = _REF_SYS_PAT.search(line)
                if rs_m:
                    af_refsys = rs_m.group(1).strip()
                if _ART_FEAT_END.search(clean):
                    flush_af_buf()
                    in_af = False
            else:
                writer.write(line)

    p(f"  udf_BRjCat: Basis-Features behalten + ABE ergaenzt ({inserted_feats} neu)")
    p(f"  Leere ECLASS-Bloecke gefuellt:  {filled_empty}")
    p(f"  ECLASS-9.1 umbenannt:           {renamed_91} Bloecke")
    p(f"  UDX eingefuegt:                 {inserted_udx} Artikel")
    return inserted_udx + inserted_feats + renamed_91



# ── Hauptfunktion ─────────────────────────────────────────────────────────────

def merge(udx_src: str, basis_src: str, out_file: str,
          progress_cb=None) -> dict:
    """
    Führt den vollständigen Merge durch.

    Parameter:
        udx_src    Pfad zur Büroring-ABE-Datei (mit UDX + ECLASS-Features)
        basis_src  Pfad zur Büroring-Basis-Datei (Hauptkatalog)
        out_file   Zielpfad für bueroring_merged.xml
        progress_cb  Callable(msg, tag="") für GUI-Log

    Rückgabe:
        dict mit Statistiken
    """
    p = progress_cb or (lambda m, **kw: None)
    temp_file = out_file + ".tmp"

    # Eingaben prüfen
    for path, label in [(udx_src, "UDX-Quelle"), (basis_src, "Basisdatei")]:
        if not os.path.exists(path):
            raise FileNotFoundError(f"{label} nicht gefunden: {path}")

    orig_size = os.path.getsize(basis_src)

    # Phase 0: Features + UDX aus ABE-Datei extrahieren
    eclass_feats, udx_blocks = _extract_phase0(udx_src, p)

    # Phase 1: Basisdatei kopieren
    _copy_basis(basis_src, out_file, p)

    # Phase 2: Features + UDX einfügen
    total_inserted = _merge_phase2(out_file, temp_file,
                                   eclass_feats, udx_blocks, p)

    # temp → out ersetzen
    p("Ersetze Ausgabedatei …")
    os.replace(temp_file, out_file)

    # Erste 3 Zeilen von udx_src (bueroring.xml) in Ausgabe übernehmen
    # (XML-Deklaration + BMECAT-Header der ABE-Datei sind maßgeblich)
    p("Übernehme Header-Zeilen aus bueroring.xml …")
    try:
        with open(udx_src, encoding="utf-8", errors="replace") as f:
            udx_lines = [next(f) for _ in range(3)]
        with open(out_file, encoding="utf-8", errors="replace") as f:
            out_lines = f.readlines()
        # Ersetze die ersten 3 Zeilen der Ausgabe durch die der ABE
        merged_lines = udx_lines + out_lines[3:]
        with open(out_file, "w", encoding="utf-8") as f:
            f.writelines(merged_lines)
    except Exception as e:
        p(f"  Header-Übernahme fehlgeschlagen: {e}", tag="warn")

    new_size = os.path.getsize(out_file)
    delta    = new_size - orig_size

    # ── Qualitätsbericht ──────────────────────────────────────────────────────
    p("─" * 50)
    p("Qualitätsbericht:")
    p(f"  Artikel mit UDX-Block:          {len(udx_blocks):>6}")
    p(f"  Artikel mit ECLASS-Features:    {len(eclass_feats):>6}")
    p(f"  Einträge eingefügt:             {total_inserted:>6}")
    p(f"  Originalgröße:  {orig_size:>12,} Bytes")
    p(f"  Neue Größe:     {new_size:>12,} Bytes")
    p(f"  Differenz:      {delta:>+12,} Bytes")

    # Qualitäts-Check: Artikel ohne jegliche Features zählen
    try:
        no_features = 0
        content = Path(out_file).read_text(encoding="utf-8", errors="replace")
        for art_m in _ARTICLE_PAT.finditer(content):
            if not _HAS_FEATURE.search(art_m.group()):
                no_features += 1
        if no_features:
            p(f"  ⚠ Artikel ohne Features:        {no_features:>6}", tag="warn")
        else:
            p(f"  Alle Artikel haben Features.", tag="ok")
    except Exception:
        pass

    if delta < 0:
        p("WARNUNG: Ausgabedatei ist kleiner als Original!", tag="warn")
    elif delta == 0:
        p("WARNUNG: Keine Daten eingefügt (AIDs nicht gefunden?)", tag="warn")
    else:
        p(f"Merge abgeschlossen → {os.path.basename(out_file)}", tag="ok")

    return {
        "orig_size":      orig_size,
        "new_size":       new_size,
        "delta":          delta,
        "total_inserted": total_inserted,
        "eclass_count":   len(eclass_feats),
        "udx_count":      len(udx_blocks),
        "no_features":    no_features if 'no_features' in dir() else 0,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Keyword-Inject für bueroring_merged.xml
# ──────────────────────────────────────────────────────────────────────────────

def _load_keywords(csv_path: str, progress_cb=None) -> dict:
    """
    Liest keywords_exploded.csv und gibt zurück:
    { supplier_aid_lower → [keyword, ...] }
    """
    import csv as _csv
    p = progress_cb or (lambda m, **kw: None)
    result = {}
    if not os.path.exists(csv_path):
        p(f"Keywords-Datei nicht gefunden: {csv_path}", tag="warn")
        return result
    with open(csv_path, encoding="utf-8", errors="replace") as f:
        for row in _csv.DictReader(f):
            aid = row.get("supplier_aid", "").strip().lower()
            kw  = row.get("keyword", "").strip()
            if aid and kw:
                if aid not in result:
                    result[aid] = []
                result[aid].append(kw)
    p(f"Keywords geladen: {len(result)} Artikel, "
      f"{sum(len(v) for v in result.values())} Keywords gesamt")
    return result


def inject_keywords(xml_path: str, keywords: dict,
                    progress_cb=None) -> int:
    """
    Fügt pro Artikel Keywords aus der Tabelle in <ARTICLE_DETAILS> ein.
    Bestehende Keywords bleiben, neue werden dedupliziert ergänzt.
    Schreibt direkt zurück in xml_path.
    Gibt Anzahl geänderter Artikel zurück.
    """
    p = progress_cb or (lambda m, **kw: None)
    if not keywords:
        return 0

    _KW_PAT      = re.compile(r'(?is)<keyword>(.*?)</keyword>')
    _DETAILS_END = re.compile(r'(?i)</article_details>')

    p("Injiziere Keywords …")
    content = Path(xml_path).read_text(encoding="utf-8", errors="replace")
    changed = 0

    def _process_article(m):
        nonlocal changed
        article = m.group()
        aid_m   = _AID_PAT.search(article)
        if not aid_m:
            return article
        aid = aid_m.group(1).strip().lower()

        new_kws = keywords.get(aid)
        if not new_kws:
            return article

        # Bestehende Keywords (case-insensitiv)
        existing = {k.group(1).strip().lower()
                    for k in _KW_PAT.finditer(article)}
        to_add   = [kw for kw in new_kws
                    if kw.strip().lower() not in existing]
        if not to_add:
            return article

        kw_xml = "\n".join(f"        <KEYWORD>{_xml_escape(kw)}</KEYWORD>"
                           for kw in to_add)
        end_m  = _DETAILS_END.search(article)
        if not end_m:
            return article

        changed += 1
        pos = end_m.start()
        return article[:pos] + kw_xml + "\n        " + article[pos:]

    new_content = _ARTICLE_PAT.sub(_process_article, content)

    if changed:
        Path(xml_path).write_text(new_content, encoding="utf-8")
        p(f"  Keywords injiziert: {changed} Artikel aktualisiert", tag="ok")
    else:
        p("  Keine neuen Keywords gefunden.")

    return changed


def sanitize_xml(xml_path: str, progress_cb=None) -> int:
    """
    Repariert nackte Ampersands (&) im gesamten XML.

    Ein & ohne nachfolgendes Entity-Pattern (amp;, lt;, gt;, quot;, apos;, #...)
    wird zu &amp; escaped.

    Wird als letzter Schritt nach Merge + Keywords aufgerufen.
    Gibt die Anzahl reparierter Stellen zurück.
    """
    from lib.utils import xml_fix_ampersands
    p = progress_cb or (lambda m, **kw: None)

    content = Path(xml_path).read_text(encoding="utf-8", errors="replace")
    fixed = xml_fix_ampersands(content)

    n_fixes = fixed.count("&amp;") - content.count("&amp;")

    if n_fixes > 0:
        Path(xml_path).write_text(fixed, encoding="utf-8")
        p(f"  XML-Sanitize: {n_fixes} nackte Ampersands repariert in "
          f"{os.path.basename(xml_path)}", tag="warn")
    else:
        p(f"  XML-Sanitize: keine nackten Ampersands gefunden.", tag="dim")

    return n_fixes

# Matcht einen kompletten UDX-Block
_UDX_BLOCK_PAT  = re.compile(
    r'(?is)(<USER_DEFINED_EXTENSIONS>)(.*?)(</USER_DEFINED_EXTENSIONS>)')

# Matcht einzelne UDX-Tags: <UDX.TAGNAME>Wert</UDX.TAGNAME>
_UDX_TAG_PAT    = re.compile(
    r'(?is)<(UDX\.[^>]+)>(.*?)</\1>')

# Einrückung die vor dem UDX-Block stand (für sauberes Formatting)
_UDX_INDENT_PAT = re.compile(r'(?m)^([ \t]*)<USER_DEFINED_EXTENSIONS>')


def _udx_block_to_features(match: re.Match) -> str:
    """
    Wandelt einen kompletten USER_DEFINED_EXTENSIONS-Block in einen
    ARTICLE_FEATURES-Block mit REFERENCE_FEATURE_SYSTEM_NAME=udf_NDW-0.1 um.

    <UDX.LAENGE>140,000</UDX.LAENGE>
    →
    <FEATURE>
      <FNAME>LAENGE</FNAME>
      <FVALUE>140,000</FVALUE>
      <FDESCR>laenge</FDESCR>
    </FEATURE>

    Eingebettet in:
    <ARTICLE_FEATURES>
      <REFERENCE_FEATURE_SYSTEM_NAME>udf_NDW-0.1</REFERENCE_FEATURE_SYSTEM_NAME>
      ...
    </ARTICLE_FEATURES>
    """
    inner = match.group(2)
    tags  = _UDX_TAG_PAT.findall(inner)   # [(tagname, value), ...]

    if not tags:
        return ""   # leerer Block → komplett entfernen

    lines = ["\t\t<ARTICLE_FEATURES>",
             "\t\t\t<REFERENCE_FEATURE_SYSTEM_NAME>udf_NDW-0.1</REFERENCE_FEATURE_SYSTEM_NAME>"]

    for tag_full, value in tags:
        # "UDX.LAENGE" → "LAENGE"; "UDX.SOE.GPSRHERSTELLEREMAIL" → "GPSRHERSTELLEREMAIL"
        # (rsplit statt split: nur der letzte Teil ist der eigentliche Feldname,
        # alles davor sind UDX/Namespace-Prefixe wie "UDX." oder "UDX.SOE.")
        fname  = tag_full.rsplit(".", 1)[-1] if "." in tag_full else tag_full
        fdescr = fname.lower()
        value  = value.strip()
        lines.append(
            f"\t\t\t<FEATURE>\n"
            f"\t\t\t\t<FNAME>{_xml_escape(fname)}</FNAME>\n"
            f"\t\t\t\t<FVALUE>{_xml_escape(value)}</FVALUE>\n"
            f"\t\t\t\t<FDESCR>{_xml_escape(fdescr)}</FDESCR>\n"
            f"\t\t\t</FEATURE>"
        )

    lines.append("\t\t</ARTICLE_FEATURES>")
    return "\n".join(lines)


def convert_udx_to_features(xml_path: str, progress_cb=None) -> dict:
    """
    Liest xml_path, wandelt alle USER_DEFINED_EXTENSIONS-Blöcke in
    normale FEATURE-Blöcke um und schreibt die Datei zurück.

    Jedes <UDX.TAGNAME>Wert</UDX.TAGNAME> wird zu:
        <FEATURE>
            <FNAME>TAGNAME</FNAME>
            <FVALUE>Wert</FVALUE>
        </FEATURE>

    Der USER_DEFINED_EXTENSIONS-Block selbst wird entfernt.
    Die neuen FEATURE-Blöcke werden an gleicher Stelle eingefügt.

    Rückgabe: {"converted": int, "file": str}
    """
    p = progress_cb or (lambda m, **kw: None)

    if not os.path.exists(xml_path):
        raise FileNotFoundError(f"Datei nicht gefunden: {xml_path}")

    name = os.path.basename(xml_path)
    p(f"UDX→Features: lese {name} …")

    content  = Path(xml_path).read_text(encoding="utf-8", errors="replace")
    orig_len = len(content)

    # Zählen wie viele Blöcke konvertiert werden
    count = len(_UDX_BLOCK_PAT.findall(content))

    # Ersetzen
    new_content = _UDX_BLOCK_PAT.sub(_udx_block_to_features, content)

    # Zurückschreiben
    temp = xml_path + ".tmp"
    Path(temp).write_text(new_content, encoding="utf-8")
    os.replace(temp, xml_path)

    new_len = len(new_content)
    p(f"  {name}: {count} UDX-Blöcke konvertiert  "
      f"({orig_len:,} → {new_len:,} Zeichen, Δ{new_len-orig_len:+,})",
      tag="ok")

    return {"converted": count, "file": xml_path}


# ──────────────────────────────────────────────────────────────────────────────
# FNAME-Deduplizierung
# ──────────────────────────────────────────────────────────────────────────────

# Matcht einen einzelnen <FEATURE>…</FEATURE>-Block
_FEATURE_BLOCK_PAT = re.compile(r'(?is)<feature>(.*?)</feature>')


def deduplicate_fnames(xml_path: str, progress_cb=None) -> dict:
    """
    Entfernt doppelte FNAMEs innerhalb jedes <ARTICLE>-Blocks.

    Vorgehen pro Artikel:
    - Alle <FEATURE>-Blöcke werden gescannt
    - Das erste Vorkommen jedes FNAME bleibt erhalten
    - Jedes weitere Vorkommen desselben FNAME (case-insensitiv) wird gelöscht
    - Leerzeilen die durch das Löschen entstehen werden bereinigt

    Rückgabe:
        {
          "removed":  int,                    # Anzahl gelöschter Features
          "articles": [{aid, fnames}],        # betroffene Artikel
          "file":     str,
        }
    """
    p = progress_cb or (lambda m, **kw: None)

    if not os.path.exists(xml_path):
        raise FileNotFoundError(f"Datei nicht gefunden: {xml_path}")

    name     = os.path.basename(xml_path)
    content  = Path(xml_path).read_text(encoding="utf-8", errors="replace")
    orig_len = len(content)

    total_removed   = 0
    affected_arts   = []

    def _dedup_article(art_match: re.Match) -> str:
        nonlocal total_removed
        article = art_match.group()

        # AID für Reporting
        aid_m = _AID_PAT.search(article)
        aid   = aid_m.group(1).strip() if aid_m else "?"

        seen_fnames: set = set()
        removed_here: list = []

        def _check_feature(feat_match: re.Match) -> str:
            inner  = feat_match.group(1)   # Inhalt zwischen <feature>…</feature>
            fn_m   = _FNAME_PAT.search(inner)
            if not fn_m:
                return feat_match.group()  # kein FNAME → unverändert

            fname     = fn_m.group(1).strip()
            fname_key = fname.lower()

            if fname_key in seen_fnames:
                # Duplikat → leeren String zurück (= löschen)
                removed_here.append(fname)
                return ""
            else:
                seen_fnames.add(fname_key)
                return feat_match.group()

        new_article = _FEATURE_BLOCK_PAT.sub(_check_feature, article)

        if removed_here:
            total_removed += len(removed_here)
            affected_arts.append({"aid": aid, "removed": removed_here})
            # Mehrfach-Leerzeilen bereinigen die durch das Löschen entstehen
            new_article = re.sub(r'\n{3,}', '\n\n', new_article)

        return new_article

    new_content = _ARTICLE_PAT.sub(_dedup_article, content)

    if total_removed > 0:
        temp = xml_path + ".tmp"
        Path(temp).write_text(new_content, encoding="utf-8")
        os.replace(temp, xml_path)
        p(f"  {name}: {total_removed} doppelte Features entfernt "
          f"in {len(affected_arts)} Artikel(n)", tag="warn")
        # Detail-Zeilen sind pro Aufruf teuer (GUI-Insert + Datei-Append) –
        # bei mehreren tausend betroffenen Artikeln kostet das reine Loggen
        # sonst Minuten, ohne dass danach noch etwas verarbeitet wird.
        _DETAIL_LIMIT = 50
        for a in affected_arts[:_DETAIL_LIMIT]:
            dupes = ", ".join(a["removed"])
            p(f"    AID {a['aid']}: entfernt → {dupes}", tag="warn")
        if len(affected_arts) > _DETAIL_LIMIT:
            p(f"    … und {len(affected_arts) - _DETAIL_LIMIT} weitere Artikel "
              f"(gekürzt, siehe Details bei Bedarf im XML-Diff)", tag="warn")
    else:
        p(f"  {name}: keine doppelten FNAMEs gefunden", tag="ok")

    return {
        "removed":  total_removed,
        "articles": affected_arts,
        "file":     xml_path,
    }


def deduplicate_files(xml_paths: list, progress_cb=None) -> dict:
    """
    Führt deduplicate_fnames() auf mehreren Dateien aus.
    Gibt Gesamt-Statistik zurück.
    """
    p = progress_cb or (lambda m, **kw: None)
    total   = {"removed": 0, "files": 0, "articles": 0}
    details = []

    for path in xml_paths:
        if not os.path.exists(path):
            p(f"  Überspringe (nicht gefunden): {os.path.basename(path)}", tag="warn")
            continue
        result = deduplicate_fnames(path, progress_cb=p)
        details.append(result)
        total["removed"]  += result["removed"]
        total["articles"] += len(result["articles"])
        if result["removed"] > 0:
            total["files"] += 1

    return {"total": total, "details": details}


