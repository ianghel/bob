"""Per-user email sync — fetches emails on login and every 5 minutes."""

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import delete, func, select

from core.config import get_settings
from core.database.engine import async_session
from core.database.models import EmailAccount, EmailDigest
from core.email.gmail import fetch_sent_emails, fetch_unread_emails

logger = logging.getLogger(__name__)

SYNC_INTERVAL_SECONDS = 5 * 60  # 5 minutes
MAX_EMAILS_PER_USER = 50
AUTO_STOP_AFTER_SECONDS = 60 * 60  # stop loop after 1 hour of no login refresh

# Track active per-user sync loops: {user_id: asyncio.Task}
_active_loops: dict[str, asyncio.Task] = {}


async def sync_user_emails(user_id: str, tenant_id: str) -> int:
    """Fetch emails for a single user's accounts. Returns count of new emails."""
    settings = get_settings()
    if not settings.google_client_id:
        return 0

    new_total = 0

    async with async_session() as db:
        result = await db.execute(
            select(EmailAccount).where(
                EmailAccount.user_id == user_id,
                EmailAccount.is_active == True,
            )
        )
        accounts = result.scalars().all()

        if not accounts:
            return 0

        for account in accounts:
            try:
                # --- Inbox (unread) ---
                raw_emails = await fetch_unread_emails(
                    account=account,
                    client_id=settings.google_client_id,
                    client_secret=settings.google_client_secret,
                    max_results=30,
                )
                await db.commit()  # persist refreshed token

                new_count = 0
                for email_data in raw_emails:
                    existing = await db.execute(
                        select(EmailDigest.id).where(
                            EmailDigest.user_id == user_id,
                            EmailDigest.message_id == email_data["message_id"],
                        )
                    )
                    if existing.scalar_one_or_none():
                        continue

                    received = _parse_date(email_data.get("received_at"))
                    digest = EmailDigest(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        account_id=account.id,
                        message_id=email_data["message_id"],
                        source="gmail",
                        sender=email_data["sender"],
                        subject=email_data["subject"],
                        body_snippet=email_data.get("body", "")[:500],
                        attachments_json=email_data.get("attachments", []),
                        urgency="medium",
                        category="other",
                        action=None,
                        reply_draft=None,
                        status="pending",
                        received_at=received,
                    )
                    db.add(digest)
                    new_count += 1

                # --- Sent emails ---
                sent_emails = await fetch_sent_emails(
                    account=account,
                    client_id=settings.google_client_id,
                    client_secret=settings.google_client_secret,
                    max_results=20,
                )

                sent_count = 0
                for email_data in sent_emails:
                    existing = await db.execute(
                        select(EmailDigest.id).where(
                            EmailDigest.user_id == user_id,
                            EmailDigest.message_id == email_data["message_id"],
                        )
                    )
                    if existing.scalar_one_or_none():
                        continue

                    received = _parse_date(email_data.get("received_at"))
                    to_addr = email_data.get("to", "unknown")
                    digest = EmailDigest(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        account_id=account.id,
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
                new_total += new_count + sent_count

                if new_count or sent_count:
                    logger.info(
                        "Email sync: %d inbox + %d sent for %s",
                        new_count, sent_count, account.email_address,
                    )

            except Exception as e:
                logger.error("Email sync failed for %s: %s", account.email_address, e)

        # --- Trim to MAX_EMAILS_PER_USER ---
        await _trim_emails(db, user_id)

    return new_total


async def _trim_emails(db, user_id: str):
    """Keep only the newest MAX_EMAILS_PER_USER emails for a user."""
    count_result = await db.execute(
        select(func.count(EmailDigest.id)).where(EmailDigest.user_id == user_id)
    )
    total = count_result.scalar()

    if total <= MAX_EMAILS_PER_USER:
        return

    # Find the cutoff: get the id of the Nth newest email
    cutoff_result = await db.execute(
        select(EmailDigest.processed_at)
        .where(EmailDigest.user_id == user_id)
        .order_by(EmailDigest.processed_at.desc())
        .offset(MAX_EMAILS_PER_USER)
        .limit(1)
    )
    cutoff_date = cutoff_result.scalar()
    if cutoff_date is None:
        return

    deleted = await db.execute(
        delete(EmailDigest).where(
            EmailDigest.user_id == user_id,
            EmailDigest.processed_at <= cutoff_date,
        )
    )
    await db.commit()
    logger.info("Trimmed %d old emails for user %s", deleted.rowcount, user_id)


def trigger_user_sync(user_id: str, tenant_id: str):
    """Fire-and-forget: sync emails for a user and start a 5-min loop.

    Safe to call multiple times — restarts the loop timer on each login.
    """
    # Cancel existing loop if any (will restart fresh)
    existing = _active_loops.get(user_id)
    if existing and not existing.done():
        existing.cancel()

    task = asyncio.create_task(_user_sync_loop(user_id, tenant_id))
    _active_loops[user_id] = task


async def _user_sync_loop(user_id: str, tenant_id: str):
    """Sync immediately, then every 5 minutes. Auto-stops after 1 hour."""
    try:
        # Immediate first sync
        logger.info("Email sync triggered for user %s", user_id)
        await sync_user_emails(user_id, tenant_id)

        # Periodic sync every 5 minutes
        elapsed = 0
        while elapsed < AUTO_STOP_AFTER_SECONDS:
            await asyncio.sleep(SYNC_INTERVAL_SECONDS)
            elapsed += SYNC_INTERVAL_SECONDS
            logger.info("Periodic email sync for user %s", user_id)
            await sync_user_emails(user_id, tenant_id)

        logger.info("Email sync loop stopped for user %s (auto-stop after 1h)", user_id)
    except asyncio.CancelledError:
        logger.info("Email sync loop cancelled for user %s", user_id)
    except Exception as e:
        logger.error("Email sync loop error for user %s: %s", user_id, e)
    finally:
        _active_loops.pop(user_id, None)


def _parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except ValueError:
        return None
