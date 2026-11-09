from datetime import datetime, timedelta
from enum import Enum
import hmac

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from tiny_ca_gateway.models import API_SETTINGS

security = HTTPBearer()


def _same(provided: str, expected: str) -> bool:
    """Constant-time token comparison."""
    return hmac.compare_digest(provided.encode(), expected.encode())


class RolesAccess(Enum):
    GLOBAL = "global"
    TEMPORARY = "temporary"


def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    token = credentials.credentials

    if not _same(token, API_SETTINGS.api_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    return token


def verify_temporary_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str | None:
    token = credentials.credentials
    is_global = _same(token, API_SETTINGS.api_token)
    if not is_global and not _same(token, API_SETTINGS.internal_temporary_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )
    # check global token
    if is_global:
        return None
    if API_SETTINGS.internal_token_valid_until is None:
        internal_token_valid_until = datetime.now() + timedelta(
            minutes=API_SETTINGS.ttl_token
        )
        API_SETTINGS.internal_token_valid_until = internal_token_valid_until
    else:
        time_token: str | datetime = API_SETTINGS.internal_token_valid_until
        if isinstance(time_token, str):
            time_token = datetime.strptime(time_token, API_SETTINGS.datetime_fmt)

        if time_token < datetime.now():  # type: ignore[operator]
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Expired ttl temporary token",
            )
    return token
