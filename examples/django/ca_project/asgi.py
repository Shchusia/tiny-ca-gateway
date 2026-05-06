import os
import sys
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ca_project.settings")

import django

django.setup()

from django.core.asgi import get_asgi_application

LOGGER = logging.getLogger("django-ca")


class CALifespanMiddleware:
    """
    Intercepts ASGI lifespan events and starts/stops CA.

    This is an alternative to AppConfig.ready() — preferred for uvicorn,
    as it works correctly with the async event loop.
    """

    def __init__(self, app):
        self.app = app
        self._manager = None

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            await self._handle_lifespan(scope, receive, send)
        else:
            await self.app(scope, receive, send)

    async def _handle_lifespan(self, scope, receive, send):
        while True:
            message = await receive()

            if message["type"] == "lifespan.startup":
                try:
                    await self._startup()
                    await send({"type": "lifespan.startup.complete"})
                except Exception as exc:
                    LOGGER.error("CA startup failed: %s", exc, exc_info=True)
                    await send({"type": "lifespan.startup.failed", "message": str(exc)})
                    return

            elif message["type"] == "lifespan.shutdown":
                try:
                    await self._shutdown()
                finally:
                    await send({"type": "lifespan.shutdown.complete"})
                return

    async def _startup(self) -> None:
        from tiny_ca_gateway.django.lifespan.manager import DjangoCALifespanManager

        self._manager = DjangoCALifespanManager(
            logger=LOGGER,
            common_name="Example Root CA",
            organization="ACME Corp",
        )
        await self._manager.on_startup()
        LOGGER.info("✓ CA initialised and ready.")

    async def _shutdown(self) -> None:
        if self._manager:
            await self._manager.on_shutdown()
        LOGGER.info("CA shut down.")


_django_app = get_asgi_application()
application = CALifespanMiddleware(_django_app)
