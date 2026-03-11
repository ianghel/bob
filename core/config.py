"""Centralized application settings using pydantic-settings.

All environment variables are defined once here. Import ``get_settings()``
wherever you need configuration instead of calling ``os.getenv()`` directly.
"""

from functools import lru_cache
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide configuration backed by environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # -- App ------------------------------------------------------------------
    app_env: str = "development"
    log_level: str = "INFO"

    # -- LLM Provider ---------------------------------------------------------
    llm_provider: str = "local"

    # -- AWS / Bedrock --------------------------------------------------------
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_default_region: str = "us-east-1"

    # -- Local Model (LM Studio / OpenAI-compatible) -------------------------
    local_model_base_url: str = "http://localhost:1234/v1"
    local_model_name: str = "your-model-name"
    local_model_embed_name: str = "text-embedding-nomic-embed-text-v1.5"
    local_model_api_key: str = "not-needed"

    # -- API Security ---------------------------------------------------------
    api_key: str = "dev-secret-key-change-in-prod"
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440  # 24 hours

    # -- CORS -----------------------------------------------------------------
    cors_origins: str = "http://localhost:3000,http://localhost:8080,http://localhost:5173"

    # -- Database (MariaDB / MySQL) -------------------------------------------
    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_database: str = "bob"
    db_username: str = "root"
    db_password: str = ""
    db_pool_size: int = 20
    db_max_overflow: int = 10
    db_pool_recycle: int = 3600

    # -- ChromaDB -------------------------------------------------------------
    chroma_host: str = "localhost"
    chroma_port: int = 8001
    chroma_use_http: bool = False

    # -- Email (SMTP) ---------------------------------------------------------
    mail_host: str = "smtp.gmail.com"
    mail_port: int = 587
    mail_username: str = ""
    mail_password: str = ""
    mail_from_address: str = ""
    admin_approval_email: str = ""

    # -- System Prompt --------------------------------------------------------
    system_prompt: str = (
        "You are Bob, a helpful AI assistant. "
        "You can search the internet for up-to-date information, compare prices, "
        "recommend products, and fetch content from web pages. "
        "When the user asks about products, prices, or shopping, use the search_products tool. "
        "When the user asks factual questions or needs current information, use the web_search tool. "
        "When the user asks to read or download content from a URL, use the fetch_webpage tool. "
        "Always provide sources and links when using search results."
    )

    # -- Web Search -----------------------------------------------------------
    web_search_enabled: bool = True
    web_search_max_results: int = 5

    # -- Agent ----------------------------------------------------------------
    agent_timeout_seconds: int = 120

    # -- Rate Limiting --------------------------------------------------------
    rate_limit: str = "60/minute"

    # -- Context Window / Memory Management -----------------------------------
    context_max_tokens: int = 48000
    context_sliding_window_turns: int = 10
    context_summary_enabled: bool = True

    # -- Session Limits -------------------------------------------------------
    max_turns_per_session: int = 100
    session_expiry_hours: int = 24

    # -- JWT Auto-Refresh -----------------------------------------------------
    jwt_auto_refresh: bool = True
    jwt_refresh_threshold_percent: int = 25

    # -- Computed properties --------------------------------------------------

    @property
    def cors_origin_list(self) -> list[str]:
        """Parse comma-separated CORS origins into a list."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def database_url(self) -> str:
        """Build the async SQLAlchemy connection string."""
        return (
            f"mysql+aiomysql://{self.db_username}:{quote_plus(self.db_password)}"
            f"@{self.db_host}:{self.db_port}/{self.db_database}"
        )


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings singleton."""
    return Settings()
