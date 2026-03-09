"""Authentication endpoints: register, login, verify email, password reset."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.dependencies import CurrentUserDep, DBSessionDep
from core.auth.service import (
    AuthError,
    approve_user,
    login,
    register,
    request_password_reset,
    reset_password,
    verify_email,
)
from core.database.models import Tenant

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3)
    password: str = Field(..., min_length=8)
    name: str = Field(..., min_length=1)


class RegisterResponse(BaseModel):
    user_id: str
    email: str
    name: str
    message: str


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    tenant_slug: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8)


class UserProfileResponse(BaseModel):
    user_id: str
    email: str
    name: str
    tenant_id: str
    tenant_slug: str
    email_verified: bool


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register_user(
    request: RegisterRequest,
    db: DBSessionDep,
) -> RegisterResponse:
    """Register a new user (auto-creates a tenant)."""
    try:
        user = await register(
            db=db,
            email=request.email,
            password=request.password,
            name=request.name,
        )
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    return RegisterResponse(
        user_id=user.id,
        email=user.email,
        name=user.name,
        message="Registration successful. Your account is pending admin approval.",
    )


@router.post("/login", response_model=LoginResponse)
async def login_user(
    request: LoginRequest,
    db: DBSessionDep,
) -> LoginResponse:
    """Authenticate and receive a JWT access token."""
    try:
        token, tenant_slug = await login(
            db=db,
            email=request.email,
            password=request.password,
        )
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    return LoginResponse(access_token=token, tenant_slug=tenant_slug)


@router.get("/verify-email")
async def verify_email_endpoint(
    token: str,
    db: DBSessionDep,
) -> dict:
    """Verify a user's email using the token from the verification email."""
    try:
        user = await verify_email(db=db, token=token)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    return {"message": "Email verified successfully", "email": user.email}


@router.get("/approve-user")
async def approve_user_endpoint(
    token: str,
    db: DBSessionDep,
) -> dict:
    """Approve a user account (admin clicks link from email)."""
    try:
        user = await approve_user(db=db, token=token)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    return {
        "message": f"User {user.email} has been approved successfully.",
        "email": user.email,
        "user_id": user.id,
    }


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(
    request: ForgotPasswordRequest,
    db: DBSessionDep,
) -> dict:
    """Request a password reset email."""
    await request_password_reset(db=db, email=request.email)
    return {"message": "If the email exists, a reset link has been sent."}


@router.post("/reset-password")
async def reset_password_endpoint(
    request: ResetPasswordRequest,
    db: DBSessionDep,
) -> dict:
    """Reset password using a valid reset token."""
    try:
        user = await reset_password(db=db, token=request.token, new_password=request.new_password)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    return {"message": "Password reset successfully"}


@router.get("/me", response_model=UserProfileResponse)
async def get_profile(
    user: CurrentUserDep,
    db: DBSessionDep,
) -> UserProfileResponse:
    """Get the current authenticated user's profile."""
    # Look up tenant slug
    tenant_stmt = select(Tenant).where(Tenant.id == user.tenant_id)
    tenant_result = await db.execute(tenant_stmt)
    tenant = tenant_result.scalar_one()

    return UserProfileResponse(
        user_id=user.id,
        email=user.email,
        name=user.name,
        tenant_id=user.tenant_id,
        tenant_slug=tenant.slug,
        email_verified=user.email_verified,
    )
