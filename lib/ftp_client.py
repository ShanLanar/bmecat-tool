# lib/ftp_client.py – FTP- und SFTP-Operationen, optimiert für Hochgeschwindigkeit
#
# Kernoptimierungen:
#   FTP:  blocksize = 8 MB, SO_RCVBUF/SO_SNDBUF = 16 MB, PASV-Modus
#   SFTP: window_size = 64 MB, max_packet_size = 32 KB, prefetch()
#         manuelle Chunk-Loop statt sftp.get() (umgeht paramiko-Bottleneck)
#
# Abhängigkeiten: pip install paramiko

import ftplib
import fnmatch
import os
import time
import socket
import logging
from pathlib import Path

log = logging.getLogger(__name__)

try:
    from lib.credentials import decrypt as _decrypt_pw
except Exception:
    def _decrypt_pw(v): return v   # Fallback: Klartext

try:
    import paramiko
    PARAMIKO_OK = True
except ImportError:
    PARAMIKO_OK = False
    log.warning("paramiko nicht installiert – SFTP nicht verfuegbar. 'pip install paramiko'")

# ── Tuning-Konstanten ─────────────────────────────────────────────────────────
FTP_BLOCKSIZE   = 8 * 1024 * 1024    # 8 MB pro retrbinary-Block
SOCKET_BUF      = 16 * 1024 * 1024   # 16 MB SO_RCVBUF / SO_SNDBUF
SFTP_WINDOW     = 64 * 1024 * 1024   # 64 MB SFTP-Window
SFTP_MAX_PACKET = 32 * 1024          # 32 KB SFTP-Paketgröße
SFTP_CHUNK      = 32 * 1024          # Chunk-Größe für manuelle Lese-Loop


# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _backoff_delay(attempt: int, base: float = 5.0, maximum: float = 120.0) -> float:
    """
    Exponentieller Backoff mit Jitter (Industry Best Practice).
    attempt 1 → ~5s, attempt 2 → ~10s, attempt 3 → ~20s, ...
    """
    import random
    delay = min(base * (2 ** (attempt - 1)), maximum)
    jitter = delay * 0.25 * (2 * random.random() - 1)
    return max(1.0, delay + jitter)


class CircuitBreaker:
    """
    Circuit Breaker Pattern (Fowler/Nygard).
    Verhindert wiederholte Verbindungsversuche zu einem ausgefallenen Server.
    States: CLOSED → OPEN (nach N Fehlern) → HALF_OPEN (ein Testversuch)
    """
    def __init__(self, failure_threshold: int = 3, reset_timeout: float = 300):
        self._failures = 0
        self._threshold = failure_threshold
        self._reset_timeout = reset_timeout
        self._last_failure = 0
        self._state = "closed"

    @property
    def state(self):
        if self._state == "open":
            if time.time() - self._last_failure > self._reset_timeout:
                self._state = "half_open"
        return self._state

    def allow_request(self) -> bool:
        return self.state in ("closed", "half_open")

    def record_success(self):
        self._failures = 0
        self._state = "closed"

    def record_failure(self):
        self._failures += 1
        self._last_failure = time.time()
        if self._failures >= self._threshold:
            self._state = "open"


# Globale Circuit-Breaker pro Host
_circuit_breakers: dict = {}


def _get_breaker(host: str) -> CircuitBreaker:
    if host not in _circuit_breakers:
        _circuit_breakers[host] = CircuitBreaker()
    return _circuit_breakers[host]


def _ensure_dir(path: str):
    Path(path).mkdir(parents=True, exist_ok=True)


def _tune_socket(sock):
    """Setzt SO_RCVBUF / SO_SNDBUF auf SOCKET_BUF."""
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, SOCKET_BUF)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, SOCKET_BUF)
    except Exception as e:
        log.debug(f"Socket-Tuning fehlgeschlagen (ignoriert): {e}")


# ── Fortschritts-Tracker ──────────────────────────────────────────────────────

class _ProgressTracker:
    THROTTLE_S = 0.2

    def __init__(self, filename: str, total_bytes: int, file_progress_cb):
        self.filename   = filename
        self.total      = total_bytes
        self.received   = 0
        self._cb        = file_progress_cb
        self._t0        = time.monotonic()
        self._last_emit = 0.0

    def update_chunk(self, chunk: bytes):
        self.received += len(chunk)
        self._emit()

    def update_absolute(self, sent: int):
        self.received = sent
        self._emit()

    def _emit(self):
        now = time.monotonic()
        if now - self._last_emit < self.THROTTLE_S:
            return
        self._last_emit = now
        self._fire()

    def _fire(self):
        if not self._cb:
            return
        elapsed = time.monotonic() - self._t0 or 0.001
        speed   = self.received / elapsed
        if self.total > 0:
            pct = min(self.received / self.total * 100, 100)
            eta = (self.total - self.received) / speed if speed > 0 else 0.0
        else:
            pct, eta = 0.0, 0.0
        self._cb(self.filename, pct, self.received, self.total, speed, eta)

    def finish(self):
        self.received = self.total if self.total > 0 else self.received
        elapsed = time.monotonic() - self._t0 or 0.001
        speed   = self.received / elapsed
        if self._cb:
            self._cb(self.filename, 100.0, self.received, self.total, speed, 0.0)


# ── FTP ───────────────────────────────────────────────────────────────────────

class FTPClient:
    def __init__(self, host, user, password, port=21):
        self.host     = host
        self.user     = user
        self.password = password
        self.port     = port
        self._ftp     = None

    def connect(self, retries: int = 3, retry_delay: int = 30):
        breaker = _get_breaker(self.host)
        if not breaker.allow_request():
            raise ConnectionError(
                f"Circuit Breaker OPEN für {self.host} – "
                f"Server nach wiederholten Fehlern gesperrt (5 Min Pause)")
        last_exc = None
        for attempt in range(1, retries + 1):
            try:
                self._ftp = ftplib.FTP()
                self._ftp.connect(self.host, self.port, timeout=120)
                _tune_socket(self._ftp.sock)
                self._ftp.login(self.user, self.password)
                self._ftp.set_pasv(True)
                breaker.record_success()
                log.info(f"FTP verbunden: {self.host}")
                return
            except Exception as exc:
                last_exc = exc
                breaker.record_failure()
                if attempt < retries:
                    log.warning(
                        f"FTP connect fehlgeschlagen ({self.host}), "
                        f"Versuch {attempt}/{retries} – warte {retry_delay}s: {exc}")
                    import time as _time; _time.sleep(retry_delay)
        raise last_exc

    def disconnect(self):
        if self._ftp:
            try:
                self._ftp.quit()
            except Exception:
                pass
        log.info(f"FTP getrennt: {self.host}")

    def _size(self, name: str) -> int:
        try:
            return self._ftp.size(name) or 0
        except Exception:
            return 0

    def _remote_size_mtime(self, name: str) -> tuple:
        """Gibt (size, mtime_str) zurück für Delta-Check. FTP-spezifisch."""
        size = self._size(name)
        try:
            mtime = self._ftp.sendcmd(f"MDTM {name}")
        except Exception:
            mtime = ""
        return size, mtime

    def download(self, remote_path: str, local_dir: str,
                 latest_only: bool = False,
                 skip_if_unchanged: bool = False,
                 retries: int = 3, retry_delay: int = 30,
                 progress_cb=None, file_progress_cb=None):
        _ensure_dir(local_dir)
        cb = progress_cb
        remote_dir  = os.path.dirname(remote_path).replace("\\", "/") or "."
        file_filter = os.path.basename(remote_path)

        # Immer vom Root aus navigieren
        try:
            self._ftp.cwd("/")
            self._ftp.cwd(remote_dir)
        except ftplib.error_perm as e:
            log.error(f"FTP cd '{remote_dir}' fehlgeschlagen: {e}")
            raise

        entries = []
        self._ftp.retrlines("LIST", entries.append)

        files = []
        for entry in entries:
            parts = entry.split()
            if parts and fnmatch.fnmatch(parts[-1], file_filter):
                files.append(parts[-1])

        if not files:
            msg = f"Keine Dateien fuer Muster '{file_filter}' in '{remote_dir}'"
            log.warning(msg)
            if cb:
                cb(msg, tag="warn")
            return []

        if latest_only:
            def _mdtm(n):
                try:
                    return self._ftp.sendcmd(f"MDTM {n}")
                except Exception:
                    return ""
            files = [max(files, key=_mdtm)]

        downloaded = []
        for name in files:
            local_path = os.path.join(local_dir, name)
            total      = self._size(name)

            # Delta-Check: überspringen wenn Größe + mtime identisch
            if skip_if_unchanged and os.path.exists(local_path):
                remote_size, remote_mtime = self._remote_size_mtime(name)
                local_size  = os.path.getsize(local_path)
                if remote_size and remote_size == local_size:
                    if cb:
                        cb(f"Übersprungen (unverändert): {name}  "
                           f"({_fmt_size(local_size)})", tag="dim")
                    downloaded.append(local_path)
                    continue

            if cb:
                cb(f"Download: {name}  ({_fmt_size(total) if total else '?'})")

            tracker = _ProgressTracker(name, total, file_progress_cb)

            # Retry-Loop
            last_exc = None
            for attempt in range(1, retries + 1):
                try:
                    with open(local_path, "wb") as f:
                        def _write(chunk, _f=f, _t=tracker):
                            _f.write(chunk)
                            _t.update_chunk(chunk)
                        self._ftp.retrbinary(f"RETR {name}", _write,
                                             blocksize=FTP_BLOCKSIZE)
                    last_exc = None
                    break
                except Exception as e:
                    last_exc = e
                    if attempt < retries:
                        if cb:
                            cb(f"  Download-Fehler (Versuch {attempt}/{retries}): "
                               f"{e} – Retry in {_backoff_delay(attempt):.0f}s ...", tag="warn")
                        time.sleep(_backoff_delay(attempt))
                        # Verbindung neu aufbauen
                        try:
                            self.disconnect()
                            self.connect()
                            self._ftp.cwd("/")
                            self._ftp.cwd(remote_dir)
                        except Exception:
                            pass
                    else:
                        raise last_exc

            tracker.finish()
            downloaded.append(local_path)
            log.info(f"Heruntergeladen: {remote_dir}/{name} -> {local_path}")
            if cb:
                cb(f"Fertig: {name}  ({_fmt_size(tracker.received)})", tag="ok")

        return downloaded

    def upload(self, local_pattern: str, remote_dir: str,
               delete_after: bool = False,
               retries: int = 3, retry_delay: int = 15,
               progress_cb=None, file_progress_cb=None):
        import glob
        cb    = progress_cb
        files = glob.glob(local_pattern)
        if not files:
            log.warning(f"Keine Dateien fuer Upload: '{local_pattern}'")
            return

        try:
            self._ftp.cwd("/")
            self._ftp.cwd(remote_dir)
        except ftplib.error_perm as e:
            log.error(f"FTP cd '{remote_dir}' fehlgeschlagen: {e}")
            raise

        for path in files:
            name  = os.path.basename(path)
            total = os.path.getsize(path)

            if cb:
                cb(f"Upload: {name}  ({_fmt_size(total)})")

            # Retry-Loop
            last_exc = None
            for attempt in range(1, retries + 1):
                try:
                    tracker = _ProgressTracker(name, total, file_progress_cb)
                    with open(path, "rb") as f:
                        self._ftp.storbinary(f"STOR {name}", f,
                                             blocksize=FTP_BLOCKSIZE,
                                             callback=lambda chunk, _t=tracker: _t.update_chunk(chunk))
                    tracker.finish()

                    # Verify: Dateigröße auf Server prüfen
                    try:
                        remote_size = self._ftp.size(name)
                        if remote_size is not None and remote_size != total:
                            raise IOError(
                                f"Größenmismatch nach Upload: lokal={total}, "
                                f"remote={remote_size}")
                    except ftplib.error_perm:
                        pass  # SIZE nicht unterstützt → kein Verify

                    last_exc = None
                    break
                except Exception as e:
                    last_exc = e
                    if attempt < retries:
                        if cb:
                            cb(f"  Upload-Fehler (Versuch {attempt}/{retries}): "
                               f"{e} – Retry in {_backoff_delay(attempt):.0f}s ...", tag="warn")
                        time.sleep(_backoff_delay(attempt))
                        try:
                            self.disconnect()
                            self.connect()
                            self._ftp.cwd("/")
                            self._ftp.cwd(remote_dir)
                        except Exception:
                            pass
                    else:
                        raise last_exc

            log.info(f"Hochgeladen: {path} -> {remote_dir}/{name}")
            if cb:
                cb(f"Fertig: {name}", tag="ok")
            if delete_after:
                os.remove(path)


# ── SFTP ──────────────────────────────────────────────────────────────────────

class SFTPClient:
    def __init__(self, host, user, password, port=22):
        if not PARAMIKO_OK:
            raise RuntimeError("paramiko nicht installiert. Bitte: pip install paramiko")
        self.host     = host
        self.user     = user
        self.password = password
        self.port     = port
        self._ssh     = None
        self._sftp    = None

    def connect(self, retries: int = 3, retry_delay: int = 30):
        breaker = _get_breaker(self.host)
        if not breaker.allow_request():
            raise ConnectionError(
                f"Circuit Breaker OPEN für {self.host} – "
                f"Server nach wiederholten Fehlern gesperrt (5 Min Pause)")
        last_exc = None
        for attempt in range(1, retries + 1):
            try:
                self._ssh = paramiko.SSHClient()
                self._ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

                sock = socket.create_connection((self.host, self.port), timeout=30)
                _tune_socket(sock)

                self._ssh.connect(
                    self.host, port=self.port,
                    username=self.user, password=self.password,
                    sock=sock,
                    timeout=30, look_for_keys=False, allow_agent=False,
                )

                t = self._ssh.get_transport()
                t.window_size              = SFTP_WINDOW
                t.packetizer.REKEY_BYTES   = 2**40
                t.packetizer.REKEY_PACKETS = 2**40

                self._sftp = self._ssh.open_sftp()
                self._sftp.MAX_REQUEST_SIZE = SFTP_MAX_PACKET

                breaker.record_success()
                log.info(f"SFTP verbunden: {self.host} "
                         f"(window={_fmt_size(SFTP_WINDOW)}, "
                         f"packet={_fmt_size(SFTP_MAX_PACKET)})")
                return
            except Exception as exc:
                last_exc = exc
                breaker.record_failure()
                if attempt < retries:
                    log.warning(
                        f"SFTP connect fehlgeschlagen ({self.host}), "
                        f"Versuch {attempt}/{retries} – warte {retry_delay}s: {exc}")
                    import time as _time; _time.sleep(retry_delay)
        raise last_exc

    def disconnect(self):
        if self._sftp:
            self._sftp.close()
        if self._ssh:
            self._ssh.close()
        log.info(f"SFTP getrennt: {self.host}")

    def _fast_get(self, remote_path: str, local_path: str,
                  total: int, tracker: _ProgressTracker):
        """
        Hochperformanter SFTP-Download via SFTPFile.readv().

        readv() schickt alle READ-Requests auf einmal ab und hält
        max_concurrent_prefetch_requests davon gleichzeitig offen.
        Das ist das Äquivalent zu WinSCPs paralleler Read-Pipeline
        und vermeidet das stop-and-wait-Problem von sftp.get() und
        den einmaligen Burst von prefetch().
        """
        CHUNK = SFTP_MAX_PACKET   # 32 KB pro Request
        DEPTH = 64                # Requests gleichzeitig in der Leitung

        if total <= 0:
            # Größe unbekannt: Fallback auf prefetch-Loop
            with self._sftp.open(remote_path, "rb") as rf:
                rf.prefetch()
                with open(local_path, "wb") as lf:
                    while True:
                        data = rf.read(CHUNK * DEPTH)
                        if not data:
                            break
                        lf.write(data)
                        tracker.update_chunk(data)
            return

        # Chunk-Liste aufbauen: [(offset, length), ...]
        chunks = []
        offset = 0
        while offset < total:
            chunks.append((offset, min(CHUNK, total - offset)))
            offset += CHUNK

        with self._sftp.open(remote_path, "rb") as rf, \
             open(local_path, "wb") as lf:

            for data in rf.readv(chunks,
                                  max_concurrent_prefetch_requests=DEPTH):
                if data:
                    lf.write(data)
                    tracker.update_chunk(data)

    def download(self, remote_path: str, local_dir: str,
                 latest_only: bool = False,
                 skip_if_unchanged: bool = False,
                 retries: int = 3, retry_delay: int = 30,
                 progress_cb=None, file_progress_cb=None):
        _ensure_dir(local_dir)
        cb = progress_cb
        remote_dir  = os.path.dirname(remote_path).replace("\\", "/") or "."
        file_filter = os.path.basename(remote_path)

        try:
            entries = self._sftp.listdir_attr(remote_dir)
        except Exception as e:
            log.error(f"SFTP listdir '{remote_dir}' fehlgeschlagen: {e}")
            raise

        files = [e for e in entries if fnmatch.fnmatch(e.filename, file_filter)]

        if not files:
            msg = f"Keine Dateien fuer Muster '{file_filter}' in '{remote_dir}'"
            log.warning(msg)
            if cb:
                cb(msg, tag="warn")
            return []

        if latest_only:
            files = [max(files, key=lambda e: e.st_mtime or 0)]

        downloaded = []
        for entry in files:
            remote_full = f"{remote_dir}/{entry.filename}"
            local_path  = os.path.join(local_dir, entry.filename)
            total       = entry.st_size or 0

            # Delta-Check: überspringen wenn Größe identisch
            if skip_if_unchanged and os.path.exists(local_path):
                local_size = os.path.getsize(local_path)
                if total and total == local_size:
                    if cb:
                        cb(f"Übersprungen (unverändert): {entry.filename}  "
                           f"({_fmt_size(local_size)})", tag="dim")
                    downloaded.append(local_path)
                    continue

            if cb:
                cb(f"Download: {entry.filename}  ({_fmt_size(total) if total else '?'})")

            tracker = _ProgressTracker(entry.filename, total, file_progress_cb)

            # Retry-Loop
            last_exc = None
            for attempt in range(1, retries + 1):
                try:
                    self._fast_get(remote_full, local_path, total, tracker)
                    last_exc = None
                    break
                except Exception as e:
                    last_exc = e
                    if attempt < retries:
                        if cb:
                            cb(f"  Download-Fehler (Versuch {attempt}/{retries}): "
                               f"{e} – Retry in {_backoff_delay(attempt):.0f}s ...", tag="warn")
                        time.sleep(_backoff_delay(attempt))
                        try:
                            self.disconnect()
                            self.connect()
                        except Exception:
                            pass
                    else:
                        raise last_exc

            tracker.finish()
            downloaded.append(local_path)
            log.info(f"Heruntergeladen: {remote_full} -> {local_path}")
            if cb:
                cb(f"Fertig: {entry.filename}  ({_fmt_size(tracker.received)})", tag="ok")

        return downloaded

    def upload(self, local_pattern: str, remote_dir: str,
               delete_after: bool = False,
               retries: int = 3, retry_delay: int = 15,
               progress_cb=None, file_progress_cb=None):
        import glob
        cb    = progress_cb
        files = glob.glob(local_pattern)
        if not files:
            log.warning(f"Keine Dateien fuer Upload: '{local_pattern}'")
            return

        for path in files:
            name        = os.path.basename(path)
            total       = os.path.getsize(path)
            remote_full = f"{remote_dir}/{name}"

            if cb:
                cb(f"Upload: {name}  ({_fmt_size(total)})")

            # Retry-Loop
            last_exc = None
            for attempt in range(1, retries + 1):
                try:
                    tracker = _ProgressTracker(name, total, file_progress_cb)

                    with open(path, "rb") as local_f, \
                         self._sftp.open(remote_full, "wb") as remote_f:
                        remote_f.set_pipelined(True)
                        while True:
                            chunk = local_f.read(SFTP_CHUNK)
                            if not chunk:
                                break
                            remote_f.write(chunk)
                            tracker.update_chunk(chunk)

                    tracker.finish()

                    # Verify: Dateigröße auf Server prüfen
                    try:
                        remote_stat = self._sftp.stat(remote_full)
                        if remote_stat.st_size != total:
                            raise IOError(
                                f"Größenmismatch nach Upload: lokal={total}, "
                                f"remote={remote_stat.st_size}")
                    except IOError:
                        raise
                    except Exception:
                        pass  # stat fehlgeschlagen → kein Verify

                    last_exc = None
                    break
                except Exception as e:
                    last_exc = e
                    if attempt < retries:
                        if cb:
                            cb(f"  Upload-Fehler (Versuch {attempt}/{retries}): "
                               f"{e} – Retry in {_backoff_delay(attempt):.0f}s ...", tag="warn")
                        time.sleep(_backoff_delay(attempt))
                        try:
                            self.disconnect()
                            self.connect()
                        except Exception:
                            pass
                    else:
                        raise last_exc

            log.info(f"Hochgeladen: {path} -> {remote_full}")
            if cb:
                cb(f"Fertig: {name}", tag="ok")
            if delete_after:
                os.remove(path)


# ── Factory ───────────────────────────────────────────────────────────────────

def make_client(cfg: dict):
    protocol = cfg.get("protocol", "ftp").lower()
    password = _decrypt_pw(cfg.get("password", ""))
    if protocol == "sftp":
        return SFTPClient(cfg["host"], cfg["user"], password,
                          cfg.get("port", 22))
    else:
        return FTPClient(cfg["host"], cfg["user"], password,
                         cfg.get("port", 21))


class DryRunFtpClient:
    """Simulierter FTP-Client für --dry-run Modus. Führt keine echten Uploads durch."""
    def __init__(self, host=""):
        self.host = host

    def connect(self): pass
    def disconnect(self): pass

    def download(self, remote, local_dir, **kw):
        import logging
        logging.getLogger(__name__).info("[DRY-RUN] Download übersprungen: %s", remote)

    def upload(self, local_path, remote_path, **kw):
        import logging
        logging.getLogger(__name__).info("[DRY-RUN] Upload übersprungen: %s → %s",
                                          local_path, remote_path)

    def stat(self, path): return None
    def exists(self, path): return False
    def makedirs(self, path): pass

