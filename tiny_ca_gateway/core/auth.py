from __future__ import annotations

from tiny_ca_gateway.models import API_SETTINGS


def get_expected_token() -> str:
    return getattr(API_SETTINGS, "api_token", "") or ""


def auth_enabled() -> bool:
    return bool(get_expected_token())


def check_token(provided: str | None) -> bool:
    expected = get_expected_token()
    if not expected:
        return True
    return provided == expected


def extract_bearer(authorization_header: str | None) -> str | None:
    if not authorization_header:
        return None
    if authorization_header.startswith("Bearer "):
        return authorization_header[7:]
    return None
