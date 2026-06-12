#!/usr/bin/env python3
"""
Kaufland API – Offline-Demo

Zeigt Client-Initialisierung, HMAC-SHA256-Signatur und Datenmodelle OHNE
Netzwerkzugriff. Echte Calls nur, wenn KAUFLAND_CLIENT_KEY/SECRET_KEY gesetzt
sind UND --live übergeben wird.

Aufruf:
    python -m demos.kaufland_api.demo          # offline (sichere Signatur-Demo)
    python -m demos.kaufland_api.demo --live   # echter GET /units (nur mit Keys)
"""

import json
import os
import sys

from .client import KauflandAPIClient
from .models import Inventory, Price, Product


def main():
    live = "--live" in sys.argv

    client_key = os.environ.get("KAUFLAND_CLIENT_KEY", "demo-client-key")
    secret_key = os.environ.get("KAUFLAND_SECRET_KEY", "demo-secret-key")

    client = KauflandAPIClient(client_key, secret_key)

    print("=" * 60)
    print("Kaufland API – Technik-Demo")
    print("=" * 60)
    print(f"Basis-URL : {client.base_url}")
    print(f"Client-Key: {client_key[:4]}… ({len(client_key)} Zeichen)")

    # 1. Signatur offline demonstrieren (kein Netzwerk)
    method, uri, body, ts = "GET", f"{client.base_url}/units", "", 1700000000
    sig = client._sign_request(method, uri, body, ts)
    print("\nHMAC-SHA256-Signatur (Beispiel):")
    print(f"  Signatur-String: {method}\\n{uri}\\n{body}\\n{ts}")
    print(f"  Signatur:        {sig}")

    headers = client._get_headers(method, uri, body)
    print("\nErzeugte Header:")
    for k, v in headers.items():
        shown = v if k != "Shop-Signature" else v[:16] + "…"
        print(f"  {k}: {shown}")

    # 2. Datenmodell demonstrieren
    product = Product(
        id=0, sku="SOC12345", title="Kugelschreiber blau",
        price=Price(0.99), inventory=Inventory(quantity=500, sku="SOC12345"),
        category_id=162800,
    )
    print("\nProduct.to_dict(exclude_none=True):")
    print(json.dumps(product.to_dict(exclude_none=True), indent=2,
                     ensure_ascii=False))

    # 3. Optional: echter Call
    if live:
        if client_key == "demo-client-key":
            print("\n--live ignoriert: keine echten Keys "
                  "(KAUFLAND_CLIENT_KEY/SECRET_KEY) gesetzt.")
        else:
            print("\nLive-Request: GET /units ...")
            try:
                print(json.dumps(client.get_units(limit=1), indent=2,
                                 ensure_ascii=False))
            except Exception as e:
                print(f"Fehler: {e}")

    client.close()
    print("\nFertig.")


if __name__ == "__main__":
    main()
