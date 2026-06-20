# tasks/eclass_catalog_scrape.py – eClass-Katalog von eclass.eu scrapen
#
# Strategie: Selenium + CDP (Chrome DevTools Protocol)
#   1. Öffnet eclass.eu/content-suche im echten Chrome-Browser
#   2. Akzeptiert Cookie-Banner automatisch
#   3. Fängt echte TYPO3-API-Calls ab (requestWillBeSent inkl. POST-Body)
#   4. Probiert TYPO3-Extbase-Varianten (form-encoded POST) durch
#   5. DOM-Fallback wenn API nicht gefunden
#
# Ausgabe: eclass_catalog.csv in BASE_DIR (oder --out Pfad)
#   version ; code ; name_de ; name_en ; level ; parent_code
#
# Installation (einmalig):
#   py -m pip install selenium webdriver-manager
#
# CLI:
#   py tasks/eclass_catalog_scrape.py --discover        # echte API-Calls zeigen
#   py tasks/eclass_catalog_scrape.py --version 12.0    # eine Version
#   py tasks/eclass_catalog_scrape.py --all-versions    # alle Versionen

import argparse
import csv
import json
import logging
import os
import re
import time
import urllib.parse
from pathlib import Path

log = logging.getLogger(__name__)

CATALOG_FILENAME = "eclass_catalog.csv"
TARGET_URL       = "https://eclass.eu/eclass-standard/content-suche"
TYPO3_API        = "https://eclass.eu/shop/typo3-api"

# Bekannte eClass-Versionen (neueste zuerst)
ECLASS_VERSIONS = [
    "12.0", "11.1", "11.0",
    "10.0.1", "10.0",
    "9.1", "9.0",
    "8.0", "7.1", "7.0", "6.0", "5.1.4",
]

CSV_HEADER = ["version", "code", "name_de", "name_en", "level", "parent_code"]
LEVELS     = {0: "segment", 1: "hauptgruppe", 2: "gruppe", 3: "klasse"}

# TYPO3 Extbase-Erweiterungsnamen (nach Wahrscheinlichkeit)
TYPO3_EXTS = [
    "tpieclass", "eclass", "eclasscatalog", "eclasspages",
    "eclassdb", "eclasssearch", "standardeclass", "shop",
]

# Action/Controller-Kombinationen
TYPO3_ACTIONS = [
    ("getClasses",    "Content"),
    ("listClasses",   "Content"),
    ("getChildren",   "Content"),
    ("getTree",       "Content"),
    ("getSegments",   "Content"),
    ("list",          "Content"),
    ("index",         "Content"),
    ("getClasses",    "Classification"),
    ("listClasses",   "Classification"),
    ("getChildren",   "Classification"),
    ("list",          "Classification"),
    ("getCategories", "Category"),
    ("list",          "Category"),
]

# URL-Varianten für den API-Endpunkt
API_URLS = [
    f"{TYPO3_API}?locale=de",
    TYPO3_API,
    f"{TYPO3_API}?type=6111&locale=de",
    f"{TYPO3_API}?type=4711&locale=de",
    f"{TYPO3_API}?type=2021&locale=de",
    f"{TYPO3_API}?type=1&locale=de",
    "https://eclass.eu/?eID=typo3-api&locale=de",
]

VERSION_PARAM_NAMES = ["version", "releaseVersion", "eclassVersion", "release"]
PARENT_PARAM_NAMES  = ["parentCode", "parent", "parentId", "code"]


# ── Selenium-Setup ────────────────────────────────────────────────────────────

def _make_driver(headless: bool = False):
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
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    try:
        svc = Service(ChromeDriverManager().install())
        drv = webdriver.Chrome(service=svc, options=opts)
    except Exception:
        drv = webdriver.Chrome(options=opts)

    # maxPostDataSize damit POST-Bodies im Performance-Log erscheinen
    drv.execute_cdp_cmd("Network.enable", {"maxPostDataSize": 65536})
    return drv


# ── Cookie-Banner wegklicken ──────────────────────────────────────────────────

def _accept_cookies(driver):
    from selenium.webdriver.common.by import By

    selectors = [
        "#onetrust-accept-btn-handler",
        "button[id*='accept']", "button[class*='accept']",
        "button[id*='cookie']", "button[class*='cookie']",
        "button[id*='consent']", "button[class*='consent']",
        ".cc-accept", "[data-testid='cookie-accept']", "button.agree",
    ]
    time.sleep(2)
    for sel in selectors:
        try:
            for btn in driver.find_elements(By.CSS_SELECTOR, sel):
                if btn.is_displayed():
                    btn.click()
                    log.info("  Cookie-Banner akzeptiert (%s)", sel)
                    time.sleep(1)
                    return True
        except Exception:
            pass
    try:
        for btn in driver.find_elements(By.TAG_NAME, "button"):
            txt = btn.text.strip().lower()
            if any(kw in txt for kw in
                   ["akzept", "accept", "agree", "zustimm", "alle erlauben"]):
                if btn.is_displayed():
                    btn.click()
                    log.info("  Cookie-Banner Text-Match: '%s'", btn.text.strip())
                    time.sleep(1)
                    return True
    except Exception:
        pass
    return False


# ── Netzwerk-Logs auslesen (Request + Response) ───────────────────────────────

def _capture_all_calls(driver) -> list[dict]:
    """
    Liest den Performance-Log. Liefert Paare aus Request+Response.
    requestWillBeSent enthält den POST-Body (dank maxPostDataSize=65536).
    """
    req_info: dict = {}
    calls:    list = []

    try:
        logs = driver.get_log("performance")
    except Exception:
        return calls

    for entry in logs:
        try:
            msg    = json.loads(entry["message"])["message"]
            method = msg.get("method", "")
            params = msg.get("params", {})
        except Exception:
            continue

        if method == "Network.requestWillBeSent":
            rid = params.get("requestId", "")
            req = params.get("request", {})
            req_info[rid] = {
                "url":         req.get("url", ""),
                "http_method": req.get("method", "GET"),
                "post_data":   req.get("postData", ""),
                "headers":     dict(req.get("headers", {})),
            }

        elif method == "Network.responseReceived":
            rid  = params.get("requestId", "")
            resp = params.get("response", {})
            mime = resp.get("mimeType", "")
            if "json" not in mime and "javascript" not in mime and "text" not in mime:
                continue
            try:
                body_raw = driver.execute_cdp_cmd(
                    "Network.getResponseBody", {"requestId": rid})
                body_str = body_raw.get("body", "")
                if not body_str:
                    continue
                try:
                    body = json.loads(body_str)
                except Exception:
                    body = body_str
                info = req_info.get(rid, {})
                calls.append({
                    "url":         resp.get("url") or info.get("url", ""),
                    "http_method": info.get("http_method", "GET"),
                    "post_data":   info.get("post_data", ""),
                    "headers":     info.get("headers", {}),
                    "response":    body,
                    "status":      resp.get("status", 0),
                })
            except Exception:
                pass

    return calls


# ── Browser-seitige Fetch-Requests ───────────────────────────────────────────

def _js_fetch(driver, url: str, method: str = "GET",
              content_type: str = "", body: str = "", timeout: int = 20):
    """Fetch im Browser-Kontext (hat Session-Cookies)."""
    script = """
    const [resolve, url, method, contentType, body] = arguments;
    const opts = {method, credentials: 'same-origin',
                  headers: {'X-Requested-With': 'XMLHttpRequest',
                             'Accept': 'application/json, text/plain, */*'}};
    if (contentType) opts.headers['Content-Type'] = contentType;
    if (body)        opts.body = body;
    fetch(url, opts)
      .then(r => r.text())
      .then(t => {
          let d = null;
          try { d = JSON.parse(t); } catch(e) {}
          resolve({ok: true, data: d, raw: t.substring(0, 2000)});
      })
      .catch(e => resolve({ok: false, err: e.toString()}));
    """
    try:
        driver.set_script_timeout(timeout)
        result = driver.execute_async_script(script, url, method, content_type, body)
        if result and result.get("ok"):
            return result.get("data") if result.get("data") is not None else result.get("raw")
    except Exception as e:
        log.debug("  JS-Fetch Fehler: %s", e)
    return None


def _form_post(driver, url: str, data: dict, timeout: int = 20):
    """POST mit application/x-www-form-urlencoded (TYPO3-Standard)."""
    body = urllib.parse.urlencode(data, doseq=True)
    return _js_fetch(driver, url, "POST",
                     "application/x-www-form-urlencoded; charset=UTF-8", body, timeout)


def _json_post(driver, url: str, data: dict, timeout: int = 20):
    """POST mit application/json."""
    return _js_fetch(driver, url, "POST", "application/json",
                     json.dumps(data), timeout)


def _js_get(driver, url: str, timeout: int = 20):
    return _js_fetch(driver, url, "GET", "", "", timeout)


# ── Response validieren ───────────────────────────────────────────────────────

def _has_items(data) -> bool:
    if isinstance(data, list) and data:
        return True
    if isinstance(data, dict):
        for key in ["items", "data", "results", "categories", "classes",
                    "content", "list", "nodes", "children", "segments"]:
            val = data.get(key)
            if isinstance(val, list) and val:
                return True
        for v in data.values():
            if isinstance(v, list) and v:
                return True
    return False


# ── TYPO3-API Brute-Force (form-encoded POST) ─────────────────────────────────

def _try_typo3_api(driver, version: str = "12.0", parent: str = None,
                   known_cfg: dict | None = None) -> tuple:
    """
    Probiert TYPO3-Extbase-Varianten mit form-encoded POST.
    Gibt (response_data, cfg_dict) zurück; cfg_dict = None wenn kein Treffer.
    known_cfg beschleunigt Folgeaufrufe (bereits bekannte Konfiguration).
    """
    if known_cfg:
        payload = dict(known_cfg["payload_template"])
        if known_cfg.get("version_key"):
            payload[known_cfg["version_key"]] = version
        if known_cfg.get("parent_key"):
            payload[known_cfg["parent_key"]] = parent or ""
        for post_fn in (_form_post, _json_post):
            result = post_fn(driver, known_cfg["url"], payload)
            if _has_items(result):
                return result, known_cfg
        return None, None

    for ext in TYPO3_EXTS:
        for action, controller in TYPO3_ACTIONS:
            prefix = f"tx_{ext}_content"
            for vp in VERSION_PARAM_NAMES:
                for pp in PARENT_PARAM_NAMES:
                    payload = {
                        f"{prefix}[action]":     action,
                        f"{prefix}[controller]": controller,
                        f"{prefix}[{vp}]":       version,
                        f"{prefix}[{pp}]":       parent or "",
                    }
                    for url in API_URLS:
                        result = _form_post(driver, url, payload)
                        if _has_items(result):
                            log.info("  ✓ TYPO3: %s | tx_%s[%s/%s]",
                                     url, ext, action, vp)
                            cfg = {
                                "url": url,
                                "payload_template": {
                                    f"{prefix}[action]":     action,
                                    f"{prefix}[controller]": controller,
                                },
                                "version_key": f"{prefix}[{vp}]",
                                "parent_key":  f"{prefix}[{pp}]",
                            }
                            return result, cfg

                        if not parent:
                            p2 = {k: v for k, v in payload.items()
                                  if k != f"{prefix}[{pp}]"}
                            result = _form_post(driver, url, p2)
                            if _has_items(result):
                                log.info("  ✓ TYPO3 (kein Parent): %s | tx_%s[%s]",
                                         url, ext, action)
                                cfg = {
                                    "url": url,
                                    "payload_template": {
                                        f"{prefix}[action]":     action,
                                        f"{prefix}[controller]": controller,
                                    },
                                    "version_key": f"{prefix}[{vp}]",
                                    "parent_key":  None,
                                }
                                return result, cfg

    # JSON-POST-Fallback (weniger üblich bei TYPO3)
    for ext in TYPO3_EXTS[:3]:
        for action, controller in TYPO3_ACTIONS[:5]:
            payload = {"action": action, "controller": controller,
                       "version": version, "parent": parent or ""}
            for url in API_URLS[:3]:
                result = _json_post(driver, url, payload)
                if _has_items(result):
                    log.info("  ✓ JSON-POST: %s | %s", url, action)
                    cfg = {"url": url,
                           "payload_template": {"action": action, "controller": controller},
                           "version_key": "version", "parent_key": "parent"}
                    return result, cfg

    return None, None


# ── Discover-Modus ────────────────────────────────────────────────────────────

def discover(driver, wait_sec: int = 45, progress_cb=None) -> dict:
    """
    Öffnet die Seite, klickt selbst durch, zeigt echte API-Calls mit POST-Bodies.
    Gibt gefundene {url: response} zurück.
    """
    from selenium.webdriver.common.by import By

    p = progress_cb or log.info
    p("=== DISCOVER-MODUS ===")
    p(f"Seite laden: {TARGET_URL}")

    driver.get(TARGET_URL)
    time.sleep(4)
    _accept_cookies(driver)
    time.sleep(3)

    p("Klicke Kategorien an ...")
    clicked = False
    for sel in [
        "select option:not([value=''])", "option[value*='.']",
        "[class*='version'] a", ".version-select option",
        ".category-item a", ".cat-link", ".tree-item a",
        "[class*='categor'] a", "[class*='segment'] a",
        "ul.nav a", ".sidebar a", "li a",
    ]:
        try:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            for el in els:
                if el.is_displayed() and el.text.strip():
                    driver.execute_script("arguments[0].click();", el)
                    p(f"  Geklickt: '{el.text.strip()[:60]}'")
                    clicked = True
                    time.sleep(2)
                    break
            if clicked:
                break
        except Exception:
            pass

    time.sleep(3)
    calls = _capture_all_calls(driver)
    p(f"\nGefangene Netzwerk-Calls: {len(calls)} total")

    api_calls = [c for c in calls if any(kw in c.get("url", "").lower()
                 for kw in ["typo3", "eclass", "api", "ajax"])]

    result_urls: dict = {}
    if api_calls:
        p(f"\nAPI-relevante Calls ({len(api_calls)}):")
        for call in api_calls[:15]:
            url = call["url"]
            p(f"  ── {call['http_method']} {url}  (Status {call.get('status','?')})")
            if call.get("post_data"):
                p(f"     POST-Body: {call['post_data'][:400]}")
            resp = call.get("response")
            if resp:
                p(f"     Response:  {str(resp)[:200]}")
                result_urls[url] = resp
    else:
        p("Keine API-Calls gefunden.")
        p("Alle JSON-Calls:")
        for call in [c for c in calls if isinstance(c.get("response"), (dict, list))][:10]:
            p(f"  {call['http_method']} {call['url']} | POST: {call.get('post_data','')[:80]}")

    # Brute-Force Kurztest
    p("\nBrute-Force Kurztest ...")
    driver.get(TARGET_URL)
    time.sleep(4)
    _accept_cookies(driver)
    time.sleep(2)
    for ext in TYPO3_EXTS[:4]:
        action, controller = TYPO3_ACTIONS[0]
        prefix  = f"tx_{ext}_content"
        payload = {f"{prefix}[action]": action, f"{prefix}[controller]": controller,
                   f"{prefix}[version]": "12.0", f"{prefix}[parentCode]": ""}
        result = _form_post(driver, API_URLS[0], payload)
        ok     = "✓ DATEN!" if _has_items(result) else "✗ leer"
        p(f"  {ok} | tx_{ext}[{action}] → {str(result)[:100] if result else 'None'}")
        if _has_items(result):
            p(f"  >>> PAYLOAD: {payload}")

    p("\nDOM-Extraktion:")
    items = _extract_from_dom(driver)
    p(f"  {len(items)} Einträge im DOM")
    for item in items[:5]:
        p(f"  {item['code']} | {item['name_de']}")

    return result_urls


# ── DOM-Fallback ──────────────────────────────────────────────────────────────

CODE_RE = re.compile(r'^(\d{2}(?:-\d{2}){0,3})\s+(.+)$')


def _extract_from_dom(driver) -> list[dict]:
    from selenium.webdriver.common.by import By
    items: list = []
    seen:  set  = set()
    for sel in ["a", "li", "td", "span", ".category", ".class-item",
                "[class*='entry']", "[class*='categor']", "[class*='eclass']"]:
        try:
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                txt = el.text.strip()
                m   = CODE_RE.match(txt)
                if m and m.group(1) not in seen:
                    code = m.group(1)
                    seen.add(code)
                    depth  = code.count("-")
                    parent = "-".join(code.split("-")[:-1]) if "-" in code else ""
                    items.append({"code": code, "name_de": m.group(2).strip(),
                                  "name_en": "", "level": LEVELS.get(depth, "unbekannt"),
                                  "parent_code": parent})
        except Exception:
            pass
    return items


def _navigate_dom_scrape(driver, version: str) -> list[dict]:
    """DOM-Scraping mit versionierter URL als letzter Fallback."""
    for url in [
        f"{TARGET_URL}?version={urllib.parse.quote(version)}",
        f"{TARGET_URL}?tx_tpieclass_content[version]={urllib.parse.quote(version)}",
        f"https://eclass.eu/eclass-standard/content-suche/{urllib.parse.quote(version)}",
    ]:
        try:
            driver.get(url)
            time.sleep(3)
            items = _extract_from_dom(driver)
            if items:
                log.info("  DOM: %d Einträge von %s", len(items), url)
                return items
        except Exception:
            pass
    return []


# ── Haupt-Scraper ─────────────────────────────────────────────────────────────

class EclassScraper:

    def __init__(self, driver, api_base: str = None, progress_cb=None):
        self._drv          = driver
        self._api          = api_base
        self._results: list = []
        self._p            = progress_cb or log.info
        self._known_cfg: dict | None = None
        self._session_ready = False

    def _warmup(self):
        if self._session_ready:
            return
        log.info("  Lade Seite ...")
        self._drv.get(TARGET_URL)
        time.sleep(5)
        _accept_cookies(self._drv)
        time.sleep(2)
        self._session_ready = True

    def _parse_items(self, data) -> list[dict]:
        raw = []
        if isinstance(data, list):
            raw = data
        elif isinstance(data, dict):
            for key in ["items", "data", "results", "categories", "classes",
                        "content", "list", "nodes", "children", "segments"]:
                val = data.get(key)
                if isinstance(val, list) and val:
                    raw = val
                    break
            if not raw:
                for v in data.values():
                    if isinstance(v, list) and v:
                        raw = v
                        break
        items = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            code = (item.get("id") or item.get("code") or item.get("classId") or
                    item.get("identifier") or item.get("classificationCode") or "")
            name_de = (item.get("name_de") or item.get("preferredName") or
                       item.get("name") or item.get("title") or item.get("label") or "")
            name_en = item.get("name_en") or item.get("titleEn") or ""
            if isinstance(name_de, dict):
                name_en = name_de.get("en", "")
                name_de = name_de.get("de", "")
            has_ch = bool(item.get("hasChildren") or item.get("children")
                          or item.get("childCount", 0))
            if code:
                items.append({"code": str(code).strip(), "name_de": str(name_de).strip(),
                              "name_en": str(name_en).strip(), "children": has_ch})
        return items

    def _get_children(self, version: str, parent: str = None) -> list[dict]:
        result, cfg = _try_typo3_api(
            self._drv, version=version, parent=parent, known_cfg=self._known_cfg)
        if cfg and not self._known_cfg:
            self._known_cfg = cfg
            log.info("  API-Konfiguration gespeichert: %s", cfg.get("url"))
        return self._parse_items(result) if result else []

    def scrape_version(self, version: str) -> int:
        self._p(f"\n  === Version {version} ===")
        self._warmup()
        count = 0

        def _recurse(parent_code, depth):
            nonlocal count
            if depth > 3:
                return
            items = self._get_children(version, parent_code)
            if not items and depth == 0:
                log.warning("    Keine Daten für Version %s", version)
                return
            for item in items:
                code   = item["code"]
                depth_ = code.count("-")
                parent = "-".join(code.split("-")[:-1]) if "-" in code else ""
                self._results.append({
                    "version": version, "code": code,
                    "name_de": item["name_de"], "name_en": item["name_en"],
                    "level":   LEVELS.get(depth_, f"level{depth_}"),
                    "parent_code": parent,
                })
                count += 1
                if item.get("children") and depth < 3:
                    _recurse(code, depth + 1)

        _recurse(None, 0)

        if count == 0:
            log.info("  API leer – versuche DOM-Scraping für %s ...", version)
            dom_items = _navigate_dom_scrape(self._drv, version)
            self._session_ready = False
            for item in dom_items:
                item["version"] = version
                self._results.append(item)
                count += 1

        self._p(f"  → {count:,} Einträge für Version {version}")
        return count

    def run(self, versions: list[str] = None, out_csv: str = None,
            api_base: str = None) -> list[dict]:
        self._warmup()
        if versions is None:
            versions = ECLASS_VERSIONS
        self._p(f"  Versionen: {versions}")

        total = 0
        for v in versions:
            n = self.scrape_version(v)
            total += n
            if out_csv and self._results:
                _write_csv(self._results, out_csv)
                self._p(f"  Checkpoint: {total:,} Einträge → {out_csv}")

        if out_csv:
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
    p("│  Methode: Selenium + Chrome (TYPO3-API / DOM-Fallback)")
    p(f"│  Ausgabe: {CATALOG_FILENAME}  (in BASE_DIR)")
    p("└────────────────────────────────────────────────────────────")

    try:
        from selenium import webdriver  # noqa
    except ImportError:
        raise RuntimeError("py -m pip install selenium webdriver-manager")

    out_csv = os.path.join(_cfg.BASE_DIR, CATALOG_FILENAME)
    driver  = _make_driver(headless=False)
    try:
        scraper = EclassScraper(driver, progress_cb=p)
        results = scraper.run(out_csv=out_csv)
        if results:
            p(f"  Gesamt: {len(results):,} Einträge", tag="ok")
            p(f"  Datei:  {out_csv}", tag="ok")
        else:
            p("  Keine Daten. Bitte --discover ausführen.", tag="error")
    finally:
        driver.quit()


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cli():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(description="eClass-Katalog Scraper")
    ap.add_argument("--discover",     action="store_true",
                    help="Öffnet Browser, fängt echte API-Calls ab (inkl. POST-Body)")
    ap.add_argument("--version",      metavar="V",
                    help="Nur diese Version, z.B. '12.0'")
    ap.add_argument("--all-versions", action="store_true",
                    help="Alle bekannten Versionen")
    ap.add_argument("--api",          metavar="URL",
                    help="API-Base-URL manuell (überschreibt Auto-Detect)")
    ap.add_argument("--out",          default="eclass_catalog.csv")
    ap.add_argument("--wait",         type=int, default=45,
                    help="Wartezeit für --discover in Sekunden")
    args = ap.parse_args()

    driver = _make_driver(headless=False)
    try:
        if args.discover:
            calls = discover(driver, wait_sec=args.wait, progress_cb=log.info)
            if calls:
                print("\nGefundene API-Calls:")
                for url in calls:
                    print(f"  {url}")
            return

        versions = ([args.version] if args.version
                    else ECLASS_VERSIONS if args.all_versions
                    else ["12.0"])

        scraper = EclassScraper(driver, api_base=args.api, progress_cb=log.info)
        results = scraper.run(versions=versions, out_csv=args.out, api_base=args.api)

        if results:
            log.info("Fertig: %d Einträge → %s", len(results), args.out)
        else:
            log.warning("Keine Daten – bitte --discover ausführen")
    finally:
        driver.quit()


if __name__ == "__main__":
    _cli()
