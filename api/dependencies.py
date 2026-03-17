"""FastAPI dependency injection providers."""

import logging
from typing import Annotated, Optional

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langchain_community.embeddings import BedrockEmbeddings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.agent.orchestrator import AgentOrchestrator
from core.auth.api_tokens import validate_api_token
from core.config import Settings, get_settings
from core.database.engine import get_db
from core.database.models import Tenant, User
from core.auth.jwt import decode_token
from core.llm.base import BaseLLMProvider
from core.llm.bedrock import BedrockProvider
from core.llm.local import LocalProvider
from core.rag.ingestion import DocumentIngestionPipeline
from core.rag.pipeline import RAGPipeline
from core.rag.retriever import ChromaRetriever

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DB session dependency
# ---------------------------------------------------------------------------

DBSessionDep = Annotated[AsyncSession, Depends(get_db)]

# ---------------------------------------------------------------------------
# Bearer token security scheme
# ---------------------------------------------------------------------------

_bearer_scheme = HTTPBearer(auto_error=False)

# ---------------------------------------------------------------------------
# JWT / API-token user authentication
# ---------------------------------------------------------------------------


async def get_current_user(
    db: DBSessionDep,
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(_bearer_scheme)] = None,
) -> User:
    """Decode a Bearer JWT or validate an API token, then load the user."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    raw_token = credentials.credentials

    # --- Path 1: Try JWT first ---
    try:
        payload = decode_token(raw_token)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

        stmt = select(User).where(User.id == user_id, User.is_active == True, User.is_approved == True)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
        return user

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")

    except jwt.InvalidTokenError:
        pass  # Not a valid JWT — fall through to API token check

    # --- Path 2: API token fallback ---
    if not raw_token.startswith("bob_"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    result = await validate_api_token(db, raw_token)
    if result is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked API token")

    user, tenant_id = result
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]

# ---------------------------------------------------------------------------
# Tenant resolution (derived from authenticated user)
# ---------------------------------------------------------------------------


async def get_current_tenant(
    db: DBSessionDep,
    user: CurrentUserDep,
) -> Tenant:
    """Resolve the tenant from the authenticated user's tenant_id."""
    stmt = select(Tenant).where(Tenant.id == user.tenant_id, Tenant.is_active == True)
    result = await db.execute(stmt)
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found or deactivated",
        )
    return tenant


CurrentTenantDep = Annotated[Tenant, Depends(get_current_tenant)]

# ---------------------------------------------------------------------------
# API key authentication (kept for admin/backward-compat use)
# ---------------------------------------------------------------------------

API_KEY_NAME = "X-API-Key"


async def verify_api_key(
    x_api_key: Annotated[Optional[str], Header(alias="X-API-Key")] = None,
    settings: Settings = Depends(get_settings),
) -> str:
    """Validate the X-API-Key header."""
    if not x_api_key or x_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return x_api_key


APIKeyDep = Annotated[str, Depends(verify_api_key)]

# ---------------------------------------------------------------------------
# Singleton instances (LLM, RAG — not tenant-scoped, shared infrastructure)
# ---------------------------------------------------------------------------

_llm_provider: Optional[BaseLLMProvider] = None
_retriever: Optional[ChromaRetriever] = None
_rag_pipeline: Optional[RAGPipeline] = None
_ingestion_pipeline: Optional[DocumentIngestionPipeline] = None
_agent_orchestrator: Optional[AgentOrchestrator] = None


def get_llm_provider() -> BaseLLMProvider:
    """Return the configured LLM provider (Bedrock or Local)."""
    global _llm_provider
    if _llm_provider is None:
        settings = get_settings()
        if settings.llm_provider == "bedrock":
            _llm_provider = BedrockProvider(
                region=settings.aws_default_region,
                chat_model_id=settings.bedrock_chat_model_id,
                embed_model_id=settings.bedrock_embed_model_id,
            )
            logger.info("Using BedrockProvider (region=%s, model=%s)", settings.aws_default_region, settings.bedrock_chat_model_id)
        else:
            _llm_provider = LocalProvider(
                base_url=settings.local_model_base_url,
                model_name=settings.local_model_name,
                api_key=settings.local_model_api_key,
                embed_model_name=settings.local_model_embed_name,
            )
            logger.info(
                "Using LocalProvider (url=%s, model=%s, embed=%s)",
                settings.local_model_base_url,
                settings.local_model_name,
                settings.local_model_embed_name,
            )
    return _llm_provider


def _build_embedding_function():
    """Build the LangChain embedding function based on LLM_PROVIDER setting."""
    from langchain_openai import OpenAIEmbeddings

    settings = get_settings()
    if settings.llm_provider == "bedrock":
        return BedrockEmbeddings(
            model_id=settings.bedrock_embed_model_id,
            region_name=settings.aws_default_region,
        )
    return OpenAIEmbeddings(
        model=settings.local_model_embed_name,
        openai_api_base=settings.local_model_base_url,
        openai_api_key=settings.local_model_api_key,
        default_headers={"User-Agent": "curl/7.88.1"},
        check_embedding_ctx_length=False,
    )


def get_retriever() -> ChromaRetriever:
    """Return the singleton ChromaRetriever instance."""
    global _retriever
    if _retriever is None:
        settings = get_settings()
        embedding_fn = _build_embedding_function()
        _retriever = ChromaRetriever(
            embedding_function=embedding_fn,
            host=settings.chroma_host,
            port=settings.chroma_port,
            persist_directory="./data/chroma_db",
            use_http_client=settings.chroma_use_http,
        )
    return _retriever


def get_rag_pipeline() -> RAGPipeline:
    """Return the singleton RAGPipeline instance."""
    global _rag_pipeline
    if _rag_pipeline is None:
        _rag_pipeline = RAGPipeline(
            retriever=get_retriever(),
            llm_provider=get_llm_provider(),
        )
    return _rag_pipeline


def get_ingestion_pipeline() -> DocumentIngestionPipeline:
    """Return the singleton DocumentIngestionPipeline instance."""
    global _ingestion_pipeline
    if _ingestion_pipeline is None:
        _ingestion_pipeline = DocumentIngestionPipeline(retriever=get_retriever())
    return _ingestion_pipeline


def _build_strands_model():
    """Build the Strands Model instance based on LLM_PROVIDER setting."""
    settings = get_settings()

    if settings.llm_provider == "bedrock":
        from strands.models.bedrock import BedrockModel
        return BedrockModel(
            model_id=settings.bedrock_chat_model_id,
            region_name=settings.aws_default_region,
        )
    else:
        from strands.models.openai import OpenAIModel
        return OpenAIModel(
            client_args={
                "base_url": settings.local_model_base_url,
                "api_key": settings.local_model_api_key,
                "default_headers": {"User-Agent": "curl/7.88.1"},
            },
            model_id=settings.local_model_name,
        )


def get_agent_orchestrator() -> AgentOrchestrator:
    """Return the singleton AgentOrchestrator instance."""
    global _agent_orchestrator
    if _agent_orchestrator is None:
        settings = get_settings()
        _agent_orchestrator = AgentOrchestrator(
            strands_model=_build_strands_model(),
            rag_pipeline=get_rag_pipeline(),
            system_prompt=settings.system_prompt,
            timeout_seconds=settings.agent_timeout_seconds,
        )
    return _agent_orchestrator


# ---------------------------------------------------------------------------
# Typed dependency aliases for route injection
# ---------------------------------------------------------------------------

LLMDep = Annotated[BaseLLMProvider, Depends(get_llm_provider)]
RetrieverDep = Annotated[ChromaRetriever, Depends(get_retriever)]
RAGDep = Annotated[RAGPipeline, Depends(get_rag_pipeline)]
IngestionDep = Annotated[DocumentIngestionPipeline, Depends(get_ingestion_pipeline)]
AgentDep = Annotated[AgentOrchestrator, Depends(get_agent_orchestrator)]
