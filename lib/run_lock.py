# lib/run_lock.py – Einzelinstanz-Schutz via Lock-File
#
# Verhindert dass zwei Tool-Instanzen gleichzeitig laufen
# (z. B. wenn der Scheduler ein zweites Mal startet während ein Lauf noch läuft).

import os
import logging
import time

log = logging.getLogger(__name__)

_LOCK_FILE = "bmecat_tool.lock"


class RunLock:
    """
    Context-Manager der beim Eintritt eine Lock-Datei erzeugt
    und beim Verlassen löscht.

    Wenn bereits eine Lock-Datei existiert und der Prozess noch läuft:
    → RunLockError wird geworfen.
    Wenn die Lock-Datei existiert aber der Prozess nicht mehr läuft
    (Absturz): Lock wird überschrieben (Stale-Lock).
    """

    def __init__(self, base_dir: str):
        self.path   = os.path.join(base_dir, _LOCK_FILE)
        self._owned = False

    def acquire(self) -> bool:
        """Versucht die Sperre zu setzen. Gibt True zurück wenn erfolgreich."""
        if os.path.exists(self.path):
            try:
                data    = open(self.path).read().strip().split("\n")
                old_pid = int(data[0]) if data else 0
                if _pid_running(old_pid):
                    log.warning(
                        f"Lauf bereits aktiv (PID {old_pid}). "
                        "Neuer Start wird übersprungen.")
                    return False
                log.info(f"Stale Lock-Datei gefunden (PID {old_pid} nicht aktiv), "
                         "wird überschrieben.")
            except Exception:
                pass   # Unlesbare Lock-Datei → überschreiben

        pid = os.getpid()
        ts  = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(self.path, "w") as f:
                f.write(f"{pid}\n{ts}\n")
            self._owned = True
            return True
        except Exception as e:
            log.error(f"Lock-Datei konnte nicht erstellt werden: {e}")
            return True   # Im Zweifel: weiterarbeiten, Doppellauf ist besser als kein Lauf

    def release(self):
        """Gibt die Sperre frei."""
        if self._owned and os.path.exists(self.path):
            try:
                os.unlink(self.path)
                self._owned = False
            except Exception as e:
                log.warning(f"Lock-Datei konnte nicht gelöscht werden: {e}")

    def __enter__(self):
        if not self.acquire():
            raise RunLockError("Lauf bereits aktiv – dieser Start wird übersprungen.")
        return self

    def __exit__(self, *_):
        self.release()


class RunLockError(Exception):
    pass


def _pid_running(pid: int) -> bool:
    """Prüft ob ein Prozess mit dieser PID noch läuft."""
    if pid <= 0:
        return False
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:
        pass
    # Fallback ohne psutil: os.kill mit Signal 0
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False
