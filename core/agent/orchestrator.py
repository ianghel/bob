"""Strands agent orchestrator for multi-tool task execution."""

import logging
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from strands import Agent
from strands.models import Model

from core.agent.tools import calculator, get_current_time, make_rag_lookup_tool, summarize_text
from core.database.models import AgentRun as AgentRunModel

logger = logging.getLogger(__name__)


class AgentRunStatus(str, Enum):
    """Lifecycle states for an agent run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ToolCall(BaseModel):
    """Record of a single tool invocation during an agent run."""

    tool_name: str
    input: dict[str, Any]
    output: str
    duration_ms: float


class AgentRun(BaseModel):
    """Complete record of one agent execution (API-facing model)."""

    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task: str
    status: AgentRunStatus = AgentRunStatus.PENDING
    output: Optional[str] = None
    steps: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None


class AgentOrchestrator:
    """Orchestrates Strands agent execution with DB-backed run storage."""

    def __init__(
        self,
        strands_model: Model,
        rag_pipeline=None,
        system_prompt: str = "You are a helpful AI assistant with access to tools.",
    ) -> None:
        self._system_prompt = system_prompt
        self._strands_model = strands_model
        self._rag_pipeline = rag_pipeline

        self._base_tools = [calculator, get_current_time, summarize_text]

        logger.info(
            "AgentOrchestrator initialized with %d base tools + rag_lookup",
            len(self._base_tools),
        )

    def _build_agent(self, tenant_id: str | None = None) -> Agent:
        """Construct a fresh Strands Agent instance with all tools."""
        tools = list(self._base_tools)
        if self._rag_pipeline is not None:
            tools.append(make_rag_lookup_tool(self._rag_pipeline, tenant_id=tenant_id))
        return Agent(
            model=self._strands_model,
            tools=tools,
            system_prompt=self._system_prompt,
        )

    async def run(
        self,
        task: str,
        db: AsyncSession,
        tenant_id: str,
        user_id: str,
        run_id: Optional[str] = None,
    ) -> AgentRun:
        """Execute an agent task and persist the run to the database."""
        rid = run_id or str(uuid.uuid4())

        # Create DB record
        db_run = AgentRunModel(
            id=rid,
            tenant_id=tenant_id,
            user_id=user_id,
            task=task,
            status="running",
            started_at=datetime.now(timezone.utc),
            steps_json=[],
            tool_calls_json=[],
        )
        db.add(db_run)
        await db.flush()

        # Build the API-facing model
        api_run = AgentRun(run_id=rid, task=task, status=AgentRunStatus.RUNNING)
        api_run.started_at = db_run.started_at

        try:
            agent = self._build_agent(tenant_id=tenant_id)
            logger.info("Agent run %s starting: %r", rid, task[:80])

            response = agent(task)

            tool_calls_data = []
            if hasattr(response, "metrics") and response.metrics:
                tool_uses = getattr(response.metrics, "tool_uses", [])
                for tu in tool_uses:
                    tc = ToolCall(
                        tool_name=tu.get("name", "unknown"),
                        input=tu.get("input", {}),
                        output=str(tu.get("output", "")),
                        duration_ms=tu.get("duration_ms", 0.0),
                    )
                    api_run.tool_calls.append(tc)
                    tool_calls_data.append(tc.model_dump())

            output = str(response)
            now = datetime.now(timezone.utc)
            duration = (now - api_run.started_at).total_seconds() if api_run.started_at else None

            api_run.status = AgentRunStatus.COMPLETED
            api_run.output = output
            api_run.completed_at = now
            api_run.duration_seconds = duration

            db_run.status = "completed"
            db_run.output = output
            db_run.completed_at = now
            db_run.duration_seconds = duration
            db_run.tool_calls_json = tool_calls_data

            logger.info("Agent run %s completed in %.2fs", rid, duration or 0)

        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            now = datetime.now(timezone.utc)
            duration = (now - api_run.started_at).total_seconds() if api_run.started_at else None

            api_run.status = AgentRunStatus.FAILED
            api_run.error = error_msg
            api_run.completed_at = now
            api_run.duration_seconds = duration

            db_run.status = "failed"
            db_run.error = error_msg
            db_run.completed_at = now
            db_run.duration_seconds = duration

            logger.error("Agent run %s failed: %s", rid, error_msg)

        await db.flush()
        return api_run

    async def get_run(self, db: AsyncSession, run_id: str, tenant_id: str) -> Optional[AgentRun]:
        """Retrieve a run record by ID, scoped to tenant."""
        stmt = select(AgentRunModel).where(
            AgentRunModel.id == run_id,
            AgentRunModel.tenant_id == tenant_id,
        )
        result = await db.execute(stmt)
        db_run = result.scalar_one_or_none()
        if not db_run:
            return None
        return self._db_to_api(db_run)

    async def list_runs(self, db: AsyncSession, tenant_id: str, limit: int = 20) -> list[AgentRun]:
        """Return the most recent agent runs for a tenant."""
        stmt = (
            select(AgentRunModel)
            .where(AgentRunModel.tenant_id == tenant_id)
            .order_by(AgentRunModel.started_at.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        return [self._db_to_api(r) for r in result.scalars().all()]

    @staticmethod
    def _db_to_api(db_run: AgentRunModel) -> AgentRun:
        """Convert a DB AgentRun to the API-facing model."""
        tool_calls = []
        for tc_data in (db_run.tool_calls_json or []):
            tool_calls.append(ToolCall(
                tool_name=tc_data.get("tool_name", "unknown"),
                input=tc_data.get("input", {}),
                output=tc_data.get("output", ""),
                duration_ms=tc_data.get("duration_ms", 0.0),
            ))

        return AgentRun(
            run_id=db_run.id,
            task=db_run.task,
            status=AgentRunStatus(db_run.status),
            output=db_run.output,
            steps=db_run.steps_json or [],
            tool_calls=tool_calls,
            error=db_run.error,
            started_at=db_run.started_at,
            completed_at=db_run.completed_at,
            duration_seconds=db_run.duration_seconds,
        )
