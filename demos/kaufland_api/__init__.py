"""
Kaufland Seller API – Technik-Demo (nicht in die Pipeline verdrahtet).

Referenz-Implementierung einer HMAC-SHA256-signierten Anbindung an die
Kaufland Seller API. Siehe README.md und demo.py.
"""

from .client import (
    APIAuthException,
    APIException,
    APIRateLimitException,
    KauflandAPIClient,
)
from .endpoints import HTTPMethod, KauflandEndpoints
from .models import (
    Attribute,
    Category,
    Inventory,
    Price,
    Product,
    ProductBatch,
)

__all__ = [
    "KauflandAPIClient",
    "APIException",
    "APIAuthException",
    "APIRateLimitException",
    "KauflandEndpoints",
    "HTTPMethod",
    "Price",
    "Inventory",
    "Category",
    "Attribute",
    "Product",
    "ProductBatch",
]
