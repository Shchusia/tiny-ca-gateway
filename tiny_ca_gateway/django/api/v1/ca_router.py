from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any
import uuid as _uuid_module

import aiofiles
from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding, load_pem_private_key
from django.http import HttpRequest, HttpResponse, StreamingHttpResponse
from ninja import Router
from ninja.errors import HttpError
from ninja.security import HttpBearer
from tiny_ca.managers.async_lifecycle_manager import AsyncCertLifecycleManager
from tiny_ca.models.certificate import CAConfig, CertificateDetails

from tiny_ca_gateway.core import (
    REASON_MAP,
    ArtifactType,
    CertListItem,
    ChainResponse,
    CosignRequest,
    CosignResponse,
    CreateRootCaResponse,
    CRLRefreshResponse,
    CRLVerifyRequest,
    DeleteResponse,
    ExpiringResponse,
    ExportP12Request,
    IntermediateCARequest,
    IssueCertRequest,
    IssueCertResponse,
    MaintenanceResponse,
    RenewRequest,
    RenewResponse,
    RevokeRequest,
    RevokeResponse,
    RotateResponse,
    Routes,
    StatusResponse,
    VerifyRequest,
    VerifyResponse,
    build_client_config,
    get_artifact_path,
    record_to_item,
)
from tiny_ca_gateway.core.auth import auth_enabled, check_token, extract_bearer
from tiny_ca_gateway.core.helpers import (
    load_pem_cert as __load_pem_cert,
)
from tiny_ca_gateway.core.helpers import (
    load_pem_crl as __load_pem_crl,
)
from tiny_ca_gateway.core.schemas import CRLVerifyResponse
from tiny_ca_gateway.core.summary import RoutesSummary
from tiny_ca_gateway.django.lifespan.manager import DjangoCALifespanManager
from tiny_ca_gateway.models import API_SETTINGS

ca_router = Router(tags=["ca"])


# ---------------------------------------------------------------------------
# Django Ninja-specific wrappers
# ---------------------------------------------------------------------------


class TokenAuth(HttpBearer):
    """
    Bearer token auth.

    HttpBearer вызывает authenticate() только когда заголовок Authorization
    ПРИСУТСТВУЕТ. Если заголовка нет — Ninja сам возвращает 401 до нашего кода.
    Переопределяем __call__: если auth выключен — пропускаем всё.
    """

    def __call__(self, request: HttpRequest) -> Any:
        if not auth_enabled():
            return "open"
        return super().__call__(request)

    def authenticate(self, request: HttpRequest, token: str) -> str | None:
        if check_token(token):
            return token
        raise HttpError(401, "Invalid or missing bearer token.")


token_auth = TokenAuth()


def _require_factory() -> AsyncCertLifecycleManager:
    mgr = DjangoCALifespanManager().manager
    if mgr.factory is None:
        raise HttpError(503, "CA not initialised — call POST /ca/root to bootstrap.")
    return mgr


def _load_pem_cert(pem: str) -> x509.Certificate:
    try:
        return __load_pem_cert(pem)
    except ValueError as exc:
        raise HttpError(422, str(exc)) from exc


def _load_pem_crl(pem: str) -> x509.CertificateRevocationList:
    try:
        return __load_pem_crl(pem)
    except ValueError as exc:
        raise HttpError(422, str(exc)) from exc


# ===========================================================================
# Public
# ===========================================================================


@ca_router.get(Routes.GET_PUBLIC_CERT, summary=RoutesSummary.GET_PUBLIC_CERT, auth=None)
async def get_public_cert(request: HttpRequest) -> HttpResponse:
    cert_path = Path(API_SETTINGS.path_to_ca_cer)
    if not cert_path.exists():
        raise HttpError(404, "CA not bootstrapped — POST /ca/root first.")
    return HttpResponse(
        cert_path.read_bytes(),
        content_type="application/x-pem-file",
        headers={"Content-Disposition": 'attachment; filename="ca.pem"'},
    )


@ca_router.get(Routes.BASE_CRL, summary=RoutesSummary.BASE_CRL, auth=None)
async def crl_route(request: HttpRequest, pem: bool = False) -> HttpResponse:
    crl_path = Path(API_SETTINGS.path_to_crl)
    if not crl_path.exists():
        try:
            await _require_factory().generate_crl()
        except Exception as exc:
            raise HttpError(500, str(exc)) from exc
    if not crl_path.exists():
        raise HttpError(500, "CRL not found after generation.")
    async with aiofiles.open(crl_path, "rb") as fh:
        content = await fh.read()
    if pem:
        if not content.startswith(b"-----"):
            content = x509.load_der_x509_crl(content).public_bytes(Encoding.PEM)
        return HttpResponse(
            content,
            content_type="application/x-pem-file",
            headers={"Content-Disposition": 'attachment; filename="ca.crl.pem"'},
        )
    return HttpResponse(
        content,
        content_type="application/pkix-crl",
        headers={
            "Content-Disposition": 'attachment; filename="ca.crl"',
            "Cache-Control": "max-age=3600",
        },
    )


# ===========================================================================
# List
# ===========================================================================


@ca_router.get(
    "/",
    response=list[CertListItem],
    auth=token_auth,
    summary=RoutesSummary.GET_LIST_CERTS,
)
@ca_router.get(
    Routes.GET_LIST_CERTS,
    summary=RoutesSummary.GET_LIST_CERTS,
    response=list[CertListItem],
    auth=token_auth,
)
async def list_certificates(
    request: HttpRequest,
    status: str | None = None,
    key_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[CertListItem]:
    records = await _require_factory().list_certificates(
        status=status,
        key_type=key_type,
        limit=max(1, min(limit, 1000)),
        offset=max(0, offset),
    )
    return [record_to_item(r) for r in records]


@ca_router.get(
    Routes.GET_LIST_EXPIRING_CERTS,
    summary=RoutesSummary.GET_LIST_EXPIRING_CERTS,
    response=ExpiringResponse,
    auth=token_auth,
)
async def get_expiring(request: HttpRequest, within_days: int = 30) -> ExpiringResponse:
    records = await _require_factory().get_expiring_soon(
        within_days=max(1, min(within_days, 365))
    )
    return ExpiringResponse(
        within_days=within_days,
        count=len(records),
        certificates=[record_to_item(r) for r in records],
    )


# ===========================================================================
# CA bootstrap
# ===========================================================================


@ca_router.post(
    Routes.CA_ROOT,
    summary=RoutesSummary.CA_ROOT,
    response=CreateRootCaResponse,
    auth=token_auth,
)
async def create_root_ca(
    request: HttpRequest, payload: CAConfig
) -> CreateRootCaResponse:
    lm = DjangoCALifespanManager()
    try:
        await lm.rebuild_root_ca_pair(ca_config=payload)
    except Exception as exc:
        raise HttpError(409, str(exc)) from exc
    try:
        await lm.rebuild_manager()
    except Exception as exc:
        lm.logger.error("Factory reload failed: %s", exc)
    cert_obj = x509.load_pem_x509_certificate(
        Path(API_SETTINGS.path_to_ca_cer).read_bytes()
    )
    return CreateRootCaResponse(
        ca_id="",
        expires_at=cert_obj.not_valid_after_utc.strftime(API_SETTINGS.datetime_fmt),
    )


@ca_router.post(
    Routes.CA_INTERMEDIATE,
    summary=RoutesSummary.CA_INTERMEDIATE,
    response=IssueCertResponse,
    auth=token_auth,
)
async def issue_intermediate_ca(
    request: HttpRequest, payload: IntermediateCARequest
) -> IssueCertResponse:
    mgr = _require_factory()
    _uuid = str(_uuid_module.uuid4())
    try:
        cert, _ = await mgr.issue_intermediate_ca(
            common_name=payload.common_name,
            key_size=payload.key_size,
            days_valid=payload.days_valid,
            path_length=payload.path_length,
            organization=payload.organization,
            country=payload.country,
            uuid_str=_uuid,
        )
    except Exception as exc:
        raise HttpError(422, str(exc)) from exc
    return IssueCertResponse(
        uuid=_uuid,
        serial_number=cert.serial_number,
        common_name=payload.common_name,
        not_valid_before=cert.not_valid_before_utc,
        not_valid_after=cert.not_valid_after_utc,
    )


@ca_router.post(
    Routes.ISSUE,
    summary=RoutesSummary.ISSUE,
    response=IssueCertResponse,
    auth=token_auth,
)
async def issue_certificate(
    request: HttpRequest, payload: IssueCertRequest
) -> IssueCertResponse:
    mgr = _require_factory()
    _uuid = str(_uuid_module.uuid4())
    try:
        # ВАЖНО: Валидация key_size ПЕРЕД issue_certificate
        if payload.key_size and (payload.key_size < 2048 or payload.key_size > 4096):
            raise HttpError(
                400, f"Invalid key_size: {payload.key_size}. Must be 2048-4096."
            )

        cert, _, _ = await mgr.issue_certificate(
            config=build_client_config(payload),
            uuid_str=_uuid,
            is_overwrite=payload.is_overwrite,
        )
    except HttpError:
        raise
    except ValueError as exc:
        # Ловим ошибки валидации от tiny_ca
        if "key" in str(exc).lower():
            raise HttpError(400, str(exc)) from exc
        raise HttpError(409, str(exc)) from exc
    except Exception as exc:
        raise HttpError(409, str(exc)) from exc
    return IssueCertResponse(
        uuid=_uuid,
        serial_number=cert.serial_number,
        common_name=payload.common_name,
        not_valid_before=cert.not_valid_before_utc,
        not_valid_after=cert.not_valid_after_utc,
    )


@ca_router.post(
    Routes.MAINTENANCE_EXPIRE,
    summary=RoutesSummary.MAINTENANCE_EXPIRE,
    response=MaintenanceResponse,
    auth=token_auth,
)
async def mark_expired(request: HttpRequest) -> MaintenanceResponse:
    return MaintenanceResponse(
        updated=await _require_factory().refresh_expired_statuses()
    )


# ===========================================================================
# CRL
# ===========================================================================


@ca_router.post(Routes.CRL_REFRESH, response=CRLRefreshResponse, auth=token_auth)
async def refresh_crl(request: HttpRequest) -> CRLRefreshResponse:
    try:
        crl = await _require_factory().generate_crl()
    except Exception as exc:
        raise HttpError(500, str(exc)) from exc
    return CRLRefreshResponse(next_update=crl.next_update_utc)


@ca_router.post(Routes.CRL_VERIFY, summary=RoutesSummary.CRL_VERIFY, auth=token_auth)
async def verify_crl(
    request: HttpRequest, payload: CRLVerifyRequest
) -> CRLVerifyResponse:
    crl = _load_pem_crl(payload.pem)
    try:
        await _require_factory().verify_crl(crl=crl)
        return CRLVerifyResponse(valid=True, next_update=str(crl.next_update_utc))

    except Exception as exc:
        return CRLVerifyResponse(valid=False, detail=str(exc))


# ===========================================================================
# Verification / cosign / export
# ===========================================================================


@ca_router.post(
    Routes.VERIFY,
    summary=RoutesSummary.VERIFY,
    response=VerifyResponse,
    auth=token_auth,
)
async def verify_certificate(
    request: HttpRequest, payload: VerifyRequest
) -> VerifyResponse:
    cert = _load_pem_cert(payload.pem)
    try:
        # ВАЖНО: verify_certificate может вернуть False вместо исключения
        result = await _require_factory().verify_certificate(cert=cert)
        # Если результат — это кортеж (valid, reason), обработать
        if isinstance(result, tuple):
            valid, reason = result
            if valid:
                return VerifyResponse(valid=True)
            else:
                return VerifyResponse(
                    valid=False, detail=reason or "Verification failed"
                )
        # Если просто исключение не выброшено — сертификат валиден
        return VerifyResponse(valid=True)
    except Exception as exc:
        return VerifyResponse(valid=False, detail=str(exc))


@ca_router.post(
    Routes.COSIGN,
    summary=RoutesSummary.COSIGN,
    response=CosignResponse,
    auth=token_auth,
)
async def cosign_certificate(
    request: HttpRequest, payload: CosignRequest
) -> CosignResponse:
    cert = _load_pem_cert(payload.pem)
    try:
        cosigned = await _require_factory().cosign_certificate(
            cert=cert,
            days_valid=payload.days_valid,
            valid_from=payload.valid_from,
        )
    except Exception as exc:
        raise HttpError(422, str(exc)) from exc
    return CosignResponse(
        serial_number=cosigned.serial_number,
        not_valid_before=cosigned.not_valid_before_utc,
        not_valid_after=cosigned.not_valid_after_utc,
        pem=cosigned.public_bytes(Encoding.PEM).decode(),
    )


@ca_router.post(Routes.EXPORT, summary=RoutesSummary.EXPORT, auth=token_auth)
async def export_pkcs12(
    request: HttpRequest, serial: int, payload: ExportP12Request
) -> HttpResponse:
    mgr = _require_factory()
    record = await mgr._db.get_by_serial(serial=serial)
    if not record:
        raise HttpError(404, f"Certificate serial={serial} not found")
    key_path = await get_artifact_path(record.uuid, "key")
    if not key_path:
        raise HttpError(404, "Private key not found in storage")
    async with aiofiles.open(key_path, "rb") as fh:
        private_key = load_pem_private_key(await fh.read(), password=None)
    p12 = await mgr.export_pkcs12(
        cert=x509.load_pem_x509_certificate(record.certificate_pem.encode()),
        private_key=private_key,
        password=payload.password.encode() if payload.password else None,
    )
    fname = (record.common_name or str(serial)).replace(" ", "_")
    return HttpResponse(
        p12,
        content_type="application/x-pkcs12",
        headers={"Content-Disposition": f'attachment; filename="{fname}.p12"'},
    )


# ===========================================================================
# Mutations
# ===========================================================================


@ca_router.patch(
    Routes.REVOKE,
    summary=RoutesSummary.REVOKE,
    response=RevokeResponse,
    auth=token_auth,
)
async def revoke_certificate(
    request: HttpRequest, payload: RevokeRequest
) -> RevokeResponse:
    reason = REASON_MAP.get(payload.reason, x509.ReasonFlags.unspecified)
    ok = await _require_factory().revoke_certificate(
        serial=payload.serial_number, reason=reason
    )
    if not ok:
        raise HttpError(
            404, f"No valid certificate with serial={payload.serial_number}"
        )
    return RevokeResponse(revoked=True, serial_number=payload.serial_number)


@ca_router.post(
    Routes.ROTATE,
    summary=RoutesSummary.ROTATE,
    response=RotateResponse,
    auth=token_auth,
)
async def rotate_certificate(
    request: HttpRequest, serial: int, payload: IssueCertRequest
) -> RotateResponse:
    _uuid = str(_uuid_module.uuid4())
    try:
        new_cert, _, _ = await _require_factory().rotate_certificate(
            serial=serial, config=build_client_config(payload)
        )
    except Exception as exc:
        raise HttpError(404, str(exc)) from exc
    return RotateResponse(
        uuid=_uuid,
        serial_number=new_cert.serial_number,
        common_name=payload.common_name,
        not_valid_before=new_cert.not_valid_before_utc,
        not_valid_after=new_cert.not_valid_after_utc,
    )


@ca_router.post(
    Routes.RENEW, summary=RoutesSummary.RENEW, response=RenewResponse, auth=token_auth
)
async def renew_certificate(
    request: HttpRequest, serial: int, payload: RenewRequest
) -> RenewResponse:
    try:
        renewed = await _require_factory().renew_certificate(
            serial=serial, days_valid=payload.days_valid
        )
    except Exception as exc:
        raise HttpError(404, str(exc)) from exc
    return RenewResponse(
        old_serial=serial,
        new_serial=renewed.serial_number,
        not_valid_after=renewed.not_valid_after_utc,
    )


@ca_router.delete(
    Routes.DELETE,
    summary=RoutesSummary.DELETE,
    response=DeleteResponse,
    auth=token_auth,
)
async def delete_certificate(request: HttpRequest, serial: int) -> DeleteResponse:
    if not await _require_factory().delete_certificate(serial=serial):
        raise HttpError(404, f"Certificate serial={serial} not found")
    return DeleteResponse(deleted=True, serial=serial)


# ===========================================================================
# Inspection
# ===========================================================================


@ca_router.get(
    Routes.STATUS,
    summary=RoutesSummary.STATUS,
    response=StatusResponse,
    auth=token_auth,
)
async def get_status(request: HttpRequest, serial: int) -> StatusResponse:
    status = await _require_factory().get_certificate_status(serial=serial)
    return StatusResponse(serial=serial, status=str(status))


@ca_router.get(Routes.INSPECT, auth=token_auth, summary=Routes.INSPECT)
async def inspect_certificate(request: HttpRequest, serial: int) -> CertificateDetails:
    mgr = _require_factory()
    record = await mgr._db.get_by_serial(serial=serial)
    if not record:
        raise HttpError(404, f"Certificate serial={serial} not found")
    cert = x509.load_pem_x509_certificate(record.certificate_pem.encode())
    return await mgr.inspect_certificate(cert=cert)


@ca_router.get(
    Routes.CHAIN,
    response=ChainResponse,
    auth=token_auth,
    summary=RoutesSummary.CHAIN,
)
async def get_cert_chain(request: HttpRequest, serial: int) -> ChainResponse:
    mgr = _require_factory()
    record = await mgr._db.get_by_serial(serial=serial)
    if not record:
        raise HttpError(404, f"Certificate serial={serial} not found")
    cert = x509.load_pem_x509_certificate(record.certificate_pem.encode())
    chain = await mgr.get_cert_chain(cert=cert)
    return ChainResponse(
        serial=serial,
        chain_length=len(chain),
        chain=[c.public_bytes(Encoding.PEM).decode() for c in chain],
    )


# ===========================================================================
# Downloads
# ===========================================================================


@ca_router.get(
    Routes.DOWNLOAD_STREAM, auth=token_auth, summary=RoutesSummary.DOWNLOAD_STREAM
)
async def stream_artefact(
    request: HttpRequest, uuid_certificate: str, object_type: ArtifactType = "pem"
) -> StreamingHttpResponse:
    path = await get_artifact_path(uuid_certificate, object_type)
    if not path:
        raise HttpError(404, "Artefact not found")

    async def _iter(p: Path, chunk: int = 1024 * 1024) -> AsyncGenerator[bytes, None]:
        async with aiofiles.open(p, "rb") as fh:
            while data := await fh.read(chunk):
                yield data

    return StreamingHttpResponse(
        _iter(path),
        content_type="application/x-pem-file",
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )


@ca_router.get(
    "/artifact/{uuid_certificate}", auth=token_auth, summary=RoutesSummary.DOWNLOAD
)
async def download_artefact(
    request: HttpRequest, uuid_certificate: str, object_type: ArtifactType = "pem"
) -> HttpResponse:
    path = await get_artifact_path(uuid_certificate, object_type)
    if not path:
        raise HttpError(404, "Artefact not found")
    async with aiofiles.open(path, "rb") as fh:
        content = await fh.read()
    return HttpResponse(
        content,
        content_type="application/x-pem-file",
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )
