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


def _build_subject(data: dict) -> str:
    n_err = data.get("tasks_fehler", 0)
    n_ok  = data.get("tasks_ok", 0)
    total = data.get("tasks_gesamt", 0)
    if n_err > 0:
        return f"⚠ BMEcat-Tool: {n_err} Fehler bei {total} Tasks"
    return f"✅ BMEcat-Tool: {n_ok}/{total} Tasks erfolgreich"


def _build_body(data: dict) -> str:
    lines = [
        "BMEcat Download-Tool – Lauf-Zusammenfassung",
        "=" * 50,
        "",
        f"Start:    {data.get('start', '?')}",
        f"Ende:     {data.get('ende', '?')}",
        f"Dauer:    {data.get('dauer_s', 0):.0f} Sekunden",
        "",
        f"Tasks:    {data.get('tasks_ok', 0)} OK, "
        f"{data.get('tasks_fehler', 0)} Fehler "
        f"(von {data.get('tasks_gesamt', 0)})",
        "",
    ]

    fehler = data.get("fehler", [])
    if fehler:
        lines.append("FEHLER:")
        for f in fehler:
            lines.append(f"  ❌ {f}")
        lines.append("")

    lines.append("Task-Details:")
    lines.append("-" * 50)
    for task in data.get("tasks", []):
        status = "✅" if task["status"] == "ok" else "❌"
        dur    = f"{task['duration_s']:.1f}s"
        lines.append(f"  {status} {task['name']:40s} {dur:>8s}")
        if task.get("details", {}).get("fehler"):
            lines.append(f"     → {task['details']['fehler']}")
    lines.append("")

    dedup = data.get("deduplizierung", {})
    if dedup.get("removed", 0) > 0:
        lines.append(
            f"Deduplizierung: {dedup['removed']} Features entfernt "
            f"in {dedup['articles']} Artikeln aus {dedup['files']} Dateien"
        )

    lines += ["", "-- ", "BMEcat Download-Tool (automatisch generiert)"]
    return "\n".join(lines)


def _build_mail(report: dict, dropped: list, price_warnings: list) -> tuple[str, str]:
    host = socket.gethostname()
    ts   = datetime.now().strftime("%d.%m.%Y %H:%M")

    subject = f"[BMEcat-Tool] {_build_subject(report)} – {ts} ({host})"
    body    = _build_body(report)

    extras = []
    if dropped:
        extras += [
            f"WEGGEFALLENE ARTIKEL ({len(dropped)}):",
            "(nicht mehr im Lieferantenkatalog – im Shop ggf. deaktivieren)",
            "",
        ]
        for a in dropped[:50]:
            extras.append(f"  {a.get('product_id','?'):<20}  {a.get('supplier_name','')}")
        if len(dropped) > 50:
            extras.append(f"  … und {len(dropped) - 50} weitere")
        extras.append("")

    if price_warnings:
        extras += ["PREISREGEL-WARNUNGEN:", ""]
        for w in price_warnings:
            extras.append(f"  ⚠  {w}")
        extras.append("")

    if extras:
        body = body + "\n" + "\n".join(extras)

    return subject, body


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
