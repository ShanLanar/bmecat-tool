# lib/dimension_normalize.py – Maße/Gewicht vereinheitlichen
#
# Lieferanten liefern Maße unterschiedlich: Büroring "165 mm" bzw. FUNIT,
# Nordwest im udf_NDW-Block als "140,000" OHNE FUNIT, die Einheit steht in
# eigenen Features "Maßeinheit" (MM/CM/M) und "Gewichtseinheit" (G/KG);
# fehlende Werte stehen als "0,000". Shops und Brickfox übernehmen nur den
# Zahlenwert – ohne Bereinigung landet dort "140,000" ohne Einheit oder 0.
#
# Regeln (gelten für alle Lieferanten, greifen nur wo nötig):
#   1. Maß-Features (config.FEATURE_TARGET_UNITS: Länge, Breite, Höhe, Tiefe,
#      Durchmesser, Gewicht) ohne FUNIT bekommen die Einheit aus dem
#      Träger-Feature des Artikels (config.DIMENSION_UNIT_CARRIERS), sonst
#      die Standard-Einheit (config.DIMENSION_DEFAULT_UNITS, z.B. mm).
#   2. Wert bereinigen und auf die Zieleinheit umrechnen
#      (lib.db_postprocess.normalize_feature_value: "140,000" → 140 mm,
#      "355" + G → 0.355 kg).
#   3. Numerischer Wert 0 → Feature entfernen (= Wert fehlt; zählt in der
#      Lückenauswertung dann korrekt als Lücke).
#   4. Träger-Features (Maßeinheit, Gewichtseinheit) werden entfernt, sobald
#      sie verarbeitet sind.
#   Nicht-numerische Werte ("932 - 1608", "4 x 4", "max. 420") bleiben
#   unverändert.
#
# Anwendung: DB-Import (alle Lieferanten), Task "Zusatz-Features & Marken in
# DB einspielen" (vorhandene Artikel), VENDOSYS-Export (Sicherheitsnetz) und
# als XML-Stufe im Nordwest-Task vor dem Brickfox-Upload (normalize_xml).

import os
import re
from typing import Callable

from lib.db_postprocess import normalize_feature_value, _target_units

_DEFAULT_CARRIERS = {
    "maßeinheit":     ("länge", "breite", "höhe", "tiefe", "durchmesser"),
    "masseinheit":    ("länge", "breite", "höhe", "tiefe", "durchmesser"),
    "gewichtseinheit": ("gewicht",),
}
_DEFAULT_UNITS = {"länge": "mm", "breite": "mm", "höhe": "mm", "tiefe": "mm",
                  "durchmesser": "mm"}

_NUM_PAT = re.compile(r"^\s*([-+]?\d+(?:[.,]\d+)?)\s*([A-Za-zµ]*)\s*$")


def _carriers() -> dict:
    try:
        import config as _cfg
        cfg = getattr(_cfg, "DIMENSION_UNIT_CARRIERS", None)
        if cfg:
            return {str(k).strip().lower(): tuple(str(x).strip().lower() for x in v)
                    for k, v in cfg.items()}
    except Exception:
        pass
    return dict(_DEFAULT_CARRIERS)


def _default_units() -> dict:
    try:
        import config as _cfg
        cfg = getattr(_cfg, "DIMENSION_DEFAULT_UNITS", None)
        if cfg is not None:
            return {str(k).strip().lower(): str(v).strip().lower() for k, v in cfg.items()}
    except Exception:
        pass
    return dict(_DEFAULT_UNITS)


def _plan(feats: list) -> tuple:
    """
    feats: [(fname, fvalue, funit), ...] in Reihenfolge.
    Returns (changes, drop_idx, stats):
      changes  {idx: (fvalue_neu, funit_neu)}
      drop_idx {idx, ...}   (Nullwerte + verarbeitete Träger)
    """
    targets = _target_units()
    carriers = _carriers()
    defaults = _default_units()
    stats = {"unit_from_carrier": 0, "unit_default": 0, "normalized": 0,
             "zero_dropped": 0, "carriers_dropped": 0}

    unit_for: dict = {}      # dim_lower → Einheit aus Träger
    carrier_idx = []
    for i, (fn, fv, fu) in enumerate(feats):
        key = (fn or "").strip().lower()
        if key in carriers and (fv or "").strip():
            for dim in carriers[key]:
                unit_for.setdefault(dim, fv.strip().lower())
            carrier_idx.append(i)

    changes, drop = {}, set()
    has_dim = False
    for i, (fn, fv, fu) in enumerate(feats):
        key = (fn or "").strip().lower()
        if key not in targets:
            continue
        has_dim = True
        fv = (fv or "").strip()
        fu = (fu or "").strip()
        m = _NUM_PAT.match(fv)
        if not m:
            continue                       # "932 - 1608", "4 x 4": unangetastet
        unit_in_value = m.group(2)
        unit = (fu or unit_in_value).lower()
        if not unit:
            if key in unit_for:
                unit = unit_for[key]
                stats["unit_from_carrier"] += 1
            elif key in defaults:
                unit = defaults[key]
                stats["unit_default"] += 1
        try:
            if float(m.group(1).replace(",", ".")) == 0:
                drop.add(i)
                stats["zero_dropped"] += 1
                continue
        except ValueError:
            continue
        if unit:
            nv, nu = normalize_feature_value(fn, m.group(1), unit)
        else:
            nv, nu = normalize_feature_value(fn, m.group(1), "")[0], ""
        if (nv, nu) != (fv, fu):
            changes[i] = (nv, nu)
            stats["normalized"] += 1
    if carrier_idx and has_dim:
        for i in carrier_idx:
            drop.add(i)
        stats["carriers_dropped"] += len(carrier_idx)
    return changes, drop, stats


def normalize_dimension_features(features: list) -> tuple:
    """Feature-Dicts (DB-Format) bereinigen. Returns (neue_liste, stats)."""
    if not features:
        return features, {}
    feats = [(f.get("fname", ""), f.get("fvalue", ""), f.get("funit", "")) for f in features]
    changes, drop, stats = _plan(feats)
    if not changes and not drop:
        return features, stats
    out = []
    for i, f in enumerate(features):
        if i in drop:
            continue
        if i in changes:
            f = dict(f)
            f["fvalue"], f["funit"] = changes[i]
        out.append(f)
    return out, stats


# ── XML-Stufe (Nordwest-XMLs vor dem Brickfox-Upload) ────────────────────────

_FEATURE_PAT = re.compile(r"<FEATURE\b[^>]*>.*?</FEATURE>\s*", re.IGNORECASE | re.DOTALL)
_FNAME_PAT   = re.compile(r"<FNAME>(.*?)</FNAME>", re.IGNORECASE | re.DOTALL)
_FVALUE_PAT  = re.compile(r"(<FVALUE>)(.*?)(</FVALUE>)", re.IGNORECASE | re.DOTALL)
_FUNIT_PAT   = re.compile(r"(<FUNIT>)(.*?)(</FUNIT>)", re.IGNORECASE | re.DOTALL)


def _xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _unescape(s: str) -> str:
    import html
    return html.unescape(s).strip()


def normalize_article_xml(article: str, stats: dict = None) -> str:
    """Einen <ARTICLE>-Block (Text) bereinigen."""
    blocks = list(_FEATURE_PAT.finditer(article))
    if not blocks:
        return article
    feats = []
    for b in blocks:
        s = b.group()
        fn = _FNAME_PAT.search(s)
        fv = _FVALUE_PAT.search(s)
        fu = _FUNIT_PAT.search(s)
        feats.append((_unescape(fn.group(1)) if fn else "",
                      _unescape(fv.group(2)) if fv else "",
                      _unescape(fu.group(2)) if fu else ""))
    changes, drop, st = _plan(feats)
    if stats is not None:
        for k, v in st.items():
            stats[k] = stats.get(k, 0) + v
    if not changes and not drop:
        return article
    out, pos = [], 0
    for i, b in enumerate(blocks):
        out.append(article[pos:b.start()])
        pos = b.end()
        if i in drop:
            continue
        s = b.group()
        if i in changes:
            nv, nu = changes[i]
            s = _FVALUE_PAT.sub(lambda m: m.group(1) + _xml_escape(nv) + m.group(3), s, count=1)
            if nu:
                if _FUNIT_PAT.search(s):
                    s = _FUNIT_PAT.sub(lambda m: m.group(1) + _xml_escape(nu) + m.group(3), s, count=1)
                else:
                    # FUNIT direkt nach FVALUE einfügen, Einrückung der FVALUE-Zeile übernehmen
                    s = re.sub(r"(?is)([ \t]*)(<FVALUE>.*?</FVALUE>)",
                               lambda m: f"{m.group(1)}{m.group(2)}\n{m.group(1)}<FUNIT>{_xml_escape(nu)}</FUNIT>",
                               s, count=1)
        out.append(s)
    out.append(article[pos:])
    return "".join(out)


def normalize_xml(xml_path: str, progress_cb: Callable = None) -> dict:
    """Maße/Gewicht in einer BMEcat-XML bereinigen (artikelweise, streaming)."""
    p = progress_cb or (lambda m, **kw: None)
    if not os.path.exists(xml_path):
        p(f"Maße-Normalisierung: Datei nicht gefunden: {xml_path}", tag="warn")
        return {}
    name = os.path.basename(xml_path)
    tmp = xml_path + ".dim_tmp"
    stats = {"articles": 0}
    art_open = re.compile(r"<ARTICLE[\s>]", re.IGNORECASE)
    art_close = re.compile(r"</ARTICLE>", re.IGNORECASE)
    # Robust auch bei "</ARTICLE><ARTICLE mode=...>" auf einer Zeile (Nordwest)
    # und minimierten XMLs: Zeile stückweise abarbeiten.
    buf, in_art = [], False
    with open(xml_path, "r", encoding="utf-8", errors="replace") as src, \
         open(tmp, "w", encoding="utf-8") as dst:
        for line in src:
            rest = line
            while rest:
                if not in_art:
                    m = art_open.search(rest)
                    if not m:
                        dst.write(rest)
                        break
                    dst.write(rest[:m.start()])
                    rest = rest[m.start():]
                    in_art, buf = True, []
                cm = art_close.search(rest)
                if not cm:
                    buf.append(rest)
                    break
                buf.append(rest[:cm.end()])
                stats["articles"] += 1
                dst.write(normalize_article_xml("".join(buf), stats))
                buf, in_art = [], False
                rest = rest[cm.end():]
        if buf:
            dst.write("".join(buf))
    os.replace(tmp, xml_path)
    p(f"Maße-Normalisierung {name}: {stats['articles']} Artikel – "
      f"{stats.get('unit_from_carrier', 0)} Einheiten aus Maßeinheit/Gewichtseinheit, "
      f"{stats.get('unit_default', 0)} Standard-Einheit, {stats.get('normalized', 0)} Werte umgerechnet, "
      f"{stats.get('zero_dropped', 0)} Nullwerte entfernt, {stats.get('carriers_dropped', 0)} Träger-Features entfernt",
      tag="ok")
    return stats
