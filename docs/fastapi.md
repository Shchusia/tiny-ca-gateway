# Integrating tiny-ca-gateway with FastAPI

This guide shows how to add the CA REST API to an existing FastAPI application.

## Install

```bash
pip install "tiny-ca-gateway[fastapi]"
```

## Minimal integration

```python
# main.py
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from tiny_ca_gateway.fastapi.lifespan.manager import FastAPILifespanManager
from tiny_ca_gateway.fastapi.api.v1.ca_routes import router as ca_router

# Configure storage paths (can also be set via environment variables)
os.environ.setdefault("CA_CERT_PATH", "certs/ca.pem")
os.environ.setdefault("CA_KEY_PATH",  "certs/ca.key")
os.environ.setdefault("CA_CRL_PATH",  "certs/crl.pem")
os.environ.setdefault("CA_CERTS_DIR", "certs/")
os.environ.setdefault("CA_DB_URL",    "sqlite+aiosqlite:///ca.db")
os.environ.setdefault("CA_API_TOKEN", "")        # empty = open access

@asynccontextmanager
async def lifespan(app: FastAPI):
    manager = FastAPILifespanManager(
        common_name="My Root CA",
        organization="ACME Corp",
    )
    await manager.on_startup()   # bootstraps DB, creates CA if missing
    yield
    await manager.on_shutdown()

app = FastAPI(lifespan=lifespan)

# Mount all 22 CA endpoints under /api/v1/ca/...
app.include_router(ca_router, prefix="/api/v1")
```

Run:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
# Swagger UI → http://localhost:8000/docs
```

---

## Adding to an existing lifespan

If your app already has a lifespan context manager, add the CA startup call inside it:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # your existing startup
    await database.connect()

    # CA startup
    await FastAPILifespanManager(common_name="My CA").on_startup()

    yield

    # your existing shutdown
    await database.disconnect()
```

---

## Using a `.env` file

```bash
# .env
CA_CERT_PATH=certs/ca.pem
CA_KEY_PATH=certs/ca.key
CA_CRL_PATH=certs/crl.pem
CA_CERTS_DIR=certs/
CA_DB_URL=sqlite+aiosqlite:///ca.db
CA_API_TOKEN=your-secret-token
```

Load it with `python-dotenv` or `pydantic-settings` before importing the gateway.

---

## Securing with a bearer token

Set `CA_API_TOKEN` to a non-empty value. All protected endpoints will require:

```
Authorization: Bearer <your-token>
```

The `/cert` and `/crl` endpoints are always public (no token required).

---

## Changing the URL prefix

```python
# Mount at /ca instead of /api/v1/ca
app.include_router(ca_router, prefix="/ca")
```

The `ca_router` already includes `/ca` prefix internally. Pass `prefix=""` to override:

```python
from tiny_ca_gateway.fastapi.api.v1.ca_routes import router

# router has prefix="/ca" — to move to /v2/pki/ca:
app.include_router(router, prefix="/v2/pki")
```

---

## Production with Uvicorn

```bash
# Single worker (recommended — CA uses an in-process singleton)
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1

# With SSL termination at the reverse proxy (nginx/caddy recommended)
uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1
```

> **Note:** Use `--workers 1`. The CA manager is a process-level singleton; multiple workers share the same DB but each would load the CA independently, which can cause race conditions on write-heavy operations.

---

## Swagger UI

FastAPI generates Swagger UI automatically. After startup visit:

```
http://localhost:8000/docs       # Swagger UI
http://localhost:8000/redoc      # ReDoc
http://localhost:8000/openapi.json
```

---

## File structure produced

```
certs/
├── ca.pem                          # CA public certificate
├── ca.key                          # CA private key
├── crl.pem                         # Certificate Revocation List
└── <uuid>/
    ├── service.pem                 # Issued certificate
    ├── service.key                 # Private key
    └── service.csr                 # Certificate signing request
ca.db                               # SQLite metadata database
```
