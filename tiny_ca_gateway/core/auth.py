"""
tiny_ca_gateway/core/auth.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Единая логика проверки Bearer-токена для всех фреймворков.

  CA_API_TOKEN пустой/не задан → открытый доступ.
  CA_API_TOKEN задан            → токен обязателен.
"""

from __future__ import annotations

from tiny_ca_gateway.models import API_SETTINGS


def get_expected_token() -> str:
    return getattr(API_SETTINGS, "api_token", "") or ""


def auth_enabled() -> bool:
    return bool(get_expected_token())


def check_token(provided: str | None) -> bool:
    """True = доступ разрешён."""
    expected = get_expected_token()
    if not expected:
        return True  # auth выключен
    return provided == expected


def extract_bearer(authorization_header: str | None) -> str | None:
    if not authorization_header:
        return None
    if authorization_header.startswith("Bearer "):
        return authorization_header[7:]
    return None
