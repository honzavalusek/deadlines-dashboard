"""Async engine and session factory.

Async all the way through — routes, sessions and the LLM fan-out share one
concurrency model rather than bridging a sync ORM into an async pipeline with
threadpool hops.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.db.tables import Base

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_engine(database_url: str, echo: bool = False) -> AsyncEngine:
    global _engine, _sessionmaker
    _engine = create_async_engine(database_url, echo=echo)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        raise RuntimeError("init_engine() must be called before requesting a session")
    return _sessionmaker


async def create_schema() -> None:
    """Create tables if absent.

    Deliberately not Alembic: this is a PoC with disposable data. Alembic is the
    production path and is named as such in the README, not stubbed here.
    """
    if _engine is None:
        raise RuntimeError("init_engine() must be called first")
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    if _engine is not None:
        await _engine.dispose()


async def session_scope() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, committed on clean exit."""
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
