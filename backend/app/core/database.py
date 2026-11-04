"""SQLAlchemy engine, session dependency, and declarative base.

Models and migrations remain Om's responsibility; this file only provides the
shared application infrastructure they will use.
"""

from collections.abc import AsyncGenerator, Generator
import logging
import re
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _sanitize_db_url(url: str) -> str:
    """Remove user credentials from database URL for safe logging."""
    if not url:
        return ""
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:[REDACTED]@", url)


def normalize_sync_database_url(url: str) -> str:
    """Normalize database URL for SQLAlchemy 2.0 with psycopg3 driver.

    Handles Supabase, Azure, Heroku, and cloud Postgres URLs starting with
    'postgres://' or 'postgresql://' (without explicit driver specification).
    """
    if not url:
        return ""
    clean = url.strip()
    if clean.startswith("postgres://"):
        clean = "postgresql+psycopg://" + clean[len("postgres://"):]
    elif clean.startswith("postgresql://") and not clean.startswith("postgresql+"):
        clean = "postgresql+psycopg://" + clean[len("postgresql://"):]
    return clean


def _build_db_kwargs(url: str) -> dict[str, Any]:
    """Construct engine kwargs tailored for local, Supabase, Azure, or SQLite databases."""
    kwargs: dict[str, Any] = {"pool_pre_ping": True}
    if not url.startswith("sqlite"):
        kwargs.update(
            {
                "pool_size": settings.db_pool_size,
                "max_overflow": settings.db_max_overflow,
                "pool_timeout": settings.db_pool_timeout,
                "pool_recycle": settings.db_pool_recycle,
            }
        )
        connect_args: dict[str, Any] = {}
        # Supabase Transaction Pooler (port 6543 / Supavisor / pgbouncer):
        # Disable prepared statement caching to prevent 'prepared statement already exists' collisions.
        if ":6543" in url:
            connect_args["prepare_threshold"] = None
        if connect_args:
            kwargs["connect_args"] = connect_args
    return kwargs


_normalized_database_url = normalize_sync_database_url(settings.database_url)
db_kwargs: dict[str, Any] = _build_db_kwargs(_normalized_database_url)

engine = create_engine(_normalized_database_url, **db_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _resolve_async_database_url(sync_url: str) -> str:
    """Resolve an async-compatible SQLAlchemy URL from a synchronous URL."""
    norm = normalize_sync_database_url(sync_url)
    if norm.startswith("postgresql+psycopg_async://") or norm.startswith("postgresql+asyncpg://"):
        return norm
    if norm.startswith("postgresql+psycopg://"):
        return norm.replace("postgresql+psycopg://", "postgresql+psycopg_async://", 1)
    if norm.startswith("postgresql://"):
        return norm.replace("postgresql://", "postgresql+psycopg_async://", 1)
    return norm


def _create_safe_async_engine(
    sync_url: str, kwargs: dict[str, Any]
) -> tuple[AsyncEngine | None, async_sessionmaker[AsyncSession] | None]:
    """Create the async SQLAlchemy engine safely without crashing on synchronous sqlite test URLs."""
    norm_sync = normalize_sync_database_url(sync_url)
    if norm_sync.startswith("sqlite") and "+aiosqlite" not in norm_sync:
        logger.debug("async_engine_skipped_for_sync_sqlite")
        return None, None
    async_url = _resolve_async_database_url(norm_sync)
    async_kwargs = dict(kwargs)
    if ":6543" in async_url:
        c_args = dict(async_kwargs.get("connect_args", {}))
        c_args["prepare_threshold"] = None
        async_kwargs["connect_args"] = c_args
    try:
        eng = create_async_engine(async_url, **async_kwargs)
        maker = async_sessionmaker(eng, expire_on_commit=False)
        return eng, maker
    except Exception as exc:
        safe_url = _sanitize_db_url(async_url)
        logger.warning(
            "async_engine_primary_driver_failed",
            extra={"url": safe_url, "error": str(exc)},
        )
        # Fallback to standard psycopg dialect if psycopg_async alias is unavailable
        try:
            fallback_url = norm_sync.replace("postgresql://", "postgresql+psycopg://", 1)
            eng = create_async_engine(fallback_url, **async_kwargs)
            maker = async_sessionmaker(eng, expire_on_commit=False)
            return eng, maker
        except Exception as fb_exc:
            logger.error(
                "async_database_init_failed",
                extra={"url": _sanitize_db_url(fallback_url), "error": str(fb_exc)},
            )
            return None, None


def init_async_db(
    url: str | None = None, kwargs: dict[str, Any] | None = None
) -> tuple[AsyncEngine | None, async_sessionmaker[AsyncSession] | None]:
    """Explicit initializer allowing runtime or test injection without relying only on module load globals."""
    target_url = normalize_sync_database_url(url or settings.database_url)
    target_kwargs = kwargs if kwargs is not None else _build_db_kwargs(target_url)
    return _create_safe_async_engine(target_url, target_kwargs)


_async_database_url = _resolve_async_database_url(_normalized_database_url)
async_engine, AsyncSessionLocal = _create_safe_async_engine(_normalized_database_url, db_kwargs)
async_session_factory = AsyncSessionLocal


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models owned by the database module."""


def get_db() -> Generator[Session, None, None]:
    """Yield a database session and guarantee it is closed afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_db_async() -> AsyncGenerator[AsyncSession, None]:
    """Yield an asynchronous database session when AsyncSessionLocal is configured (GAP-07)."""
    if AsyncSessionLocal is None:
        raise RuntimeError("AsyncSessionLocal is not configured for the active database URL.")
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
