from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from cryptography import x509

from tiny_ca_gateway.core.schemas import (
    ArtifactType,
    CertListItem,
    IssueCertRequest,
)
from tiny_ca_gateway.models import API_SETTINGS

if TYPE_CHECKING:
    from tiny_ca.models.certificate import ClientConfig

LOGGER = logging.getLogger("tiny-ca")


# ---------------------------------------------------------------------------
# Record → schema
# ---------------------------------------------------------------------------


def record_to_item(r: object) -> CertListItem:
    """Convert a DB record to a CertListItem schema."""
    return CertListItem(
        serial_number=r.serial_number,  # type: ignore[attr-defined]
        common_name=r.common_name,  # type: ignore[attr-defined]
        status=r.status,  # type: ignore[attr-defined]
        key_type=r.key_type,  # type: ignore[attr-defined]
        not_valid_after=r.not_valid_after,  # type: ignore[attr-defined]
        uuid=r.uuid,  # type: ignore[attr-defined]
    )


# ---------------------------------------------------------------------------
# File system
# ---------------------------------------------------------------------------


async def get_artifact_path(uuid: str, object_type: ArtifactType) -> Path | None:
    """
    Return the path to ``<certs_dir>/<uuid>/<any_name>.<object_type>``
    or ``None`` if not found.

    tiny_ca stores files as ``<common_name>.<ext>`` inside a UUID folder,
    so we scan by extension rather than assuming a fixed filename.
    """
    folder = Path(API_SETTINGS.path_to_certificates_folder) / uuid
    if not folder.is_dir():
        LOGGER.debug("Artifact folder not found: %s", folder)
        return None
    ext = f".{object_type}"
    for f in folder.iterdir():
        if f.is_file() and f.suffix == ext:
            return f
    return None


# ---------------------------------------------------------------------------
# PEM loaders  (raise ValueError — caller converts to HTTP error)
# ---------------------------------------------------------------------------


def load_pem_cert(pem: str) -> x509.Certificate:
    """Parse PEM certificate; raises ValueError on failure."""
    try:
        return x509.load_pem_x509_certificate(pem.encode())
    except Exception as exc:
        raise ValueError(f"Invalid PEM certificate: {exc}") from exc


def load_pem_crl(pem: str) -> x509.CertificateRevocationList:
    """Parse PEM CRL; raises ValueError on failure."""
    try:
        return x509.load_pem_x509_crl(pem.encode())
    except Exception as exc:
        raise ValueError(f"Invalid PEM CRL: {exc}") from exc


# ---------------------------------------------------------------------------
# ClientConfig builder  (issue / rotate share identical logic)
# ---------------------------------------------------------------------------


def build_client_config(payload: IssueCertRequest) -> ClientConfig:
    """
    Build a ``ClientConfig`` from an ``IssueCertRequest``.

    Centralises the payload → config mapping that was copy-pasted
    in every framework's issue and rotate handlers.
    """
    from tiny_ca.const import CertType
    from tiny_ca.models.certificate import ClientConfig

    return ClientConfig(
        common_name=payload.common_name,
        serial_type=CertType.SERVICE,
        key_size=payload.key_size,
        days_valid=payload.days_valid,
        valid_from=payload.valid_from,
        email=payload.email,
        is_server_cert=payload.is_server_cert,
        is_client_cert=payload.is_client_cert,
        san_dns=payload.san_dns,
        san_ip=[str(ip) for ip in payload.san_ip] if payload.san_ip else None,
    )
