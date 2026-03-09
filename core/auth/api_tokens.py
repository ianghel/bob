"""API token management: create, list, revoke, validate."""

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.models import ApiToken, User

logger = logging.getLogger(__name__)

TOKEN_PREFIX = "bob_"
TOKEN_BYTE_LENGTH = 32  # 32 bytes = 64 hex chars → total token ~68 chars


def _generate_raw_token() -> str:
    """Generate a cryptographically random token like bob_a1b2c3d4e5..."""
    random_part = secrets.token_hex(TOKEN_BYTE_LENGTH)
    return f"{TOKEN_PREFIX}{random_part}"


def _hash_token(raw_token: str) -> str:
    """SHA-256 hash of the raw token for storage."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


async def create_api_token(
    db: AsyncSession,
    user_id: str,
    tenant_id: str,
    name: str,
) -> tuple:
    """Create a new API token. Returns (db_record, raw_token).

    The raw_token is returned only once and must be shown to the user immediately.
    """
    raw_token = _generate_raw_token()
    token_hash = _hash_token(raw_token)
    token_prefix = raw_token[-4:]  # Last 4 chars for display

    api_token = ApiToken(
        id=str(uuid.uuid4()),
        user_id=user_id,
        tenant_id=tenant_id,
        name=name,
        token_hash=token_hash,
        token_prefix=token_prefix,
    )
    db.add(api_token)
    await db.commit()
    await db.refresh(api_token)

    logger.info("API token created: name=%s, user=%s", name, user_id)
    return api_token, raw_token


async def list_api_tokens(
    db: AsyncSession,
    user_id: str,
) -> list:
    """List all API tokens for a user (active and revoked)."""
    stmt = (
        select(ApiToken)
        .where(ApiToken.user_id == user_id)
        .order_by(ApiToken.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def revoke_api_token(
    db: AsyncSession,
    token_id: str,
    user_id: str,
) -> ApiToken | None:
    """Revoke an API token. Returns the token if found, None otherwise."""
    stmt = select(ApiToken).where(
        ApiToken.id == token_id,
        ApiToken.user_id == user_id,
    )
    result = await db.execute(stmt)
    api_token = result.scalar_one_or_none()

    if not api_token:
        return None

    api_token.is_revoked = True
    await db.commit()
    await db.refresh(api_token)

    logger.info("API token revoked: id=%s, user=%s", token_id, user_id)
    return api_token


async def validate_api_token(
    db: AsyncSession,
    raw_token: str,
) -> tuple | None:
    """Validate a raw API token. Returns (user, tenant_id) or None.

    Also updates last_used_at timestamp.
    """
    token_hash = _hash_token(raw_token)
    stmt = select(ApiToken).where(
        ApiToken.token_hash == token_hash,
        ApiToken.is_revoked == False,
    )
    result = await db.execute(stmt)
    api_token = result.scalar_one_or_none()

    if not api_token:
        return None

    # Load the user
    user_stmt = select(User).where(
        User.id == api_token.user_id,
        User.is_active == True,
        User.is_approved == True,
    )
    user_result = await db.execute(user_stmt)
    user = user_result.scalar_one_or_none()

    if not user:
        return None

    # Update last_used_at
    api_token.last_used_at = datetime.now(timezone.utc)
    await db.commit()

    return user, api_token.tenant_id
