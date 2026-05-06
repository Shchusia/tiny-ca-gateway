from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import uuid as _uuid_module

import aiofiles
from aiohttp import web
from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding, load_pem_private_key
from pydantic import BaseModel, ValidationError
from tiny_ca.managers.async_lifecycle_manager import AsyncCertLifecycleManager
from tiny_ca.models.certificate import CAConfig

from tiny_ca_gateway.aiohttp.lifespan.manager import AiohttpCAManager
from tiny_ca_gateway.core import (
    REASON_MAP,
    CosignRequest,
    CRLVerifyRequest,
    ExportP12Request,
    IntermediateCARequest,
    IssueCertRequest,
    RenewRequest,
    RevokeRequest,
    Routes,
    VerifyRequest,
    build_client_config,
    get_artifact_path,
    record_to_item,
)
from tiny_ca_gateway.core.helpers import load_pem_cert, load_pem_crl
from tiny_ca_gateway.models import API_SETTINGS

routes = web.RouteTableDef()


# ---------------------------------------------------------------------------
# aiohttp-specific wrappers
# ---------------------------------------------------------------------------


def _require_factory() -> AsyncCertLifecycleManager:
    mgr = AiohttpCAManager().manager
    if mgr.factory is None:
        raise web.HTTPServiceUnavailable(
            content_type="application/json",
            text='{"detail": "CA not initialised — POST /ca/root first."}',
        )
    return mgr


def _verify_token(request: web.Request) -> None:
    expected = getattr(API_SETTINGS, "api_token", None)
    if not expected:
        return
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth[7:] != expected:
        raise web.HTTPUnauthorized(
            content_type="application/json",
            text='{"detail": "Invalid or missing bearer token."}',
        )


def _load_pem_cert(pem: str) -> x509.Certificate:
    try:
        return load_pem_cert(pem)
    except ValueError as exc:
        raise web.HTTPUnprocessableEntity(
            content_type="application/json", text=json.dumps({"detail": str(exc)})
        ) from exc


def _load_pem_crl(pem: str) -> x509.CertificateRevocationList:
    try:
        return load_pem_crl(pem)
    except ValueError as exc:
        raise web.HTTPUnprocessableEntity(
            content_type="application/json", text=json.dumps({"detail": str(exc)})
        ) from exc


async def _parse(request: web.Request, model_cls: type[BaseModel]) -> Any:
    try:
        return model_cls.model_validate(await request.json())
    except ValidationError as exc:
        raise web.HTTPUnprocessableEntity(
            content_type="application/json", text=exc.json()
        ) from exc
    except Exception as exc:
        raise web.HTTPBadRequest(
            content_type="application/json",
            text=json.dumps({"detail": f"Invalid JSON: {exc}"}),
        ) from exc


def _resp(data: dict[str, Any] | list[Any], status: int = 200) -> web.Response:
    if hasattr(data, "model_dump"):
        payload = data.model_dump(mode="json")
    elif isinstance(data, list):
        payload = [
            i.model_dump(mode="json") if hasattr(i, "model_dump") else i for i in data
        ]
    else:
        payload = data
    return web.Response(
        text=json.dumps(payload, default=str),
        content_type="application/json",
        status=status,
    )


def _err(detail: str, status: int) -> web.Response:
    return web.Response(
        text=json.dumps({"detail": detail}),
        content_type="application/json",
        status=status,
    )


# ===========================================================================
# Public
# ===========================================================================


@routes.get(Routes.GET_PUBLIC_CERT)
async def get_public_cert(request: web.Request) -> web.Response:
    cert_path = Path(API_SETTINGS.path_to_ca_cer)
    if not cert_path.exists():
        return _err("CA not bootstrapped — POST /ca/root first.", 404)
    return web.Response(
        body=cert_path.read_bytes(),
        content_type="application/x-pem-file",
        headers={"Content-Disposition": 'attachment; filename="ca.pem"'},
    )


@routes.get(Routes.BASE_CRL)
async def crl_route(request: web.Request) -> web.Response:
    pem_fmt = request.rel_url.query.get("pem", "false").lower() == "true"
    crl_path = Path(API_SETTINGS.path_to_crl)
    if not crl_path.exists():
        try:
            await _require_factory().generate_crl()
        except Exception as exc:
            return _err(str(exc), 500)
    if not crl_path.exists():
        return _err("CRL not found after generation.", 500)
    async with aiofiles.open(crl_path, "rb") as fh:
        content = await fh.read()
    if pem_fmt:
        if not content.startswith(b"-----"):
            content = x509.load_der_x509_crl(content).public_bytes(Encoding.PEM)
        return web.Response(
            body=content,
            content_type="application/x-pem-file",
            headers={"Content-Disposition": 'attachment; filename="ca.crl.pem"'},
        )
    return web.Response(
        body=content,
        content_type="application/pkix-crl",
        headers={
            "Content-Disposition": 'attachment; filename="ca.crl"',
            "Cache-Control": "max-age=3600",
        },
    )


# ===========================================================================
# List
# ===========================================================================


@routes.get("")
@routes.get("/")
async def list_certificates(request: web.Request) -> web.Response:
    _verify_token(request)
    q = request.rel_url.query
    records = await _require_factory().list_certificates(
        status=q.get("status"),
        key_type=q.get("key_type"),
        limit=min(int(q.get("limit", 100)), 1000),
        offset=max(int(q.get("offset", 0)), 0),
    )
    return _resp([record_to_item(r) for r in records])


@routes.get(Routes.GET_LIST_EXPIRING_CERTS)
async def get_expiring(request: web.Request) -> web.Response:
    _verify_token(request)
    within_days = max(1, min(int(request.rel_url.query.get("within_days", 30)), 365))
    records = await _require_factory().get_expiring_soon(within_days=within_days)
    return _resp(
        {
            "within_days": within_days,
            "count": len(records),
            "certificates": [
                record_to_item(r).model_dump(mode="json") for r in records
            ],
        }
    )


# ===========================================================================
# CA bootstrap
# ===========================================================================


@routes.post(Routes.CA_ROOT)
async def create_root_ca(request: web.Request) -> web.Response:
    _verify_token(request)
    lm = AiohttpCAManager()
    payload = await _parse(request, CAConfig)
    try:
        await lm.rebuild_root_ca_pair(ca_config=payload)
    except Exception as exc:
        return _err(str(exc), 409)
    try:
        await lm.rebuild_manager()
    except Exception as exc:
        lm.logger.error("Factory reload failed: %s", exc)
    cert_obj = x509.load_pem_x509_certificate(
        Path(API_SETTINGS.path_to_ca_cer).read_bytes()
    )
    return _resp(
        {
            "ca_id": "",
            "expires_at": cert_obj.not_valid_after_utc.strftime(
                API_SETTINGS.datetime_fmt
            ),
        }
    )


@routes.post(Routes.CA_INTERMEDIATE)
async def issue_intermediate_ca(request: web.Request) -> web.Response:
    _verify_token(request)
    mgr = _require_factory()
    payload = await _parse(request, IntermediateCARequest)
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
        return _err(str(exc), 422)
    return _resp(
        {
            "uuid": _uuid,
            "serial_number": cert.serial_number,
            "common_name": payload.common_name,
            "not_valid_before": cert.not_valid_before_utc.isoformat(),
            "not_valid_after": cert.not_valid_after_utc.isoformat(),
        }
    )


@routes.post(Routes.ISSUE)
async def issue_certificate(request: web.Request) -> web.Response:
    _verify_token(request)
    mgr = _require_factory()
    payload = await _parse(request, IssueCertRequest)
    _uuid = str(_uuid_module.uuid4())
    try:
        cert, _, _ = await mgr.issue_certificate(
            config=build_client_config(payload),
            uuid_str=_uuid,
            is_overwrite=payload.is_overwrite,
        )
    except Exception as exc:
        return _err(str(exc), 409)
    return _resp(
        {
            "uuid": _uuid,
            "serial_number": cert.serial_number,
            "common_name": payload.common_name,
            "not_valid_before": cert.not_valid_before_utc.isoformat(),
            "not_valid_after": cert.not_valid_after_utc.isoformat(),
        },
        status=201,
    )


@routes.post(Routes.MAINTENANCE_EXPIRE)
async def mark_expired(request: web.Request) -> web.Response:
    _verify_token(request)
    return _resp({"updated": await _require_factory().refresh_expired_statuses()})


# ===========================================================================
# CRL
# ===========================================================================


@routes.post(Routes.CRL_REFRESH)
async def refresh_crl(request: web.Request) -> web.Response:
    _verify_token(request)
    try:
        crl = await _require_factory().generate_crl()
    except Exception as exc:
        return _err(str(exc), 500)
    return _resp({"next_update": crl.next_update_utc.isoformat()})


@routes.post(Routes.CRL_VERIFY)
async def verify_crl(request: web.Request) -> web.Response:
    _verify_token(request)
    payload = await _parse(request, CRLVerifyRequest)
    crl = _load_pem_crl(payload.pem)
    try:
        await _require_factory().verify_crl(crl=crl)
        return _resp({"valid": True, "next_update": crl.next_update_utc.isoformat()})
    except Exception as exc:
        return _resp({"valid": False, "detail": str(exc)})


# ===========================================================================
# Verification / cosign / export
# ===========================================================================


@routes.post(Routes.VERIFY)
async def verify_certificate(request: web.Request) -> web.Response:
    _verify_token(request)
    cert = _load_pem_cert((await _parse(request, VerifyRequest)).pem)
    try:
        await _require_factory().verify_certificate(cert=cert)
        return _resp({"valid": True})
    except Exception as exc:
        return _resp({"valid": False, "detail": str(exc)})


@routes.post(Routes.COSIGN)
async def cosign_certificate(request: web.Request) -> web.Response:
    _verify_token(request)
    payload = await _parse(request, CosignRequest)
    cert = _load_pem_cert(payload.pem)
    try:
        cosigned = await _require_factory().cosign_certificate(
            cert=cert,
            days_valid=payload.days_valid,
            valid_from=payload.valid_from,
        )
    except Exception as exc:
        return _err(str(exc), 422)
    return _resp(
        {
            "serial_number": cosigned.serial_number,
            "not_valid_before": cosigned.not_valid_before_utc.isoformat(),
            "not_valid_after": cosigned.not_valid_after_utc.isoformat(),
            "pem": cosigned.public_bytes(Encoding.PEM).decode(),
        }
    )


@routes.post(Routes.EXPORT)
async def export_pkcs12(request: web.Request) -> web.Response:
    _verify_token(request)
    serial = int(request.match_info["serial"])
    mgr = _require_factory()
    payload = await _parse(request, ExportP12Request)
    record = await mgr._db.get_by_serial(serial=serial)
    if not record:
        return _err(f"Certificate serial={serial} not found", 404)
    key_path = await get_artifact_path(record.uuid, "key")
    if not key_path:
        return _err("Private key not found in storage", 404)
    async with aiofiles.open(key_path, "rb") as fh:
        private_key = load_pem_private_key(await fh.read(), password=None)
    p12 = await mgr.export_pkcs12(
        cert=x509.load_pem_x509_certificate(record.certificate_pem.encode()),
        private_key=private_key,
        password=payload.password.encode() if payload.password else None,
    )
    fname = (record.common_name or str(serial)).replace(" ", "_")
    return web.Response(
        body=p12,
        content_type="application/x-pkcs12",
        headers={"Content-Disposition": f'attachment; filename="{fname}.p12"'},
    )


# ===========================================================================
# Mutations
# ===========================================================================


@routes.patch(Routes.REVOKE)
async def revoke_certificate(request: web.Request) -> web.Response:
    _verify_token(request)
    payload = await _parse(request, RevokeRequest)
    reason = REASON_MAP.get(payload.reason, x509.ReasonFlags.unspecified)
    ok = await _require_factory().revoke_certificate(
        serial=payload.serial_number, reason=reason
    )
    if not ok:
        return _err(f"No valid certificate with serial={payload.serial_number}", 404)
    return _resp({"revoked": True, "serial_number": payload.serial_number})


@routes.post(Routes.ROTATE)
async def rotate_certificate(request: web.Request) -> web.Response:
    _verify_token(request)
    serial = int(request.match_info["serial"])
    payload = await _parse(request, IssueCertRequest)
    _uuid = str(_uuid_module.uuid4())
    try:
        new_cert, _, _ = await _require_factory().rotate_certificate(
            serial=serial, config=build_client_config(payload)
        )
    except Exception as exc:
        return _err(str(exc), 404)
    return _resp(
        {
            "uuid": _uuid,
            "serial_number": new_cert.serial_number,
            "common_name": payload.common_name,
            "not_valid_before": new_cert.not_valid_before_utc.isoformat(),
            "not_valid_after": new_cert.not_valid_after_utc.isoformat(),
        }
    )


@routes.post(Routes.RENEW)
async def renew_certificate(request: web.Request) -> web.Response:
    _verify_token(request)
    serial = int(request.match_info["serial"])
    payload = await _parse(request, RenewRequest)
    try:
        renewed = await _require_factory().renew_certificate(
            serial=serial, days_valid=payload.days_valid
        )
    except Exception as exc:
        return _err(str(exc), 404)
    return _resp(
        {
            "old_serial": serial,
            "new_serial": renewed.serial_number,
            "not_valid_after": renewed.not_valid_after_utc.isoformat(),
        }
    )


@routes.delete(Routes.DELETE)
async def delete_certificate(request: web.Request) -> web.Response:
    _verify_token(request)
    serial = int(request.match_info["serial"])
    if not await _require_factory().delete_certificate(serial=serial):
        return _err(f"Certificate serial={serial} not found", 404)
    return _resp({"deleted": True, "serial": serial})


# ===========================================================================
# Inspection
# ===========================================================================


@routes.get(Routes.STATUS)
async def get_status(request: web.Request) -> web.Response:
    _verify_token(request)
    serial = int(request.match_info["serial"])
    status = await _require_factory().get_certificate_status(serial=serial)
    return _resp({"serial": serial, "status": str(status)})


@routes.get(Routes.INSPECT)
async def inspect_certificate(request: web.Request) -> web.Response:
    _verify_token(request)
    serial = int(request.match_info["serial"])
    mgr = _require_factory()
    record = await mgr._db.get_by_serial(serial=serial)
    if not record:
        return _err(f"Certificate serial={serial} not found", 404)
    cert = x509.load_pem_x509_certificate(record.certificate_pem.encode())
    return _resp((await mgr.inspect_certificate(cert=cert)).model_dump())


@routes.get(Routes.CHAIN)
async def get_cert_chain(request: web.Request) -> web.Response:
    _verify_token(request)
    serial = int(request.match_info["serial"])
    mgr = _require_factory()
    record = await mgr._db.get_by_serial(serial=serial)
    if not record:
        return _err(f"Certificate serial={serial} not found", 404)
    cert = x509.load_pem_x509_certificate(record.certificate_pem.encode())
    chain = await mgr.get_cert_chain(cert=cert)
    return _resp(
        {
            "serial": serial,
            "chain_length": len(chain),
            "chain": [c.public_bytes(Encoding.PEM).decode() for c in chain],
        }
    )


# ===========================================================================
# Downloads
# ===========================================================================


@routes.get(Routes.DOWNLOAD_STREAM)
async def stream_artifact(request: web.Request) -> web.StreamResponse:
    _verify_token(request)
    uuid_certificate = request.match_info["uuid_certificate"]
    path = await get_artifact_path(
        uuid_certificate,
        request.rel_url.query.get("object_type", "pem"),  # type: ignore
    )
    if not path:
        return _err("Artefact not found", 404)
    response = web.StreamResponse(
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'}
    )
    response.content_type = "application/x-pem-file"
    await response.prepare(request)
    async with aiofiles.open(path, "rb") as fh:
        while chunk := await fh.read(1024 * 1024):
            await response.write(chunk)
    await response.write_eof()
    return response


@routes.get(Routes.DOWNLOAD)
async def download_artifact(request: web.Request) -> web.Response:
    _verify_token(request)
    uuid_certificate = request.match_info["uuid_certificate"]
    path = await get_artifact_path(
        uuid_certificate,
        request.rel_url.query.get("object_type", "pem"),  # type: ignore [arg-type]
    )
    if not path:
        return _err("Artefact not found", 404)
    async with aiofiles.open(path, "rb") as fh:
        content = await fh.read()
    return web.Response(
        body=content,
        content_type="application/x-pem-file",
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )
