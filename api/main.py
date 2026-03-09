"""FastAPI application entry point."""

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routes import agent, auth, chat, rag, tenants, tokens

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Application lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    from core.database.engine import engine
    from core.database.models import Base

    logger.info("Starting bob (provider=%s)", os.getenv("LLM_PROVIDER", "local"))

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

# ---------------------------------------------------------------------------
# CORS middleware
# ---------------------------------------------------------------------------

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8080").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
    """Return application health status."""
    return {
        "status": "healthy",
        "provider": os.getenv("LLM_PROVIDER", "local"),
        "version": "1.0.0",
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
