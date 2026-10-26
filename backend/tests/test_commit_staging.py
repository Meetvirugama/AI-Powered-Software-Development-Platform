"""Tests for Parth — Week 2 Day 4: Commit Staging.

Verifies:
1. Agent changes in the local workspace are staged into a Git commit:
   agent/task-f47ac10b
     └── commit: "agent: Add JWT service (step 1 of 3)"
2. Commit is created on the agent branch in the local workspace clone.
3. No push to GitHub occurs (Push is deferred to Week 3).
4. Specific file staging vs. staging all changes (git add -A).
5. Error handling when there are no changes staged or invalid workspace directory.
6. API endpoint POST /api/v1/repositories/{id}/source/commit.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.errors import APIError
from app.main import app
from app.models.repository import Repository
from app.services.git_branch import CommitResult, GitBranchService, format_agent_branch_name


@pytest.fixture
def repo_id() -> UUID:
    return uuid4()


@pytest.fixture
def user_id() -> UUID:
    return uuid4()


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
    return db


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

    # Initialize repository and base branch
    run_cmd("init", "-b", "main")
    run_cmd("config", "user.name", "Test Setup")
    run_cmd("config", "user.email", "setup@test.local")

    # Initial commit on main
    readme = ws / "README.md"
    readme.write_text("# Web Platform\nInitial content\n", encoding="utf-8")
    run_cmd("add", "README.md")
    run_cmd("commit", "-m", "Initial commit on main")

    # Create and switch to agent branch
    run_cmd("checkout", "-b", "agent/task-f47ac10b")

    return ws


# ═══════════════════════════════════════════════════════════════════════════
# 1. Commit Staging Unit Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestCommitStagingService:
    """Test suite for GitBranchService.commit workspace operations."""

    @pytest.mark.asyncio
    async def test_commit_creates_commit_on_agent_branch(
        self, mock_db, git_workspace: Path, repo_id: UUID
    ):
        """Creates a commit on agent/task-f47ac10b with expected message and stats."""
        # Add new file in workspace
        service_file = git_workspace / "jwt.service.ts"
        service_file.write_text("export class JwtService {}\n", encoding="utf-8")

        service = GitBranchService(mock_db)
        commit_message = "agent: Add JWT service (step 1 of 3)"

        result = await service.commit(
            workspace_path=git_workspace,
            commit_message=commit_message,
            task_id="f47ac10b",
            repository_id=repo_id,
            author_name="Agent Worker",
            author_email="agent@ai-platform.local",
        )

        assert isinstance(result, CommitResult)
        assert len(result.commit_sha) == 40
        assert result.branch == "agent/task-f47ac10b"
        assert result.message == commit_message
        assert "jwt.service.ts" in result.files_changed
        assert result.pushed is False  # MUST NEVER PUSH IN WEEK 2

        # Verify via git log that the commit exists in the workspace
        proc = subprocess.run(
            ["git", "log", "-1", "--pretty=format:%s|%an|%ae"],
            cwd=str(git_workspace),
            capture_output=True,
            text=True,
            check=True,
        )
        msg, author, email = proc.stdout.split("|")
        assert msg == commit_message
        assert author == "Agent Worker"
        assert email == "agent@ai-platform.local"

    @pytest.mark.asyncio
    async def test_commit_specific_files_only(
        self, mock_db, git_workspace: Path, repo_id: UUID
    ):
        """Stages only the specified files, leaving other modifications unstaged."""
        file_a = git_workspace / "auth.ts"
        file_b = git_workspace / "unrelated.txt"
        file_a.write_text("// auth logic\n", encoding="utf-8")
        file_b.write_text("// unrelated file\n", encoding="utf-8")

        service = GitBranchService(mock_db)
        result = await service.commit(
            workspace_path=git_workspace,
            commit_message="agent: Stage auth.ts only",
            files=["auth.ts"],
        )

        assert result.files_changed == ["auth.ts"]

        # unrelated.txt should still be untracked
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(git_workspace),
            capture_output=True,
            text=True,
            check=True,
        )
        assert "?? unrelated.txt" in proc.stdout

    @pytest.mark.asyncio
    async def test_commit_no_changes_raises_error(
        self, mock_db, git_workspace: Path
    ):
        """Raises APIError(400) if no files are modified/staged."""
        service = GitBranchService(mock_db)

        with pytest.raises(APIError) as exc_info:
            await service.commit(
                workspace_path=git_workspace,
                commit_message="agent: No changes",
                allow_empty=False,
            )
        assert exc_info.value.status_code == 400
        assert "No changes staged" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_commit_allow_empty(
        self, mock_db, git_workspace: Path
    ):
        """Allows empty commit when allow_empty is True."""
        service = GitBranchService(mock_db)
        result = await service.commit(
            workspace_path=git_workspace,
            commit_message="agent: Empty checkpoint commit",
            allow_empty=True,
        )
        assert isinstance(result, CommitResult)
        assert result.files_changed == []

    @pytest.mark.asyncio
    async def test_commit_switches_to_task_branch_if_on_different_branch(
        self, mock_db, git_workspace: Path
    ):
        """Switches to the expected agent branch before committing if on another branch."""
        # Checkout main first
        subprocess.run(["git", "checkout", "main"], cwd=str(git_workspace), check=True)

        new_file = git_workspace / "helper.py"
        new_file.write_text("def helper(): pass\n", encoding="utf-8")

        service = GitBranchService(mock_db)
        result = await service.commit(
            workspace_path=git_workspace,
            commit_message="agent: Add helper on agent branch",
            task_id="f47ac10b",
        )

        assert result.branch == "agent/task-f47ac10b"

    @pytest.mark.asyncio
    async def test_commit_non_existent_workspace_raises_400(self, mock_db):
        """Non-existent workspace path raises 400."""
        service = GitBranchService(mock_db)
        with pytest.raises(APIError) as exc:
            await service.commit(
                workspace_path="C:/non_existent_path_xyz_123",
                commit_message="test",
            )
        assert exc.value.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════
# 2. REST API Route Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestCommitStagingRoutes:
    """Test suite for POST /api/v1/repositories/{id}/source/commit."""

    def _setup_auth(self, monkeypatch):
        """Configure JWT and Redis mocks for authenticated requests."""
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
        return fake_redis

    def test_commit_staging_endpoint_success(
        self, mock_db, git_workspace: Path, repo_id: UUID, user_id: UUID, monkeypatch
    ):
        self._setup_auth(monkeypatch)
        from app.core.security import create_access_token

        # Create a file to stage
        new_file = git_workspace / "route_test.txt"
        new_file.write_text("hello from route test", encoding="utf-8")

        app.dependency_overrides[get_db] = lambda: mock_db
        client = TestClient(app)

        payload = {
            "workspace_path": str(git_workspace),
            "commit_message": "agent: Add route_test.txt",
            "task_id": "f47ac10b",
            "author_name": "API Agent",
            "author_email": "api-agent@platform.local",
        }

        token, _ = create_access_token(str(user_id))
        headers = {"Authorization": f"Bearer {token}"}
        response = client.post(
            f"/api/v1/repositories/{repo_id}/source/commit",
            json=payload,
            headers=headers,
        )

        app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["branch"] == "agent/task-f47ac10b"
        assert data["message"] == "agent: Add route_test.txt"
        assert "route_test.txt" in data["files_changed"]
        assert data["pushed"] is False

