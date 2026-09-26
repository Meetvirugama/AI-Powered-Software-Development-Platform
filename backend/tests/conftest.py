"""Shared pytest fixtures and test configuration for the backend.

Provides:
- Test database engine and session (supporting PostgreSQL via TEST_DATABASE_URL or SQLite test.db)
- Synchronous and asynchronous HTTP test clients (httpx)
- Mock GitHub API fixture using `responses`
- Mock Redis fixture
- FastAPI dependency overrides
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import AsyncGenerator, Generator
import pytest
from fastapi.testclient import TestClient
import httpx
import responses
from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    Vector = None  # type: ignore

try:
    from tests.mocks.github import register_github_mocks
except ImportError:
    from backend.tests.mocks.github import register_github_mocks

from app.core.config import get_settings
from app.core.database import Base, get_db
from app.main import app

# Determine test database URL
TEST_DB_PATH = Path(__file__).resolve().parent.parent / "test.db"
DEFAULT_TEST_DATABASE_URL = f"sqlite:///{TEST_DB_PATH.as_posix()}"
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)

# Configure SQLite compatibility for PostgreSQL-specific types if using SQLite
@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


if Vector is not None:
    @compiles(Vector, "sqlite")
    def _compile_vector_sqlite(type_, compiler, **kw):
        return "TEXT"


class FakeRedis:
    """In-memory Redis fake for fast, isolated test execution."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.blocklisted: set[str] = set()

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str, *args, **kwargs) -> bool:
        self.store[key] = str(value)
        return True

    def setex(self, key: str, time: int, value: str) -> bool:
        self.store[key] = str(value)
        self.blocklisted.add(key)
        return True

    def exists(self, key: str) -> int:
        return int(key in self.store or key in self.blocklisted)

    def rpush(self, *_: object) -> int:
        return 1

    def delete(self, key: str) -> int:
        existed = key in self.store
        self.store.pop(key, None)
        self.blocklisted.discard(key)
        return int(existed)

    def ping(self) -> bool:
        return True


@pytest.fixture(scope="session")
def test_engine():
    """Create a single database engine for the test session."""
    is_sqlite = TEST_DATABASE_URL.startswith("sqlite")
    connect_args = {"check_same_thread": False} if is_sqlite else {}

    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args=connect_args,
        pool_pre_ping=True,
    )

    # Filter out postgresql-specific indexes if creating on SQLite
    if is_sqlite:
        for table in Base.metadata.tables.values():
            indexes_to_remove = [
                idx
                for idx in table.indexes
                if any(
                    "to_tsvector" in str(getattr(expr, "text", expr))
                    or idx.dialect_options.get("postgresql", {}).get("using") in ("hnsw", "gin")
                    for expr in idx.expressions
                )
            ]
            for idx in indexes_to_remove:
                table.indexes.remove(idx)

    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()

    # Clean up local SQLite test file if one was created
    if is_sqlite and TEST_DB_PATH.exists():
        try:
            TEST_DB_PATH.unlink(missing_ok=True)
        except OSError:
            pass


@pytest.fixture
def db_session(test_engine) -> Generator[Session, None, None]:
    """Provide an isolated database session per test with automatic rollback."""
    connection = test_engine.connect()
    transaction = connection.begin()
    test_session_maker = sessionmaker(autocommit=False, autoflush=False, bind=connection)
    session = test_session_maker()

    yield session

    session.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


@pytest.fixture
def fake_redis(monkeypatch) -> FakeRedis:
    """Mock Redis client for tests."""
    mock = FakeRedis()
    monkeypatch.setattr("app.core.redis.get_redis", lambda: mock)
    monkeypatch.setattr("app.core.auth.get_redis", lambda: mock)
    try:
        monkeypatch.setattr("app.api.v1.auth.get_redis", lambda: mock)
    except AttributeError:
        pass
    try:
        monkeypatch.setattr("app.api.v1.repositories.get_redis", lambda: mock)
    except AttributeError:
        pass
    return mock


@pytest.fixture
def mock_github() -> Generator[responses.RequestsMock, None, None]:
    """Mock external GitHub API calls using the responses library."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        register_github_mocks(rsps)
        yield rsps


@pytest.fixture
def client(db_session: Session, fake_redis: FakeRedis) -> Generator[TestClient, None, None]:
    """Synchronous test client configured with database overrides and fake Redis."""
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app, base_url="http://testserver", raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
async def async_client(db_session: Session, fake_redis: FakeRedis) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Asynchronous httpx test client for testing async FastAPI endpoints."""
    app.dependency_overrides[get_db] = lambda: db_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.clear()
