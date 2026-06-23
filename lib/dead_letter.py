# lib/dead_letter.py – Dead Letter Queue für problematische Artikel
#
# Artikel die Validierung nicht bestehen landen in
# logs/quarantine_YYYYMMDD.xml statt still übersprungen zu werden.
# Der Rest der Pipeline läuft weiter.
#
# Inspired by: Enterprise Integration Patterns (Hohpe/Woolf),
# Apache Camel Dead Letter Channel.

import os
import re
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

_AID_PAT     = re.compile(r'<SUPPLIER_AID>(.*?)</SUPPLIER_AID>', re.IGNORECASE)
_ARTICLE_PAT = re.compile(r'(?is)(<article[\s>].*?</article>)')


class DeadLetterQueue:
    """
    Sammelt abgelehnte Artikel mit Begründung.
    Schreibt am Ende eine Quarantäne-XML.
    """

    def __init__(self, log_dir: str, supplier: str = ""):
        self._log_dir   = log_dir
        self._supplier  = supplier
        self._rejected: list = []   # [(aid, reason, article_xml)]

    def reject(self, article_xml: str, reason: str):
        """Artikel zur DLQ hinzufügen."""
        aid_m = _AID_PAT.search(article_xml)
        aid   = aid_m.group(1).strip() if aid_m else "UNKNOWN"
        self._rejected.append((aid, reason, article_xml))
        log.debug("DLQ: %s abgelehnt (%s)", aid, reason)

    def __len__(self):
        return len(self._rejected)

    def flush(self, progress_cb=None) -> str | None:
        """
        Schreibt alle abgelehnten Artikel nach quarantine_YYYYMMDD.xml.
        Gibt den Dateipfad zurück oder None wenn DLQ leer.
        """
        p = progress_cb or (lambda m, **kw: None)

        if not self._rejected:
            return None

        Path(self._log_dir).mkdir(parents=True, exist_ok=True)
        ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
        supplier = f"_{self._supplier}" if self._supplier else ""
        out_path = os.path.join(self._log_dir,
                                f"quarantine{supplier}_{ts}.xml")

        with open(out_path, "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write(f'<!-- BMEcat Dead Letter Queue — {len(self._rejected)} Artikel -->\n')
            f.write(f'<!-- Zeitpunkt: {datetime.now().isoformat()} -->\n')
            f.write('<QUARANTINE>\n')
            for aid, reason, xml in self._rejected:
                f.write(f'  <!-- AID: {aid} | Grund: {reason} -->\n')
                f.write(f'  {xml.strip()}\n')
            f.write('</QUARANTINE>\n')

        p(f"Dead Letter Queue: {len(self._rejected)} Artikel in Quarantäne "
          f"→ {os.path.basename(out_path)}", tag="warn")

        self._rejected.clear()
        return out_path


def quarantine_no_aid(xml_path: str, progress_cb=None) -> int:
    """
    Schneller Pflichtprüf-Pass: entfernt alle Artikel ohne SUPPLIER_AID aus der XML.
    Quarantänisiert sie in logs/quarantine_no_aid_YYYYMMDD.xml.
    Gibt Anzahl entfernter Artikel zurück.

    Deutlich schneller als enrich() da keine Enrichment-Regeln laufen.
    Wird auch bei Merge-Skip aufgerufen.
    """
    p = progress_cb or (lambda m, **kw: None)

    content = Path(xml_path).read_text(encoding="utf-8", errors="replace")
    removed = []

    def _check(m):
        art = m.group(1)
        aid_m = _AID_PAT.search(art)
        if not aid_m or not aid_m.group(1).strip():
            removed.append(art)
            return ""   # Artikel aus XML entfernen
        return art

    new_content = _ARTICLE_PAT.sub(_check, content)

    if not removed:
        return 0

    # Quarantäne-Datei schreiben
    try:
        import config as _cfg
        log_dir = _cfg.DIRS.get("logs", "logs")
    except Exception:
        log_dir = os.path.join(os.path.dirname(xml_path), "..", "logs")

    Path(log_dir).mkdir(parents=True, exist_ok=True)
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    q_path   = os.path.join(log_dir, f"quarantine_no_aid_{ts}.xml")
    with open(q_path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write(f'<!-- Artikel ohne SUPPLIER_AID — {len(removed)} Stück -->\n')
        f.write('<QUARANTINE>\n')
        for art in removed:
            f.write(f'  {art.strip()}\n')
        f.write('</QUARANTINE>\n')

    Path(xml_path).write_text(new_content, encoding="utf-8")

    p(f"⛔ SUPPLIER_AID-Prüfung: {len(removed)} Artikel ohne SUPPLIER_AID entfernt "
      f"→ {os.path.basename(q_path)}", tag="warn")
    log.warning("quarantine_no_aid: %d Artikel aus %s entfernt",
                len(removed), os.path.basename(xml_path))
    return len(removed)


def validate_article_basic(article_xml: str) -> str | None:
    """
    Minimale Artikel-Validierung für DLQ-Entscheidung.

    Returns:
        Fehlergrund als String, oder None wenn OK.
    """
    # Kein SUPPLIER_AID
    aid_m = _AID_PAT.search(article_xml)
    if not aid_m or not aid_m.group(1).strip():
        return "Kein SUPPLIER_AID"

    aid = aid_m.group(1).strip()

    # AID enthält XML-Sonderzeichen
    if any(c in aid for c in ('<', '>', '&', '"')):
        return f"SUPPLIER_AID enthält XML-Sonderzeichen: {aid!r}"

    # Leerer Artikel-Block (< 50 Zeichen Nutzcontent)
    content = re.sub(r'<[^>]+>', '', article_xml).strip()
    if len(content) < 10:
        return "Artikel-Block nahezu leer"

    return None
