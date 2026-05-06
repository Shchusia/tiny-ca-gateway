from pathlib import Path
from typing import Literal

from cryptography import x509
from fastapi import HTTPException
from tiny_ca.managers.async_lifecycle_manager import AsyncCertLifecycleManager

from tiny_ca_gateway.core import CertListItem
from tiny_ca_gateway.fastapi.lifespan import FastAPILifespanManager
from tiny_ca_gateway.models import API_SETTINGS

ArtifactType = Literal["pem", "key", "csr"]


def _record_to_item(r: object) -> CertListItem:
    return CertListItem(
        serial_number=r.serial_number,  # type: ignore[attr-defined]
        common_name=r.common_name,  # type: ignore[attr-defined]
        status=r.status,  # type: ignore[attr-defined]
        key_type=r.key_type,  # type: ignore[attr-defined]
        not_valid_after=r.not_valid_after,  # type: ignore[attr-defined]
        uuid=r.uuid,  # type: ignore[attr-defined]
    )


def require_factory() -> AsyncCertLifecycleManager:
    """Return the singleton manager; raise 503 if the factory (CA) is not loaded."""
    mgr: AsyncCertLifecycleManager = FastAPILifespanManager().manager
    if mgr.factory is None:
        raise HTTPException(
            503,
            "CA not initialised — call POST /v1/ca/root to bootstrap the certificate authority.",
        )
    return mgr


async def get_path_to_ca_file_if_exists(
    uuid: str,
    object_type: ArtifactType,
    is_ca: bool = True,
) -> Path | None:
    """
    Return the path to ``<base_folder>/<uuid>/<any_name>.<object_type>``
    or ``None`` if it does not exist.

    tiny_ca stores files as ``<common_name>.<ext>`` inside a UUID folder,
    so we scan the directory for any file with the matching extension
    rather than assuming a fixed filename.
    """

    folder = Path(API_SETTINGS.path_to_certificates_folder) / uuid
    if not folder.is_dir():
        print("not dir")
        return None

    extension = f".{object_type}"
    for f in folder.iterdir():
        print(f)
        if f.is_file() and f.suffix == extension:
            return f

    return None


async def get_path_to_service_file_if_exists(
    uuid: str,
    extension: ArtifactType,
) -> Path | None:
    """
    Same as above but scans under ``path_to_certificates_folder`` directly
    (services live in the same base folder with their own UUID sub-dirs).
    """
    return await get_path_to_ca_file_if_exists(uuid, extension)


def load_pem_crl(pem: str) -> x509.CertificateRevocationList:
    try:
        return x509.load_pem_x509_crl(pem.encode())
    except Exception as exc:
        raise HTTPException(422, f"Invalid PEM CRL: {exc}") from exc


def load_pem_cert(pem: str) -> x509.Certificate:
    try:
        return x509.load_pem_x509_certificate(pem.encode())
    except Exception as exc:
        raise HTTPException(422, f"Invalid PEM certificate: {exc}") from exc
