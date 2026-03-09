"""Tenant management endpoints."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from api.dependencies import APIKeyDep, CurrentTenantDep, DBSessionDep
from core.tenant.service import create_tenant

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tenants", tags=["tenants"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CreateTenantRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: Optional[str] = Field(None, min_length=1, max_length=100)


class TenantResponse(BaseModel):
    id: str
    name: str
    slug: str
    is_active: bool


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant_endpoint(
    request: CreateTenantRequest,
    db: DBSessionDep,
    _: APIKeyDep,
) -> TenantResponse:
    """Create a new tenant (admin-only, requires X-API-Key)."""
    try:
        tenant = await create_tenant(db=db, name=request.name, slug=request.slug)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        is_active=tenant.is_active,
    )


@router.get("/me", response_model=TenantResponse)
async def get_current_tenant_info(
    tenant: CurrentTenantDep,
) -> TenantResponse:
    """Get info about the current tenant (from X-Tenant-ID header)."""
    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        is_active=tenant.is_active,
    )
