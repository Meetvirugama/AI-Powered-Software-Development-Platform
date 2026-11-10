"""Unit and integration tests for GitHub Source Browsing & Consolidation (Issue #196).

Verifies:
1. GitHubSourceService.list_issues retrieves and filters remote issues, excluding pull requests.
2. GitHubSourceService.get_issue_detail retrieves and formats remote issue metadata.
3. GitHubSourceService.get_issue compatibility adapter for IssueToTaskAdapter.
4. HTTP endpoints GET /repositories/{id}/source/issues and /source/issues/{issue_number}.
5. Deprecated duplicate execution surfaces under /repositories/{id}/source/task/* return 410 with X-Canonical-Endpoint.
6. Multi-tenant isolation and input validation for issue browsing.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch
import pytest
from sqlalchemy.orm import Session

from app.core.errors import APIError
from app.integrations.github.schemas import RemoteIssueInfo
from app.integrations.github.source_service import GitHubSourceService
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.user import User


@pytest.fixture
def repo_setup(db_session: Session):
    """Seed test user, installation, and repository."""
    user = User(
        id=uuid.uuid4(),
        github_id="gh_196",
        email="source_browser@example.com",
        login="source_user196",
        avatar_url="",
    )
    db_session.add(user)
    db_session.flush()

    inst = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=user.id,
        installation_id="196001",
        account_login=user.login,
        permissions={},
    )
    db_session.add(inst)
    db_session.flush()

    repo = Repository(
        id=uuid.uuid4(),
        user_id=user.id,
        installation_id=inst.id,
        github_repo_id="196999",
        owner=user.login,
        name="source-browsing-repo",
        default_branch="main",
        sync_status=SyncStatus.SYNCED,
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    return {"user": user, "repo": repo, "inst": inst}


@pytest.mark.asyncio
async def test_source_service_list_issues_filters_prs(db_session: Session, repo_setup: dict):
    """Test listing issues via GitHubSourceService cleanly filters out pull requests."""
    service = GitHubSourceService(db_session)
    repo = repo_setup["repo"]
    user = repo_setup["user"]

    mock_raw_issues = [
        {
            "number": 101,
            "title": "Fix authentication header parsing",
            "state": "open",
            "body": "Header authorization is missing Bearer prefix in some clients.",
            "user": {"login": "octocat"},
            "labels": [{"name": "bug"}, {"name": "backend"}],
            "html_url": "https://github.com/source_user196/source-browsing-repo/issues/101",
            "comments": 3,
        },
        {
            "number": 102,
            "title": "A pull request masquerading under issues API",
            "state": "open",
            "body": "PR description",
            "user": {"login": "contributor"},
            "pull_request": {"url": "https://api.github.com/repos/.../pulls/102"},
            "labels": [],
        },
        {
            "number": 103,
            "title": "Feature: Add caching to file tree",
            "state": "open",
            "body": "Cache tree queries for 5 minutes.",
            "user": {"login": "developer"},
            "labels": [{"name": "enhancement"}],
            "html_url": "https://github.com/source_user196/source-browsing-repo/issues/103",
            "comments": 0,
        },
    ]

    mock_client = AsyncMock()
    mock_client.list_issues = AsyncMock(return_value=mock_raw_issues)

    with patch.object(service, "_get_client", AsyncMock(return_value=mock_client)):
        issues = await service.list_issues(repo.id, user.id, state="open")

    assert len(issues) == 2  # #102 pull request filtered out
    assert issues[0].number == 101
    assert issues[0].title == "Fix authentication header parsing"
    assert issues[0].author == "octocat"
    assert issues[0].labels == ["bug", "backend"]
    assert issues[0].comments_count == 3
    assert issues[0].is_pull_request is False

    assert issues[1].number == 103
    assert issues[1].title == "Feature: Add caching to file tree"
    assert issues[1].author == "developer"
    assert issues[1].labels == ["enhancement"]


@pytest.mark.asyncio
async def test_source_service_get_issue_detail_and_compat(db_session: Session, repo_setup: dict):
    """Test retrieving single issue detail and GitHubIssueData compatibility adapter."""
    service = GitHubSourceService(db_session)
    repo = repo_setup["repo"]
    user = repo_setup["user"]

    mock_issue_data = {
        "number": 42,
        "title": "Database connection timeout during burst load",
        "state": "open",
        "body": "Connection pool exhausted when running 100 concurrent requests.",
        "user": {"login": "db_admin"},
        "labels": [{"name": "performance"}, {"name": "database"}],
        "html_url": "https://github.com/source_user196/source-browsing-repo/issues/42",
        "comments": 5,
    }

    mock_client = AsyncMock()
    mock_client.get_issue = AsyncMock(return_value=mock_issue_data)

    with patch.object(service, "_get_client", AsyncMock(return_value=mock_client)):
        detail = await service.get_issue_detail(repo.id, user.id, 42)
        compat = await service.get_issue(repo.id, user.id, 42)

    assert detail.number == 42
    assert detail.title == "Database connection timeout during burst load"
    assert detail.author == "db_admin"
    assert detail.labels == ["performance", "database"]
    assert detail.comments_count == 5

    # Test compatibility adapter for IssueToTaskAdapter
    assert compat.number == 42
    assert compat.title == "Database connection timeout during burst load"
    assert compat.author == "db_admin"
    assert compat.is_pull_request is False


def test_api_remote_issues_endpoints(client, db_session: Session, repo_setup: dict, monkeypatch):
    """Test HTTP API endpoints for listing and viewing remote GitHub issues."""
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-12345-secure-32bytes!")
    from app.core.config import get_settings
    get_settings.cache_clear()
    from app.core.security import create_access_token

    user = repo_setup["user"]
    repo = repo_setup["repo"]
    token, _ = create_access_token(user_id=str(user.id))
    headers = {"Authorization": f"Bearer {token}"}

    sample_issue = {
        "number": 55,
        "title": "Remote issue via API route",
        "state": "open",
        "body": "Detailed report",
        "user": {"login": "tester"},
        "labels": [{"name": "qa"}],
        "html_url": "https://github.com/source_user196/source-browsing-repo/issues/55",
        "comments": 1,
    }

    mock_client = AsyncMock()
    mock_client.list_issues = AsyncMock(return_value=[sample_issue])
    mock_client.get_issue = AsyncMock(return_value=sample_issue)

    with patch.object(GitHubSourceService, "_get_client", AsyncMock(return_value=mock_client)):
        # 1. List remote issues
        resp_list = client.get(
            f"/api/v1/repositories/{repo.id}/source/issues",
            headers=headers,
        )
        assert resp_list.status_code == 200
        items = resp_list.json()
        assert len(items) == 1
        assert items[0]["number"] == 55
        assert items[0]["title"] == "Remote issue via API route"
        assert items[0]["author"] == "tester"

        # 2. Get specific remote issue
        resp_item = client.get(
            f"/api/v1/repositories/{repo.id}/source/issues/55",
            headers=headers,
        )
        assert resp_item.status_code == 200
        data = resp_item.json()
        assert data["number"] == 55
        assert data["title"] == "Remote issue via API route"
        assert data["author"] == "tester"

        # 3. Invalid issue number returns 400
        resp_invalid = client.get(
            f"/api/v1/repositories/{repo.id}/source/issues/0",
            headers=headers,
        )
        assert resp_invalid.status_code == 400

        # 4. Negative issue number returns 400
        resp_neg = client.get(
            f"/api/v1/repositories/{repo.id}/source/issues/-5",
            headers=headers,
        )
        assert resp_neg.status_code == 400


def test_api_issue_not_found_handling(client, repo_setup: dict, monkeypatch):
    """Test 404 response when a remote issue is not found on GitHub."""
    from app.integrations.github.client import GitHubAPIError

    monkeypatch.setenv("JWT_SECRET", "test-secret-key-12345-secure-32bytes!")
    from app.core.config import get_settings
    get_settings.cache_clear()
    from app.core.security import create_access_token

    user = repo_setup["user"]
    repo = repo_setup["repo"]
    token, _ = create_access_token(user_id=str(user.id))
    headers = {"Authorization": f"Bearer {token}"}

    mock_client = AsyncMock()
    mock_client.get_issue = AsyncMock(side_effect=GitHubAPIError("Not Found", status_code=404))

    with patch.object(GitHubSourceService, "_get_client", AsyncMock(return_value=mock_client)):
        resp = client.get(
            f"/api/v1/repositories/{repo.id}/source/issues/9999",
            headers=headers,
        )
        assert resp.status_code == 404
        body = resp.json()
        detail = body.get("detail") or body.get("message") or body.get("error")
        assert "not found" in str(detail).lower()


def test_api_multi_tenant_repository_isolation(client, db_session: Session, repo_setup: dict, monkeypatch):
    """Verify users cannot browse issues for repositories they do not own."""
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-12345-secure-32bytes!")
    from app.core.config import get_settings
    get_settings.cache_clear()
    from app.core.security import create_access_token

    other_user = User(
        id=uuid.uuid4(),
        github_id="gh_other_196",
        email="other@example.com",
        login="other_user196",
        avatar_url="",
    )
    db_session.add(other_user)
    db_session.commit()

    token_other, _ = create_access_token(user_id=str(other_user.id))
    headers_other = {"Authorization": f"Bearer {token_other}"}
    repo = repo_setup["repo"]

    resp = client.get(
        f"/api/v1/repositories/{repo.id}/source/issues",
        headers=headers_other,
    )
    assert resp.status_code in (403, 404)



def test_api_deprecated_duplicate_task_execution_surfaces(client, repo_setup: dict, monkeypatch):
    """Verify deprecated /repositories/{id}/source/task/* surfaces return 410 with X-Canonical-Endpoint."""
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-12345-secure-32bytes!")
    from app.core.config import get_settings
    get_settings.cache_clear()
    from app.core.security import create_access_token

    user = repo_setup["user"]
    repo = repo_setup["repo"]
    token, _ = create_access_token(user_id=str(user.id))
    headers = {"Authorization": f"Bearer {token}"}

    for action in ["publish-pr", "tests", "verify", "repair", "execute-pipeline"]:
        resp = client.post(
            f"/api/v1/repositories/{repo.id}/source/task/{action}",
            headers=headers,
            json={"task_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 410
        assert resp.headers.get("x-canonical-endpoint") == "/api/v1/tasks"
        assert resp.headers.get("deprecation") == "true"
        body = resp.json()
        assert body["error"] == "DEPRECATED_ENDPOINT"
        assert "consolidated" in body["message"]

        # Also verify /source/task-workspace/*
        resp_ws = client.post(
            f"/api/v1/repositories/{repo.id}/source/task-workspace/{action}",
            headers=headers,
            json={"task_id": str(uuid.uuid4())},
        )
        assert resp_ws.status_code == 410
        assert resp_ws.headers.get("x-canonical-endpoint") == "/api/v1/tasks"
        assert resp_ws.headers.get("deprecation") == "true"
        body_ws = resp_ws.json()
        assert body_ws["error"] == "DEPRECATED_ENDPOINT"
        assert "consolidated" in body_ws["message"]


@pytest.mark.asyncio
async def test_source_service_list_issues_repo_not_found_404(db_session: Session, repo_setup: dict):
    """Verify list_issues raises 404 when repository is not found on GitHub."""
    from app.integrations.github.client import GitHubAPIError

    service = GitHubSourceService(db_session)
    repo = repo_setup["repo"]
    user = repo_setup["user"]

    mock_client = AsyncMock()
    mock_client.list_issues = AsyncMock(side_effect=GitHubAPIError("Not Found", status_code=404))

    with patch.object(service, "_get_client", AsyncMock(return_value=mock_client)):
        with pytest.raises(APIError) as exc_info:
            await service.list_issues(repo.id, user.id)

        assert exc_info.value.status_code == 404
        assert "not found on GitHub" in str(exc_info.value.message)
