# Integrating tiny-ca-gateway with Django Ninja

This guide shows how to add the CA REST API to an existing Django project.

## Install

```bash
pip install "tiny-ca-gateway[django]"
```

## Minimal integration

### 1. Environment

Set the following variables before Django starts (in `.env`, shell, or `settings.py`):

```bash
CA_CERT_PATH=certs/ca.pem
CA_KEY_PATH=certs/ca.key
CA_CRL_PATH=certs/crl.pem
CA_CERTS_DIR=certs/
CA_DB_URL=sqlite+aiosqlite:///ca.db
CA_API_TOKEN=                      # empty = open access
```

### 2. App config (`apps.py`)

Create or update the `AppConfig` that starts the CA when Django loads:

```python
# myapp/apps.py
import asyncio
import logging
from django.apps import AppConfig

log = logging.getLogger("django-ca")

class MyAppConfig(AppConfig):
    name = "myapp"

    def ready(self) -> None:
        from tiny_ca_gateway.django.lifespan.manager import DjangoCALifespanManager

        manager = DjangoCALifespanManager(
            common_name="My Root CA",
            organization="ACME Corp",
        )
        try:
            # ready() is synchronous; use asyncio.run() before the event loop starts
            asyncio.run(manager.on_startup())
            log.info("CA initialised.")
        except Exception as exc:
            log.error("CA startup failed: %s", exc)
            # Protected endpoints return 503 until the CA is ready
```

Point Django to this config:

```python
# myapp/__init__.py
default_app_config = "myapp.apps.MyAppConfig"
```

Or in `settings.py`:

```python
INSTALLED_APPS = [
    ...
    "myapp.apps.MyAppConfig",
]
```

### 3. URL configuration (`urls.py`)

```python
# myproject/urls.py
from django.urls import path
from ninja import NinjaAPI
from tiny_ca_gateway.django.api.v1.ca_router import ca_router

api = NinjaAPI(title="My API", version="1")
api.add_router("/ca", ca_router)      # → /api/v1/ca/...

urlpatterns = [
    path("api/v1/", api.urls),
    # ... your existing URLs
]
```

### 4. Run

```bash
# Development
python manage.py runserver 8000

# Production (ASGI — recommended for async views)
uvicorn myproject.asgi:application --workers 1 --host 0.0.0.0 --port 8000

# Production (WSGI)
gunicorn myproject.wsgi:application --bind 0.0.0.0:8000 --workers 1
```

Swagger UI: `http://localhost:8000/api/v1/docs`

---

## Adding to an existing NinjaAPI instance

If your project already has a `NinjaAPI` instance, just add the router:

```python
# urls.py
from myproject.api import api          # your existing NinjaAPI instance
from tiny_ca_gateway.django.api.v1.ca_router import ca_router

api.add_router("/ca", ca_router)       # adds /api/v1/ca/... to your existing API
```

---

## ASGI lifespan (alternative to AppConfig)

For pure ASGI deployments with uvicorn you can use the ASGI lifespan protocol instead of `AppConfig.ready()`:

```python
# myproject/asgi.py
import os
import logging
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "myproject.settings")

import django
django.setup()

log = logging.getLogger("django-ca")
_django_app = get_asgi_application()

class CALifespanMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            await self._handle_lifespan(scope, receive, send)
        else:
            await self.app(scope, receive, send)

    async def _handle_lifespan(self, scope, receive, send):
        from tiny_ca_gateway.django.lifespan.manager import DjangoCALifespanManager
        manager = DjangoCALifespanManager(common_name="My Root CA")

        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await manager.on_startup()
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await manager.on_shutdown()
                await send({"type": "lifespan.shutdown.complete"})
                return

application = CALifespanMiddleware(_django_app)
```

---

## Bearer token authentication

Set `CA_API_TOKEN`. Protected endpoints require:

```
Authorization: Bearer <your-token>
```

The auth layer uses Django Ninja's `HttpBearer`. When `CA_API_TOKEN` is empty, the `__call__` bypass allows all requests through without any header requirement — no need to configure anything for local development.

`GET /api/v1/ca/cert` and `GET /api/v1/ca/crl` are always public (`auth=None`).

---

## Required Django settings

Add to `settings.py`:

```python
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "myapp",           # or wherever your AppConfig lives
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
            ],
        },
    },
]
```

> **`TEMPLATES` is required** by Django Ninja to render the Swagger UI page. Without it `GET /docs` returns 500.

---

## Workers and async

| Server | Mode | Notes |
|--------|------|-------|
| `manage.py runserver` | WSGI/sync | CA init via `AppConfig.ready()` |
| `gunicorn wsgi` | WSGI/sync | Use `--workers 1` |
| `uvicorn asgi` | ASGI/async | CA init via lifespan or `AppConfig.ready()` |

> **Workers = 1 recommended.** The CA manager is a process-level singleton backed by a file-system store and SQLite. Multiple workers share the DB but each loads the CA factory independently.

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
