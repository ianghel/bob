"""RAG endpoints: document ingestion and knowledge base querying."""

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, UploadFile, File, status
from pydantic import BaseModel, Field

from api.dependencies import (
    CurrentTenantDep,
    CurrentUserDep,
    DBSessionDep,
    IngestionDep,
    RAGDep,
    RetrieverDep,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rag", tags=["rag"])

ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md", ".docx"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class RAGQueryRequest(BaseModel):
    """Request body for querying the knowledge base."""

    query: str = Field(..., description="The question to answer", min_length=1, max_length=8_000)
    k: int = Field(4, ge=1, le=20, description="Number of context chunks to retrieve")
    session_id: Optional[str] = Field(
        None, description="Optional session ID for conversational RAG"
    )


class SourceDocument(BaseModel):
    """A source document cited in a RAG response."""

    document_id: str
    source: str
    format: str
    excerpt: str


class RAGQueryResponse(BaseModel):
    """Response from a RAG query."""

    answer: str
    query: str
    sources: list[SourceDocument]
    chunks_retrieved: int


class IngestResponse(BaseModel):
    """Response after ingesting a document."""

    document_id: str
    filename: str
    chunks: int
    format: str
    message: str


class DocumentListResponse(BaseModel):
    """Response listing all ingested documents."""

    documents: list[dict]
    total: int


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/ingest",
    response_model=IngestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest a document into the knowledge base",
)
async def ingest_document(
    tenant: CurrentTenantDep,
    user: CurrentUserDep,
    file: UploadFile = File(...),
    ingestion: IngestionDep = None,
) -> IngestResponse:
    """Upload and ingest a document scoped to the current tenant."""
    suffix = Path(file.filename or "file").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported file type: {suffix!r}. "
                f"Allowed: {sorted(ALLOWED_EXTENSIONS)}"
            ),
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large: {len(content)} bytes (max {MAX_FILE_SIZE})",
        )

    try:
        result = await ingestion.ingest_bytes(
            content=content,
            filename=file.filename or "upload",
            tenant_id=tenant.id,
        )
    except Exception as e:
        logger.error("Ingestion failed for %s: %s", file.filename, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ingestion failed: {e}",
        )

    return IngestResponse(
        document_id=result.document_id,
        filename=result.filename,
        chunks=result.chunks,
        format=result.format,
        message=f"Successfully ingested {result.chunks} chunks from {result.filename}",
    )


@router.post(
    "/query",
    response_model=RAGQueryResponse,
    summary="Query the knowledge base using RAG",
)
async def query_knowledge_base(
    request: RAGQueryRequest,
    rag: RAGDep,
    tenant: CurrentTenantDep,
    user: CurrentUserDep,
) -> RAGQueryResponse:
    """Answer a question using RAG, scoped to the current tenant's documents."""
    try:
        result = await rag.query(question=request.query, tenant_id=tenant.id)
    except Exception as e:
        logger.error("RAG query failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"RAG query failed: {e}",
        )

    sources = [
        SourceDocument(
            document_id=s["document_id"],
            source=s["source"],
            format=s["format"],
            excerpt=s["excerpt"],
        )
        for s in result.sources
    ]

    return RAGQueryResponse(
        answer=result.answer,
        query=result.query,
        sources=sources,
        chunks_retrieved=len(result.sources),
    )


@router.delete(
    "/documents/{document_id}",
    summary="Delete a document from the knowledge base",
)
async def delete_document(
    document_id: str,
    retriever: RetrieverDep,
    tenant: CurrentTenantDep,
    user: CurrentUserDep,
) -> dict:
    """Delete all chunks belonging to a document, scoped to tenant."""
    try:
        deleted = retriever.delete_document(document_id, tenant_id=tenant.id)
    except Exception as e:
        logger.error("Failed to delete document %s: %s", document_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete document: {e}",
        )

    if deleted == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id!r} not found",
        )

    return {"document_id": document_id, "chunks_deleted": deleted}


@router.get(
    "/documents",
    response_model=DocumentListResponse,
    summary="List all ingested documents",
)
async def list_documents(
    retriever: RetrieverDep,
    tenant: CurrentTenantDep,
    user: CurrentUserDep,
    limit: int = Query(50, ge=1, le=200, description="Max documents to return"),
    offset: int = Query(0, ge=0, description="Number of documents to skip"),
) -> DocumentListResponse:
    """List documents in the current tenant's knowledge base (paginated)."""
    try:
        all_documents = retriever.list_documents(tenant_id=tenant.id)
    except Exception as e:
        logger.error("Failed to list documents: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list documents: {e}",
        )
    page = all_documents[offset : offset + limit]
    return DocumentListResponse(documents=page, total=len(all_documents))
