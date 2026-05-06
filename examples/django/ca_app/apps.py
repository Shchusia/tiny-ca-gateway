from __future__ import annotations
import sys, os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))
import asyncio
import logging

from django.apps import AppConfig

LOGGER = logging.getLogger("django-ca")


class CAAppConfig(AppConfig):
    name = "ca_app"
    verbose_name = "Certificate Authority"

    def ready(self) -> None:
        """
        Called by Django once after all models have loaded.

        ready() is synchronous, so we run an async init via asyncio.run().
        This is safe: ready() is guaranteed to be called before the first request.
        """
        from tiny_ca_gateway.django.lifespan.manager import DjangoCALifespanManager

        # If the asynchronous loop is already running (uvicorn), skip it.
        # Initialization will occur via CALifespanMiddleware in asgi.py
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            LOGGER.debug(
                "Async loop already running — CA init delegated to ASGI lifespan."
            )
            return

        manager = DjangoCALifespanManager(
            logger=LOGGER,
            common_name="Example Root CA",
            organization="ACME Corp",
        )

        try:
            asyncio.run(manager.on_startup())
            LOGGER.info("✓ CA initialised via AppConfig.ready()")
        except Exception as exc:
            # Don't crash Django - endpoints will return 503 until CA is up
            LOGGER.error("CA initialisation failed: %s", exc, exc_info=True)
