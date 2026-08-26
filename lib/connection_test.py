# lib/connection_test.py – FTP/SFTP-Verbindungstest (kein Download)
#
# Prüft für jeden Eintrag in config.CONNECTIONS, ob eine Verbindung
# aufgebaut und angemeldet werden kann. Gibt je eine Status-Zeile zurück.

import logging
import socket
import ftplib
from dataclasses import dataclass
from typing import Callable, Optional

log = logging.getLogger(__name__)


@dataclass
class TestResult:
    name:    str
    ok:      bool
    message: str
    latency_ms: Optional[float] = None


def _test_ftp(name: str, cfg: dict) -> TestResult:
    import time
    host = cfg["host"]
    port = cfg.get("port", 21)
    t0   = time.monotonic()
    try:
        ftp = ftplib.FTP()
        ftp.connect(host, port, timeout=10)
        ftp.login(cfg["user"], cfg["password"])
        welcome = ftp.getwelcome()
        ftp.quit()
        ms = round((time.monotonic() - t0) * 1000)
        return TestResult(name, True, f"OK – {welcome[:60]}", ms)
    except ftplib.error_perm as e:
        return TestResult(name, False, f"Anmeldung fehlgeschlagen: {e}")
    except (socket.timeout, ConnectionRefusedError, OSError) as e:
        return TestResult(name, False, f"Verbindung fehlgeschlagen: {e}")
    except Exception as e:
        return TestResult(name, False, f"Fehler: {e}")


def _test_sftp(name: str, cfg: dict) -> TestResult:
    import time
    try:
        import paramiko
    except ImportError:
        return TestResult(name, False, "paramiko nicht installiert (pip install paramiko)")

    host = cfg["host"]
    port = cfg.get("port", 22)
    t0   = time.monotonic()
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host, port=port,
                    username=cfg["user"], password=cfg["password"],
                    timeout=10, look_for_keys=False, allow_agent=False)
        sftp = ssh.open_sftp()
        # Kleiner Smoke-Test: Wurzelverzeichnis auflisten
        sftp.listdir(".")
        sftp.close()
        ssh.close()
        ms = round((time.monotonic() - t0) * 1000)
        return TestResult(name, True, "OK – Anmeldung + SFTP-Handshake erfolgreich", ms)
    except paramiko.AuthenticationException as e:
        return TestResult(name, False, f"Authentifizierung fehlgeschlagen: {e}")
    except (socket.timeout, OSError) as e:
        return TestResult(name, False, f"Verbindung fehlgeschlagen: {e}")
    except Exception as e:
        return TestResult(name, False, f"Fehler: {e}")


def _test_mysql(name: str, cfg: dict) -> TestResult:
    import time
    try:
        import pymysql
    except ImportError:
        return TestResult(name, False, "PyMySQL nicht installiert (pip install PyMySQL)")

    host = cfg["host"]
    port = cfg.get("port", 3306)
    t0   = time.monotonic()
    try:
        con = pymysql.connect(
            host=host, port=port,
            user=cfg["user"], password=cfg["password"],
            database=cfg.get("database") or None,
            connect_timeout=10, charset="utf8mb4",
        )
        con.close()
        ms = round((time.monotonic() - t0) * 1000)
        return TestResult(name, True, "OK – Anmeldung erfolgreich", ms)
    except pymysql.err.OperationalError as e:
        return TestResult(name, False, f"Verbindung/Anmeldung fehlgeschlagen: {e}")
    except Exception as e:
        return TestResult(name, False, f"Fehler: {e}")


def test_all(progress_cb: Optional[Callable] = None) -> list[TestResult]:
    """Testet alle Verbindungen aus config.CONNECTIONS sequenziell."""
    from config import CONNECTIONS
    p = progress_cb or (lambda m, **kw: None)
    results = []

    for name, cfg in CONNECTIONS.items():
        p(f"Teste {name} ({cfg['protocol'].upper()} {cfg['host']}) …")
        protocol = cfg.get("protocol", "ftp").lower()
        if protocol == "sftp":
            r = _test_sftp(name, cfg)
        elif protocol == "mysql":
            r = _test_mysql(name, cfg)
        else:
            r = _test_ftp(name, cfg)

        icon = "✅" if r.ok else "❌"
        lat  = f"  [{r.latency_ms} ms]" if r.latency_ms else ""
        p(f"{icon} {name}: {r.message}{lat}")
        log.info(f"Verbindungstest {name}: {'OK' if r.ok else 'FEHLER'} – {r.message}")
        results.append(r)

    ok_count  = sum(1 for r in results if r.ok)
    p(f"\n{'─'*40}")
    p(f"Ergebnis: {ok_count}/{len(results)} Verbindungen erfolgreich.")
    return results
