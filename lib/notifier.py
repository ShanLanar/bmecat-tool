# lib/notifier.py – E-Mail-Benachrichtigung nach Lauf
#
# Sendet eine Zusammenfassung per SMTP.  Konfiguration in config.NOTIFICATION.
# on_success=False (Standard): nur bei Fehlern senden.

import logging
import smtplib
import socket
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

log = logging.getLogger(__name__)


def send_run_notification(report: dict, dropped_articles: list[dict] = None,
                          price_warnings: list[str] = None) -> bool:
    """
    Sendet eine Zusammenfassung des Laufs per E-Mail.

    report          – LaufReport.as_dict() oder gleichwertiges Dict
    dropped_articles – Liste von {product_id, supplier_name} Artikeln
                       die beim Stale-Cleanup entfernt wurden
    price_warnings  – Liste von Warnungstexten zu ablaufenden Preisregeln
    Gibt True zurück wenn gesendet, False bei Fehler oder deaktiviert.
    """
    try:
        import config as _cfg
        cfg = _cfg.NOTIFICATION
    except Exception:
        return False

    if not cfg.get("enabled"):
        return False

    n_err = report.get("tasks_fehler", 0)
    if n_err == 0 and not cfg.get("on_success") and not price_warnings:
        return False

    subject, body = _build_mail(report, dropped_articles or [], price_warnings or [])

    try:
        _send(cfg, subject, body)
        log.info(f"Benachrichtigungs-Mail gesendet an {cfg['to']}")
        return True
    except Exception as e:
        log.error(f"Mail-Versand fehlgeschlagen: {e}")
        return False


def _build_mail(report: dict, dropped: list, price_warnings: list) -> tuple[str, str]:
    n_ok  = report.get("tasks_ok", 0)
    n_err = report.get("tasks_fehler", 0)
    dauer = report.get("dauer_s", 0)
    host  = socket.gethostname()
    ts    = datetime.now().strftime("%d.%m.%Y %H:%M")

    status = "✓ Erfolgreich" if n_err == 0 else f"✗ {n_err} Fehler"
    subject = f"[BMEcat-Tool] {status} – {ts} ({host})"

    lines = [
        f"BMEcat Download-Tool – Laufbericht",
        f"{'=' * 48}",
        f"Datum:          {ts}",
        f"Rechner:        {host}",
        f"Dauer:          {int(dauer // 60)} min {int(dauer % 60)} s",
        f"Tasks OK:       {n_ok}",
        f"Tasks Fehler:   {n_err}",
        "",
    ]

    if report.get("fehler"):
        lines += ["FEHLERHAFTE TASKS:", ""]
        for t in report["fehler"]:
            lines.append(f"  ✗  {t}")
        lines.append("")

    lines += ["TASK-ÜBERSICHT:", ""]
    for t in report.get("tasks", []):
        icon = "✓" if t["status"] == "ok" else "✗"
        lines.append(f"  {icon}  {t['name']:<35} {t['duration_s']:.0f} s")
    lines.append("")

    if dropped:
        lines += [
            f"WEGGEFALLENE ARTIKEL ({len(dropped)}):",
            "(nicht mehr im Lieferantenkatalog – im Shop ggf. deaktivieren)",
            "",
        ]
        for a in dropped[:50]:
            lines.append(f"  {a.get('product_id','?'):<20}  {a.get('supplier_name','')}")
        if len(dropped) > 50:
            lines.append(f"  … und {len(dropped) - 50} weitere")
        lines.append("")

    if price_warnings:
        lines += ["PREISREGEL-WARNUNGEN:", ""]
        for w in price_warnings:
            lines.append(f"  ⚠  {w}")
        lines.append("")

    lines += [
        "─" * 48,
        "BMEcat Download-Tool  |  ABE GmbH",
    ]

    return subject, "\n".join(lines)


def _send(cfg: dict, subject: str, body: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = cfg.get("from", "bmecat-tool@abe-brands.de")
    msg["To"]      = ", ".join(cfg["to"])
    msg.attach(MIMEText(body, "plain", "utf-8"))

    host = cfg["smtp_host"]
    port = int(cfg.get("smtp_port", 587))
    tls  = cfg.get("smtp_tls", True)

    if tls:
        with smtplib.SMTP(host, port, timeout=15) as s:
            s.starttls()
            if cfg.get("smtp_user"):
                s.login(cfg["smtp_user"], cfg.get("smtp_pass", ""))
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=15) as s:
            if cfg.get("smtp_user"):
                s.login(cfg["smtp_user"], cfg.get("smtp_pass", ""))
            s.send_message(msg)
