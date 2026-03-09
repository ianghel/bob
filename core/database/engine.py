"""Async SQLAlchemy engine and session factory for MySQL."""

import os
from urllib.parse import quote_plus

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
_DB_PORT = os.getenv("DB_PORT", "3306")
_DB_DATABASE = os.getenv("DB_DATABASE", "bob")
_DB_USERNAME = os.getenv("DB_USERNAME", "root")
_DB_PASSWORD = os.getenv("DB_PASSWORD", "")

DATABASE_URL = (
    f"mysql+aiomysql://{_DB_USERNAME}:{quote_plus(_DB_PASSWORD)}@{_DB_HOST}:{_DB_PORT}/{_DB_DATABASE}"
)

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    """FastAPI dependency that yields an async DB session."""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
