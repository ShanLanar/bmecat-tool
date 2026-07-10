# lib/db_postprocess.py – Post-Processing vor dem VENDOSYS-Export
#
# Regeln werden aus CSV-Dateien im BASE_DIR geladen (alle optional).
#
# Dateien:
#   postprocess_blacklist.csv      – product_id/supplier_pid (Wildcards: *GRATIS*)
#   postprocess_fname_blacklist.csv– FNAME-Werte die nicht exportiert werden (Wildcards: *Marke*)
#   postprocess_prices.csv         – Preisformeln pro Lieferant/Artikelmuster
#   postprocess_price_types.csv    – Preis-Typ-Konvertierung (net_list→nrp etc.)
#   postprocess_suffixes.csv       – AID-Suffix pro Lieferant
#   postprocess_categories.csv     – Kategoriemapping pro Artikel
#   postprocess_crosssell.csv      – Crossselling-Links
#   postprocess_media.csv          – Medien-Overrides pro Artikel (add/replace/remove)
#   postprocess_media_global.csv   – Globale MIME-Regeln per Pattern
#   postprocess_reference_types.csv– Referenztyp-Remapping
#   fusage_3_features.csv          – Feature-Namen mit FUSAGE=3 (alle anderen: 1)
#   supplier_priority.csv          – EAN-Konfliktauflösung (Zahl = Priorität)
#   postprocess_hook.py            – Optionaler Python-Hook

import ast
import csv
import fnmatch
import importlib.util
import logging
import os
import re
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)


# ── CSV-Hilfsfunktion ─────────────────────────────────────────────────────────

def _read_csv(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    rows = []
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            sample = f.read(4096)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=',;')
            except csv.Error:
                dialect = csv.excel
            f.seek(0)
            reader = csv.DictReader(f, dialect=dialect)
            for row in reader:
                # k ist None, wenn eine Zeile mehr Felder hat als die Kopfzeile
                # (DictReader sammelt den Überschuss unter dem Schlüssel None) –
                # solche Overflow-Werte sind keine echten Spalten, ignorieren.
                rows.append({k.strip(): (v or '').strip()
                             for k, v in row.items() if k is not None})
    except Exception as e:
        log.warning(f"CSV-Lesefehler {os.path.basename(path)}: {e}")
    return rows


# ── Blacklist ─────────────────────────────────────────────────────────────────

def _load_blacklist(base_dir: str) -> list:
    """Gibt Liste von (is_pattern, value) zurück. Wildcards: *GRATIS*"""
    path = os.path.join(base_dir, 'postprocess_blacklist.csv')
    if not os.path.exists(path):
        return []
    entries = []
    with open(path, 'r', encoding='utf-8-sig') as f:
        for line in f:
            v = line.strip()
            if v and not v.startswith('#'):
                is_glob = '*' in v or '?' in v
                entries.append((is_glob, v))
    if entries:
        log.info(f"Blacklist: {len(entries)} Einträge geladen")
    return entries


def _is_blacklisted(entries: list, product_id: str, supplier_pid: str) -> bool:
    for is_glob, pattern in entries:
        for val in (product_id, supplier_pid):
            if is_glob:
                if fnmatch.fnmatch(val, pattern) or fnmatch.fnmatch(val.upper(), pattern.upper()):
                    return True
            else:
                if val == pattern:
                    return True
    return False


# ── FUSAGE-3-Liste ────────────────────────────────────────────────────────────

def _load_fusage3(base_dir: str) -> set:
    path = os.path.join(base_dir, 'fusage_3_features.csv')
    if not os.path.exists(path):
        return set()
    names = set()
    with open(path, 'r', encoding='utf-8-sig') as f:
        for line in f:
            v = line.strip()
            if v and not v.startswith('#') and v.lower() != 'fname':
                names.add(v)
    if names:
        log.info(f"FUSAGE-3-Liste: {len(names)} Features geladen")
    return names


def _apply_fusage(features: list, fusage3: set) -> list:
    if not fusage3:
        return features
    result = []
    for f in features:
        f2 = dict(f)
        f2['fusage'] = 3 if f.get('fname', '') in fusage3 else 1
        result.append(f2)
    return result


# ── FNAME-Blacklist ───────────────────────────────────────────────────────────

def _load_fname_blacklist(base_dir: str) -> list:
    """
    Gibt Liste von Regeln [{fname, is_glob, fvalue}] zurück.
    Spalten: fname (Pflicht, Wildcards *Marke* erlaubt), fvalue (optional).
    Ist fvalue gesetzt, wird das Feature nur bei diesem Wert gefiltert
    (z.B. 'Be Green' nur wenn FVALUE=CAA017). Leeres fvalue = immer filtern.
    """
    path = os.path.join(base_dir, 'postprocess_fname_blacklist.csv')
    if not os.path.exists(path):
        return []
    entries = []
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            # Kommentarzeilen (können selbst Kommas enthalten) vor dem CSV-Parsing entfernen
            lines = [ln for ln in f if not ln.strip().startswith('#')]
        try:
            dialect = csv.Sniffer().sniff(''.join(lines[:20]), delimiters=',;')
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(lines, dialect=dialect)
        for row in reader:
            fname = (row.get('fname') or '').strip()
            if not fname:
                continue
            entries.append({
                'fname':   fname,
                'is_glob': '*' in fname or '?' in fname,
                'fvalue':  (row.get('fvalue') or '').strip(),
            })
    except Exception as e:
        log.warning(f"FNAME-Blacklist Lesefehler: {e}")
        return []
    if entries:
        log.info(f"FNAME-Blacklist: {len(entries)} Einträge geladen")
    return entries


# ECLASS-Booleschwerte können als Roh-Code (CAA017) oder bereits über
# fvalue_renames.csv konvertiert (Nein) in der DB stehen — beide Seiten
# der Regel akzeptieren beide Schreibweisen.
_ECLASS_BOOL_ALIASES = {'caa016': 'ja', 'caa017': 'nein'}


def _fvalue_matches(rule_value: str, actual_value: str) -> bool:
    rv = rule_value.strip().lower()
    av = (actual_value or '').strip().lower()
    if rv == av:
        return True
    return _ECLASS_BOOL_ALIASES.get(rv, rv) == _ECLASS_BOOL_ALIASES.get(av, av)


def _is_fname_blacklisted(entries: list, fname: str, fvalue: str) -> bool:
    for rule in entries:
        pattern = rule['fname']
        if rule['is_glob']:
            name_match = (fnmatch.fnmatch(fname, pattern)
                          or fnmatch.fnmatch(fname.upper(), pattern.upper()))
        else:
            name_match = fname.lower() == pattern.lower()
        if not name_match:
            continue
        if rule['fvalue'] and not _fvalue_matches(rule['fvalue'], fvalue):
            continue   # fvalue-Bedingung gesetzt, aber nicht erfüllt
        return True
    return False


def _apply_fname_blacklist(features: list, blacklist: list) -> list:
    if not blacklist:
        return features
    return [f for f in features
            if not _is_fname_blacklisted(blacklist, f.get('fname', ''), f.get('fvalue', ''))]


# ── Preisberechnung ───────────────────────────────────────────────────────────

def _parse_price_formula(formula: str):
    formula = formula.strip()
    if formula.startswith('fixed:'):
        val = float(formula[6:])
        return lambda p: val
    if formula.startswith('*'):
        factor = float(formula[1:])
        return lambda p, f=factor: round(p * f, 2) if p is not None else p
    if formula.startswith('+'):
        delta = float(formula[1:])
        return lambda p, d=delta: round(p + d, 2) if p is not None else p
    if formula.startswith('-'):
        delta = float(formula[1:])
        return lambda p, d=delta: round(p - d, 2) if p is not None else p
    try:
        ast.parse(formula, mode='eval')
        return lambda p, f=formula: round(eval(f.replace('price', str(p))), 2) if p is not None else p
    except Exception:
        log.warning(f"Unbekannte Preisformel: {formula!r}")
        return lambda p: p


def _load_price_rules(base_dir: str) -> list:
    rows  = _read_csv(os.path.join(base_dir, 'postprocess_prices.csv'))
    rules = []
    for row in rows:
        formula = row.get('formula', '')
        if not formula or formula.startswith('#'):
            continue
        pattern = row.get('product_id_pattern', '*') or '*'
        regex   = re.compile('^' + re.escape(pattern).replace(r'\*', '.*') + '$', re.I)
        rules.append({
            'supplier':     row.get('supplier', ''),
            'pattern':      regex,
            'raw_pattern':  pattern,
            'fn':           _parse_price_formula(formula),
            'to_type':      row.get('to_type',   '').strip(),
            'date_from':    row.get('date_from',  '').strip(),
            'date_to':      row.get('date_to',    '').strip(),
        })
    if rules:
        log.info(f"Preisformeln: {len(rules)} geladen")
    return rules


def build_price_rule_index(rules: list) -> tuple[dict, list]:
    """
    Trennt Preisregeln in exakte product_id-Treffer (Dict, O(1)-Lookup) und
    echte Wildcard-Muster (kleine Liste, linear geprüft).

    Vermeidet den O(n×m)-Scan über alle Regeln pro Artikel – bei z.B. 73.000
    Softcarrier-Einzelregeln (eine pro Artikel, keine Wildcards) bedeutete das
    bislang bis zu 73.000 Regex-Vergleiche PRO ARTIKEL, insbesondere teuer für
    Artikel ohne passende Regel (Schleife muss komplett durchlaufen).

    Gibt (exact_index, wildcard_rules) zurück – exact_index ist
    {PRODUCT_ID (upper): [rule, ...]} in ursprünglicher Datei-Reihenfolge.
    """
    exact: dict = {}
    wildcard: list = []
    for order, rule in enumerate(rules):
        rule = {**rule, '_order': order}
        raw = rule.get('raw_pattern', '*')
        if '*' in raw or '?' in raw:
            wildcard.append(rule)
        else:
            exact.setdefault(raw.upper(), []).append(rule)
    return exact, wildcard


def match_price_rule(exact_index: dict, wildcard_rules: list, pid: str, supplier: str):
    """O(1)-im-Schnitt-Ersatz für die lineare Preisregel-Suche. Erhält die
    ursprüngliche Datei-Reihenfolge als Priorität (erste passende Regel gewinnt)."""
    candidates = exact_index.get(pid.upper(), []) + wildcard_rules
    if not candidates:
        return None
    for rule in sorted(candidates, key=lambda r: r['_order']):
        if rule['supplier'] and rule['supplier'].lower() != supplier.lower():
            continue
        if rule['pattern'].match(pid):
            return rule
    return None


# ── Preis-Typ-Konvertierung ───────────────────────────────────────────────────

def _load_price_type_rules(base_dir: str) -> list:
    """net_list → nrp etc., mit optionaler Datumssetzung"""
    rows  = _read_csv(os.path.join(base_dir, 'postprocess_price_types.csv'))
    rules = []
    for row in rows:
        from_t = row.get('from_type', '')
        to_t   = row.get('to_type', '')
        if not from_t or not to_t or from_t.startswith('#'):
            continue
        rules.append({
            'supplier':             row.get('supplier', ''),
            'from_type':            from_t,
            'to_type':              to_t,
            'date_from':            row.get('date_from', ''),
            'date_to_offset_days':  int(row.get('date_to_offset_days', 0) or 0),
        })
    if rules:
        log.info(f"Preis-Typ-Regeln: {len(rules)} geladen")
    return rules


def _apply_price_type(art: dict, rules: list) -> dict:
    sup = art.get('supplier_name', '')
    for rule in rules:
        if rule['supplier'] and rule['supplier'].lower() != sup.lower():
            continue
        if art.get('price_type', '') == rule['from_type']:
            art['price_type'] = rule['to_type']
            if rule['date_from']:
                art['valid_start_date'] = rule['date_from']
            if rule['date_to_offset_days']:
                dt = datetime.now(timezone.utc) + timedelta(days=rule['date_to_offset_days'])
                art['valid_end_date'] = dt.strftime('%Y-%m-%d')
            break
    return art


# ── AID-Suffixe ───────────────────────────────────────────────────────────────

def _load_suffix_rules(base_dir: str) -> dict:
    rows = _read_csv(os.path.join(base_dir, 'postprocess_suffixes.csv'))
    rules = {}
    for row in rows:
        sup = row.get('supplier', '')
        sfx = row.get('aid_suffix', '')
        if sup:
            rules[sup] = sfx
    if rules:
        log.info(f"AID-Suffixe: {len(rules)} Lieferanten konfiguriert")
    return rules


# ── Kategorie-Mapping ─────────────────────────────────────────────────────────

def _load_category_rules(base_dir: str) -> dict:
    rows  = _read_csv(os.path.join(base_dir, 'postprocess_categories.csv'))
    rules = {}
    for row in rows:
        pid = row.get('product_id', '')
        grp = row.get('catalog_group_id', '')
        sub = row.get('catalog_sub_group_id', '')
        if pid:
            rules[pid] = (grp, sub)
    if rules:
        log.info(f"Kategorie-Mapping: {len(rules)} Einträge geladen")
    return rules


# ── Crossselling ──────────────────────────────────────────────────────────────

def _load_crosssell_rules(base_dir: str) -> dict:
    rows  = _read_csv(os.path.join(base_dir, 'postprocess_crosssell.csv'))
    rules: dict[str, list] = {}
    for row in rows:
        pid       = row.get('product_id', '')
        art_id_to = row.get('art_id_to', '')
        ref_type  = row.get('ref_type', 'similar') or 'similar'
        if pid and art_id_to:
            rules.setdefault(pid, []).append({'ref_type': ref_type, 'art_id_to': art_id_to})
    if rules:
        log.info(f"Crossselling: {len(rules)} Artikel konfiguriert")
    return rules


# ── Referenztyp-Remapping ─────────────────────────────────────────────────────

def _load_reference_type_rules(base_dir: str) -> dict:
    rows  = _read_csv(os.path.join(base_dir, 'postprocess_reference_types.csv'))
    rules = {}
    for row in rows:
        ft = row.get('from_type', '')
        tt = row.get('to_type', '')
        if ft and tt and not ft.startswith('#'):
            rules[ft] = tt
    if rules:
        log.info(f"Referenztyp-Mapping: {len(rules)} Typen konfiguriert")
    return rules


# ── Mediendaten (Artikel-spezifisch) ─────────────────────────────────────────

def _load_media_rules(base_dir: str) -> dict:
    rows = _read_csv(os.path.join(base_dir, 'postprocess_media.csv'))
    rules: dict[str, list] = {}
    for row in rows:
        pid    = row.get('product_id', '')
        action = row.get('action', 'add').lower()
        if pid:
            rules.setdefault(pid, []).append({
                'action':       action,
                'mime_type':    row.get('mime_type', ''),
                'mime_source':  row.get('mime_source', ''),
                'mime_purpose': row.get('mime_purpose', ''),
                'mime_desc':    row.get('mime_desc', ''),
                'mime_alt':     row.get('mime_alt', ''),
                'mime_order':   int(row.get('mime_order', 0) or 0),
            })
    if rules:
        log.info(f"Medien-Overrides: {len(rules)} Artikel konfiguriert")
    return rules


# ── Globale MIME-Regeln ───────────────────────────────────────────────────────

def _load_global_media_rules(base_dir: str) -> list:
    """
    Globale Regeln anhand von Patterns (unabhängig von product_id).
    Spalten: supplier, description_pattern, source_pattern, mime_type_pattern, new_purpose
    """
    rows  = _read_csv(os.path.join(base_dir, 'postprocess_media_global.csv'))
    rules = []
    for row in rows:
        np = row.get('new_purpose', '').strip()
        if not np or np.startswith('#'):
            continue
        rules.append({
            'supplier':             row.get('supplier', '').strip(),
            'description_pattern':  row.get('description_pattern', '').strip(),
            'source_pattern':       row.get('source_pattern', '').strip(),
            'mime_type_pattern':    row.get('mime_type_pattern', '').strip(),
            'new_purpose':          np,
        })
    if rules:
        log.info(f"Globale Medienregeln: {len(rules)} geladen")
    return rules


def _match_pattern(value: str, pattern: str) -> bool:
    """Leer = passt immer. * = Wildcard."""
    if not pattern:
        return True
    return fnmatch.fnmatch(value, pattern) or fnmatch.fnmatch(value.lower(), pattern.lower())


def _apply_global_media(mimes: list, sup: str, global_rules: list) -> list:
    if not global_rules:
        return mimes
    result = []
    for m in mimes:
        m2 = dict(m)
        for rule in global_rules:
            if rule['supplier'] and not _match_pattern(sup, rule['supplier']):
                continue
            if not _match_pattern(m.get('mime_desc', ''), rule['description_pattern']):
                continue
            if not _match_pattern(m.get('mime_source', ''), rule['source_pattern']):
                continue
            if not _match_pattern(m.get('mime_type', ''), rule['mime_type_pattern']):
                continue
            m2['mime_purpose'] = rule['new_purpose']
            break  # erste passende Regel gewinnt
        result.append(m2)
    return result


# ── Lieferanten-Priorität (EAN-Dedup) ────────────────────────────────────────

def load_supplier_priority(base_dir: str) -> dict:
    """Gibt {supplier_name: priority_int} zurück. Niedrigere Zahl = höhere Priorität."""
    rows = _read_csv(os.path.join(base_dir, 'supplier_priority.csv'))
    result = {}
    for row in rows:
        sup = row.get('supplier_name', '')
        pri = row.get('priority', '')
        if sup and pri and not sup.startswith('#'):
            try:
                result[sup] = int(pri)
            except ValueError:
                pass
    return result


def apply_ean_dedup(articles: list, priority: dict) -> list:
    """
    EAN-Crosslieferant-Deduplizierung.
    Bei mehreren Lieferanten mit derselben EAN gewinnt der mit niedrigster Priority.
    Artikel ohne EAN oder mit EAN='0' werden nicht berührt.
    """
    if not priority:
        return articles

    # EAN → niedrigste Priority unter allen Artikeln mit dieser EAN ermitteln
    ean_min_prio: dict[str, int] = {}
    for art in articles:
        ean = art.get('ean', '').strip()
        if not ean or ean == '0':
            continue
        sup  = art.get('supplier_name', '')
        prio = priority.get(sup, 999)
        if ean not in ean_min_prio or prio < ean_min_prio[ean]:
            ean_min_prio[ean] = prio

    filtered = []
    skipped  = 0
    for art in articles:
        ean = art.get('ean', '').strip()
        if not ean or ean == '0':
            filtered.append(art)
            continue
        sup  = art.get('supplier_name', '')
        prio = priority.get(sup, 999)
        if prio <= ean_min_prio[ean]:
            filtered.append(art)
        else:
            skipped += 1

    if skipped:
        log.info(f"EAN-Dedup: {skipped} Artikel übersprungen (EAN-Konflikt, niedrigere Priorität)")
    return filtered


# ── Python-Hook ───────────────────────────────────────────────────────────────

def _load_hook(base_dir: str):
    hook_path = os.path.join(base_dir, 'postprocess_hook.py')
    if not os.path.exists(hook_path):
        return None
    try:
        spec   = importlib.util.spec_from_file_location('postprocess_hook', hook_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if hasattr(module, 'process'):
            log.info("postprocess_hook.py geladen")
            return module.process
    except Exception as e:
        log.warning(f"postprocess_hook.py Ladefehler: {e}")
    return None


# ── Haupt-PostProcessor ───────────────────────────────────────────────────────

def _check_price_expiry(rules: list, warn_days: int = 30) -> list[str]:
    """
    Prüft ob Preisregeln ablaufen oder bereits abgelaufen sind.
    Gibt Liste von Warnungstexten zurück.
    warn_days: Warnung wenn date_to weniger als N Tage entfernt.
    """
    from datetime import date, datetime
    today = date.today()
    warnings = []
    expired = []
    soon = []

    for r in rules:
        dt_str = r.get("date_to", "")
        if not dt_str:
            continue
        try:
            dt = datetime.strptime(dt_str[:10], "%Y-%m-%d").date()
            days_left = (dt - today).days
            pid = r.get("pattern").pattern.replace("^", "").replace(".*", "*").replace("$", "")
            supplier = r.get("supplier", "?")
            if days_left < 0:
                expired.append((pid, supplier, dt_str, abs(days_left)))
            elif days_left < warn_days:
                soon.append((pid, supplier, dt_str, days_left))
        except Exception:
            pass

    if expired:
        warnings.append(
            f"{len(expired)} Preisregel(n) bereits abgelaufen "
            f"(z.B. {expired[0][1]} {expired[0][0][:20]} "
            f"seit {expired[0][3]} Tagen).")
    if soon:
        warnings.append(
            f"{len(soon)} Preisregel(n) laufen in <{warn_days} Tagen ab "
            f"(z.B. {soon[0][1]} {soon[0][0][:20]} "
            f"läuft {soon[0][3]} Tage ab).")
    return warnings


class PostProcessor:

    def __init__(self, base_dir: str):
        self._base_dir     = base_dir
        self._blacklist    = _load_blacklist(base_dir)
        self._fname_blacklist = _load_fname_blacklist(base_dir)
        self._fusage3      = _load_fusage3(base_dir)
        self._price_rules  = _load_price_rules(base_dir)
        self._price_rule_exact, self._price_rule_wildcard = build_price_rule_index(self._price_rules)
        self._price_warnings: list[str] = _check_price_expiry(self._price_rules)
        self._price_types  = _load_price_type_rules(base_dir)
        self._suffixes     = _load_suffix_rules(base_dir)
        self._categories   = _load_category_rules(base_dir)
        self._crosssell    = _load_crosssell_rules(base_dir)
        self._ref_types    = _load_reference_type_rules(base_dir)
        self._media        = _load_media_rules(base_dir)
        self._global_media = _load_global_media_rules(base_dir)
        self._hook         = _load_hook(base_dir)
        self.no_price_rule_pids: list[str] = []

    def is_blacklisted(self, article: dict) -> bool:
        return _is_blacklisted(
            self._blacklist,
            article.get('product_id', ''),
            article.get('supplier_pid', ''),
        )

    def process(self, article: dict) -> dict | None:
        if self.is_blacklisted(article):
            return None

        art = dict(article)
        pid = art.get('product_id', '')
        sup = art.get('supplier_name', '')

        # ── FNAME-Blacklist ──────────────────────────────────────────────────
        art['features'] = _apply_fname_blacklist(art.get('features', []), self._fname_blacklist)

        # ── FUSAGE ────────────────────────────────────────────────────────────
        art['features'] = _apply_fusage(art.get('features', []), self._fusage3)

        # ── Preisformel ───────────────────────────────────────────────────────
        rule = match_price_rule(self._price_rule_exact, self._price_rule_wildcard, pid, sup)
        if rule:
            art['price_amount'] = rule['fn'](art.get('price_amount'))
            if rule.get('to_type'):
                art['price_type'] = rule['to_type']
            if rule.get('date_from'):
                art['valid_start_date'] = rule['date_from']
            if rule.get('date_to'):
                from datetime import date, timedelta
                raw = rule['date_to']
                if raw.startswith('+'):
                    # Syntax: +365 → heute + 365 Tage (rollierend)
                    try:
                        art['valid_end_date'] = (
                            date.today() + timedelta(days=int(raw[1:]))
                        ).isoformat()
                    except ValueError:
                        art['valid_end_date'] = raw
                else:
                    # Festes Datum: 2027-12-31
                    art['valid_end_date'] = raw
            art['_price_rule_applied'] = True

        # ── SOC ohne Preisregel → nicht exportieren ──────────────────────────
        if not art.get('_price_rule_applied'):
            sup_norm = sup.lower().replace('ü', 'u').replace(' ', '')
            if 'softcarrier' in sup_norm or 'soc' in sup_norm:
                self.no_price_rule_pids.append(pid)
                return None

        # ── Preis-Typ-Konvertierung ───────────────────────────────────────────
        art = _apply_price_type(art, self._price_types)

        # ── Preisplausibilität ────────────────────────────────────────────────
        price = art.get('price_amount')
        if isinstance(price, (int, float)):
            if price <= 0:
                log.warning(f"Preiswarnung {pid}: Preis = {price} (≤ 0)")
                art['_price_zero'] = True
            elif price > 5000:
                log.debug(f"Hoher Preis {pid}: {price:.2f} EUR (> 5.000)")

        # ── AID-Suffix ────────────────────────────────────────────────────────
        suffix = self._suffixes.get(sup, '')
        if suffix:
            art['_aid_suffix'] = suffix

        # ── Kategorie ─────────────────────────────────────────────────────────
        if pid in self._categories:
            grp, sub = self._categories[pid]
            art['catalog_group_id']     = grp
            art['catalog_sub_group_id'] = sub

        # ── Crossselling ──────────────────────────────────────────────────────
        if pid in self._crosssell:
            existing = {r['art_id_to'] for r in art.get('references', [])}
            for ref in self._crosssell[pid]:
                if ref['art_id_to'] not in existing:
                    art.setdefault('references', []).append(ref)

        # ── Referenztypen remappen ────────────────────────────────────────────
        if self._ref_types:
            art['references'] = [
                {**r, 'ref_type': self._ref_types.get(r.get('ref_type', ''), r.get('ref_type', ''))}
                for r in art.get('references', [])
            ]

        # ── Medien (Artikel-spezifisch) ───────────────────────────────────────
        if pid in self._media:
            mimes = list(art.get('mimes', []))
            for rule in self._media[pid]:
                purpose = rule['mime_purpose']
                if rule['action'] == 'remove':
                    mimes = [m for m in mimes if m.get('mime_purpose') != purpose]
                elif rule['action'] == 'replace':
                    mimes = [m for m in mimes if m.get('mime_purpose') != purpose]
                    mimes.append({k: v for k, v in rule.items() if k != 'action'})
                elif rule['action'] == 'add':
                    mimes.append({k: v for k, v in rule.items() if k != 'action'})
            art['mimes'] = sorted(mimes, key=lambda m: m.get('mime_order', 0))

        # ── Globale MIME-Regeln ───────────────────────────────────────────────
        art['mimes'] = _apply_global_media(art.get('mimes', []), sup, self._global_media)

        # ── Python-Hook ───────────────────────────────────────────────────────
        if self._hook:
            try:
                art = self._hook(art)
                if art is None:
                    return None
            except Exception as e:
                log.warning(f"Hook-Fehler für {pid}: {e}")

        return art
