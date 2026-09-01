# lib/credentials.py – Verschlüsselte Zugangsdaten
#
# Beim ersten Start wird ein Fernet-Schlüssel in BASE_DIR/.fernet.key erzeugt.
# Passwörter in supplier_config.yaml können dann als "enc:BASE64..." gespeichert
# werden.  Klartext-Passwörter bleiben weiterhin funktionsfähig (Fallback).
#
# Verschlüsseln:  python -m lib.credentials encrypt "meinPasswort"
# Entschlüsseln:  python -m lib.credentials decrypt "enc:..."

import os
import sys
import logging

log = logging.getLogger(__name__)

_KEY_FILE = ".fernet.key"
_PREFIX   = "enc:"

_fernet = None   # gecachte Instanz


def _get_fernet():
    global _fernet
    if _fernet is not None:
        return _fernet
    try:
        from cryptography.fernet import Fernet
        import config as _cfg
        key_path = os.path.join(_cfg.BASE_DIR, _KEY_FILE)
        if os.path.exists(key_path):
            key = open(key_path, "rb").read().strip()
        else:
            key = Fernet.generate_key()
            with open(key_path, "wb") as f:
                f.write(key)
            # Datei für andere Benutzer unsichtbar machen (Windows: versteckt)
            try:
                import ctypes
                ctypes.windll.kernel32.SetFileAttributesW(key_path, 2)  # HIDDEN
            except Exception:
                pass
            log.info(f"Neuer Verschlüsselungsschlüssel erzeugt: {key_path}")
        _fernet = Fernet(key)
        return _fernet
    except Exception as e:
        log.warning(f"Verschlüsselung nicht verfügbar: {e}")
        return None


def decrypt(value: str) -> str:
    """
    Entschlüsselt einen 'enc:...'-Wert.
    Klartext-Werte werden unverändert zurückgegeben.
    """
    if not isinstance(value, str) or not value.startswith(_PREFIX):
        return value
    f = _get_fernet()
    if f is None:
        log.error("Passwort verschlüsselt aber cryptography nicht verfügbar")
        return ""
    try:
        token = value[len(_PREFIX):]
        return f.decrypt(token.encode()).decode()
    except Exception as e:
        log.error(f"Passwort konnte nicht entschlüsselt werden: {e}")
        return ""


def encrypt(plaintext: str) -> str:
    """Verschlüsselt einen Klartext-Wert, gibt 'enc:...' zurück."""
    f = _get_fernet()
    if f is None:
        raise RuntimeError("cryptography-Bibliothek nicht verfügbar")
    token = f.encrypt(plaintext.encode()).decode()
    return f"{_PREFIX}{token}"


def resolve_yaml_passwords(cfg: dict) -> dict:
    """
    Geht rekursiv durch ein Config-Dict und entschlüsselt alle
    Werte die mit 'enc:' beginnen.  Gibt eine Kopie zurück.
    """
    if isinstance(cfg, dict):
        return {k: resolve_yaml_passwords(v) for k, v in cfg.items()}
    if isinstance(cfg, list):
        return [resolve_yaml_passwords(v) for v in cfg]
    if isinstance(cfg, str) and cfg.startswith(_PREFIX):
        return decrypt(cfg)
    return cfg


if __name__ == "__main__":
    """CLI-Hilfsprogramm:
       python -m lib.credentials encrypt "passwort"
       python -m lib.credentials decrypt "enc:..."
    """
    if len(sys.argv) != 3:
        print("Verwendung: python -m lib.credentials encrypt|decrypt WERT")
        sys.exit(1)
    cmd, val = sys.argv[1], sys.argv[2]
    if cmd == "encrypt":
        print(encrypt(val))
    elif cmd == "decrypt":
        print(decrypt(val))
    else:
        print("Unbekannter Befehl:", cmd)
        sys.exit(1)
