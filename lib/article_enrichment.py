# lib/article_enrichment.py
#
# Regelbasierte Nachbearbeitung von BMEcat-Dateien.
# Wird nach dem Merge auf bueroring_merged.xml angewendet.
#
# Regeln:
#   1. Fehlende DESCRIPTION_LONG → Fallback aus udf_BRjCat-Features
#      Priorität: "Langbeschreibung (Online)" → "Langbeschreibung" → "Kurzbeschreibung (Online)"
#                → "Anreißer (Online)" → "Kurzbeschreibung"
#
#   2. Fehlender MANUFACTURER_NAME → Fallback aus udf_BRjCat "Marke" oder "Hersteller"
#
# Erweiterbar: neue Regeln als Funktionen mit Signatur
#   rule_xxx(article: str) -> str

import re
import os
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# ── Regex-Muster ──────────────────────────────────────────────────────────────

_ARTICLE_PAT   = re.compile(r'(?is)(<article[\s>].*?</article>)')
_AID_PAT       = re.compile(r'(?is)<supplier_aid>(.*?)</supplier_aid>')
_DESC_LONG_PAT = re.compile(r'(?is)<description_long>(.*?)</description_long>')
_DESC_SHORT_PAT= re.compile(r'(?is)<description_short>(.*?)</description_short>')
_MFR_PAT       = re.compile(r'(?is)<manufacturer_name>(.*?)</manufacturer_name>')
_AF_PAT        = re.compile(r'(?is)<article_features>(.*?)</article_features>')
_RS_PAT        = re.compile(r'(?is)<reference_feature_system_name>(.*?)</reference_feature_system_name>')
_FEAT_PAT      = re.compile(r'(?is)<feature>(.*?)</feature>')
_FNAME_PAT     = re.compile(r'(?is)<fname>(.*?)</fname>')
_FVALUE_PAT    = re.compile(r'(?is)<fvalue>(.*?)</fvalue>')
_DETAILS_END   = re.compile(r'(?i)(</article_details>)')
_MFR_AID_END   = re.compile(r'(?i)(</manufacturer_aid>)')
_KEYWORD_PAT   = re.compile(r'(?i)<keyword>(.*?)</keyword>')
_EAN_PAT       = re.compile(
    r'(?is)<(?:ean|international_pid[^>]*)>(.*?)</(?:ean|international_pid)>')


def _get_brjcat_features(article: str) -> dict:
    """
    Extrahiert alle FNAME→FVALUE-Paare aus dem udf_BRjCat-Block.
    Gibt Dict {fname_lower: fvalue} zurück.
    """
    result = {}
    for af_m in _AF_PAT.finditer(article):
        block = af_m.group(1)
        rs_m  = _RS_PAT.search(block)
        if not rs_m or "brjcat" not in rs_m.group(1).lower():
            continue
        for feat_m in _FEAT_PAT.finditer(block):
            inner  = feat_m.group(1)
            fn_m   = _FNAME_PAT.search(inner)
            fv_m   = _FVALUE_PAT.search(inner)
            if fn_m and fv_m:
                fname  = fn_m.group(1).strip()
                fvalue = fv_m.group(1).strip()
                if fvalue:
                    result[fname.lower()] = fvalue
    return result


from lib.utils import xml_escape as _xml_escape


# ── Regel 1: DESCRIPTION_LONG Fallback ───────────────────────────────────────

# Prioritätsliste der Quell-Features (Kleinbuchstaben)
_DESC_LONG_FALLBACKS = [
    "langbeschreibung (online)",
    "langbeschreibung",
    "kurzbeschreibung (online)",
    "anreißer (online)",
    "kurzbeschreibung",
]


def rule_description_long(article: str) -> tuple[str, bool]:
    """
    Füllt fehlende DESCRIPTION_LONG aus udf_BRjCat-Features auf.
    Gibt (neuer_artikel, verändert) zurück.
    """
    # Bereits vorhanden und nicht leer?
    dl_m = _DESC_LONG_PAT.search(article)
    if dl_m and dl_m.group(1).strip():
        return article, False

    features = _get_brjcat_features(article)

    # Ersten passenden Fallback suchen
    fallback = None
    for key in _DESC_LONG_FALLBACKS:
        val = features.get(key, "")
        if val and val.strip():
            fallback = val.strip()
            break

    if not fallback:
        return article, False

    escaped = _xml_escape(fallback)

    if dl_m:
        # Leeres Tag ersetzen
        new_article = _DESC_LONG_PAT.sub(
            f"<DESCRIPTION_LONG>{escaped}</DESCRIPTION_LONG>", article, count=1)
    else:
        # Vor </ARTICLE_DETAILS> einfügen
        new_article = _DETAILS_END.sub(
            f"        <DESCRIPTION_LONG>{escaped}</DESCRIPTION_LONG>\n\\1",
            article, count=1)

    return new_article, new_article != article


# ── Regel 2: MANUFACTURER_NAME Fallback ──────────────────────────────────────

_MFR_FALLBACKS = [
    "marke",
    "hersteller",
    "hersteller-name",
    "gpsr hersteller name",   # GPSR-Kontaktdaten als letzter Fallback
]


def rule_manufacturer_name(article: str) -> tuple[str, bool]:
    """
    Füllt fehlenden MANUFACTURER_NAME aus udf_BRjCat-Features auf.
    Gibt (neuer_artikel, verändert) zurück.
    """
    mfr_m = _MFR_PAT.search(article)
    if mfr_m and mfr_m.group(1).strip():
        return article, False

    features = _get_brjcat_features(article)

    fallback = None
    for key in _MFR_FALLBACKS:
        val = features.get(key, "")
        if val and val.strip():
            fallback = val.strip()
            break

    if not fallback:
        return article, False

    escaped = _xml_escape(fallback)

    if mfr_m:
        new_article = _MFR_PAT.sub(
            f"<MANUFACTURER_NAME>{escaped}</MANUFACTURER_NAME>", article, count=1)
    else:
        # Nach MANUFACTURER_AID einfügen falls vorhanden, sonst vor </ARTICLE_DETAILS>
        if _MFR_AID_END.search(article):
            new_article = _MFR_AID_END.sub(
                f"\\1\n        <MANUFACTURER_NAME>{escaped}</MANUFACTURER_NAME>",
                article, count=1)
        else:
            new_article = _DETAILS_END.sub(
                f"        <MANUFACTURER_NAME>{escaped}</MANUFACTURER_NAME>\n\\1",
                article, count=1)

    return new_article, new_article != article



# ── Regel 2b: Hersteller-Normalisierung via Alias-Tabelle ────────────────────

_mfr_aliases: dict | None = None

def _load_mfr_aliases() -> dict:
    """Lädt manufacturer_aliases.csv aus BASE_DIR (gecacht)."""
    global _mfr_aliases
    if _mfr_aliases is not None:
        return _mfr_aliases
    try:
        import config as _cfg, csv
        path = os.path.join(_cfg.BASE_DIR, "manufacturer_aliases.csv")
        if not os.path.exists(path):
            # Standardwerte anlegen
            with open(path, "w", encoding="utf-8") as f:
                f.write(
                    "from,to\n"
                    "HEWLETT PACKARD,HP\n"
                    "HEWLETT-PACKARD,HP\n"
                    "MICROSOFT CORPORATION,Microsoft\n"
                    "SAMSUNG ELECTRONICS,Samsung\n"
                    "EPSON DEUTSCHLAND,Epson\n"
                    "3M DEUTSCHLAND,3M\n"
                )
        aliases = {}
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            for row in csv.DictReader(f):
                src = (row.get("from") or "").strip().upper()
                dst = (row.get("to") or "").strip()
                if src and dst and not src.startswith("#"):
                    aliases[src] = dst
        _mfr_aliases = aliases
    except Exception:
        _mfr_aliases = {}
    return _mfr_aliases


def rule_manufacturer_normalize(article: str) -> tuple[str, bool]:
    """
    Normalisiert MANUFACTURER_NAME via manufacturer_aliases.csv.
    Exakter Vergleich nach Uppercase — kein Fuzzy-Matching hier.
    Beispiel: "HEWLETT PACKARD" → "HP"
    """
    m = _MFR_PAT.search(article)
    if not m:
        return article, False
    mfr = m.group(1).strip()
    if not mfr:
        return article, False
    aliases = _load_mfr_aliases()
    normalized = aliases.get(mfr.upper())
    if not normalized or normalized == mfr:
        return article, False
    from lib.utils import xml_escape as _xe
    article = article[:m.start(1)] + _xe(normalized) + article[m.end(1):]
    return article, True

# ── Regel 3: EAN als Keyword ──────────────────────────────────────────────────

def rule_ean_keyword(article: str) -> tuple[str, bool]:
    """
    Fügt die EAN/GTIN als <KEYWORD> ein, falls noch nicht vorhanden.

    Quelle: <EAN> oder <INTERNATIONAL_PID type="ean"> in ARTICLE_DETAILS.
    Einfügeort: nach dem letzten vorhandenen <KEYWORD>-Tag.
    """
    ean_m = _EAN_PAT.search(article)
    if not ean_m:
        return article, False

    ean = ean_m.group(1).strip()
    if not ean or not ean.isdigit() or len(ean) not in (8, 13, 14):
        return article, False

    # Bereits als Keyword vorhanden?
    existing = [m.group(1).strip() for m in _KEYWORD_PAT.finditer(article)]
    if ean in existing:
        return article, False

    # Nach letztem Keyword einfügen
    last_kw = list(_KEYWORD_PAT.finditer(article))
    if last_kw:
        pos = last_kw[-1].end()
        article = article[:pos] + f"\n        <KEYWORD>{ean}</KEYWORD>" + article[pos:]
    else:
        # Kein Keyword vorhanden → vor </ARTICLE_DETAILS>
        article = _DETAILS_END.sub(
            f"        <KEYWORD>{ean}</KEYWORD>\n\\1", article, count=1)

    return article, True


# ── Regel 4: Keyword-Deduplication ───────────────────────────────────────────

def rule_keyword_dedup(article: str) -> tuple[str, bool]:
    """
    Entfernt doppelte <KEYWORD>-Tags (case-insensitiv, erste Schreibweise bleibt).

    Beispiel: CASIO + Casio + casio → nur CASIO (erste Schreibweise)
    """
    keywords = list(_KEYWORD_PAT.finditer(article))
    if len(keywords) <= 1:
        return article, False

    seen = set()
    to_remove = []
    for m in keywords:
        val = m.group(1).strip()
        key = val.lower()
        if key in seen:
            to_remove.append(m)
        else:
            seen.add(key)

    if not to_remove:
        return article, False

    # Rückwärts entfernen (Positionen bleiben gültig)
    for m in reversed(to_remove):
        # Ganzen Tag + optionales Leerzeichen/Newline davor entfernen
        start = m.start()
        end   = m.end()
        # Einrückung vor dem Tag mitentfernen
        while start > 0 and article[start - 1] in (" ", "\t"):
            start -= 1
        # Newline nach dem Tag mitentfernen
        if end < len(article) and article[end] == "\n":
            end += 1
        article = article[:start] + article[end:]

    return article, True


_AID_SUFFIX_PAT = re.compile(r'\s*\([A-Z0-9]{4,30}\)\s*$')


# ── Regel 5: AID-Suffix aus DESCRIPTION_SHORT entfernen ─────────────────────

def rule_clean_desc_short(article: str) -> tuple[str, bool]:
    """
    Entfernt Artikel-ID-Suffixe aus DESCRIPTION_SHORT.

    'Wissenschaftlicher Schulrechner FX-87DEX (CASFX87DEX)'
     -> 'Wissenschaftlicher Schulrechner FX-87DEX'

    Regex: r'\\s*\\([A-Z0-9]{4,30}\\)$' — Großbuchstaben/Ziffern in Klammern am Ende.
    """
    m = _DESC_SHORT_PAT.search(article)
    if not m:
        return article, False

    original = m.group(1)
    cleaned  = _AID_SUFFIX_PAT.sub("", original).strip()

    if cleaned == original:
        return article, False

    article = article[:m.start(1)] + cleaned + article[m.end(1):]
    return article, True


_DELIVERY_PAT = re.compile(r'<DELIVERY_TIME>', re.IGNORECASE)


# ── Regel 6: GTIN Auto-Fix ────────────────────────────────────────────────────

def rule_gtin_fix(article: str) -> tuple[str, bool]:
    """
    Korrigiert EANs bei denen nur die letzte Stelle (Prüfziffer) falsch ist.
    Ändert ausschließlich die letzte Ziffer — nie die ersten 12/7.
    """
    from lib.utils import gtin_valid, gtin_fix
    ean_m = _EAN_PAT.search(article)
    if not ean_m:
        return article, False
    ean = ean_m.group(1).strip()
    if not ean or not ean.isdigit() or len(ean) not in (8, 13, 14):
        return article, False
    if gtin_valid(ean):
        return article, False
    fixed = gtin_fix(ean)
    if not fixed or fixed == ean:
        return article, False
    article = article[:ean_m.start(1)] + fixed + article[ean_m.end(1):]
    return article, True


# ── Regel 7: DELIVERY_TIME Fallback ──────────────────────────────────────────

def rule_delivery_time(article: str) -> tuple[str, bool]:
    """
    Setzt DELIVERY_TIME=1 wenn der Wert fehlt.
    Artikel ohne Lieferzeit bekommen auf Plattformen den schlechtesten Slot.
    """
    if _DELIVERY_PAT.search(article):
        return article, False
    return _DETAILS_END.sub(
        "<DELIVERY_TIME>1</DELIVERY_TIME>\n\\1", article, count=1), True


RULES = [
    ("description_long",  rule_description_long),
    ("manufacturer_name", rule_manufacturer_name),
    ("manufacturer_normalize", rule_manufacturer_normalize),
    ("ean_keyword",       rule_ean_keyword),
    ("keyword_dedup",     rule_keyword_dedup),
    ("clean_desc_short",  rule_clean_desc_short),
    ("gtin_fix",          rule_gtin_fix),
    ("delivery_time",     rule_delivery_time),
]

RULE_VERBS = {
    "description_long":  "Langbeschreibung ergänzt",
    "manufacturer_name": "Hersteller ergänzt",
    "manufacturer_normalize": "Herstellername normalisiert",
    "ean_keyword":       "EAN als Keyword eingefügt",
    "keyword_dedup":     "Keyword-Duplikate bereinigt",
    "clean_desc_short":  "AID-Suffix aus Kurzbeschreibung entfernt",
    "gtin_fix":          "EAN-Prüfziffer korrigiert",
    "delivery_time":     "Lieferzeit auf 1 Tag gesetzt",
}


# ── Hauptfunktion ─────────────────────────────────────────────────────────────

def enrich(xml_path: str, progress_cb=None) -> dict:
    """
    Wendet alle Regeln in RULES auf xml_path an und schreibt die Datei zurück.
    Artikel die grundlegende Validierung nicht bestehen → Dead Letter Queue.
    """
    p = progress_cb or (lambda m, **kw: None)

    if not os.path.exists(xml_path):
        raise FileNotFoundError(f"Datei nicht gefunden: {xml_path}")

    name = os.path.basename(xml_path)
    p(f"Anreicherung: lese {name} …")
    content = Path(xml_path).read_text(encoding="utf-8", errors="replace")

    # DLQ einrichten
    try:
        import config as _cfg
        log_dir = _cfg.DIRS.get("logs", "logs")
    except Exception:
        log_dir = os.path.join(os.path.dirname(xml_path), "..", "logs")

    from lib.dead_letter import DeadLetterQueue, validate_article_basic
    supplier = os.path.splitext(name)[0]
    dlq = DeadLetterQueue(log_dir, supplier)

    total_arts   = 0
    changed_arts = 0
    quarantined  = 0
    by_rule      = {rule_name: 0 for rule_name, _ in RULES}

    def _process(m):
        nonlocal total_arts, changed_arts, quarantined
        article  = m.group(1)
        original = article
        total_arts += 1

        # Basis-Validierung → DLQ
        reason = validate_article_basic(article)
        if reason:
            dlq.reject(article, reason)
            quarantined += 1
            return ""   # aus XML entfernen

        for rule_name, rule_fn in RULES:
            article, changed = rule_fn(article)
            if changed:
                by_rule[rule_name] += 1

        if article != original:
            changed_arts += 1

        return article

    new_content = _ARTICLE_PAT.sub(_process, content)

    if new_content != content:
        Path(xml_path).write_text(new_content, encoding="utf-8")

    dlq.flush(progress_cb=p)

    p(f"  Artikel gesamt:       {total_arts:>6}")
    p(f"  Artikel geändert:     {changed_arts:>6}")
    if quarantined:
        p(f"  Artikel quarantäniert: {quarantined:>5}", tag="warn")
    for rule_name, count in by_rule.items():
        if count:
            verb = RULE_VERBS.get(rule_name, "geändert")
            p(f"  {rule_name}: {count} Artikel – {verb}", tag="ok")

    return {
        "articles_total":   total_arts,
        "articles_changed": changed_arts,
        "quarantined":      quarantined,
        "by_rule":          by_rule,
    }
