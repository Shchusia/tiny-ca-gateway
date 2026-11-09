"""
Framework-agnostic operations shared by every adapter.

Adapters call these and translate exceptions to HTTP with
:func:`error_status`, so the status codes are the same everywhere.
"""

from __future__ import annotations

from cryptography import x509
from tiny_ca.exc import (
    CertificateRevokedError,
    CertNotFound,
    FileAlreadyExists,
    NameConstraintViolation,
    NotUniqueCertOwner,
)
from tiny_ca.managers.async_lifecycle_manager import AsyncCertLifecycleManager

from tiny_ca_gateway.core.schemas import (
    CertifyIntermediateCARequest,
    IntermediateCARequest,
)


def error_status(exc: BaseException, default: int) -> int:
    """
    HTTP status for a tiny-ca exception: 409 for conflicts with existing
    state (revoked certificate, duplicate common name), 422 for name
    constraint violations, 404 for unknown certificates, else *default*.
    """
    if isinstance(
        exc, CertificateRevokedError | NotUniqueCertOwner | FileAlreadyExists
    ):
        return 409
    if isinstance(exc, NameConstraintViolation):
        return 422
    if isinstance(exc, CertNotFound):
        return 404
    return default


def load_pem_csr(pem: str) -> x509.CertificateSigningRequest:
    """Parse a PEM CSR; raises ValueError on failure."""
    try:
        return x509.load_pem_x509_csr(pem.encode())
    except Exception as exc:
        raise ValueError(f"Invalid PEM CSR: {exc}") from exc


async def issue_intermediate(
    mgr: AsyncCertLifecycleManager, payload: IntermediateCARequest, uuid_str: str
) -> x509.Certificate:
    """Generate a key pair and issue an intermediate CA certificate."""
    cert, _ = await mgr.issue_intermediate_ca(
        common_name=payload.common_name,
        key_algorithm=payload.key_algorithm,
        key_size=payload.key_size,
        days_valid=payload.days_valid,
        path_length=payload.path_length,
        organization=payload.organization,
        country=payload.country,
        name_constraints=payload.name_constraints,
        is_overwrite=payload.is_overwrite,
        uuid_str=uuid_str,
    )
    return cert


async def certify_intermediate(
    mgr: AsyncCertLifecycleManager,
    payload: CertifyIntermediateCARequest,
    uuid_str: str,
) -> x509.Certificate:
    """
    Issue an intermediate CA certificate for the key in *payload.csr*.

    Raises ValueError for an unparsable CSR and ``ValidationCertError``
    for a CSR whose signature does not verify.
    """
    return await mgr.certify_intermediate_ca(
        subject_key=load_pem_csr(payload.csr),
        common_name=payload.common_name,
        days_valid=payload.days_valid,
        path_length=payload.path_length,
        organization=payload.organization,
        country=payload.country,
        name_constraints=payload.name_constraints,
        is_overwrite=payload.is_overwrite,
        uuid_str=uuid_str,
    )
