# tasks/xlsx_to_bmecat.py – Lieferanten-XLSX (WPS/Excel, Bilder per DISPIMG) -> BMEcat 1.2
#
# Aufruf: python -m tasks.xlsx_to_bmecat <datei.xlsx> <ausgabeordner> [Lieferantenname]
# Erzeugt: <ausgabeordner>/bmecat.xml und <ausgabeordner>/images/*.jpg|png
import logging
import os
import re
import sys
import zipfile
from datetime import datetime
from xml.sax.saxutils import escape

import openpyxl
from lxml import etree
from PIL import Image

log = logging.getLogger(__name__)

NS_CI = {"x": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
         "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
         "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
         "rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
TAX = "0.19"
MARK = re.compile(r"^\s*(?:[①-⑳]|【\d+】|\d+[.)])\s*")
DISPIMG = re.compile(r'DISPIMG\("([^"]+)"')


def extract_images(xlsx, out_dir):
    """DISPIMG-ID -> Dateiname im out_dir (WebP/Sonstiges wird nach JPEG gewandelt)."""
    os.makedirs(out_dir, exist_ok=True)
    result = {}
    with zipfile.ZipFile(xlsx) as z:
        rels = etree.fromstring(z.read("xl/_rels/cellimages.xml.rels"))
        target = {r.get("Id"): r.get("Target") for r in rels}
        root = etree.fromstring(z.read("xl/cellimages.xml"))
        for pic in root.iterfind(".//x:pic", NS_CI):
            pid = pic.find("x:nvPicPr/x:cNvPr", NS_CI).get("name")
            rid = pic.find(".//a:blip", NS_CI).get("{%s}embed" % NS_CI["r"])
            src = "xl/" + target[rid]
            ext = os.path.splitext(src)[1].lower()
            name = pid.lower() + (".png" if ext == ".png" else ".jpg")
            if ext in (".jpg", ".jpeg"):
                data = z.read(src)
                with open(os.path.join(out_dir, name), "wb") as f:
                    f.write(data)
            else:  # webp o. ä. ist kein BMEcat-übliches MIME_TYPE -> JPEG/PNG
                with z.open(src) as f:
                    im = Image.open(f)
                    im.load()
                if name.endswith(".jpg"):
                    im = im.convert("RGB")
                im.save(os.path.join(out_dir, name))
            result[pid] = name
    return result


def parse_features(text):
    """'Name: Wert'-Zeilen -> [(fname, fvalue)]; Zeilen ohne Doppelpunkt (Überschriften) entfallen."""
    out = []
    for line in (text or "").splitlines():
        line = MARK.sub("", line).strip()
        name, sep, value = line.partition(":")
        if sep and name.strip() and value.strip():
            out.append((name.strip(), value.strip()))
        elif line:
            log.info("Merkmalszeile ohne Wert übersprungen: %r", line)
    return out


def clean(text):
    return re.sub(r"\*\*", "", text or "").strip()


def short_desc(desc, fallback):
    """DESCRIPTION_SHORT (max. 80 Zeichen): erste Zeile, bei 'Titel: Text' nur der Titel."""
    first = next((MARK.sub("", ln).strip() for ln in clean(desc).splitlines() if ln.strip()), "")
    first = first.split(":")[0] if ":" in first else first
    first = first.strip() or fallback
    return first if len(first) <= 80 else first[:79].rsplit(" ", 1)[0] + "…"


def price(v):
    try:
        return "%.2f" % float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


def build(xlsx, out_dir, supplier="Elektrowaren Wuter GmbH"):
    images = extract_images(xlsx, os.path.join(out_dir, "images"))
    ws = openpyxl.load_workbook(xlsx).active
    arts, skipped = [], []
    for n, (sku, foto, _link, desc, merk, cost, rrp, *_) in enumerate(ws.iter_rows(min_row=3, values_only=True), 1):
        if not sku:
            continue
        net, gross = price(cost), price(rrp)
        if not net or not gross:  # ARTICLE_PRICE_DETAILS ist in BMEcat 1.2 Pflicht
            skipped.append(sku)
            continue
        m = DISPIMG.search(str(foto or ""))
        arts.append(dict(aid="WUTER-%03d" % n, alt=str(sku), short=short_desc(desc, str(sku)),
                         long=clean(desc), feats=parse_features(merk), net=net, gross=gross,
                         img=images.get(m.group(1)) if m else None))
    e = escape
    x = ['<?xml version="1.0" encoding="UTF-8"?>',
         '<BMECAT version="1.2" xmlns="http://www.bmecat.org/bmecat/1.2/bmecat_new_catalog">',
         '<HEADER><GENERATOR_INFO>xlsx_to_bmecat</GENERATOR_INFO><CATALOG><LANGUAGE>deu</LANGUAGE>'
         '<CATALOG_ID>WUTER</CATALOG_ID><CATALOG_VERSION>1.0</CATALOG_VERSION>'
         '<CATALOG_NAME>%s</CATALOG_NAME><DATETIME type="generation_date"><DATE>%s</DATE></DATETIME>'
         '<CURRENCY>EUR</CURRENCY></CATALOG><SUPPLIER><SUPPLIER_NAME>%s</SUPPLIER_NAME></SUPPLIER></HEADER>'
         % (e(supplier), datetime.now().strftime("%Y-%m-%d"), e(supplier)), "<T_NEW_CATALOG>"]
    for a in arts:
        x.append("<ARTICLE><SUPPLIER_AID>%s</SUPPLIER_AID><ARTICLE_DETAILS><DESCRIPTION_SHORT>%s</DESCRIPTION_SHORT>"
                 % (a["aid"], e(a["short"])))
        if a["long"]:
            x.append("<DESCRIPTION_LONG>%s</DESCRIPTION_LONG>" % e(a["long"]))
        x.append("<SUPPLIER_ALT_AID>%s</SUPPLIER_ALT_AID></ARTICLE_DETAILS>" % e(a["alt"]))
        if a["feats"]:
            x.append("<ARTICLE_FEATURES>" + "".join(
                "<FEATURE><FNAME>%s</FNAME><FVALUE>%s</FVALUE></FEATURE>" % (e(k), e(v)) for k, v in a["feats"])
                + "</ARTICLE_FEATURES>")
        x.append("<ARTICLE_ORDER_DETAILS><ORDER_UNIT>C62</ORDER_UNIT><CONTENT_UNIT>C62</CONTENT_UNIT>"
                 "<NO_CU_PER_OU>1</NO_CU_PER_OU></ARTICLE_ORDER_DETAILS><ARTICLE_PRICE_DETAILS>")
        for t, amt in (("net_customer", a["net"]), ("gros_list", a["gross"])):
            x.append('<ARTICLE_PRICE price_type="%s"><PRICE_AMOUNT>%s</PRICE_AMOUNT><PRICE_CURRENCY>EUR'
                     "</PRICE_CURRENCY><TAX>%s</TAX></ARTICLE_PRICE>" % (t, amt, TAX))
        x.append("</ARTICLE_PRICE_DETAILS>")
        if a["img"]:
            mt = "image/png" if a["img"].endswith(".png") else "image/jpeg"
            x.append("<MIME_INFO><MIME><MIME_SOURCE>images/%s</MIME_SOURCE><MIME_TYPE>%s</MIME_TYPE>"
                     "<MIME_PURPOSE>normal</MIME_PURPOSE></MIME></MIME_INFO>" % (a["img"], mt))
        x.append("</ARTICLE>")
    x.append('</T_NEW_CATALOG></BMECAT>')
    path = os.path.join(out_dir, "bmecat.xml")
    xml = "\n".join(x)
    etree.fromstring(xml.encode())  # Wohlgeformtheit
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml)
    log.info("%d Artikel, übersprungen (ohne Preis): %s", len(arts), skipped)
    return path, arts, skipped


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p, arts, skipped = build(*sys.argv[1:4])
    print(p, len(arts), "Artikel; übersprungen:", skipped)
