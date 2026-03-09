"""Agent endpoints for running Strands agent tasks."""

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from api.dependencies import AgentDep, CurrentTenantDep, CurrentUserDep, DBSessionDep
from core.agent.orchestrator import AgentRun, AgentRunStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class AgentRunRequest(BaseModel):
    """Request body for running an agent task."""

    task: str = Field(
        ...,
        description="Natural language task for the agent to execute",
        min_length=1,
        max_length=16_000,
    )
    run_id: Optional[str] = Field(
        None, description="Pre-assigned run ID; generated if omitted"
    )


class ToolCallResponse(BaseModel):
    """A tool invocation record in the run response."""

    tool_name: str
    input: dict[str, Any]
    output: str
    duration_ms: float


class AgentRunResponse(BaseModel):
    """Response body for an agent run."""

    run_id: str
    task: str
    status: AgentRunStatus
    output: Optional[str] = None
    steps: list[str]
    tool_calls: list[ToolCallResponse]
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_seconds: Optional[float] = None


class AgentRunListResponse(BaseModel):
    """Response listing recent agent runs."""

    runs: list[AgentRunResponse]
    total: int


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _run_to_response(run: AgentRun) -> AgentRunResponse:
    """Convert an AgentRun domain object to the API response model."""
    return AgentRunResponse(
        run_id=run.run_id,
        task=run.task,
        status=run.status,
        output=run.output,
        steps=run.steps,
        tool_calls=[
            ToolCallResponse(
                tool_name=tc.tool_name,
                input=tc.input,
                output=tc.output,
                duration_ms=tc.duration_ms,
            )
            for tc in run.tool_calls
        ],
        error=run.error,
        started_at=run.started_at.isoformat() if run.started_at else None,
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
        duration_seconds=run.duration_seconds,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/run",
    response_model=AgentRunResponse,
    status_code=status.HTTP_200_OK,
    summary="Run an agent task",
)
async def run_agent(
    request: AgentRunRequest,
    orchestrator: AgentDep,
    db: DBSessionDep,
    user: CurrentUserDep,
    tenant: CurrentTenantDep,
) -> AgentRunResponse:
    """Execute an agent task, scoped to the current tenant."""
    try:
        run = await orchestrator.run(
            task=request.task,
            db=db,
            tenant_id=tenant.id,
            user_id=user.id,
            run_id=request.run_id,
        )
        await db.commit()
    except Exception as e:
        logger.error("Unexpected error during agent run: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Agent execution failed: {e}",
        )

    return _run_to_response(run)


@router.get(
    "/{run_id}/status",
    response_model=AgentRunResponse,
    summary="Get agent run status",
)
async def get_run_status(
    run_id: str,
    orchestrator: AgentDep,
    db: DBSessionDep,
    user: CurrentUserDep,
    tenant: CurrentTenantDep,
) -> AgentRunResponse:
    """Retrieve the status and results of an agent run."""
    run = await orchestrator.get_run(db=db, run_id=run_id, tenant_id=tenant.id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' not found",
        )
    return _run_to_response(run)


@router.get(
    "/",
    response_model=AgentRunListResponse,
    summary="List recent agent runs",
)
async def list_runs(
    orchestrator: AgentDep,
    db: DBSessionDep,
    user: CurrentUserDep,
    tenant: CurrentTenantDep,
    limit: int = Query(20, ge=1, le=100, description="Max runs to return"),
    offset: int = Query(0, ge=0, description="Number of runs to skip"),
) -> AgentRunListResponse:
    """List the most recent agent runs for the current tenant (paginated)."""
    runs = await orchestrator.list_runs(db=db, tenant_id=tenant.id, limit=limit, offset=offset)
    return AgentRunListResponse(
        runs=[_run_to_response(r) for r in runs],
        total=len(runs),
    )
