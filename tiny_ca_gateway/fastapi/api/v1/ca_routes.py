from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from pathlib import Path
from typing import Any, Literal
import uuid as _uuid_module

import aiofiles
from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding, load_pem_private_key
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from fastapi import Path as FPath
from starlette.responses import FileResponse, StreamingResponse
from tiny_ca.models.certificate import CAConfig, CertificateDetails

from tiny_ca_gateway.core import (
    REASON_MAP,
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
from tiny_ca_gateway.core.schemas import ArtifactType, CRLVerifyResponse
from tiny_ca_gateway.core.summary import RoutesSummary
from tiny_ca_gateway.fastapi.api.v1.utils import (
    load_pem_cert,
    load_pem_crl,
    require_factory,
)
from tiny_ca_gateway.fastapi.auth.verify import verify_token
from tiny_ca_gateway.fastapi.lifespan.manager import FastAPILifespanManager
from tiny_ca_gateway.models import API_SETTINGS

router = APIRouter(prefix="/ca", tags=["ca"])


# ===========================================================================
# Public
# ===========================================================================


@router.get(Routes.GET_PUBLIC_CERT, summary=RoutesSummary.GET_PUBLIC_CERT)
async def get_public_cert() -> FileResponse:
    from pathlib import Path as P

    cert_path = P(API_SETTINGS.path_to_ca_cer)
    if not cert_path.exists():
        from fastapi import HTTPException

        raise HTTPException(
            404, "CA certificate not found — bootstrap first via POST /root"
        )
    return FileResponse(
        cert_path, media_type="application/x-pem-file", filename="ca.pem"
    )


@router.get(
    Routes.BASE_CRL,
    summary=RoutesSummary.BASE_CRL,
    responses={
        200: {"content": {"application/pkix-crl": {}, "application/x-pem-file": {}}},
    },
)
async def crl_route(pem: bool = False) -> Response:
    from pathlib import Path as P

    crl_path = P(API_SETTINGS.path_to_crl)
    if not crl_path.exists():
        mgr = require_factory()
        try:
            await mgr.generate_crl()
        except Exception as exc:
            raise HTTPException(500, f"Failed to generate CRL: {exc}") from exc
    if not crl_path.exists():
        raise HTTPException(500, "CRL file still not found after generation attempt")
    async with aiofiles.open(crl_path, "rb") as fh:
        content = await fh.read()
    if pem:
        if not content.startswith(b"-----"):
            crl_obj = x509.load_der_x509_crl(content)
            content = crl_obj.public_bytes(Encoding.PEM)
        return Response(
            content,
            media_type="application/x-pem-file",
            headers={"Content-Disposition": 'attachment; filename="ca.crl.pem"'},
        )
    return Response(
        content,
        media_type="application/pkix-crl",
        headers={
            "Content-Disposition": 'attachment; filename="ca.crl"',
            "Cache-Control": "max-age=3600",
        },
    )


# ===========================================================================
# List / search
# ===========================================================================


@router.get(
    Routes.GET_LIST_CERTS,
    summary=RoutesSummary.GET_LIST_CERTS,
    response_model=list[CertListItem],
)
async def list_certificates(
    token: str = Depends(verify_token),
    status: str | None = Query(default=None),
    key_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[CertListItem]:
    mgr = require_factory()
    records = await mgr.list_certificates(
        status=status, key_type=key_type, limit=limit, offset=offset
    )
    return [record_to_item(r) for r in records]


@router.get(
    Routes.GET_LIST_EXPIRING_CERTS,
    summary=RoutesSummary.GET_LIST_EXPIRING_CERTS,
    response_model=ExpiringResponse,
)
async def get_expiring(
    token: str = Depends(verify_token),
    within_days: int = Query(default=30, ge=1, le=365),
) -> ExpiringResponse:
    mgr = require_factory()
    records = await mgr.get_expiring_soon(within_days=within_days)
    return ExpiringResponse(
        within_days=within_days,
        count=len(records),
        certificates=[record_to_item(r) for r in records],
    )


# ===========================================================================
# CA bootstrap / issuance
# ===========================================================================


@router.post(
    Routes.CA_ROOT, summary=RoutesSummary.CA_ROOT, response_model=CreateRootCaResponse
)
async def create_root_ca(
    token: str = Depends(verify_token),
    payload: CAConfig = Body(),
) -> CreateRootCaResponse:

    lm = FastAPILifespanManager()
    try:
        await lm.rebuild_root_ca_pair(ca_config=payload)
    except Exception as exc:
        raise HTTPException(409, str(exc)) from exc
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


@router.post(
    Routes.CA_INTERMEDIATE,
    summary=RoutesSummary.CA_INTERMEDIATE,
    response_model=IssueCertResponse,
)
async def issue_intermediate_ca(
    token: str = Depends(verify_token),
    payload: IntermediateCARequest = Body(),
) -> IssueCertResponse:
    from fastapi import HTTPException

    mgr = require_factory()
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
        raise HTTPException(422, str(exc)) from exc
    return IssueCertResponse(
        uuid=_uuid,
        serial_number=cert.serial_number,
        common_name=payload.common_name,
        not_valid_before=cert.not_valid_before_utc,
        not_valid_after=cert.not_valid_after_utc,
    )


@router.post(
    Routes.ISSUE, summary=RoutesSummary.ISSUE, response_model=IssueCertResponse
)
async def issue_certificate(
    token: str = Depends(verify_token),
    payload: IssueCertRequest = Body(),
) -> IssueCertResponse:
    from fastapi import HTTPException

    mgr = require_factory()
    _uuid = str(_uuid_module.uuid4())
    try:
        # ВАЖНО: Валидация key_size ПЕРЕД issue_certificate
        if payload.key_size and (payload.key_size < 2048 or payload.key_size > 4096):
            raise HTTPException(
                400, f"Invalid key_size: {payload.key_size}. Must be 2048-4096."
            )

        cert, _, _ = await mgr.issue_certificate(
            config=build_client_config(payload),
            uuid_str=_uuid,
            is_overwrite=payload.is_overwrite,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        # Ловим ошибки валидации от tiny_ca
        if "key" in str(exc).lower():
            raise HTTPException(400, str(exc)) from exc
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(409, str(exc)) from exc
    return IssueCertResponse(
        uuid=_uuid,
        serial_number=cert.serial_number,
        common_name=payload.common_name,
        not_valid_before=cert.not_valid_before_utc,
        not_valid_after=cert.not_valid_after_utc,
    )


@router.post(
    Routes.MAINTENANCE_EXPIRE,
    summary=RoutesSummary.MAINTENANCE_EXPIRE,
    response_model=MaintenanceResponse,
)
async def mark_expired(token: str = Depends(verify_token)) -> MaintenanceResponse:
    return MaintenanceResponse(
        updated=await require_factory().refresh_expired_statuses()
    )


# ===========================================================================
# CRL
# ===========================================================================


@router.post(
    Routes.CRL_REFRESH,
    response_model=CRLRefreshResponse,
    summary=RoutesSummary.CRL_REFRESH,
)
async def refresh_crl(token: str = Depends(verify_token)) -> CRLRefreshResponse:

    try:
        crl = await require_factory().generate_crl()
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc
    return CRLRefreshResponse(next_update=crl.next_update_utc)


@router.post(Routes.CRL_VERIFY, summary=RoutesSummary.CRL_VERIFY)
async def verify_crl(
    token: str = Depends(verify_token), payload: CRLVerifyRequest = Body()
) -> CRLVerifyResponse:
    crl = load_pem_crl(payload.pem)
    try:
        await require_factory().verify_crl(crl=crl)

        return CRLVerifyResponse(valid=True, next_update=str(crl.next_update_utc))
    except Exception as exc:
        return CRLVerifyResponse(valid=False, detail=str(exc))


# ===========================================================================
# Verification / cosign / export
# ===========================================================================


@router.post(
    Routes.VERIFY,
    response_model=VerifyResponse,
    summary=RoutesSummary.VERIFY,
)
async def verify_certificate(
    token: str = Depends(verify_token), payload: VerifyRequest = Body()
) -> VerifyResponse:
    cert = load_pem_cert(payload.pem)
    try:
        # ВАЖНО: verify_certificate может вернуть False вместо исключения
        result = await require_factory().verify_certificate(cert=cert)
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


@router.post(
    Routes.COSIGN,
    response_model=CosignResponse,
    summary=RoutesSummary.COSIGN,
)
async def cosign_certificate(
    token: str = Depends(verify_token), payload: CosignRequest = Body()
) -> CosignResponse:
    from fastapi import HTTPException

    cert = load_pem_cert(payload.pem)
    try:
        cosigned = await require_factory().cosign_certificate(
            cert=cert,
            days_valid=payload.days_valid,
            valid_from=payload.valid_from,
        )
    except Exception as exc:
        raise HTTPException(422, str(exc)) from exc
    return CosignResponse(
        serial_number=cosigned.serial_number,
        not_valid_before=cosigned.not_valid_before_utc,
        not_valid_after=cosigned.not_valid_after_utc,
        pem=cosigned.public_bytes(Encoding.PEM).decode(),
    )


@router.post(Routes.EXPORT, summary=RoutesSummary.EXPORT)
async def export_pkcs12(
    token: str = Depends(verify_token),
    serial: int = FPath(),
    payload: ExportP12Request = Body(default=ExportP12Request()),
) -> Response:
    from fastapi import HTTPException

    mgr = require_factory()
    record = await mgr._db.get_by_serial(serial=serial)
    if record is None:
        raise HTTPException(404, f"Certificate serial={serial} not found")
    if not record.uuid:
        raise HTTPException(404, "No storage UUID for this certificate")
    key_path = await get_artifact_path(record.uuid, "key")
    if key_path is None:
        raise HTTPException(404, "Private key not found in storage")
    async with aiofiles.open(key_path, "rb") as fh:
        private_key = load_pem_private_key(await fh.read(), password=None)
    cert = x509.load_pem_x509_certificate(record.certificate_pem.encode())
    password = payload.password.encode() if payload.password else None
    p12_bytes = await mgr.export_pkcs12(
        cert=cert, private_key=private_key, password=password
    )
    filename = (record.common_name or str(serial)).replace(" ", "_")
    return Response(
        p12_bytes,
        media_type="application/x-pkcs12",
        headers={"Content-Disposition": f'attachment; filename="{filename}.p12"'},
    )


# ===========================================================================
# Mutations
# ===========================================================================


@router.patch(
    Routes.REVOKE, response_model=RevokeResponse, summary=RoutesSummary.REVOKE
)
async def revoke_certificate(
    token: str = Depends(verify_token), payload: RevokeRequest = Body()
) -> RevokeResponse:
    from fastapi import HTTPException

    reason = REASON_MAP.get(payload.reason, x509.ReasonFlags.unspecified)
    ok = await require_factory().revoke_certificate(
        serial=payload.serial_number, reason=reason
    )
    if not ok:
        raise HTTPException(
            404, f"No valid certificate with serial={payload.serial_number}"
        )
    return RevokeResponse(revoked=True, serial_number=payload.serial_number)


@router.post(
    Routes.ROTATE,
    response_model=RotateResponse,
    summary=RoutesSummary.ROTATE,
)
async def rotate_certificate(
    token: str = Depends(verify_token),
    serial: int = FPath(),
    payload: IssueCertRequest = Body(),
) -> RotateResponse:
    from fastapi import HTTPException

    _uuid = str(_uuid_module.uuid4())
    try:
        new_cert, _, _ = await require_factory().rotate_certificate(
            serial=serial, config=build_client_config(payload)
        )
    except Exception as exc:
        raise HTTPException(404, str(exc)) from exc
    return RotateResponse(
        uuid=_uuid,
        serial_number=new_cert.serial_number,
        common_name=payload.common_name,
        not_valid_before=new_cert.not_valid_before_utc,
        not_valid_after=new_cert.not_valid_after_utc,
    )


@router.post(
    Routes.RENEW,
    response_model=RenewResponse,
    summary=RoutesSummary.RENEW,
)
async def renew_certificate(
    token: str = Depends(verify_token),
    serial: int = FPath(),
    payload: RenewRequest = Body(),
) -> RenewResponse:
    from fastapi import HTTPException

    try:
        renewed = await require_factory().renew_certificate(
            serial=serial, days_valid=payload.days_valid
        )
    except Exception as exc:
        raise HTTPException(404, str(exc)) from exc
    return RenewResponse(
        old_serial=serial,
        new_serial=renewed.serial_number,
        not_valid_after=renewed.not_valid_after_utc,
    )


@router.delete(
    Routes.DELETE,
    response_model=DeleteResponse,
    summary=RoutesSummary.DELETE,
)
async def delete_certificate(
    token: str = Depends(verify_token), serial: int = FPath()
) -> DeleteResponse:
    from fastapi import HTTPException

    if not await require_factory().delete_certificate(serial=serial):
        raise HTTPException(404, f"Certificate serial={serial} not found")
    return DeleteResponse(deleted=True, serial=serial)


# ===========================================================================
# Inspection
# ===========================================================================


@router.get(
    Routes.STATUS,
    response_model=StatusResponse,
    summary=RoutesSummary.STATUS,
)
async def get_status(
    token: str = Depends(verify_token), serial: int = FPath()
) -> StatusResponse:
    status = await require_factory().get_certificate_status(serial=serial)
    return StatusResponse(serial=serial, status=str(status))


@router.get(Routes.INSPECT, summary=RoutesSummary.INSPECT)
async def inspect_certificate(
    token: str = Depends(verify_token), serial: int = FPath()
) -> CertificateDetails:

    mgr = require_factory()
    record = await mgr._db.get_by_serial(serial=serial)
    if record is None:
        raise HTTPException(404, f"Certificate serial={serial} not found")
    cert = x509.load_pem_x509_certificate(record.certificate_pem.encode())
    return await mgr.inspect_certificate(cert=cert)


@router.get(
    Routes.CHAIN,
    response_model=ChainResponse,
    summary=RoutesSummary.CHAIN,
)
async def get_cert_chain(
    token: str = Depends(verify_token), serial: int = FPath()
) -> ChainResponse:

    mgr = require_factory()
    record = await mgr._db.get_by_serial(serial=serial)
    if record is None:
        raise HTTPException(404, f"Certificate serial={serial} not found")
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


@router.get(Routes.DOWNLOAD_STREAM, summary=RoutesSummary.DOWNLOAD_STREAM)
async def stream_artefact(
    token: str = Depends(verify_token),
    uuid_certificate: str = FPath(),
    object_type: Literal["pem", "key", "csr"] = Query(),
) -> StreamingResponse:

    path = await get_artifact_path(uuid_certificate, object_type)
    if path is None:
        raise HTTPException(404, "Artefact not found")

    async def _iter(p: Path, chunk: int = 1024 * 1024) -> AsyncGenerator[bytes, None]:
        async with aiofiles.open(p, "rb") as fh:
            while data := await fh.read(chunk):
                yield data

    return StreamingResponse(
        _iter(path),
        media_type="application/x-pem-file",
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )


@router.get(Routes.DOWNLOAD, summary=RoutesSummary.DOWNLOAD)
async def download_artefact(
    token: str = Depends(verify_token),
    uuid_certificate: str = FPath(),
    object_type: ArtifactType = Query(),
) -> FileResponse:
    from fastapi import HTTPException

    path = await get_artifact_path(uuid_certificate, object_type)
    if path is None:
        raise HTTPException(404, "Artefact not found")
    return FileResponse(path, media_type="application/x-pem-file", filename=path.name)
