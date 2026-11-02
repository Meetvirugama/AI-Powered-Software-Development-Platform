"""End-to-End Acceptance and Master Integration Tests for Week 3 Day 7.

Validates:
- Complete 17-step autonomous lifecycle:
  Finding -> Issue -> Plan -> Approval Gate -> Task Branch Isolation ->
  Workspace Setup -> Edit -> Commit -> Restricted Testing ->
  Bounded Repair -> Verification (12 checks) -> Publication Gate ->
  Push agent/task-{id} -> GitHub Draft PR.
- Zero manual intervention between Plan Approval and Draft PR creation.
- Approval gate blocking unapproved task plans.
- Publication gate blocking unauthorized push and PR creation.
- Bounded self-repair loop execution within autonomous pipeline.
- REST endpoint POST /api/v1/repositories/{id}/source/task/execute-pipeline.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

os.environ["JWT_SECRET"] = "test-jwt-secret-for-week3-day7-acceptance-12345"

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.security import create_access_token
from app.integrations.github.schemas import PullRequestInfo, TaskPipelineRequest, TaskPipelineResponse
from app.main import app
from app.models.pull_request import PullRequest
from app.models.repository import Repository
from app.models.user import User
from app.repositories.pull_request_repository import PullRequestRepository
from app.schemas.task import TaskStatus
from app.services.git_branch import GitBranchService, format_agent_branch_name
from app.services.task_orchestrator import TaskExecutionOrchestrator

TaskPipelineRequest.__test__ = False
TaskPipelineResponse.__test__ = False


@pytest.fixture
def base_repo_workspace(tmp_path: Path) -> tuple[Path, str]:
    """Create a temporary initialized Git repository representing the repository workspace."""
    repo_dir = tmp_path / "repo_base"
    repo_dir.mkdir(parents=True)

    subprocess.run(["git", "init", "-b", "main"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test Committer"], cwd=str(repo_dir), check=True)
    subprocess.run(["git", "config", "user.email", "committer@example.com"], cwd=str(repo_dir), check=True)

    init_file = repo_dir / "app.py"
    init_file.write_text("def add(a, b):\n    return a + b\n")

    test_file = repo_dir / "test_app.py"
    test_file.write_text("from app import add\n\ndef test_add():\n    assert add(2, 3) == 5\n")

    subprocess.run(["git", "add", "."], cwd=str(repo_dir), check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit on base branch"], cwd=str(repo_dir), check=True)

    res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo_dir), check=True, capture_output=True, text=True)
    base_sha = res.stdout.strip()
    return repo_dir, base_sha


@pytest.fixture
def client_setup():
    user_id = uuid4()
    repo_id = uuid4()

    mock_db = MagicMock()
    mock_user = User(
        id=user_id,
        github_id=12345,
        login="testuser",
        email="test@example.com",
    )
    repo = Repository(
        id=repo_id,
        user_id=user_id,
        name="test-repo",
        owner="testuser",
        default_branch="main",
        installation_id=uuid4(),
        github_repo_id="12345",
    )

    def mock_execute(stmt):
        res = MagicMock()
        res.scalar_one_or_none.return_value = repo
        return res

    mock_db.execute = mock_execute
    mock_db.get.return_value = repo
    mock_db.scalars.return_value.first.return_value = repo

    app.dependency_overrides[get_db] = lambda: mock_db
    test_client = TestClient(app)

    from app.core.config import get_settings
    get_settings.cache_clear()

    with patch("app.core.security.get_settings") as mock_sec_settings, \
         patch("app.core.auth.get_settings") as mock_auth_settings, \
         patch("app.core.auth.get_redis") as mock_redis:

        mock_s = MagicMock()
        mock_s.jwt_secret = "test-jwt-secret-key-12345"
        mock_s.jwt_algorithm = "HS256"
        mock_s.access_token_expire_seconds = 3600
        mock_s.jwt_expire_minutes = 60
        mock_sec_settings.return_value = mock_s
        mock_auth_settings.return_value = mock_s
        mock_redis.return_value.exists.return_value = False

        token, _ = create_access_token(str(user_id))
        auth_headers = {"Authorization": f"Bearer {token}"}

        yield test_client, repo_id, auth_headers
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 1. Full 17-Step End-to-End Orchestrator Pipeline
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_17_step_pipeline_happy_path(base_repo_workspace, tmp_path):
    """Execute complete 17-step pipeline from plan to verified Draft PR with zero manual interventions."""
    repo_dir, base_sha = base_repo_workspace
    task_id = uuid4()
    repo_id = uuid4()
    user_id = uuid4()
    short_id = str(task_id)[:8]
    task_ws = tmp_path / f"task-{short_id}"

    import shutil
    shutil.copytree(repo_dir, task_ws)

    mock_db = MagicMock()
    repo = Repository(
        id=repo_id,
        user_id=user_id,
        name="test-repo",
        owner="testuser",
        default_branch="main",
        installation_id=uuid4(),
        github_repo_id="12345",
    )
    mock_db.get.return_value = repo

    orchestrator = TaskExecutionOrchestrator(mock_db)

    # Mock remote GitHub API operations in publish_task_draft_pr
    mock_gh_client = AsyncMock()
    mock_gh_client.create_branch = AsyncMock()
    mock_gh_client.create_pull_request = AsyncMock(return_value={
        "number": 42,
        "title": f"Autonomous fix for task {short_id}",
        "html_url": f"https://github.com/testuser/test-repo/pull/42",
        "state": "open",
        "base": {"ref": "main"},
        "head": {"ref": format_agent_branch_name(task_id)},
        "created_at": "2026-11-02T12:00:00Z",
        "draft": True,
    })

    with patch.object(GitBranchService, "_get_client_for_repo", return_value=mock_gh_client), \
         patch.object(GitBranchService, "branch_exists", return_value=False), \
         patch.object(GitBranchService, "_get_repository", return_value=repo), \
         patch.object(PullRequestRepository, "get_by_task_id", return_value=None), \
         patch.object(PullRequestRepository, "create_or_update", return_value=MagicMock(pr_number=42)):

        result = await orchestrator.execute_task_pipeline(
            repository_id=repo_id,
            task_id=task_id,
            user_id=user_id,
            has_approved_plan=True,
            publication_authorized=True,
            base_revision=base_sha,
            target_file="app.py",
            new_content="def add(a, b):\n    '''Add two numbers safely.'''\n    return int(a) + int(b)\n",
            commit_message=f"feat(app): add input casting for task {short_id}",
            test_command="pytest",
            workspace_path=task_ws,
        )

    # Assertions on complete 17-step execution
    assert result.task_id == task_id
    assert result.final_status == TaskStatus.DRAFT_PR_CREATED.value
    assert result.verification_passed is True
    assert result.branch_name == f"agent/task-{short_id}"
    assert result.pr_number == 42
    assert "Draft PR created" in result.message

    # Verify all 17 steps were recorded
    step_numbers = [s.step_number for s in result.steps_executed]
    assert 1 in step_numbers
    assert 3 in step_numbers   # Approval Gate
    assert 5 in step_numbers   # Rule 563 Branch Isolation
    assert 8 in step_numbers   # Apply Changes
    assert 11 in step_numbers  # Restricted Test Execution
    assert 14 in step_numbers  # Independent Verification
    assert 15 in step_numbers  # Publication Gate
    assert 17 in step_numbers  # Push & Draft PR


# ---------------------------------------------------------------------------
# 2. Approval Gate Enforcement
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_blocked_without_plan_approval(base_repo_workspace, tmp_path):
    """Enforce that unapproved plan stops execution at Step 3 without modifying branch or workspace."""
    repo_dir, base_sha = base_repo_workspace
    task_id = uuid4()
    repo_id = uuid4()
    user_id = uuid4()
    task_ws = tmp_path / "task-unapproved"

    orchestrator = TaskExecutionOrchestrator(MagicMock())

    result = await orchestrator.execute_task_pipeline(
        repository_id=repo_id,
        task_id=task_id,
        user_id=user_id,
        has_approved_plan=False,  # Unapproved
        publication_authorized=True,
        base_revision=base_sha,
        target_file="app.py",
        new_content="unapproved content",
        commit_message="unapproved",
        workspace_path=task_ws,
    )

    assert result.final_status == TaskStatus.BLOCKED.value
    assert "Human approval gate required" in result.message
    assert result.pr_number is None
    assert result.verification_passed is False

    # Verify stopped at Step 3
    failed_steps = [s for s in result.steps_executed if s.status == "FAILED"]
    assert len(failed_steps) == 1
    assert failed_steps[0].step_number == 3


# ---------------------------------------------------------------------------
# 3. Publication Gate Enforcement
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_halts_at_ready_for_publication(base_repo_workspace, tmp_path):
    """Enforce that without publication_authorized=True, pipeline stops at READY_FOR_PUBLICATION without push/PR."""
    repo_dir, base_sha = base_repo_workspace
    task_id = uuid4()
    repo_id = uuid4()
    user_id = uuid4()
    short_id = str(task_id)[:8]
    task_ws = tmp_path / f"task-{short_id}"

    import shutil
    shutil.copytree(repo_dir, task_ws)

    mock_db = MagicMock()
    repo = Repository(
        id=repo_id,
        user_id=user_id,
        name="test-repo",
        owner="testuser",
        default_branch="main",
        installation_id=uuid4(),
        github_repo_id="12345",
    )
    mock_db.get.return_value = repo

    orchestrator = TaskExecutionOrchestrator(mock_db)

    mock_gh_client = AsyncMock()
    mock_gh_client.create_branch = AsyncMock()

    with patch.object(GitBranchService, "_get_client_for_repo", return_value=mock_gh_client), \
         patch.object(GitBranchService, "branch_exists", return_value=False), \
         patch.object(GitBranchService, "_get_repository", return_value=repo):
        result = await orchestrator.execute_task_pipeline(
            repository_id=repo_id,
            task_id=task_id,
            user_id=user_id,
            has_approved_plan=True,
            publication_authorized=False,  # NOT authorized
            base_revision=base_sha,
            target_file="app.py",
            new_content="def add(a, b):\n    '''Updated add.'''\n    return a + b\n",
            commit_message=f"feat: update app for task {short_id}",
            test_command="pytest",
            workspace_path=task_ws,
        )

    assert result.final_status == TaskStatus.READY_FOR_PUBLICATION.value
    assert result.verification_passed is True
    assert result.pr_number is None
    assert "Awaiting human publication authorization" in result.message

    blocked_steps = [s for s in result.steps_executed if s.status == "BLOCKED"]
    assert len(blocked_steps) == 1
    assert blocked_steps[0].step_number == 15


# ---------------------------------------------------------------------------
# 4. Bounded Self-Repair Integration in Pipeline
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_with_bounded_self_repair(base_repo_workspace, tmp_path):
    """Pipeline encounters test failure, executes bounded self-repair, passes and creates Draft PR."""
    repo_dir, base_sha = base_repo_workspace
    task_id = uuid4()
    repo_id = uuid4()
    user_id = uuid4()
    short_id = str(task_id)[:8]
    task_ws = tmp_path / f"task-{short_id}"

    import shutil
    shutil.copytree(repo_dir, task_ws)

    mock_db = MagicMock()
    repo = Repository(
        id=repo_id,
        user_id=user_id,
        name="test-repo",
        owner="testuser",
        default_branch="main",
        installation_id=uuid4(),
        github_repo_id="12345",
    )
    mock_db.get.return_value = repo
    orchestrator = TaskExecutionOrchestrator(mock_db)

    # Initial broken content that causes syntax/assertion error
    broken_content = "def add(a, b):\n    return a - b  # Bug!\n"
    # Repair patch that fixes it
    repair_patch = """--- a/app.py
+++ b/app.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a - b  # Bug!
+    return a + b
"""

    mock_gh_client = AsyncMock()
    mock_gh_client.create_branch = AsyncMock()
    mock_gh_client.create_pull_request = AsyncMock(return_value={
        "number": 43,
        "title": f"Fix: Repaired bug for task {short_id}",
        "html_url": f"https://github.com/testuser/test-repo/pull/43",
        "state": "open",
        "base": {"ref": "main"},
        "head": {"ref": format_agent_branch_name(task_id)},
        "created_at": "2026-11-02T12:00:00Z",
        "draft": True,
    })

    with patch.object(GitBranchService, "_get_client_for_repo", return_value=mock_gh_client), \
         patch.object(GitBranchService, "branch_exists", return_value=False), \
         patch.object(GitBranchService, "_get_repository", return_value=repo), \
         patch.object(PullRequestRepository, "get_by_task_id", return_value=None), \
         patch.object(PullRequestRepository, "create_or_update", return_value=MagicMock(pr_number=43)):

        result = await orchestrator.execute_task_pipeline(
            repository_id=repo_id,
            task_id=task_id,
            user_id=user_id,
            has_approved_plan=True,
            publication_authorized=True,
            base_revision=base_sha,
            target_file="app.py",
            new_content=broken_content,
            commit_message=f"feat: buggy implementation {short_id}",
            test_command="pytest",
            workspace_path=task_ws,
            repair_patch=repair_patch,
        )

    assert result.final_status == TaskStatus.DRAFT_PR_CREATED.value
    assert result.verification_passed is True
    assert result.repair_attempts_used == 1
    assert result.pr_number == 43


# ---------------------------------------------------------------------------
# 5. REST Endpoint Acceptance Test
# ---------------------------------------------------------------------------

def test_api_task_execute_pipeline_endpoint(client_setup, base_repo_workspace, tmp_path):
    """Verify POST /api/v1/repositories/{id}/source/task/execute-pipeline REST API."""
    client, repo_id, auth_headers = client_setup
    repo_dir, base_sha = base_repo_workspace
    task_id = uuid4()
    short_id = str(task_id)[:8]
    task_ws = tmp_path / f"task-api-{short_id}"

    import shutil
    shutil.copytree(repo_dir, task_ws)

    mock_gh_client = AsyncMock()
    mock_gh_client.create_branch = AsyncMock()
    mock_gh_client.create_pull_request = AsyncMock(return_value={
        "number": 99,
        "title": f"Autonomous fix for task {short_id}",
        "html_url": f"https://github.com/testuser/test-repo/pull/99",
        "state": "open",
        "base": {"ref": "main"},
        "head": {"ref": format_agent_branch_name(task_id)},
        "created_at": "2026-11-02T12:00:00Z",
        "draft": True,
    })

    payload = {
        "task_id": str(task_id),
        "has_approved_plan": True,
        "publication_authorized": True,
        "base_revision": base_sha,
        "target_file": "app.py",
        "new_content": "def add(a, b):\n    '''API updated add.'''\n    return a + b\n",
        "commit_message": f"feat: api pipeline task {short_id}",
        "test_command": "pytest",
        "workspace_path": str(task_ws),
    }

    with patch.object(GitBranchService, "_get_client_for_repo", return_value=mock_gh_client), \
         patch.object(GitBranchService, "branch_exists", return_value=False), \
         patch.object(PullRequestRepository, "get_by_task_id", return_value=None), \
         patch.object(PullRequestRepository, "create_or_update", return_value=MagicMock(pr_number=99)):

        response = client.post(
            f"/api/v1/repositories/{repo_id}/source/task/execute-pipeline",
            json=payload,
            headers=auth_headers,
        )

    assert response.status_code == 200, f"Error: {response.text}"
    data = response.json()
    assert data["task_id"] == str(task_id)
    assert data["final_status"] == "DRAFT_PR_CREATED"
    assert data["verification_passed"] is True
    assert data["pr_number"] == 99
    assert len(data["steps_executed"]) >= 10
