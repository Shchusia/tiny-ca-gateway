"""
models/settings.py — application settings via pydantic-settings.

All fields can be overridden with environment variables or a .env file.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import warnings

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from tiny_ca import KeyAlgorithm
from tiny_ca.const import DEFAULT_KEY_ALGORITHM


class ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    debug: bool = False

    # ------------------------------------------------------------------
    # Storage paths
    # ------------------------------------------------------------------
    # Base folder for ALL certificates.  CA cert lives in a sub-folder
    # created by tiny_ca storage; its exact UUID path is tracked by the DB.
    path_to_certificates_folder: str = "./certs"

    # Resolved at runtime from the DB / scan — overridable via env for
    # fixed-path deployments.
    path_to_ca_cer: str = Field(default="certs/ca.pem", alias="CA_CER")
    path_to_ca_key: str = Field(default="certs/ca.key", alias="CA_KEY")
    path_to_crl: str = "./certs/crl.pem"

    # ------------------------------------------------------------------
    # Auth tokens
    # ------------------------------------------------------------------
    api_token: str = "changeme"
    internal_temporary_token: str = "changeme2"

    # ------------------------------------------------------------------
    # Token TTL
    # ------------------------------------------------------------------
    internal_token_valid_until: str | datetime | None = None
    ttl_token: int = 30  # minutes

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    db_url: str = Field("sqlite+aiosqlite:///ca_demo_repository.db", alias="DB_URL_CA")
    db_url_sync: str = Field("sqlite:///ca_demo_repository.db", alias="DB_URL_CA_SYNC")

    # ------------------------------------------------------------------
    # Certificate profile
    # ------------------------------------------------------------------
    # Key algorithm of the root CA generated on first start.
    ca_key_algorithm: KeyAlgorithm = DEFAULT_KEY_ALGORITHM
    # Policy OIDs written into every issued certificate, plus an optional
    # URI of the Certification Practice Statement.
    certificate_policies: list[str] = []
    cps_uri: str | None = None
    # CRL Distribution Points / AIA caIssuers / AIA OCSP URLs.
    crl_distribution_points: list[str] = []
    ca_issuers_urls: list[str] = []
    ocsp_urls: list[str] = []

    # ------------------------------------------------------------------
    # Audit log
    # ------------------------------------------------------------------
    # Hash-chained JSON Lines record of every CA operation; disabled when
    # unset.  With a PEM private key every entry is also signed.
    audit_log_path: str | None = None
    audit_log_key: str | None = None
    audit_log_actor: str | None = None

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------
    datetime_fmt: str = "%Y-%m-%d %H:%M:%S"
    cors_origins: list[str] = []

    def model_post_init(self, __context: object) -> None:  # noqa: D401
        if self.api_token in ("changeme", "secret"):
            warnings.warn(
                "API_TOKEN is set to a default value — change it before deploying.",
                UserWarning,
                stacklevel=2,
            )
        if self.internal_temporary_token in ("changeme2", "secret2"):
            warnings.warn(
                "INTERNAL_TEMPORARY_TOKEN is set to a default value — change it before deploying.",
                UserWarning,
                stacklevel=2,
            )


API_SETTINGS = ApiSettings()
