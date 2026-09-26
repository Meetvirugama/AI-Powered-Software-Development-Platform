"""Tests verifying the test infrastructure fixtures: database, fake Redis, and GitHub mocks."""

from __future__ import annotations

import requests
from sqlalchemy.orm import Session

from app.models.user import User
from backend.tests.mocks.github import (
    DEFAULT_MOCK_USER,
    DEFAULT_MOCK_INSTALLATIONS,
    DEFAULT_MOCK_REPOSITORIES,
)


def test_mock_github_user_endpoint(mock_github) -> None:
    """Verify that requests to https://api.github.com/user are mocked by default."""
    response = requests.get("https://api.github.com/user")
    assert response.status_code == 200
    data = response.json()
    assert data["login"] == DEFAULT_MOCK_USER["login"]
    assert data["id"] == DEFAULT_MOCK_USER["id"]


def test_mock_github_installations_and_tokens(mock_github) -> None:
    """Verify installation and token generation mock endpoints."""
    # List installations
    installations_resp = requests.get("https://api.github.com/app/installations")
    assert installations_resp.status_code == 200
    assert len(installations_resp.json()) == len(DEFAULT_MOCK_INSTALLATIONS)

    # Generate installation access token
    token_resp = requests.post("https://api.github.com/app/installations/98765/access_tokens")
    assert token_resp.status_code == 201
    assert "token" in token_resp.json()


def test_mock_github_repositories(mock_github) -> None:
    """Verify repository list mock endpoint."""
    resp = requests.get("https://api.github.com/installation/repositories")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_count"] == DEFAULT_MOCK_REPOSITORIES["total_count"]
    assert data["repositories"][0]["name"] == "sample-repo"


def test_database_session_crud(db_session: Session) -> None:
    """Verify test database session supports CRUD operations and rolls back."""
    user = User(
        github_id="gh-12345",
        login="testuser",
        email="testuser@example.com",
    )
    db_session.add(user)
    db_session.commit()

    retrieved = db_session.query(User).filter_by(login="testuser").first()
    assert retrieved is not None
    assert retrieved.github_id == "gh-12345"
    assert retrieved.email == "testuser@example.com"


def test_fake_redis_fixture(fake_redis) -> None:
    """Verify the FakeRedis test fixture supports standard key-value and blocklist operations."""
    fake_redis.set("key1", "val1")
    assert fake_redis.get("key1") == "val1"
    assert fake_redis.exists("key1") == 1

    fake_redis.setex("key2", 60, "val2")
    assert fake_redis.exists("key2") == 1
    assert "key2" in fake_redis.blocklisted

    fake_redis.delete("key1")
    assert fake_redis.exists("key1") == 0
