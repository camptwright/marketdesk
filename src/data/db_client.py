"""Database engine management.

Unlike fantasy-edge (which forks Celery workers and needs a strict pooled-
vs-NullPool split - see that repo's CLAUDE.md constraint #1), marketdesk has
no Celery and no forking at all: APScheduler's `AsyncIOScheduler` runs jobs
as coroutines on the SAME event loop as the FastAPI app, in the same
process. One pooled engine, shared by request handlers and scheduled jobs
alike, is correct and sufficient here - there is no second process to
accidentally inherit live connections.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config.settings import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            pool_size=10,
            max_overflow=5,
            pool_pre_ping=True,
            pool_recycle=1800,
            echo=False,
        )
        _sessionmaker = async_sessionmaker(
            _engine, class_=AsyncSession, expire_on_commit=False
        )
    return _engine


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency."""
    get_engine()
    assert _sessionmaker is not None
    async with _sessionmaker() as session:
        yield session


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Same session factory, for use outside FastAPI's DI system - i.e. from
    APScheduler job callbacks, which aren't request handlers and can't use
    `Depends(get_db)`."""
    get_engine()
    assert _sessionmaker is not None
    async with _sessionmaker() as session:
        yield session


async def dispose_engine() -> None:
    """Called from the FastAPI lifespan shutdown hook."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None
