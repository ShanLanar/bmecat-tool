# lib/notifications.py – Kompatibilitäts-Weiterleitung → lib/notifier.py
#
# Kanonische Implementierung: lib/notifier.py (wird von main.py verwendet).
# Dieses Modul leitet weiter damit bestehende Imports und Tests unverändert bleiben.

from lib.notifier import (  # noqa: F401
    _build_subject,
    _build_body,
    send_run_notification as send_run_summary,
)
