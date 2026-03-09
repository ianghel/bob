"""Tests for the agent endpoint and tool execution."""

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock, patch

from api.main import app
from core.agent.orchestrator import AgentRun, AgentRunStatus, ToolCall
from datetime import datetime, timezone

API_KEY = "dev-secret-key-change-in-prod"
HEADERS = {"X-API-Key": API_KEY}


def make_mock_run(
    task: str = "What is 6 * 7?",
    status: AgentRunStatus = AgentRunStatus.COMPLETED,
    output: str = "6 * 7 = 42",
    tool_calls: list | None = None,
) -> AgentRun:
    """Helper to build a mock AgentRun."""
    run = AgentRun(task=task)
    run.status = status
    run.output = output
    run.started_at = datetime.now(timezone.utc)
    run.completed_at = datetime.now(timezone.utc)
    run.duration_seconds = 1.5
    if tool_calls:
        run.tool_calls = tool_calls
    return run


@pytest.fixture
async def client():
    """Async test client for the FastAPI app."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_agent_run_returns_completed_response(client):
    """Running an agent task should return a completed run response."""
    mock_run = make_mock_run(
        task="What is 6 * 7?",
        output="The answer is 42.",
    )

    with patch("api.dependencies.get_agent_orchestrator") as mock_get_orch:
        mock_orch = MagicMock()
        mock_orch.run = AsyncMock(return_value=mock_run)
        mock_get_orch.return_value = mock_orch

        response = await client.post(
            "/api/v1/agent/run",
            json={"task": "What is 6 * 7?"},
            headers=HEADERS,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert "output" in data
    assert data["output"] == "The answer is 42."
    assert "run_id" in data
    assert "tool_calls" in data


@pytest.mark.asyncio
async def test_agent_run_with_calculator_tool(client):
    """Agent run should record calculator tool calls."""
    calculator_tool_call = ToolCall(
        tool_name="calculator",
        input={"expression": "6 * 7"},
        output="42",
        duration_ms=1.5,
    )
    mock_run = make_mock_run(
        task="Calculate 6 * 7",
        output="6 * 7 = 42",
        tool_calls=[calculator_tool_call],
    )

    with patch("api.dependencies.get_agent_orchestrator") as mock_get_orch:
        mock_orch = MagicMock()
        mock_orch.run = AsyncMock(return_value=mock_run)
        mock_get_orch.return_value = mock_orch

        response = await client.post(
            "/api/v1/agent/run",
            json={"task": "Calculate 6 * 7"},
            headers=HEADERS,
        )

    assert response.status_code == 200
    data = response.json()
    tool_calls = data["tool_calls"]
    assert len(tool_calls) >= 1
    # Verify the calculator tool was called
    calc_calls = [tc for tc in tool_calls if tc["tool_name"] == "calculator"]
    assert len(calc_calls) == 1
    assert calc_calls[0]["output"] == "42"


@pytest.mark.asyncio
async def test_get_run_status(client):
    """Status endpoint should return the run details by run_id."""
    mock_run = make_mock_run()
    run_id = mock_run.run_id

    with patch("api.dependencies.get_agent_orchestrator") as mock_get_orch:
        mock_orch = MagicMock()
        mock_orch.get_run = MagicMock(return_value=mock_run)
        mock_get_orch.return_value = mock_orch

        response = await client.get(
            f"/api/v1/agent/{run_id}/status",
            headers=HEADERS,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["run_id"] == run_id
    assert data["status"] == "completed"


@pytest.mark.asyncio
async def test_get_run_status_404(client):
    """Status endpoint should return 404 for an unknown run_id."""
    with patch("api.dependencies.get_agent_orchestrator") as mock_get_orch:
        mock_orch = MagicMock()
        mock_orch.get_run = MagicMock(return_value=None)
        mock_get_orch.return_value = mock_orch

        response = await client.get(
            "/api/v1/agent/nonexistent-run-id/status",
            headers=HEADERS,
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_agent_requires_api_key(client):
    """Agent endpoint should reject requests without a valid API key."""
    response = await client.post(
        "/api/v1/agent/run",
        json={"task": "test"},
        headers={"X-API-Key": "bad-key"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_agent_run_returns_duration(client):
    """Agent run response should include timing information."""
    mock_run = make_mock_run()

    with patch("api.dependencies.get_agent_orchestrator") as mock_get_orch:
        mock_orch = MagicMock()
        mock_orch.run = AsyncMock(return_value=mock_run)
        mock_get_orch.return_value = mock_orch

        response = await client.post(
            "/api/v1/agent/run",
            json={"task": "What is the time?"},
            headers=HEADERS,
        )

    data = response.json()
    assert data["duration_seconds"] is not None
    assert data["started_at"] is not None


# ---------------------------------------------------------------------------
# Unit tests for the calculator tool
# ---------------------------------------------------------------------------


def test_calculator_basic_arithmetic():
    """Calculator tool should handle basic arithmetic correctly."""
    from core.agent.tools import calculator

    assert calculator("2 + 3") == "5"
    assert calculator("10 - 4") == "6"
    assert calculator("6 * 7") == "42"
    assert calculator("15 / 3") == "5"


def test_calculator_math_functions():
    """Calculator tool should support math functions."""
    from core.agent.tools import calculator

    assert calculator("sqrt(16)") == "4"
    assert calculator("abs(-5)") == "5"
    assert calculator("round(3.7)") == "4"


def test_calculator_division_by_zero():
    """Calculator tool should handle division by zero gracefully."""
    from core.agent.tools import calculator

    result = calculator("1 / 0")
    assert "Error" in result


def test_calculator_invalid_expression():
    """Calculator tool should reject invalid expressions safely."""
    from core.agent.tools import calculator

    result = calculator("import os")
    assert "Error" in result


def test_get_current_time_format():
    """get_current_time should return a valid ISO 8601 timestamp."""
    from core.agent.tools import get_current_time
    from datetime import datetime

    result = get_current_time()
    # Should parse as a valid datetime
    dt = datetime.fromisoformat(result)
    assert dt.tzinfo is not None  # UTC-aware
