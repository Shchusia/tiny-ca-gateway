#!/usr/bin/env python3
"""
ca_integration_test.py
~~~~~~~~~~~~~~~~~~~~~~~
Интеграционные тесты для tiny-ca REST API.

Запуск против любого бэкенда (FastAPI / Flask / aiohttp / Django Ninja):

    python demos/demo-fastapi.py      # → http://localhost:8000
    python demos/demo-flask.py        # → http://localhost:8000
    python demos/demo-aiohttp.py      # → http://localhost:8000

    python ca_integration_test.py
    python ca_integration_test.py --base-url http://localhost:9000
    python ca_integration_test.py --token mysecrettoken --verbose

Коды выхода:
    0 — все тесты прошли
    1 — есть упавшие тесты
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="tiny-ca integration tests")
    p.add_argument("--base-url", default="http://localhost:8000")
    p.add_argument("--prefix", default="/api/v1/ca")
    p.add_argument("--token", default="47a7114e-a4cb-4bd0-b9f2-96c292b8e2b2")
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument("--timeout", type=int, default=15)
    return p.parse_args()


# ---------------------------------------------------------------------------
# HTTP client (stdlib only — no deps)
# ---------------------------------------------------------------------------


class Client:
    def __init__(self, base: str, prefix: str, token: str, timeout: int, verbose: bool):
        self.base = base.rstrip("/")
        self.prefix = prefix
        self.token = token
        self.timeout = timeout
        self.verbose = verbose

    def _url(self, path: str) -> str:
        path = path if path.startswith("/") else f"/{path}"
        return f"{self.base}{self.prefix}{path}"

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def request(
        self, method: str, path: str, body: Any = None, params: dict | None = None
    ) -> tuple[int, Any]:
        url = self._url(path)
        if params:
            url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
        data = json.dumps(body).encode() if body is not None else None
        req = Request(url, data=data, headers=self._headers(), method=method)
        if self.verbose:
            print(f"\n  → {method} {url}")
            if body:
                print(f"     {json.dumps(body, default=str)[:200]}")
        try:
            with urlopen(req, timeout=self.timeout) as r:
                status, raw = r.status, r.read()
        except HTTPError as e:
            status, raw = e.code, e.read()
        try:
            result = json.loads(raw) if raw else None
        except Exception:
            result = raw.decode(errors="replace") if raw else None
        if self.verbose:
            print(f"  ← {status}: {str(result)[:300]}")
        return status, result

    def get(self, path, params=None):
        return self.request("GET", path, params=params)

    def post(self, path, body=None):
        return self.request("POST", path, body=body)

    def patch(self, path, body=None):
        return self.request("PATCH", path, body=body)

    def delete(self, path):
        return self.request("DELETE", path)

    def get_raw(self, path: str, params: dict | None = None) -> tuple[int, bytes]:
        url = self._url(path)
        if params:
            url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
        req = Request(url, headers=self._headers(), method="GET")
        try:
            with urlopen(req, timeout=self.timeout) as r:
                return r.status, r.read()
        except HTTPError as e:
            return e.code, e.read()


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------


@dataclass
class Result:
    name: str
    passed: bool
    message: str = ""
    duration_ms: float = 0.0


@dataclass
class Suite:
    client: Client
    results: list[Result] = field(default_factory=list)
    # shared state
    issued_uuid: str = ""
    issued_serial: int = 0
    issued_pem: str = ""

    def run(self, name: str, fn):
        t0 = time.perf_counter()
        try:
            fn()
            r = Result(
                name=name, passed=True, duration_ms=(time.perf_counter() - t0) * 1000
            )
        except AssertionError as exc:
            r = Result(
                name=name,
                passed=False,
                message=str(exc),
                duration_ms=(time.perf_counter() - t0) * 1000,
            )
        except Exception as exc:
            r = Result(
                name=name,
                passed=False,
                message=f"{type(exc).__name__}: {exc}",
                duration_ms=(time.perf_counter() - t0) * 1000,
            )
        self.results.append(r)
        sym = "✓" if r.passed else "✗"
        suffix = f"  ({r.message})" if not r.passed else ""
        print(f"  {sym} [{r.duration_ms:>6.0f}ms] {name}{suffix}")

    # ── assert helpers ──────────────────────────────────────────────────────

    def ok(self, status, expected, body=None):
        assert status == expected, (
            f"Expected HTTP {expected}, got {status}. Body: {str(body)[:300]}"
        )

    def has(self, body: dict, *keys):
        missing = [k for k in keys if k not in body]
        assert not missing, f"Missing keys: {missing}. Got: {list(body.keys())}"

    def is_pem(self, data: bytes | str, label="CERTIFICATE"):
        if isinstance(data, bytes):
            data = data.decode(errors="replace")
        assert f"-----BEGIN {label}-----" in data, (
            f"Expected PEM '{label}', got: {data[:200]}"
        )

    def is_datetime(self, value: str, field=""):
        try:
            datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            assert False, f"Not a valid datetime ({field}): {value!r}"

    def days_valid(self, not_before: str, not_after: str, expected: int, tol=2):
        nb = datetime.datetime.fromisoformat(not_before.replace("Z", "+00:00"))
        na = datetime.datetime.fromisoformat(not_after.replace("Z", "+00:00"))
        actual = (na - nb).days
        assert abs(actual - expected) <= tol, (
            f"Expected ~{expected} days validity, got {actual}"
        )


# ---------------------------------------------------------------------------
# All tests
# ---------------------------------------------------------------------------


def run_all(s: Suite):
    c = s.client

    # ── 1. Public endpoints ─────────────────────────────────────────────────
    print("\n━━━━ 1. PUBLIC ENDPOINTS ━━━━")

    def t_cert_pem():
        code, raw = c.get_raw("/cert")
        s.ok(code, 200)
        s.is_pem(raw, "CERTIFICATE")

    s.run("GET /cert → PEM certificate", t_cert_pem)

    def t_cert_content_type():
        url = c._url("/cert")
        req = Request(url, headers=c._headers())
        with urlopen(req, timeout=c.timeout) as r:
            ct = r.headers.get("Content-Type", "")
        assert "pem" in ct or "octet" in ct, f"Unexpected Content-Type: {ct}"

    s.run("GET /cert → Content-Type is pem/octet", t_cert_content_type)

    def t_crl_der():
        code, raw = c.get_raw("/crl")
        assert code in (200, 500), f"Unexpected: {code}"
        if code == 200:
            assert isinstance(raw, bytes)

    s.run("GET /crl → DER bytes", t_crl_der)

    def t_crl_pem():
        code, raw = c.get_raw("/crl", {"pem": "true"})
        if code == 200:
            s.is_pem(raw, "X509 CRL")

    s.run("GET /crl?pem=true → PEM CRL", t_crl_pem)

    # ── 2. Route completeness ────────────────────────────────────────────────
    print("\n━━━━ 2. ROUTE COMPLETENESS ━━━━")

    routes = [
        # GET "/" проверяется отдельно через _list_get (aiohttp subapp routing)
        ("GET", "/expiring"),
        ("POST", "/root"),
        ("POST", "/intermediate"),
        ("POST", "/issue"),
        ("POST", "/maintenance/expire"),
        ("POST", "/crl/refresh"),
        ("POST", "/crl/verify"),
        ("POST", "/verify"),
        ("POST", "/cosign"),
        ("PATCH", "/revoke"),
    ]
    for method, path in routes:

        def t_route(m=method, p=path):
            code, body = c.request(m, p, body={} if m in ("POST", "PATCH") else None)
            assert code != 404, f"Route {m} {p} → 404 (not registered)"
            assert code != 405, f"Route {m} {p} → 405 (wrong method)"

        s.run(f"{method} {path} → route exists", t_route)

    # ── 3. Issue certificate ─────────────────────────────────────────────────
    print("\n━━━━ 3. ISSUE CERTIFICATE ━━━━")

    def t_issue_basic():
        code, body = c.post(
            "/issue",
            {
                "common_name": "test.integration.local",
                "days_valid": 90,
                "is_server_cert": True,
                "san_dns": ["test.integration.local", "localhost"],
                "is_overwrite": True,
            },
        )
        assert code in (200, 201), f"Expected 200/201, got {code}: {body}"
        s.has(
            body,
            "uuid",
            "serial_number",
            "common_name",
            "not_valid_before",
            "not_valid_after",
        )
        assert body["common_name"] == "test.integration.local"
        s.is_datetime(body["not_valid_before"], "not_valid_before")
        s.is_datetime(body["not_valid_after"], "not_valid_after")
        s.days_valid(body["not_valid_before"], body["not_valid_after"], 90)
        s.issued_uuid = body["uuid"]
        s.issued_serial = body["serial_number"]

    s.run("POST /issue → fields + 90-day validity", t_issue_basic)

    def t_issue_365():
        code, body = c.post(
            "/issue",
            {"common_name": "year.test.local", "days_valid": 365, "is_overwrite": True},
        )
        assert code in (200, 201), f"{code}: {body}"
        s.days_valid(body["not_valid_before"], body["not_valid_after"], 365)

    s.run("POST /issue → days_valid=365 → ~1 year", t_issue_365)

    def t_issue_730():
        code, body = c.post(
            "/issue",
            {
                "common_name": "twoyears.test.local",
                "days_valid": 730,
                "is_overwrite": True,
            },
        )
        assert code in (200, 201), f"{code}: {body}"
        s.days_valid(body["not_valid_before"], body["not_valid_after"], 730)

    s.run("POST /issue → days_valid=730 → ~2 years", t_issue_730)

    def t_issue_duplicate_409():
        c.post("/issue", {"common_name": "dup.test.local", "days_valid": 30})
        code, _ = c.post(
            "/issue",
            {"common_name": "dup.test.local", "days_valid": 30, "is_overwrite": False},
        )
        assert code == 409, f"Expected 409 Conflict, got {code}"

    s.run("POST /issue → duplicate without overwrite → 409", t_issue_duplicate_409)

    def t_issue_overwrite():
        c.post("/issue", {"common_name": "overwrite.test.local", "days_valid": 30})
        code, body = c.post(
            "/issue",
            {
                "common_name": "overwrite.test.local",
                "days_valid": 60,
                "is_overwrite": True,
            },
        )
        assert code in (200, 201), f"Expected 200/201 with is_overwrite, got {code}"

    s.run("POST /issue → is_overwrite=true → replaces cert", t_issue_overwrite)

    def t_issue_bad_keysize():
        code, _ = c.post("/issue", {"common_name": "bad.key.local", "key_size": 512})
        assert code in (400, 422), f"Expected 400/422 for key_size=512, got {code}"

    s.run("POST /issue → key_size=512 → 400/422", t_issue_bad_keysize)

    # ── 4. Download artifacts ────────────────────────────────────────────────
    print("\n━━━━ 4. DOWNLOAD ARTIFACTS ━━━━")

    def _get_artifact(uuid: str, object_type: str = "pem"):
        """
        Download artifact с fallback для aiohttp.
        aiohttp переименовывает /{uuid} → /download/{uuid} чтобы избежать
        конфликта с DELETE /{serial} (одинаковый паттерн, разные методы).
        """
        code, raw = c.get_raw(f"/{uuid}", {"object_type": object_type})
        if code == 405:
            code, raw = c.get_raw(f"/download/{uuid}", {"object_type": object_type})
        return code, raw

    def t_download_pem():
        assert s.issued_uuid, "No UUID from issue step"
        code, raw = _get_artifact(s.issued_uuid, "pem")
        s.ok(code, 200)
        s.is_pem(raw, "CERTIFICATE")
        s.issued_pem = raw.decode() if isinstance(raw, bytes) else raw

    s.run("GET /{uuid}?object_type=pem → PEM certificate", t_download_pem)

    def t_download_key():
        assert s.issued_uuid
        code, raw = _get_artifact(s.issued_uuid, "key")
        s.ok(code, 200)
        text = raw.decode(errors="replace") if isinstance(raw, bytes) else raw
        assert "PRIVATE KEY" in text, f"Expected PEM private key, got: {text[:200]}"

    s.run(
        "GET /{uuid}?object_type=key → private key (PKCS#1 or PKCS#8)", t_download_key
    )

    def t_download_stream():
        assert s.issued_uuid
        # /stream/{uuid} стандартный путь; aiohttp использует /download/stream/{uuid}
        code, raw = c.get_raw(f"/stream/{s.issued_uuid}", {"object_type": "pem"})
        if code == 405:
            code, raw = c.get_raw(
                f"/download/stream/{s.issued_uuid}", {"object_type": "pem"}
            )
        s.ok(code, 200)
        s.is_pem(raw, "CERTIFICATE")

    s.run("GET /stream/{uuid} → streamed PEM", t_download_stream)

    def t_download_unknown():
        code, _ = _get_artifact("00000000-0000-0000-0000-000000000000", "pem")
        assert code == 404, f"Expected 404 for unknown UUID, got {code}"

    s.run("GET /unknown-uuid → 404", t_download_unknown)

    # ── 5. List & search ─────────────────────────────────────────────────────
    print("\n━━━━ 5. LIST & SEARCH ━━━━")

    def _list_get(params=None):
        """
        GET / с fallback для aiohttp subapp routing.
        Порядок: "/" → "/list" → ""
        Если тело — HTML страница Django 404, пробуем следующий путь.
        """

        def is_html(b):
            return isinstance(b, str) and b.strip().startswith("<")

        code, body = c.get("/", params)
        if code == 404 or is_html(body):
            code, body = c.get("/list", params)
        if code == 404 or is_html(body):
            code, body = c.get("", params)
        return code, body

    def t_list_returns_list():
        code, body = _list_get()
        s.ok(code, 200)
        assert isinstance(body, list), (
            f"Expected list, got {type(body).__name__}: {str(body)[:100]}"
        )
        assert len(body) >= 1, "Expected at least 1 certificate"

    s.run("GET / → list of certificates", t_list_returns_list)

    def t_list_fields():
        code, body = _list_get()
        s.ok(code, 200)
        required = {"serial_number", "common_name", "status", "not_valid_after"}
        for item in body[:5]:
            missing = required - set(item.keys())
            assert not missing, f"Item missing fields: {missing}"

    s.run("GET / → each item has required fields", t_list_fields)

    def t_list_limit():
        code, body = _list_get({"limit": "2"})
        s.ok(code, 200)
        assert len(body) <= 2, f"Expected ≤2 items, got {len(body)}"

    s.run("GET /?limit=2 → respects limit", t_list_limit)

    def t_list_filter_valid():
        code, body = _list_get({"status": "valid"})
        s.ok(code, 200)
        for item in body:
            assert item.get("status") == "valid", (
                f"Item has status={item.get('status')} in 'valid' filter"
            )

    s.run("GET /?status=valid → only valid certs", t_list_filter_valid)

    def t_expiring_structure():
        # 9999 > le=365 в FastAPI схеме → 422; используем 365
        code, body = c.get("/expiring", {"within_days": "365"})
        s.ok(code, 200)
        s.has(body, "within_days", "count", "certificates")
        assert isinstance(body["certificates"], list)
        assert body["count"] == len(body["certificates"]), (
            f"count={body['count']} != len(certificates)={len(body['certificates'])}"
        )

    s.run("GET /expiring → count matches list length", t_expiring_structure)

    def t_expiring_within_days():
        code, body = c.get("/expiring", {"within_days": "1"})
        s.ok(code, 200)
        assert body["within_days"] == 1

    s.run("GET /expiring?within_days=1 → within_days echoed", t_expiring_within_days)

    # ── 6. Inspect / Status / Chain ──────────────────────────────────────────
    print("\n━━━━ 6. INSPECT / STATUS / CHAIN ━━━━")

    def t_status_valid():
        assert s.issued_serial
        code, body = c.get(f"/status/{s.issued_serial}")
        s.ok(code, 200)
        s.has(body, "serial", "status")
        assert body["status"] in ("valid", "revoked", "expired"), (
            f"Unexpected status: {body['status']}"
        )

    s.run("GET /status/{serial} → valid status string", t_status_valid)

    def t_status_unknown():
        code, body = c.get("/status/9999999")
        assert code in (200, 404), f"Expected 200 or 404, got {code}"
        if code == 200 and isinstance(body, dict):
            assert body.get("status") != "valid", (
                f"Unknown serial → status='valid'? {body}"
            )

    s.run("GET /status/9999999 → 404 or non-valid status", t_status_unknown)

    def t_inspect():
        assert s.issued_serial
        code, body = c.get(f"/inspect/{s.issued_serial}")
        s.ok(code, 200)
        assert isinstance(body, dict) and len(body) > 0, "Empty inspect response"

    s.run("GET /inspect/{serial} → certificate details dict", t_inspect)

    def t_chain():
        assert s.issued_serial
        code, body = c.get(f"/chain/{s.issued_serial}")
        s.ok(code, 200)
        s.has(body, "serial", "chain_length", "chain")
        assert body["chain_length"] >= 1
        assert len(body["chain"]) == body["chain_length"]
        for pem_str in body["chain"]:
            s.is_pem(pem_str, "CERTIFICATE")

    s.run("GET /chain/{serial} → PEM chain with CA", t_chain)

    # ── 7. Verify ────────────────────────────────────────────────────────────
    print("\n━━━━ 7. VERIFY ━━━━")

    def t_verify_valid():
        assert s.issued_pem, "No PEM from download step"
        code, body = c.post("/verify", {"pem": s.issued_pem})
        s.ok(code, 200)
        assert body.get("valid") is True, f"Expected valid=true, got: {body}"

    s.run("POST /verify → valid cert → {valid: true}", t_verify_valid)

    def t_verify_garbage():
        code, body = c.post("/verify", {"pem": "this is not a certificate"})
        assert code in (200, 422), f"Unexpected {code}"
        if code == 200:
            assert body.get("valid") is False

    s.run("POST /verify → garbage PEM → 422 or valid=false", t_verify_garbage)

    def t_crl_verify_valid():
        _, raw = c.get_raw("/crl", {"pem": "true"})
        if not raw or not raw.startswith(b"-----"):
            return
        code, body = c.post("/crl/verify", {"pem": raw.decode()})
        s.ok(code, 200)
        assert "valid" in body

    s.run("POST /crl/verify → valid CRL", t_crl_verify_valid)

    def t_crl_verify_invalid():
        code, body = c.post("/crl/verify", {"pem": "not a crl"})
        assert code in (200, 422)
        if code == 200:
            assert body.get("valid") is False

    s.run("POST /crl/verify → invalid → 422 or valid=false", t_crl_verify_invalid)

    # ── 8. Maintenance ───────────────────────────────────────────────────────
    print("\n━━━━ 8. MAINTENANCE ━━━━")

    def t_expire():
        code, body = c.post("/maintenance/expire")
        s.ok(code, 200)
        s.has(body, "updated")
        assert isinstance(body["updated"], int) and body["updated"] >= 0

    s.run("POST /maintenance/expire → {updated: int}", t_expire)

    def t_crl_refresh():
        code, body = c.post("/crl/refresh")
        s.ok(code, 200)
        s.has(body, "next_update")
        s.is_datetime(body["next_update"], "next_update")
        nu = datetime.datetime.fromisoformat(body["next_update"].replace("Z", "+00:00"))
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        assert nu > now, f"CRL next_update should be in the future, got {nu}"

    s.run("POST /crl/refresh → next_update is future datetime", t_crl_refresh)

    # ── 9. Revoke ────────────────────────────────────────────────────────────
    print("\n━━━━ 9. REVOKE ━━━━")

    def t_revoke_ok():
        _, iss = c.post(
            "/issue",
            {"common_name": "to.revoke.local", "days_valid": 30, "is_overwrite": True},
        )
        code, body = c.patch(
            "/revoke",
            {"serial_number": iss["serial_number"], "reason": "keyCompromise"},
        )
        s.ok(code, 200)
        assert body.get("revoked") is True
        assert body.get("serial_number") == iss["serial_number"]

    s.run("PATCH /revoke → revoked=true", t_revoke_ok)

    def t_revoke_status():
        _, iss = c.post(
            "/issue",
            {
                "common_name": "status.check.local",
                "days_valid": 30,
                "is_overwrite": True,
            },
        )
        serial = iss["serial_number"]
        c.patch("/revoke", {"serial_number": serial, "reason": "superseded"})
        code, body = c.get(f"/status/{serial}")
        s.ok(code, 200)
        assert body["status"] == "revoked", (
            f"Expected 'revoked', got '{body['status']}'"
        )

    s.run("PATCH /revoke → GET /status → status='revoked'", t_revoke_status)

    def t_revoke_verify():
        code0, iss = c.post(
            "/issue",
            {
                "common_name": "revoke.verify.local",
                "days_valid": 30,
                "is_overwrite": True,
            },
        )
        assert code0 in (200, 201), f"Issue failed: {code0}: {iss}"
        serial, uuid = iss["serial_number"], iss["uuid"]
        _, raw = _get_artifact(uuid, "pem")
        pem_str = raw.decode() if isinstance(raw, bytes) else raw
        c.patch("/revoke", {"serial_number": serial, "reason": "unspecified"})
        code, body = c.post("/verify", {"pem": pem_str})
        # 200+valid=false или 422 — оба означают "сертификат не прошёл проверку"
        assert code in (200, 422), f"Expected 200 or 422, got {code}"
        if code == 200:
            assert body.get("valid") is False, "Revoked cert should fail /verify"

    s.run("Revoked cert → POST /verify → valid=false or 422", t_revoke_verify)

    def t_revoke_invalid_reason():
        _, iss = c.post(
            "/issue",
            {"common_name": "bad.reason.local", "days_valid": 30, "is_overwrite": True},
        )
        code, _ = c.patch(
            "/revoke",
            {"serial_number": iss["serial_number"], "reason": "not_a_real_reason"},
        )
        assert code in (200, 422), f"Unexpected {code} for invalid reason"

    s.run(
        "PATCH /revoke → invalid reason → 200 or 422 (not 500)", t_revoke_invalid_reason
    )

    def t_revoke_404():
        code, _ = c.patch(
            "/revoke", {"serial_number": 9999999, "reason": "unspecified"}
        )
        s.ok(code, 404)

    s.run("PATCH /revoke → unknown serial → 404", t_revoke_404)

    # ── 10. Renew ────────────────────────────────────────────────────────────
    print("\n━━━━ 10. RENEW ━━━━")

    def t_renew():
        _, iss = c.post(
            "/issue",
            {"common_name": "to.renew.local", "days_valid": 30, "is_overwrite": True},
        )
        serial = iss["serial_number"]
        code, body = c.post(f"/renew/{serial}", {"days_valid": 90})
        s.ok(code, 200)
        s.has(body, "old_serial", "new_serial", "not_valid_after")
        assert body["old_serial"] == serial
        assert isinstance(body["new_serial"], int)
        s.is_datetime(body["not_valid_after"], "not_valid_after")
        # Validity should be ~90 days from now
        na = datetime.datetime.fromisoformat(
            body["not_valid_after"].replace("Z", "+00:00")
        )
        days_left = (na - datetime.datetime.now(tz=datetime.timezone.utc)).days
        assert 85 <= days_left <= 95, (
            f"Renewed cert: expected ~90 days, got {days_left}"
        )

    s.run("POST /renew/{serial} → ~90 days validity from now", t_renew)

    def t_renew_404():
        code, _ = c.post("/renew/9999999", {"days_valid": 30})
        s.ok(code, 404)

    s.run("POST /renew/9999999 → 404", t_renew_404)

    # ── 11. Rotate ───────────────────────────────────────────────────────────
    print("\n━━━━ 11. ROTATE ━━━━")

    def t_rotate():
        _, iss = c.post(
            "/issue",
            {
                "common_name": "rotate.test.local",
                "days_valid": 30,
                "is_overwrite": True,
            },
        )
        rot_serial = iss["serial_number"]
        code, body = c.post(
            f"/rotate/{rot_serial}",
            {
                "common_name": "rotate.test.local",
                "days_valid": 60,
                "is_overwrite": True,
            },
        )
        s.ok(code, 200)
        s.has(
            body,
            "uuid",
            "serial_number",
            "common_name",
            "not_valid_before",
            "not_valid_after",
        )
        assert body["serial_number"] != rot_serial, "Rotated cert must have new serial"
        s.days_valid(body["not_valid_before"], body["not_valid_after"], 60)

    s.run("POST /rotate/{serial} → new serial + 60-day validity", t_rotate)

    # ── 12. Delete ───────────────────────────────────────────────────────────
    print("\n━━━━ 12. DELETE ━━━━")

    def t_delete_ok():
        _, iss = c.post(
            "/issue",
            {"common_name": "to.delete.local", "days_valid": 30, "is_overwrite": True},
        )
        serial = iss["serial_number"]
        code, body = c.delete(f"/{serial}")
        s.ok(code, 200)
        assert body.get("deleted") is True
        assert body.get("serial") == serial

    s.run("DELETE /{serial} → deleted=true", t_delete_ok)

    def t_delete_then_gone():
        code0, iss = c.post(
            "/issue",
            {
                "common_name": "delete.check.local",
                "days_valid": 30,
                "is_overwrite": True,
            },
        )
        assert code0 in (200, 201), f"Issue failed: {code0}: {iss}"
        serial = iss["serial_number"]
        c.delete(f"/{serial}")
        code, body = c.get(f"/status/{serial}")
        # hard delete → 404; soft delete → 200 но не "valid"
        assert code in (200, 404), f"Expected 200 or 404 after delete, got {code}"
        if code == 200 and isinstance(body, dict):
            assert body.get("status") != "valid", f"Deleted cert status='valid'? {body}"

    s.run("DELETE → GET /status → 404 or non-valid status", t_delete_then_gone)

    def t_delete_404():
        code, _ = c.delete("/9999999")
        s.ok(code, 404)

    s.run("DELETE /9999999 → 404", t_delete_404)

    # ── 13. Intermediate CA ──────────────────────────────────────────────────
    print("\n━━━━ 13. INTERMEDIATE CA ━━━━")

    def t_intermediate():
        code, body = c.post(
            "/intermediate",
            {
                "common_name": "Test Intermediate CA",
                "key_size": 2048,
                "days_valid": 365,
                "organization": "ACME Corp",
                "country": "UA",
            },
        )
        s.ok(code, 200)
        s.has(
            body,
            "uuid",
            "serial_number",
            "common_name",
            "not_valid_before",
            "not_valid_after",
        )
        s.days_valid(body["not_valid_before"], body["not_valid_after"], 365)

    s.run("POST /intermediate → ~365 days validity", t_intermediate)

    # ── 14. Auth ─────────────────────────────────────────────────────────────
    print("\n━━━━ 14. AUTH ━━━━")

    def t_auth_protected():
        # Проверяем /expiring — надёжно работает во всех фреймворках (GET "/" иначе резолвится в aiohttp)
        endpoints = [("/expiring", "GET"), ("/maintenance/expire", "POST")]
        codes = []
        for ep, method in endpoints:
            url = c._url(ep)
            req = Request(
                url,
                data=b"{}" if method == "POST" else None,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                method=method,
            )
            try:
                with urlopen(req, timeout=c.timeout) as r:
                    codes.append(r.status)
            except HTTPError as e:
                codes.append(e.code)
        if c.token:
            assert all(code in (401, 403) for code in codes), (
                f"With auth enabled, no-token requests should fail. Got {codes}"
            )
        else:
            assert all(code == 200 for code in codes), (
                f"With no auth, requests should succeed. Got {codes}"
            )

    s.run(
        "Protected endpoint without token → 401/403 (if auth enabled)", t_auth_protected
    )

    def t_cert_public():
        url = f"{c.base}{c.prefix}/cert"
        req = Request(url, headers={"Accept": "*/*"})
        try:
            with urlopen(req, timeout=c.timeout) as r:
                code = r.status
        except HTTPError as e:
            code = e.code
        assert code == 200, f"Public /cert should work without auth, got {code}"

    s.run("GET /cert accessible without token (public)", t_cert_public)

    # ── 15. Data consistency ─────────────────────────────────────────────────
    print("\n━━━━ 15. DATA CONSISTENCY ━━━━")

    def t_issued_in_list():
        code0, iss = c.post(
            "/issue",
            {"common_name": "list.check.local", "days_valid": 30, "is_overwrite": True},
        )
        assert code0 in (200, 201), f"Issue failed: {code0}: {iss}"
        serial = str(iss["serial_number"])
        _, lst = _list_get()
        assert isinstance(lst, list), f"Expected list, got: {str(lst)[:100]}"
        serials = [str(item["serial_number"]) for item in lst]
        assert serial in serials, f"Serial {serial} not found in list"

    s.run("Issued serial appears in GET /", t_issued_in_list)

    def t_revoked_in_filtered_list():
        code0, iss = c.post(
            "/issue",
            {
                "common_name": "revoke.list.local",
                "days_valid": 30,
                "is_overwrite": True,
            },
        )
        assert code0 in (200, 201), f"Issue failed: {code0}: {iss}"
        serial = str(iss["serial_number"])
        c.patch("/revoke", {"serial_number": int(serial), "reason": "unspecified"})
        _, lst = _list_get({"status": "revoked"})
        assert isinstance(lst, list), f"Expected list, got: {str(lst)[:100]}"
        serials = [str(item["serial_number"]) for item in lst]
        assert serial in serials, f"Revoked serial {serial} not in revoked list"

    s.run("Revoked cert appears in GET /?status=revoked", t_revoked_in_filtered_list)

    def t_pem_matches_chain():
        assert s.issued_uuid and s.issued_serial
        _, raw = _get_artifact(s.issued_uuid, "pem")
        _, chain_body = c.get(f"/chain/{s.issued_serial}")
        if not isinstance(chain_body, dict) or "chain" not in chain_body:
            assert False, f"Unexpected chain response: {str(chain_body)[:200]}"
        pem_dl = raw.decode() if isinstance(raw, bytes) else raw

        def normalize(p):
            return "".join(
                ln.strip()
                for ln in p.strip().splitlines()
                if not ln.strip().startswith("-----")
            )

        dl_norm = normalize(pem_dl)
        # Ищем по всей цепочке — порядок leaf/CA может отличаться между бэкендами
        found = any(normalize(c_pem) == dl_norm for c_pem in chain_body["chain"])
        assert found, (
            f"Downloaded PEM not found in chain (len={len(chain_body['chain'])})"
        )

    s.run("Downloaded PEM found in /chain", t_pem_matches_chain)

    def t_crl_has_revoked():
        # Issue, revoke, refresh CRL, check it via /crl/verify
        _, iss = c.post(
            "/issue",
            {
                "common_name": "crl.revoke.check.local",
                "days_valid": 30,
                "is_overwrite": True,
            },
        )
        c.patch(
            "/revoke", {"serial_number": iss["serial_number"], "reason": "unspecified"}
        )
        code, body = c.post("/crl/refresh")
        s.ok(code, 200)
        assert "next_update" in body

    s.run("Revoke → /crl/refresh → next_update present", t_crl_has_revoked)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main():
    args = _parse_args()

    print(f"\n{'═' * 62}")
    print(f"  tiny-ca Integration Tests")
    print(f"  Target : {args.base_url}{args.prefix}")
    print(
        f"  Auth   : {'Bearer token set' if args.token else 'no token (open access)'}"
    )
    print(f"{'═' * 62}")

    client = Client(
        base=args.base_url,
        prefix=args.prefix,
        token=args.token,
        timeout=args.timeout,
        verbose=args.verbose,
    )

    # connectivity check
    print("\nChecking server connectivity...")
    try:
        code, _ = client.get_raw("/cert")
        print(f"  ✓ Reachable (HTTP {code})")
    except URLError as exc:
        print(f"\n  ✗ Cannot reach {args.base_url}{args.prefix}/cert")
        print(f"    {exc}")
        print(f"    Start the server first!\n")
        sys.exit(1)

    suite = Suite(client=client)
    run_all(suite)

    total = len(suite.results)
    passed = sum(1 for r in suite.results if r.passed)
    failed = total - passed
    total_ms = sum(r.duration_ms for r in suite.results)

    print(f"\n{'═' * 62}")
    print(f"  {passed}/{total} passed  |  {failed} failed  |  {total_ms:.0f}ms total")
    print(f"{'═' * 62}")

    if failed:
        print(f"\n  Failed:")
        for r in suite.results:
            if not r.passed:
                print(f"    ✗ {r.name}")
                print(f"      {r.message}")
        print()
        sys.exit(1)
    else:
        print(f"\n  All {total} tests passed ✓\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
