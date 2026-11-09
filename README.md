# tiny-ca-gateway

[![PyPI](https://img.shields.io/pypi/v/tiny_ca_gateway)](https://pypi.org/project/tiny-ca-gateway/)
[![Python](https://img.shields.io/pypi/pyversions/tiny_ca_gateway)](https://pypi.org/project/tiny-ca-gateway/)
[![Downloads](https://static.pepy.tech/badge/tiny-ca-gateway)](https://pepy.tech/projects/tiny-ca-gateway)
[![Downloads/month](https://static.pepy.tech/badge/tiny-ca-gateway/month)](https://pepy.tech/projects/tiny-ca-gateway)
[![Coverage Status](https://coveralls.io/repos/github/Shchusia/tiny-ca-gateway/badge.svg)](https://coveralls.io/github/Shchusia/tiny-ca-gateway)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**tiny-ca-gateway** provides ready-to-use REST API routes for  [tiny-ca](https://github.com/Shchusia/tiny_ca) — a lightweight Python Certificate Authority library. Mount a full-featured CA HTTP API into any of your existing applications in minutes.

> **Built on top of [tiny-ca](https://github.com/Shchusia/tiny_ca).** This package only provides the HTTP layer. For CA internals, certificate issuance logic, and database models, see the [tiny-ca documentation](https://github.com/Shchusia/tiny_ca).

---

## Features

- **23 REST endpoints** — issue, revoke, renew, rotate, verify, download certificates and more
- **tiny-ca 1.0** — ECDSA P-384 keys by default (RSA, P-256 and Ed25519 on request), name-constrained intermediate CAs, intermediate CAs for keys held in an HSM, certificate policies and a signed audit log
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

Settings are read once, when `tiny_ca_gateway` is first imported (from the
environment or a `.env` file in the working directory).

| Variable | Default | Description |
|----------|---------|-------------|
| `CA_CER` | `certs/ca.pem` | Path to the CA certificate |
| `CA_KEY` | `certs/ca.key` | Path to the CA private key |
| `PATH_TO_CRL` | `./certs/crl.pem` | Path to the CRL file |
| `PATH_TO_CERTIFICATES_FOLDER` | `./certs` | Directory for issued certificates |
| `DB_URL_CA` | `sqlite+aiosqlite:///ca_demo_repository.db` | SQLAlchemy async database URL |
| `API_TOKEN` | `changeme` | Bearer token. Flask, aiohttp and Django allow open access when it is empty; FastAPI always requires it |
| `CA_KEY_ALGORITHM` | `ec-p384` | Key of the root CA created on first start: `rsa`, `ec-p256`, `ec-p384` or `ed25519` |
| `CERTIFICATE_POLICIES` | `[]` | JSON list of policy OIDs added to every issued certificate |
| `CPS_URI` | — | Certification Practice Statement URI (requires `CERTIFICATE_POLICIES`) |
| `CRL_DISTRIBUTION_POINTS` | `[]` | JSON list of CRL URLs written into issued certificates |
| `CA_ISSUERS_URLS` / `OCSP_URLS` | `[]` | JSON lists for the Authority Information Access extension |
| `AUDIT_LOG_PATH` | — | Enables the hash-chained audit log (JSON Lines) of every CA operation |
| `AUDIT_LOG_KEY` | — | Unencrypted PEM private key that signs each audit entry |
| `AUDIT_LOG_ACTOR` | OS user name | Actor recorded in audit entries |

Verify an audit log offline with tiny-ca:

```python
from tiny_ca import AuditLog
from cryptography.hazmat.primitives.serialization import load_pem_public_key

public_key = load_pem_public_key(open("audit.pub", "rb").read())
print(AuditLog.verify("audit.jsonl", public_key), "entries verified")
```

---

## API reference

All adapters expose the same 23 endpoints under the configured prefix:

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/cert` | ✗ | Download CA public certificate |
| `GET` | `/crl` | ✗ | Download CRL (DER or `?pem=true`) |
| `GET` | `/` | ✓ | List certificates |
| `GET` | `/expiring` | ✓ | Certificates expiring soon |
| `POST` | `/root` | ✓ | Bootstrap / replace root CA |
| `POST` | `/intermediate` | ✓ | Issue intermediate CA (optional `name_constraints`) |
| `POST` | `/intermediate/certify` | ✓ | Certify an intermediate CA from its CSR; the key stays in your HSM |
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

`/issue`, `/rotate` and `/intermediate` accept `key_algorithm` (`ec-p384` by
default) and `key_size` (RSA only, 2048–8192).  Renewing or co-signing a
revoked certificate, deleting a revoked certificate before it expires, and
re-using the common name of an existing intermediate CA without
`"is_overwrite": true` return **409 Conflict**; a name outside an
intermediate's `name_constraints` returns **422**.

### Name-constrained intermediate CA

```bash
curl -X POST http://localhost:8000/api/v1/ca/intermediate \
  -H "Authorization: Bearer $API_TOKEN" -H "Content-Type: application/json" \
  -d '{"common_name": "Internal Services CA",
       "name_constraints": {"permitted_dns": ["svc.example.com"],
                            "permitted_ip": ["10.0.0.0/8"]}}'
```

### Intermediate CA for a key in an HSM

Generate the key and a CSR inside the HSM, then send only the CSR:

```bash
curl -X POST http://localhost:8000/api/v1/ca/intermediate/certify \
  -H "Authorization: Bearer $API_TOKEN" -H "Content-Type: application/json" \
  -d "{\"common_name\": \"HSM Issuing CA\", \"csr\": $(jq -Rs . < issuing-ca.csr)}"
```

---

## Running the integration tests

```bash
# Start any backend first, then:
python tests/ca_integration_test.py --base-url http://localhost:8000

# Start every backend in every server mode (9 runs), test it and verify its
# signed audit log:
task run-all-tests TOKEN=mysecret

# The same under coverage.py; writes .coverage and coverage.xml:
task coverage

# Publish the coverage to Coveralls:
COVERALLS_REPO_TOKEN=... task coverage-upload
```

Tested on Python 3.12, 3.14 and 3.15 with FastAPI 0.162, Flask 3.1,
aiohttp 3.14 and Django 6.1 / Django Ninja 1.8.

---

## License

MIT — see [LICENSE](LICENSE).
