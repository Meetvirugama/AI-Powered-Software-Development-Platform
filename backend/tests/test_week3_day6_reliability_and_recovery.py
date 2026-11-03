"""Unit and integration tests for Week 3 Day 6 deliverables.

Covers:
- Task state machine transition guards and illegal transition rejection.
- Remote base-revision drift detection.
- Worker restart recovery and repair budget preservation.
- Workspace boundary traversal protection and safe idempotent cleanup.
- Attack matrix and security hardening.
- REST endpoints for task recovery and cleanup.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

os.environ["JWT_SECRET"] = "test-jwt-secret-for-week3-day6-tests-12345"

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.errors import APIError, ErrorCode
from app.core.security import create_access_token
from app.main import app
from app.models.repository import Repository
from app.models.user import User
from app.schemas.task import TaskStatus
from app.services.git_branch import _DEFAULT_WORKSPACE_ROOT
from app.services.task_recovery import TaskRecoveryService


# ---------------------------------------------------------------------------
# Test Fixtures & Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def recovery_service():
    return TaskRecoveryService()


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
# 1. State Machine Transition Guards
# ---------------------------------------------------------------------------

def test_validate_task_transition_valid_paths(recovery_service):
    """Confirm canonical valid transitions pass without exception."""
    # Planning -> Pending Approval
    recovery_service.validate_task_transition(TaskStatus.PLANNING, TaskStatus.PENDING_APPROVAL)
    # Pending Approval -> Approved
    recovery_service.validate_task_transition(TaskStatus.PENDING_APPROVAL, TaskStatus.APPROVED)
    # Approved -> Workspace Setup
    recovery_service.validate_task_transition(TaskStatus.APPROVED, TaskStatus.WORKSPACE_SETUP)
    # Workspace Setup -> Executing
    recovery_service.validate_task_transition(TaskStatus.WORKSPACE_SETUP, TaskStatus.EXECUTING)
    # Executing -> Testing
    recovery_service.validate_task_transition(TaskStatus.EXECUTING, TaskStatus.TESTING)
    # Testing -> Repairing
    recovery_service.validate_task_transition(TaskStatus.TESTING, TaskStatus.REPAIRING)
    # Repairing -> Testing
    recovery_service.validate_task_transition(TaskStatus.REPAIRING, TaskStatus.TESTING)
    # Testing -> Verifying
    recovery_service.validate_task_transition(TaskStatus.TESTING, TaskStatus.VERIFYING)
    # Verifying -> Ready for Publication
    recovery_service.validate_task_transition(TaskStatus.VERIFYING, TaskStatus.READY_FOR_PUBLICATION)
    # Ready for Publication -> Publishing
    recovery_service.validate_task_transition(TaskStatus.READY_FOR_PUBLICATION, TaskStatus.PUBLISHING)
    # Publishing -> Draft PR Created
    recovery_service.validate_task_transition(TaskStatus.PUBLISHING, TaskStatus.DRAFT_PR_CREATED)


def test_validate_task_transition_illegal_skips_rejected(recovery_service):
    """Enforce that illegal state skips (e.g. bypassing approval) raise APIError 400."""
    # Attempting to jump directly from PENDING_APPROVAL to EXECUTING (bypassing human approval)
    with pytest.raises(APIError) as exc_info:
        recovery_service.validate_task_transition(TaskStatus.PENDING_APPROVAL, TaskStatus.EXECUTING)
    assert exc_info.value.status_code == 400
    assert exc_info.value.code == ErrorCode.INVALID_STATE_TRANSITION

    # Attempting to jump from REJECTED to EXECUTING
    with pytest.raises(APIError) as exc_info:
        recovery_service.validate_task_transition(TaskStatus.REJECTED, TaskStatus.EXECUTING)
    assert exc_info.value.status_code == 400

    # Attempting to jump from CREATED to DRAFT_PR_CREATED
    with pytest.raises(APIError) as exc_info:
        recovery_service.validate_task_transition(TaskStatus.CREATED, TaskStatus.DRAFT_PR_CREATED)
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# 2. Base Revision Drift Detection
# ---------------------------------------------------------------------------

def test_detect_base_revision_drift(recovery_service):
    """Test detection of upstream commit drift on remote base branch."""
    base_sha = "abc123def4567890123456789012345678901234"
    same_sha = "ABC123DEF4567890123456789012345678901234"
    drifted_sha = "fff999888777666555444333222111000aaabbbc"

    # Same revision (case insensitive) -> No drift
    assert recovery_service.detect_base_revision_drift(base_sha, same_sha) is False

    # Drifted revision -> Drift detected
    assert recovery_service.detect_base_revision_drift(base_sha, drifted_sha) is True

    # Empty values -> No drift reported
    assert recovery_service.detect_base_revision_drift("", drifted_sha) is False
    assert recovery_service.detect_base_revision_drift(base_sha, None) is False


# ---------------------------------------------------------------------------
# 3. Task State Reconciliation Across Worker Crashes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reconcile_task_state_base_drift(recovery_service):
    """When base revision has drifted, state reconciles to RECOVERY_REQUIRED."""
    task_id = uuid4()
    repo_id = uuid4()

    result = await recovery_service.reconcile_task_state(
        task_id=task_id,
        repository_id=repo_id,
        last_known_status=TaskStatus.EXECUTING,
        recorded_base_sha="1111111111111111111111111111111111111111",
        current_remote_base_sha="2222222222222222222222222222222222222222",
        repair_attempts_used=2,
    )

    assert result["task_id"] == task_id
    assert result["reconciled_status"] == TaskStatus.RECOVERY_REQUIRED.value
    assert result["base_drift_detected"] is True
    assert result["recovery_action"] == "REPLAN_REQUIRED"
    assert result["repair_attempts_used"] == 2  # Budget must NOT be reset


@pytest.mark.asyncio
async def test_reconcile_task_state_pr_already_exists(recovery_service):
    """When remote PR already exists, state reconciles to DRAFT_PR_CREATED."""
    task_id = uuid4()
    repo_id = uuid4()

    result = await recovery_service.reconcile_task_state(
        task_id=task_id,
        repository_id=repo_id,
        last_known_status=TaskStatus.PUBLISHING,
        recorded_base_sha="1111111111111111111111111111111111111111",
        current_remote_base_sha="1111111111111111111111111111111111111111",
        remote_pr_exists=True,
        repair_attempts_used=1,
    )

    assert result["reconciled_status"] == TaskStatus.DRAFT_PR_CREATED.value
    assert result["recovery_action"] == "NONE"
    assert result["repair_attempts_used"] == 1


@pytest.mark.asyncio
async def test_reconcile_task_state_worker_crash_resumption(recovery_service):
    """When worker crashed during EXECUTING and branch exists, resume at WORKSPACE_SETUP."""
    task_id = uuid4()
    repo_id = uuid4()

    result = await recovery_service.reconcile_task_state(
        task_id=task_id,
        repository_id=repo_id,
        last_known_status=TaskStatus.EXECUTING,
        recorded_base_sha="1111111111111111111111111111111111111111",
        current_remote_base_sha="1111111111111111111111111111111111111111",
        remote_branch_exists=True,
        remote_pr_exists=False,
        repair_attempts_used=1,
    )

    assert result["reconciled_status"] == TaskStatus.WORKSPACE_SETUP.value
    assert result["recovery_action"] == "RESUME_EXECUTION"
    assert result["repair_attempts_used"] == 1


# ---------------------------------------------------------------------------
# 4. Safe Workspace Boundary & Cleanup
# ---------------------------------------------------------------------------

def test_cleanup_task_workspace_safe(tmp_path):
    """Clean up disposable workspace within allowed root."""
    root_dir = tmp_path / "workspaces"
    root_dir.mkdir(parents=True)
    task_dir = root_dir / "task-abcdef12"
    task_dir.mkdir(parents=True)
    (task_dir / "file.txt").write_text("temporary work")

    assert task_dir.exists()
    cleaned = TaskRecoveryService.cleanup_task_workspace(
        workspace_path=task_dir,
        task_id="abcdef12",
        workspace_root=root_dir,
    )
    assert cleaned is True
    assert not task_dir.exists()


def test_cleanup_task_workspace_idempotent(tmp_path):
    """Returns True if task workspace is already removed."""
    root_dir = tmp_path / "workspaces"
    root_dir.mkdir(parents=True)
    non_existent = root_dir / "task-ghost"

    cleaned = TaskRecoveryService.cleanup_task_workspace(
        workspace_path=non_existent,
        task_id="ghost",
        workspace_root=root_dir,
    )
    assert cleaned is True


def test_cleanup_task_workspace_traversal_attack_blocked(tmp_path):
    """Block path traversal attempts outside workspace root."""
    root_dir = tmp_path / "workspaces"
    root_dir.mkdir(parents=True)
    outside_dir = tmp_path / "system_dir"
    outside_dir.mkdir(parents=True)

    with pytest.raises(APIError) as exc_info:
        TaskRecoveryService.cleanup_task_workspace(
            workspace_path=outside_dir,
            task_id="malicious",
            workspace_root=root_dir,
        )
    assert exc_info.value.status_code == 400
    assert "escapes allowed workspace root" in str(exc_info.value.message)


def test_cleanup_task_workspace_cannot_delete_entire_root(tmp_path):
    """Block attempt to delete the workspace root itself."""
    root_dir = tmp_path / "workspaces"
    root_dir.mkdir(parents=True)

    with pytest.raises(APIError) as exc_info:
        TaskRecoveryService.cleanup_task_workspace(
            workspace_path=root_dir,
            task_id="root_wipe",
            workspace_root=root_dir,
        )
    assert exc_info.value.status_code == 400
    assert "Cannot delete the entire workspace root" in str(exc_info.value.message)


# ---------------------------------------------------------------------------
# 5. REST Endpoints for Recovery & Cleanup
# ---------------------------------------------------------------------------

def test_api_task_recover_endpoint(client_setup):
    """Verify POST /api/v1/repositories/{repository_id}/source/task/recover."""
    client, repo_id, auth_headers = client_setup
    task_id = uuid4()

    payload = {
        "task_id": str(task_id),
        "last_known_status": "EXECUTING",
        "recorded_base_sha": "aaa",
        "current_remote_base_sha": "bbb",  # Drifted
        "remote_branch_exists": True,
        "remote_pr_exists": False,
        "repair_attempts_used": 1,
    }

    response = client.post(
        f"/api/v1/repositories/{repo_id}/source/task/recover",
        json=payload,
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["task_id"] == str(task_id)
    assert data["reconciled_status"] == "RECOVERY_REQUIRED"
    assert data["base_drift_detected"] is True
    assert data["recovery_action"] == "REPLAN_REQUIRED"
    assert data["repair_attempts_used"] == 1


def test_api_task_cleanup_endpoint(client_setup, tmp_path):
    """Verify POST /api/v1/repositories/{repository_id}/source/task/cleanup."""
    client, repo_id, auth_headers = client_setup
    task_id = uuid4()
    short_id = str(task_id)[:8]

    # Create dummy directory in default workspace root
    target_dir = _DEFAULT_WORKSPACE_ROOT / f"task-{short_id}"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "temp.txt").write_text("data")

    payload = {
        "task_id": str(task_id),
        "workspace_path": str(target_dir),
    }

    response = client.post(
        f"/api/v1/repositories/{repo_id}/source/task/cleanup",
        json=payload,
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["task_id"] == str(task_id)
    assert data["cleaned"] is True
    assert not target_dir.exists()
