"""Tests for RAG ingestion and querying."""

import io
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock, patch

from api.main import app
from core.rag.ingestion import IngestionResult
from core.rag.pipeline import RAGResult

API_KEY = "dev-secret-key-change-in-prod"
HEADERS = {"X-API-Key": API_KEY}

SAMPLE_MARKDOWN = b"""# Test Document

This is a test document about Python programming.

Python is a high-level, general-purpose programming language. It emphasizes
code readability and simplicity. Python supports multiple programming paradigms,
including procedural, object-oriented, and functional programming.
"""


@pytest.fixture
async def client():
    """Async test client for the FastAPI app."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
def mock_ingestion_result():
    """Sample IngestionResult fixture."""
    result = IngestionResult(
        document_id="test-doc-id-123",
        filename="test.md",
        chunks=3,
        format="markdown",
    )
    return result


@pytest.fixture
def mock_rag_result():
    """Sample RAGResult fixture."""
    return RAGResult(
        answer="Python is a high-level programming language known for readability.",
        sources=[
            {
                "document_id": "test-doc-id-123",
                "source": "test.md",
                "format": "markdown",
                "excerpt": "Python is a high-level, general-purpose programming language...",
            }
        ],
        query="What is Python?",
    )


@pytest.mark.asyncio
async def test_ingest_document(client, mock_ingestion_result):
    """Uploading a markdown file should return 201 with ingestion stats."""
    with patch("api.dependencies.get_ingestion_pipeline") as mock_get_pipeline:
        mock_pipeline = MagicMock()
        mock_pipeline.ingest_bytes = AsyncMock(return_value=mock_ingestion_result)
        mock_get_pipeline.return_value = mock_pipeline

        response = await client.post(
            "/api/v1/rag/ingest",
            files={"file": ("test.md", io.BytesIO(SAMPLE_MARKDOWN), "text/markdown")},
            headers=HEADERS,
        )

    assert response.status_code == 201
    data = response.json()
    assert data["document_id"] == "test-doc-id-123"
    assert data["filename"] == "test.md"
    assert data["chunks"] == 3
    assert data["format"] == "markdown"


@pytest.mark.asyncio
async def test_ingest_unsupported_format(client):
    """Uploading an unsupported file format should return 400."""
    response = await client.post(
        "/api/v1/rag/ingest",
        files={"file": ("image.png", io.BytesIO(b"fake png data"), "image/png")},
        headers=HEADERS,
    )
    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]


@pytest.mark.asyncio
async def test_rag_query_returns_answer_with_sources(client, mock_rag_result):
    """RAG query should return answer and at least one source."""
    with patch("api.dependencies.get_rag_pipeline") as mock_get_rag:
        mock_pipeline = MagicMock()
        mock_pipeline.query = AsyncMock(return_value=mock_rag_result)
        mock_get_rag.return_value = mock_pipeline

        response = await client.post(
            "/api/v1/rag/query",
            json={"query": "What is Python?", "k": 4},
            headers=HEADERS,
        )

    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert len(data["answer"]) > 0
    assert "sources" in data
    assert len(data["sources"]) >= 1
    # Verify source structure
    source = data["sources"][0]
    assert "document_id" in source
    assert "source" in source
    assert "format" in source
    assert "excerpt" in source


@pytest.mark.asyncio
async def test_rag_query_sources_match_ingested_document(client, mock_rag_result):
    """RAG query sources should reference the ingested document."""
    with patch("api.dependencies.get_rag_pipeline") as mock_get_rag:
        mock_pipeline = MagicMock()
        mock_pipeline.query = AsyncMock(return_value=mock_rag_result)
        mock_get_rag.return_value = mock_pipeline

        response = await client.post(
            "/api/v1/rag/query",
            json={"query": "What is Python?"},
            headers=HEADERS,
        )

    assert response.status_code == 200
    data = response.json()
    sources = data["sources"]
    assert any(s["document_id"] == "test-doc-id-123" for s in sources)


@pytest.mark.asyncio
async def test_list_documents(client):
    """Document listing should return the stored documents."""
    mock_docs = [
        {
            "document_id": "doc-1",
            "source": "test.md",
            "format": "markdown",
            "chunk_count": 3,
        }
    ]
    with patch("api.dependencies.get_retriever") as mock_get_retriever:
        mock_retriever = MagicMock()
        mock_retriever.list_documents = MagicMock(return_value=mock_docs)
        mock_get_retriever.return_value = mock_retriever

        response = await client.get("/api/v1/rag/documents", headers=HEADERS)

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["documents"][0]["source"] == "test.md"


@pytest.mark.asyncio
async def test_rag_requires_api_key(client):
    """RAG query should reject requests without a valid API key."""
    response = await client.post(
        "/api/v1/rag/query",
        json={"query": "test"},
        headers={"X-API-Key": "invalid"},
    )
    assert response.status_code == 401
