"""Tests for the chat endpoint and conversation memory."""

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch, MagicMock

from api.main import app
from core.llm.base import LLMResponse

API_KEY = "dev-secret-key-change-in-prod"
HEADERS = {"X-API-Key": API_KEY}


@pytest.fixture
def mock_llm_response():
    """A sample LLM response fixture."""
    return LLMResponse(
        content="Hello! How can I help you today?",
        model="test-model",
        input_tokens=10,
        output_tokens=20,
    )


@pytest.fixture
async def client():
    """Async test client for the FastAPI app."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_chat_returns_response(client, mock_llm_response):
    """Chat endpoint should return a valid response for a user message."""
    with patch("api.dependencies.get_llm_provider") as mock_get_llm:
        mock_provider = AsyncMock()
        mock_provider.chat = AsyncMock(return_value=mock_llm_response)
        mock_get_llm.return_value = mock_provider

        response = await client.post(
            "/api/v1/chat/",
            json={"message": "Hello!"},
            headers=HEADERS,
        )

    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert "message_id" in data
    assert "content" in data
    assert len(data["content"]) > 0


@pytest.mark.asyncio
async def test_chat_maintains_session(client, mock_llm_response):
    """Subsequent messages with the same session_id should use the same session."""
    with patch("api.dependencies.get_llm_provider") as mock_get_llm:
        mock_provider = AsyncMock()
        mock_provider.chat = AsyncMock(return_value=mock_llm_response)
        mock_get_llm.return_value = mock_provider

        # First message — captures the session_id
        r1 = await client.post(
            "/api/v1/chat/",
            json={"message": "My name is Alice."},
            headers=HEADERS,
        )
        assert r1.status_code == 200
        session_id = r1.json()["session_id"]

        # Second message — same session
        r2 = await client.post(
            "/api/v1/chat/",
            json={"message": "What is my name?", "session_id": session_id},
            headers=HEADERS,
        )
        assert r2.status_code == 200
        assert r2.json()["session_id"] == session_id


@pytest.mark.asyncio
async def test_chat_history_endpoint(client, mock_llm_response):
    """After chatting, history endpoint should return conversation turns."""
    with patch("api.dependencies.get_llm_provider") as mock_get_llm:
        mock_provider = AsyncMock()
        mock_provider.chat = AsyncMock(return_value=mock_llm_response)
        mock_get_llm.return_value = mock_provider

        r = await client.post(
            "/api/v1/chat/",
            json={"message": "Hello!"},
            headers=HEADERS,
        )
        session_id = r.json()["session_id"]

    history_r = await client.get(
        f"/api/v1/chat/{session_id}/history",
        headers=HEADERS,
    )
    assert history_r.status_code == 200
    data = history_r.json()
    assert data["session_id"] == session_id
    assert data["total_turns"] == 1
    assert data["turns"][0]["user"] == "Hello!"


@pytest.mark.asyncio
async def test_chat_history_404_for_unknown_session(client):
    """History endpoint should return 404 for a session that doesn't exist."""
    response = await client.get(
        "/api/v1/chat/nonexistent-session-id/history",
        headers=HEADERS,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_session(client, mock_llm_response):
    """Deleting a session should clear its history."""
    with patch("api.dependencies.get_llm_provider") as mock_get_llm:
        mock_provider = AsyncMock()
        mock_provider.chat = AsyncMock(return_value=mock_llm_response)
        mock_get_llm.return_value = mock_provider

        r = await client.post(
            "/api/v1/chat/",
            json={"message": "Hello!"},
            headers=HEADERS,
        )
        session_id = r.json()["session_id"]

    # Delete
    del_r = await client.delete(f"/api/v1/chat/{session_id}", headers=HEADERS)
    assert del_r.status_code == 204

    # History should now 404
    history_r = await client.get(
        f"/api/v1/chat/{session_id}/history", headers=HEADERS
    )
    assert history_r.status_code == 404


@pytest.mark.asyncio
async def test_chat_requires_api_key(client):
    """Chat endpoint should reject requests without a valid API key."""
    response = await client.post(
        "/api/v1/chat/",
        json={"message": "Hello!"},
        headers={"X-API-Key": "wrong-key"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_chat_validates_empty_message(client):
    """Chat endpoint should reject empty messages."""
    response = await client.post(
        "/api/v1/chat/",
        json={"message": ""},
        headers=HEADERS,
    )
    assert response.status_code == 422
