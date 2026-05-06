from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable, Coroutine, Generator
import functools
from pathlib import Path
from typing import Any, TypeVar
import uuid as _uuid_module

import aiofiles
from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding, load_pem_private_key
from flask import (
    Blueprint,
    Response,
    abort,
    jsonify,
    make_response,
    request,
    stream_with_context,
)
from tiny_ca.managers.async_lifecycle_manager import AsyncCertLifecycleManager
from tiny_ca.models.certificate import CAConfig

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
from tiny_ca_gateway.flask.lifespan.manager import FlaskCAManager
from tiny_ca_gateway.models import API_SETTINGS

ca_bp = Blueprint("ca", __name__)


# ---------------------------------------------------------------------------
# Flask-specific wrappers
# ---------------------------------------------------------------------------


def _require_factory() -> AsyncCertLifecycleManager:
    mgr = FlaskCAManager().manager
    if mgr.factory is None:
        abort(
            make_response(
                jsonify(detail="CA not initialised — POST /ca/root first."), 503
            )
        )
    return mgr


def _verify_token() -> None:
    expected = getattr(API_SETTINGS, "api_token", None)
    if not expected:
        return
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth[7:] != expected:
        abort(make_response(jsonify(detail="Invalid or missing bearer token."), 401))


def _load_pem_cert(pem: str) -> x509.Certificate:
    try:
        return load_pem_cert(pem)
    except ValueError as exc:
        abort(make_response(jsonify(detail=str(exc)), 422))


def _load_pem_crl(pem: str) -> x509.CertificateRevocationList:
    try:
        return load_pem_crl(pem)
    except ValueError as exc:
        abort(make_response(jsonify(detail=str(exc)), 422))


T = TypeVar("T")


def _run(coro: Coroutine[Any, Any, T]) -> T:
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _async(f: Callable[..., Coroutine[Any, Any, T]]) -> Callable[..., T]:
    @functools.wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        return _run(f(*args, **kwargs))

    return wrapper


def _json(data: dict[str, Any] | list[Any], status: int = 200) -> tuple[Response, int]:
    if hasattr(data, "model_dump"):
        return jsonify(data.model_dump(mode="json")), status
    if isinstance(data, list):
        return (
            jsonify(
                [
                    i.model_dump(mode="json") if hasattr(i, "model_dump") else i
                    for i in data
                ]
            ),
            status,
        )
    return jsonify(data), status


# ===========================================================================
# Public
# ===========================================================================


@ca_bp.get(Routes.GET_PUBLIC_CERT)
def get_public_cert() -> Response | tuple[Response, int]:
    cert_path = Path(API_SETTINGS.path_to_ca_cer)
    if not cert_path.exists():
        return jsonify(detail="CA not bootstrapped — POST /ca/root first."), 404
    return Response(
        cert_path.read_bytes(),
        mimetype="application/x-pem-file",
        headers={"Content-Disposition": 'attachment; filename="ca.pem"'},
    )


@ca_bp.get(Routes.BASE_CRL)
@_async
async def crl_route() -> Response | tuple[Response, int]:
    pem_fmt = request.args.get("pem", "false").lower() == "true"
    crl_path = Path(API_SETTINGS.path_to_crl)
    if not crl_path.exists():
        mgr = _require_factory()
        try:
            await mgr.generate_crl()
        except Exception as exc:
            return jsonify(detail=str(exc)), 500
    if not crl_path.exists():
        return jsonify(detail="CRL not found after generation."), 500
    async with aiofiles.open(crl_path, "rb") as fh:
        content = await fh.read()
    if pem_fmt:
        if not content.startswith(b"-----"):
            content = x509.load_der_x509_crl(content).public_bytes(Encoding.PEM)
        return Response(
            content,
            mimetype="application/x-pem-file",
            headers={"Content-Disposition": 'attachment; filename="ca.crl.pem"'},
        )
    return Response(
        content,
        mimetype="application/pkix-crl",
        headers={
            "Content-Disposition": 'attachment; filename="ca.crl"',
            "Cache-Control": "max-age=3600",
        },
    )


# ===========================================================================
# List / search
# ===========================================================================


@ca_bp.get(Routes.GET_LIST_CERTS, strict_slashes=False)
@ca_bp.get("/", strict_slashes=False)
@_async
async def list_certificates() -> Response | tuple[Response, int]:
    _verify_token()
    mgr = _require_factory()
    records = await mgr.list_certificates(
        status=request.args.get("status"),
        key_type=request.args.get("key_type"),
        limit=min(int(request.args.get("limit", 100)), 1000),
        offset=max(int(request.args.get("offset", 0)), 0),
    )
    return _json([record_to_item(r) for r in records])


@ca_bp.get(Routes.GET_LIST_EXPIRING_CERTS)
@_async
async def get_expiring() -> Response | tuple[Response, int]:
    _verify_token()
    mgr = _require_factory()
    within_days = max(1, min(int(request.args.get("within_days", 30)), 365))
    records = await mgr.get_expiring_soon(within_days=within_days)
    return _json(
        {
            "within_days": within_days,
            "count": len(records),
            "certificates": [
                record_to_item(r).model_dump(mode="json") for r in records
            ],
        }
    )


# ===========================================================================
# CA bootstrap / issuance
# ===========================================================================


@ca_bp.post(Routes.CA_ROOT)
@_async
async def create_root_ca() -> Response | tuple[Response, int]:
    _verify_token()
    lm = FlaskCAManager()
    try:
        payload = CAConfig.model_validate(request.get_json())
    except Exception as exc:
        return jsonify(detail=str(exc)), 422
    try:
        await lm.rebuild_root_ca_pair(ca_config=payload)
    except Exception as exc:
        return jsonify(detail=str(exc)), 409
    try:
        await lm.rebuild_manager()
    except Exception as exc:
        lm.logger.error("Factory reload failed: %s", exc)
    cert_obj = x509.load_pem_x509_certificate(
        Path(API_SETTINGS.path_to_ca_cer).read_bytes()
    )
    return _json(
        {
            "ca_id": "",
            "expires_at": cert_obj.not_valid_after_utc.strftime(
                API_SETTINGS.datetime_fmt
            ),
        }
    )


@ca_bp.post(Routes.CA_INTERMEDIATE)
@_async
async def issue_intermediate_ca() -> Response | tuple[Response, int]:
    _verify_token()
    mgr = _require_factory()
    try:
        payload = IntermediateCARequest.model_validate(request.get_json())
    except Exception as exc:
        return jsonify(detail=str(exc)), 422
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
        return jsonify(detail=str(exc)), 422
    return _json(
        {
            "uuid": _uuid,
            "serial_number": cert.serial_number,
            "common_name": payload.common_name,
            "not_valid_before": cert.not_valid_before_utc.isoformat(),
            "not_valid_after": cert.not_valid_after_utc.isoformat(),
        }
    )


@ca_bp.post(Routes.ISSUE)
@_async
async def issue_certificate() -> Response | tuple[Response, int]:
    _verify_token()
    mgr = _require_factory()
    try:
        payload = IssueCertRequest.model_validate(request.get_json())
    except Exception as exc:
        return jsonify(detail=str(exc)), 422
    _uuid = str(_uuid_module.uuid4())
    try:
        # ВАЖНО: Валидация key_size ПЕРЕД issue_certificate
        if payload.key_size and (payload.key_size < 2048 or payload.key_size > 4096):
            return (
                jsonify(
                    detail=f"Invalid key_size: {payload.key_size}. Must be 2048-4096."
                ),
                400,
            )

        cert, _, _ = await mgr.issue_certificate(
            config=build_client_config(payload),
            uuid_str=_uuid,
            is_overwrite=payload.is_overwrite,
        )
    except ValueError as exc:
        # Ловим ошибки валидации от tiny_ca
        if "key" in str(exc).lower():
            return jsonify(detail=str(exc)), 400
        return jsonify(detail=str(exc)), 409
    except Exception as exc:
        return jsonify(detail=str(exc)), 409
    return _json(
        {
            "uuid": _uuid,
            "serial_number": cert.serial_number,
            "common_name": payload.common_name,
            "not_valid_before": cert.not_valid_before_utc.isoformat(),
            "not_valid_after": cert.not_valid_after_utc.isoformat(),
        },
        201,
    )


@ca_bp.post(Routes.MAINTENANCE_EXPIRE)
@_async
async def mark_expired() -> Response | tuple[Response, int]:
    _verify_token()
    return _json({"updated": await _require_factory().refresh_expired_statuses()})


# ===========================================================================
# CRL
# ===========================================================================


@ca_bp.post(Routes.CRL_REFRESH)
@_async
async def refresh_crl() -> Response | tuple[Response, int]:
    _verify_token()
    try:
        crl = await _require_factory().generate_crl()
    except Exception as exc:
        return jsonify(detail=str(exc)), 500
    return _json({"next_update": crl.next_update_utc.isoformat()})


@ca_bp.post(Routes.CRL_VERIFY)
@_async
async def verify_crl() -> Response | tuple[Response, int]:
    _verify_token()
    try:
        payload = CRLVerifyRequest.model_validate(request.get_json())
    except Exception as exc:
        return jsonify(detail=str(exc)), 422
    crl = _load_pem_crl(payload.pem)
    try:
        await _require_factory().verify_crl(crl=crl)
        return _json({"valid": True, "next_update": crl.next_update_utc.isoformat()})
    except Exception as exc:
        return _json({"valid": False, "detail": str(exc)})


# ===========================================================================
# Verification / cosign / export
# ===========================================================================


@ca_bp.post(Routes.VERIFY)
@_async
async def verify_certificate() -> Response | tuple[Response, int]:
    _verify_token()
    try:
        payload = VerifyRequest.model_validate(request.get_json())
    except Exception as exc:
        return jsonify(detail=str(exc)), 422
    cert = _load_pem_cert(payload.pem)
    try:
        # ВАЖНО: verify_certificate может вернуть False вместо исключения
        result = await _require_factory().verify_certificate(cert=cert)
        # Если результат — это кортеж (valid, reason), обработать
        if isinstance(result, tuple):
            valid, reason = result
            if valid:
                return _json({"valid": True})
            else:
                return _json(
                    {"valid": False, "detail": reason or "Verification failed"}
                )
        # Если просто исключение не выброшено — сертификат валиден
        return _json({"valid": True})
    except Exception as exc:
        return _json({"valid": False, "detail": str(exc)})


@ca_bp.post(Routes.COSIGN)
@_async
async def cosign_certificate() -> Response | tuple[Response, int]:
    _verify_token()
    try:
        payload = CosignRequest.model_validate(request.get_json())
    except Exception as exc:
        return jsonify(detail=str(exc)), 422
    cert = _load_pem_cert(payload.pem)
    try:
        cosigned = await _require_factory().cosign_certificate(
            cert=cert,
            days_valid=payload.days_valid,
            valid_from=payload.valid_from,
        )
    except Exception as exc:
        return jsonify(detail=str(exc)), 422
    return _json(
        {
            "serial_number": cosigned.serial_number,
            "not_valid_before": cosigned.not_valid_before_utc.isoformat(),
            "not_valid_after": cosigned.not_valid_after_utc.isoformat(),
            "pem": cosigned.public_bytes(Encoding.PEM).decode(),
        }
    )


@ca_bp.post("/export-p12/<int:serial>")
@_async
async def export_pkcs12(serial: int) -> Response | tuple[Response, int]:
    _verify_token()
    mgr = _require_factory()
    try:
        payload = ExportP12Request.model_validate(request.get_json() or {})
    except Exception as exc:
        return jsonify(detail=str(exc)), 422
    record = await mgr._db.get_by_serial(serial=serial)
    if not record:
        return jsonify(detail=f"Certificate serial={serial} not found"), 404
    key_path = await get_artifact_path(record.uuid, "key")
    if not key_path:
        return jsonify(detail="Private key not found"), 404
    async with aiofiles.open(key_path, "rb") as fh:
        private_key = load_pem_private_key(await fh.read(), password=None)
    p12 = await mgr.export_pkcs12(
        cert=x509.load_pem_x509_certificate(record.certificate_pem.encode()),
        private_key=private_key,
        password=payload.password.encode() if payload.password else None,
    )
    fname = (record.common_name or str(serial)).replace(" ", "_")
    return Response(
        p12,
        mimetype="application/x-pkcs12",
        headers={"Content-Disposition": f'attachment; filename="{fname}.p12"'},
    )


# ===========================================================================
# Mutations
# ===========================================================================


@ca_bp.patch(Routes.REVOKE)
@_async
async def revoke_certificate() -> Response | tuple[Response, int]:
    _verify_token()
    try:
        payload = RevokeRequest.model_validate(request.get_json())
    except Exception as exc:
        return jsonify(detail=str(exc)), 422
    reason = REASON_MAP.get(payload.reason, x509.ReasonFlags.unspecified)
    ok = await _require_factory().revoke_certificate(
        serial=payload.serial_number, reason=reason
    )
    if not ok:
        return (
            jsonify(detail=f"No valid certificate with serial={payload.serial_number}"),
            404,
        )
    return _json({"revoked": True, "serial_number": payload.serial_number})


@ca_bp.post("/rotate/<int:serial>")
@_async
async def rotate_certificate(serial: int) -> Response | tuple[Response, int]:
    _verify_token()
    try:
        payload = IssueCertRequest.model_validate(request.get_json())
    except Exception as exc:
        return jsonify(detail=str(exc)), 422
    _uuid = str(_uuid_module.uuid4())
    try:
        new_cert, _, _ = await _require_factory().rotate_certificate(
            serial=serial, config=build_client_config(payload)
        )
    except Exception as exc:
        return jsonify(detail=str(exc)), 404
    return _json(
        {
            "uuid": _uuid,
            "serial_number": new_cert.serial_number,
            "common_name": payload.common_name,
            "not_valid_before": new_cert.not_valid_before_utc.isoformat(),
            "not_valid_after": new_cert.not_valid_after_utc.isoformat(),
        }
    )


@ca_bp.post("/renew/<int:serial>")
@_async
async def renew_certificate(serial: int) -> Response | tuple[Response, int]:
    _verify_token()
    try:
        payload = RenewRequest.model_validate(request.get_json())
    except Exception as exc:
        return jsonify(detail=str(exc)), 422
    try:
        renewed = await _require_factory().renew_certificate(
            serial=serial, days_valid=payload.days_valid
        )
    except Exception as exc:
        return jsonify(detail=str(exc)), 404
    return _json(
        {
            "old_serial": serial,
            "new_serial": renewed.serial_number,
            "not_valid_after": renewed.not_valid_after_utc.isoformat(),
        }
    )


@ca_bp.delete("/<int:serial>")
@_async
async def delete_certificate(serial: int) -> Response | tuple[Response, int]:
    _verify_token()
    if not await _require_factory().delete_certificate(serial=serial):
        return jsonify(detail=f"Certificate serial={serial} not found"), 404
    return _json({"deleted": True, "serial": serial})


# ===========================================================================
# Inspection
# ===========================================================================


@ca_bp.get("/status/<int:serial>")
@_async
async def get_status(serial: int) -> Response | tuple[Response, int]:
    _verify_token()
    status = await _require_factory().get_certificate_status(serial=serial)
    return _json({"serial": serial, "status": str(status)})


@ca_bp.get("/inspect/<int:serial>")
@_async
async def inspect_certificate(serial: int) -> Response | tuple[Response, int]:
    _verify_token()
    mgr = _require_factory()
    record = await mgr._db.get_by_serial(serial=serial)
    if not record:
        return jsonify(detail=f"Certificate serial={serial} not found"), 404
    cert = x509.load_pem_x509_certificate(record.certificate_pem.encode())
    return _json((await mgr.inspect_certificate(cert=cert)).model_dump())


@ca_bp.get("/chain/<int:serial>")
@_async
async def get_cert_chain(serial: int) -> Response | tuple[Response, int]:
    _verify_token()
    mgr = _require_factory()
    record = await mgr._db.get_by_serial(serial=serial)
    if not record:
        return jsonify(detail=f"Certificate serial={serial} not found"), 404
    cert = x509.load_pem_x509_certificate(record.certificate_pem.encode())
    chain = await mgr.get_cert_chain(cert=cert)
    return _json(  # type: ignore[no-untyped-call]
        {
            "serial": serial,
            "chain_length": len(chain),
            "chain": [c.public_bytes(Encoding.PEM).decode() for c in chain],
        }
    )


# ===========================================================================
# Downloads
# ===========================================================================


@ca_bp.get("/stream/<string:uuid_certificate>")
@_async
async def stream_artifact(uuid_certificate: str) -> Response | tuple[Response, int]:
    _verify_token()
    object_type = request.args.get("object_type", "pem")
    path = await get_artifact_path(uuid_certificate, object_type)  # type: ignore[arg-type]
    if not path:
        return jsonify(detail="Artefact not found"), 404

    def _sync_iter() -> Generator[bytes, None, None]:
        import asyncio as _asyncio

        loop = _asyncio.new_event_loop()
        gen = _iter(path)
        try:
            while True:
                try:
                    yield loop.run_until_complete(gen.__anext__())
                except StopAsyncIteration:
                    break
        finally:
            loop.close()

    async def _iter(p: Path, chunk: int = 1024 * 1024) -> AsyncGenerator[bytes, None]:
        async with aiofiles.open(p, "rb") as fh:
            while data := await fh.read(chunk):
                yield data

    return Response(
        stream_with_context(_sync_iter()),
        mimetype="application/x-pem-file",
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )


@ca_bp.get("/<string:uuid_certificate>")
@_async
async def download_artifact(uuid_certificate: str) -> Response | tuple[Response, int]:
    _verify_token()
    object_type = request.args.get("object_type", "pem")
    path = await get_artifact_path(uuid_certificate, object_type)  # type: ignore[arg-type]
    if not path:
        return jsonify(detail="Artefact not found"), 404
    async with aiofiles.open(path, "rb") as fh:
        content = await fh.read()
    return Response(
        content,
        mimetype="application/x-pem-file",
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )
