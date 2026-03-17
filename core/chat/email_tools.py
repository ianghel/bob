"""Email tools for chat-mode tool calling.

Allows the LLM to search emails, get inbox status, and send emails
on behalf of the user — all through natural conversation.
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.database.models import Contact, EmailAccount, EmailDigest
from core.email.gmail import send_email

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OpenAI function-calling tool schemas
# ---------------------------------------------------------------------------

EMAIL_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_emails",
            "description": (
                "Search the user's email inbox. Use this when the user asks about their emails, "
                "messages, inbox, or anything email-related. Can filter by sender, subject, "
                "urgency, category, or date range."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query — matches sender, subject, or body",
                    },
                    "urgency": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                        "description": "Filter by urgency level (optional)",
                    },
                    "category": {
                        "type": "string",
                        "description": "Filter by category: invoice, meeting, question, newsletter, notification, personal, spam, other (optional)",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["pending", "sent", "skipped"],
                        "description": "Filter by status (optional, default: all)",
                    },
                    "hours": {
                        "type": "integer",
                        "description": "Only emails from the last N hours (default: 168 = 7 days)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return (default: 10)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_email_summary",
            "description": (
                "Get a quick overview of the user's email inbox — counts by status, "
                "urgency, and category. Use when the user asks 'how many emails', "
                "'what's in my inbox', or similar overview questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "hours": {
                        "type": "integer",
                        "description": "Time window in hours (default: 24 = today)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": (
                "Send an email on behalf of the user via their connected Gmail. "
                "Use this when the user explicitly asks to send, write, or reply to an email. "
                "IMPORTANT: Before sending, always call list_contacts to verify the recipient "
                "email address exists in the contact list. If the address is NOT in the contact "
                "list, warn the user that this is an unknown address and ask for explicit "
                "confirmation before sending. Never guess or hallucinate email addresses."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": "Recipient email address — must be verified against contacts",
                    },
                    "subject": {
                        "type": "string",
                        "description": "Email subject line",
                    },
                    "body": {
                        "type": "string",
                        "description": "Email body text",
                    },
                    "force": {
                        "type": "boolean",
                        "description": "Set to true to send even if address is not in contacts (user confirmed)",
                    },
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_contacts",
            "description": (
                "List the user's known email contacts. Use this to look up email addresses "
                "before sending an email — never guess addresses. Can search by name or email. "
                "Also use when the user asks 'who are my contacts', 'what email does X have', etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search by name or email address (optional — returns all if empty)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default: 50)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_contact",
            "description": (
                "Save an email address as a permanent contact. Use this when the user "
                "explicitly provides an email address in chat that they want to remember, "
                "e.g. 'email-ul lui Ion este ion@example.com'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "email": {
                        "type": "string",
                        "description": "Email address to save",
                    },
                    "name": {
                        "type": "string",
                        "description": "Contact name (optional)",
                    },
                },
                "required": ["email"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool executor factory — creates a closure with DB + user context
# ---------------------------------------------------------------------------


def make_email_tool_executor(db: AsyncSession, user_id: str, tenant_id: str):
    """Return an async tool executor closure bound to the user's DB session."""

    async def search_emails(
        query: str = "",
        urgency: str = None,
        category: str = None,
        status: str = None,
        hours: int = 168,
        limit: int = 10,
    ) -> str:
        since = datetime.now(timezone.utc) - timedelta(hours=hours)

        stmt = (
            select(EmailDigest)
            .where(
                EmailDigest.tenant_id == tenant_id,
                EmailDigest.user_id == user_id,
                EmailDigest.processed_at >= since,
            )
            .order_by(EmailDigest.received_at.desc())
            .limit(min(limit, 20))
        )

        if query:
            like = f"%{query}%"
            stmt = stmt.where(
                or_(
                    EmailDigest.sender.ilike(like),
                    EmailDigest.subject.ilike(like),
                    EmailDigest.body_snippet.ilike(like),
                )
            )
        if urgency:
            stmt = stmt.where(EmailDigest.urgency == urgency)
        if category:
            stmt = stmt.where(EmailDigest.category == category)
        if status:
            stmt = stmt.where(EmailDigest.status == status)

        result = await db.execute(stmt)
        digests = result.scalars().all()

        if not digests:
            return "No emails found matching your criteria."

        lines = []
        for d in digests:
            date_str = d.received_at.strftime("%d %b %H:%M") if d.received_at else "?"
            lines.append(
                f"- [{d.urgency.upper()}] [{d.category}] {date_str}\n"
                f"  From: {d.sender}\n"
                f"  Subject: {d.subject}\n"
                f"  Action: {d.action or 'none'}\n"
                f"  Status: {d.status}"
                + (f"\n  Reply draft: {d.reply_draft}" if d.reply_draft else "")
            )

        return f"Found {len(digests)} emails:\n\n" + "\n\n".join(lines)

    async def get_email_summary(hours: int = 24) -> str:
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        base = (
            select(EmailDigest)
            .where(
                EmailDigest.tenant_id == tenant_id,
                EmailDigest.user_id == user_id,
                EmailDigest.processed_at >= since,
            )
        )

        result = await db.execute(base)
        digests = result.scalars().all()

        if not digests:
            return f"No emails in the last {hours} hours."

        # Counts
        by_urgency: dict[str, int] = {}
        by_category: dict[str, int] = {}
        by_status: dict[str, int] = {}
        for d in digests:
            by_urgency[d.urgency] = by_urgency.get(d.urgency, 0) + 1
            by_category[d.category or "other"] = by_category.get(d.category or "other", 0) + 1
            by_status[d.status] = by_status.get(d.status, 0) + 1

        parts = [f"Email summary (last {hours}h): {len(digests)} total"]
        parts.append(f"By urgency: {', '.join(f'{k}: {v}' for k, v in by_urgency.items())}")
        parts.append(f"By category: {', '.join(f'{k}: {v}' for k, v in by_category.items())}")
        parts.append(f"By status: {', '.join(f'{k}: {v}' for k, v in by_status.items())}")

        # Top senders
        senders: dict[str, int] = {}
        for d in digests:
            senders[d.sender] = senders.get(d.sender, 0) + 1
        top = sorted(senders.items(), key=lambda x: -x[1])[:5]
        parts.append(f"Top senders: {', '.join(f'{s} ({c})' for s, c in top)}")

        return "\n".join(parts)

    async def send_email_tool(to: str, subject: str, body: str, force: bool = False) -> str:
        settings = get_settings()

        # Check if recipient is a known contact
        contact_result = await db.execute(
            select(Contact).where(
                Contact.user_id == user_id,
                Contact.email == to.lower().strip(),
            )
        )
        known_contact = contact_result.scalar_one_or_none()

        if not known_contact and not force:
            return (
                f"⚠️ ATENȚIE: Adresa '{to}' NU se află în lista ta de contacte. "
                f"Nu am găsit-o în emailurile tale anterioare. "
                f"Ești sigur că vrei să trimiți la această adresă? "
                f"Confirmă și voi trimite, sau verifică adresa."
            )

        # Get user's Gmail account
        result = await db.execute(
            select(EmailAccount).where(
                EmailAccount.user_id == user_id,
                EmailAccount.provider == "gmail",
                EmailAccount.is_active == True,
            )
        )
        account = result.scalar_one_or_none()

        if not account:
            return "Error: No Gmail account connected. Connect Gmail first in the Email tab."

        if not settings.google_client_id:
            return "Error: Google OAuth not configured."

        try:
            gmail_result = await send_email(
                account=account,
                client_id=settings.google_client_id,
                client_secret=settings.google_client_secret,
                to=to,
                subject=subject,
                body=body,
            )

            # Save sent email as a digest entry so it appears in the inbox
            now = datetime.now(timezone.utc)
            sent_digest = EmailDigest(
                tenant_id=tenant_id,
                user_id=user_id,
                message_id=gmail_result.get("id", f"sent-{now.timestamp()}"),
                source="gmail",
                sender=f"me → {to}",
                subject=subject,
                body_snippet=body[:500],
                urgency="low",
                category="sent",
                action=f"Sent to {to}",
                reply_draft=None,
                status="sent",
                received_at=now,
            )
            db.add(sent_digest)

            # Also save the recipient as a contact if not already known
            if not known_contact:
                db.add(Contact(
                    user_id=user_id,
                    tenant_id=tenant_id,
                    email=to.lower().strip(),
                    source="chat",
                ))

            await db.commit()
            return f"Email sent successfully to {to} with subject: {subject}"
        except Exception as e:
            logger.error("send_email tool failed: %s", e)
            return f"Failed to send email: {e}"

    async def list_contacts_tool(query: str = "", limit: int = 50) -> str:
        stmt = (
            select(Contact)
            .where(Contact.user_id == user_id)
            .order_by(Contact.name, Contact.email)
            .limit(min(limit, 200))
        )

        if query:
            like = f"%{query}%"
            stmt = stmt.where(
                or_(
                    Contact.email.ilike(like),
                    Contact.name.ilike(like),
                )
            )

        result = await db.execute(stmt)
        contacts = result.scalars().all()

        if not contacts:
            if query:
                return f"No contacts found matching '{query}'."
            return "No contacts yet. Contacts are automatically added when you sync emails."

        lines = []
        for c in contacts:
            name_part = f" ({c.name})" if c.name else ""
            source_part = f" [{c.source}]" if c.source != "email" else ""
            lines.append(f"- {c.email}{name_part}{source_part}")

        return f"Found {len(contacts)} contacts:\n" + "\n".join(lines)

    async def save_contact_tool(email: str, name: str = "") -> str:
        addr = email.lower().strip()
        if "@" not in addr:
            return f"Invalid email address: {email}"

        existing = await db.execute(
            select(Contact).where(
                Contact.user_id == user_id,
                Contact.email == addr,
            )
        )
        contact = existing.scalar_one_or_none()

        if contact:
            if name and not contact.name:
                contact.name = name
                await db.commit()
                return f"Updated contact {addr} with name '{name}'."
            return f"Contact {addr} already exists."

        db.add(Contact(
            user_id=user_id,
            tenant_id=tenant_id,
            email=addr,
            name=name or None,
            source="chat",
        ))
        await db.commit()
        return f"Contact saved: {addr}" + (f" ({name})" if name else "")

    # Registry
    _registry = {
        "search_emails": search_emails,
        "get_email_summary": get_email_summary,
        "send_email": send_email_tool,
        "list_contacts": list_contacts_tool,
        "save_contact": save_contact_tool,
    }

    async def execute(name: str, arguments: str | dict) -> str:
        func = _registry.get(name)
        if func is None:
            return None  # Not an email tool — let other executor handle it
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                return f"Invalid arguments for {name}: {arguments}"
        try:
            return await func(**arguments)
        except Exception as e:
            logger.error("Email tool %s error: %s", name, e)
            return f"Email tool {name} failed: {e}"

    return execute
