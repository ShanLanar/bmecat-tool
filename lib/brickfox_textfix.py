# lib/brickfox_textfix.py – Text-Regeln für die Brickfox-Kopie der Merge-XML
#
# Marktplatz-Anforderungen (Netto), die NUR die an Brickfox gelieferte XML
# betreffen – Datenbank, Viewer und VENDOSYS-Export (Allago/OfficeXL) bleiben
# unverändert. Wird bei jedem Merge-Lauf auf die frisch erzeugte
# bueroring_merged.xml angewendet und als bueroring_merged_brickfox.xml
# geschrieben; diese Kopie geht als bueroring.xml nach Brickfox.
#
# Regeln (config.BRICKFOX_TEXT_RULES):
#   beschreibung_absaetze   DESCRIPTION_LONG durch das Feature
#                           "Langbeschreibung (Online)" ersetzen, wenn dieses
#                           Absätze (Leerzeilen) enthält – gleicher Text, aber
#                           gegliedert. Büroring liefert DESCRIPTION_LONG als
#                           reinen Fließtext.
#   satzzeichen_leerzeichen Fehlendes Leerzeichen nach Satzende ergänzen
#                           ("Vögel.Der 70 mm" → "Vögel. Der 70 mm").
#   titel_menge             Inhaltsmenge aus dem Feature "Inhalt" an den Titel
#                           (DESCRIPTION_SHORT) anhängen, wenn Menge ≠ 1 und die
#                           Zahl im Titel noch nicht vorkommt
#                           ("…, Hebelmechanik" → "…, Hebelmechanik, 10 Stück").
#                           Alle Titeländerungen → logs/brickfox_titel_menge_*.csv
#
# Textverarbeitung per Regex auf dem Roh-XML (wie lib/article_enrichment.py);
# Inhalte sind in der Merge-XML bereits XML-escaped und werden 1:1 übernommen.

import csv
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Callable

_ARTICLE_PAT    = re.compile(r'(?is)(<article[\s>].*?</article>)')
_AID_PAT        = re.compile(r'(?is)<supplier_aid>(.*?)</supplier_aid>')
_DESC_LONG_PAT  = re.compile(r'(?is)(<description_long>)(.*?)(</description_long>)')
_DESC_SHORT_PAT = re.compile(r'(?is)(<description_short>)(.*?)(</description_short>)')
_FEAT_PAT       = re.compile(r'(?is)<feature>(.*?)</feature>')
_FNAME_PAT      = re.compile(r'(?is)<fname>(.*?)</fname>')
_FVALUE_PAT     = re.compile(r'(?is)<fvalue>(.*?)</fvalue>')

# Satzende direkt gefolgt von Großbuchstabe + Kleinbuchstabe, davor ein Wort
# aus ≥3 Kleinbuchstaben (schließt Abkürzungen wie "z.B.", "Nr.5", "Co.KG" aus)
_GLUED_PAT = re.compile(r'(?<=[a-zäöüß]{3}[.!?])(?=[A-ZÄÖÜ][a-zäöüß])')

# "10 Stück", "1.000 Stück", "100 Blatt", "2,5 kg"
_INHALT_PAT = re.compile(r'^\s*(\d{1,3}(?:\.\d{3})*|\d+)(?:[.,](\d+))?\s*(.*?)\s*$')

_LANG_FEATURE_NAMES = ("langbeschreibung (online)", "langbeschreibung")

# Titel enthält bereits eine Mengenangabe ("100 Blatt", "10er Pack", "2 Rollen") →
# nicht noch eine zweite anhängen ("…, 100 Blatt, 300 Stück" wäre irreführend)
_TITLE_QTY_PAT = re.compile(
    r"(?i)\b\d[\d.]*\s*(?:er[- ]?)?(?:x\s*\d+\s*)?"
    r"(?:Stück|Stk\.?|St\.|Blatt|Bl\.|Rollen?|Pack(?:ung(?:en)?)?|Pck\.?|Beutel|Sets?|"
    r"Flaschen?|Paar|Kartons?|Dosen?|Tuben?|Bogen|Bögen|Stifte?|Teile|tlg\.?|teilig|"
    r"Liter|ml|kg|g\b|m\b|Meter|Blister)")


def _rules() -> dict:
    default = {"beschreibung_absaetze": True, "satzzeichen_leerzeichen": True, "titel_menge": True}
    try:
        import config as _cfg
        cfg = getattr(_cfg, "BRICKFOX_TEXT_RULES", None)
        if isinstance(cfg, dict):
            default.update({k: bool(v) for k, v in cfg.items()})
    except Exception:
        pass
    return default


def _features(article: str) -> dict:
    out = {}
    for fm in _FEAT_PAT.finditer(article):
        body = fm.group(1)
        n = _FNAME_PAT.search(body)
        v = _FVALUE_PAT.search(body)
        if n:
            name = n.group(1).strip()
            if name and name not in out:
                out[name] = v.group(1) if v else ""
    return out


def fix_glued_sentences(text: str) -> str:
    return _GLUED_PAT.sub(" ", text)


def _norm_paragraphs(text: str) -> str:
    """Zeilenenden vereinheitlichen; Absätze (Leerzeile) bleiben erhalten."""
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip("\n")


def _digits(s: str) -> str:
    return re.sub(r"[^\d]", "", s)


def title_with_inhalt(title: str, inhalt: str) -> str | None:
    """
    Gibt den ergänzten Titel zurück oder None, wenn nichts zu tun ist
    (Menge 1, kein numerischer Inhalt, Zahl schon im Titel, Titel enthält
    bereits eine andere Mengenangabe wie "100 Blatt").
    """
    m = _INHALT_PAT.match(inhalt or "")
    if not m:
        return None
    whole, frac, unit = m.group(1), m.group(2), (m.group(3) or "").strip()
    digits = _digits(whole)
    if not digits or int(digits) <= 1 and not frac:
        return None
    if not unit:
        return None
    # Zahl schon im Titel? (1000 / 1.000 / 1000er / 1000-er / 10x / 10 x)
    title_digits_tokens = {_digits(t) for t in re.findall(r"\d[\d.]*", title)}
    if digits in title_digits_tokens:
        return None
    if _TITLE_QTY_PAT.search(title):
        return None
    amount = whole if not frac else f"{whole},{frac}"
    suffix = f"{amount} {unit}"
    t = title.rstrip()
    sep = "" if t.endswith((",", ";")) else ","
    return f"{t}{sep} {suffix}"


def apply_text_rules(src_xml: str, dst_xml: str, logs_dir: str = None,
                     progress_cb: Callable = None) -> dict:
    """Erzeugt aus src_xml die Brickfox-Kopie dst_xml mit den Text-Regeln."""
    p = progress_cb or (lambda m, **kw: None)
    rules = _rules()
    if not any(rules.values()):
        p("Brickfox-Textregeln: alle deaktiviert – Kopie unverändert.", tag="dim")

    content = Path(src_xml).read_text(encoding="utf-8", errors="replace")
    stats = {"articles": 0, "desc_absaetze": 0, "desc_leerzeichen": 0,
             "titel_menge": 0, "titel_report": ""}
    title_rows = []

    def _patch(m: re.Match) -> str:
        art = m.group(1)
        stats["articles"] += 1
        feats = None
        aid_m = _AID_PAT.search(art)
        aid = aid_m.group(1).strip() if aid_m else ""

        # ── Beschreibung ─────────────────────────────────────────────────
        dl = _DESC_LONG_PAT.search(art)
        if dl and (rules["beschreibung_absaetze"] or rules["satzzeichen_leerzeichen"]):
            old = dl.group(2)
            new = old
            replaced = False
            if rules["beschreibung_absaetze"]:
                feats = _features(art)
                for name, val in feats.items():
                    if name.lower() in _LANG_FEATURE_NAMES and "\n\n" in val.replace("\r\n", "\n"):
                        new = _norm_paragraphs(val)
                        replaced = True
                        break
            if rules["satzzeichen_leerzeichen"]:
                fixed = fix_glued_sentences(new)
                if fixed != new:
                    new = fixed
                    if not replaced:
                        stats["desc_leerzeichen"] += 1
            if replaced:
                stats["desc_absaetze"] += 1
            if new != old:
                art = art[:dl.start(2)] + new + art[dl.end(2):]

        # ── Titel ────────────────────────────────────────────────────────
        if rules["titel_menge"]:
            ds = _DESC_SHORT_PAT.search(art)
            if ds:
                if feats is None:
                    feats = _features(art)
                inhalt = feats.get("Inhalt", "")
                if inhalt:
                    new_title = title_with_inhalt(ds.group(2), inhalt)
                    if new_title:
                        title_rows.append((aid, ds.group(2), new_title, inhalt))
                        stats["titel_menge"] += 1
                        art = art[:ds.start(2)] + new_title + art[ds.end(2):]
        return art

    new_content = _ARTICLE_PAT.sub(_patch, content)

    tmp = dst_xml + ".tmp"
    Path(tmp).write_text(new_content, encoding="utf-8")
    os.replace(tmp, dst_xml)

    if title_rows and logs_dir:
        os.makedirs(logs_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(logs_dir, f"brickfox_titel_menge_{ts}.csv")
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["supplier_aid", "titel_alt", "titel_neu", "inhalt"])
            w.writerows(title_rows)
        stats["titel_report"] = path

    p(f"Brickfox-Textregeln: {stats['articles']} Artikel → {os.path.basename(dst_xml)}: "
      f"{stats['desc_absaetze']} Beschreibungen mit Absätzen aus 'Langbeschreibung (Online)', "
      f"{stats['desc_leerzeichen']} Satzzeichen-Leerzeichen ergänzt, "
      f"{stats['titel_menge']} Titel um Inhaltsmenge ergänzt"
      + (f" → {os.path.basename(stats['titel_report'])}" if stats["titel_report"] else ""),
      tag="ok")
    return stats
