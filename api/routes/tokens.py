"""API token management endpoints: create, list, revoke."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from api.dependencies import CurrentUserDep, DBSessionDep
from core.auth.api_tokens import create_api_token, list_api_tokens, revoke_api_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tokens", tags=["tokens"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CreateTokenRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Label for this token")


class CreateTokenResponse(BaseModel):
    """Returned ONLY at creation time. Contains the raw token."""

    id: str
    name: str
    token: str  # The full raw token — shown once, never again
    token_prefix: str
    created_at: str


class TokenInfo(BaseModel):
    """Token metadata (no raw token)."""

    id: str
    name: str
    token_prefix: str
    is_revoked: bool
    last_used_at: Optional[str]
    created_at: str


class TokenListResponse(BaseModel):
    tokens: list[TokenInfo]


class RevokeTokenResponse(BaseModel):
    id: str
    name: str
    is_revoked: bool
    message: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/", response_model=CreateTokenResponse, status_code=status.HTTP_201_CREATED)
async def create_token(
    request: CreateTokenRequest,
    user: CurrentUserDep,
    db: DBSessionDep,
) -> CreateTokenResponse:
    """Create a new API token. The raw token is returned only once."""
    api_token, raw_token = await create_api_token(
        db=db,
        user_id=user.id,
        tenant_id=user.tenant_id,
        name=request.name,
    )
    return CreateTokenResponse(
        id=api_token.id,
        name=api_token.name,
        token=raw_token,
        token_prefix=api_token.token_prefix,
        created_at=api_token.created_at.isoformat(),
    )


@router.get("/", response_model=TokenListResponse)
async def list_tokens(
    user: CurrentUserDep,
    db: DBSessionDep,
) -> TokenListResponse:
    """List all API tokens for the current user."""
    tokens = await list_api_tokens(db=db, user_id=user.id)
    return TokenListResponse(
        tokens=[
            TokenInfo(
                id=t.id,
                name=t.name,
                token_prefix=t.token_prefix,
                is_revoked=t.is_revoked,
                last_used_at=t.last_used_at.isoformat() if t.last_used_at else None,
                created_at=t.created_at.isoformat(),
            )
            for t in tokens
        ]
    )


@router.delete("/{token_id}", response_model=RevokeTokenResponse)
async def revoke_token(
    token_id: str,
    user: CurrentUserDep,
    db: DBSessionDep,
) -> RevokeTokenResponse:
    """Revoke an API token."""
    api_token = await revoke_api_token(db=db, token_id=token_id, user_id=user.id)
    if not api_token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token not found",
        )
    return RevokeTokenResponse(
        id=api_token.id,
        name=api_token.name,
        is_revoked=True,
        message="Token revoked successfully",
    )
