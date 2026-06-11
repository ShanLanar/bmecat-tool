# lib/config_migration.py – Config-Versioning und Auto-Migration
#
# Wenn config.py neue Schlüssel bekommt (z.B. BFSG, AI_ENRICHMENT),
# wird config_user.json beim nächsten Start automatisch um die Defaults ergänzt.
# Keine manuellen Eingriffe nötig, kein Startup-Crash wegen fehlender Keys.

import os
import json
import logging
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

# Aktuelle Config-Version — erhöhen wenn neue Pflichtfelder hinzukommen
CONFIG_VERSION = 5

# Defaults für alle bekannten optionalen Sektionen
# Werden in config_user.json eingetragen wenn sie fehlen
SECTION_DEFAULTS = {
    "NOTIFICATION": {
        "enabled": False, "smtp_host": "", "smtp_port": 587,
        "smtp_user": "", "smtp_pass": "", "smtp_tls": True,
        "from": "", "to": [], "on_success": False,
    },
    "ARTICLE_THRESHOLDS": {
        "bueroring_merged.xml": 20000,
        "soft-carrier_merge.xml": 60000,
        "arbeitsschutz.xml": 5000,
        "werkstatt.xml": 10000,
        "werkzeugtechnik.xml": 40000,
    },
    "BFSG": {
        "enabled": False,
        "alt_text": True,
        "clean_desc_short": True,
        "remove_html": True,
        "foreign_keywords": False,
    },
    "AI_ENRICHMENT": {
        "enabled": False,
        "model": "claude-haiku-4-5-20251001",
        "max_articles": 200,
        "min_desc_len": 20,
        "tasks": {
            "improve_desc_short": True,
            "improve_desc_long": True,
            "normalize_mfr": True,
            "suggest_keywords": False,
        },
    },
    "ATP_ARCHIVE_DIR": r"\\obs.abe-brands.de\OBS\data\VERFUG\Archiv",
}


def migrate(user_config_path: str, progress_cb=None) -> bool:
    """
    Liest config_user.json, ergänzt fehlende Sektionen, schreibt zurück.

    Returns:
        True wenn Änderungen vorgenommen wurden.
    """
    p = progress_cb or (lambda m, **kw: None)

    if not os.path.exists(user_config_path):
        return False

    try:
        with open(user_config_path, "r", encoding="utf-8") as f:
            user_cfg = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        p(f"Config-Migration: config_user.json nicht lesbar: {e}", tag="warn")
        return False

    current_version = user_cfg.get("__version__", 0)
    if current_version >= CONFIG_VERSION:
        return False

    changed = False

    for section, defaults in SECTION_DEFAULTS.items():
        if section not in user_cfg:
            user_cfg[section] = defaults
            p(f"Config-Migration: Sektion '{section}' ergänzt (neu in v{CONFIG_VERSION})",
              tag="dim")
            changed = True
        elif isinstance(defaults, dict) and isinstance(user_cfg[section], dict):
            # Fehlende Unterschlüssel ergänzen
            for key, val in defaults.items():
                if key not in user_cfg[section]:
                    user_cfg[section][key] = val
                    changed = True

    user_cfg["__version__"] = CONFIG_VERSION

    if changed:
        # Backup vor Überschreiben
        backup = user_config_path + ".bak"
        try:
            import shutil
            shutil.copy2(user_config_path, backup)
        except Exception:
            pass

        p_path = Path(user_config_path)
        with tempfile.NamedTemporaryFile("w", dir=p_path.parent, delete=False,
                                         suffix=".tmp", encoding="utf-8") as f:
            json.dump(user_cfg, f, ensure_ascii=False, indent=2)
            tmp = f.name
        os.replace(tmp, user_config_path)
        p(f"Config-Migration: config_user.json auf v{CONFIG_VERSION} aktualisiert.",
          tag="ok")

    return changed
