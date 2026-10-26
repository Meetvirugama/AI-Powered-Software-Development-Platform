"""Tests for Parth — Week 2 Day 3: Agent Branch Creation.

Verifies:
1. When execution starts (task transitions to EXECUTING), the agent branch is created:
   main -> agent/task-{task_id} (e.g. agent/task-f47ac10b)
2. The branch points to the latest commit of the base branch with no commits yet.
3. Idempotent behavior when a paused/resumed task re-transitions to EXECUTING.
4. Custom base branch support.
5. Error handling for non-existent repositories or unavailable GitHub API.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.core.errors import APIError, ErrorCode
from app.integrations.github.client import GitHubAPIError, GitHubClient
from app.models.repository import Repository
from app.services.git_branch import AgentBranchInfo, GitBranchService


@pytest.fixture
def repo_id():
    return uuid4()


@pytest.fixture
def user_id():
    return uuid4()


@pytest.fixture
def sample_repo(repo_id, user_id):
    repo = MagicMock(spec=Repository)
    repo.id = repo_id
    repo.user_id = user_id
    repo.installation_id = "inst-123"
    repo.owner = "acme"
    repo.name = "web-platform"
    repo.default_branch = "main"
    return repo


@pytest.fixture
def mock_db(sample_repo):
    db = MagicMock()
    db.scalars.return_value.first.return_value = sample_repo
    return db


@pytest.fixture
def mock_client():
    client = MagicMock(spec=GitHubClient)
    client.get_branch = AsyncMock()
    client.create_branch = AsyncMock()
    client.get_ref = AsyncMock()
    return client


# ═══════════════════════════════════════════════════════════════════════════
# Agent Branch Creation on Task Execution Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestAgentBranchCreation:
    """Test suite for agent branch creation on task EXECUTING transition."""

    @pytest.mark.asyncio
    async def test_on_task_executing_creates_agent_branch(
        self, mock_db, mock_client, repo_id, user_id
    ):
        """When task transitions to EXECUTING, Parth's service creates agent/task-{task_id}."""
        task_id = UUID("f47ac10b-58cc-4372-a567-0e02b2c3d479")
        base_commit_sha = "d1e2f3a4b5c6d7e8f90123456789abcdef012345"

        # Side effect: agent branch does not exist initially; main branch exists with commit
        def get_branch_side_effect(owner, repo, branch):
            if branch == "agent/task-f47ac10b":
                raise GitHubAPIError("Not Found", status_code=404)
            if branch == "main":
                return {"name": "main", "commit": {"sha": base_commit_sha}}
            raise GitHubAPIError("Not Found", status_code=404)

        mock_client.get_branch.side_effect = get_branch_side_effect
        mock_client.create_branch.return_value = {"ref": "refs/heads/agent/task-f47ac10b"}

        service = GitBranchService(mock_db, client=mock_client)
        info = await service.on_task_executing(repo_id, task_id, user_id=user_id)

        assert isinstance(info, AgentBranchInfo)
        assert info.branch_name == "agent/task-f47ac10b"
        assert info.base_branch == "main"
        assert info.base_sha == base_commit_sha
        assert info.status == "created"
        assert info.task_id == str(task_id)
        assert info.repository_id == str(repo_id)

        # Confirm client created branch pointing to base commit SHA with 0 agent commits
        mock_client.create_branch.assert_called_once_with(
            "acme",
            "web-platform",
            "agent/task-f47ac10b",
            base_commit_sha,
        )

    @pytest.mark.asyncio
    async def test_on_task_executing_idempotent_if_already_exists(
        self, mock_db, mock_client, repo_id, user_id
    ):
        """If task resumes from PAUSED, branch already exists and is reused with status='ready'."""
        task_id = "f47ac10b"
        base_commit_sha = "aabbccddeeff00112233445566778899aabbccdd"

        # Both main and agent branch exist
        mock_client.get_branch.return_value = {
            "name": "agent/task-f47ac10b",
            "commit": {"sha": base_commit_sha},
        }

        service = GitBranchService(mock_db, client=mock_client)
        info = await service.on_task_executing(repo_id, task_id, user_id=user_id)

        assert info.branch_name == "agent/task-f47ac10b"
        assert info.status == "ready"
        assert info.base_sha == base_commit_sha
        # Does not attempt duplicate branch creation
        mock_client.create_branch.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_task_executing_custom_base_branch(
        self, mock_db, mock_client, repo_id, user_id
    ):
        """Allows branching off a custom base branch such as 'develop'."""
        task_id = "task-custom-99"
        dev_sha = "fedcba9876543210fedcba9876543210fedcba98"

        def get_branch_side_effect(owner, repo, branch):
            if branch == "agent/task-task-cus":
                raise GitHubAPIError("Not Found", status_code=404)
            if branch == "develop":
                return {"name": "develop", "commit": {"sha": dev_sha}}
            raise GitHubAPIError("Not Found", status_code=404)

        mock_client.get_branch.side_effect = get_branch_side_effect
        mock_client.create_branch.return_value = {"ref": "refs/heads/agent/task-task-cus"}

        service = GitBranchService(mock_db, client=mock_client)
        info = await service.on_task_executing(
            repo_id, task_id, user_id=user_id, base_branch="develop"
        )

        assert info.base_branch == "develop"
        assert info.base_sha == dev_sha
        assert info.status == "created"
        mock_client.create_branch.assert_called_once_with(
            "acme", "web-platform", info.branch_name, dev_sha
        )

    @pytest.mark.asyncio
    async def test_on_task_executing_missing_repository(self, mock_db, mock_client):
        """Missing repository raises 404 REPOSITORY_NOT_FOUND."""
        mock_db.scalars.return_value.first.return_value = None
        service = GitBranchService(mock_db, client=mock_client)

        with pytest.raises(APIError) as exc_info:
            await service.on_task_executing(uuid4(), "task123")
        assert exc_info.value.status_code == 404
        assert exc_info.value.code == ErrorCode.REPOSITORY_NOT_FOUND


# ═══════════════════════════════════════════════════════════════════════════
# Agent Branch Endpoint Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestAgentBranchRoutes:
    """Contract tests for POST /api/v1/repositories/{id}/source/agent-branch."""

    def _setup_auth(self, monkeypatch):
        from app.core.config import get_settings

        monkeypatch.setenv("JWT_SECRET", "test-secret")
        get_settings.cache_clear()

        class FakeRedis:
            def exists(self, key: str) -> int:
                return 0
            def setex(self, *args) -> None:
                pass
            def rpush(self, *args) -> int:
                return 1

        fake_redis = FakeRedis()
        monkeypatch.setattr("app.core.auth.get_redis", lambda: fake_redis)

    def test_unauthenticated_agent_branch_returns_401(self, monkeypatch):
        """Unauthenticated requests must be rejected with 401."""
        self._setup_auth(monkeypatch)
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app, raise_server_exceptions=False)
        repo_id = str(uuid4())
        response = client.post(
            f"/api/v1/repositories/{repo_id}/source/agent-branch",
            json={"task_id": "task-123"},
        )
        assert response.status_code == 401

    def test_missing_task_id_returns_422(self, monkeypatch):
        """Missing task_id in both body and query params returns 422."""
        self._setup_auth(monkeypatch)
        from fastapi.testclient import TestClient
        from app.main import app
        from app.core.security import create_access_token

        token, _ = create_access_token(str(uuid4()))
        client = TestClient(app, raise_server_exceptions=False)
        repo_id = str(uuid4())
        response = client.post(
            f"/api/v1/repositories/{repo_id}/source/agent-branch",
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )
        assert response.status_code == 422


