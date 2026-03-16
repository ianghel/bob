"""Email endpoints — Gmail OAuth connect, sync, LLM triage, inbox, actions.

Multi-tenant: each user connects their own Gmail via OAuth.
Bob fetches emails, triages them with LLM, and shows inbox with actions.
"""

import base64
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, func

from api.dependencies import (
    APIKeyDep,
    CurrentTenantDep,
    CurrentUserDep,
    DBSessionDep,
    LLMDep,
)
from core.config import get_settings
from core.database.models import EmailAccount, EmailDigest
from core.email.gmail import (
    build_auth_url,
    exchange_code,
    fetch_unread_emails,
    fetch_sent_emails,
    send_reply,
)
from core.llm.base import Message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/email", tags=["email"])

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AttachmentInfo(BaseModel):
    name: str
    type: str = "unknown"
    size: int = 0


class EmailProcessRequest(BaseModel):
    """Payload sent by n8n when a new email arrives."""
    message_id: str = Field(..., description="Unique email message ID")
    source: str = Field("gmail", description="Email provider")
    sender: str
    subject: str = ""
    body: str = Field("", description="Email body (plain text)")
    attachments: list[AttachmentInfo] = Field(default_factory=list)
    received_at: Optional[str] = Field(None, description="ISO timestamp")


class EmailDigestResponse(BaseModel):
    id: str
    message_id: str
    source: str
    sender: str
    subject: str
    urgency: str
    category: Optional[str]
    action: Optional[str]
    reply_draft: Optional[str]
    attachments: list[dict]
    status: str
    received_at: Optional[str]
    processed_at: str


class EmailActionRequest(BaseModel):
    """User action on a digest entry."""
    action: str = Field(..., description="send | skip | edit")
    edited_reply: Optional[str] = Field(None, description="Custom reply text (if action=edit)")


# ---------------------------------------------------------------------------
# GET /email/connections — check connected accounts
# ---------------------------------------------------------------------------


@router.get("/connections", summary="Check email provider connections")
async def get_connections(
    user: CurrentUserDep,
    tenant: CurrentTenantDep,
    db: DBSessionDep,
):
    """Check which email providers are connected for the current user."""
    settings = get_settings()

    result = await db.execute(
        select(EmailAccount).where(
            EmailAccount.user_id == user.id,
            EmailAccount.is_active == True,
        )
    )
    accounts = result.scalars().all()

    gmail_account = next((a for a in accounts if a.provider == "gmail"), None)

    return {
        "gmail": {
            "connected": gmail_account is not None,
            "email": gmail_account.email_address if gmail_account else None,
            "can_connect": bool(settings.google_client_id),
        },
    }


# ---------------------------------------------------------------------------
# GET /email/connect/gmail — initiate Google OAuth
# ---------------------------------------------------------------------------


@router.get("/connect/gmail", summary="Connect Gmail via OAuth")
async def connect_gmail(
    user: CurrentUserDep,
    tenant: CurrentTenantDep,
):
    """Redirect user to Google OAuth consent screen."""
    settings = get_settings()

    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Google OAuth not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.",
        )

    redirect_uri = settings.google_redirect_uri or f"{settings.base_url}/api/v1/email/callback/gmail"

    # Encode user context in state
    state_data = json.dumps({"user_id": user.id, "tenant_id": tenant.id})
    state = base64.urlsafe_b64encode(state_data.encode()).decode()

    auth_url = build_auth_url(
        client_id=settings.google_client_id,
        redirect_uri=redirect_uri,
        state=state,
    )

    return {"auth_url": auth_url}


# ---------------------------------------------------------------------------
# GET /email/callback/gmail — Google OAuth callback
# ---------------------------------------------------------------------------


@router.get("/callback/gmail", summary="Gmail OAuth callback", include_in_schema=False)
async def gmail_callback(
    request: Request,
    db: DBSessionDep,
    code: str = Query(...),
    state: str = Query(""),
    error: Optional[str] = Query(None),
):
    """Handle Google OAuth callback — exchange code for tokens."""
    settings = get_settings()

    if error:
        return RedirectResponse(
            url=f"{settings.base_url or ''}/?email_error={error}",
            status_code=302,
        )

    # Decode state
    try:
        state_data = json.loads(base64.urlsafe_b64decode(state).decode())
        user_id = state_data["user_id"]
        tenant_id = state_data["tenant_id"]
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    redirect_uri = settings.google_redirect_uri or f"{settings.base_url}/api/v1/email/callback/gmail"

    # Exchange code for tokens
    try:
        token_data = await exchange_code(
            code=code,
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            redirect_uri=redirect_uri,
        )
    except Exception as e:
        logger.error("Gmail OAuth token exchange failed: %s", e)
        return RedirectResponse(
            url=f"{settings.base_url or ''}/?email_error=token_exchange_failed",
            status_code=302,
        )

    # Upsert EmailAccount
    result = await db.execute(
        select(EmailAccount).where(
            EmailAccount.user_id == user_id,
            EmailAccount.provider == "gmail",
        )
    )
    account = result.scalar_one_or_none()

    if account:
        account.access_token = token_data["access_token"]
        account.refresh_token = token_data.get("refresh_token") or account.refresh_token
        account.token_expires_at = token_data["expires_at"]
        account.email_address = token_data["email_address"]
        account.scopes = token_data.get("scopes", "")
        account.is_active = True
        account.updated_at = datetime.now(timezone.utc)
    else:
        account = EmailAccount(
            user_id=user_id,
            tenant_id=tenant_id,
            provider="gmail",
            email_address=token_data["email_address"],
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            token_expires_at=token_data["expires_at"],
            scopes=token_data.get("scopes", ""),
        )
        db.add(account)

    await db.commit()

    logger.info("Gmail connected for user %s: %s", user_id, token_data["email_address"])

    # Redirect back to frontend email tab
    return RedirectResponse(
        url=f"{settings.base_url or ''}/?tab=email&gmail_connected=1",
        status_code=302,
    )


# ---------------------------------------------------------------------------
# POST /email/disconnect/gmail — remove Gmail connection
# ---------------------------------------------------------------------------


@router.post("/disconnect/gmail", summary="Disconnect Gmail")
async def disconnect_gmail(
    user: CurrentUserDep,
    tenant: CurrentTenantDep,
    db: DBSessionDep,
):
    """Remove Gmail OAuth connection for the current user."""
    result = await db.execute(
        select(EmailAccount).where(
            EmailAccount.user_id == user.id,
            EmailAccount.provider == "gmail",
            EmailAccount.is_active == True,
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="No Gmail account connected")

    account.is_active = False
    await db.commit()

    return {"message": "Gmail disconnected"}


# ---------------------------------------------------------------------------
# POST /email/sync — fetch new emails from connected Gmail
# ---------------------------------------------------------------------------


@router.post("/sync", summary="Sync emails from connected Gmail")
async def sync_emails(
    user: CurrentUserDep,
    tenant: CurrentTenantDep,
    db: DBSessionDep,
    llm: LLMDep,
):
    """Fetch unread emails from Gmail and triage them with LLM."""
    settings = get_settings()

    # Get active Gmail account
    result = await db.execute(
        select(EmailAccount).where(
            EmailAccount.user_id == user.id,
            EmailAccount.is_active == True,
        )
    )
    accounts = result.scalars().all()

    if not accounts:
        raise HTTPException(status_code=404, detail="No email accounts connected. Connect Gmail first.")

    total_new = 0
    total_sent = 0
    errors = []

    for account in accounts:
        try:
            if account.provider == "gmail":
                # --- Inbox (unread) ---
                raw_emails = await fetch_unread_emails(
                    account=account,
                    client_id=settings.google_client_id,
                    client_secret=settings.google_client_secret,
                    max_results=20,
                )

                # Save refreshed token if it was updated
                await db.commit()

                for email_data in raw_emails:
                    # Dedup
                    existing = await db.execute(
                        select(EmailDigest).where(
                            EmailDigest.message_id == email_data["message_id"]
                        )
                    )
                    if existing.scalar_one_or_none():
                        continue

                    # Triage with LLM
                    triage = await _triage_email_dict(llm, email_data)

                    # Parse received_at
                    received = None
                    if email_data.get("received_at"):
                        try:
                            received = datetime.fromisoformat(
                                email_data["received_at"].replace("Z", "+00:00")
                            )
                        except ValueError:
                            pass

                    digest = EmailDigest(
                        tenant_id=tenant.id,
                        user_id=user.id,
                        message_id=email_data["message_id"],
                        source="gmail",
                        sender=email_data["sender"],
                        subject=email_data["subject"],
                        body_snippet=email_data.get("body", "")[:500],
                        attachments_json=email_data.get("attachments", []),
                        urgency=triage.get("urgency", "medium"),
                        category=triage.get("category", "other"),
                        action=triage.get("action"),
                        reply_draft=triage.get("reply_draft"),
                        status="pending",
                        received_at=received,
                    )
                    db.add(digest)
                    total_new += 1

                # --- Sent emails ---
                sent_emails = await fetch_sent_emails(
                    account=account,
                    client_id=settings.google_client_id,
                    client_secret=settings.google_client_secret,
                    max_results=20,
                )

                total_sent = 0
                for email_data in sent_emails:
                    existing = await db.execute(
                        select(EmailDigest).where(
                            EmailDigest.message_id == email_data["message_id"]
                        )
                    )
                    if existing.scalar_one_or_none():
                        continue

                    received = None
                    if email_data.get("received_at"):
                        try:
                            received = datetime.fromisoformat(
                                email_data["received_at"].replace("Z", "+00:00")
                            )
                        except ValueError:
                            pass

                    to_addr = email_data.get("to", "unknown")
                    digest = EmailDigest(
                        tenant_id=tenant.id,
                        user_id=user.id,
                        message_id=email_data["message_id"],
                        source="gmail",
                        sender=f"me → {to_addr}",
                        subject=email_data["subject"],
                        body_snippet=email_data.get("body", "")[:500],
                        attachments_json=email_data.get("attachments", []),
                        urgency="low",
                        category="sent",
                        action=f"Sent to {to_addr}",
                        reply_draft=None,
                        status="sent",
                        received_at=received,
                    )
                    db.add(digest)
                    total_sent += 1

                # Update last sync
                account.last_sync_at = datetime.now(timezone.utc)

        except Exception as e:
            logger.error("Sync failed for %s (%s): %s", account.provider, account.email_address, e)
            errors.append(f"{account.provider}: {str(e)}")

    await db.commit()

    return {
        "synced_inbox": total_new,
        "synced_sent": total_sent,
        "errors": errors if errors else None,
    }


# ---------------------------------------------------------------------------
# POST /email/process — external ingest (n8n or API)
# ---------------------------------------------------------------------------


@router.post(
    "/process",
    response_model=EmailDigestResponse,
    summary="Process an incoming email (called by n8n)",
    status_code=status.HTTP_201_CREATED,
)
async def process_email(
    payload: EmailProcessRequest,
    api_key: APIKeyDep,
    llm: LLMDep,
    db: DBSessionDep,
    tenant_id: str = Query(..., description="Tenant ID"),
    user_id: str = Query(..., description="User ID"),
):
    """Receive an email from n8n, run LLM triage, store digest."""
    # Dedup by message_id
    existing = await db.execute(
        select(EmailDigest).where(EmailDigest.message_id == payload.message_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Email {payload.message_id} already processed",
        )

    # LLM triage
    triage = await _triage_email_payload(llm, payload)

    # Parse received_at
    received = None
    if payload.received_at:
        try:
            received = datetime.fromisoformat(payload.received_at.replace("Z", "+00:00"))
        except ValueError:
            pass

    digest = EmailDigest(
        tenant_id=tenant_id,
        user_id=user_id,
        message_id=payload.message_id,
        source=payload.source,
        sender=payload.sender,
        subject=payload.subject,
        body_snippet=payload.body[:500] if payload.body else None,
        attachments_json=[a.model_dump() for a in payload.attachments],
        urgency=triage.get("urgency", "medium"),
        category=triage.get("category", "other"),
        action=triage.get("action"),
        reply_draft=triage.get("reply_draft"),
        status="pending",
        received_at=received,
    )
    db.add(digest)
    await db.commit()
    await db.refresh(digest)

    return _to_response(digest)


# ---------------------------------------------------------------------------
# GET /email/inbox — dashboard feed
# ---------------------------------------------------------------------------


@router.get(
    "/inbox",
    response_model=list[EmailDigestResponse],
    summary="Get email inbox digest",
)
async def get_inbox(
    user: CurrentUserDep,
    tenant: CurrentTenantDep,
    db: DBSessionDep,
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
):
    """Return processed emails for the current user, newest first."""
    query = (
        select(EmailDigest)
        .where(
            EmailDigest.tenant_id == tenant.id,
            EmailDigest.user_id == user.id,
        )
        .order_by(EmailDigest.processed_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if status_filter:
        query = query.where(EmailDigest.status == status_filter)

    result = await db.execute(query)
    digests = result.scalars().all()
    return [_to_response(d) for d in digests]


# ---------------------------------------------------------------------------
# GET /email/stats
# ---------------------------------------------------------------------------


@router.get("/stats", summary="Email digest stats")
async def get_stats(
    user: CurrentUserDep,
    tenant: CurrentTenantDep,
    db: DBSessionDep,
):
    """Quick count of pending/high-urgency emails."""
    base = select(func.count()).select_from(EmailDigest).where(
        EmailDigest.tenant_id == tenant.id,
        EmailDigest.user_id == user.id,
    )
    pending = await db.execute(base.where(EmailDigest.status == "pending"))
    high = await db.execute(
        base.where(EmailDigest.urgency == "high", EmailDigest.status == "pending")
    )

    return {
        "pending": pending.scalar() or 0,
        "high_urgency": high.scalar() or 0,
    }


# ---------------------------------------------------------------------------
# GET /email/summary — daily email summary
# ---------------------------------------------------------------------------


@router.get("/summary", summary="Daily email summary")
async def get_daily_summary(
    user: CurrentUserDep,
    tenant: CurrentTenantDep,
    db: DBSessionDep,
    llm: LLMDep,
):
    """Generate an LLM-powered summary of today's emails."""
    # Get today's emails (last 24 hours)
    since = datetime.now(timezone.utc) - timedelta(hours=24)

    result = await db.execute(
        select(EmailDigest)
        .where(
            EmailDigest.tenant_id == tenant.id,
            EmailDigest.user_id == user.id,
            EmailDigest.processed_at >= since,
        )
        .order_by(EmailDigest.received_at.desc())
    )
    digests = result.scalars().all()

    if not digests:
        return {
            "summary": "No emails received in the last 24 hours.",
            "email_count": 0,
            "categories": {},
        }

    # Build category counts
    categories: dict[str, int] = {}
    for d in digests:
        cat = d.category or "other"
        categories[cat] = categories.get(cat, 0) + 1

    # Build email list for LLM
    email_lines = []
    for i, d in enumerate(digests[:30], 1):
        urgency = d.urgency or "?"
        category = d.category or "?"
        status_str = d.status or "?"
        email_lines.append(
            f"{i}. [{urgency.upper()}] [{category}] From: {d.sender} — Subject: {d.subject}\n"
            f"   Action: {d.action or 'none'} | Status: {status_str}"
        )

    emails_text = "\n".join(email_lines)

    summary_prompt = f"""You are Bob, an AI email assistant. Generate a concise daily email summary in Romanian.

You have {len(digests)} emails from the last 24 hours:

{emails_text}

Write a brief, natural summary (3-5 sentences) covering:
- How many emails total, and key categories
- Any urgent items that need attention
- Notable senders or topics
- What's already been handled vs what's pending

Keep it conversational and helpful. Write in Romanian."""

    try:
        response = await llm.chat(
            messages=[Message(role="user", content=summary_prompt)],
            temperature=0.3,
            max_tokens=500,
        )
        summary = response.content.strip()
    except Exception as e:
        logger.error("Summary generation failed: %s", e)
        high_count = sum(1 for d in digests if d.urgency == "high")
        pending_count = sum(1 for d in digests if d.status == "pending")
        summary = (
            f"Ai {len(digests)} emailuri din ultimele 24 de ore. "
            f"{high_count} urgente, {pending_count} in asteptare. "
            f"Categorii: {', '.join(f'{k} ({v})' for k, v in categories.items())}."
        )

    return {
        "summary": summary,
        "email_count": len(digests),
        "categories": categories,
    }


# ---------------------------------------------------------------------------
# PATCH /email/{digest_id}/action — user responds
# ---------------------------------------------------------------------------


@router.patch(
    "/{digest_id}/action",
    response_model=EmailDigestResponse,
    summary="Take action on an email digest",
)
async def take_action(
    digest_id: str,
    body: EmailActionRequest,
    user: CurrentUserDep,
    tenant: CurrentTenantDep,
    db: DBSessionDep,
):
    """Mark a digest as sent/skipped/edited. If 'send', actually send the reply via Gmail."""
    settings = get_settings()

    result = await db.execute(
        select(EmailDigest).where(
            EmailDigest.id == digest_id,
            EmailDigest.tenant_id == tenant.id,
            EmailDigest.user_id == user.id,
        )
    )
    digest = result.scalar_one_or_none()
    if not digest:
        raise HTTPException(status_code=404, detail="Email digest not found")

    if body.action == "edit" and body.edited_reply:
        digest.reply_draft = body.edited_reply
        digest.status = "edited"

    elif body.action == "send":
        # Actually send the reply via Gmail API
        reply_text = digest.reply_draft
        if reply_text and digest.source == "gmail":
            account_result = await db.execute(
                select(EmailAccount).where(
                    EmailAccount.user_id == user.id,
                    EmailAccount.provider == "gmail",
                    EmailAccount.is_active == True,
                )
            )
            account = account_result.scalar_one_or_none()
            if account and settings.google_client_id:
                try:
                    await send_reply(
                        account=account,
                        client_id=settings.google_client_id,
                        client_secret=settings.google_client_secret,
                        to=digest.sender,
                        subject=digest.subject or "",
                        body=reply_text,
                    )
                    # Save any refreshed tokens
                    await db.commit()
                except Exception as e:
                    logger.error("Failed to send Gmail reply: %s", e)
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to send reply: {str(e)}",
                    )
        digest.status = "sent"

    elif body.action == "skip":
        digest.status = "skipped"

    else:
        raise HTTPException(status_code=400, detail="Invalid action (send|skip|edit)")

    await db.commit()
    await db.refresh(digest)
    return _to_response(digest)


# ---------------------------------------------------------------------------
# LLM triage
# ---------------------------------------------------------------------------

TRIAGE_PROMPT = """You are an email assistant. Analyze this email and respond ONLY with JSON (no markdown, no backticks):

From: {sender}
Subject: {subject}
Body: {body}
Attachments: {attachments}

JSON format:
{{"urgency": "low|medium|high", "category": "invoice|meeting|question|newsletter|notification|personal|spam|other", "action": "one short sentence about what to do", "reply_draft": "1-2 sentence suggested reply, or null if no reply needed"}}"""


async def _triage_email_dict(llm, email_data: dict) -> dict:
    """Run LLM triage on a raw email dict."""
    body_for_llm = email_data.get("body", "")[:1500] or "(empty)"
    attachments_str = ", ".join(
        f"{a['name']} ({a.get('type', '?')})" for a in email_data.get("attachments", [])
    ) or "none"

    prompt = TRIAGE_PROMPT.format(
        sender=email_data.get("sender", "unknown"),
        subject=email_data.get("subject", ""),
        body=body_for_llm,
        attachments=attachments_str,
    )

    try:
        response = await llm.chat(
            messages=[Message(role="user", content=prompt)],
            temperature=0.1,
            max_tokens=300,
        )
        raw = response.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return json.loads(raw)
    except Exception as e:
        logger.warning("LLM triage failed: %s", e)
        return {
            "urgency": "medium",
            "category": "other",
            "action": "Review this email manually",
            "reply_draft": None,
        }


async def _triage_email_payload(llm, payload: EmailProcessRequest) -> dict:
    """Run LLM triage on an EmailProcessRequest."""
    return await _triage_email_dict(llm, {
        "sender": payload.sender,
        "subject": payload.subject,
        "body": payload.body,
        "attachments": [a.model_dump() for a in payload.attachments],
    })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_response(d: EmailDigest) -> EmailDigestResponse:
    return EmailDigestResponse(
        id=d.id,
        message_id=d.message_id,
        source=d.source,
        sender=d.sender,
        subject=d.subject or "",
        urgency=d.urgency,
        category=d.category,
        action=d.action,
        reply_draft=d.reply_draft,
        attachments=d.attachments_json or [],
        status=d.status,
        received_at=d.received_at.isoformat() if d.received_at else None,
        processed_at=d.processed_at.isoformat(),
    )
