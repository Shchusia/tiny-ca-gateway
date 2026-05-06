from __future__ import annotations

import datetime
from typing import Literal

from cryptography import x509 as _x509
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Reason map
# ---------------------------------------------------------------------------

REASON_MAP: dict[str, _x509.ReasonFlags] = {
    "unspecified": _x509.ReasonFlags.unspecified,
    "keyCompromise": _x509.ReasonFlags.key_compromise,
    "cACompromise": _x509.ReasonFlags.ca_compromise,
    "affiliationChanged": _x509.ReasonFlags.affiliation_changed,
    "superseded": _x509.ReasonFlags.superseded,
    "cessationOfOperation": _x509.ReasonFlags.cessation_of_operation,
    "certificateHold": _x509.ReasonFlags.certificate_hold,
    "removeFromCRL": _x509.ReasonFlags.remove_from_crl,
    "privilegeWithdrawn": _x509.ReasonFlags.privilege_withdrawn,
    "aACompromise": _x509.ReasonFlags.aa_compromise,
}

ArtifactType = Literal["pem", "key", "csr"]

# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class CertListItem(BaseModel):
    serial_number: str
    common_name: str
    status: str
    key_type: str | None
    not_valid_after: datetime.datetime
    uuid: str | None


class ExpiringResponse(BaseModel):
    within_days: int
    count: int
    certificates: list[CertListItem]


class CreateRootCaResponse(BaseModel):
    ca_id: str = Field(description="Storage UUID of the new CA.")
    expires_at: str = ""


class IssueCertResponse(BaseModel):
    uuid: str
    serial_number: int
    common_name: str
    not_valid_before: datetime.datetime
    not_valid_after: datetime.datetime


class MaintenanceResponse(BaseModel):
    updated: int


class VerifyResponse(BaseModel):
    valid: bool
    detail: str = ""


class CRLRefreshResponse(BaseModel):
    next_update: datetime.datetime


class RevokeResponse(BaseModel):
    revoked: bool
    serial_number: int


class DeleteResponse(BaseModel):
    deleted: bool
    serial: int


class StatusResponse(BaseModel):
    serial: int
    status: str


class RenewResponse(BaseModel):
    old_serial: int
    new_serial: int
    not_valid_after: datetime.datetime


class CosignResponse(BaseModel):
    serial_number: int
    not_valid_before: datetime.datetime
    not_valid_after: datetime.datetime
    pem: str


class ChainResponse(BaseModel):
    serial: int
    chain_length: int
    chain: list[str]


class RotateResponse(BaseModel):
    uuid: str
    serial_number: int
    common_name: str
    not_valid_before: datetime.datetime
    not_valid_after: datetime.datetime


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class IntermediateCARequest(BaseModel):
    common_name: str
    key_size: int = Field(default=4096, ge=2048, le=8192)
    days_valid: int = Field(default=1825, ge=1, le=36500)
    path_length: int | None = 0
    organization: str | None = None
    country: str | None = "UA"


class IssueCertRequest(BaseModel):
    common_name: str
    key_size: int = Field(default=2048, ge=1024, le=8192)
    days_valid: int = Field(default=365, ge=1, le=36500)
    valid_from: datetime.datetime | None = None
    email: str | None = None
    is_server_cert: bool = False
    is_client_cert: bool = False
    san_dns: list[str] | None = None
    san_ip: list[str] | None = None
    is_overwrite: bool = False


class CRLVerifyRequest(BaseModel):
    pem: str = Field(description="PEM-encoded CRL.")


class CRLVerifyResponse(BaseModel):
    valid: bool
    detail: str = ""
    next_update: str = ""


class VerifyRequest(BaseModel):
    pem: str = Field(description="PEM-encoded X.509 certificate.")


class CosignRequest(BaseModel):
    pem: str = Field(description="PEM-encoded certificate to co-sign.")
    days_valid: int | None = None
    valid_from: datetime.datetime | None = None


class ExportP12Request(BaseModel):
    password: str | None = Field(
        default=None,
        description="Passphrase to encrypt the PKCS#12 bundle.",
    )


class RevokeRequest(BaseModel):
    serial_number: int
    reason: str = Field(
        default="unspecified",
        description="unspecified | keyCompromise | cACompromise | ...",
    )


class RenewRequest(BaseModel):
    days_valid: int = Field(default=365, ge=1, le=36500)
