"""FastAPI application entry point."""

import logging
import time
import uuid
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from api.routes import agent, auth, chat, rag, tenants, tokens
from core.config import get_settings

settings = get_settings()

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

limiter = Limiter(key_func=get_remote_address, default_limits=[settings.rate_limit])

# ---------------------------------------------------------------------------
# Application lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    from core.database.engine import engine
    from core.database.models import Base

    logger.info("Starting bob (provider=%s)", settings.llm_provider)

    # Create all tables if they don't exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables verified/created")

    yield

    await engine.dispose()
    logger.info("Shutting down bob")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Bob",
    description=(
        "Bob — your AI agent. Conversational AI with memory, "
        "Retrieval-Augmented Generation (RAG), and agentic tool use. "
        "Supports Amazon Bedrock and local OpenAI-compatible models."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Attach rate limiter state
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ---------------------------------------------------------------------------
# Middleware (order matters — last added = outermost)
# ---------------------------------------------------------------------------

# GZip compression for responses > 500 bytes
app.add_middleware(GZipMiddleware, minimum_size=500)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Tenant-ID"],
    expose_headers=["X-New-Token", "X-Request-ID", "X-Process-Time-Ms", "X-Session-ID"],
)


# ---------------------------------------------------------------------------
# Request / Response logging middleware
# ---------------------------------------------------------------------------


@app.middleware("http")
async def logging_middleware(request: Request, call_next) -> Response:
    """Log all incoming requests and outgoing responses with timing."""
    request_id = str(uuid.uuid4())[:8]
    start = time.perf_counter()

    logger.info(
        "[%s] --> %s %s",
        request_id,
        request.method,
        request.url.path,
    )

    response: Response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000

    logger.info(
        "[%s] <-- %s %s %d (%.1fms)",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )

    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time-Ms"] = f"{duration_ms:.1f}"

    # JWT auto-refresh: issue a new token when the current one is close to expiry
    if response.status_code < 400:
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            raw_token = auth_header[7:]
            # Only attempt refresh for JWT tokens, not API tokens (bob_*)
            if not raw_token.startswith("bob_"):
                from core.auth.jwt import maybe_refresh_token

                new_token = maybe_refresh_token(raw_token)
                if new_token:
                    response.headers["X-New-Token"] = new_token

    return response


# ---------------------------------------------------------------------------
# Include routers
# ---------------------------------------------------------------------------

API_PREFIX = "/api/v1"

app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(tenants.router, prefix=API_PREFIX)
app.include_router(chat.router, prefix=API_PREFIX)
app.include_router(rag.router, prefix=API_PREFIX)
app.include_router(agent.router, prefix=API_PREFIX)
app.include_router(tokens.router, prefix=API_PREFIX)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/health", tags=["meta"], summary="Health check")
async def health_check() -> dict:
    """Return application health status with dependency checks."""
    import sqlalchemy

    from core.database.engine import engine

    checks: dict[str, str] = {}

    # Database connectivity
    try:
        async with engine.connect() as conn:
            await conn.execute(sqlalchemy.text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    overall = "healthy" if all(v == "ok" for v in checks.values()) else "degraded"

    return {
        "status": overall,
        "provider": settings.llm_provider,
        "version": "1.0.0",
        "checks": checks,
    }


@app.get("/", tags=["meta"], summary="Root")
async def root() -> dict:
    """Root endpoint with API info."""
    return {
        "name": "Bob",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }


# ---------------------------------------------------------------------------
# Global exception handler
# ---------------------------------------------------------------------------


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all exception handler to avoid leaking stack traces."""
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "type": type(exc).__name__,
        },
    )
