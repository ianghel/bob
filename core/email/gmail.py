"""Gmail OAuth2 + API client for Bob.

Handles:
  - OAuth2 authorization URL generation
  - Token exchange (auth code -> access/refresh tokens)
  - Token refresh
  - Fetching unread emails via Gmail API
  - Sending replies via Gmail API
"""

import base64
import logging
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from typing import Optional
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1"

# Scopes needed for reading + sending email
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",  # to mark as read
    "https://www.googleapis.com/auth/userinfo.email",
]


def build_auth_url(client_id: str, redirect_uri: str, state: str) -> str:
    """Build the Google OAuth2 authorization URL."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(GMAIL_SCOPES),
        "access_type": "offline",  # needed for refresh_token
        "prompt": "consent",  # always show consent to get refresh_token
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


async def exchange_code(
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> dict:
    """Exchange authorization code for access + refresh tokens."""
    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        res.raise_for_status()
        data = res.json()

    # Get user email from userinfo
    email_address = await _get_user_email(data["access_token"])

    return {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token"),
        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=data.get("expires_in", 3600)),
        "scopes": data.get("scope", ""),
        "email_address": email_address,
    }


async def refresh_access_token(
    refresh_token: str,
    client_id: str,
    client_secret: str,
) -> dict:
    """Refresh an expired access token."""
    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
            },
        )
        res.raise_for_status()
        data = res.json()

    return {
        "access_token": data["access_token"],
        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=data.get("expires_in", 3600)),
    }


async def _get_user_email(access_token: str) -> str:
    """Get the authenticated user's email address."""
    async with httpx.AsyncClient(timeout=10) as client:
        res = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        res.raise_for_status()
        return res.json().get("email", "unknown")


async def _ensure_valid_token(account, client_id: str, client_secret: str) -> str:
    """Return a valid access token, refreshing if expired."""
    now = datetime.now(timezone.utc)
    expires_at = account.token_expires_at
    if expires_at:
        # Handle naive datetimes (stored without timezone)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at > now + timedelta(minutes=2):
            return account.access_token

    if not account.refresh_token:
        raise RuntimeError("Token expired and no refresh token available")

    logger.info("Refreshing Gmail token for %s", account.email_address)
    refreshed = await refresh_access_token(account.refresh_token, client_id, client_secret)
    account.access_token = refreshed["access_token"]
    account.token_expires_at = refreshed["expires_at"]
    return refreshed["access_token"]


async def fetch_unread_emails(
    account,
    client_id: str,
    client_secret: str,
    max_results: int = 10,
) -> list[dict]:
    """Fetch recent inbox emails from Gmail API."""
    token = await _ensure_valid_token(account, client_id, client_secret)

    async with httpx.AsyncClient(timeout=20) as client:
        # List recent inbox messages (not just unread)
        res = await client.get(
            f"{GMAIL_API_BASE}/users/me/messages",
            headers={"Authorization": f"Bearer {token}"},
            params={"q": "in:inbox", "maxResults": max_results},
        )
        res.raise_for_status()
        messages = res.json().get("messages", [])

        if not messages:
            return []

        # Fetch each message details
        emails = []
        for msg_ref in messages:
            msg_res = await client.get(
                f"{GMAIL_API_BASE}/users/me/messages/{msg_ref['id']}",
                headers={"Authorization": f"Bearer {token}"},
                params={"format": "full"},
            )
            if msg_res.status_code != 200:
                continue

            msg = msg_res.json()
            emails.append(_parse_gmail_message(msg))

    return emails


async def fetch_sent_emails(
    account,
    client_id: str,
    client_secret: str,
    max_results: int = 10,
) -> list[dict]:
    """Fetch recently sent emails from Gmail API."""
    token = await _ensure_valid_token(account, client_id, client_secret)

    async with httpx.AsyncClient(timeout=20) as client:
        res = await client.get(
            f"{GMAIL_API_BASE}/users/me/messages",
            headers={"Authorization": f"Bearer {token}"},
            params={"q": "in:sent", "maxResults": max_results},
        )
        res.raise_for_status()
        messages = res.json().get("messages", [])

        if not messages:
            return []

        emails = []
        for msg_ref in messages:
            msg_res = await client.get(
                f"{GMAIL_API_BASE}/users/me/messages/{msg_ref['id']}",
                headers={"Authorization": f"Bearer {token}"},
                params={"format": "full"},
            )
            if msg_res.status_code != 200:
                continue

            msg = msg_res.json()
            parsed = _parse_gmail_message(msg)
            parsed["is_sent"] = True
            emails.append(parsed)

    return emails


def _parse_gmail_message(msg: dict) -> dict:
    """Parse a Gmail API message into a clean dict."""
    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}

    # Extract body
    body = ""
    payload = msg.get("payload", {})
    if payload.get("body", {}).get("data"):
        body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    elif payload.get("parts"):
        for part in payload["parts"]:
            if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
                break

    # Extract attachments
    attachments = []
    for part in payload.get("parts", []):
        if part.get("filename"):
            attachments.append({
                "name": part["filename"],
                "type": part.get("mimeType", "unknown"),
                "size": int(part.get("body", {}).get("size", 0)),
            })

    # Parse date
    internal_date = msg.get("internalDate")
    received_at = None
    if internal_date:
        received_at = datetime.fromtimestamp(int(internal_date) / 1000, tz=timezone.utc).isoformat()

    return {
        "message_id": msg["id"],
        "thread_id": msg.get("threadId"),
        "sender": headers.get("from", "unknown"),
        "to": headers.get("to", ""),
        "subject": headers.get("subject", "(no subject)"),
        "body": body[:2000],
        "snippet": msg.get("snippet", ""),
        "attachments": attachments,
        "received_at": received_at,
        "label_ids": msg.get("labelIds", []),
    }


async def send_email(
    account,
    client_id: str,
    client_secret: str,
    to: str,
    subject: str,
    body: str,
    thread_id: Optional[str] = None,
    in_reply_to: Optional[str] = None,
) -> dict:
    """Send an email via Gmail API. Adds 'Re:' only when replying to a thread."""
    token = await _ensure_valid_token(account, client_id, client_secret)

    # Build email
    message = MIMEText(body)
    message["to"] = to

    # Only add "Re:" when it's actually a reply (has thread context)
    if in_reply_to or thread_id:
        message["subject"] = f"Re: {subject}" if not subject.startswith("Re:") else subject
    else:
        message["subject"] = subject

    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
        message["References"] = in_reply_to

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    payload = {"raw": raw}
    if thread_id:
        payload["threadId"] = thread_id

    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.post(
            f"{GMAIL_API_BASE}/users/me/messages/send",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        res.raise_for_status()
        return res.json()


# Backward-compatible alias
send_reply = send_email
