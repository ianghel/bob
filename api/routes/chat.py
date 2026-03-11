"""Chat endpoint with conversation memory, SSE streaming, RAG, and web search."""

import json
import logging
import uuid
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.dependencies import (
    CurrentTenantDep,
    CurrentUserDep,
    DBSessionDep,
    IngestionDep,
    LLMDep,
    RetrieverDep,
)
from core.chat.web_tools import TOOL_SCHEMAS, execute_tool
from core.config import get_settings
from core.llm.base import Message, MessageRole
from core.llm.local import LocalProvider
from core.memory.context_manager import ContextManager
from core.memory.conversation import ConversationMemory, conversation_to_text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

_memory = ConversationMemory()
_context_manager = ContextManager()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    """Request body for the chat endpoint."""

    message: str = Field(..., description="User message", min_length=1, max_length=32_000)
    session_id: Optional[str] = Field(
        None, description="Session ID for conversation continuity; generated if omitted"
    )
    stream: bool = Field(False, description="If true, response is streamed via SSE")
    system_prompt: Optional[str] = Field(
        None, description="Override the default system prompt for this request"
    )
    max_tokens: int = Field(4096, ge=1, le=8192)
    temperature: float = Field(0.7, ge=0.0, le=1.0)
    use_knowledge: bool = Field(True, description="Query RAG knowledge base for context")
    knowledge_k: int = Field(4, ge=1, le=20, description="Number of RAG chunks to retrieve")
    use_web_search: bool = Field(True, description="Enable web search tools (search, products, fetch)")


class ChatResponse(BaseModel):
    """Response body from the chat endpoint."""

    session_id: str
    message_id: str
    content: str
    model: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    knowledge_used: bool = False
    knowledge_sources: Optional[list[str]] = None
    web_search_used: bool = False
    tools_used: Optional[list[str]] = None


class SessionSummary(BaseModel):
    session_id: str
    title: Optional[str] = None
    created_at: str
    updated_at: str
    is_expired: bool = False


class SessionListResponse(BaseModel):
    sessions: list[SessionSummary]
    total: int


class SessionHistoryResponse(BaseModel):
    """Response body for session history endpoint."""

    session_id: str
    turns: list[dict]
    total_turns: int


class ArchiveResponse(BaseModel):
    session_id: str
    document_id: str
    chunks: int
    message: str


class CleanupResponse(BaseModel):
    expired_count: int
    message: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/", response_model=ChatResponse, summary="Send a chat message")
async def chat(
    request: ChatRequest,
    db: DBSessionDep,
    llm: LLMDep,
    user: CurrentUserDep,
    tenant: CurrentTenantDep,
    retriever: RetrieverDep,
) -> ChatResponse:
    """Send a message and receive an AI response.

    Maintains conversation history across requests using the session_id.
    Supports optional Server-Sent Events streaming via the `stream` flag.
    When use_knowledge is true, queries the RAG knowledge base for context.
    """
    session = await _memory.get_or_create_session(
        db=db,
        tenant_id=tenant.id,
        user_id=user.id,
        session_id=request.session_id,
    )
    session_id = session.id

    # --- Session guards: expiration & turn limit --------------------------
    if await _memory.check_session_expired(session, db):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Session has expired due to inactivity. Please start a new session.",
        )
    if _memory.check_turn_limit(session):
        _settings = get_settings()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Session has reached the maximum of "
                f"{_settings.max_turns_per_session} turns. "
                f"Please start a new session."
            ),
        )

    _settings = get_settings()
    system_prompt = request.system_prompt or _settings.system_prompt

    # Optionally augment with RAG context
    knowledge_sources: list[str] | None = None
    if request.use_knowledge:
        try:
            rag_docs = await retriever.similarity_search(
                query=request.message,
                k=request.knowledge_k,
                tenant_id=tenant.id,
            )
            if rag_docs:
                knowledge_sources = []
                context_parts = []
                for i, doc in enumerate(rag_docs, 1):
                    source = doc.metadata.get("source", "unknown")
                    knowledge_sources.append(source)
                    context_parts.append(f"[Source {i}: {source}]\n{doc.page_content}")
                context_text = "\n\n".join(context_parts)
                system_prompt += (
                    f"\n\nRelevant context from your knowledge base:\n{context_text}\n\n"
                    "Use the above context to inform your response when relevant. "
                    "If the context doesn't help answer the question, rely on your general knowledge."
                )
        except Exception as e:
            logger.warning("RAG lookup failed, continuing without context: %s", e)

    # Build token-budget-aware message history for the LLM
    messages = await _context_manager.prepare_messages(
        turns=session.turns,
        current_user_message=request.message,
        system_prompt=system_prompt,
        llm=llm,
        db=db,
        conversation=session,
    )

    if request.stream:
        return StreamingResponse(
            _stream_chat(
                messages=messages,
                llm=llm,
                db=db,
                session_id=session_id,
                user_message=request.message,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                knowledge_used=request.use_knowledge and knowledge_sources is not None,
                knowledge_sources=knowledge_sources,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Session-ID": session_id,
            },
        )

    # Non-streaming response — with optional tool calling
    _settings2 = get_settings()
    use_tools = request.use_web_search and _settings2.web_search_enabled and isinstance(llm, LocalProvider)

    try:
        if use_tools:
            response = await llm.chat_with_tools(
                messages=messages,
                tools=TOOL_SCHEMAS,
                tool_executor=execute_tool,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
            )
        else:
            response = await llm.chat(
                messages=messages,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
            )
    except Exception as e:
        logger.error("LLM chat error for session %s: %s", session_id, e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM provider error: {e}",
        )

    tools_used_names = [t["name"] for t in response.tools_used] if response.tools_used else None
    web_search_used = bool(response.tools_used)

    await _memory.save_turn(
        db=db,
        session_id=session_id,
        user_message=request.message,
        assistant_message=response.content,
    )
    await db.commit()

    return ChatResponse(
        session_id=session_id,
        message_id=str(uuid.uuid4()),
        content=response.content,
        model=response.model,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        knowledge_used=request.use_knowledge and knowledge_sources is not None,
        knowledge_sources=knowledge_sources,
        web_search_used=web_search_used,
        tools_used=tools_used_names,
    )


async def _stream_chat(
    messages: list[Message],
    llm,
    db,
    session_id: str,
    user_message: str,
    max_tokens: int,
    temperature: float,
    knowledge_used: bool = False,
    knowledge_sources: list[str] | None = None,
):
    """Async generator producing SSE-formatted chunks."""
    full_response = []
    try:
        async for chunk in llm.stream(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        ):
            full_response.append(chunk)
            data = json.dumps({"chunk": chunk, "session_id": session_id})
            yield f"data: {data}\n\n"

        # Save completed turn to memory
        complete_text = "".join(full_response)
        await _memory.save_turn(
            db=db,
            session_id=session_id,
            user_message=user_message,
            assistant_message=complete_text,
        )
        await db.commit()

        yield f"data: {json.dumps({'done': True, 'session_id': session_id, 'knowledge_used': knowledge_used, 'knowledge_sources': knowledge_sources})}\n\n"

    except Exception as e:
        logger.error("Stream error for session %s: %s", session_id, e)
        yield f"data: {json.dumps({'error': str(e)})}\n\n"


# ---------------------------------------------------------------------------
# File upload in chat
# ---------------------------------------------------------------------------

_ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md", ".docx"}
_MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB


class ChatUploadResponse(BaseModel):
    session_id: str
    message_id: str
    content: str
    document_id: str
    filename: str
    chunks: int


@router.post("/upload", response_model=ChatUploadResponse, summary="Upload file to chat")
async def chat_upload(
    db: DBSessionDep,
    llm: LLMDep,
    user: CurrentUserDep,
    tenant: CurrentTenantDep,
    retriever: RetrieverDep,
    ingestion: IngestionDep,
    file: UploadFile = File(...),
    message: str = Form(""),
    session_id: Optional[str] = Form(None),
) -> ChatUploadResponse:
    """Upload a file in chat — auto-ingests into knowledge base and responds about content."""
    # Validate extension
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type: {suffix}. Allowed: {', '.join(_ALLOWED_EXTENSIONS)}",
        )

    # Read and validate size
    file_bytes = await file.read()
    if len(file_bytes) > _MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size: {_MAX_UPLOAD_SIZE // (1024*1024)} MB",
        )

    # Ingest into knowledge base
    ingest_result = await ingestion.ingest_bytes(
        data=file_bytes,
        filename=file.filename or "upload",
        tenant_id=tenant.id,
        metadata={"uploaded_by": user.id, "source": "chat-upload"},
    )

    # Get or create session
    session = await _memory.get_or_create_session(
        db=db, tenant_id=tenant.id, user_id=user.id, session_id=session_id,
    )

    # Retrieve context from the freshly ingested document
    rag_docs = await retriever.similarity_search(
        query=message or f"Content of {file.filename}",
        k=6,
        tenant_id=tenant.id,
    )
    context_parts = []
    for i, doc in enumerate(rag_docs, 1):
        context_parts.append(f"[Chunk {i}]\n{doc.page_content}")
    context_text = "\n\n".join(context_parts)

    # Ask LLM about the file
    user_msg = (
        f"The user uploaded a file: {file.filename} "
        f"({len(file_bytes)} bytes, {ingest_result.chunks} chunks ingested). "
        f"{message}" if message else
        f"The user uploaded a file: {file.filename} "
        f"({len(file_bytes)} bytes, {ingest_result.chunks} chunks ingested). "
        f"Summarize what this file contains."
    )
    _settings = get_settings()
    system_prompt = (
        f"{_settings.system_prompt}\n\n"
        f"File content from {file.filename}:\n{context_text}\n\n"
        "Use the file content above to answer the user's question about the file."
    )

    messages = [
        Message(role=MessageRole.SYSTEM, content=system_prompt),
        Message(role=MessageRole.USER, content=user_msg),
    ]

    try:
        response = await llm.chat(messages=messages, max_tokens=4096, temperature=0.5)
    except Exception as e:
        logger.error("LLM error during upload chat: %s", e)
        response_content = (
            f"File {file.filename} uploaded and ingested into the knowledge base "
            f"({ingest_result.chunks} chunks). However, I could not generate a summary: {e}"
        )
    else:
        response_content = response.content

    await _memory.save_turn(
        db=db, session_id=session.id,
        user_message=f"[Uploaded: {file.filename}] {message}",
        assistant_message=response_content,
    )
    await db.commit()

    return ChatUploadResponse(
        session_id=session.id,
        message_id=str(uuid.uuid4()),
        content=response_content,
        document_id=ingest_result.document_id,
        filename=file.filename or "upload",
        chunks=ingest_result.chunks,
    )


# ---------------------------------------------------------------------------
# Fetch URL endpoint
# ---------------------------------------------------------------------------


class FetchUrlRequest(BaseModel):
    url: str = Field(..., description="URL to fetch")
    session_id: Optional[str] = Field(None, description="Session ID")


class FetchUrlResponse(BaseModel):
    session_id: str
    url: str
    content_preview: str
    document_id: str
    chunks: int


@router.post("/fetch-url", response_model=FetchUrlResponse, summary="Fetch URL and ingest")
async def fetch_url(
    request: FetchUrlRequest,
    db: DBSessionDep,
    user: CurrentUserDep,
    tenant: CurrentTenantDep,
    ingestion: IngestionDep,
) -> FetchUrlResponse:
    """Fetch content from a URL, ingest into knowledge base, return preview."""
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                request.url,
                headers={"User-Agent": "Mozilla/5.0 (Bob-Agent)"},
            )
            resp.raise_for_status()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to fetch URL: {e}",
        )

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    clean_text = "\n".join(lines)

    # Ingest into knowledge base
    ingest_result = await ingestion.ingest_text(
        text=clean_text,
        source_name=request.url,
        metadata={
            "fetched_by": user.id,
            "source_type": "web-fetch",
            "url": request.url,
        },
        tenant_id=tenant.id,
    )

    # Get or create session for tracking
    session = await _memory.get_or_create_session(
        db=db, tenant_id=tenant.id, user_id=user.id, session_id=request.session_id,
    )

    await _memory.save_turn(
        db=db, session_id=session.id,
        user_message=f"[Fetched URL: {request.url}]",
        assistant_message=f"Fetched and ingested {len(clean_text)} characters from {request.url} ({ingest_result.chunks} chunks).",
    )
    await db.commit()

    preview = clean_text[:2000] + ("..." if len(clean_text) > 2000 else "")

    return FetchUrlResponse(
        session_id=session.id,
        url=request.url,
        content_preview=preview,
        document_id=ingest_result.document_id,
        chunks=ingest_result.chunks,
    )


# NOTE: /sessions MUST come before /{session_id}/* routes to avoid
# FastAPI treating "sessions" as a path parameter.

@router.get("/sessions", response_model=SessionListResponse, summary="List conversation sessions")
async def list_sessions(
    db: DBSessionDep,
    user: CurrentUserDep,
    tenant: CurrentTenantDep,
    limit: int = Query(20, ge=1, le=100, description="Max sessions to return"),
    offset: int = Query(0, ge=0, description="Number of sessions to skip"),
) -> SessionListResponse:
    """List conversation sessions for the current user (paginated)."""
    conversations = await _memory.list_sessions(db=db, tenant_id=tenant.id, user_id=user.id)
    page = conversations[offset : offset + limit]
    return SessionListResponse(
        sessions=[
            SessionSummary(
                session_id=c.id,
                title=c.title,
                created_at=c.created_at.isoformat() if c.created_at else "",
                updated_at=c.updated_at.isoformat() if c.updated_at else "",
                is_expired=c.is_expired,
            )
            for c in page
        ],
        total=len(conversations),
    )


@router.post(
    "/cleanup-expired",
    response_model=CleanupResponse,
    summary="Mark expired sessions",
)
async def cleanup_expired_sessions(
    db: DBSessionDep,
    user: CurrentUserDep,
    tenant: CurrentTenantDep,
) -> CleanupResponse:
    """Batch-mark all sessions inactive longer than the configured expiry period."""
    count = await _memory.expire_stale_sessions(db=db, tenant_id=tenant.id)
    await db.commit()
    return CleanupResponse(
        expired_count=count,
        message=f"Marked {count} session(s) as expired.",
    )


@router.get(
    "/{session_id}/history",
    response_model=SessionHistoryResponse,
    summary="Get conversation history",
)
async def get_history(
    session_id: str,
    db: DBSessionDep,
    user: CurrentUserDep,
    tenant: CurrentTenantDep,
) -> SessionHistoryResponse:
    """Retrieve full conversation history for a session."""
    session = await _memory.get_session(db=db, tenant_id=tenant.id, session_id=session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found",
        )

    turns = [
        {
            "turn_id": turn.id,
            "user": turn.user_message,
            "assistant": turn.assistant_message,
            "created_at": turn.created_at.isoformat() if turn.created_at else None,
        }
        for turn in session.turns
    ]

    return SessionHistoryResponse(
        session_id=session_id,
        turns=turns,
        total_turns=len(turns),
    )


@router.post(
    "/{session_id}/archive",
    response_model=ArchiveResponse,
    summary="Archive conversation to knowledge base",
)
async def archive_session(
    session_id: str,
    db: DBSessionDep,
    user: CurrentUserDep,
    tenant: CurrentTenantDep,
    ingestion: IngestionDep,
) -> ArchiveResponse:
    """Save a conversation to the RAG knowledge base for future retrieval."""
    session = await _memory.get_session(db=db, tenant_id=tenant.id, session_id=session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found",
        )

    if not session.turns:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Session has no messages to archive",
        )

    text = conversation_to_text(session)
    result = await ingestion.ingest_text(
        text=text,
        source_name=f"chat:{session_id}",
        document_id=session_id,
        metadata={
            "user_id": user.id,
            "session_id": session_id,
            "document_type": "conversation",
        },
        tenant_id=tenant.id,
    )

    return ArchiveResponse(
        session_id=session_id,
        document_id=result.document_id,
        chunks=result.chunks,
        message=f"Archived {len(session.turns)} turns as {result.chunks} searchable chunks",
    )


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear a session",
)
async def delete_session(
    session_id: str,
    db: DBSessionDep,
    user: CurrentUserDep,
    tenant: CurrentTenantDep,
) -> None:
    """Delete a conversation session and all its history."""
    deleted = await _memory.delete_session(db=db, tenant_id=tenant.id, session_id=session_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found",
        )
    await db.commit()
