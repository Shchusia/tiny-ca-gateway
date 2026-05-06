"""
example_aiohttp_ca/demo-aiohttp.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
aiohttp + tiny-ca + Swagger UI.

Swagger UI:   http://localhost:8000/docs
OpenAPI JSON: http://localhost:8000/openapi.json
"""

from __future__ import annotations
import sys, os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))  # noqa

import json
import logging

from aiohttp import web
from tiny_ca_gateway.aiohttp.api.v1.ca_routes import routes
from tiny_ca_gateway.aiohttp.lifespan.manager import AiohttpCAManager
from tiny_ca_gateway.openapi import SWAGGER_UI_HTML, build_openapi_schema

logging.basicConfig(
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s", level=logging.INFO
)
LOGGER = logging.getLogger("aiohttp-ca")


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


async def ca_lifespan(app: web.Application):
    manager = AiohttpCAManager(
        logger=LOGGER, common_name="aiohttp Root CA", organization="ACME Corp"
    )
    await manager.on_startup()
    LOGGER.info("✓ CA ready.")
    yield
    await manager.on_shutdown()


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


@web.middleware
async def error_middleware(request: web.Request, handler) -> web.Response:
    try:
        return await handler(request)
    except web.HTTPException as exc:
        if exc.content_type == "application/json":
            raise
        return web.Response(
            text=json.dumps({"detail": exc.reason}),
            content_type="application/json",
            status=exc.status,
        )
    except Exception as exc:
        LOGGER.error("Unhandled: %s", exc, exc_info=True)
        return web.Response(
            text=json.dumps({"detail": "Internal server error"}),
            content_type="application/json",
            status=500,
        )


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app() -> web.Application:
    app = web.Application(middlewares=[error_middleware])
    app.cleanup_ctx.append(ca_lifespan)

    # CA sub-application
    ca_subapp = web.Application()
    ca_subapp.add_routes(routes)
    app.add_subapp("/api/v1/ca", ca_subapp)

    # ── Swagger UI ──────────────────────────────────────────────────────────
    async def openapi_schema(request: web.Request) -> web.Response:
        schema = build_openapi_schema(title="Tiny CA API (aiohttp)", version="1.0")
        return web.Response(
            text=json.dumps(schema, default=str),
            content_type="application/json",
        )

    async def swagger_ui(request: web.Request) -> web.Response:
        html = SWAGGER_UI_HTML.format(
            title="Tiny CA API (aiohttp)",
            openapi_url="/openapi.json",
        )
        return web.Response(text=html, content_type="text/html")

    app.router.add_get("/openapi.json", openapi_schema)
    app.router.add_get("/docs", swagger_ui)

    # ── Health ──────────────────────────────────────────────────────────────
    async def health(request: web.Request) -> web.Response:
        return web.Response(
            text=json.dumps({"status": "ok", "framework": "aiohttp"}),
            content_type="application/json",
        )

    app.router.add_get("/health", health)

    return app


app = create_app()
if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=8000, access_log=LOGGER)
