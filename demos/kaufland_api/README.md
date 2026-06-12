# Kaufland Seller API – Technik-Demo

Referenz-Implementierung einer signierten Anbindung an die **Kaufland Seller
API**. **Nicht** in die BMEcat-Pipeline verdrahtet — dient als technische
Vorlage für eine spätere `lib/channels/kaufland.py`.

## Inhalt

| Datei          | Zweck                                                        |
|----------------|-------------------------------------------------------------|
| `client.py`    | `KauflandAPIClient` – HMAC-SHA256-Auth, Retry, CRUD          |
| `endpoints.py` | `KauflandEndpoints`, `HTTPMethod`                            |
| `models.py`    | Datenmodelle: `Product`, `Price`, `Inventory`, `Category` … |
| `demo.py`      | Offline-Demo (Signatur + Modelle), optional `--live`        |

## Authentifizierung

Jeder Request wird per **HMAC-SHA256** signiert:

```
Signatur-String = "\n".join([HTTP-Methode, vollständige-URI, Body, Timestamp])
Shop-Signature  = HMAC_SHA256(secret_key, Signatur-String)
```

Header: `Shop-Client-Key`, `Shop-Timestamp`, `Shop-Signature`.

## Ausführen

```bash
# Offline – zeigt Signatur-Erzeugung und Datenmodelle, kein Netzwerk
python -m demos.kaufland_api.demo

# Echter Call (nur mit gesetzten Keys)
export KAUFLAND_CLIENT_KEY=...      # 32 Zeichen
export KAUFLAND_SECRET_KEY=...      # 64 Zeichen
python -m demos.kaufland_api.demo --live
```

## Verwendung als Bibliothek

```python
from demos.kaufland_api import KauflandAPIClient, Product, Price, Inventory

client = KauflandAPIClient(client_key, secret_key)
units  = client.get_units(limit=10)
client.close()
```

## Sicherheit

- **Keine Credentials im Repo.** Keys ausschließlich über Umgebungsvariablen
  oder Konstruktor-Parameter übergeben.
- Die ursprünglich mitgelieferten `credentials.enc` / `.key` wurden bewusst
  **nicht** übernommen.

## Bekannte Abweichungen vom Original

- Doppelt vorhandene Methoden (`_handle_response`, `request`, `get` …) entfernt.
- Bug behoben: im Duplikat wurde `_get_headers()` ohne Argumente aufgerufen.
- Eigenständig importierbar (relative Imports statt `from api import …`).
- Service-Schicht (`services.py`) nicht übernommen — die Convenience-Methoden
  am Client decken die Demo ab.
