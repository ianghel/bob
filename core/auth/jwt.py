"""JWT token creation and validation."""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt

_SECRET = os.getenv("JWT_SECRET", "change-me-in-production")
_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60"))


def create_access_token(user_id: str, tenant_id: str) -> str:
    """Create a signed JWT access token."""
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=_EXPIRE_MINUTES),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, _SECRET, algorithm=_ALGORITHM)


def maybe_refresh_token(token: str) -> Optional[str]:
    """Return a fresh token if the current one is in its refresh window.

    The refresh window is the last *N %* of the token's total lifetime
    (configured via ``JWT_REFRESH_THRESHOLD_PERCENT``).  If the token is
    still young enough, ``None`` is returned.
    """
    from core.config import get_settings

    settings = get_settings()
    if not settings.jwt_auto_refresh:
        return None

    try:
        payload = jwt.decode(token, _SECRET, algorithms=[_ALGORITHM])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None

    exp = payload.get("exp")
    iat = payload.get("iat")
    if not exp or not iat:
        return None

    exp_dt = datetime.fromtimestamp(exp, tz=timezone.utc)
    iat_dt = datetime.fromtimestamp(iat, tz=timezone.utc)
    now = datetime.now(timezone.utc)

    total_lifetime = (exp_dt - iat_dt).total_seconds()
    remaining = (exp_dt - now).total_seconds()

    threshold = settings.jwt_refresh_threshold_percent / 100.0
    if remaining <= total_lifetime * threshold:
        user_id = payload.get("sub")
        tenant_id = payload.get("tenant_id")
        if user_id and tenant_id:
            return create_access_token(user_id=user_id, tenant_id=tenant_id)

    return None


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token.

    Returns:
        Dict with 'sub' (user_id) and 'tenant_id'.

    Raises:
        jwt.ExpiredSignatureError: Token has expired.
        jwt.InvalidTokenError: Token is malformed or invalid.
    """
    return jwt.decode(token, _SECRET, algorithms=[_ALGORITHM])


# ---------------------------------------------------------------------------
# Admin-approval tokens (used in email link, not for API auth)
# ---------------------------------------------------------------------------

_APPROVAL_EXPIRE_DAYS = int(os.getenv("APPROVAL_TOKEN_EXPIRE_DAYS", "7"))


def create_approval_token(user_id: str) -> str:
    """Create a JWT for admin approval of a user account (7-day default expiry)."""
    payload = {
        "sub": user_id,
        "purpose": "admin_approval",
        "exp": datetime.now(timezone.utc) + timedelta(days=_APPROVAL_EXPIRE_DAYS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, _SECRET, algorithm=_ALGORITHM)


def decode_approval_token(token: str) -> str:
    """Decode an approval JWT and return the user_id.

    Raises:
        jwt.ExpiredSignatureError: Token has expired.
        jwt.InvalidTokenError: Token is malformed or invalid.
        ValueError: Token purpose is not 'admin_approval'.
    """
    payload = jwt.decode(token, _SECRET, algorithms=[_ALGORITHM])
    if payload.get("purpose") != "admin_approval":
        raise ValueError("Token is not an approval token")
    user_id = payload.get("sub")
    if not user_id:
        raise ValueError("Token missing user ID")
    return user_id
