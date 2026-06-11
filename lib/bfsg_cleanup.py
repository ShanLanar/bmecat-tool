# lib/bfsg_cleanup.py – Barrierefreiheits-Bereinigung (BFSG/EU Accessibility Act)
#
# Optional — aktivierbar per config.py:
#
#   BFSG = {
#       "enabled":            False,   # Gesamt-Schalter
#       "alt_text":           True,    # MIME_ALT aus DESCRIPTION_SHORT befüllen
#       "clean_desc_short":   True,    # AID-Suffix aus DESCRIPTION_SHORT entfernen
#       "remove_html":        True,    # HTML-Tags aus DESCRIPTION_LONG entfernen
#       "foreign_keywords":   True,    # Fremdsprachige Keywords entfernen
#   }
#
# Läuft als Anreicherungsschritt nach allen anderen Transforms.
# Betrifft die gesamte Output-XML — für alle Lieferanten.

import re
import os
import shutil
import logging

log = logging.getLogger(__name__)

# ── Patterns ──────────────────────────────────────────────────────────────────

_AID_SUFFIX   = re.compile(r'\s*\([A-Z0-9\-]{4,30}\)\s*$')      # "(CASFX87DEX)" am Ende
_HTML_TAG     = re.compile(r'<[^>]+>')                             # HTML-Tags
_MIME_SRC_PAT = re.compile(r'(<MIME_SOURCE>)(.*?)(</MIME_SOURCE>)', re.IGNORECASE)
_MIME_ALT_PAT = re.compile(r'<MIME_ALT>.*?</MIME_ALT>',           re.IGNORECASE)
_DESC_SH_PAT  = re.compile(r'(<DESCRIPTION_SHORT>)(.*?)(</DESCRIPTION_SHORT>)',
                            re.IGNORECASE | re.DOTALL)
_DESC_LG_PAT  = re.compile(r'(<DESCRIPTION_LONG>)(.*?)(</DESCRIPTION_LONG>)',
                            re.IGNORECASE | re.DOTALL)
_KW_PAT       = re.compile(r'<KEYWORD>(.*?)</KEYWORD>', re.IGNORECASE)
_MIME_INFO_PAT = re.compile(r'(<MIME>)(.*?)(</MIME>)', re.IGNORECASE | re.DOTALL)
_ARTICLE_PAT  = re.compile(r'<ARTICLE\b[^>]*>.*?</ARTICLE>', re.IGNORECASE | re.DOTALL)

# Bekannte fremdsprachige Wörter (erweiterbar)
_FOREIGN_STOPWORDS = frozenset({
    # Niederländisch
    "zwart", "wit", "rood", "blauw", "groen", "geel", "grijs",
    "groot", "klein", "nieuw", "oud",
    # Englisch (in deutschen Katalogen oft falsch)
    # Absichtlich eng gehalten: nur eindeutig fremdsprachige, nicht Marken
})


# ── Einzel-Transformationen ───────────────────────────────────────────────────

def _clean_desc_short(text: str) -> str:
    """Entfernt AID-Suffix wie '(CASFX87DEX)' am Ende der Kurzbeschreibung."""
    return _AID_SUFFIX.sub("", text).strip()


def _remove_html(text: str) -> str:
    """Entfernt HTML-Tags aus Text, dekodiert Entities."""
    import html
    text = html.unescape(text)
    text = _HTML_TAG.sub(" ", text)
    return " ".join(text.split())


def _is_foreign_keyword(kw: str) -> bool:
    """Prüft ob ein Keyword eindeutig fremdsprachig ist."""
    kw_lower = kw.lower().strip()

    # Bekannte Stopwords
    if kw_lower in _FOREIGN_STOPWORDS:
        return True

    # Rein nummerisch oder zu kurz → behalten
    if len(kw_lower) < 4 or kw_lower.isdigit():
        return False

    # Sieht aus wie eine AID/EAN → behalten
    if re.match(r'^[A-Z0-9\-]{3,}$', kw.strip()):
        return False

    # langdetect als Fallback (nur wenn Paket installiert)
    try:
        import langdetect
        lang = langdetect.detect(kw_lower)
        return lang not in ("de", "en", "und")
    except Exception:
        return False


def _add_mime_alt(mime_block: str, desc_short: str) -> str:
    """Fügt MIME_ALT aus DESCRIPTION_SHORT in einen MIME-Block ein."""
    if _MIME_ALT_PAT.search(mime_block):
        return mime_block  # bereits vorhanden

    alt_text = _clean_desc_short(desc_short)[:100]  # max 100 Zeichen
    if not alt_text:
        return mime_block

    from lib.utils import xml_escape
    alt_tag = f"<MIME_ALT>{xml_escape(alt_text)}</MIME_ALT>"

    # Nach MIME_SOURCE einfügen
    return _MIME_SRC_PAT.sub(
        lambda m: m.group(1) + m.group(2) + m.group(3) + "\n" + alt_tag,
        mime_block, count=1)


# ── Artikel-Transformation ────────────────────────────────────────────────────

def transform_article_bfsg(article: str, cfg: dict) -> tuple[str, dict]:
    """
    Wendet alle aktivierten BFSG-Transforms auf einen <ARTICLE>-Block an.

    Returns:
        (transformed, stats_dict)
    """
    stats = {"alt_text": 0, "desc_short": 0, "html": 0, "keywords": 0}

    # 1. MIME_ALT aus DESCRIPTION_SHORT
    if cfg.get("alt_text"):
        desc_sh_m = _DESC_SH_PAT.search(article)
        desc_short = desc_sh_m.group(2).strip() if desc_sh_m else ""

        if desc_short:
            def _patch_mime(m):
                patched = _add_mime_alt(m.group(), desc_short)
                if patched != m.group():
                    stats["alt_text"] += 1
                return patched
            article = _MIME_INFO_PAT.sub(_patch_mime, article)

    # 2. AID-Suffix aus DESCRIPTION_SHORT
    if cfg.get("clean_desc_short"):
        def _clean_ds(m):
            cleaned = _clean_desc_short(m.group(2))
            if cleaned != m.group(2):
                stats["desc_short"] += 1
                return m.group(1) + cleaned + m.group(3)
            return m.group()
        article = _DESC_SH_PAT.sub(_clean_ds, article, count=1)

    # 3. HTML aus DESCRIPTION_LONG
    if cfg.get("remove_html"):
        def _clean_dl(m):
            cleaned = _remove_html(m.group(2))
            if cleaned != m.group(2).strip():
                stats["html"] += 1
                from lib.utils import xml_escape
                return m.group(1) + xml_escape(cleaned) + m.group(3)
            return m.group()
        article = _DESC_LG_PAT.sub(_clean_dl, article, count=1)

    # 4. Fremdsprachige Keywords
    if cfg.get("foreign_keywords"):
        kws_before = _KW_PAT.findall(article)
        kept = set()
        foreign = []
        for kw in kws_before:
            if _is_foreign_keyword(kw):
                foreign.append(kw)
            else:
                kept.add(kw)

        if foreign:
            stats["keywords"] += len(foreign)
            for kw in foreign:
                article = article.replace(
                    f"<KEYWORD>{kw}</KEYWORD>", "", 1)

    return article, stats


# ── Haupt-Funktion ────────────────────────────────────────────────────────────

def run_bfsg_cleanup(xml_path: str, progress_cb=None) -> dict:
    """
    Führt BFSG-Barrierefreiheits-Bereinigung auf einer BMEcat-XML durch.
    Wird nur ausgeführt wenn BFSG["enabled"] = True in config.py.

    Gibt Statistiken zurück (oder {} wenn deaktiviert/Fehler).
    """
    p = progress_cb or (lambda m, **kw: None)

    # Config laden
    try:
        import config as _cfg
        bfsg_cfg = getattr(_cfg, "BFSG", {})
    except Exception:
        bfsg_cfg = {}

    if not bfsg_cfg.get("enabled", False):
        p("BFSG-Cleanup: deaktiviert (BFSG['enabled'] = False in config.py)", tag="dim")
        return {}

    if not os.path.exists(xml_path):
        p(f"BFSG-Cleanup: Datei nicht gefunden: {xml_path}", tag="warn")
        return {}

    active = [k for k, v in bfsg_cfg.items() if k != "enabled" and v]
    p(f"BFSG-Cleanup: {os.path.basename(xml_path)} "
      f"[{', '.join(active)}] ...")

    tmp_path = xml_path + ".bfsg_tmp"
    total_stats = {"alt_text": 0, "desc_short": 0, "html": 0,
                   "keywords": 0, "articles": 0}

    from lib.utils import iter_articles

    # Header (vor erstem Artikel)
    header_buf = []
    with open(xml_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if re.search(r"<ARTICLE[\s>]", line, re.IGNORECASE):
                break
            header_buf.append(line)

    # Footer (nach letztem Artikel)
    with open(xml_path, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()
    last = raw.rfind("</ARTICLE>")
    footer = raw[last + len("</ARTICLE>"):] if last >= 0 else ""

    with open(tmp_path, "w", encoding="utf-8") as writer:
        writer.write("".join(header_buf))
        for article in iter_articles(xml_path):
            transformed, stats = transform_article_bfsg(article, bfsg_cfg)
            writer.write(transformed)
            total_stats["articles"] += 1
            for k, v in stats.items():
                total_stats[k] += v
        writer.write(footer)

    shutil.move(tmp_path, xml_path)

    p(f"BFSG-Cleanup: {total_stats['articles']} Artikel bereinigt — "
      f"{total_stats['alt_text']} MIME_ALT ergänzt, "
      f"{total_stats['desc_short']} Titel bereinigt, "
      f"{total_stats['html']} HTML-Beschreibungen, "
      f"{total_stats['keywords']} Fremdwort-Keywords entfernt.", tag="ok")

    return total_stats
