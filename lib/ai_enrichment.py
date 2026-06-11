# lib/ai_enrichment.py – KI-gestützte Artikeldaten-Verbesserung
#
# Nutzt die Anthropic API um schwache Artikeldaten zu verbessern.
# Wird nur auf Artikel angewendet die konkrete Lücken haben.
# Ergebnisse werden gecacht (logs/ai_cache.json) um API-Kosten zu minimieren.
#
# Konfiguration in config.py:
#
#   AI_ENRICHMENT = {
#       "enabled":        False,     # Gesamt-Schalter
#       "model":          "claude-haiku-4-5-20251001",  # günstigstes Modell
#       "max_articles":   200,       # max. Artikel pro Lauf
#       "min_desc_len":   20,        # DESCRIPTION_SHORT kürzer → Kandidat
#       "tasks": {
#           "improve_desc_short": True,   # Kurzbeschreibung verbessern
#           "improve_desc_long":  True,   # Langbeschreibung ergänzen
#           "normalize_mfr":      True,   # Herstellernamen normalisieren
#           "suggest_keywords":   False,  # Zusätzliche Keywords vorschlagen
#       }
#   }

import os
import re
import json
import logging
import shutil
from pathlib import Path
from datetime import datetime

log = logging.getLogger(__name__)

_CACHE_FILE    = "ai_cache.json"
_ARTICLE_PAT   = re.compile(r'<ARTICLE\b[^>]*>.*?</ARTICLE>', re.IGNORECASE | re.DOTALL)
_AID_PAT       = re.compile(r'<SUPPLIER_AID>(.*?)</SUPPLIER_AID>', re.IGNORECASE)
_DSH_PAT       = re.compile(r'<DESCRIPTION_SHORT>(.*?)</DESCRIPTION_SHORT>', re.IGNORECASE | re.DOTALL)
_DLG_PAT       = re.compile(r'<DESCRIPTION_LONG>(.*?)</DESCRIPTION_LONG>', re.IGNORECASE | re.DOTALL)
_MFR_PAT       = re.compile(r'<MANUFACTURER_NAME>(.*?)</MANUFACTURER_NAME>', re.IGNORECASE)
_KW_PAT        = re.compile(r'<KEYWORD>(.*?)</KEYWORD>', re.IGNORECASE)
_DETAILS_END   = re.compile(r'(</ARTICLE_DETAILS>)', re.IGNORECASE)


# ── Config laden ──────────────────────────────────────────────────────────────

def _get_cfg() -> dict:
    try:
        import config as _cfg
        return getattr(_cfg, "AI_ENRICHMENT", {})
    except Exception:
        return {}


# ── Cache ─────────────────────────────────────────────────────────────────────

def _load_cache(log_dir: str) -> dict:
    path = os.path.join(log_dir, _CACHE_FILE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_cache(log_dir: str, cache: dict):
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    path = os.path.join(log_dir, _CACHE_FILE)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


# ── Artikel analysieren: welche brauchen Hilfe? ───────────────────────────────

def _needs_improvement(article: str, cfg: dict) -> dict:
    """
    Prüft welche Felder eines Artikels verbessert werden sollen.
    Returns: {field: current_value} für Felder die Hilfe brauchen.
    """
    min_desc = cfg.get("min_desc_len", 20)
    tasks    = cfg.get("tasks", {})
    needs    = {}

    dsh_m = _DSH_PAT.search(article)
    dlg_m = _DLG_PAT.search(article)
    mfr_m = _MFR_PAT.search(article)

    dsh = dsh_m.group(1).strip() if dsh_m else ""
    dlg = dlg_m.group(1).strip() if dlg_m else ""
    mfr = mfr_m.group(1).strip() if mfr_m else ""

    if tasks.get("improve_desc_short") and len(dsh) < min_desc:
        needs["desc_short"] = dsh

    if tasks.get("improve_desc_long") and not dlg and dsh:
        needs["desc_long"] = dsh  # aus Kurzbeschreibung erzeugen

    if tasks.get("normalize_mfr") and mfr and len(mfr) > 30:
        needs["manufacturer"] = mfr  # zu langer Name → normalisieren

    return needs


# ── Anthropic API Aufruf ──────────────────────────────────────────────────────

def _call_api(prompt: str, model: str) -> str | None:
    """Ruft die Anthropic API auf. Gibt None bei Fehler zurück."""
    try:
        import anthropic
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=model,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
        return msg.content[0].text.strip()
    except Exception as e:
        log.warning("KI-API Fehler: %s", e)
        return None


def _build_prompt(aid: str, needs: dict, article: str, tasks: dict) -> str:
    """Baut einen kompakten Prompt für alle benötigten Verbesserungen."""
    # Kontext sammeln
    kws = _KW_PAT.findall(article)[:5]
    mfr_m = _MFR_PAT.search(article)
    mfr   = mfr_m.group(1).strip() if mfr_m else ""

    lines = [
        "Du verbesserst Produktdaten für einen deutschen B2B-Bürobedarf-Katalog.",
        "Antworte NUR mit einem JSON-Objekt, kein Fließtext.",
        "",
        f"Artikel: {aid}",
    ]

    if mfr:
        lines.append(f"Hersteller: {mfr}")
    if kws:
        lines.append(f"Keywords: {', '.join(kws)}")
    if needs.get("desc_short"):
        lines.append(f"Aktuelle Kurzbeschreibung: {needs['desc_short']}")

    lines.append("")
    lines.append("Aufgaben (gib nur die angeforderten Felder zurück):")

    if "desc_short" in needs and tasks.get("improve_desc_short"):
        lines.append('- "desc_short": Verbesserte Kurzbeschreibung (max. 80 Zeichen, Deutsch, kein AID-Code am Ende)')

    if "desc_long" in needs and tasks.get("improve_desc_long"):
        lines.append('- "desc_long": Sachliche Langbeschreibung (2-3 Sätze, Deutsch, aus Kurzbeschreibung + Keywords)')

    if "manufacturer" in needs and tasks.get("normalize_mfr"):
        lines.append(f'- "manufacturer": Normalisierter Herstellername (kurz, ohne GmbH/AG/Europe) für: {needs["manufacturer"]}')

    if tasks.get("suggest_keywords"):
        lines.append('- "keywords": Array mit 3-5 zusätzlichen deutschen Suchbegriffen')

    lines.append("")
    lines.append('Beispiel: {"desc_short": "...", "desc_long": "...", "manufacturer": "..."}')

    return "\n".join(lines)


# ── Artikel patchen ───────────────────────────────────────────────────────────

def _patch_article(article: str, improvements: dict) -> str:
    """Wendet KI-Verbesserungen auf einen Artikel-Block an."""
    from lib.utils import xml_escape

    if "desc_short" in improvements:
        val = xml_escape(improvements["desc_short"])
        article = _DSH_PAT.sub(
            lambda m: m.group().replace(m.group(1), val), article, count=1)

    if "desc_long" in improvements:
        val = xml_escape(improvements["desc_long"])
        if _DLG_PAT.search(article):
            article = _DLG_PAT.sub(
                lambda m: m.group().replace(m.group(1), val), article, count=1)
        else:
            article = _DETAILS_END.sub(
                f"<DESCRIPTION_LONG>{val}</DESCRIPTION_LONG>\n\\1",
                article, count=1)

    if "manufacturer" in improvements:
        val = xml_escape(improvements["manufacturer"])
        if _MFR_PAT.search(article):
            article = _MFR_PAT.sub(
                lambda m: m.group().replace(m.group(1), val), article, count=1)

    if "keywords" in improvements and isinstance(improvements["keywords"], list):
        existing = {k.lower() for k in _KW_PAT.findall(article)}
        kw_tags  = "\n".join(
            f"        <KEYWORD>{xml_escape(k)}</KEYWORD>"
            for k in improvements["keywords"]
            if k.lower() not in existing
        )
        if kw_tags:
            article = _DETAILS_END.sub(
                f"{kw_tags}\n\\1", article, count=1)

    return article


# ── Haupt-Funktion ────────────────────────────────────────────────────────────

def run_ai_enrichment(xml_path: str, progress_cb=None) -> dict:
    """
    KI-gestützte Artikeldaten-Verbesserung.

    Workflow:
    1. Artikel mit Lücken identifizieren
    2. Cache prüfen (bereits verarbeitete überspringen)
    3. Anthropic API aufrufen (Haiku, kompakter Prompt)
    4. Ergebnis in XML einpflegen + Cache speichern
    """
    p = progress_cb or (lambda m, **kw: None)
    cfg = _get_cfg()

    if not cfg.get("enabled", False):
        p("KI-Anreicherung: deaktiviert (AI_ENRICHMENT['enabled'] = False).", tag="dim")
        return {}

    if not os.path.exists(xml_path):
        p(f"KI-Anreicherung: Datei nicht gefunden: {xml_path}", tag="warn")
        return {}

    model       = cfg.get("model", "claude-haiku-4-5-20251001")
    max_art     = cfg.get("max_articles", 200)
    tasks       = cfg.get("tasks", {})

    try:
        import config as _cfg
        log_dir = _cfg.DIRS.get("logs", "logs")
    except Exception:
        log_dir = "logs"

    cache = _load_cache(log_dir)
    p(f"KI-Anreicherung: {os.path.basename(xml_path)}, max. {max_art} Artikel, "
      f"Modell: {model}")

    # XML lesen
    with open(xml_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    articles   = list(_ARTICLE_PAT.finditer(content))
    candidates = []
    for m in articles:
        article = m.group()
        aid_m   = _AID_PAT.search(article)
        if not aid_m:
            continue
        aid  = aid_m.group(1).strip()
        needs = _needs_improvement(article, cfg)
        if needs and aid not in cache:
            candidates.append((aid, m.start(), m.end(), article, needs))

    p(f"  {len(articles)} Artikel gesamt, {len(candidates)} Kandidaten, "
      f"{len(candidates) - len(cache)} noch nicht gecacht")

    to_process = candidates[:max_art]
    stats = {"processed": 0, "improved": 0, "cached": 0, "errors": 0}

    # Sortiert von hinten nach vorne verarbeiten (Positionen bleiben gültig)
    for aid, start, end, article, needs in reversed(to_process):
        prompt = _build_prompt(aid, needs, article, tasks)
        response = _call_api(prompt, model)

        if not response:
            stats["errors"] += 1
            cache[aid] = {"error": True, "ts": datetime.now().isoformat()}
            continue

        # JSON parsen
        try:
            # Manche Modelle umwickeln JSON in ```json ... ```
            clean = re.sub(r'```(?:json)?\s*|\s*```', '', response).strip()
            improvements = json.loads(clean)
        except (json.JSONDecodeError, ValueError):
            stats["errors"] += 1
            cache[aid] = {"error": True, "ts": datetime.now().isoformat()}
            continue

        stats["processed"] += 1
        if any(improvements.values()):
            patched = _patch_article(article, improvements)
            content = content[:start] + patched + content[end:]
            stats["improved"] += 1

        cache[aid] = {"improvements": improvements, "ts": datetime.now().isoformat()}
        p(f"  KI: {aid} → {list(improvements.keys())}", tag="dim")

    # Zurückschreiben
    with open(xml_path, "w", encoding="utf-8") as f:
        f.write(content)

    _save_cache(log_dir, cache)

    p(f"KI-Anreicherung: {stats['processed']} verarbeitet, "
      f"{stats['improved']} verbessert, "
      f"{stats['errors']} Fehler.", tag="ok")

    return stats


def run_ai_enrichment_task(progress_cb=None, file_progress_cb=None):
    """Task-Einstiegspunkt: KI-Anreicherung für alle konfigurierten XMLs."""
    p = progress_cb or (lambda m, **kw: None)
    try:
        import config as _cfg
        in_bme = _cfg.DIRS["in_bme"]
        merge_cfg = getattr(_cfg, "MERGE", {})
        target = os.path.join(in_bme, merge_cfg.get("out_file", "bueroring_merged.xml"))
        if os.path.exists(target):
            run_ai_enrichment(target, progress_cb=p)
        else:
            p(f"KI-Anreicherung: {os.path.basename(target)} nicht gefunden. "
              f"Bitte erst Büroring-Merge ausführen.", tag="warn")
    except Exception as e:
        p(f"KI-Anreicherung Fehler: {e}", tag="warn")
