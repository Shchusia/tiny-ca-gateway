# Changelog

All notable changes to **tiny-ca-gateway** will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [0.1.0] — 2025-05-06

Initial public release.

### Added

#### Core (`tiny_ca_gateway.core`)
- Shared Pydantic v2 schemas for all request/response models (`schemas.py`)
- Unified `REASON_MAP` — single source of truth for CRL revocation reasons
- `BaseCAManager` — singleton lifecycle base class with `on_startup`, `on_shutdown`, `rebuild_root_ca_pair`, `rebuild_manager` and `init_sync` (for WSGI contexts)
- `Routes` StrEnum — all 22 API path constants defined once, used by every adapter
- `core.auth` — framework-agnostic bearer token logic (`check_token`, `auth_enabled`, `extract_bearer`, `get_expected_token`)
- Shared helpers: `record_to_item`, `get_artifact_path`, `load_pem_cert`, `load_pem_crl`, `build_client_config`
- OpenAPI schema builder (`openapi.py`) and Swagger UI HTML template — used by Flask and aiohttp adapters

#### FastAPI adapter (`tiny_ca_gateway.fastapi`)
- `FastAPILifespanManager` — thin subclass of `BaseCAManager`
- `verify_token` dependency — `HTTPBearer(auto_error=False)` + `check_token`; open access when `CA_API_TOKEN` is empty
- Full async router with all 22 endpoints; mounts under `/ca` prefix
- Framework-native `FileResponse` and `StreamingResponse` for artifact downloads

#### Flask adapter (`tiny_ca_gateway.flask`)
- `FlaskCAManager` — `BaseCAManager` subclass with `init_sync()` for WSGI startup
- `ca_blueprint` Blueprint with all 22 endpoints
- Async-to-sync bridge (`_run` / `@_async` decorator) for running `tiny-ca` coroutines inside WSGI workers
- Explicit `/<string:uuid_certificate>` Flask-style path parameters (avoids Werkzeug literal-string routing pitfall)
- Pydantic `ValidationError` caught and returned as HTTP 422 on all body-parsing calls
- `strict_slashes=False` on the list endpoint to handle both `/api/v1/ca` and `/api/v1/ca/`

#### aiohttp adapter (`tiny_ca_gateway.aiohttp`)
- `AiohttpCAManager` — `BaseCAManager` subclass
- `web.RouteTableDef` with all 22 endpoints; mounts as a sub-application
- Native `web.StreamResponse` for streaming artifact downloads
- `cleanup_ctx` lifespan pattern (equivalent to FastAPI's `@asynccontextmanager lifespan`)
- `/list` alias registered alongside `""` and `"/"` for robust sub-application routing

#### Django Ninja adapter (`tiny_ca_gateway.django`)
- `DjangoCALifespanManager` — `BaseCAManager` subclass; `init_sync()` used from `AppConfig.ready()`
- `TokenAuth(HttpBearer)` with `__call__` override — bypasses Ninja's pre-auth 401 when `CA_API_TOKEN` is empty
- `/artifact/{uuid_certificate}` download path — avoids Django Ninja route conflict with `DELETE /{serial}`
- Both `AppConfig.ready()` (WSGI) and ASGI lifespan middleware startup patterns documented and supported
- `/` alias registered alongside `Routes.GET_LIST_CERTS` (`""`) for trailing-slash compatibility

#### API endpoints (all adapters)
- `GET  /cert` — public CA certificate download (no auth)
- `GET  /crl` — CRL download, DER by default, `?pem=true` for PEM (no auth)
- `GET  /` — list certificates with `status`, `key_type`, `limit`, `offset` filters
- `GET  /expiring` — certificates expiring within `within_days` (1–365)
- `POST /root` — bootstrap or replace self-signed root CA
- `POST /intermediate` — issue intermediate CA certificate
- `POST /issue` — issue leaf certificate with SAN, server/client flags, overwrite support
- `POST /maintenance/expire` — bulk-mark expired certificates
- `POST /crl/refresh` — force-regenerate CRL
- `POST /crl/verify` — verify CRL signature and expiry
- `POST /verify` — verify certificate against CA chain and CRL
- `POST /cosign` — co-sign an externally generated certificate
- `POST /export-p12/{serial}` — export PKCS#12 bundle with optional passphrase
- `PATCH /revoke` — revoke certificate with RFC 5280 reason code
- `POST /rotate/{serial}` — revoke and re-issue with a new key pair
- `POST /renew/{serial}` — extend validity period, keep existing key
- `DELETE /{serial}` — hard-delete certificate record and artefact files
- `GET  /status/{serial}` — lifecycle status (`valid` / `revoked` / `expired`)
- `GET  /inspect/{serial}` — structured certificate details
- `GET  /chain/{serial}` — full PEM certificate chain
- `GET  /stream/{uuid}` — chunked streaming download of `pem` / `key` / `csr`
- `GET  /{uuid}` — single-response download of `pem` / `key` / `csr`

#### Integration tests (`tests/ca_integration_test.py`)
- 58-test integration suite with zero external dependencies (stdlib only)
- Groups: Public Endpoints, Route Completeness, Issue Certificate, Download Artifacts, List & Search, Inspect/Status/Chain, Verify, Maintenance, Revoke, Renew, Rotate, Delete, Intermediate CA, Auth, Data Consistency
- Validity period checks: exact day-count assertions with ±2 day tolerance
- PEM normalization: `re.sub`-based base64 extraction, works across PKCS#1 and PKCS#8 key formats
- Framework-aware fallbacks: `_get_artifact` tries `/{uuid}` → `/artifact/{uuid}` → `/download/{uuid}`; `_list_get` tries `/` → `""` → `/list`
- Auth test probes multiple endpoints to handle frameworks that return 404 on `GET /`

#### Taskfile (`Taskfile.yml`)
- `run-tests` — run integration tests against a running server (`PORT`, `TOKEN` options)
- `run-all-tests` — sequentially start each backend (dev + prod mode), run the full test suite, stop the server, print a pass/fail summary; supports `TOKEN`, `PORT`, `TIMEOUT` options
- `run-fastapi-demo`, `run-flask-demo`, `run-aiohttp-demo`, `run-django-demo` — individual demo runners with `MODE=dev|prod` switch

#### Demo applications (`examples/`)
- `examples/fastapi/demo-fastapi.py`
- `examples/flask/demo-flask.py`
- `examples/aiohttp/demo-aiohttp.py`
- `examples/django/` — full Django project (`settings.py`, `urls.py`, `asgi.py`, `wsgi.py`, `apps.py`)

#### Documentation (`docs/`)
- `README.md` — project overview, quick-start examples, full endpoint table, environment variable reference
- `docs/fastapi.md` — FastAPI integration guide
- `docs/flask.md` — Flask integration guide
- `docs/aiohttp.md` — aiohttp integration guide
- `docs/django.md` — Django Ninja integration guide (WSGI + ASGI startup, `TEMPLATES` requirement, token auth internals)

---

[Unreleased]: https://github.com/yourorg/tiny-ca-gateway/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/yourorg/tiny-ca-gateway/releases/tag/v0.1.0
