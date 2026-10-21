# lib/ebay_api.py – eBay-Anbindung (OAuth2 + Trading API)
#
# Bestehende Angebote (über Seller Hub / File Exchange angelegt) lassen sich
# nur über die klassische Trading API per Item number pflegen – die neuere
# Inventory API kennt sie nicht. Verwendet werden:
#   GetMyeBaySelling        – aktive Angebote mit SKU/Menge/Preis abrufen
#   ReviseInventoryStatus   – Menge (und optional Preis) je Item number ändern
#   EndFixedPriceItem       – Angebot beenden (Bestand 0)
#   AddFixedPriceItem       – nur Sandbox: Testangebot anlegen
#
# Authentifizierung: OAuth2 "Authorization Code Grant" (User-Token).
#   1. build_authorize_url() im Browser öffnen, mit dem Verkäufer-Account
#      zustimmen – eBay leitet auf die RuName-Accept-Seite um, in der
#      Adresszeile steht ?code=...
#   2. exchange_code(code) → Refresh-Token (ca. 18 Monate gültig), wird
#      in config_user.json (Verbindung ebay / ebay_sandbox) gespeichert.
#   3. Zugriffstoken (2 h) werden daraus automatisch erneuert.
#
# Konfiguration: config.CONNECTIONS["ebay"] (Production) und
# CONNECTIONS["ebay_sandbox"]; CONNECTIONS["ebay"]["environment"] entscheidet,
# welches Keyset die Tasks verwenden ("sandbox" | "production").
#
# Keine externen Abhängigkeiten (urllib + xml.etree).

import base64
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as _xml_escape

log = logging.getLogger(__name__)

try:
    from lib.credentials import decrypt as _decrypt, encrypt as _encrypt
except Exception:                       # pragma: no cover
    def _decrypt(v): return v
    def _encrypt(v): return v

_ENDPOINTS = {
    "production": {
        "auth":    "https://auth.ebay.com/oauth2/authorize",
        "token":   "https://api.ebay.com/identity/v1/oauth2/token",
        "trading": "https://api.ebay.com/ws/api.dll",
    },
    "sandbox": {
        "auth":    "https://auth.sandbox.ebay.com/oauth2/authorize",
        "token":   "https://api.sandbox.ebay.com/identity/v1/oauth2/token",
        "trading": "https://api.sandbox.ebay.com/ws/api.dll",
    },
}

# Trading-API-Aufrufe mit OAuth-User-Token brauchen diese Scopes
SCOPES = [
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
]

COMPAT_LEVEL = "1193"
SITE_ID_DE   = "77"
_NS = "urn:ebay:apis:eBLBaseComponents"
_TIMEOUT = 60


class EbayError(RuntimeError):
    pass


# ── Konfiguration ─────────────────────────────────────────────────────────────

def resolve_config(connections: dict, environment: str = None) -> tuple[str, dict]:
    """
    Liefert (environment, keyset-Konfig). environment aus Parameter, sonst aus
    CONNECTIONS["ebay"]["environment"] (Standard: sandbox).
    """
    env = (environment or connections.get("ebay", {}).get("environment") or "sandbox").strip().lower()
    if env not in _ENDPOINTS:
        raise EbayError(f"Unbekannte eBay-Umgebung '{env}' (erlaubt: sandbox, production)")
    cfg = dict(connections.get("ebay_sandbox" if env == "sandbox" else "ebay", {}))
    cfg["_environment"] = env
    return env, cfg


def _require(cfg: dict, *keys):
    missing = [k for k in keys if not (cfg.get(k) or "").strip()]
    if missing:
        raise EbayError(
            f"eBay-Konfiguration ({cfg.get('_environment', '?')}) unvollständig: "
            f"{', '.join(missing)} fehlt – Konfiguration → Verbindungen → "
            f"{'ebay_sandbox' if cfg.get('_environment') == 'sandbox' else 'ebay'}")


# ── OAuth2 ────────────────────────────────────────────────────────────────────

def build_authorize_url(cfg: dict) -> str:
    _require(cfg, "client_id", "ru_name")
    env = cfg.get("_environment", "sandbox")
    q = urllib.parse.urlencode({
        "client_id":     cfg["client_id"].strip(),
        "redirect_uri":  cfg["ru_name"].strip(),
        "response_type": "code",
        "scope":         " ".join(SCOPES),
        "prompt":        "login",
    })
    return f"{_ENDPOINTS[env]['auth']}?{q}"


def _basic_auth(cfg: dict) -> str:
    raw = f"{cfg['client_id'].strip()}:{_decrypt(cfg['client_secret']).strip()}"
    return "Basic " + base64.b64encode(raw.encode()).decode()


def _token_request(cfg: dict, form: dict) -> dict:
    env = cfg.get("_environment", "sandbox")
    data = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(_ENDPOINTS[env]["token"], data=data, method="POST", headers={
        "Content-Type":  "application/x-www-form-urlencoded",
        "Authorization": _basic_auth(cfg),
    })
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            j = json.loads(body)
            msg = j.get("error_description") or j.get("error") or body
        except Exception:
            msg = body
        raise EbayError(f"eBay Token-Fehler ({e.code}): {msg}") from None


def extract_code(value: str) -> str:
    """Nimmt den rohen Code oder die komplette Redirect-URL (…?code=…&expires_in=…)."""
    value = (value or "").strip()
    if "code=" in value:
        qs = urllib.parse.urlparse(value).query if "://" in value else value.split("?", 1)[-1]
        code = urllib.parse.parse_qs(qs).get("code", [""])[0]
        return urllib.parse.unquote(code) if code else value
    return urllib.parse.unquote(value)


def exchange_code(cfg: dict, code: str) -> dict:
    """Autorisierungscode → {refresh_token, refresh_token_expires_in, access_token, ...}"""
    _require(cfg, "client_id", "client_secret", "ru_name")
    return _token_request(cfg, {
        "grant_type":   "authorization_code",
        "code":         extract_code(code),
        "redirect_uri": cfg["ru_name"].strip(),
    })


_access_cache: dict = {}   # env -> (token, expires_at)


def get_access_token(cfg: dict) -> str:
    _require(cfg, "client_id", "client_secret", "refresh_token")
    env = cfg.get("_environment", "sandbox")
    tok, exp = _access_cache.get(env, (None, 0))
    if tok and time.time() < exp - 120:
        return tok
    j = _token_request(cfg, {
        "grant_type":    "refresh_token",
        "refresh_token": _decrypt(cfg["refresh_token"]).strip(),
        "scope":         " ".join(SCOPES),
    })
    tok = j["access_token"]
    _access_cache[env] = (tok, time.time() + int(j.get("expires_in", 7200)))
    return tok


def encrypt_secret(value: str) -> str:
    """Für die Ablage in config_user.json (Fernet, falls verfügbar)."""
    try:
        return _encrypt(value) if value else value
    except Exception:
        return value


# ── Trading API ───────────────────────────────────────────────────────────────

def _t(el, tag: str, default: str = "") -> str:
    found = el.find(f"{{{_NS}}}{tag}")
    return (found.text or "").strip() if found is not None and found.text else default


def trading_call(cfg: dict, call_name: str, body_xml: str, site_id: str = None) -> ET.Element:
    """
    Führt einen Trading-API-Aufruf aus. body_xml = Inhalt des <…Request>-Elements.
    Gibt das Response-Element zurück; wirft EbayError bei Ack=Failure.
    """
    env = cfg.get("_environment", "sandbox")
    token = get_access_token(cfg)
    xml = (f'<?xml version="1.0" encoding="utf-8"?>'
           f'<{call_name}Request xmlns="{_NS}">'
           f'<ErrorLanguage>de_DE</ErrorLanguage><WarningLevel>High</WarningLevel>'
           f'{body_xml}</{call_name}Request>')
    req = urllib.request.Request(_ENDPOINTS[env]["trading"], data=xml.encode("utf-8"), method="POST", headers={
        "Content-Type":                     "text/xml",
        "X-EBAY-API-COMPATIBILITY-LEVEL":   COMPAT_LEVEL,
        "X-EBAY-API-CALL-NAME":             call_name,
        "X-EBAY-API-SITEID":                site_id or cfg.get("site_id") or SITE_ID_DE,
        "X-EBAY-API-IAF-TOKEN":             token,
    })
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        raise EbayError(f"{call_name}: HTTP {e.code} – {e.read().decode(errors='replace')[:400]}") from None
    except urllib.error.URLError as e:
        raise EbayError(f"{call_name}: Verbindung fehlgeschlagen – {e.reason}") from None
    root = ET.fromstring(raw)
    ack = _t(root, "Ack")
    if ack not in ("Success", "Warning"):
        errs = []
        for err in root.findall(f"{{{_NS}}}Errors"):
            errs.append(f"[{_t(err, 'ErrorCode')}] {_t(err, 'LongMessage') or _t(err, 'ShortMessage')}")
        raise EbayError(f"{call_name}: {ack} – " + ("; ".join(errs) or raw.decode(errors='replace')[:400]))
    if ack == "Warning":
        for err in root.findall(f"{{{_NS}}}Errors"):
            log.warning(f"{call_name} Warnung [{_t(err, 'ErrorCode')}]: {_t(err, 'LongMessage')}")
    return root


def get_user(cfg: dict) -> dict:
    """GetUser – Verbindungstest; liefert {user_id, email, site}."""
    root = trading_call(cfg, "GetUser", "")
    user = root.find(f"{{{_NS}}}User")
    if user is None:
        return {}
    return {"user_id": _t(user, "UserID"), "email": _t(user, "Email"), "site": _t(user, "Site")}


def get_active_listings(cfg: dict, progress_cb=None) -> list[dict]:
    """
    GetMyeBaySelling / ActiveList (alle Seiten).
    Returns [{item_id, sku, title, quantity, quantity_sold, price, currency, listing_type}]
    quantity = noch verfügbare Menge.
    """
    p = progress_cb or (lambda m, **kw: None)
    items, page, total_pages = [], 1, 1
    while page <= total_pages:
        body = (f"<ActiveList><Include>true</Include><IncludeNotes>false</IncludeNotes>"
                f"<Pagination><EntriesPerPage>200</EntriesPerPage><PageNumber>{page}</PageNumber></Pagination>"
                f"</ActiveList><DetailLevel>ReturnAll</DetailLevel>")
        root = trading_call(cfg, "GetMyeBaySelling", body)
        active = root.find(f"{{{_NS}}}ActiveList")
        if active is None:
            break
        pag = active.find(f"{{{_NS}}}PaginationResult")
        if pag is not None:
            total_pages = int(_t(pag, "TotalNumberOfPages", "1") or 1)
        for it in active.iter(f"{{{_NS}}}Item"):
            sell = it.find(f"{{{_NS}}}SellingStatus")
            price_el = sell.find(f"{{{_NS}}}CurrentPrice") if sell is not None else None
            qty_total = int(_t(it, "Quantity", "0") or 0)
            qty_sold  = int(_t(sell, "QuantitySold", "0") or 0) if sell is not None else 0
            qty_avail_raw = _t(it, "QuantityAvailable", "")
            qty_avail = int(qty_avail_raw) if qty_avail_raw else max(qty_total - qty_sold, 0)
            items.append({
                "item_id":       _t(it, "ItemID"),
                "sku":           _t(it, "SKU"),
                "title":         _t(it, "Title"),
                "quantity":      qty_avail,
                "quantity_sold": qty_sold,
                "price":         (price_el.text or "").strip() if price_el is not None else "",
                "currency":      price_el.get("currencyID", "") if price_el is not None else "",
                "listing_type":  _t(it, "ListingType"),
            })
        p(f"eBay: Seite {page}/{total_pages} – {len(items)} aktive Angebote")
        page += 1
    return items


def revise_inventory_status(cfg: dict, changes: list[dict]) -> list[dict]:
    """
    ReviseInventoryStatus – bis zu 4 Angebote je Aufruf.
    changes: [{item_id, quantity, price (optional)}]
    Returns Liste mit {item_id, ok, message}.
    """
    results = []
    for i in range(0, len(changes), 4):
        chunk = changes[i:i + 4]
        body = ""
        for c in chunk:
            body += f"<InventoryStatus><ItemID>{_xml_escape(str(c['item_id']))}</ItemID>"
            if c.get("quantity") is not None:
                body += f"<Quantity>{int(c['quantity'])}</Quantity>"
            if c.get("price") not in (None, ""):
                body += f"<StartPrice>{c['price']}</StartPrice>"
            body += "</InventoryStatus>"
        try:
            root = trading_call(cfg, "ReviseInventoryStatus", body)
            # Fehler je Item werden als Warnung/Errors mit ItemID gemeldet
            failed = {}
            for err in root.findall(f"{{{_NS}}}Errors"):
                for par in err.findall(f"{{{_NS}}}ErrorParameters"):
                    if par.get("ParamID") == "ItemID":
                        failed[_t(par, "Value")] = _t(err, "LongMessage")
            for c in chunk:
                iid = str(c["item_id"])
                results.append({"item_id": iid, "ok": iid not in failed,
                                "message": failed.get(iid, "OK")})
        except EbayError as e:
            for c in chunk:
                results.append({"item_id": str(c["item_id"]), "ok": False, "message": str(e)})
    return results


def end_fixed_price_item(cfg: dict, item_id: str, reason: str = "NotAvailable") -> dict:
    body = (f"<ItemID>{_xml_escape(str(item_id))}</ItemID>"
            f"<EndingReason>{reason}</EndingReason>")
    try:
        root = trading_call(cfg, "EndFixedPriceItem", body)
        return {"item_id": str(item_id), "ok": True, "message": "beendet " + _t(root, "EndTime")}
    except EbayError as e:
        return {"item_id": str(item_id), "ok": False, "message": str(e)}


def add_test_listing(cfg: dict, sku: str, title: str, price: str = "9.99",
                     quantity: int = 5, category_id: str = "171949") -> str:
    """
    Nur Sandbox: minimales Festpreis-Testangebot (GTC) anlegen. Gibt ItemID zurück.
    Hinweis: Die Sandbox verlangt je nach Account Business Policies oder
    Zahlungs-/Rückgabeangaben; Fehlermeldungen kommen als EbayError zurück.
    """
    if cfg.get("_environment") != "sandbox":
        raise EbayError("Testangebote nur in der Sandbox")
    body = f"""<Item>
<Title>{_xml_escape(title)}</Title>
<Description>{_xml_escape('Testangebot ' + sku + ' (Sandbox) – automatisch angelegt vom BMEcat-Tool.')}</Description>
<PrimaryCategory><CategoryID>{category_id}</CategoryID></PrimaryCategory>
<StartPrice>{price}</StartPrice>
<Quantity>{int(quantity)}</Quantity>
<SKU>{_xml_escape(sku)}</SKU>
<ConditionID>1000</ConditionID>
<Country>DE</Country>
<Currency>EUR</Currency>
<Location>Wermelskirchen</Location>
<PostalCode>42929</PostalCode>
<ListingDuration>GTC</ListingDuration>
<ListingType>FixedPriceItem</ListingType>
<DispatchTimeMax>3</DispatchTimeMax>
<Site>Germany</Site>
<ReturnPolicy><ReturnsAcceptedOption>ReturnsAccepted</ReturnsAcceptedOption>
<ReturnsWithinOption>Days_30</ReturnsWithinOption><ShippingCostPaidByOption>Buyer</ShippingCostPaidByOption></ReturnPolicy>
<ShippingDetails><ShippingType>Flat</ShippingType>
<ShippingServiceOptions><ShippingServicePriority>1</ShippingServicePriority>
<ShippingService>DE_DHLPaket</ShippingService><ShippingServiceCost>4.99</ShippingServiceCost>
</ShippingServiceOptions></ShippingDetails>
</Item>"""
    root = trading_call(cfg, "AddFixedPriceItem", body)
    return _t(root, "ItemID")
