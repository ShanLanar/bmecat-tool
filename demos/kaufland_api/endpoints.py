"""
Kaufland Seller API – Endpoint-Definitionen

Zentrale Sammlung der REST-Endpoints und HTTP-Methoden.
Teil der Technik-Demo (demos/kaufland_api) – nicht in die Pipeline verdrahtet.
"""


class KauflandEndpoints:
    """Zentrale Definition aller Kaufland API Endpoints."""

    # Produkte
    PRODUCTS        = "/products"
    PRODUCT_DETAIL  = "/products/{product_id}"
    PRODUCT_CREATE  = "/products"
    PRODUCT_UPDATE  = "/products/{product_id}"
    PRODUCT_DELETE  = "/products/{product_id}"

    # Bestand
    INVENTORY        = "/products/{product_id}/inventory"
    INVENTORY_UPDATE = "/products/{product_id}/inventory"
    STOCK_LEVELS     = "/products/{product_id}/stock"

    # Preise
    PRICES       = "/products/{product_id}/prices"
    PRICE_UPDATE = "/products/{product_id}/prices"
    OFFER_UPDATE = "/products/{product_id}/offer"

    # Kategorien
    CATEGORIES          = "/categories"
    CATEGORY_DETAIL     = "/categories/{category_id}"
    CATEGORY_ATTRIBUTES = "/categories/{category_id}/attributes"

    # Attribute
    ATTRIBUTES       = "/attributes"
    ATTRIBUTE_VALUES = "/attributes/{attribute_id}/values"

    # Media/Bilder
    PRODUCT_IMAGES = "/products/{product_id}/images"
    IMAGE_UPLOAD   = "/products/{product_id}/images"

    # Fulfillment
    FULFILLMENT = "/orders/{order_id}/fulfillment"

    # Suchfunktionen
    SEARCH_PRODUCTS = "/products/search"

    @staticmethod
    def get_full_url(base_url: str, endpoint: str, **kwargs) -> str:
        """
        Konstruiere komplette API-URL mit Parametern.

        Args:
            base_url: Basis-URL der API
            endpoint: Endpoint-Template (z.B. "/products/{product_id}")
            **kwargs: Parameter zum Ersetzen (z.B. product_id=123)

        Returns:
            Vollständige API-URL
        """
        url = endpoint
        for key, value in kwargs.items():
            url = url.replace(f"{{{key}}}", str(value))
        return f"{base_url.rstrip('/')}{url}"


class HTTPMethod:
    """HTTP-Methoden."""
    GET    = "GET"
    POST   = "POST"
    PUT    = "PUT"
    PATCH  = "PATCH"
    DELETE = "DELETE"
