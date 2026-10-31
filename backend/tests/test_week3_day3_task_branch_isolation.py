"""Tests for Parth — Week 3 Day 3: Task Branch Isolation & Base Revision Validation (F33 / W3-04).

Verifies:
1. `GitBranchService.resolve_base_revision`:
   - Default branch resolution when base_revision is None or empty.
   - Commit SHA resolution (both 40-char and short hex).
   - Branch and tag name resolution.
   - 404 error handling for missing commit SHA or missing branch.
   - Strict rejection of path traversal ('..'), null bytes, and CLI flag injection.
2. `create_isolated_task_workspace`:
   - Creation of dedicated `.workspaces/task-{id}` directory.
   - Protection against path traversal and traversal escapes.
3. `GitBranchService.setup_task_branch_isolation`:
   - Remote branch creation `agent/task-{id}` from base revision SHA.
   - Idempotency when remote branch already exists.
   - Local workspace git checkout/branch isolation.
   - Rejection of protected branch names (Rule 563).
4. `GitHubSourceService.validate_base_revision` and `setup_task_branch`.
5. `GitHubService.create_task_branch`.
6. API Endpoints:
   - POST /api/v1/repositories/{id}/source/task-branch/isolate
   - POST /api/v1/repositories/{id}/source/task-branch/validate-base
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

os.environ["JWT_SECRET"] = "test-jwt-secret-key-for-parth-week3-day3-tests-12345"

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.errors import APIError, ErrorCode
from app.core.security import create_access_token
from app.integrations.github.client import GitHubAPIError, GitHubClient
from app.integrations.github.schemas import (
    BaseRevisionValidationRequest,
    BaseRevisionValidationResponse,
    BranchIsolationCheck,
    TaskBranchIsolationRequest,
    TaskBranchIsolationResponse,
)
from app.integrations.github.service import GitHubService, GitHubSourceService
from app.main import app
from app.models.repository import Repository
from app.models.user import User
from app.services.git_branch import (
    GitBranchService,
    create_isolated_task_workspace,
    format_agent_branch_name,
)


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def setup_jwt_secret(monkeypatch):
    from app.core.config import get_settings
    settings = get_settings()
    old_secret = settings.jwt_secret
    settings.jwt_secret = "test-jwt-secret-key-for-parth-week3-day3-tests-12345"

    class FakeRedis:
        def exists(self, key):
            return False

    monkeypatch.setattr("app.core.auth.get_redis", lambda: FakeRedis())
    yield
    settings.jwt_secret = old_secret


@pytest.fixture
def repo_id() -> UUID:
    return uuid4()


@pytest.fixture
def user_id() -> UUID:
    return uuid4()


@pytest.fixture
def task_id() -> UUID:
    return UUID("f47ac10b-58cc-4372-a567-0e02b2c3d479")


@pytest.fixture
def sample_repo(repo_id: UUID, user_id: UUID) -> Repository:
    repo = MagicMock(spec=Repository)
    repo.id = repo_id
    repo.user_id = user_id
    repo.installation_id = "inst-123"
    repo.owner = "acme"
    repo.name = "web-platform"
    repo.default_branch = "main"
    return repo


@pytest.fixture
def mock_db(sample_repo: Repository):
    db = MagicMock()
    db.scalars.return_value.first.return_value = sample_repo
    db.execute.return_value.scalar_one_or_none.return_value = sample_repo
    db.get.return_value = None
    return db


@pytest.fixture
def mock_client():
    client = MagicMock(spec=GitHubClient)
    client.get_branch = AsyncMock()
    client.get_commit = AsyncMock()
    client.get_ref = AsyncMock()
    client.create_branch = AsyncMock()
    return client


@pytest.fixture
def git_workspace(tmp_path: Path) -> Path:
    """Initialize a real temporary git repository as an agent workspace."""
    ws = tmp_path / "workspace_task_f47ac10b"
    ws.mkdir(parents=True, exist_ok=True)

    def run_cmd(*args: str):
        subprocess.run(
            ["git", *args],
            cwd=str(ws),
            check=True,
            capture_output=True,
            text=True,
        )

    run_cmd("init", "-b", "main")
    run_cmd("config", "user.name", "Test Setup")
    run_cmd("config", "user.email", "setup@test.local")

    readme = ws / "README.md"
    readme.write_text("# Web Platform\nInitial content\n", encoding="utf-8")
    run_cmd("add", "README.md")
    run_cmd("commit", "-m", "Initial commit on main")
    return ws


# ═══════════════════════════════════════════════════════════════════════════
# 1. Base Revision Validation & Resolution Unit Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestBaseRevisionResolution:
    """Tests for GitBranchService.resolve_base_revision."""

    @pytest.mark.asyncio
    async def test_resolve_default_branch_when_none(self, mock_db, mock_client, sample_repo):
        service = GitBranchService(mock_db, client=mock_client)
        mock_client.get_branch.return_value = {"commit": {"sha": "sha-main-123"}}

        ref, sha, ref_type = await service.resolve_base_revision(sample_repo.id, None)

        assert ref == "main"
        assert sha == "sha-main-123"
        assert ref_type == "branch"
        mock_client.get_branch.assert_called_once_with("acme", "web-platform", "main")

    @pytest.mark.asyncio
    async def test_resolve_commit_sha(self, mock_db, mock_client, sample_repo):
        service = GitBranchService(mock_db, client=mock_client)
        commit_sha = "abcdef1234567890abcdef1234567890abcdef12"
        mock_client.get_commit.return_value = {"sha": commit_sha}

        ref, sha, ref_type = await service.resolve_base_revision(sample_repo.id, commit_sha)

        assert ref == commit_sha
        assert sha == commit_sha
        assert ref_type == "commit"
        mock_client.get_commit.assert_called_once_with("acme", "web-platform", commit_sha)

    @pytest.mark.asyncio
    async def test_resolve_branch_name(self, mock_db, mock_client, sample_repo):
        service = GitBranchService(mock_db, client=mock_client)
        mock_client.get_branch.return_value = {"commit": {"sha": "sha-feat-999"}}

        ref, sha, ref_type = await service.resolve_base_revision(sample_repo.id, "feature/auth")

        assert ref == "feature/auth"
        assert sha == "sha-feat-999"
        assert ref_type == "branch"
        mock_client.get_branch.assert_called_once_with("acme", "web-platform", "feature/auth")

    @pytest.mark.asyncio
    async def test_resolve_tag_via_ref(self, mock_db, mock_client, sample_repo):
        service = GitBranchService(mock_db, client=mock_client)
        mock_client.get_branch.side_effect = GitHubAPIError("Branch not found", status_code=404)
        mock_client.get_ref.side_effect = [
            GitHubAPIError("heads not found", status_code=404),
            {"object": {"sha": "sha-tag-v1"}},  # tags found
        ]

        ref, sha, ref_type = await service.resolve_base_revision(sample_repo.id, "v1.0.0")

        assert ref == "v1.0.0"
        assert sha == "sha-tag-v1"
        assert ref_type == "tag"

    @pytest.mark.asyncio
    async def test_resolve_missing_base_revision_raises_404(self, mock_db, mock_client, sample_repo):
        service = GitBranchService(mock_db, client=mock_client)
        mock_client.get_branch.side_effect = GitHubAPIError("Not found", status_code=404)
        mock_client.get_ref.side_effect = GitHubAPIError("Not found", status_code=404)

        with pytest.raises(APIError) as exc_info:
            await service.resolve_base_revision(sample_repo.id, "nonexistent-branch")

        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_rejects_unsafe_base_revision(self, mock_db, mock_client, sample_repo):
        service = GitBranchService(mock_db, client=mock_client)

        for unsafe in ["../escape", "main\x00extra", "--upload-pack", ""]:
            if not unsafe:
                unsafe = "   "
            with pytest.raises(APIError):
                await service.resolve_base_revision(sample_repo.id, unsafe)


# ═══════════════════════════════════════════════════════════════════════════
# 2. Workspace Creation & Path Traversal Guards (F33)
# ═══════════════════════════════════════════════════════════════════════════

class TestWorkspaceIsolationGuards:
    """Tests for create_isolated_task_workspace and workspace path safety."""

    def test_create_isolated_task_workspace_success(self, tmp_path: Path):
        task_id = "f47ac10b"
        ws_path = create_isolated_task_workspace(tmp_path, task_id)

        assert ws_path.exists()
        assert ws_path.is_dir()
        assert ws_path.name == "task-f47ac10b"
        assert ws_path.parent.name == ".workspaces"

    def test_create_isolated_task_workspace_rejects_path_traversal(self, tmp_path: Path):
        with pytest.raises(APIError) as exc:
            create_isolated_task_workspace(str(tmp_path) + "/../escaped", "f47ac10b")
        assert exc.value.status_code == 400

    def test_create_isolated_task_workspace_rejects_malicious_task_id(self, tmp_path: Path):
        with pytest.raises(APIError):
            create_isolated_task_workspace(tmp_path, "../escape")
        with pytest.raises(APIError):
            create_isolated_task_workspace(tmp_path, "-invalid")


# ═══════════════════════════════════════════════════════════════════════════
# 3. Task Branch Isolation Setup Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestTaskBranchIsolationSetup:
    """Tests for GitBranchService.setup_task_branch_isolation."""

    @pytest.mark.asyncio
    async def test_setup_remote_branch_creation(self, mock_db, mock_client, sample_repo, task_id):
        service = GitBranchService(mock_db, client=mock_client)

        def mock_get_branch(owner, repo, branch):
            if branch == "agent/task-f47ac10b":
                raise GitHubAPIError("Branch not found", status_code=404)
            return {"commit": {"sha": "sha-base-100"}}

        mock_client.get_branch.side_effect = mock_get_branch
        mock_client.create_branch.return_value = {"ref": "refs/heads/agent/task-f47ac10b"}

        resp = await service.setup_task_branch_isolation(
            repository_id=sample_repo.id,
            task_id=task_id,
            base_revision="main",
        )

        assert resp.branch_name == "agent/task-f47ac10b"
        assert resp.base_branch == "main"
        assert resp.base_sha == "sha-base-100"
        assert resp.is_isolated is True
        assert resp.status == "created"
        mock_client.create_branch.assert_called_once_with(
            "acme", "web-platform", "agent/task-f47ac10b", "sha-base-100"
        )

    @pytest.mark.asyncio
    async def test_setup_remote_branch_already_exists_is_idempotent(
        self, mock_db, mock_client, sample_repo, task_id
    ):
        service = GitBranchService(mock_db, client=mock_client)
        mock_client.get_branch.return_value = {"commit": {"sha": "sha-base-100"}}

        resp = await service.setup_task_branch_isolation(
            repository_id=sample_repo.id,
            task_id=task_id,
            base_revision="main",
        )

        assert resp.branch_name == "agent/task-f47ac10b"
        assert resp.status == "ready"
        mock_client.create_branch.assert_not_called()

    @pytest.mark.asyncio
    async def test_setup_task_branch_with_workspace_checkout(
        self, mock_db, mock_client, sample_repo, task_id, git_workspace: Path
    ):
        service = GitBranchService(mock_db, client=mock_client)
        mock_client.get_branch.return_value = {"commit": {"sha": "sha-base-100"}}

        resp = await service.setup_task_branch_isolation(
            repository_id=sample_repo.id,
            task_id=task_id,
            base_revision="main",
            workspace_path=git_workspace,
        )

        assert resp.status == "isolated"
        assert resp.workspace_path == str(git_workspace)

        # Verify git checkout in workspace
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(git_workspace),
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout.strip() == "agent/task-f47ac10b"

    @pytest.mark.asyncio
    async def test_rejects_protected_branch_name_conflict(self, mock_db, sample_repo):
        service = GitBranchService(mock_db)
        with patch("app.services.git_branch.format_agent_branch_name", return_value="main"):
            with pytest.raises(APIError) as exc_info:
                await service.setup_task_branch_isolation(
                    repository_id=sample_repo.id,
                    task_id=uuid4(),
                    base_revision="main",
                )
            assert exc_info.value.status_code == 400
            assert "protected branch" in exc_info.value.message.lower()


# ═══════════════════════════════════════════════════════════════════════════
# 4. GitHubSourceService & GitHubService Integration
# ═══════════════════════════════════════════════════════════════════════════

class TestServiceMethodsWeek3Day3:
    """Tests for GitHubSourceService and GitHubService Day 3 methods."""

    @pytest.mark.asyncio
    async def test_github_source_service_validate_base_revision(self, mock_db, sample_repo, user_id):
        source_svc = GitHubSourceService(mock_db)
        with patch.object(
            GitBranchService,
            "resolve_base_revision",
            new=AsyncMock(return_value=("main", "sha-abc-123", "branch")),
        ):
            resp = await source_svc.validate_base_revision(sample_repo.id, user_id, "main")
            assert isinstance(resp, BaseRevisionValidationResponse)
            assert resp.base_revision == "main"
            assert resp.commit_sha == "sha-abc-123"
            assert resp.ref_type == "branch"
            assert resp.is_valid is True

    @pytest.mark.asyncio
    async def test_github_source_service_setup_task_branch(self, mock_db, sample_repo, user_id, task_id):
        source_svc = GitHubSourceService(mock_db)
        expected = TaskBranchIsolationResponse(
            task_id=task_id,
            repository_id=sample_repo.id,
            branch_name="agent/task-f47ac10b",
            base_branch="main",
            base_sha="sha-123",
            workspace_path="/tmp/test",
            is_isolated=True,
            status="isolated",
        )
        with patch.object(
            GitBranchService,
            "setup_task_branch_isolation",
            new=AsyncMock(return_value=expected),
        ):
            resp = await source_svc.setup_task_branch(
                sample_repo.id, user_id, task_id, "main", "/tmp/test"
            )
            assert resp.branch_name == "agent/task-f47ac10b"
            assert resp.status == "isolated"

    @pytest.mark.asyncio
    async def test_github_service_create_task_branch(self):
        gh_svc = GitHubService()
        with patch.object(gh_svc, "_resolve_token", new=AsyncMock(return_value="token-123")), \
             patch("app.integrations.github.service.GitHubClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get_branch.return_value = {"commit": {"sha": "sha-main-999"}}
            mock_client.create_branch.return_value = {"ref": "refs/heads/agent/task-f47ac10b"}
            mock_client_cls.return_value = mock_client

            result = await gh_svc.create_task_branch(
                owner="acme",
                repo="platform",
                task_id="f47ac10b",
                base_revision="main",
            )
            assert result["branch_name"] == "agent/task-f47ac10b"
            assert result["base_sha"] == "sha-main-999"


# ═══════════════════════════════════════════════════════════════════════════
# 5. API Endpoints Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestTaskBranchIsolationEndpoints:
    """Tests for POST /repositories/{id}/source/task-branch/isolate and validate-base."""

    def test_isolate_task_branch_endpoint_success(self, mock_db, sample_repo, user_id, task_id):
        expected_resp = TaskBranchIsolationResponse(
            task_id=task_id,
            repository_id=sample_repo.id,
            branch_name="agent/task-f47ac10b",
            base_branch="main",
            base_sha="sha-isolated-456",
            workspace_path="/tmp/workspace",
            is_isolated=True,
            status="isolated",
        )

        app.dependency_overrides[get_db] = lambda: mock_db
        client = TestClient(app)

        with patch.object(
            GitBranchService,
            "setup_task_branch_isolation",
            new=AsyncMock(return_value=expected_resp),
        ):
            payload = {
                "task_id": str(task_id),
                "base_revision": "main",
                "workspace_path": "/tmp/workspace",
                "create_workspace": False,
            }
            token, _ = create_access_token(str(user_id))
            headers = {"Authorization": f"Bearer {token}"}
            res = client.post(
                f"/api/v1/repositories/{sample_repo.id}/source/task-branch/isolate",
                json=payload,
                headers=headers,
            )

            app.dependency_overrides.clear()
            assert res.status_code == 200
            data = res.json()
            assert data["branch_name"] == "agent/task-f47ac10b"
            assert data["base_branch"] == "main"
            assert data["base_sha"] == "sha-isolated-456"
            assert data["is_isolated"] is True
            assert data["status"] == "isolated"

    def test_validate_base_revision_endpoint_success(self, mock_db, sample_repo, user_id):
        app.dependency_overrides[get_db] = lambda: mock_db
        client = TestClient(app)

        with patch.object(
            GitHubSourceService,
            "validate_base_revision",
            new=AsyncMock(
                return_value=BaseRevisionValidationResponse(
                    repository_id=sample_repo.id,
                    base_revision="feature/jwt",
                    commit_sha="sha-jwt-123456",
                    ref_type="branch",
                    is_valid=True,
                )
            ),
        ):
            payload = {"base_revision": "feature/jwt"}
            token, _ = create_access_token(str(user_id))
            headers = {"Authorization": f"Bearer {token}"}
            res = client.post(
                f"/api/v1/repositories/{sample_repo.id}/source/task-branch/validate-base",
                json=payload,
                headers=headers,
            )

            app.dependency_overrides.clear()
            assert res.status_code == 200
            data = res.json()
            assert data["base_revision"] == "feature/jwt"
            assert data["commit_sha"] == "sha-jwt-123456"
            assert data["ref_type"] == "branch"
            assert data["is_valid"] is True
