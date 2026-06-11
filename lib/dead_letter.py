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

_AID_PAT = re.compile(r'<SUPPLIER_AID>(.*?)</SUPPLIER_AID>', re.IGNORECASE)


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
