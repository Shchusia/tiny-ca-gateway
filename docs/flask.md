# Integrating tiny-ca-gateway with Flask

This guide shows how to add the CA REST API to an existing Flask application.

## Install

```bash
pip install "tiny-ca-gateway[flask]"
```

## Minimal integration

```python
# app.py
import os
from flask import Flask
from tiny_ca_gateway.flask.lifespan.manager import FlaskCAManager
from tiny_ca_gateway.flask.api.v1.ca_blueprint import ca_bp

os.environ.setdefault("CA_CERT_PATH", "certs/ca.pem")
os.environ.setdefault("CA_KEY_PATH",  "certs/ca.key")
os.environ.setdefault("CA_CRL_PATH",  "certs/crl.pem")
os.environ.setdefault("CA_CERTS_DIR", "certs/")
os.environ.setdefault("CA_DB_URL",    "sqlite+aiosqlite:///ca.db")
os.environ.setdefault("CA_API_TOKEN", "")

def create_app() -> Flask:
    app = Flask(__name__)

    # Bootstrap the CA once at startup (sync — WSGI compatible)
    FlaskCAManager(
        common_name="My Root CA",
        organization="ACME Corp",
    ).init_sync()

    # Mount all 22 CA endpoints at /api/v1/ca/...
    app.register_blueprint(ca_bp, url_prefix="/api/v1/ca")

    return app

if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=8000, debug=True)
```

Run:

```bash
python app.py
# or
flask --app app:create_app run --port 8000
```

---

## Adding to an existing application factory

```python
# your existing app.py
def create_app(config=None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config or "config.Default")

    # --- your existing extensions ---
    db.init_app(app)
    login_manager.init_app(app)

    # --- CA gateway ---
    from tiny_ca_gateway.flask.lifespan.manager import FlaskCAManager
    from tiny_ca_gateway.flask.api.v1.ca_blueprint import ca_bp

    FlaskCAManager(common_name="My CA").init_sync()
    app.register_blueprint(ca_bp, url_prefix="/api/v1/ca")

    # --- your existing blueprints ---
    from myapp.auth import auth_bp
    app.register_blueprint(auth_bp)

    return app
```

---

## Swagger UI

Flask does not include Swagger UI by default. The gateway provides a lightweight CDN-based UI automatically at:

```
http://localhost:8000/docs          # Swagger UI
http://localhost:8000/openapi.json  # OpenAPI schema
```

To enable it, add the docs routes in `create_app()`:

```python
import json
from flask import Response
from tiny_ca_gateway.openapi import SWAGGER_UI_HTML, build_openapi_schema

@app.get("/openapi.json")
def openapi_schema():
    return Response(
        json.dumps(build_openapi_schema(title="My CA API")),
        content_type="application/json",
    )

@app.get("/docs")
def swagger_ui():
    return Response(
        SWAGGER_UI_HTML.format(title="My CA API", openapi_url="/openapi.json"),
        content_type="text/html",
    )
```

---

## Securing with a bearer token

Set `CA_API_TOKEN` to a non-empty value. Protected endpoints require:

```
Authorization: Bearer <your-token>
```

`GET /api/v1/ca/cert` and `GET /api/v1/ca/crl` are always public.

---

## Production with Gunicorn

```bash
# Single worker recommended (CA singleton is process-scoped)
gunicorn "app:create_app()" --bind 0.0.0.0:8000 --workers 1
```

> **Important:** Flask is WSGI. Async views inside the gateway run via an `asyncio` bridge (`loop.run_until_complete`). This means each request blocks a thread while the CA performs async I/O. For high-concurrency CA workloads consider the aiohttp or FastAPI adapters instead.

---

## Error handling

The blueprint already registers its own error responses (JSON `{"detail": "..."}` format). To unify with your app's existing error handler:

```python
from flask import jsonify

@app.errorhandler(404)
def not_found(e):
    return jsonify(detail=str(e)), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify(detail="Internal server error"), 500
```

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
