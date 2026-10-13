"""
Repository isolation tests — every repository-scoped endpoint.
Owner: Sukun — W1 (Day 3 matrix, re-verified for the Day 7 Security Gate)

Matrix (Docs/week1.md, Day 3):
    User A token + User A repository      → 2xx
    User A token + User B repository      → denied (403, or 404 which also hides existence)
    User A token + non-existent repository → 404
    No token                              → 401

Also checks that a denied request never reaches the RAG pipeline and never
returns User B's data in the body.

Run with:
    pytest backend/tests/test_repository_isolation.py -v --no-cov
"""

from __future__ import annotations

import uuid

import pytest

from ai.schemas.output import RepositoryAnswer
from app.core.security import create_access_token
from app.main import app
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.user import User

# (method, path template, json body)
ENDPOINTS = [
    ("GET", "/api/v1/repositories/{id}", None),
    ("POST", "/api/v1/repositories/{id}/sync", None),
    ("POST", "/api/v1/repositories/{id}/search", {"query": "auth", "top_k": 5}),
    ("POST", "/api/v1/repositories/{id}/chat", {"question": "Where is auth?"}),
    ("GET", "/api/v1/repositories/{id}/files", None),
    ("GET", "/api/v1/repositories/{id}/symbols", None),
]
IDS = [f"{m} {p.split('{id}')[-1] or '/'}" for m, p, _ in ENDPOINTS]

USER_B_SECRET_NAME = "user-b-private-repo"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_user_with_repo(db_session, login: str, repo_name: str) -> tuple[User, Repository]:
    user = User(id=uuid.uuid4(), github_id=f"gh-{uuid.uuid4().hex[:8]}", login=login,
                email=f"{login}@example.com")
    db_session.add(user)
    db_session.commit()
    installation = GitHubInstallation(id=uuid.uuid4(), user_id=user.id,
                                      installation_id=f"inst-{uuid.uuid4().hex[:8]}",
                                      account_login=login, permissions={"contents": "read"})
    db_session.add(installation)
    db_session.commit()
    repo = Repository(id=uuid.uuid4(), user_id=user.id, installation_id=installation.id,
                      github_repo_id=f"gh-repo-{uuid.uuid4().hex[:8]}", owner=login,
                      name=repo_name, default_branch="main", language="Python",
                      sync_status=SyncStatus.NOT_SYNCED)
    db_session.add(repo)
    db_session.commit()
    return user, repo


@pytest.fixture()
def user_a(db_session, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-12345")
    from app.core.config import get_settings
    get_settings.cache_clear()
    return _make_user_with_repo(db_session, "user_a", "user-a-repo")


@pytest.fixture()
def user_b(db_session):
    return _make_user_with_repo(db_session, "user_b", USER_B_SECRET_NAME)


@pytest.fixture()
def user_a_headers(user_a):
    token, _ = create_access_token(str(user_a[0].id))
    return {"Authorization": f"Bearer {token}"}


class _SpyPipeline:
    """Fake RAG pipeline that records which repositories it was asked about."""

    def __init__(self) -> None:
        self.repository_ids: list[uuid.UUID] = []

    async def retrieve(self, query, repository_id, top_k):
        self.repository_ids.append(repository_id)
        return []

    async def chat(self, question, repository_id, history):
        self.repository_ids.append(repository_id)
        return RepositoryAnswer(answer="ok", sources=[], confidence="low")


@pytest.fixture()
def spy_pipeline():
    previous = getattr(app.state, "rag_pipeline", None)
    spy = _SpyPipeline()
    app.state.rag_pipeline = spy
    yield spy
    app.state.rag_pipeline = previous


def _call(client, method, template, body, repo_id, headers=None):
    return client.request(method, template.format(id=repo_id), json=body, headers=headers or {})


# ---------------------------------------------------------------------------
# The matrix
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method, template, body", ENDPOINTS, ids=IDS)
def test_owner_can_access_own_repository(client, user_a, user_a_headers, spy_pipeline, method, template, body):
    res = _call(client, method, template, body, user_a[1].id, user_a_headers)
    assert res.status_code in (200, 202), res.text


@pytest.mark.parametrize("method, template, body", ENDPOINTS, ids=IDS)
def test_user_a_cannot_access_user_b_repository(client, user_a, user_b, user_a_headers, spy_pipeline,
                                                 method, template, body):
    user_b_repo = user_b[1]
    res = _call(client, method, template, body, user_b_repo.id, user_a_headers)

    # Spec says 403. Some routes return 404 ("does not exist or you do not have
    # access"), which also denies access and additionally hides that the repo exists.
    assert res.status_code in (403, 404), f"{method} {template} leaked access: {res.status_code}"
    assert USER_B_SECRET_NAME not in res.text, "User B's repository data appeared in the response"
    assert user_b_repo.id not in spy_pipeline.repository_ids, "Pipeline was called for another user's repo"


@pytest.mark.parametrize("method, template, body", ENDPOINTS, ids=IDS)
def test_nonexistent_repository_returns_404(client, user_a, user_a_headers, spy_pipeline, method, template, body):
    res = _call(client, method, template, body, uuid.uuid4(), user_a_headers)
    assert res.status_code == 404


@pytest.mark.parametrize("method, template, body", ENDPOINTS, ids=IDS)
def test_no_token_returns_401(client, user_a, method, template, body):
    res = _call(client, method, template, body, user_a[1].id)
    assert res.status_code == 401


def test_list_repositories_only_returns_own(client, user_a, user_b, user_a_headers):
    res = client.get("/api/v1/repositories", headers=user_a_headers)
    assert res.status_code == 200
    names = {r["name"] for r in res.json()}
    assert "user-a-repo" in names
    assert USER_B_SECRET_NAME not in names
