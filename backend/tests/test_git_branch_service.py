"""Unit tests for Parth's Week 2 Day 1 deliverable: GitBranchService.

Validates:
- Branch naming convention: agent/task-{task_id} (e.g. agent/task-f47ac10b)
- get_default_branch retrieval and 404 handling
- branch_exists check (true/false)
- create_agent_branch idempotency, commit SHA resolution, and ref creation
- delete_branch deletion and default-branch protection
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.core.errors import APIError, ErrorCode
from app.integrations.github.client import GitHubAPIError, GitHubClient
from app.models.repository import Repository
from app.services.git_branch import GitBranchService, format_agent_branch_name


# ═══════════════════════════════════════════════════════════════════════════
# 1. Branch Naming Convention Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestBranchNaming:
    """Validate the branch naming convention from Week 2 Day 1 specification."""

    def test_format_branch_name_with_uuid(self):
        task_id = UUID("f47ac10b-58cc-4372-a567-0e02b2c3d479")
        branch_name = format_agent_branch_name(task_id)
        assert branch_name == "agent/task-f47ac10b"

    def test_format_branch_name_with_uuid_str(self):
        task_id = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
        branch_name = format_agent_branch_name(task_id)
        assert branch_name == "agent/task-f47ac10b"

    def test_format_branch_name_with_short_str(self):
        task_id = "run42"
        branch_name = format_agent_branch_name(task_id)
        assert branch_name == "agent/task-run42"

    def test_format_branch_name_with_custom_id(self):
        task_id = "12345678"
        branch_name = format_agent_branch_name(task_id)
        assert branch_name == "agent/task-12345678"


# ═══════════════════════════════════════════════════════════════════════════
# 2. GitBranchService Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestGitBranchService:
    """Test suite for GitBranchService operations."""

    @pytest.fixture
    def mock_db(self):
        return MagicMock()

    @pytest.fixture
    def mock_client(self):
        client = MagicMock(spec=GitHubClient)
        client.get_branch = AsyncMock()
        client.create_branch = AsyncMock()
        client.delete_branch = AsyncMock()
        client.get_ref = AsyncMock()
        return client

    @pytest.fixture
    def sample_repo(self):
        repo = MagicMock(spec=Repository)
        repo.id = uuid4()
        repo.user_id = uuid4()
        repo.installation_id = "inst-123"
        repo.owner = "acme"
        repo.name = "web-platform"
        repo.default_branch = "main"
        return repo

    # ----- get_default_branch ----------------------------------------------

    @pytest.mark.asyncio
    async def test_get_default_branch_success(self, mock_db, mock_client, sample_repo):
        mock_db.scalars.return_value.first.return_value = sample_repo
        service = GitBranchService(mock_db, client=mock_client)

        branch = await service.get_default_branch(sample_repo.id)
        assert branch == "main"

    @pytest.mark.asyncio
    async def test_get_default_branch_repo_not_found(self, mock_db, mock_client):
        mock_db.scalars.return_value.first.return_value = None
        service = GitBranchService(mock_db, client=mock_client)

        with pytest.raises(APIError) as exc_info:
            await service.get_default_branch(uuid4())
        assert exc_info.value.status_code == 404
        assert exc_info.value.code == ErrorCode.REPOSITORY_NOT_FOUND

    # ----- branch_exists ---------------------------------------------------

    @pytest.mark.asyncio
    async def test_branch_exists_true(self, mock_db, mock_client, sample_repo):
        mock_db.scalars.return_value.first.return_value = sample_repo
        mock_client.get_branch.return_value = {"name": "feature-x"}
        service = GitBranchService(mock_db, client=mock_client)

        exists = await service.branch_exists(sample_repo.id, "feature-x")
        assert exists is True
        mock_client.get_branch.assert_called_once_with("acme", "web-platform", "feature-x")

    @pytest.mark.asyncio
    async def test_branch_exists_false_on_404(self, mock_db, mock_client, sample_repo):
        mock_db.scalars.return_value.first.return_value = sample_repo
        mock_client.get_branch.side_effect = GitHubAPIError("Not Found", status_code=404)
        service = GitBranchService(mock_db, client=mock_client)

        exists = await service.branch_exists(sample_repo.id, "nonexistent-branch")
        assert exists is False

    @pytest.mark.asyncio
    async def test_branch_exists_raises_on_500(self, mock_db, mock_client, sample_repo):
        mock_db.scalars.return_value.first.return_value = sample_repo
        mock_client.get_branch.side_effect = GitHubAPIError("Server error", status_code=500)
        service = GitBranchService(mock_db, client=mock_client)

        with pytest.raises(APIError) as exc_info:
            await service.branch_exists(sample_repo.id, "some-branch")
        assert exc_info.value.status_code == 502

    # ----- create_agent_branch ---------------------------------------------

    @pytest.mark.asyncio
    async def test_create_agent_branch_success(self, mock_db, mock_client, sample_repo):
        mock_db.scalars.return_value.first.return_value = sample_repo
        task_id = UUID("f47ac10b-58cc-4372-a567-0e02b2c3d479")

        # branch_exists returns False (404 on get_branch for agent/task-f47ac10b)
        # then base branch get_branch returns source commit
        def get_branch_side_effect(owner, repo, branch):
            if branch == "agent/task-f47ac10b":
                raise GitHubAPIError("Not Found", status_code=404)
            if branch == "main":
                return {"name": "main", "commit": {"sha": "c0ffee1234567890"}}
            raise GitHubAPIError("Not Found", status_code=404)

        mock_client.get_branch.side_effect = get_branch_side_effect
        mock_client.create_branch.return_value = {"ref": "refs/heads/agent/task-f47ac10b"}

        service = GitBranchService(mock_db, client=mock_client)
        created_branch = await service.create_agent_branch(sample_repo.id, task_id)

        assert created_branch == "agent/task-f47ac10b"
        mock_client.create_branch.assert_called_once_with(
            "acme",
            "web-platform",
            "agent/task-f47ac10b",
            "c0ffee1234567890",
        )

    @pytest.mark.asyncio
    async def test_create_agent_branch_already_exists_is_idempotent(self, mock_db, mock_client, sample_repo):
        mock_db.scalars.return_value.first.return_value = sample_repo
        task_id = UUID("f47ac10b-58cc-4372-a567-0e02b2c3d479")

        # branch already exists
        mock_client.get_branch.return_value = {"name": "agent/task-f47ac10b"}

        service = GitBranchService(mock_db, client=mock_client)
        created_branch = await service.create_agent_branch(sample_repo.id, task_id)

        assert created_branch == "agent/task-f47ac10b"
        mock_client.create_branch.assert_not_called()

    # ----- delete_branch ---------------------------------------------------

    @pytest.mark.asyncio
    async def test_delete_branch_success(self, mock_db, mock_client, sample_repo):
        mock_db.scalars.return_value.first.return_value = sample_repo
        mock_client.delete_branch.return_value = None
        service = GitBranchService(mock_db, client=mock_client)

        result = await service.delete_branch(sample_repo.id, "agent/task-f47ac10b")
        assert result is True
        mock_client.delete_branch.assert_called_once_with("acme", "web-platform", "agent/task-f47ac10b")

    @pytest.mark.asyncio
    async def test_delete_default_branch_rejected(self, mock_db, mock_client, sample_repo):
        mock_db.scalars.return_value.first.return_value = sample_repo
        service = GitBranchService(mock_db, client=mock_client)

        with pytest.raises(APIError) as exc_info:
            await service.delete_branch(sample_repo.id, "main")
        assert exc_info.value.status_code == 400
        assert exc_info.value.code == ErrorCode.INVALID_REQUEST
        mock_client.delete_branch.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_branch_returns_true(self, mock_db, mock_client, sample_repo):
        mock_db.scalars.return_value.first.return_value = sample_repo
        mock_client.delete_branch.side_effect = GitHubAPIError("Not Found", status_code=404)
        service = GitBranchService(mock_db, client=mock_client)

        result = await service.delete_branch(sample_repo.id, "agent/task-old")
        assert result is True
