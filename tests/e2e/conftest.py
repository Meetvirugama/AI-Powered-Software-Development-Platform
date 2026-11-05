"""Shared E2E Test Fixtures and Test Environment Setup.

Provides completely isolated, non-mocked test execution:
- Clean in-memory SQLite database per test with all ORM models registered
- Full-featured in-memory Redis client supporting strings, sets, lists, transactions, and TTLs
- Authenticated FastAPI TestClient with real JWT tokens
- Ephemeral Git repository and workspace fixtures for sandbox testing
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
import tempfile
import uuid
import subprocess
import shutil
from typing import Any, Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

# Ensure backend is on PYTHONPATH
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Ensure test JWT and webhook secrets are always configured when running pytest tests/e2e/ directly
os.environ.setdefault("JWT_SECRET", "e2e-test-jwt-secret-key-at-least-32-chars-long")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "test-webhook-secret")

from app.core.config import get_settings
get_settings.cache_clear()
from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.main import app
from app import models as _app_models  # noqa: F401
from app.models.user import User
from app.models.repository import Repository
from app.models.github_installation import GitHubInstallation
from app.models.task import AgentTask

try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    Vector = None  # type: ignore

# SQLite type overrides for PostgreSQL dialects
@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"

if Vector is not None:
    @compiles(Vector, "sqlite")
    def _compile_vector_sqlite(type_, compiler, **kw):
        return "TEXT"


class E2EInMemoryRedis:
    """In-memory Redis fake with comprehensive command support for end-to-end testing."""

    def __init__(self) -> None:
        self.strings: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}
        self.lists: dict[str, list[str]] = {}
        self.ttls: dict[str, int] = {}

    def get(self, key: str) -> str | None:
        return self.strings.get(key)

    def set(self, key: str, value: Any, ex: int | None = None, nx: bool = False, px: int | None = None) -> bool:
        if nx and (key in self.strings or key in self.sets or key in self.lists):
            return False
        self.strings[key] = str(value)
        if ex is not None:
            self.ttls[key] = ex
        return True

    def setex(self, key: str, time: int, value: Any) -> bool:
        self.strings[key] = str(value)
        self.ttls[key] = time
        return True

    def exists(self, *keys: str) -> int:
        count = 0
        for k in keys:
            if k in self.strings or k in self.sets or k in self.lists:
                count += 1
        return count

    def delete(self, *keys: str) -> int:
        deleted = 0
        for k in keys:
            if k in self.strings:
                del self.strings[k]
                deleted += 1
            if k in self.sets:
                del self.sets[k]
                deleted += 1
            if k in self.lists:
                del self.lists[k]
                deleted += 1
            self.ttls.pop(k, None)
        return deleted

    def rpush(self, key: str, *values: Any) -> int:
        if key not in self.lists:
            self.lists[key] = []
        for v in values:
            self.lists[key].append(str(v))
        return len(self.lists[key])

    def lpop(self, key: str) -> str | None:
        if key in self.lists and self.lists[key]:
            return self.lists[key].pop(0)
        return None

    def rpoplpush(self, source: str, destination: str) -> str | None:
        if source in self.lists and self.lists[source]:
            item = self.lists[source].pop()
            if destination not in self.lists:
                self.lists[destination] = []
            self.lists[destination].insert(0, item)
            return item
        return None

    def llen(self, key: str) -> int:
        return len(self.lists.get(key, []))

    def lrange(self, key: str, start: int, end: int) -> list[str]:
        items = self.lists.get(key, [])
        if end == -1:
            return items[start:]
        return items[start : end + 1]

    def sadd(self, key: str, *members: Any) -> int:
        if key not in self.sets:
            self.sets[key] = set()
        added = 0
        for m in members:
            sm = str(m)
            if sm not in self.sets[key]:
                self.sets[key].add(sm)
                added += 1
        return added

    def sismember(self, key: str, member: Any) -> bool:
        return str(member) in self.sets.get(key, set())

    def smembers(self, key: str) -> set[str]:
        return set(self.sets.get(key, set()))

    def scard(self, key: str) -> int:
        return len(self.sets.get(key, set()))

    def ttl(self, key: str) -> int:
        return self.ttls.get(key, -1)

    def ping(self) -> bool:
        return True

    def pipeline(self, transaction: bool = True):
        return E2EPipeline(self)

    def pubsub(self):
        class MockPubSub:
            async def subscribe(self, channel):
                pass

            async def unsubscribe(self, channel):
                pass

            async def close(self):
                pass

            async def get_message(self, ignore_subscribe_messages=True, timeout=1.0):
                return {"type": "message", "data": json.dumps({"type": "connected", "is_public": True})}

        return MockPubSub()


class E2EPipeline:
    """Mock pipeline supporting rate limiting and atomic Redis operations."""

    def __init__(self, redis_instance: E2EInMemoryRedis):
        self._redis = redis_instance
        self._commands = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def incr(self, key: str):
        def _do_incr():
            curr = int(self._redis.strings.get(key, "0")) + 1
            self._redis.strings[key] = str(curr)
            return curr

        self._commands.append(_do_incr)
        return self

    def zadd(self, key: str, mapping: dict, **kwargs):
        self._commands.append(lambda: len(mapping))
        return self

    def zremrangebyscore(self, key: str, min_score: Any, max_score: Any):
        self._commands.append(lambda: 0)
        return self

    def zcard(self, key: str):
        self._commands.append(lambda: 0)
        return self

    def expire(self, key: str, time: int, **kwargs):
        self._commands.append(lambda: True)
        return self

    def execute(self):
        results = [cmd() for cmd in self._commands]
        self._commands.clear()
        return results


@pytest.fixture(scope="session")
def e2e_engine():
    """Create a persistent SQLite engine configured for all backend models."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )

    # Filter out postgresql-specific indexes for SQLite table creation
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


@pytest.fixture
def e2e_db(e2e_engine) -> Generator[Session, None, None]:
    """Provide a transaction-isolated DB session per test with clean rollback."""
    conn = e2e_engine.connect()
    trans = conn.begin()
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=conn)
    session = session_factory()

    yield session

    session.close()
    if trans.is_active:
        trans.rollback()
    conn.close()


@pytest.fixture
def e2e_redis(monkeypatch) -> E2EInMemoryRedis:
    """Mock Redis client wired directly into the application."""
    mock = E2EInMemoryRedis()
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
    async def _async_redis():
        return mock

    monkeypatch.setattr("app.core.redis.get_redis_async", _async_redis)
    try:
        monkeypatch.setattr("app.api.v1.events.get_redis_async", _async_redis)
    except AttributeError:
        pass
    return mock


@pytest.fixture
def e2e_client(e2e_db: Session, e2e_redis: E2EInMemoryRedis, monkeypatch) -> Generator[TestClient, None, None]:
    """Synchronous FastAPI TestClient with real dependency overrides."""
    monkeypatch.setenv("JWT_SECRET", os.environ.get("JWT_SECRET") or "e2e-test-jwt-secret-key-at-least-32-chars-long")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", os.environ.get("GITHUB_WEBHOOK_SECRET") or "test-webhook-secret")
    get_settings.cache_clear()
    app.dependency_overrides[get_db] = lambda: e2e_db
    with TestClient(app, base_url="http://testserver", raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def make_user(monkeypatch):
    """Helper factory to create users and real auth headers."""
    def _make(db: Session, login: str = "testuser", email: str = "testuser@example.com") -> tuple[User, dict[str, str]]:
        if not get_settings().jwt_secret:
            monkeypatch.setenv("JWT_SECRET", "e2e-test-jwt-secret-key-at-least-32-chars-long")
            get_settings.cache_clear()
        user_id = uuid.uuid4()
        user = User(
            id=user_id,
            login=login,
            email=email,
            github_id=abs(hash(login)) % 1000000,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token, _ = create_access_token(str(user.id))
        headers = {"Authorization": f"Bearer {token}"}
        return user, headers
    return _make


@pytest.fixture
def make_repo(make_user):
    """Helper factory to create repositories owned by a user."""
    def _make(db: Session, user: User, name: str = "test-repo") -> Repository:
        gh_inst = GitHubInstallation(
            id=uuid.uuid4(),
            user_id=user.id,
            installation_id=f"inst-{user.login}-{uuid.uuid4().hex[:6]}",
            account_login=user.login,
        )
        db.add(gh_inst)
        db.flush()

        repo = Repository(
            id=uuid.uuid4(),
            user_id=user.id,
            installation_id=gh_inst.id,
            owner=user.login,
            name=name,
            default_branch="main",
            github_repo_id=str(abs(hash(f"{user.login}/{name}")) % 1000000),
            sync_status="SYNCED",
        )
        db.add(repo)
        db.commit()
        db.refresh(repo)
        return repo
    return _make


@pytest.fixture
def temp_git_repo() -> Generator[Path, None, None]:
    """Create a temporary real Git repository with initial commit for workspace testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        subprocess.run(["git", "init", "-b", "main"], cwd=str(repo_path), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "E2E Tester"], cwd=str(repo_path), check=True)
        subprocess.run(["git", "config", "user.email", "tester@e2e.local"], cwd=str(repo_path), check=True)
        
        # Create standard files
        readme = repo_path / "README.md"
        readme.write_text("# E2E Test Repository\nInitial commit content.\n")
        
        main_py = repo_path / "main.py"
        main_py.write_text("def add(a: int, b: int) -> int:\n    return a + b\n")

        test_py = repo_path / "test_main.py"
        test_py.write_text("from main import add\ndef test_add():\n    assert add(1, 2) == 3\n")

        subprocess.run(["git", "add", "."], cwd=str(repo_path), check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(repo_path), check=True, capture_output=True)
        
        yield repo_path
