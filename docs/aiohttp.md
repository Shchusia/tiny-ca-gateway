# Integrating tiny-ca-gateway with aiohttp

This guide shows how to add the CA REST API to an existing aiohttp application.

## Install

```bash
pip install "tiny-ca-gateway[aiohttp]"
```

## Minimal integration

```python
# app.py
import os
import json
from aiohttp import web
from tiny_ca_gateway.aiohttp.lifespan.manager import AiohttpCAManager
from tiny_ca_gateway.aiohttp.api.v1.ca_routes import routes

os.environ.setdefault("CA_CERT_PATH", "certs/ca.pem")
os.environ.setdefault("CA_KEY_PATH",  "certs/ca.key")
os.environ.setdefault("CA_CRL_PATH",  "certs/crl.pem")
os.environ.setdefault("CA_CERTS_DIR", "certs/")
os.environ.setdefault("CA_DB_URL",    "sqlite+aiosqlite:///ca.db")
os.environ.setdefault("CA_API_TOKEN", "")

async def ca_lifespan(app: web.Application):
    """aiohttp cleanup_ctx — runs before first request / after last."""
    manager = AiohttpCAManager(
        common_name="My Root CA",
        organization="ACME Corp",
    )
    await manager.on_startup()
    yield                          # application serves requests
    await manager.on_shutdown()

def create_app() -> web.Application:
    app = web.Application()

    # Register CA lifespan
    app.cleanup_ctx.append(ca_lifespan)

    # Mount CA routes as a sub-application at /api/v1/ca
    ca_sub = web.Application()
    ca_sub.add_routes(routes)
    app.add_subapp("/api/v1/ca", ca_sub)

    return app

if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=8000)
```

Run:

```bash
python app.py
```

---

## Adding to an existing application

```python
# your existing app.py
def create_app() -> web.Application:
    app = web.Application()

    # --- your existing setup ---
    app.cleanup_ctx.append(your_db_lifespan)
    app.add_routes(your_routes)

    # --- CA gateway ---
    from tiny_ca_gateway.aiohttp.lifespan.manager import AiohttpCAManager
    from tiny_ca_gateway.aiohttp.api.v1.ca_routes import routes

    async def ca_lifespan(app):
        await AiohttpCAManager(common_name="My CA").on_startup()
        yield
        # no explicit shutdown needed

    app.cleanup_ctx.append(ca_lifespan)

    ca_sub = web.Application()
    ca_sub.add_routes(routes)
    app.add_subapp("/api/v1/ca", ca_sub)

    return app
```

---

## Global error middleware

aiohttp does not have a built-in error handler. Add one to return JSON for all errors:

```python
@web.middleware
async def error_middleware(request: web.Request, handler) -> web.Response:
    try:
        return await handler(request)
    except web.HTTPException as exc:
        return web.Response(
            text=json.dumps({"detail": exc.reason}),
            content_type="application/json",
            status=exc.status,
        )
    except Exception as exc:
        return web.Response(
            text=json.dumps({"detail": "Internal server error"}),
            content_type="application/json",
            status=500,
        )

app = web.Application(middlewares=[error_middleware])
```

---

## Swagger UI

Add OpenAPI documentation endpoints:

```python
from tiny_ca_gateway.openapi import SWAGGER_UI_HTML, build_openapi_schema

async def openapi_schema(request: web.Request) -> web.Response:
    return web.Response(
        text=json.dumps(build_openapi_schema(title="My CA API")),
        content_type="application/json",
    )

async def swagger_ui(request: web.Request) -> web.Response:
    return web.Response(
        text=SWAGGER_UI_HTML.format(
            title="My CA API",
            openapi_url="/openapi.json",
        ),
        content_type="text/html",
    )

app.router.add_get("/openapi.json", openapi_schema)
app.router.add_get("/docs", swagger_ui)
```

---

## Securing with a bearer token

Set `CA_API_TOKEN`. Protected endpoints require:

```
Authorization: Bearer <your-token>
```

`GET /api/v1/ca/cert` and `GET /api/v1/ca/crl` are always public.

---

## Route conflict note

aiohttp matches path parameters by pattern, not by HTTP method. The gateway registers:

- `DELETE /{serial}` — delete by integer serial
- `GET /{uuid_certificate}` — download by UUID string

These use different path names (`serial` vs `uuid_certificate`) and aiohttp resolves them correctly when registered in the same `RouteTableDef`. If you see `405 Method Not Allowed` on download routes, ensure the download routes are added **after** the delete route in the definition file.

---

## Production with Gunicorn

```bash
gunicorn "app:create_app()" \
  -k aiohttp.GunicornWebWorker \
  --bind 0.0.0.0:8000 \
  --workers 1
```

> **Workers = 1 recommended** — the CA manager is a process-level singleton. Multiple workers share the DB but maintain independent in-memory state.

---

## File structure produced

```
certs/
├── ca.pem
├── ca.key
├── crl.pem
└── <uuid>/
    ├── service.pem
    ├── service.key
    └── service.csr
ca.db
```
