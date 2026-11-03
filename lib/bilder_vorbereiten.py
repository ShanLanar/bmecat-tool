# lib/bilder_vorbereiten.py – Bilder für einen Lieferanten vorbereiten
#
# Für frei importierte Kataloge (z.B. W.Söhngen GmbH = SOG), deren Bilder
# getrennt geliefert werden (ZIP/Ordner, oft viele GB): aus einem Quellordner
# werden NUR die Dateien übernommen, die ein Artikel des Lieferanten in der
# Artikel-DB als Bild (MIME_SOURCE) referenziert. Sie landen als JPG mit
# Präfix im Dateinamen (SOG12345.jpg) in DIRS["in"], von wo der Task
# "Bilder-Upload (Allago + OfficeXL)" sie per Delta hochlädt.
#
# Zuordnung über den Dateinamen ohne Endung (Stamm): referenziert die DB
# "12345.png" und die Lieferung enthält "12345.tif", passt das zusammen –
# die Datei wird nach JPG konvertiert (Pillow; Transparenz → weiß) und die
# Referenz in der DB auf "12345.jpg" / image/jpeg umgestellt, damit der
# Export denselben Namen schreibt wie die hochgeladene Datei.
#
# Nicht referenzierte Dateien werden übersprungen (Log zählt sie), Artikel
# ohne Bild in der Lieferung landen in logs/bilder_vorbereiten_fehlend_*.csv.

import csv
import os
import shutil
from datetime import datetime
from typing import Callable

_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff", ".webp", ".bmp"}
_JPEG_QUALITY = 90


def _stem(name: str, prefix_lower: str) -> str:
    """Dateiname → Stamm in Kleinbuchstaben ohne Pfad, Endung und Präfix."""
    bn = os.path.basename(name.replace("\\", "/")).strip()
    stem = os.path.splitext(bn)[0].lower()
    if prefix_lower and stem.startswith(prefix_lower) and len(stem) > len(prefix_lower):
        stem = stem[len(prefix_lower):]
    return stem


def load_referenced_images(con, supplier_name: str, prefix: str) -> dict:
    """
    {stamm: {"name": Originalname aus DB (ohne Präfix), "articles": [product_id, ...],
             "mime_ids": [id, ...]}}
    für alle Bild-MIMEs aktiver Artikel des Lieferanten.
    """
    rows = con.execute("""
        SELECT m.id AS mime_id, a.product_id, m.mime_source, m.mime_type
        FROM article_mimes m
        JOIN articles a ON a.id = m.article_id
        JOIN suppliers s ON s.id = a.supplier_id
        WHERE s.supplier_name = ? AND a.active = 1 AND m.mime_source <> ''
    """, (supplier_name,)).fetchall()
    wanted: dict = {}
    pre = (prefix or "").lower()
    for r in rows:
        src = (r["mime_source"] or "").strip()
        mt  = (r["mime_type"] or "").lower()
        bn  = os.path.basename(src.replace("\\", "/"))
        ext = os.path.splitext(bn)[1].lower()
        if not (mt.startswith("image/") or ext in _IMAGE_EXT):
            continue
        if pre and bn.lower().startswith(pre) and len(bn) > len(pre):
            bn = bn[len(pre):]
        key = _stem(bn, "")
        entry = wanted.setdefault(key, {"name": bn, "articles": [], "mime_ids": []})
        if r["product_id"] not in entry["articles"]:
            entry["articles"].append(r["product_id"])
        entry["mime_ids"].append(r["mime_id"])
    return wanted


def _to_jpg(src: str, dst: str):
    """Kopiert JPGs unverändert, konvertiert alles andere nach JPEG (Pillow)."""
    if os.path.splitext(src)[1].lower() in (".jpg", ".jpeg"):
        shutil.copy2(src, dst)
        return False
    from PIL import Image
    with Image.open(src) as im:
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.getchannel("A"))
            im = bg
        elif im.mode != "RGB":
            im = im.convert("RGB")
        tmp = dst + ".tmp"
        im.save(tmp, "JPEG", quality=_JPEG_QUALITY, optimize=True)
    os.replace(tmp, dst)
    return True


def prepare_images(db_path: str, supplier_name: str, prefix: str,
                   src_dir: str, dest_dir: str, logs_dir: str,
                   move: bool = False, progress_cb: Callable = None,
                   file_progress_cb: Callable = None) -> dict:
    p = progress_cb or (lambda m, **kw: None)
    from lib.article_db import open_db, _now

    prefix = (prefix or "").strip().upper()
    pre = prefix.lower()
    con = open_db(db_path)
    try:
        wanted = load_referenced_images(con, supplier_name, prefix)
        if not wanted:
            p(f"Bilder vorbereiten: keine Bild-Referenzen für '{supplier_name}' in der DB – "
              f"Katalog zuerst importieren?", tag="warn")
            return {}
        p(f"Bilder vorbereiten [{supplier_name}, Kürzel {prefix or '–'}]: "
          f"{len(wanted)} referenzierte Bilddateien in der DB.")

        if not os.path.isdir(src_dir):
            p(f"Quellordner nicht gefunden: {src_dir}", tag="err")
            return {}
        os.makedirs(dest_dir, exist_ok=True)

        files = []
        for root, _dirs, names in os.walk(src_dir):
            for n in names:
                if os.path.splitext(n)[1].lower() in _IMAGE_EXT:
                    files.append(os.path.join(root, n))
        p(f"Quellordner: {len(files)} Bilddateien unter {src_dir}")

        copied = converted = present = skipped = dup = errors = 0
        found: set = set()
        renamed_in_db = 0
        for i, path in enumerate(files, 1):
            key = _stem(path, pre)
            entry = wanted.get(key)
            if not entry:
                skipped += 1
            elif key in found:
                dup += 1
            else:
                target_name = f"{prefix}{os.path.splitext(entry['name'])[0]}.jpg"
                target = os.path.join(dest_dir, target_name)
                try:
                    src_is_jpg = os.path.splitext(path)[1].lower() in (".jpg", ".jpeg")
                    # JPG-Quelle: vorhanden = gleicher Name + gleiche Größe.
                    # Andere Formate: vorhandene Zieldatei nicht erneut konvertieren.
                    if os.path.exists(target) and (
                            not src_is_jpg or os.path.getsize(target) == os.path.getsize(path)):
                        present += 1
                    else:
                        if _to_jpg(path, target):
                            converted += 1
                        else:
                            copied += 1
                        if move:
                            os.remove(path)
                    found.add(key)
                    # DB-Referenz auf .jpg umstellen, falls sie anders lautet
                    if os.path.splitext(entry["name"])[1].lower() not in (".jpg", ".jpeg"):
                        new_src = os.path.splitext(entry["name"])[0] + ".jpg"
                        ph = ",".join("?" * len(entry["mime_ids"]))
                        con.execute(
                            f"UPDATE article_mimes SET mime_source=?, mime_type='image/jpeg' "
                            f"WHERE id IN ({ph})", (new_src, *entry["mime_ids"]))
                        con.execute(
                            f"UPDATE articles SET last_changed=?, content_hash='' "
                            f"WHERE id IN (SELECT article_id FROM article_mimes WHERE id IN ({ph}))",
                            (_now(), *entry["mime_ids"]))
                        renamed_in_db += len(entry["mime_ids"])
                except Exception as exc:
                    errors += 1
                    p(f"  ✗ {os.path.basename(path)}: {exc}", tag="warn")
            if file_progress_cb and (i % 200 == 0 or i == len(files)):
                try:
                    file_progress_cb(i, len(files))
                except Exception:
                    pass
            if i % 2000 == 0:
                con.commit()
                p(f"  … {i}/{len(files)} geprüft, {copied + converted} übernommen", tag="dim")
        con.commit()
    finally:
        con.close()

    missing = {k: v for k, v in wanted.items() if k not in found}
    missing_path = ""
    if missing:
        os.makedirs(logs_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        missing_path = os.path.join(logs_dir, f"bilder_vorbereiten_fehlend_{ts}.csv")
        with open(missing_path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["product_id", "mime_source"])
            for k, v in sorted(missing.items()):
                for pid in v["articles"]:
                    w.writerow([pid, v["name"]])

    p(f"Bilder vorbereiten: {copied} JPGs kopiert, {converted} nach JPG konvertiert"
      f"{' (Quellen entfernt)' if move else ''}, {present} bereits vorhanden, "
      f"{skipped} nicht referenziert übersprungen, {dup} Dubletten, {errors} Fehler; "
      f"{len(missing)} referenzierte Bilder fehlen in der Lieferung"
      + (f" → {os.path.basename(missing_path)}" if missing_path else ""),
      tag="ok" if (copied or converted or present) and not errors else "warn")
    if renamed_in_db:
        p(f"  {renamed_in_db} Bild-Referenzen in der DB auf .jpg umgestellt "
          f"(Export schreibt jetzt den JPG-Namen).", tag="dim")
    p("Nächster Schritt: Task 'Bilder-Upload (Allago + OfficeXL)' – lädt nur neue Dateien hoch.",
      tag="dim")
    return {"copied": copied, "converted": converted, "present": present, "skipped": skipped,
            "dup": dup, "errors": errors, "missing": len(missing), "missing_file": missing_path,
            "referenced": len(wanted), "renamed_in_db": renamed_in_db}
