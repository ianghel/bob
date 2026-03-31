"""LLM usage tracking and monthly spending limits."""

import logging
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import Settings
from core.database.models import LlmUsageLog

logger = logging.getLogger(__name__)


async def get_monthly_spend(db: AsyncSession) -> float:
    """Return total USD spent in the current calendar month."""
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    result = await db.execute(
        select(func.coalesce(func.sum(LlmUsageLog.cost_usd), 0.0)).where(
            LlmUsageLog.period == period
        )
    )
    return float(result.scalar())


async def check_usage_limit(db: AsyncSession, settings: Settings) -> None:
    """Raise HTTP 429 if the global monthly spending limit is exceeded."""
    if not settings.usage_limit_enabled:
        return
    spend = await get_monthly_spend(db)
    if spend >= settings.usage_limit_monthly_usd:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Monthly usage limit (${settings.usage_limit_monthly_usd:.2f}) reached. "
                f"Current spend: ${spend:.2f}. Resets on the 1st of next month."
            ),
        )


async def log_llm_usage(
    db: AsyncSession,
    *,
    model: str,
    call_type: str,
    input_tokens: int | None,
    output_tokens: int | None,
    settings: Settings,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> float:
    """Log an LLM call and return its computed cost in USD."""
    cost = 0.0
    if call_type == "embed":
        if input_tokens:
            cost = (input_tokens / 1_000_000) * settings.bedrock_price_embed_per_mtok
    else:
        if input_tokens:
            cost += (input_tokens / 1_000_000) * settings.bedrock_price_input_per_mtok
        if output_tokens:
            cost += (output_tokens / 1_000_000) * settings.bedrock_price_output_per_mtok

    period = datetime.now(timezone.utc).strftime("%Y-%m")
    row = LlmUsageLog(
        period=period,
        model=model,
        call_type=call_type,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    db.add(row)
    await db.flush()
    logger.info(
        "LLM usage: %s %s — %s in / %s out — $%.6f",
        call_type, model, input_tokens, output_tokens, cost,
    )
    return cost
