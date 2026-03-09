"""Tenant CRUD service."""

import logging
import re
import secrets
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.models import Tenant

logger = logging.getLogger(__name__)


def generate_random_slug(length: int = 12) -> str:
    """Generate a cryptographically random URL-safe slug.

    secrets.token_urlsafe(12) produces a 16-char string using
    A-Z, a-z, 0-9, - and _ (base64url alphabet, no padding).
    """
    return secrets.token_urlsafe(length)


async def create_tenant(db: AsyncSession, name: str, slug: Optional[str] = None) -> Tenant:
    """Create a new tenant.

    Args:
        db: Async database session.
        name: Tenant display name.
        slug: URL-safe identifier. Auto-generated from name if omitted.

    Returns:
        The newly created Tenant.

    Raises:
        ValueError: If slug already exists.
    """
    if slug is None:
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

    existing = await get_tenant_by_slug(db, slug)
    if existing:
        raise ValueError(f"Tenant slug '{slug}' already exists")

    tenant = Tenant(id=str(uuid.uuid4()), name=name, slug=slug)
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)

    logger.info("Tenant created: %s (slug=%s)", name, slug)
    return tenant


async def get_tenant_by_slug(db: AsyncSession, slug: str) -> Optional[Tenant]:
    """Look up a tenant by its slug."""
    stmt = select(Tenant).where(Tenant.slug == slug, Tenant.is_active == True)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_tenant_by_id(db: AsyncSession, tenant_id: str) -> Optional[Tenant]:
    """Look up a tenant by its ID."""
    stmt = select(Tenant).where(Tenant.id == tenant_id, Tenant.is_active == True)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
