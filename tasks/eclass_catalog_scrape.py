# tasks/eclass_catalog_scrape.py – eClass-Katalog von eclass.eu scrapen
#
# Strategie: Selenium + Chrome DevTools Protocol (CDP)
#   Phase 1 – Discover: öffnet die Seite, fängt alle XHR/fetch-Calls ab
#              und zeigt welche API-Endpoints genutzt werden
#   Phase 2 – Scrape: nutzt die gefundenen Endpoints direkt,
#              iteriert alle Versionen und alle 4 Hierarchiestufen
#
# Ausgabe: eclass_catalog.csv in BASE_DIR
#   version ; code ; name_de ; name_en ; level ; parent_code
#
# Installation (einmalig):
#   py -m pip install selenium webdriver-manager
#
# Ausführen als eigenständiges Script:
#   py tasks/eclass_catalog_scrape.py --discover
#   py tasks/eclass_catalog_scrape.py --version 12.0
#   py tasks/eclass_catalog_scrape.py --all-versions
#
# Als Task im Tool: einfach "eClass-Katalog scrapen" auswählen
#
# Tipp: Beim ersten Aufruf --discover verwenden und die API-URL aus dem
#       Output entnehmen – dann ggf. API_PATTERN anpassen.

import argparse
import csv
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

log = logging.getLogger(__name__)

CATALOG_FILENAME = "eclass_catalog.csv"
TARGET_URL       = "https://eclass.eu/eclass-standard/content-suche"

# Bekannte eClass-Versionen (neueste zuerst)
ECLASS_VERSIONS  = [
    "12.0", "11.1", "11.0",
    "10.0.1", "10.0",
    "9.1", "9.0",
    "8.0", "7.1", "7.0", "6.0", "5.1.4",
]

CSV_HEADER = ["version", "code", "name_de", "name_en", "level", "parent_code"]

LEVELS = {0: "segment", 1: "hauptgruppe", 2: "gruppe", 3: "klasse"}


# ── Selenium-Setup ────────────────────────────────────────────────────────────

def _make_driver(headless: bool = False, manual_login: bool = True):
    """Startet Chrome mit CDP-Support (sichtbar für Login-Handling)."""
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.chrome.options import Options
        from webdriver_manager.chrome import ChromeDriverManager
    except ImportError:
        raise ImportError("py -m pip install selenium webdriver-manager")

    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1400,900")
    opts.add_argument("--lang=de-DE,de;q=0.9,en;q=0.8")
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36")

    # CDP für Network-Interception aktivieren
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    try:
        svc = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=svc, options=opts)
    except Exception:
        # Fallback: Chrome im PATH
        driver = webdriver.Chrome(options=opts)

    # CDP aktivieren
    driver.execute_cdp_cmd("Network.enable", {})
    driver.execute_cdp_cmd("Network.setExtraHTTPHeaders", {
        "headers": {"Accept-Language": "de-DE,de;q=0.9,en;q=0.8"}
    })

    return driver


# ── Phase 1: Discover – API-Pattern finden ────────────────────────────────────

def discover(driver, wait_sec: int = 45, progress_cb=None) -> dict:
    """
    Öffnet eclass.eu und wartet auf XHR-Calls.
    Gibt gefundene API-Patterns zurück: {url_pattern: example_response}.
    """
    p = progress_cb or print

    p(f"  Öffne {TARGET_URL} ...")
    driver.get(TARGET_URL)
    p(f"  Browser offen. Bitte {wait_sec}s navigieren (Kategorien anklicken) ...")

    # Warte & sammle Network-Logs
    deadline = time.time() + wait_sec
    xhr_calls = {}

    while time.time() < deadline:
        time.sleep(2)
        logs = driver.get_log("performance")
        for entry in logs:
            try:
                msg = json.loads(entry["message"])["message"]
                if msg["method"] != "Network.responseReceived":
                    continue
                resp = msg["params"]["response"]
                url  = resp.get("url", "")
                mime = resp.get("mimeType", "")
                if "json" in mime and "eclass" in url.lower():
                    rid = msg["params"]["requestId"]
                    try:
                        body = driver.execute_cdp_cmd(
                            "Network.getResponseBody", {"requestId": rid})
                        xhr_calls[url] = json.loads(body.get("body", "{}"))
                    except Exception:
                        xhr_calls[url] = {}
            except Exception:
                pass

    if not xhr_calls:
        p("  Keine API-Calls gefunden – bitte im Browser navigieren und erneut versuchen.")
        return {}

    p(f"  {len(xhr_calls)} API-Calls gefangen:")
    for url in list(xhr_calls)[:10]:
        p(f"    {url}")

    return xhr_calls


# ── Phase 2: API-basiertes Scraping ──────────────────────────────────────────

class EclassScraper:
    """
    Scrapt eClass-Hierarchie über die JavaScript-API der Seite.
    Arbeitet sich durch alle Versionen und alle 4 Ebenen.
    """

    def __init__(self, driver, api_base: str = None, progress_cb=None):
        self._drv     = driver
        self._api     = api_base  # wird im Discovery ermittelt
        self._results = []
        self._p       = progress_cb or print
        self._session_ready = False

    def _warmup(self):
        """Seite öffnen damit Session-Cookie gesetzt wird."""
        if self._session_ready:
            return
        self._drv.get(TARGET_URL)
        time.sleep(4)
        self._session_ready = True

    def _js_fetch(self, url: str) -> dict | list | None:
        """Ruft URL via fetch() im Browser-Kontext auf (hat Session-Cookie)."""
        script = """
        const [resolve] = arguments;
        fetch(arguments[1], {
            headers: {
                'Accept': 'application/json, text/plain, */*',
                'Accept-Language': 'de-DE,de;q=0.9',
            }
        })
        .then(r => r.json())
        .then(d => resolve({ok: true, data: d}))
        .catch(e => resolve({ok: false, error: e.toString()}));
        """
        try:
            result = self._drv.execute_async_script(script, url)
            if result and result.get("ok"):
                return result["data"]
        except Exception as e:
            log.debug("JS-Fetch Fehler %s: %s", url, e)
        return None

    def _detect_api(self) -> str | None:
        """
        Erkennt automatisch den API-Endpoint durch Monitoring von Network-Calls.
        Gibt Base-URL zurück wenn gefunden.
        """
        self._warmup()
        self._p("  Erkenne API-Endpoint ...")

        # Kurz warten auf initiale Calls
        time.sleep(3)
        logs = self._drv.get_log("performance")

        candidates = []
        for entry in logs:
            try:
                msg = json.loads(entry["message"])["message"]
                if msg["method"] != "Network.responseReceived":
                    continue
                resp = msg["params"]["response"]
                url  = resp.get("url", "")
                mime = resp.get("mimeType", "")
                if "json" in mime and "eclass" in url.lower():
                    candidates.append(url)
            except Exception:
                pass

        if candidates:
            # Längsten gemeinsamen Präfix finden
            import os.path
            base = candidates[0]
            for c in candidates[1:]:
                while not c.startswith(base):
                    base = base[:base.rfind("/") + 1]
                    if not base:
                        break
            self._p(f"  API-Base erkannt: {base}")
            return base

        # Fallback: bekannte Muster testen
        test_patterns = [
            "https://eclass.eu/api/",
            "https://eclass.eu/rest/",
            "https://api.eclass.eu/",
            "https://eclass.eu/eclass-standard/api/",
        ]
        for pattern in test_patterns:
            result = self._js_fetch(f"{pattern}versions")
            if result:
                self._p(f"  API-Pattern funktioniert: {pattern}")
                return pattern

        return None

    def _get_versions(self, api_base: str) -> list[str]:
        """Holt verfügbare Versionen von der API."""
        for endpoint in [
            f"{api_base}versions",
            f"{api_base}releases",
            f"{api_base}eclass/versions",
        ]:
            data = self._js_fetch(endpoint)
            if data and isinstance(data, list):
                versions = []
                for item in data:
                    if isinstance(item, dict):
                        v = item.get("version") or item.get("id") or item.get("name", "")
                    else:
                        v = str(item)
                    if v:
                        versions.append(str(v))
                if versions:
                    self._p(f"  Versionen von API: {versions}")
                    return versions
        return []

    def _get_children(self, api_base: str, version: str,
                      parent_code: str = None) -> list[dict]:
        """
        Holt Kinder-Knoten eines eClass-Knotens.
        Gibt [{code, name_de, name_en, has_children}, ...] zurück.
        """
        # Verschiedene URL-Muster ausprobieren
        ver_clean = version.replace(".", "_").replace(" ", "_")
        parent   = parent_code or ""

        url_patterns = [
            f"{api_base}search?version={version}&parentId={parent}&pageSize=500",
            f"{api_base}eclass/{ver_clean}/children?parent={parent}",
            f"{api_base}categories?version={version}&parent={parent}",
            f"{api_base}hierarchy/{version}?parent={parent}",
            f"{api_base}eclass/version/{version}/category?parent={parent}",
        ]

        for url in url_patterns:
            data = self._js_fetch(url)
            if data:
                return self._parse_items(data)

        return []

    def _parse_items(self, data) -> list[dict]:
        """Normalisiert unterschiedliche API-Response-Formate."""
        items = []

        if isinstance(data, list):
            raw_list = data
        elif isinstance(data, dict):
            raw_list = (data.get("results") or data.get("items") or
                        data.get("data") or data.get("categories") or
                        data.get("content") or [])
        else:
            return []

        for item in raw_list:
            if not isinstance(item, dict):
                continue
            code = (item.get("id") or item.get("code") or
                    item.get("classificationSystemVersionId") or
                    item.get("preferredName", {}).get("id", ""))
            name_de = (item.get("name") or item.get("name_de") or
                       item.get("preferredName", {}).get("de", "") or
                       item.get("label", ""))
            name_en = (item.get("name_en") or
                       item.get("preferredName", {}).get("en", "") or "")
            if code:
                items.append({
                    "code":     str(code).strip(),
                    "name_de":  str(name_de).strip(),
                    "name_en":  str(name_en).strip(),
                    "children": bool(item.get("hasChildren") or
                                     item.get("children") or
                                     item.get("childCount", 0)),
                })
        return items

    def _level_from_code(self, code: str) -> int:
        """24 → 0, 24-22 → 1, 24-22-09 → 2, 24-22-09-01 → 3"""
        return code.count("-")

    def scrape_version(self, api_base: str, version: str) -> int:
        """Scrapt eine vollständige Version. Gibt Anzahl Einträge zurück."""
        self._p(f"\n  === Version {version} ===")
        count = 0

        def _recurse(parent_code: str | None, depth: int):
            nonlocal count
            if depth > 3:
                return
            items = self._get_children(api_base, version, parent_code)
            if not items and depth == 0:
                self._p(f"    Keine Daten für Version {version} – API-Pattern prüfen",
                         tag="warn" if hasattr(self._p, '__call__') else None)
                return
            for item in items:
                code  = item["code"]
                level = self._level_from_code(code)
                self._results.append({
                    "version":     version,
                    "code":        code,
                    "name_de":     item["name_de"],
                    "name_en":     item["name_en"],
                    "level":       LEVELS.get(level, f"level{level}"),
                    "parent_code": parent_code or "",
                })
                count += 1
                if item.get("children") and depth < 3:
                    _recurse(code, depth + 1)

        _recurse(None, 0)
        self._p(f"  → {count:,} Einträge für Version {version}")
        return count

    def run(self, versions: list[str] = None, out_csv: str = None,
            api_base: str = None):
        """Haupteinstieg: scrapet alle angegebenen Versionen."""
        self._warmup()

        # API erkennen wenn nicht übergeben
        base = api_base or self._api or self._detect_api()
        if not base:
            self._p("  API-Endpoint nicht erkannt.")
            self._p("  Bitte --discover ausführen und API-Pattern manuell setzen.")
            raise RuntimeError("API-Endpoint nicht gefunden")

        # Versionen holen
        if versions is None:
            versions = self._get_versions(base) or ECLASS_VERSIONS
        self._p(f"  Versionen: {versions}")

        total = 0
        for v in versions:
            n = self.scrape_version(base, v)
            total += n
            # Checkpoint-Schreiben nach jeder Version
            if out_csv and self._results:
                _write_csv(self._results, out_csv)
                self._p(f"  Checkpoint: {total:,} Einträge in {out_csv}")

        if out_csv:
            _write_csv(self._results, out_csv)
        return self._results


# ── DOM-Fallback: Klickt durch die Hierarchie ─────────────────────────────────

def scrape_via_dom(driver, out_csv: str, versions: list[str] = None,
                   progress_cb=None) -> list[dict]:
    """
    Fallback wenn API nicht erreichbar: Klickt durch das Angular-UI.
    Langsamer aber robuster.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    p = progress_cb or print
    results = []

    p("  DOM-Fallback: navigiere durch UI ...")
    driver.get(TARGET_URL)
    time.sleep(5)

    # Versuche Version-Selector zu finden
    version_els = driver.find_elements(By.CSS_SELECTOR,
        "[data-version], .version-select option, "
        "select[name*='version'] option, .mat-option")

    if version_els:
        p(f"  {len(version_els)} Versionen im DOM gefunden")
    else:
        p("  Kein Versions-Selector im DOM – bitte Seite manuell öffnen")

    # Alle sichtbaren Links mit eClass-Code-Muster extrahieren
    def _extract_visible():
        items = []
        links = driver.find_elements(By.CSS_SELECTOR, "a, li[data-code], .category-item")
        for el in links:
            text = el.text.strip()
            href = el.get_attribute("href") or ""
            # Typische eClass-Code-Muster: XX, XX-XX, XX-XX-XX, XX-XX-XX-XX
            m = re.search(r'\b(\d{2}(?:-\d{2}){0,3})\b', text)
            if m:
                code = m.group(1)
                name = re.sub(r'\b\d{2}(?:-\d{2}){0,3}\b', '', text).strip(" -–")
                items.append({"code": code, "name_de": name, "href": href})
        return items

    # Erste Ebene sammeln
    first_level = _extract_visible()
    p(f"  {len(first_level)} Einträge auf erster Ebene")
    results.extend({"version": "unknown", "code": i["code"],
                    "name_de": i["name_de"], "name_en": "",
                    "level": LEVELS.get(i["code"].count("-"), "segment"),
                    "parent_code": ""}
                   for i in first_level)

    if out_csv:
        _write_csv(results, out_csv)
    return results


# ── CSV schreiben ─────────────────────────────────────────────────────────────

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
    """Task-Einstieg aus dem bmecat-tool."""
    import config as _cfg
    p = progress_cb or (lambda m, **kw: None)

    p("┌─ eClass-Katalog scrapen ───────────────────────────────────")
    p("│  Quelle:  https://eclass.eu/eclass-standard/content-suche")
    p("│  Methode: Selenium + Chrome (echter Browser)")
    p("│  Ausgabe: eclass_catalog.csv  (in BASE_DIR)")
    p("└────────────────────────────────────────────────────────────")

    try:
        from selenium import webdriver  # noqa
    except ImportError:
        raise RuntimeError(
            "Selenium nicht installiert.\n"
            "Bitte ausführen: py -m pip install selenium webdriver-manager"
        )

    out_csv = os.path.join(_cfg.BASE_DIR, CATALOG_FILENAME)

    driver = _make_driver(headless=False)
    try:
        scraper = EclassScraper(driver, progress_cb=p)
        results = scraper.run(out_csv=out_csv)

        if not results:
            p("  API nicht gefunden – versuche DOM-Fallback ...")
            results = scrape_via_dom(driver, out_csv, progress_cb=p)

        p(f"  Gesamt: {len(results):,} Einträge", tag="ok")
        p(f"  Datei:  {out_csv}", tag="ok")
    finally:
        driver.quit()


# ── CLI-Modus ─────────────────────────────────────────────────────────────────

def _cli():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")

    ap = argparse.ArgumentParser(description="eClass-Katalog Scraper")
    ap.add_argument("--discover",       action="store_true",
                    help="Öffnet Browser und zeigt API-Calls (30s)")
    ap.add_argument("--version",        metavar="VERSION",
                    help="Nur diese Version scrapen, z.B. '12.0'")
    ap.add_argument("--all-versions",   action="store_true",
                    help=f"Alle Versionen: {ECLASS_VERSIONS}")
    ap.add_argument("--api",            metavar="URL",
                    help="API-Base-URL manuell angeben")
    ap.add_argument("--out",            default="eclass_catalog.csv",
                    help="Ausgabe-CSV (default: eclass_catalog.csv)")
    ap.add_argument("--wait",           type=int, default=45,
                    help="Wartezeit für --discover in Sekunden (default: 45)")
    args = ap.parse_args()

    driver = _make_driver(headless=False)
    try:
        if args.discover:
            calls = discover(driver, wait_sec=args.wait,
                             progress_cb=log.info)
            if calls:
                print("\nGefundene API-Calls:")
                for url in calls:
                    print(f"  {url}")
                print("\nHint: --api <base-url> beim nächsten Aufruf setzen")
            return

        versions = None
        if args.version:
            versions = [args.version]
        elif args.all_versions:
            versions = ECLASS_VERSIONS

        scraper = EclassScraper(driver, api_base=args.api,
                                 progress_cb=log.info)
        results = scraper.run(versions=versions, out_csv=args.out,
                              api_base=args.api)

        if not results:
            log.info("API leer – versuche DOM-Fallback ...")
            results = scrape_via_dom(driver, args.out, versions=versions,
                                     progress_cb=log.info)

        log.info("Fertig: %d Einträge → %s", len(results), args.out)

    finally:
        driver.quit()


if __name__ == "__main__":
    _cli()
