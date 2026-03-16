"""Background email sync — fetches unread emails for all active accounts every 10 minutes."""

import asyncio
import json
import logging
from datetime import datetime, timezone

from core.config import get_settings
from core.database.engine import async_session
from core.database.models import EmailAccount, EmailDigest
from core.email.gmail import fetch_unread_emails, fetch_sent_emails
from core.llm.base import Message
from sqlalchemy import select

logger = logging.getLogger(__name__)

SYNC_INTERVAL_SECONDS = 10 * 60  # 10 minutes

TRIAGE_PROMPT = """You are an email assistant. Analyze this email and respond ONLY with JSON (no markdown, no backticks):

From: {sender}
Subject: {subject}
Body: {body}

JSON format:
{{"urgency": "low|medium|high", "category": "invoice|meeting|question|newsletter|notification|personal|spam|other", "action": "one short sentence about what to do", "reply_draft": "1-2 sentence suggested reply, or null if no reply needed"}}"""


async def _sync_all_accounts():
    """Sync emails for all active accounts."""
    settings = get_settings()

    if not settings.google_client_id:
        return

    # Build LLM provider
    from core.llm.local import LocalProvider

    llm = LocalProvider(
        base_url=settings.local_model_base_url,
        model_name=settings.local_model_name,
        api_key=settings.local_model_api_key,
    )

    async with async_session() as db:
        result = await db.execute(
            select(EmailAccount).where(EmailAccount.is_active == True)
        )
        accounts = result.scalars().all()

        if not accounts:
            return

        for account in accounts:
            try:
                raw_emails = await fetch_unread_emails(
                    account=account,
                    client_id=settings.google_client_id,
                    client_secret=settings.google_client_secret,
                    max_results=20,
                )
                await db.commit()  # save refreshed token

                new_count = 0
                for email_data in raw_emails:
                    existing = await db.execute(
                        select(EmailDigest).where(
                            EmailDigest.message_id == email_data["message_id"]
                        )
                    )
                    if existing.scalar_one_or_none():
                        continue

                    triage = await _triage(llm, email_data)

                    received = None
                    if email_data.get("received_at"):
                        try:
                            received = datetime.fromisoformat(
                                email_data["received_at"].replace("Z", "+00:00")
                            )
                        except ValueError:
                            pass

                    digest = EmailDigest(
                        tenant_id=account.tenant_id,
                        user_id=account.user_id,
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
                    new_count += 1

                # --- Also sync SENT emails ---
                sent_emails = await fetch_sent_emails(
                    account=account,
                    client_id=settings.google_client_id,
                    client_secret=settings.google_client_secret,
                    max_results=20,
                )

                sent_count = 0
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
                        tenant_id=account.tenant_id,
                        user_id=account.user_id,
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
                    sent_count += 1

                account.last_sync_at = datetime.now(timezone.utc)
                await db.commit()

                if new_count or sent_count:
                    logger.info(
                        "Background sync: %d new inbox + %d sent for %s",
                        new_count,
                        sent_count,
                        account.email_address,
                    )

            except Exception as e:
                logger.error(
                    "Background sync failed for %s: %s",
                    account.email_address,
                    e,
                )


async def _triage(llm, email_data: dict) -> dict:
    """LLM triage for a single email."""
    body_for_llm = email_data.get("body", "")[:1500] or "(empty)"
    prompt = TRIAGE_PROMPT.format(
        sender=email_data.get("sender", "unknown"),
        subject=email_data.get("subject", ""),
        body=body_for_llm,
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
        logger.warning("Background triage failed: %s", e)
        return {
            "urgency": "medium",
            "category": "other",
            "action": "Review manually",
            "reply_draft": None,
        }


async def _sync_loop():
    """Run sync every SYNC_INTERVAL_SECONDS."""
    # Wait 30 seconds after startup before first sync
    await asyncio.sleep(30)
    while True:
        try:
            logger.info("Background email sync starting...")
            await _sync_all_accounts()
            logger.info("Background email sync complete")
        except Exception as e:
            logger.error("Background email sync error: %s", e)
        await asyncio.sleep(SYNC_INTERVAL_SECONDS)


def start_email_sync_task() -> asyncio.Task:
    """Start the background sync loop as an asyncio task."""
    return asyncio.create_task(_sync_loop())
