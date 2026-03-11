"""Database-backed conversation store with tenant isolation."""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.database.models import Conversation, ConversationTurn
from core.llm.base import Message, MessageRole

logger = logging.getLogger(__name__)


def turns_to_messages(
    turns: list[ConversationTurn],
    system_prompt: Optional[str] = None,
) -> list[Message]:
    """Convert DB conversation turns to a flat list of Messages for LLM context."""
    messages: list[Message] = []
    if system_prompt:
        messages.append(Message(role=MessageRole.SYSTEM, content=system_prompt))
    for turn in turns:
        messages.append(Message(role=MessageRole.USER, content=turn.user_message))
        messages.append(Message(role=MessageRole.ASSISTANT, content=turn.assistant_message))
    return messages


class ConversationMemory:
    """Database-backed conversation store with tenant isolation.

    All operations are scoped by tenant_id to ensure data isolation
    between tenants in the shared database.
    """

    async def get_or_create_session(
        self,
        db: AsyncSession,
        tenant_id: str,
        user_id: str,
        session_id: Optional[str] = None,
    ) -> Conversation:
        """Retrieve an existing conversation or create a new one."""
        if session_id:
            stmt = (
                select(Conversation)
                .options(selectinload(Conversation.turns))
                .where(
                    Conversation.id == session_id,
                    Conversation.tenant_id == tenant_id,
                )
            )
            result = await db.execute(stmt)
            conversation = result.scalar_one_or_none()
            if conversation:
                return conversation

        new_id = session_id or str(uuid.uuid4())
        conversation = Conversation(
            id=new_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        try:
            db.add(conversation)
            await db.flush()
        except IntegrityError:
            # Race condition or stale session — conversation already exists
            await db.rollback()
            stmt = (
                select(Conversation)
                .options(selectinload(Conversation.turns))
                .where(Conversation.id == new_id)
            )
            result = await db.execute(stmt)
            conversation = result.scalar_one_or_none()
            if conversation:
                logger.debug("Recovered existing conversation: %s", new_id)
                return conversation
            # If still not found, generate a fresh ID
            new_id = str(uuid.uuid4())
            conversation = Conversation(id=new_id, tenant_id=tenant_id, user_id=user_id)
            db.add(conversation)
            await db.flush()

        # Re-fetch with eager-loaded turns to avoid lazy-load in async context
        stmt = (
            select(Conversation)
            .options(selectinload(Conversation.turns))
            .where(Conversation.id == new_id)
        )
        result = await db.execute(stmt)
        conversation = result.scalar_one()
        logger.debug("Created new conversation: %s (tenant=%s)", conversation.id, tenant_id)
        return conversation

    async def get_session(
        self,
        db: AsyncSession,
        tenant_id: str,
        session_id: str,
    ) -> Optional[Conversation]:
        """Retrieve a conversation by ID, scoped to tenant."""
        stmt = (
            select(Conversation)
            .options(selectinload(Conversation.turns))
            .where(
                Conversation.id == session_id,
                Conversation.tenant_id == tenant_id,
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def save_turn(
        self,
        db: AsyncSession,
        session_id: str,
        user_message: str,
        assistant_message: str,
    ) -> ConversationTurn:
        """Append a turn to an existing conversation."""
        turn = ConversationTurn(
            id=str(uuid.uuid4()),
            conversation_id=session_id,
            user_message=user_message,
            assistant_message=assistant_message,
        )
        db.add(turn)

        stmt = select(Conversation).where(Conversation.id == session_id)
        result = await db.execute(stmt)
        conversation = result.scalar_one_or_none()
        if conversation:
            conversation.updated_at = datetime.now(timezone.utc)
            if not conversation.title:
                conversation.title = user_message[:100]

        await db.flush()
        logger.debug("Saved turn to conversation %s", session_id)
        return turn

    async def delete_session(
        self,
        db: AsyncSession,
        tenant_id: str,
        session_id: str,
    ) -> bool:
        """Delete a conversation and all its turns (cascade)."""
        stmt = select(Conversation).where(
            Conversation.id == session_id,
            Conversation.tenant_id == tenant_id,
        )
        result = await db.execute(stmt)
        conversation = result.scalar_one_or_none()
        if not conversation:
            return False

        await db.delete(conversation)
        await db.flush()
        logger.debug("Deleted conversation: %s", session_id)
        return True

    async def list_sessions(
        self,
        db: AsyncSession,
        tenant_id: str,
        user_id: Optional[str] = None,
    ) -> list[Conversation]:
        """Return all conversations for a tenant, ordered by most recent."""
        stmt = select(Conversation).where(Conversation.tenant_id == tenant_id)
        if user_id:
            stmt = stmt.where(Conversation.user_id == user_id)
        stmt = stmt.order_by(Conversation.updated_at.desc())
        result = await db.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Session expiration & turn limits
    # ------------------------------------------------------------------

    async def check_session_expired(
        self,
        conversation: Conversation,
        db: AsyncSession,
    ) -> bool:
        """Check if a session has expired due to inactivity.

        If ``updated_at`` is older than ``SESSION_EXPIRY_HOURS`` the
        conversation is marked ``is_expired = True`` and ``True`` is returned.
        """
        from core.config import get_settings

        settings = get_settings()

        if conversation.is_expired:
            return True

        expiry_threshold = datetime.now(timezone.utc) - timedelta(
            hours=settings.session_expiry_hours,
        )
        # updated_at may be tz-naive from MySQL — normalise
        updated = conversation.updated_at.replace(tzinfo=timezone.utc)
        if updated < expiry_threshold:
            conversation.is_expired = True
            await db.flush()
            return True

        return False

    @staticmethod
    def check_turn_limit(conversation: Conversation) -> bool:
        """Return ``True`` if the conversation has reached the max turn limit."""
        from core.config import get_settings

        settings = get_settings()
        return len(conversation.turns) >= settings.max_turns_per_session

    async def expire_stale_sessions(
        self,
        db: AsyncSession,
        tenant_id: str,
    ) -> int:
        """Batch-mark all inactive sessions as expired.

        Returns the number of newly-expired sessions.
        """
        from core.config import get_settings

        settings = get_settings()
        expiry_threshold = datetime.now(timezone.utc) - timedelta(
            hours=settings.session_expiry_hours,
        )

        stmt = (
            select(Conversation)
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.is_expired.is_(False),
                Conversation.updated_at < expiry_threshold,
            )
        )
        result = await db.execute(stmt)
        stale = list(result.scalars().all())

        for conv in stale:
            conv.is_expired = True

        await db.flush()
        logger.info("Marked %d sessions as expired (tenant=%s)", len(stale), tenant_id)
        return len(stale)


def conversation_to_text(conversation: Conversation) -> str:
    """Format a conversation as searchable text for RAG ingestion."""
    lines = []
    title = conversation.title or "Untitled conversation"
    lines.append(f"Conversation: {title}")
    if conversation.created_at:
        lines.append(f"Date: {conversation.created_at.isoformat()}")
    lines.append("")

    for turn in conversation.turns:
        lines.append(f"User: {turn.user_message}")
        lines.append(f"Assistant: {turn.assistant_message}")
        lines.append("")

    return "\n".join(lines)
