"""SQLAlchemy engine, session dependency, and declarative base.

Models and migrations remain Om's responsibility; this file only provides the
shared application infrastructure they will use.
"""

from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

db_kwargs: dict[str, Any] = {"pool_pre_ping": True}
if not settings.database_url.startswith("sqlite"):
    db_kwargs.update(
        {
            "pool_size": settings.db_pool_size,
            "max_overflow": settings.db_max_overflow,
            "pool_timeout": settings.db_pool_timeout,
            "pool_recycle": settings.db_pool_recycle,
        }
    )

engine = create_engine(settings.database_url, **db_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _resolve_async_database_url(sync_url: str) -> str:
    """Resolve an async-compatible SQLAlchemy URL from a synchronous URL."""
    if sync_url.startswith("postgresql+psycopg_async://") or sync_url.startswith("postgresql+asyncpg://"):
        return sync_url
    if sync_url.startswith("postgresql+psycopg://"):
        return sync_url.replace("postgresql+psycopg://", "postgresql+psycopg_async://", 1)
    if sync_url.startswith("postgresql://"):
        return sync_url.replace("postgresql://", "postgresql+psycopg_async://", 1)
    if sync_url.startswith("postgres://"):
        return sync_url.replace("postgres://", "postgresql+psycopg_async://", 1)
    return sync_url


def _create_safe_async_engine(sync_url: str, kwargs: dict[str, Any]) -> tuple[AsyncEngine | None, async_sessionmaker[AsyncSession] | None]:
    """Create the async SQLAlchemy engine safely without crashing on synchronous sqlite test URLs."""
    if sync_url.startswith("sqlite") and "+aiosqlite" not in sync_url:
        return None, None
    async_url = _resolve_async_database_url(sync_url)
    try:
        eng = create_async_engine(async_url, **kwargs)
        maker = async_sessionmaker(eng, expire_on_commit=False)
        return eng, maker
    except Exception:
        # Fallback to standard psycopg dialect if psycopg_async alias is unavailable
        try:
            fallback_url = sync_url.replace("postgresql://", "postgresql+psycopg://", 1)
            eng = create_async_engine(fallback_url, **kwargs)
            maker = async_sessionmaker(eng, expire_on_commit=False)
            return eng, maker
        except Exception:
            return None, None


_async_database_url = _resolve_async_database_url(settings.database_url)
async_engine, AsyncSessionLocal = _create_safe_async_engine(settings.database_url, db_kwargs)


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models owned by the database module."""


def get_db() -> Generator[Session, None, None]:
    """Yield a database session and guarantee it is closed afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
