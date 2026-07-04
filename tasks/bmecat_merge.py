# tasks/bmecat_merge.py – BMEcat-Merge-Task für GUI
import os
import logging
from config import DIRS, MERGE

log = logging.getLogger(__name__)


def _paths():
    base = DIRS["in_bme"]
    return (
        os.path.join(base, MERGE["udx_src"]),
        os.path.join(base, MERGE["basis_src"]),
        os.path.join(base, MERGE["out_file"]),
    )


def _ensure_files(udx_src, basis_src, p, fp):
    """
    Prüft ob die Quelldateien vorhanden sind.
    Fehlendes wird gezielt via download_sources() nachgeladen –
    ohne Bilder, Bestand oder Dokumente mitzuladen.
    """
    missing = []
    if not os.path.exists(udx_src):
        missing.append(os.path.basename(udx_src))
    if not os.path.exists(basis_src):
        missing.append(os.path.basename(basis_src))

    if not missing:
        return

    p(f"Quelldateien fehlen ({', '.join(missing)}) – lade BMEcat-ZIPs nach ...")
    from tasks.bueroring import download_sources
    download_sources(progress_cb=p, file_progress_cb=fp)

    # Nochmals prüfen
    still = [os.path.basename(f) for f in [udx_src, basis_src]
             if not os.path.exists(f)]
    if still:
        raise FileNotFoundError(
            f"Quelldateien nach Download immer noch nicht gefunden: "
            + ", ".join(still))


def run(progress_cb=None, file_progress_cb=None):
    from lib.bmecat_merge import merge, _load_keywords, inject_keywords
    import config as _cfg
    import json
    p  = progress_cb      or (lambda m, **kw: None)
    fp = file_progress_cb or None

    udx_src, basis_src, out_file = _paths()

    p("┌─ BMEcat-Merge ─────────────────────────────────────────────")
    p(f"│  Quelle 1 (ABE + ECLASS):  {os.path.basename(udx_src)}")
    p(f"│  Quelle 2 (Hauptkatalog):  {os.path.basename(basis_src)}")
    p(f"│  ↓ Ausgabe:                {os.path.basename(out_file)}")
    p("└────────────────────────────────────────────────────────────")

    # Fehlende Quelldateien automatisch nachladen
    _ensure_files(udx_src, basis_src, p, fp)

    # Merge-Skip: Input-Hashes vergleichen
    kw_file = os.path.join(_cfg.BASE_DIR, MERGE.get("keywords", "keywords_exploded.csv"))
    hash_file = os.path.join(DIRS.get("logs", "."), "merge_hashes.json")
    skip_merge = False
    try:
        from lib.utils import file_hash
        current_hashes = {}
        fname_csv   = os.path.join(_cfg.BASE_DIR, "fname_renames.csv")
        fvalue_csv  = os.path.join(_cfg.BASE_DIR, "fvalue_renames.csv")
        for label, path in [
            ("udx",            udx_src),
            ("basis",          basis_src),
            ("kw",             kw_file),
            ("fname_renames",  fname_csv),
            ("fvalue_renames", fvalue_csv),
        ]:
            if os.path.exists(path):
                current_hashes[label] = file_hash(path)

        if os.path.exists(hash_file) and os.path.exists(out_file):
            with open(hash_file, "r") as hf:
                prev_hashes = json.load(hf)
            if current_hashes == prev_hashes:
                out_size = os.path.getsize(out_file)
                p(f"Merge-Skip: Input-Dateien unverändert, "
                  f"nutze bestehende {os.path.basename(out_file)} "
                  f"({out_size / 1024 / 1024:.0f} MB).", tag="ok")
                skip_merge = True
    except Exception as e:
        log.debug("Merge-Hash-Vergleich übersprungen: %s", e)

    if not skip_merge:
        stats = merge(udx_src, basis_src, out_file, progress_cb=p)

        # Keywords injizieren
        if os.path.exists(kw_file):
            keywords = _load_keywords(kw_file, progress_cb=p)
            n_changed = inject_keywords(out_file, keywords, progress_cb=p)
            stats["keywords_injected"] = n_changed
        else:
            p(f"Keywords-Datei nicht gefunden: {kw_file}", tag="warn")

        # XML-Sanitize: nackte Ampersands reparieren (Sicherheitsnetz)
        from lib.bmecat_merge import sanitize_xml
        n_fixes = sanitize_xml(out_file, progress_cb=p)
        stats["ampersand_fixes"] = n_fixes

        # FNAME/FVALUE-Transformationen
        from lib.fname_transforms import apply_fname_transforms, report_fname_consistency
        import config as _cfg
        ft_stats = apply_fname_transforms(out_file, _cfg.BASE_DIR, progress_cb=p)
        stats["fname_transforms"] = ft_stats

        # FNAME-Konsistenz-Report: findet FNAME-Varianten die noch nicht
        # über fname_renames.csv vereinheitlicht sind
        try:
            report_path = report_fname_consistency(
                out_file, _cfg.BASE_DIR, DIRS.get("logs", "logs"), progress_cb=p)
            if report_path:
                stats["fname_consistency_report"] = report_path
        except Exception as e:
            p(f"FNAME-Konsistenz-Report übersprungen: {e}", tag="dim")

        # Regelbasierte Anreicherung (Langbeschreibung, Hersteller-Fallbacks)
        from lib.article_enrichment import enrich
        enrich_stats = enrich(out_file, progress_cb=p)
        stats["enrichment"] = enrich_stats

        # BFSG-Barrierefreiheits-Bereinigung (optional, per config.py steuerbar)
        try:
            from lib.bfsg_cleanup import run_bfsg_cleanup
            bfsg_stats = run_bfsg_cleanup(out_file, progress_cb=p)
            if bfsg_stats:
                stats["bfsg"] = bfsg_stats
        except Exception as e:
            p(f"BFSG-Cleanup übersprungen: {e}", tag="dim")

        # Hashes speichern nach erfolgreichem Merge
        try:
            from pathlib import Path
            Path(os.path.dirname(hash_file)).mkdir(parents=True, exist_ok=True)
            with open(hash_file, "w") as hf:
                json.dump(current_hashes, hf)
        except Exception:
            pass
    else:
        stats = {"skipped": True}

    # Deduplizierung (immer, auch bei Skip)
    from tasks.others import dedup_xmls
    dedup_result = dedup_xmls([out_file], progress_cb=p, file_progress_cb=fp)
    stats["dedup"] = dedup_result

    # SUPPLIER_AID-Pflichtprüfung (immer, auch bei Skip).
    # Läuft nach dem Skip-Pfad: XML könnte aus einem älteren Lauf stammen,
    # bevor die Validierung eingeführt wurde, oder der Merge hat einen Bug.
    # Dieser Schritt ist schnell (ein Regex-Pass, kein volles Enrichment).
    if os.path.exists(out_file):
        try:
            from lib.dead_letter import quarantine_no_aid
            removed = quarantine_no_aid(out_file, progress_cb=p)
            stats["quarantined_no_aid"] = removed
        except Exception as e:
            p(f"SUPPLIER_AID-Prüfung übersprungen: {e}", tag="dim")

    # Artikelanzahl-Plausibilitätsprüfung (blockiert Upload bei zu wenig Artikeln)
    try:
        import config as _cfg
        thresholds = getattr(_cfg, "ARTICLE_THRESHOLDS", {})
        fname = os.path.basename(out_file)
        min_arts = thresholds.get(fname, 0)
        if min_arts > 0:
            from lib.utils import iter_articles
            n_arts = sum(1 for _ in iter_articles(out_file))
            stats["article_count"] = n_arts
            if n_arts < min_arts:
                p(f"⛔ ARTIKELANZAHL ZU NIEDRIG: {fname} hat {n_arts} Artikel "
                  f"(Minimum: {min_arts}). Upload abgebrochen!", tag="warn")
                stats["upload_blocked"] = True
                return stats
            else:
                p(f"✅ Artikelanzahl OK: {n_arts} ≥ {min_arts}", tag="ok")
    except Exception as e:
        p(f"Artikelanzahl-Check übersprungen: {e}", tag="dim")

    return stats

