# tasks/eclass_catalog_scrape.py – eClass-Katalog von eclass.eu scrapen
#
# Strategie: Selenium + URL-Navigation (Server-Side-Rendered TYPO3)
#   Die Seite eclass.eu/eclass-standard/content-suche rendert den Baum
#   server-seitig. Jede Ebene hat eine eigene URL mit cHash:
#     /eclass-standard/content-suche/show?tx_eclasssearch_ecsearch[id]=XXXXXXXX
#                                        &tx_eclasssearch_ecsearch[version]=12.0
#   Das Script navigiert per Formular-Submit + URL-Fetch durch alle
#   Versionen und alle 4 Hierarchiestufen.
#
# Schnellere Alternative: eclass_extractor.js in Browser-Konsole ausführen!
#
# Ausgabe: eclass_catalog.csv in BASE_DIR (oder --out Pfad)
#   version ; code ; name_de ; name_en ; level ; parent_code
#
# Installation (einmalig):
#   py -m pip install selenium webdriver-manager
#
# CLI:
#   py tasks/eclass_catalog_scrape.py --version 12.0    # eine Version
#   py tasks/eclass_catalog_scrape.py --all-versions    # alle Versionen
#   py tasks/eclass_catalog_scrape.py --list-versions   # verfügbare Versionen zeigen

import argparse
import csv
import logging
import os
import re
import time
from pathlib import Path
from urllib.parse import urlencode, urljoin

log = logging.getLogger(__name__)

CATALOG_FILENAME = "eclass_catalog.csv"
BASE_URL         = "https://eclass.eu"
TARGET_URL       = f"{BASE_URL}/eclass-standard/content-suche"
SHOW_URL         = f"{BASE_URL}/eclass-standard/content-suche/show"

# Alle Versionen aus dem Dropdown (Stand 06/2026)
ECLASS_VERSIONS = [
    "16.0", "15.0", "14.0", "13.0",
    "12.0", "11.1", "11.0", "10.1", "10.0.1",
    "9.1", "9.0", "8.1", "8.0",
    "7.1", "7.0", "6.2", "6.1", "5.14",
]

CSV_HEADER = ["version", "code", "name_de", "name_en", "level", "parent_code"]
LEVELS     = {0: "segment", 1: "hauptgruppe", 2: "gruppe", 3: "klasse"}

# Pause zwischen Requests (Server schonen)
REQUEST_DELAY = 0.4


# ── Code-Konvertierung ────────────────────────────────────────────────────────

def code8_to_eclass(code8: str) -> str:
    """
    Konvertiert 8-stelligen Zahlen-Code in Strich-Format.
    '13000000' → '13'
    '24220901' → '24-22-09-01'
    """
    s   = str(code8).zfill(8)
    seg = s[0:2]
    hg  = s[2:4]
    gr  = s[4:6]
    kl  = s[6:8]
    if hg == "00": return seg
    if gr == "00": return f"{seg}-{hg}"
    if kl == "00": return f"{seg}-{hg}-{gr}"
    return f"{seg}-{hg}-{gr}-{kl}"


# ── Selenium-Setup ────────────────────────────────────────────────────────────

def _make_driver():
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.chrome.options import Options
        from webdriver_manager.chrome import ChromeDriverManager
    except ImportError:
        raise ImportError("py -m pip install selenium webdriver-manager")

    opts = Options()
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1400,900")
    opts.add_argument("--lang=de-DE,de;q=0.9,en;q=0.8")
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36")

    try:
        svc = Service(ChromeDriverManager().install())
        drv = webdriver.Chrome(service=svc, options=opts)
    except Exception:
        drv = webdriver.Chrome(options=opts)
    return drv


# ── Cookie-Banner ─────────────────────────────────────────────────────────────

def _accept_cookies(driver):
    from selenium.webdriver.common.by import By
    time.sleep(2)
    try:
        for btn in driver.find_elements(By.TAG_NAME, "button"):
            txt = btn.text.strip().lower()
            if any(kw in txt for kw in
                   ["akzept", "accept", "alle cookies", "alle erlauben"]):
                if btn.is_displayed():
                    btn.click()
                    log.info("  Cookie-Banner akzeptiert: '%s'", btn.text.strip())
                    time.sleep(1)
                    return
        for sel in ["#data-cookie-accept", ".cookie-accept", "#onetrust-accept-btn-handler"]:
            try:
                el = driver.find_element(By.CSS_SELECTOR, sel)
                if el.is_displayed():
                    el.click()
                    time.sleep(1)
                    return
            except Exception:
                pass
    except Exception:
        pass


# ── DOM-Parsing ───────────────────────────────────────────────────────────────

NODE_RE  = re.compile(r'^node_(\d{8})$')
# Text-Format: "13 Entwicklung..." oder "  24-22 Bürobedarf..." → Name extrahieren
NAME_RE  = re.compile(r'^[\d][\d\-]*\s+(.+)')


def _parse_nodes_from_source(html_source: str, exclude_codes: set = None) -> list[dict]:
    """
    Extrahiert alle <li id="node_XXXXXXXX"> aus dem HTML-Quelltext.
    Gibt [{code8, code, name, href}] zurück.
    """
    from html.parser import HTMLParser

    items   = []
    seen    = set(exclude_codes or set())

    # Einfacher State-Machine-Parser
    class _P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.cur_code8 = None
            self.cur_href  = None
            self.in_link   = False
            self.link_text = ""

        def handle_starttag(self, tag, attrs):
            d = dict(attrs)
            if tag == "li":
                m = NODE_RE.match(d.get("id", ""))
                if m:
                    self.cur_code8 = m.group(1)
            if tag == "a" and self.cur_code8:
                cls = d.get("class", "")
                if "treeLink" in cls:
                    self.cur_href  = d.get("href", "")
                    self.in_link   = True
                    self.link_text = ""

        def handle_data(self, data):
            if self.in_link:
                self.link_text += data

        def handle_endtag(self, tag):
            if tag == "a" and self.in_link:
                self.in_link = False
                if self.cur_code8 and self.cur_href and self.cur_code8 not in seen:
                    seen.add(self.cur_code8)
                    code = code8_to_eclass(self.cur_code8)
                    text = " ".join(self.link_text.split()).strip()
                    m    = NAME_RE.match(text)
                    name = m.group(1).strip() if m else text
                    items.append({
                        "code8": self.cur_code8,
                        "code":  code,
                        "name":  name,
                        "href":  self.cur_href if self.cur_href.startswith("http")
                                 else BASE_URL + self.cur_href,
                    })
                    self.cur_code8 = None
                    self.cur_href  = None

    _P().feed(html_source)
    return items


# ── Haupt-Scraper ─────────────────────────────────────────────────────────────

class EclassScraper:

    def __init__(self, driver, progress_cb=None):
        self._drv     = driver
        self._p       = progress_cb or log.info
        self._results: list[dict] = []
        self._ready   = False

    def _warmup(self):
        if self._ready:
            return
        self._p("  Lade Seite ...")
        self._drv.get(TARGET_URL)
        time.sleep(4)
        _accept_cookies(self._drv)
        time.sleep(2)
        self._ready = True

    def _fetch_version_page(self, version: str) -> str:
        """Wechselt per Formular-Submit auf eine Version. Gibt HTML zurück."""
        self._warmup()

        # Formular per JavaScript ausfüllen und abschicken
        script = f"""
        var sel = document.getElementById('versionlist');
        if (sel) {{
            sel.value = {version!r};
            sel.dispatchEvent(new Event('change'));
        }}
        """
        self._drv.execute_script(script)
        # showLoading() + form.submit() wird durch onChange ausgelöst
        time.sleep(3)

        # Falls der automatische Submit nicht klappt, manuell abschicken
        try:
            self._drv.execute_script(
                "document.getElementById('ajaxselectlist-form').submit();")
            time.sleep(3)
        except Exception:
            pass

        return self._drv.page_source

    def _fetch_url(self, url: str) -> str:
        """Navigiert zu einer URL und gibt den HTML-Quelltext zurück."""
        time.sleep(REQUEST_DELAY)
        self._drv.get(url)
        time.sleep(2)
        return self._drv.page_source

    def _get_available_versions(self) -> list[str]:
        """Liest verfügbare Versionen aus dem Versions-Dropdown."""
        self._warmup()
        try:
            from selenium.webdriver.common.by import By
            opts = self._drv.find_elements(
                By.CSS_SELECTOR, "#versionlist option")
            return [o.get_attribute("value") for o in opts if o.get_attribute("value")]
        except Exception:
            return []

    def scrape_version(self, version: str) -> int:
        self._p(f"\n  === Version {version} ===")
        count = 0

        # Segment-Seite laden
        html = self._fetch_version_page(version)
        segments = _parse_nodes_from_source(html)
        if not segments:
            log.warning("    Keine Segmente für Version %s", version)
            return 0

        self._p(f"  {len(segments)} Segmente")

        for seg in segments:
            self._results.append({
                "version": version, "code": seg["code"], "name_de": seg["name"],
                "name_en": "", "level": "segment", "parent_code": ""
            })
            count += 1

            # Hauptgruppen
            html_hg = self._fetch_url(seg["href"])
            # Exclude segment itself
            hgruppen = _parse_nodes_from_source(html_hg, exclude_codes={seg["code8"]})
            hgruppen = [h for h in hgruppen if h["code"] != seg["code"]]

            for hg in hgruppen:
                self._results.append({
                    "version": version, "code": hg["code"], "name_de": hg["name"],
                    "name_en": "", "level": "hauptgruppe", "parent_code": seg["code"]
                })
                count += 1

                # Gruppen
                html_gr = self._fetch_url(hg["href"])
                gruppen = _parse_nodes_from_source(
                    html_gr, exclude_codes={seg["code8"], hg["code8"]})
                gruppen = [g for g in gruppen if g["code"] not in (seg["code"], hg["code"])]

                for gr in gruppen:
                    self._results.append({
                        "version": version, "code": gr["code"], "name_de": gr["name"],
                        "name_en": "", "level": "gruppe", "parent_code": hg["code"]
                    })
                    count += 1

                    # Klassen
                    html_kl = self._fetch_url(gr["href"])
                    klassen = _parse_nodes_from_source(
                        html_kl,
                        exclude_codes={seg["code8"], hg["code8"], gr["code8"]})
                    klassen = [k for k in klassen
                               if k["code"] not in (seg["code"], hg["code"], gr["code"])]

                    for kl in klassen:
                        self._results.append({
                            "version": version, "code": kl["code"], "name_de": kl["name"],
                            "name_en": "", "level": "klasse", "parent_code": gr["code"]
                        })
                        count += 1

        self._p(f"  → {count:,} Einträge für Version {version}")
        return count

    def run(self, versions: list[str], out_csv: str) -> list[dict]:
        total = 0
        for v in versions:
            n = self.scrape_version(v)
            total += n
            if self._results:
                _write_csv(self._results, out_csv)
                self._p(f"  Checkpoint: {total:,} Einträge → {out_csv}")

        _write_csv(self._results, out_csv)
        return self._results


# ── CSV ───────────────────────────────────────────────────────────────────────

def _write_csv(rows: list[dict], path: str):
    tmp = Path(path).with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_HEADER, delimiter=";",
                           extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(Path(path))


# ── Task-Einstieg ─────────────────────────────────────────────────────────────

def run(progress_cb=None):
    import config as _cfg
    p = progress_cb or (lambda m, **kw: None)

    p("┌─ eClass-Katalog scrapen ───────────────────────────────────")
    p("│  Quelle:  https://eclass.eu/eclass-standard/content-suche")
    p("│  Methode: Selenium + URL-Navigation (SSR-TYPO3)")
    p("│")
    p("│  Tipp:    Schneller per Browser-Konsole:")
    p("│           eclass_extractor.js ausführen")
    p(f"│  Ausgabe: {CATALOG_FILENAME}  (in BASE_DIR)")
    p("└────────────────────────────────────────────────────────────")

    try:
        from selenium import webdriver  # noqa
    except ImportError:
        raise RuntimeError("py -m pip install selenium webdriver-manager")

    out_csv = os.path.join(_cfg.BASE_DIR, CATALOG_FILENAME)
    driver  = _make_driver()
    try:
        scraper = EclassScraper(driver, progress_cb=p)
        results = scraper.run(ECLASS_VERSIONS, out_csv)
        if results:
            p(f"  Gesamt: {len(results):,} Einträge", tag="ok")
            p(f"  Datei:  {out_csv}", tag="ok")
        else:
            p("  Keine Daten. Browser-Konsolen-Script empfohlen.", tag="error")
    finally:
        driver.quit()


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cli():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(
        description="eClass-Katalog Scraper  (Empfehlung: eclass_extractor.js im Browser)")
    ap.add_argument("--version",        metavar="V",
                    help="Nur diese Version, z.B. '12.0'")
    ap.add_argument("--all-versions",   action="store_true",
                    help="Alle bekannten Versionen")
    ap.add_argument("--list-versions",  action="store_true",
                    help="Verfügbare Versionen von der Seite lesen und anzeigen")
    ap.add_argument("--out",            default="eclass_catalog.csv")
    args = ap.parse_args()

    driver = _make_driver()
    try:
        if args.list_versions:
            scraper = EclassScraper(driver)
            versions = scraper._get_available_versions()
            log.info("Verfügbare Versionen: %s", versions)
            return

        versions = ([args.version] if args.version
                    else ECLASS_VERSIONS if args.all_versions
                    else ECLASS_VERSIONS[:3])  # Default: neueste 3

        scraper = EclassScraper(driver, progress_cb=log.info)
        results = scraper.run(versions, args.out)
        if results:
            log.info("Fertig: %d Einträge → %s", len(results), args.out)
        else:
            log.warning("Keine Daten gesammelt.")
    finally:
        driver.quit()


if __name__ == "__main__":
    _cli()
