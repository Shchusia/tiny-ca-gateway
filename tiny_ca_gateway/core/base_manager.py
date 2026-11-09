"""
Contains all startup/shutdown/rebuild business logic.
Each framework inherits and adds only its own specifics:
- Flask: init_sync()
- Django: ready() hook
- FastAPI: already async, just uses as-is
- aiohttp: cleanup_ctx, uses as-is
"""

from __future__ import annotations

import logging
from pathlib import Path
import shutil

from cryptography.hazmat.primitives.serialization import load_pem_private_key
from tiny_ca import AuditLog, CAConfig, CAFileLoader, CertificateFactory
from tiny_ca.managers.async_lifecycle_manager import AsyncCertLifecycleManager

from tiny_ca_gateway.db import LocalDBHandler
from tiny_ca_gateway.models import API_SETTINGS
from tiny_ca_gateway.utils.singleton import SingletonMeta

LOGGER = logging.getLogger("tiny-ca")


class BaseCAManager(metaclass=SingletonMeta):
    """
    Singleton base CA manager.

    Subclass per framework and override ``_make_exception`` if the
    framework uses a custom HTTP exception type.

    Usage::

        class FlaskCAManager(BaseCAManager):
            pass

        class MyCAManager(BaseCAManager):
            _logger_name = "my-app-ca"
    """

    _manager: AsyncCertLifecycleManager
    _logger_name: str = "tiny-ca"

    def __init__(
        self,
        logger: logging.Logger | None = None,
        common_name: str = "Root CA",
        organization: str = "Organization",
    ) -> None:
        self._logger = logger or logging.getLogger(self._logger_name)
        self._common_name = common_name
        self._organization = organization
        self._db_handler = LocalDBHandler(
            API_SETTINGS.db_url,
            logger=self._logger,
        )
        self._audit_log = self._make_audit_log()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def manager(self) -> AsyncCertLifecycleManager:
        return self._manager

    @property
    def logger(self) -> logging.Logger:
        return self._logger

    @property
    def audit_log(self) -> AuditLog | None:
        return self._audit_log

    def _make_audit_log(self) -> AuditLog | None:
        """Build the audit log from settings, or ``None`` when disabled."""
        if not API_SETTINGS.audit_log_path:
            return None
        signer = None
        if API_SETTINGS.audit_log_key:
            signer = load_pem_private_key(
                Path(API_SETTINGS.audit_log_key).read_bytes(), password=None
            )
        return AuditLog(
            API_SETTINGS.audit_log_path,
            signer=signer,  # type: ignore[arg-type]
            actor=API_SETTINGS.audit_log_actor,
            logger=self._logger,
        )

    # ------------------------------------------------------------------
    # Internal async machinery
    # ------------------------------------------------------------------

    async def _rebuild_root_ca_pair(self, ca_config: CAConfig) -> None:
        """Generate a new self-signed root CA and write to disk."""
        tmp = AsyncCertLifecycleManager(
            db_handler=self._db_handler,
            logger=self._logger,
            audit_log=self._audit_log,
        )
        ca_cert_path, ca_key_path = await tmp.create_self_signed_ca(
            config=ca_config, is_overwrite=True
        )
        self._logger.warning("Generated new self-signed root CA.")
        shutil.copy(ca_cert_path, API_SETTINGS.path_to_ca_cer)
        shutil.copy(ca_key_path, API_SETTINGS.path_to_ca_key)

    async def _rebuild_manager(self) -> None:
        """(Re-)load the CA factory from disk."""
        self._manager = AsyncCertLifecycleManager(
            db_handler=self._db_handler,
            audit_log=self._audit_log,
            factory=CertificateFactory(
                ca_loader=CAFileLoader(
                    ca_cert_path=API_SETTINGS.path_to_ca_cer,
                    ca_key_path=API_SETTINGS.path_to_ca_key,
                    logger=self._logger,
                ),
                logger=self._logger,
                crl_distribution_points=API_SETTINGS.crl_distribution_points,
                ca_issuers_urls=API_SETTINGS.ca_issuers_urls,
                ocsp_urls=API_SETTINGS.ocsp_urls,
                certificate_policies=API_SETTINGS.certificate_policies,
                cps_uri=API_SETTINGS.cps_uri,
            ),
        )

    # ------------------------------------------------------------------
    # Public lifecycle API
    # ------------------------------------------------------------------

    async def on_startup(self) -> None:
        """Bootstrap DB, create CA if missing, load factory."""
        await self._db_handler._db.init_db()
        await self._db_handler.init_system_time_if_empty()

        if not Path(API_SETTINGS.path_to_ca_cer).exists():
            await self._rebuild_root_ca_pair(
                CAConfig(
                    common_name=self._common_name,
                    organization=self._organization,
                    country="UA",
                    key_algorithm=API_SETTINGS.ca_key_algorithm,
                    key_size=4096,
                    days_valid=3650,
                )
            )
        await self._rebuild_manager()
        self._logger.info("✓ CA initialised.")

    async def on_shutdown(self) -> None:
        """Graceful shutdown hook (no-op by default)."""
        pass

    # ------------------------------------------------------------------
    # Called from POST /root endpoint
    # ------------------------------------------------------------------

    async def rebuild_root_ca_pair(self, ca_config: CAConfig) -> None:
        await self._rebuild_root_ca_pair(ca_config)

    async def rebuild_manager(self) -> None:
        await self._rebuild_manager()

    # ------------------------------------------------------------------
    # Sync bootstrap (Flask / Django WSGI)
    # ------------------------------------------------------------------

    def init_sync(self) -> None:
        """
        Run on_startup() synchronously.

        Use in WSGI contexts (Flask create_app, Django AppConfig.ready).
        Safe to call even if an async loop is already running — in that
        case the call is a no-op and the ASGI lifespan handler takes over.
        """
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            self._logger.debug(
                "Async loop running — CA init delegated to ASGI lifespan."
            )
            return

        asyncio.run(self.on_startup())
