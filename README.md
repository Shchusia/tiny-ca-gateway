# tiny-ca-gateway

[![PyPI](https://img.shields.io/pypi/v/tiny-ca-gateway)](https://pypi.org/project/tiny-ca-gateway/)
[![Python](https://img.shields.io/pypi/pyversions/tiny-ca-gateway)](https://pypi.org/project/tiny-ca-gateway/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**tiny-ca-gateway** provides ready-to-use REST API routes for  [tiny-ca](https://github.com/Shchusia/tiny_ca) — a lightweight Python Certificate Authority library. Mount a full-featured CA HTTP API into any of your existing applications in minutes.

> **Built on top of [tiny-ca](https://github.com/Shchusia/tiny_ca).** This package only provides the HTTP layer. For CA internals, certificate issuance logic, and database models, see the [tiny-ca documentation](https://github.com/Shchusia/tiny_ca).

---

## Features

- **22 REST endpoints** — issue, revoke, renew, rotate, verify, download certificates and more
- **4 framework adapters** — drop into an existing app without rewriting anything
- **Shared core** — identical behaviour across all frameworks; integration tests run against all of them
- **Bearer token auth** — optional, zero-config when `CA_API_TOKEN` is empty
- **OpenAPI / Swagger UI** — built-in for FastAPI & Django Ninja; CDN-based for Flask & aiohttp
- **Async-native** — FastAPI, aiohttp and Django (ASGI) run fully async; Flask uses an asyncio bridge

---

## Supported frameworks

| Framework | Adapter | Integration guide |
|-----------|---------|------------------|
| **FastAPI** | `tiny_ca_gateway.fastapi` | [docs/fastapi.md](docs/fastapi.md) |
| **Flask** | `tiny_ca_gateway.flask` | [docs/flask.md](docs/flask.md) |
| **aiohttp** | `tiny_ca_gateway.aiohttp` | [docs/aiohttp.md](docs/aiohttp.md) |
| **Django Ninja** | `tiny_ca_gateway.django` | [docs/django.md](docs/django.md) |

---

## Quick install

Install only what you need:

```bash
# FastAPI
pip install "tiny-ca-gateway[fastapi]"

# Flask
pip install "tiny-ca-gateway[flask]"

# aiohttp
pip install "tiny-ca-gateway[aiohttp]"

# Django + Django Ninja
pip install "tiny-ca-gateway[django]"

# Everything
pip install "tiny-ca-gateway[all]"
```

---

## 60-second example

### FastAPI

```python
from fastapi import FastAPI
from contextlib import asynccontextmanager
from tiny_ca_gateway.fastapi.lifespan.manager import FastAPILifespanManager
from tiny_ca_gateway.fastapi.api.v1.ca_routes import router

@asynccontextmanager
async def lifespan(app: FastAPI):
    await FastAPILifespanManager(common_name="My CA").on_startup()
    yield

app = FastAPI(lifespan=lifespan)
app.include_router(router, prefix="/api/v1")
```

### Flask

```python
from flask import Flask
from tiny_ca_gateway.flask.lifespan.manager import FlaskCAManager
from tiny_ca_gateway.flask.api.v1.ca_blueprint import ca_bp

def create_app():
    app = Flask(__name__)
    FlaskCAManager(common_name="My CA").init_sync()
    app.register_blueprint(ca_bp, url_prefix="/api/v1/ca")
    return app
```

### aiohttp

```python
from aiohttp import web
from tiny_ca_gateway.aiohttp.lifespan.manager import AiohttpCAManager
from tiny_ca_gateway.aiohttp.api.v1.ca_routes import routes

async def lifespan(app):
    await AiohttpCAManager(common_name="My CA").on_startup()
    yield

app = web.Application()
app.cleanup_ctx.append(lifespan)
app.add_subapp("/api/v1/ca", web.Application())
app.router.add_routes(routes)
```

### Django Ninja

```python
# urls.py
from ninja import NinjaAPI
from tiny_ca_gateway.django.api.v1.ca_router import ca_router

api = NinjaAPI()
api.add_router("/ca", ca_router)

urlpatterns = [path("api/v1/", api.urls)]
```

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CA_CERT_PATH` | `certs/ca.pem` | Path to the CA certificate |
| `CA_KEY_PATH` | `certs/ca.key` | Path to the CA private key |
| `CA_CRL_PATH` | `certs/crl.pem` | Path to the CRL file |
| `CA_CERTS_DIR` | `certs/` | Directory for issued certificates |
| `CA_DB_URL` | `sqlite+aiosqlite:///ca.db` | SQLAlchemy async database URL |
| `CA_API_TOKEN` | `""` | Bearer token — empty = open access |

---

## API reference

All adapters expose the same 22 endpoints under the configured prefix:

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/cert` | ✗ | Download CA public certificate |
| `GET` | `/crl` | ✗ | Download CRL (DER or `?pem=true`) |
| `GET` | `/` | ✓ | List certificates |
| `GET` | `/expiring` | ✓ | Certificates expiring soon |
| `POST` | `/root` | ✓ | Bootstrap / replace root CA |
| `POST` | `/intermediate` | ✓ | Issue intermediate CA |
| `POST` | `/issue` | ✓ | Issue leaf certificate |
| `POST` | `/maintenance/expire` | ✓ | Mark expired certificates |
| `POST` | `/crl/refresh` | ✓ | Regenerate CRL |
| `POST` | `/crl/verify` | ✓ | Verify a CRL |
| `POST` | `/verify` | ✓ | Verify a certificate |
| `POST` | `/cosign` | ✓ | Co-sign an external certificate |
| `POST` | `/export-p12/{serial}` | ✓ | Export PKCS#12 bundle |
| `PATCH` | `/revoke` | ✓ | Revoke a certificate |
| `POST` | `/rotate/{serial}` | ✓ | Rotate (new key) |
| `POST` | `/renew/{serial}` | ✓ | Renew (same key, new validity) |
| `DELETE` | `/{serial}` | ✓ | Hard-delete certificate |
| `GET` | `/status/{serial}` | ✓ | Lifecycle status |
| `GET` | `/inspect/{serial}` | ✓ | Structured details |
| `GET` | `/chain/{serial}` | ✓ | Full PEM chain |
| `GET` | `/stream/{uuid}` | ✓ | Stream artefact (pem / key / csr) |
| `GET` | `/{uuid}` | ✓ | Download artefact |

---

## Running the integration tests

```bash
# Start any backend first, then:
python tests/ca_integration_test.py --base-url http://localhost:8000

# Run against all frameworks automatically:
task run-all-tests TOKEN=mysecret
```

---

## License

MIT — see [LICENSE](LICENSE).
