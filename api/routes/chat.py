"""Chat endpoint with conversation memory, SSE streaming, and RAG integration."""

import json
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
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
from core.llm.base import Message, MessageRole
from core.memory.conversation import ConversationMemory, conversation_to_text, turns_to_messages

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

_memory = ConversationMemory()


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


class SessionSummary(BaseModel):
    session_id: str
    title: Optional[str] = None
    created_at: str
    updated_at: str


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

    from core.config import get_settings
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

    # Build full message history for the LLM
    messages = turns_to_messages(session.turns, system_prompt=system_prompt)
    messages.append(Message(role=MessageRole.USER, content=request.message))

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

    # Non-streaming response
    try:
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
            )
            for c in page
        ],
        total=len(conversations),
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
