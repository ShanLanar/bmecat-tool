# lib/notifications.py – Benachrichtigungen nach dem Lauf
#
# Sendet eine E-Mail-Zusammenfassung wenn Fehler aufgetreten sind.
# Konfiguration über NOTIFICATION in config.py (optional).
#
# Beispiel config.py:
#   NOTIFICATION = {
#       "enabled":    True,
#       "smtp_host":  "smtp.example.com",
#       "smtp_port":  587,
#       "smtp_user":  "user@example.com",
#       "smtp_pass":  "geheim",
#       "smtp_tls":   True,
#       "from":       "bmecat-tool@abe-brands.de",
#       "to":         ["admin@abe-brands.de"],
#       "on_success": False,    # nur bei Fehlern senden
#   }

import os
import json
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

log = logging.getLogger(__name__)


def _get_config() -> dict:
    """Lädt Notification-Config, gibt leeres dict zurück wenn nicht vorhanden."""
    try:
        import config
        return getattr(config, "NOTIFICATION", {})
    except Exception:
        return {}


def send_run_summary(report_data: dict, progress_cb=None):
    """
    Sendet eine E-Mail-Zusammenfassung des Laufs.

    Args:
        report_data: Dict mit Lauf-Daten (aus LaufReport oder direkt)
            Erwartet: tasks_gesamt, tasks_ok, tasks_fehler, fehler[], dauer_s, tasks[]
        progress_cb: Log-Callback
    """
    p = progress_cb or (lambda m, **kw: None)
    cfg = _get_config()

    if not cfg.get("enabled", False):
        return

    has_errors = report_data.get("tasks_fehler", 0) > 0
    if not has_errors and not cfg.get("on_success", False):
        return  # bei Erfolg nicht senden

    try:
        subject = _build_subject(report_data)
        body    = _build_body(report_data)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = cfg.get("from", "bmecat-tool@localhost")
        msg["To"]      = ", ".join(cfg.get("to", []))

        msg.attach(MIMEText(body, "plain", "utf-8"))

        smtp_host = cfg.get("smtp_host", "localhost")
        smtp_port = cfg.get("smtp_port", 587)

        if cfg.get("smtp_tls", True):
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
            server.starttls()
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)

        if cfg.get("smtp_user"):
            server.login(cfg["smtp_user"], cfg.get("smtp_pass", ""))

        server.sendmail(
            msg["From"],
            cfg.get("to", []),
            msg.as_string()
        )
        server.quit()

        p("Benachrichtigung gesendet.", tag="ok")
        log.info("E-Mail-Benachrichtigung gesendet an %s", cfg.get("to"))

    except Exception as e:
        p(f"Benachrichtigung fehlgeschlagen: {e}", tag="warn")
        log.warning("E-Mail-Versand fehlgeschlagen: %s", e)


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

    # Fehler-Details
    fehler = data.get("fehler", [])
    if fehler:
        lines.append("FEHLER:")
        for f in fehler:
            lines.append(f"  ❌ {f}")
        lines.append("")

    # Task-Übersicht
    lines.append("Task-Details:")
    lines.append("-" * 50)
    for task in data.get("tasks", []):
        status = "✅" if task["status"] == "ok" else "❌"
        dur    = f"{task['duration_s']:.1f}s"
        lines.append(f"  {status} {task['name']:40s} {dur:>8s}")
        if task.get("details", {}).get("fehler"):
            lines.append(f"     → {task['details']['fehler']}")
    lines.append("")

    # Deduplizierung
    dedup = data.get("deduplizierung", {})
    if dedup.get("removed", 0) > 0:
        lines.append(
            f"Deduplizierung: {dedup['removed']} Features entfernt "
            f"in {dedup['articles']} Artikeln aus {dedup['files']} Dateien"
        )

    lines.append("")
    lines.append("-- ")
    lines.append("BMEcat Download-Tool (automatisch generiert)")

    return "\n".join(lines)
