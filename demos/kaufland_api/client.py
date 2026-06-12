"""
Kaufland Seller API Client – Technik-Demo

REST-Wrapper mit HMAC-SHA256-Authentifizierung, Retry-Logik und Logging.

HINWEIS: Diese Demo ist NICHT in die BMEcat-Pipeline verdrahtet. Sie zeigt,
wie eine signierte Anbindung an die Kaufland Seller API aussehen würde
(Referenz für eine spätere lib/channels/kaufland.py).

Bereinigt gegenüber dem Original:
  - doppelt vorhandene Methoden (_handle_response/request/get/...) entfernt
  - Bug behoben: _get_headers() wurde im Duplikat ohne Argumente aufgerufen
  - eigenständig importierbar (relative Imports statt 'from api import ...')

Credentials werden NICHT im Repo gespeichert – per Konstruktor oder
Umgebungsvariablen übergeben (siehe demo.py).
"""

import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .endpoints import HTTPMethod

logger = logging.getLogger(__name__)


class APIException(Exception):
    """Basis-Exception für API-Fehler."""


class APIAuthException(APIException):
    """Authentifizierungsfehler."""


class APIRateLimitException(APIException):
    """Rate-Limit überschritten."""


class KauflandAPIClient:
    """
    Client für die Kaufland Seller API.

    Authentifizierung: HMAC-SHA256-signierte Requests.
    Basis-URL: https://sellerapi.kaufland.com/v2
    """

    def __init__(
        self,
        client_key: str,
        secret_key: str,
        base_url: str = "https://sellerapi.kaufland.com/v2",
        timeout: int = 30,
        retry_attempts: int = 3,
    ):
        self.client_key     = client_key.strip()
        self.secret_key     = secret_key.strip()
        self.base_url       = base_url.rstrip("/")
        self.timeout        = timeout
        self.retry_attempts = retry_attempts

        self.session = self._create_session()
        logger.info("API-Client initialisiert für %s", self.base_url)

    def _create_session(self) -> requests.Session:
        """Session mit exponentiellem Backoff-Retry."""
        session = requests.Session()
        retry_strategy = Retry(
            total=self.retry_attempts,
            backoff_factor=1,  # 1s, 2s, 4s, ...
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    # ── Signatur / Header ─────────────────────────────────────────────────────

    def _sign_request(self, method: str, uri: str, body: str,
                      timestamp: int) -> str:
        """
        HMAC-SHA256-Signatur nach Kaufland-Schema.

        Signatur-String = "\\n".join([method, uri, body, timestamp]),
        signiert mit dem Secret Key.
        """
        plain_text = "\n".join([method, uri, body, str(timestamp)])
        hmac_obj = hmac.new(
            self.secret_key.encode(), plain_text.encode(), hashlib.sha256
        )
        return hmac_obj.hexdigest()

    def _get_headers(self, method: str, uri: str, body: str) -> Dict[str, str]:
        """Request-Header inkl. Signatur, Client-Key und Timestamp."""
        timestamp = int(time.time())
        signature = self._sign_request(method, uri, body, timestamp)
        return {
            "Accept":          "application/json",
            "Content-Type":    "application/json",
            "User-Agent":      "KauflandDemo/1.0",
            "Shop-Client-Key": self.client_key,
            "Shop-Timestamp":  str(timestamp),
            "Shop-Signature":  signature,
        }

    # ── Request-Handling ──────────────────────────────────────────────────────

    def _handle_response(self, response: requests.Response) -> Dict[str, Any]:
        """Wertet die API-Response aus und wirft passende Exceptions."""
        if response.status_code == 401:
            logger.error("Authentifizierungsfehler – Client/Secret Key ungültig")
            raise APIAuthException("Authentifizierung fehlgeschlagen")
        if response.status_code == 429:
            logger.warning("Rate-Limit erreicht")
            raise APIRateLimitException("Rate-Limit überschritten")
        if response.status_code >= 400:
            detail = response.text or "Unbekannter Fehler"
            logger.error("API-Fehler %s: %s", response.status_code, detail)
            raise APIException(f"API-Fehler {response.status_code}: {detail}")

        response.raise_for_status()

        if not response.content:
            return {"success": True, "status_code": response.status_code}
        try:
            return response.json()
        except requests.exceptions.JSONDecodeError:
            logger.warning("Response konnte nicht als JSON geparst werden")
            return {"raw": response.text, "status_code": response.status_code}

    def request(self, method: str, endpoint: str,
                data: Optional[Dict[str, Any]] = None,
                params: Optional[Dict[str, Any]] = None,
                **kwargs) -> Dict[str, Any]:
        """Generischer, signierter API-Request."""
        url  = f"{self.base_url}{endpoint}"
        body = json.dumps(data) if data else ""
        headers = self._get_headers(method, url, body)

        logger.debug("%s %s", method, url)
        try:
            response = self.session.request(
                method=method, url=url, headers=headers, json=data,
                params=params, timeout=self.timeout, **kwargs,
            )
            return self._handle_response(response)
        except requests.exceptions.RequestException as e:
            logger.error("Request-Fehler: %s", e)
            raise APIException(f"Request fehlgeschlagen: {e}")

    # ── HTTP-Verben ───────────────────────────────────────────────────────────

    def get(self, endpoint: str,
            params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self.request(HTTPMethod.GET, endpoint, params=params)

    def post(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return self.request(HTTPMethod.POST, endpoint, data=data)

    def put(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return self.request(HTTPMethod.PUT, endpoint, data=data)

    def patch(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return self.request(HTTPMethod.PATCH, endpoint, data=data)

    def delete(self, endpoint: str) -> Dict[str, Any]:
        return self.request(HTTPMethod.DELETE, endpoint)

    # ── Convenience: Units / Angebote ─────────────────────────────────────────

    def get_units(self, **params) -> Dict[str, Any]:
        logger.info("Hole Units/Angebote ...")
        return self.get("/units", params=params)

    def get_unit(self, unit_id: int) -> Dict[str, Any]:
        logger.info("Hole Unit %s ...", unit_id)
        return self.get(f"/units/{unit_id}")

    def create_unit(self, data: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("Erstelle Unit ...")
        return self.post("/units", data)

    def update_unit(self, unit_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("Aktualisiere Unit %s ...", unit_id)
        return self.patch(f"/units/{unit_id}", data)

    def delete_unit(self, unit_id: int) -> Dict[str, Any]:
        logger.info("Lösche Unit %s ...", unit_id)
        return self.delete(f"/units/{unit_id}")

    # ── Convenience: Kategorien / Bestellungen ────────────────────────────────

    def get_categories(self, **params) -> Dict[str, Any]:
        logger.info("Hole Kategorien ...")
        return self.get("/categories", params=params)

    def get_category(self, category_id: int) -> Dict[str, Any]:
        logger.info("Hole Kategorie %s ...", category_id)
        return self.get(f"/categories/{category_id}")

    def get_orders(self, **params) -> Dict[str, Any]:
        logger.info("Hole Bestellungen ...")
        return self.get("/orders", params=params)

    def get_order(self, order_id: int) -> Dict[str, Any]:
        logger.info("Hole Bestellung %s ...", order_id)
        return self.get(f"/orders/{order_id}")

    def close(self):
        """Schließe die HTTP-Session."""
        self.session.close()
        logger.info("API-Session geschlossen")
