"""Authentication service: register, login, verify, reset."""

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import jwt as pyjwt

from core.auth.email import send_password_reset_email, send_verification_email
from core.auth.jwt import create_access_token, create_approval_token, decode_approval_token
from core.database.models import Tenant, User
from core.tenant.service import create_tenant, generate_random_slug

logger = logging.getLogger(__name__)

_BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


class AuthError(Exception):
    """Raised when an auth operation fails."""

    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


async def register(
    db: AsyncSession,
    email: str,
    password: str,
    name: str,
) -> User:
    """Create a new user with an auto-generated tenant."""
    # Check global email uniqueness
    stmt = select(User).where(User.email == email)
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        raise AuthError("Email already registered", 409)

    # Auto-create tenant with random slug
    tenant_name = f"{name}'s workspace"
    slug = generate_random_slug()
    tenant = await create_tenant(db, name=tenant_name, slug=slug)

    verification_token = str(uuid.uuid4())
    user = User(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        email=email,
        password_hash=_hash_password(password),
        name=name,
        verification_token=verification_token,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # Send verification email (fire-and-forget, don't block registration)
    try:
        await send_verification_email(to=email, token=verification_token, base_url=_BASE_URL)
    except Exception:
        logger.warning("Could not send verification email to %s", email)

    logger.info("User registered (pending email verification): %s (tenant=%s)", email, tenant.slug)
    return user


async def login(
    db: AsyncSession,
    email: str,
    password: str,
) -> tuple:
    """Authenticate a user and return (access_token, tenant_slug)."""
    # Look up user by email only (globally unique)
    stmt = select(User).where(User.email == email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not _verify_password(password, user.password_hash):
        raise AuthError("Invalid email or password", 401)

    if not user.is_active:
        raise AuthError("Account is deactivated", 403)

    if not user.is_approved:
        raise AuthError("Please verify your email address before logging in", 403)

    # Look up tenant slug for the frontend
    tenant_stmt = select(Tenant).where(Tenant.id == user.tenant_id)
    tenant_result = await db.execute(tenant_stmt)
    tenant = tenant_result.scalar_one()

    token = create_access_token(user_id=user.id, tenant_id=user.tenant_id)
    return token, tenant.slug


async def verify_email(db: AsyncSession, token: str) -> User:
    """Verify a user's email using the verification token."""
    stmt = select(User).where(User.verification_token == token)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        raise AuthError("Invalid verification token", 400)

    user.email_verified = True
    user.is_approved = True
    user.verification_token = None
    await db.commit()
    await db.refresh(user)

    logger.info("Email verified and account approved for user %s", user.email)
    return user


async def request_password_reset(
    db: AsyncSession,
    email: str,
) -> None:
    """Generate a reset token and send a password reset email."""
    stmt = select(User).where(User.email == email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        # Don't reveal whether the email exists
        return

    reset_token = str(uuid.uuid4())
    user.reset_token = reset_token
    user.reset_token_expires = datetime.now(timezone.utc) + timedelta(hours=1)
    await db.commit()

    try:
        await send_password_reset_email(to=email, token=reset_token, base_url=_BASE_URL)
    except Exception:
        logger.warning("Could not send reset email to %s", email)


async def reset_password(db: AsyncSession, token: str, new_password: str) -> User:
    """Reset a user's password using a valid reset token."""
    stmt = select(User).where(User.reset_token == token)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        raise AuthError("Invalid reset token", 400)

    if user.reset_token_expires and user.reset_token_expires.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise AuthError("Reset token has expired", 400)

    user.password_hash = _hash_password(new_password)
    user.reset_token = None
    user.reset_token_expires = None
    await db.commit()
    await db.refresh(user)

    logger.info("Password reset for user %s", user.email)
    return user


async def approve_user(db: AsyncSession, token: str) -> User:
    """Approve a user account using the admin approval JWT token."""
    try:
        user_id = decode_approval_token(token)
    except pyjwt.ExpiredSignatureError:
        raise AuthError("Approval link has expired", 400)
    except (pyjwt.InvalidTokenError, ValueError) as e:
        raise AuthError(f"Invalid approval token: {e}", 400)

    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        raise AuthError("User not found", 404)

    if user.is_approved:
        raise AuthError("User is already approved", 400)

    user.is_approved = True
    await db.commit()
    await db.refresh(user)

    logger.info("User approved by admin: %s", user.email)
    return user
