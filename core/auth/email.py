"""Async email sending via SMTP for verification and password reset."""

import logging
import os
from email.message import EmailMessage

import aiosmtplib

logger = logging.getLogger(__name__)

_MAIL_HOST = os.getenv("MAIL_HOST", "127.0.0.1")
_MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
_MAIL_USERNAME = os.getenv("MAIL_USERNAME", "")
_MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
_MAIL_ENCRYPTION = os.getenv("MAIL_ENCRYPTION", "tls").lower()  # "tls" (STARTTLS) or "ssl"
_MAIL_FROM_ADDRESS = os.getenv("MAIL_FROM_ADDRESS", os.getenv("MAIL_FROM", "bob@localhost"))
_MAIL_FROM_NAME = os.getenv("MAIL_FROM_NAME", "Bob")
_ADMIN_APPROVAL_EMAIL = os.getenv("ADMIN_APPROVAL_EMAIL", "")


async def _send(to: str, subject: str, body: str) -> None:
    """Send a plain-text email via SMTP with TLS/SSL and authentication."""
    msg = EmailMessage()
    msg["From"] = f"{_MAIL_FROM_NAME} <{_MAIL_FROM_ADDRESS}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    # SSL = implicit TLS on connect (port 465)
    # TLS = STARTTLS after connect (port 587)
    use_tls = _MAIL_ENCRYPTION == "ssl"
    start_tls = _MAIL_ENCRYPTION == "tls"

    smtp_kwargs: dict = {
        "hostname": _MAIL_HOST,
        "port": _MAIL_PORT,
        "use_tls": use_tls,
        "start_tls": start_tls,
    }

    if _MAIL_USERNAME and _MAIL_PASSWORD:
        smtp_kwargs["username"] = _MAIL_USERNAME
        smtp_kwargs["password"] = _MAIL_PASSWORD

    try:
        await aiosmtplib.send(msg, **smtp_kwargs)
        logger.info("Email sent to %s: %s", to, subject)
    except Exception as e:
        logger.error("Failed to send email to %s: %s", to, e)
        raise


async def send_verification_email(to: str, token: str, base_url: str = "http://localhost:8000") -> None:
    """Send an email verification link."""
    link = f"{base_url}/api/v1/auth/verify-email?token={token}"
    await _send(
        to=to,
        subject="Verify your email",
        body=f"Please verify your email by clicking the link below:\n\n{link}\n\nIf you did not create an account, ignore this email.",
    )


async def send_password_reset_email(to: str, token: str, base_url: str = "http://localhost:8000") -> None:
    """Send a password reset link."""
    link = f"{base_url}/api/v1/auth/reset-password?token={token}"
    await _send(
        to=to,
        subject="Reset your password",
        body=f"Click the link below to reset your password:\n\n{link}\n\nThis link expires in 1 hour. If you did not request this, ignore this email.",
    )


async def send_admin_approval_email(
    user_email: str,
    user_name: str,
    tenant_name: str,
    token: str,
    base_url: str = "http://localhost:8000",
) -> None:
    """Send an approval request email to the admin."""
    if not _ADMIN_APPROVAL_EMAIL:
        logger.warning("ADMIN_APPROVAL_EMAIL not set — skipping approval email")
        return

    approve_link = f"{base_url}/api/v1/auth/approve-user?token={token}"

    await _send(
        to=_ADMIN_APPROVAL_EMAIL,
        subject=f"[Bob] New user registration: {user_email}",
        body=(
            f"A new user has registered and is awaiting your approval.\n\n"
            f"  Name:   {user_name}\n"
            f"  Email:  {user_email}\n"
            f"  Tenant: {tenant_name}\n\n"
            f"Click the link below to approve this user:\n\n"
            f"  {approve_link}\n\n"
            f"If you do not recognise this request, simply ignore this email."
        ),
    )
