"""Context window manager with sliding window and auto-summarization.

Ensures the message list sent to the LLM never exceeds the configured
token budget (``CONTEXT_MAX_TOKENS``).  When the budget is exceeded the
manager keeps only the most recent *N* turns (sliding window) and,
optionally, asks the LLM to produce a cumulative summary of the older
turns so that important context is preserved.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from core.config import get_settings
from core.llm.base import Message, MessageRole

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from core.database.models import Conversation, ConversationTurn
    from core.llm.base import BaseLLMProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Token estimation helpers
# ---------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """Rough token count: 1 token ~ 4 characters."""
    return len(text) // 4


def estimate_messages_tokens(messages: list[Message]) -> int:
    """Estimate total tokens for a list of messages (incl. role overhead)."""
    total = 0
    for msg in messages:
        total += estimate_tokens(msg.content) + 4  # ~4 tokens overhead/msg
    return total


# ---------------------------------------------------------------------------
# ContextManager
# ---------------------------------------------------------------------------

class ContextManager:
    """Build a token-budget-aware message list for the LLM.

    Strategy
    --------
    1. Build the full candidate message list from all turns.
    2. Estimate total tokens.
    3. If within budget → return as-is.
    4. If over budget:
       a. Keep only the last *window_turns* turns.
       b. Summarise older turns via the LLM (if enabled).
       c. Persist the summary on ``Conversation.summary``.
       d. Return [system, summary, recent turns, current message].
    """

    def __init__(self) -> None:
        settings = get_settings()
        self.max_tokens: int = settings.context_max_tokens
        self.window_turns: int = settings.context_sliding_window_turns
        self.summary_enabled: bool = settings.context_summary_enabled

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def prepare_messages(
        self,
        turns: list[ConversationTurn],
        current_user_message: str,
        system_prompt: str,
        llm: BaseLLMProvider,
        db: AsyncSession,
        conversation: Conversation,
    ) -> list[Message]:
        """Return a list of :class:`Message` that fits the token budget.

        Parameters
        ----------
        turns:
            All existing conversation turns (ordered by ``created_at``).
        current_user_message:
            The new message from the user.
        system_prompt:
            The system prompt (may already include RAG context).
        llm:
            LLM provider — needed when summarisation is triggered.
        db:
            Async DB session — needed to persist the summary.
        conversation:
            The ``Conversation`` ORM instance.
        """
        messages = self._build_full_messages(
            turns, current_user_message, system_prompt, conversation.summary,
        )

        total_tokens = estimate_messages_tokens(messages)
        if total_tokens <= self.max_tokens:
            return messages

        # --- Over budget — apply sliding window -----------------------
        logger.info(
            "Context exceeds budget (%d > %d tokens). "
            "Applying sliding window (last %d turns).",
            total_tokens,
            self.max_tokens,
            self.window_turns,
        )

        if len(turns) <= self.window_turns:
            # All turns fit in the window but system prompt / RAG is huge.
            # Nothing more we can trim — return as-is and let the LLM
            # handle the overflow.
            return messages

        old_turns = turns[: -self.window_turns]
        recent_turns = turns[-self.window_turns :]

        # Summarise old turns if enabled
        summary_text: Optional[str] = conversation.summary
        if self.summary_enabled and old_turns:
            summary_text = await self._summarise_turns(old_turns, conversation.summary, llm)
            conversation.summary = summary_text
            await db.flush()

        # Rebuild with summary + recent turns
        result = self._build_windowed_messages(
            recent_turns, current_user_message, system_prompt, summary_text,
        )

        logger.info(
            "Context after sliding window: %d tokens (budget: %d)",
            estimate_messages_tokens(result),
            self.max_tokens,
        )
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_full_messages(
        turns: list[ConversationTurn],
        current_user_message: str,
        system_prompt: str,
        existing_summary: Optional[str],
    ) -> list[Message]:
        msgs: list[Message] = [Message(role=MessageRole.SYSTEM, content=system_prompt)]

        if existing_summary and len(turns) > 0:
            msgs.append(
                Message(
                    role=MessageRole.SYSTEM,
                    content=f"Summary of earlier conversation:\n{existing_summary}",
                )
            )

        for turn in turns:
            msgs.append(Message(role=MessageRole.USER, content=turn.user_message))
            msgs.append(Message(role=MessageRole.ASSISTANT, content=turn.assistant_message))

        msgs.append(Message(role=MessageRole.USER, content=current_user_message))
        return msgs

    @staticmethod
    def _build_windowed_messages(
        recent_turns: list[ConversationTurn],
        current_user_message: str,
        system_prompt: str,
        summary_text: Optional[str],
    ) -> list[Message]:
        msgs: list[Message] = [Message(role=MessageRole.SYSTEM, content=system_prompt)]

        if summary_text:
            msgs.append(
                Message(
                    role=MessageRole.SYSTEM,
                    content=f"Summary of earlier conversation:\n{summary_text}",
                )
            )

        for turn in recent_turns:
            msgs.append(Message(role=MessageRole.USER, content=turn.user_message))
            msgs.append(Message(role=MessageRole.ASSISTANT, content=turn.assistant_message))

        msgs.append(Message(role=MessageRole.USER, content=current_user_message))
        return msgs

    async def _summarise_turns(
        self,
        old_turns: list[ConversationTurn],
        existing_summary: Optional[str],
        llm: BaseLLMProvider,
    ) -> str:
        """Ask the LLM to produce a concise summary of older turns."""
        parts: list[str] = []
        if existing_summary:
            parts.append(f"Previous summary:\n{existing_summary}\n")

        parts.append("Conversation turns to summarise:")
        for turn in old_turns:
            parts.append(f"User: {turn.user_message}")
            parts.append(f"Assistant: {turn.assistant_message}")

        content = "\n".join(parts)

        summary_messages = [
            Message(
                role=MessageRole.SYSTEM,
                content="You summarise conversations concisely.",
            ),
            Message(
                role=MessageRole.USER,
                content=(
                    "Produce a concise summary of the conversation below. "
                    "Preserve key facts, decisions, user preferences, and any "
                    "important context. Keep the summary under 500 words.\n\n"
                    f"{content}"
                ),
            ),
        ]

        try:
            response = await llm.chat(
                messages=summary_messages,
                max_tokens=1024,
                temperature=0.3,
            )
            logger.info("Generated conversation summary (%d chars)", len(response.content))
            return response.content
        except Exception:
            logger.exception("Failed to generate conversation summary")
            return existing_summary or ""
