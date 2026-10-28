"""SQLAlchemy engine, session dependency, and declarative base.

Models and migrations remain Om's responsibility; this file only provides the
shared application infrastructure they will use.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

db_kwargs: dict = {"pool_pre_ping": True}
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

# Build the async-driver URL from the sync URL.
# psycopg3 uses different driver names for sync vs async connections:
#   sync:  postgresql+psycopg://
#   async: postgresql+psycopg_async://
# Using the wrong driver causes blocking I/O inside async event loops.
_async_database_url = settings.database_url.replace(
    "postgresql+psycopg://", "postgresql+psycopg_async://"
)
async_engine = create_async_engine(_async_database_url, **db_kwargs)
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models owned by the database module."""


def get_db() -> Generator[Session, None, None]:
    """Yield a database session and guarantee it is closed afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
