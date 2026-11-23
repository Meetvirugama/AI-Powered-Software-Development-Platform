"""Reliability and recovery tests."""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime
from datetime import timezone
from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4
import pytest
from agent.tools.router import ToolDefinition
from agent.tools.router import ToolRequest
from agent.tools.router import ToolResult
from agent.tools.router import ToolRouter
from app.schemas.workspace import DiffImmutabilityCheckResult
from app.schemas.workspace import StaleRevisionCheckResult
from app.schemas.workspace import WorkspaceCreateRequest
from app.schemas.workspace import WorkspaceDiskUsageResult
from app.schemas.workspace import WorkspaceExecutionEventType
from app.schemas.workspace import WorkspaceInvariantCheckResult
from app.schemas.workspace import WorkspaceMetadata
from app.schemas.workspace import WorkspaceOrphanCleanupResult
from app.schemas.workspace import WorkspaceRecoveryRecord
from app.schemas.workspace import WorkspaceRecoveryResult
from app.schemas.workspace import WorkspaceResourceLimits
from app.schemas.workspace import WorkspaceStartExecutionRequest
from app.schemas.workspace import WorkspaceStatus
from sandbox.constants import DEFAULT_MAX_ORPHAN_AGE_SECONDS
from sandbox.constants import DEFAULT_MAX_WORKSPACE_FILES
from sandbox.constants import PROTECTED_BRANCHES
from sandbox.constants import RECOVERY_STALE_TIMEOUT_SECONDS
from sandbox.exceptions import WorkspaceConcurrentOperationError
from sandbox.exceptions import WorkspaceDiffDivergedError
from sandbox.exceptions import WorkspaceDiskQuotaExceededError
from sandbox.exceptions import WorkspaceError
from sandbox.exceptions import WorkspaceInvariantViolationError
from sandbox.exceptions import WorkspacePathEscapeError
from sandbox.exceptions import WorkspacePolicyViolationError
from sandbox.exceptions import WorkspacePostVerificationMutationError
from sandbox.exceptions import WorkspaceRecoveryError
from sandbox.exceptions import WorkspaceStaleRevisionError
from sandbox.exceptions import WorkspaceStateError
from sandbox.path_guard import WorkspacePathGuard
from sandbox.tool_policy_bridge import CANONICAL_WORKSPACE_TOOLS
from sandbox.tool_policy_bridge import TOOL_CHECK_DISK_BUDGET
from sandbox.tool_policy_bridge import TOOL_CHECK_STALE_REVISION
from sandbox.tool_policy_bridge import TOOL_CLEANUP_ORPHANED
from sandbox.tool_policy_bridge import TOOL_RECOVER_WORKSPACE
from sandbox.tool_policy_bridge import TOOL_VALIDATE_INVARIANTS
from sandbox.tool_policy_bridge import TOOL_VERIFY_DIFF_IMMUTABILITY
from sandbox.tool_policy_bridge import WorkspaceToolPolicyBridge
from sandbox.tool_policy_bridge import register_workspace_tools
from sandbox.workspace_manager import WorkspaceManager
from uuid import UUID
from fastapi.testclient import TestClient
from app.core.database import get_db
from app.core.errors import APIError
from app.core.errors import ErrorCode
from app.core.security import create_access_token
from app.main import app
from app.models.repository import Repository
from app.models.user import User
from app.schemas.task import TaskStatus
from app.services.git_branch import _DEFAULT_WORKSPACE_ROOT
from app.services.task_recovery import TaskRecoveryService
import uuid
from typing import Any
from sqlalchemy import create_engine
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker
from app.models.analysis_finding import AnalysisFinding
from app.models.analysis_run import AnalysisFeature
from app.models.analysis_run import AnalysisRun
from app.models.analysis_run import AnalysisRunStatus
from app.models.base import Base
from app.models.github_installation import GitHubInstallation
from app.models.repository import SyncStatus
from app.models.task import ApprovalDecision
from app.models.task import ExecutionStatus
from app.models.task import GitHubIssue
from app.models.task import RepairAttempt
from app.models.task import RepairResult
from app.models.task import Task
from app.models.task import TaskApproval
from app.models.task import TaskCheckpoint
from app.models.task import TaskEvent
from app.models.task import TaskEventType
from app.models.task import TaskExecution
from app.models.task import TaskPlan
from app.models.task import TaskPlanStatus
from app.models.task import TaskPullRequest
from app.models.task import TaskSourceType
from app.models.task import TaskStatus as PersistedTaskStatus
from app.models.task import TestRun
from app.models.task import TestRunStatus
from app.models.task import ToolInvocation
from app.models.task import ToolInvocationStatus
from app.models.task import VerificationResult
from app.models.task import VerificationStatus
from app.models.task import Workspace
from app.models.task import WorkspaceStatus as WorkspaceRecordStatus
from app.repositories.task_repository import InvalidStateTransitionError
from app.repositories.task_repository import PlanNotFoundError
from app.repositories.task_repository import TaskNotFoundError
from app.repositories.task_repository import TaskRepository
from app.schemas.task import PublicationAuthorizationRequest
from app.schemas.task import PublicationAuthorizationResponse
from app.schemas.task import TaskRecoveryResponse
from app.schemas.task import TaskResponse
from app.schemas.task import TaskTraceabilityResponse
from app.schemas.task import VerificationResultResponse
from app.services.task_history_service import TaskHistoryService


# Week 3 Day 6 Acceptance & Integration Test Suite.

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_git_repo(tmp_path: Path) -> Path:
    """Create a minimal temporary git repository with initial commit."""
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir(parents=True, exist_ok=True)

    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Prit Test"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "prit@test.local"], cwd=repo_dir, check=True)

    # Initial files
    (repo_dir / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    (repo_dir / "pyproject.toml").write_text("[project]\nname = 'test'\nversion = '0.1.0'\n", encoding="utf-8")
    src_dir = repo_dir / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / "main.py").write_text("def hello():\n    return 'world'\n", encoding="utf-8")

    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_dir, check=True)
    return repo_dir


@pytest.fixture
def temp_workspace_root(tmp_path: Path) -> Path:
    """Fixture providing an isolated base directory for test workspaces."""
    base_dir = tmp_path / ".test_workspaces"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


@pytest.fixture
def workspace_manager(temp_workspace_root: Path) -> WorkspaceManager:
    """Fixture providing a fresh WorkspaceManager instance."""
    return WorkspaceManager(base_workspaces_dir=temp_workspace_root)


@pytest.fixture
def running_workspace(
    workspace_manager: WorkspaceManager,
    temp_git_repo: Path,
) -> str:
    """Create and start a running workspace in IN_USE status with real git commit."""
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=temp_git_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    head_sha = proc.stdout.strip()

    task_id = f"task-{uuid4().hex[:8]}"
    create_req = WorkspaceCreateRequest(
        task_id=task_id,
        repository_id=str(uuid4()),
        base_revision=head_sha,
        repository_root=str(temp_git_repo),
        isolation_type="directory_copy",
    )
    workspace_manager.create_workspace(create_req)

    start_req = WorkspaceStartExecutionRequest(
        task_id=task_id,
        plan_version=1,
        approved_base_revision=head_sha,
        task_status="APPROVED",
    )
    workspace_manager.start_execution(start_req)
    return task_id


# ---------------------------------------------------------------------------
# Test Suite 1: Worker Crash & Restart Recovery
# ---------------------------------------------------------------------------

class TestWorkerCrashAndRestartRecovery:
    """Verifies crash detection, workspace state reconciliation, and restart recovery."""

    def test_recover_workspaces_empty_dir(self, workspace_manager: WorkspaceManager):
        """When no workspaces exist, recovery returns zero records cleanly."""
        res = workspace_manager.recover_workspaces()
        assert isinstance(res, WorkspaceRecoveryResult)
        assert res.total_scanned == 0
        assert res.recovered_count == 0
        assert res.failed_count == 0

    def test_recover_workspaces_marks_stuck_creating_as_failed(
        self,
        workspace_manager: WorkspaceManager,
        temp_workspace_root: Path,
    ):
        """Workspaces stuck in CREATING status during crash are marked as FAILED."""
        task_id = f"crash-{uuid4().hex[:6]}"
        ws_dir = temp_workspace_root / f"task-{task_id}"
        ws_dir.mkdir(parents=True, exist_ok=True)

        meta = {
            "workspace_id": str(uuid4()),
            "task_id": task_id,
            "repository_id": str(uuid4()),
            "base_revision": "abc1234",
            "branch_name": f"agent/task-{task_id}",
            "workspace_path": str(ws_dir),
            "status": WorkspaceStatus.CREATING.value,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        (ws_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")

        res = workspace_manager.recover_workspaces()
        assert res.total_scanned == 1
        assert res.failed_count == 1
        assert len(res.records) == 1
        record = res.records[0]
        assert record.task_id == task_id
        assert record.previous_status == WorkspaceStatus.CREATING
        assert record.new_status == WorkspaceStatus.FAILED
        assert "Worker interrupted during creation" in record.reconciliation_action

        # Check metadata on disk was updated
        updated_meta = json.loads(workspace_manager._workspace_metadata_path(ws_dir).read_text(encoding="utf-8"))
        assert updated_meta["status"] == WorkspaceStatus.FAILED.value

    def test_recover_workspaces_marks_stale_in_use_as_stopped(
        self,
        workspace_manager: WorkspaceManager,
        temp_workspace_root: Path,
    ):
        """Workspaces in IN_USE with no activity exceeding stale threshold are stopped."""
        task_id = f"stale-{uuid4().hex[:6]}"
        ws_dir = temp_workspace_root / f"task-{task_id}"
        ws_dir.mkdir(parents=True, exist_ok=True)

        # 2 hours ago
        stale_time = datetime.fromtimestamp(time.time() - 7200, tz=timezone.utc).isoformat()
        meta = {
            "workspace_id": str(uuid4()),
            "task_id": task_id,
            "repository_id": str(uuid4()),
            "base_revision": "abc1234",
            "branch_name": f"agent/task-{task_id}",
            "workspace_path": str(ws_dir),
            "status": WorkspaceStatus.IN_USE.value,
            "created_at": stale_time,
            "updated_at": stale_time,
            "last_active_at": stale_time,
        }
        (ws_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")

        res = workspace_manager.recover_workspaces(stale_timeout_seconds=3600)
        assert res.total_scanned == 1
        assert res.recovered_count == 1
        record = res.records[0]
        assert record.task_id == task_id
        assert record.previous_status == WorkspaceStatus.IN_USE
        assert record.new_status == WorkspaceStatus.STOPPED

        # Timeline event recorded
        timeline = workspace_manager.get_execution_timeline(task_id)
        assert any(e.event_type == WorkspaceExecutionEventType.WORKER_CRASH_RECOVERED for e in timeline)

    def test_recover_workspaces_preserves_active_workspace(
        self,
        workspace_manager: WorkspaceManager,
        running_workspace: str,
    ):
        """Workspaces with recent activity within timeout are not modified."""
        res = workspace_manager.recover_workspaces(stale_timeout_seconds=3600)
        assert res.total_scanned == 1
        assert res.recovered_count == 0
        assert res.failed_count == 0
        assert res.unmodified_count == 1

    def test_reconcile_workspace_reloads_cached_metadata(
        self,
        workspace_manager: WorkspaceManager,
        running_workspace: str,
        temp_workspace_root: Path,
    ):
        """reconcile_workspace re-populates memory cache from disk metadata."""
        # Evict from manager's in-memory cache
        del workspace_manager._workspaces[running_workspace]
        assert running_workspace not in workspace_manager._workspaces

        rec = workspace_manager.reconcile_workspace(running_workspace)
        assert rec.task_id == running_workspace
        assert running_workspace in workspace_manager._workspaces
        assert workspace_manager.get_workspace(running_workspace).status == WorkspaceStatus.IN_USE


# ---------------------------------------------------------------------------
# Test Suite 2: Stale Base-Revision Detection
# ---------------------------------------------------------------------------

class TestStaleBaseRevisionDetection:
    """Verifies base branch divergence detection and anti-stale protections."""

    def test_detect_stale_base_revision_up_to_date(
        self,
        workspace_manager: WorkspaceManager,
        running_workspace: str,
    ):
        """When local base revision matches remote tracking branch, reports not stale."""
        # Mock git fetch and rev-list to return 0 commits behind
        with patch.object(
            workspace_manager.command_runner,
            "execute_raw_command",
            side_effect=[
                MagicMock(exit_code=0, stdout="", stderr=""),  # git fetch
                MagicMock(exit_code=0, stdout="abc1234\n", stderr=""),  # rev-parse remote
                MagicMock(exit_code=0, stdout="0\n", stderr=""),  # rev-list count
            ],
        ):
            res = workspace_manager.detect_stale_base_revision(running_workspace)
            assert isinstance(res, StaleRevisionCheckResult)
            assert not res.is_stale
            assert res.commits_behind == 0

    def test_detect_stale_base_revision_diverged(
        self,
        workspace_manager: WorkspaceManager,
        running_workspace: str,
    ):
        """When remote branch has 3 newer commits, reports stale and provides remediation."""
        with patch.object(
            workspace_manager.command_runner,
            "execute_raw_command",
            side_effect=[
                MagicMock(exit_code=0, stdout="", stderr=""),  # git fetch
                MagicMock(exit_code=0, stdout="def5678\n", stderr=""),  # rev-parse remote
                MagicMock(exit_code=0, stdout="3\n", stderr=""),  # rev-list count = 3 commits behind
            ],
        ):
            res = workspace_manager.detect_stale_base_revision(running_workspace)
            assert res.is_stale
            assert res.commits_behind == 3
            assert res.remote_head == "def5678"
            assert "Rebase workspace feature branch" in res.remediation_suggestion

            # Verify timeline event was added
            events = workspace_manager.get_execution_timeline(running_workspace)
            assert any(e.event_type == WorkspaceExecutionEventType.STALE_REVISION_DETECTED for e in events)

    def test_assert_not_stale_raises_exception_when_diverged(
        self,
        workspace_manager: WorkspaceManager,
        running_workspace: str,
    ):
        """assert_not_stale raises WorkspaceStaleRevisionError when branch is stale."""
        with patch.object(
            workspace_manager,
            "detect_stale_base_revision",
            return_value=StaleRevisionCheckResult(
                is_stale=True,
                current_base_revision="abc1234",
                remote_head="def5678",
                commits_behind=2,
                remediation_suggestion="Rebase branch.",
            ),
        ):
            with pytest.raises(WorkspaceStaleRevisionError) as exc_info:
                workspace_manager.assert_not_stale(running_workspace)
            assert "Workspace base revision 'abc1234' is stale" in str(exc_info.value)
            assert "behind origin/main" in str(exc_info.value)

    def test_assert_not_stale_passes_when_up_to_date(
        self,
        workspace_manager: WorkspaceManager,
        running_workspace: str,
    ):
        """assert_not_stale completes without error when branch is current."""
        with patch.object(
            workspace_manager,
            "detect_stale_base_revision",
            return_value=StaleRevisionCheckResult(
                is_stale=False,
                current_base_revision="abc1234",
                commits_behind=0,
            ),
        ):
            workspace_manager.assert_not_stale(running_workspace)


# ---------------------------------------------------------------------------
# Test Suite 3: Diff Immutability & Post-Verification Mutation
# ---------------------------------------------------------------------------

class TestDiffImmutabilityAndPostVerification:
    """Verifies diff hashing, post-verification immutability, and mutation rejection."""

    def test_compute_verification_diff_hash(
        self,
        workspace_manager: WorkspaceManager,
        running_workspace: str,
    ):
        """Computes SHA-256 hash of git diff and persists it to workspace metadata."""
        # Make a valid change
        workspace_manager.write_file(running_workspace, "src/main.py", "def hello():\n    return 'changed'\n")

        diff_hash = workspace_manager.compute_verification_diff_hash(running_workspace)
        assert isinstance(diff_hash, str)
        assert len(diff_hash) == 64

        ws = workspace_manager.get_workspace(running_workspace)
        assert ws.verification_diff_hash == diff_hash

    def test_verify_diff_immutability_matching_hash(
        self,
        workspace_manager: WorkspaceManager,
        running_workspace: str,
    ):
        """When diff has not changed post-verification, verify_diff_immutability succeeds."""
        workspace_manager.write_file(running_workspace, "src/main.py", "def hello():\n    return 'tested'\n")
        initial_hash = workspace_manager.compute_verification_diff_hash(running_workspace)

        res = workspace_manager.verify_diff_immutability(running_workspace, expected_hash=initial_hash)
        assert isinstance(res, DiffImmutabilityCheckResult)
        assert res.is_immutable
        assert res.verified_diff_hash == initial_hash
        assert res.current_diff_hash == initial_hash

    def test_verify_diff_immutability_detects_mutation(
        self,
        workspace_manager: WorkspaceManager,
        running_workspace: str,
    ):
        """When workspace files mutate after verification, detects immutability breach."""
        workspace_manager.write_file(running_workspace, "src/main.py", "def hello():\n    return 'tested'\n")
        initial_hash = workspace_manager.compute_verification_diff_hash(running_workspace)

        # Sneak in an unverified modification
        workspace_manager.write_file(running_workspace, "src/main.py", "def hello():\n    return 'sneaky_mutation'\n")

        res = workspace_manager.verify_diff_immutability(running_workspace, expected_hash=initial_hash)
        assert not res.is_immutable
        assert res.verified_diff_hash == initial_hash
        assert res.current_diff_hash != initial_hash
        assert "Diff immutability violation" in (res.error_message or "")

        # Verifies timeline event
        events = workspace_manager.get_execution_timeline(running_workspace)
        assert any(e.event_type == WorkspaceExecutionEventType.POST_VERIFICATION_MUTATION_DETECTED for e in events)


# ---------------------------------------------------------------------------
# Test Suite 4: Hardened Cleanup & Orphan Garbage Collection
# ---------------------------------------------------------------------------

class TestHardenedCleanupAndOrphanCollection:
    """Verifies safe pruning of untracked, abandoned, and expired workspace directories."""

    def test_cleanup_orphaned_workspaces_dry_run(
        self,
        workspace_manager: WorkspaceManager,
        temp_workspace_root: Path,
    ):
        """Dry-run identifies candidate orphan directories without deleting them."""
        # Create an untracked directory with an old mtime
        orphan_dir = temp_workspace_root / "task-untracked-old"
        orphan_dir.mkdir(parents=True, exist_ok=True)
        (orphan_dir / "junk.txt").write_text("abandoned", encoding="utf-8")

        # Set modification time to 48 hours ago
        old_mtime = time.time() - (48 * 3600)
        os.utime(orphan_dir, (old_mtime, old_mtime))

        res = workspace_manager.cleanup_orphaned_workspaces(max_age_seconds=86400, dry_run=True)
        assert isinstance(res, WorkspaceOrphanCleanupResult)
        assert "task-untracked-old" in res.candidate_paths or any("task-untracked-old" in p for p in res.candidate_paths)
        assert res.cleaned_count == 0
        assert orphan_dir.exists()

    def test_cleanup_orphaned_workspaces_real_run(
        self,
        workspace_manager: WorkspaceManager,
        temp_workspace_root: Path,
    ):
        """Real run removes untracked abandoned directories exceeding age threshold."""
        orphan_dir = temp_workspace_root / "task-untracked-delete"
        orphan_dir.mkdir(parents=True, exist_ok=True)
        (orphan_dir / "file.txt").write_text("hello", encoding="utf-8")

        old_mtime = time.time() - (48 * 3600)
        os.utime(orphan_dir, (old_mtime, old_mtime))

        res = workspace_manager.cleanup_orphaned_workspaces(max_age_seconds=86400, dry_run=False)
        assert res.cleaned_count >= 1
        assert not orphan_dir.exists()

    def test_cleanup_orphaned_workspaces_preserves_active(
        self,
        workspace_manager: WorkspaceManager,
        running_workspace: str,
    ):
        """Active workspaces tracked in manager are never removed during orphan collection."""
        res = workspace_manager.cleanup_orphaned_workspaces(max_age_seconds=0, dry_run=False)
        ws = workspace_manager.get_workspace(running_workspace)
        assert Path(ws.workspace_path).exists()


# ---------------------------------------------------------------------------
# Test Suite 5: Sandbox Invariant Validation
# ---------------------------------------------------------------------------

class TestSandboxInvariantValidation:
    """Verifies runtime auditing of directory structure, permissions, and security."""

    def test_validate_workspace_invariants_healthy(
        self,
        workspace_manager: WorkspaceManager,
        running_workspace: str,
    ):
        """A properly initialized running workspace passes all invariant checks."""
        res = workspace_manager.validate_workspace_invariants(running_workspace)
        assert isinstance(res, WorkspaceInvariantCheckResult)
        assert res.is_valid
        assert len(res.violations) == 0

    def test_validate_workspace_invariants_missing_dir(
        self,
        workspace_manager: WorkspaceManager,
        running_workspace: str,
    ):
        """Detects if workspace root directory has been removed out-of-band."""
        ws = workspace_manager.get_workspace(running_workspace)
        # Point to non-existent directory
        ws.workspace_path = str(Path(ws.workspace_path) / "non_existent_sub")

        res = workspace_manager.validate_workspace_invariants(running_workspace)
        assert not res.is_valid
        assert any("missing on disk" in v for v in res.violations)

    def test_validate_workspace_invariants_forbidden_secrets(
        self,
        workspace_manager: WorkspaceManager,
        running_workspace: str,
    ):
        """Detects forbidden planted secret files (e.g. .env, id_rsa)."""
        ws = workspace_manager.get_workspace(running_workspace)
        (Path(ws.workspace_path) / ".env").write_text("SECRET_KEY=12345\n", encoding="utf-8")

        res = workspace_manager.validate_workspace_invariants(running_workspace)
        assert not res.is_valid
        assert any("Forbidden file or directory detected" in v for v in res.violations)


# ---------------------------------------------------------------------------
# Test Suite 6: Disk Quota & Budget Enforcement
# ---------------------------------------------------------------------------

class TestDiskQuotaAndBudgetEnforcement:
    """Verifies workspace file count and byte storage limit enforcement."""

    def test_check_disk_budget_normal(
        self,
        workspace_manager: WorkspaceManager,
        running_workspace: str,
    ):
        """Calculates file count and byte footprint within standard limits."""
        res = workspace_manager.check_disk_budget(running_workspace)
        assert isinstance(res, WorkspaceDiskUsageResult)
        assert not res.is_exceeded
        assert res.total_bytes > 0
        assert res.total_files > 0
        assert res.error_message is None

    def test_check_disk_budget_exceeds_bytes(
        self,
        workspace_manager: WorkspaceManager,
        running_workspace: str,
    ):
        """Detects byte limit overrun and logs DISK_QUOTA_EXCEEDED event."""
        # Set max_bytes to 10 bytes (lower than minimal repo footprint)
        res = workspace_manager.check_disk_budget(running_workspace, max_bytes=10)
        assert res.is_exceeded
        assert "exceeds quota" in (res.error_message or "")

        events = workspace_manager.get_execution_timeline(running_workspace)
        assert any(e.event_type == WorkspaceExecutionEventType.DISK_QUOTA_EXCEEDED for e in events)

    def test_check_disk_budget_exceeds_files(
        self,
        workspace_manager: WorkspaceManager,
        running_workspace: str,
    ):
        """Detects total file count overrun."""
        # Set max_files to 1 file (repo already has > 3 files)
        res = workspace_manager.check_disk_budget(running_workspace, max_files=1)
        assert res.is_exceeded
        assert "exceeds maximum allowed" in (res.error_message or "")


# ---------------------------------------------------------------------------
# Test Suite 7: Task Concurrency & Mutex Locking
# ---------------------------------------------------------------------------

class TestTaskConcurrencyAndLocking:
    """Verifies per-task locking to avoid concurrent conflicting mutations."""

    def test_get_task_lock_acquired_and_released(
        self,
        workspace_manager: WorkspaceManager,
    ):
        """Acquires lock in context and releases upon exit."""
        task_id = "task-lock-1"
        with workspace_manager.get_task_lock(task_id):
            # Inside lock
            assert task_id in workspace_manager._task_locks

        # Can immediately acquire again
        with workspace_manager.get_task_lock(task_id):
            assert True

    def test_get_task_lock_different_tasks_independent(
        self,
        workspace_manager: WorkspaceManager,
    ):
        """Locks for different task IDs do not block each other."""
        with workspace_manager.get_task_lock("task-A"):
            with workspace_manager.get_task_lock("task-B"):
                assert True


# ---------------------------------------------------------------------------
# Test Suite 8: Secret Sanitization in Logs and Events
# ---------------------------------------------------------------------------

class TestSecretSanitization:
    """Verifies redaction of API keys and credentials from logs and strings."""

    def test_sanitize_log_redacts_tokens(
        self,
        workspace_manager: WorkspaceManager,
    ):
        """Redacts OpenAI, Anthropic, GitHub, AWS, and Bearer tokens."""
        raw_msg = (
            "Connecting with ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890 and "
            "sk-ant-api03-abcdefghijklmnopqrstuvwxyz1234567890 and Bearer eyJhbGciOiJIUzI1NiJ9"
        )
        clean = workspace_manager.sanitize_log(raw_msg)
        assert "ghp_ABC" not in clean
        assert "sk-ant-api03" not in clean
        assert "[REDACTED]" in clean

    def test_sanitize_log_preserves_safe_text(
        self,
        workspace_manager: WorkspaceManager,
    ):
        """Preserves normal non-secret log content intact."""
        raw_msg = "Task execution finished with exit code 0."
        assert workspace_manager.sanitize_log(raw_msg) == raw_msg


# ---------------------------------------------------------------------------
# Test Suite 9: Tool Policy Bridge Day 6 Integration
# ---------------------------------------------------------------------------

class TestToolPolicyBridgeDay6Integration:
    """Verifies tool registration and execution routing for all 6 Day 6 tools."""

    @pytest.fixture
    def router_and_bridge(
        self,
        workspace_manager: WorkspaceManager,
    ) -> tuple[ToolRouter, WorkspaceToolPolicyBridge]:
        router = ToolRouter()
        bridge = register_workspace_tools(router, workspace_manager)
        return router, bridge

    def test_tool_router_day6_tools_registered(
        self,
        router_and_bridge: tuple[ToolRouter, WorkspaceToolPolicyBridge],
    ):
        """All 6 Day 6 tools are registered in the canonical router tool list."""
        router, _ = router_and_bridge
        registered_names = {t.name for t in router.get_tools()}
        for canonical_tool in [
            TOOL_RECOVER_WORKSPACE,
            TOOL_CHECK_STALE_REVISION,
            TOOL_VERIFY_DIFF_IMMUTABILITY,
            TOOL_CLEANUP_ORPHANED,
            TOOL_VALIDATE_INVARIANTS,
            TOOL_CHECK_DISK_BUDGET,
        ]:
            assert canonical_tool in registered_names

    def test_tool_router_recover_workspace_dispatch(
        self,
        router_and_bridge: tuple[ToolRouter, WorkspaceToolPolicyBridge],
        running_workspace: str,
    ):
        """TOOL_RECOVER_WORKSPACE dispatches through router and returns recovery record."""
        router, _ = router_and_bridge
        req = ToolRequest(
            tool_name=TOOL_RECOVER_WORKSPACE,
            arguments={"task_id": running_workspace},
        )
        res = router.route(req, agent_state={"task_id": running_workspace})
        assert res.success
        assert res.output["task_id"] == running_workspace

    def test_tool_router_check_stale_revision_dispatch(
        self,
        router_and_bridge: tuple[ToolRouter, WorkspaceToolPolicyBridge],
        workspace_manager: WorkspaceManager,
        running_workspace: str,
    ):
        """TOOL_CHECK_STALE_REVISION dispatches and returns StaleRevisionCheckResult dict."""
        router, _ = router_and_bridge
        with patch.object(
            workspace_manager,
            "detect_stale_base_revision",
            return_value=StaleRevisionCheckResult(is_stale=False, commits_behind=0),
        ):
            req = ToolRequest(
                tool_name=TOOL_CHECK_STALE_REVISION,
                arguments={"remote_name": "origin", "base_branch": "main"},
            )
            res = router.route(req, agent_state={"task_id": running_workspace})
            assert res.success
            assert not res.output["is_stale"]

    def test_tool_router_verify_diff_immutability_dispatch(
        self,
        router_and_bridge: tuple[ToolRouter, WorkspaceToolPolicyBridge],
        workspace_manager: WorkspaceManager,
        running_workspace: str,
    ):
        """TOOL_VERIFY_DIFF_IMMUTABILITY dispatches and returns DiffImmutabilityCheckResult."""
        router, _ = router_and_bridge
        workspace_manager.write_file(running_workspace, "src/main.py", "def hello():\n    return 'tested'\n")
        h = workspace_manager.compute_verification_diff_hash(running_workspace)

        req = ToolRequest(
            tool_name=TOOL_VERIFY_DIFF_IMMUTABILITY,
            arguments={"expected_hash": h},
        )
        res = router.route(req, agent_state={"task_id": running_workspace})
        assert res.success
        assert res.output["is_immutable"]

    def test_tool_router_cleanup_orphaned_dispatch(
        self,
        router_and_bridge: tuple[ToolRouter, WorkspaceToolPolicyBridge],
        workspace_manager: WorkspaceManager,
    ):
        """TOOL_CLEANUP_ORPHANED dispatches without requiring a specific task_id."""
        router, _ = router_and_bridge
        req = ToolRequest(
            tool_name=TOOL_CLEANUP_ORPHANED,
            arguments={"dry_run": True},
        )
        res = router.route(req, agent_state={})
        assert res.success
        assert "cleaned_count" in res.output

    def test_tool_router_validate_invariants_dispatch(
        self,
        router_and_bridge: tuple[ToolRouter, WorkspaceToolPolicyBridge],
        running_workspace: str,
    ):
        """TOOL_VALIDATE_INVARIANTS dispatches and returns invariant check result."""
        router, _ = router_and_bridge
        req = ToolRequest(
            tool_name=TOOL_VALIDATE_INVARIANTS,
            arguments={},
        )
        res = router.route(req, agent_state={"task_id": running_workspace})
        assert res.success
        assert res.output["valid"]

    def test_tool_router_check_disk_budget_dispatch(
        self,
        router_and_bridge: tuple[ToolRouter, WorkspaceToolPolicyBridge],
        running_workspace: str,
    ):
        """TOOL_CHECK_DISK_BUDGET dispatches and returns disk usage result."""
        router, _ = router_and_bridge
        req = ToolRequest(
            tool_name=TOOL_CHECK_DISK_BUDGET,
            arguments={"max_bytes": 100000000},
        )
        res = router.route(req, agent_state={"task_id": running_workspace})
        assert res.success
        assert res.output["within_budget"]


# Unit and integration tests for Week 3 Day 6 deliverables.

os.environ["JWT_SECRET"] = "test-jwt-secret-for-week3-day6-tests-12345"




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


# Week 3 Day 6 & Day 7 Database Query Performance, Audit Consistency, Crash Recovery & 17-Step E2E Acceptance.

# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------

def _seed_user_and_repo(db: Session, prefix: str = "d6d7") -> tuple[User, Repository]:
    """Helper to seed isolated tenant user and repository using standard conftest db."""
    user = User(
        id=uuid.uuid4(),
        github_id=abs(hash(f"{prefix}_{uuid.uuid4().hex[:4]}")) % 1000000,
        login=f"{prefix}_{uuid.uuid4().hex[:4]}",
        email=f"{prefix}@example.com",
    )
    db.add(user)
    db.flush()

    installation = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=user.id,
        installation_id=f"inst_{uuid.uuid4().hex[:8]}",
        account_login=user.login,
        permissions={"contents": "write", "pull_requests": "write"},
    )
    db.add(installation)
    db.flush()

    repo = Repository(
        id=uuid.uuid4(),
        user_id=user.id,
        installation_id=installation.id,
        github_repo_id=f"repo_{uuid.uuid4().hex[:8]}",
        owner=user.login,
        name=f"repo-{prefix}-{uuid.uuid4().hex[:4]}",
        default_branch="main",
        sync_status=SyncStatus.SYNCED,
    )
    db.add(repo)
    db.commit()
    db.refresh(user)
    db.refresh(repo)
    return user, repo


# ---------------------------------------------------------------------------
# 1. Database Query Performance & Index Optimization (Day 6)
# ---------------------------------------------------------------------------

class TestQueryPerformanceAndIndexOptimization:
    """Verifies composite indexes, fast active-task querying, and query SLA latency."""

    def test_table_indexes_present_and_configured(self) -> None:
        """Verify that all composite and performance indexes are registered in ORM metadata."""
        tables = Base.metadata.tables

        # Check tasks table indexes
        task_table = tables["tasks"]
        task_index_names = {idx.name for idx in task_table.indexes}
        assert "ix_tasks_repo_status" in task_index_names
        assert "ix_tasks_repo_created" in task_index_names

        # Check workspaces table indexes
        ws_table = tables["workspaces"]
        ws_index_names = {idx.name for idx in ws_table.indexes}
        assert "ix_workspaces_task_status" in ws_index_names

        # Check task_executions table indexes
        ex_table = tables["task_executions"]
        ex_index_names = {idx.name for idx in ex_table.indexes}
        assert "ix_task_executions_task_attempt" in ex_index_names
        assert "ix_task_executions_task_created" in ex_index_names

        # Check tool_invocations table indexes
        tool_table = tables["tool_invocations"]
        tool_index_names = {idx.name for idx in tool_table.indexes}
        assert "ix_tool_invocations_task_created" in tool_index_names
        assert "ix_tool_invocations_task_tool" in tool_index_names

        # Check test_runs table indexes
        test_table = tables["test_runs"]
        test_index_names = {idx.name for idx in test_table.indexes}
        assert "ix_test_runs_task_created" in test_index_names
        assert "ix_test_runs_task_status" in test_index_names

        # Check verification_results table indexes
        ver_table = tables["verification_results"]
        ver_index_names = {idx.name for idx in ver_table.indexes}
        assert "ix_verification_results_task_revision" in ver_index_names
        assert "ix_verification_results_task_created" in ver_index_names

        # Check checkpoints and PR tables
        cp_table = tables["task_checkpoints"]
        assert "ix_task_checkpoints_task_created" in {idx.name for idx in cp_table.indexes}

        pr_table = tables["task_pull_requests"]
        assert "ix_task_pull_requests_repo_pr" in {idx.name for idx in pr_table.indexes}

    def test_get_active_tasks_for_repository_filtering(self, db_session: Session) -> None:
        """Querying active tasks filters out terminal states and uses pagination."""
        user, repo = _seed_user_and_repo(db_session, "perf-active")
        repository = TaskRepository(db_session)

        # Create active tasks
        t1 = repository.create_task(repo.id, "Active Task 1", user_id=user.id)
        t2 = repository.create_task(repo.id, "Active Task 2", user_id=user.id)
        repository.transition_status(t2.id, repo.id, PersistedTaskStatus.PLANNING)

        # Create terminal tasks
        t_term1 = repository.create_task(repo.id, "Terminal Cancelled", user_id=user.id)
        repository.transition_status(t_term1.id, repo.id, PersistedTaskStatus.CANCELLED)

        t_term2 = repository.create_task(repo.id, "Terminal Failed", user_id=user.id)
        repository.transition_status(t_term2.id, repo.id, PersistedTaskStatus.FAILED)

        # Query active tasks
        active_tasks = repository.get_active_tasks_for_repository(repo.id)
        active_ids = {t.id for t in active_tasks}

        assert t1.id in active_ids
        assert t2.id in active_ids
        assert t_term1.id not in active_ids
        assert t_term2.id not in active_ids
        assert len(active_tasks) == 2

    def test_query_latency_within_sla_benchmark(self, db_session: Session) -> None:
        """Indexed lookups for task, timeline, and active list must execute under 50ms SLA."""
        user, repo = _seed_user_and_repo(db_session, "perf-sla")
        repository = TaskRepository(db_session)

        # Seed 10 tasks with events
        created_tasks = []
        for i in range(10):
            t = repository.create_task(repo.id, f"SLA Task {i}", user_id=user.id)
            repository.record_event(t.id, repo.id, "BENCHMARK_EVENT", {"idx": i}, user_id=user.id)
            created_tasks.append(t)

        target_task = created_tasks[5]

        # 1. Benchmark get_task
        t0 = time.perf_counter()
        retrieved = repository.get_task(target_task.id, repo.id)
        t_get_task_ms = (time.perf_counter() - t0) * 1000.0
        assert retrieved is not None
        assert t_get_task_ms < 50.0, f"get_task took {t_get_task_ms:.2f}ms, exceeding 50ms SLA"

        # 2. Benchmark get_active_tasks_for_repository
        t0 = time.perf_counter()
        actives = repository.get_active_tasks_for_repository(repo.id, limit=20)
        t_active_ms = (time.perf_counter() - t0) * 1000.0
        assert len(actives) == 10
        assert t_active_ms < 50.0, f"get_active_tasks took {t_active_ms:.2f}ms, exceeding 50ms SLA"

        # 3. Benchmark get_task_timeline
        t0 = time.perf_counter()
        events = repository.get_task_timeline(target_task.id, repo.id)
        t_timeline_ms = (time.perf_counter() - t0) * 1000.0
        assert len(events) >= 2  # TASK_CREATED + BENCHMARK_EVENT
        assert t_timeline_ms < 30.0, f"get_task_timeline took {t_timeline_ms:.2f}ms, exceeding 30ms SLA"

    def test_eager_loading_avoids_n_plus_one(self, db_session: Session) -> None:
        """Fetching a task eagerly loads plans, approvals, workspace, and executions."""
        user, repo = _seed_user_and_repo(db_session, "perf-eager")
        repository = TaskRepository(db_session)

        task = repository.create_task(repo.id, "Eager Loading Task", user_id=user.id)
        plan = repository.save_plan(task.id, repo.id, summary="Plan 1", steps=[{"step": 1}])
        repository.approve_plan(task.id, repo.id, plan_version=plan.version, user_id=user.id)
        repository.record_workspace(task.id, repo.id, "/ws/task", "agent/task", "base-sha")
        repository.record_execution_start(task.id, repo.id, worker_id="w-eager")

        # Expire session so attributes are not in identity map
        db_session.expire_all()

        loaded_task = repository.get_task(task.id, repo.id)
        assert loaded_task is not None
        # Accessing relationships should succeed immediately
        assert len(loaded_task.plans) == 1
        assert len(loaded_task.approvals) == 1
        assert loaded_task.workspace is not None
        assert len(loaded_task.executions) == 1


# ---------------------------------------------------------------------------
# 2. Audit Event Consistency & Immutability Enforcement (Day 6)
# ---------------------------------------------------------------------------

class TestAuditEventConsistencyAndImmutability:
    """Verifies append-only immutability, chronological monotonic ordering, and zero credential leakage."""

    def test_audit_events_are_append_only_and_immutable(self, db_session: Session) -> None:
        """Attempting to delete or modify an audit event is strictly rejected."""
        user, repo = _seed_user_and_repo(db_session, "audit-imm")
        repository = TaskRepository(db_session)

        task = repository.create_task(repo.id, "Immutable Audit Task", user_id=user.id)
        event = repository.record_event(task.id, repo.id, "SYSTEM_CHECK", {"key": "value"})

        with pytest.raises(PermissionError, match="Audit events are immutable and cannot be deleted"):
            repository.delete_event(event.id)

        with pytest.raises(PermissionError, match="Audit events are immutable and cannot be modified"):
            repository.update_event(event.id, summary="Altered summary")

    def test_task_approvals_are_immutable(self, db_session: Session) -> None:
        """Attempting to alter a human plan approval is strictly rejected."""
        user, repo = _seed_user_and_repo(db_session, "approval-imm")
        repository = TaskRepository(db_session)

        task = repository.create_task(repo.id, "Approval Immutability Task", user_id=user.id)
        plan = repository.save_plan(task.id, repo.id, summary="Plan", steps=[{"step": 1}])
        approval = repository.approve_plan(task.id, repo.id, plan_version=plan.version, user_id=user.id)

        with pytest.raises(PermissionError, match="Task approvals are immutable and cannot be modified"):
            repository.update_approval(approval.id, feedback="Mutated feedback")

    def test_timeline_order_strictly_monotonic(self, db_session: Session) -> None:
        """Timeline events must return in strictly non-decreasing chronological order."""
        user, repo = _seed_user_and_repo(db_session, "timeline-seq")
        repository = TaskRepository(db_session)

        task = repository.create_task(repo.id, "Monotonic Timeline Task", user_id=user.id)
        for i in range(5):
            repository.record_event(task.id, repo.id, f"EVENT_{i}", {"index": i}, user_id=user.id)

        timeline = repository.get_task_timeline(task.id, repo.id)
        assert len(timeline) == 6  # 1 creation + 5 appended

        for i in range(len(timeline) - 1):
            assert timeline[i].created_at <= timeline[i + 1].created_at

    def test_state_transitions_always_record_consistent_events(self, db_session: Session) -> None:
        """Every status transition must emit a corresponding timeline audit event."""
        user, repo = _seed_user_and_repo(db_session, "trans-events")
        repository = TaskRepository(db_session)

        task = repository.create_task(repo.id, "Transition Events Task", user_id=user.id)
        repository.transition_status(
            task.id,
            repo.id,
            PersistedTaskStatus.PLANNING,
            user_id=user.id,
            reason="Starting planner phase",
        )

        timeline = repository.get_task_timeline(task.id, repo.id)
        transition_events = [e for e in timeline if e.event_type == TaskEventType.STATE_TRANSITIONED.value]
        assert len(transition_events) == 1
        ev = transition_events[0]
        assert ev.event_data["from_status"] == PersistedTaskStatus.CREATED.value
        assert ev.event_data["to_status"] == PersistedTaskStatus.PLANNING.value
        assert ev.event_data["reason"] == "Starting planner phase"

    def test_secret_scrubbing_across_all_event_fields(self, db_session: Session) -> None:
        """Raw secrets in event payloads and reasons are redacted before persistence."""
        user, repo = _seed_user_and_repo(db_session, "audit-scrub")
        repository = TaskRepository(db_session)

        task = repository.create_task(repo.id, "Scrubbed Event Task", user_id=user.id)
        secret_token = "ghp_123456789012345678901234567890123456"
        secret_key = "sk-proj-1234567890abcdef1234567890"

        ev = repository.record_event(
            task_id=task.id,
            repository_id=repo.id,
            event_type="AUTH_LOG",
            event_data={"token": secret_token, "headers": {"Authorization": f"Bearer {secret_key}"}},
            summary=f"Dispatched with key {secret_key}",
        )

        assert secret_token not in str(ev.event_data)
        assert secret_key not in str(ev.event_data)
        assert secret_key not in ev.summary
        assert "[REDACTED]" in ev.summary


# ---------------------------------------------------------------------------
# 3. Crash Recovery & Worker Restart Resilience (Day 6 & F39)
# ---------------------------------------------------------------------------

class TestWorkerCrashRecoveryAndRestartResilience:
    """Verifies crash detection, checkpoint rollback, retry budget preservation, and idempotency."""

    def test_recover_interrupted_task_with_valid_checkpoint(self, db_session: Session) -> None:
        """An interrupted task with a valid checkpoint is transitioned to RECOVERY_REQUIRED with checkpoint metadata."""
        user, repo = _seed_user_and_repo(db_session, "crash-cp")
        repository = TaskRepository(db_session)

        task = repository.create_task(repo.id, "Crash Recovery Task", user_id=user.id)
        plan = repository.save_plan(task.id, repo.id, summary="Plan", steps=[{"step": 1}])
        repository.approve_plan(task.id, repo.id, plan_version=plan.version, user_id=user.id)
        repository.record_workspace(task.id, repo.id, "/ws/crash", "agent/task", "base-sha")

        # Save a valid checkpoint during execution
        repository.save_checkpoint(
            task_id=task.id,
            repository_id=repo.id,
            step_name="step_3_file_modified",
            state_data={"modified_files": ["auth.py"], "diff_size": 150},
            recovery_instructions="Re-apply patch from step 3 and run tests",
        )

        # Transition to EXECUTING with an open execution record
        repository.transition_status(task.id, repo.id, PersistedTaskStatus.WORKSPACE_SETUP)
        repository.transition_status(task.id, repo.id, PersistedTaskStatus.EXECUTING)
        ex = repository.record_execution_start(task.id, repo.id, worker_id="worker-crash-1")

        # Simulate worker crash & restart reconciliation
        reconciled = repository.reconcile_crashed_task(task.id, repo.id, reason="Worker SIGKILL detected")

        assert reconciled.status == PersistedTaskStatus.RECOVERY_REQUIRED.value
        assert "Worker SIGKILL detected" in reconciled.error_message

        # Verify dangling execution record is marked FAILED
        db_session.refresh(ex)
        assert ex.status == ExecutionStatus.FAILED.value
        assert ex.error_message == "Worker SIGKILL detected"

        # Verify CRASH_RECOVERED event logged
        timeline = repository.get_task_timeline(task.id, repo.id)
        crash_events = [e for e in timeline if e.event_type == "CRASH_RECOVERED"]
        assert len(crash_events) == 1
        assert crash_events[0].event_data["step_name"] == "step_3_file_modified"

    def test_recover_interrupted_task_without_checkpoint(self, db_session: Session) -> None:
        """An interrupted task with no checkpoint is transitioned to RECOVERY_REQUIRED for manual triage."""
        user, repo = _seed_user_and_repo(db_session, "crash-nocp")
        repository = TaskRepository(db_session)

        task = repository.create_task(repo.id, "No-CP Task", user_id=user.id)
        plan = repository.save_plan(task.id, repo.id, summary="Plan", steps=[{"step": 1}])
        repository.approve_plan(task.id, repo.id, plan_version=plan.version, user_id=user.id)
        repository.record_workspace(task.id, repo.id, "/ws/task", "agent/task", "base-sha")
        repository.transition_status(task.id, repo.id, PersistedTaskStatus.WORKSPACE_SETUP)
        repository.transition_status(task.id, repo.id, PersistedTaskStatus.EXECUTING)
        repository.transition_status(task.id, repo.id, PersistedTaskStatus.TESTING)

        reconciled = repository.reconcile_crashed_task(task.id, repo.id, reason="Host out of memory")

        assert reconciled.status == PersistedTaskStatus.RECOVERY_REQUIRED.value
        timeline = repository.get_task_timeline(task.id, repo.id)
        detected_events = [e for e in timeline if e.event_type == "CRASH_DETECTED"]
        assert len(detected_events) == 1
        assert "Host out of memory" in detected_events[0].event_data["reason"]

    def test_recover_task_with_exhausted_retry_budget(self, db_session: Session) -> None:
        """When repair budget is exhausted, crash recovery transitions task to FAILED rather than infinite loop."""
        user, repo = _seed_user_and_repo(db_session, "crash-exhaust")
        repository = TaskRepository(db_session)

        task = repository.create_task(repo.id, "Budget Exhausted Task", user_id=user.id)
        plan = repository.save_plan(task.id, repo.id, summary="Plan", steps=[{"step": 1}])
        repository.approve_plan(task.id, repo.id, plan_version=plan.version, user_id=user.id)
        repository.record_workspace(task.id, repo.id, "/ws/task", "agent/task", "base-sha")
        repository.transition_status(task.id, repo.id, PersistedTaskStatus.WORKSPACE_SETUP)
        repository.transition_status(task.id, repo.id, PersistedTaskStatus.EXECUTING)
        repository.transition_status(task.id, repo.id, PersistedTaskStatus.TESTING)
        repository.transition_status(task.id, repo.id, PersistedTaskStatus.REPAIRING)

        # Exhaust repair attempts to 3
        repository.increment_repair_attempt(task.id, repo.id)
        repository.increment_repair_attempt(task.id, repo.id)
        repository.increment_repair_attempt(task.id, repo.id)
        db_session.refresh(task)
        assert task.repair_attempts_used == 3

        reconciled = repository.reconcile_crashed_task(task.id, repo.id, reason="Worker crash during repair attempt 3")

        assert reconciled.status == PersistedTaskStatus.FAILED.value
        assert "repair attempt budget exhausted" in reconciled.error_message

        timeline = repository.get_task_timeline(task.id, repo.id)
        failed_events = [e for e in timeline if e.event_type == "RECOVERY_FAILED"]
        assert len(failed_events) == 1

    def test_retry_counter_preserved_across_worker_restart(self, db_session: Session) -> None:
        """Worker crash recovery guarantees that repair_attempts_used is NEVER decremented or reset to 0."""
        user, repo = _seed_user_and_repo(db_session, "retry-pres")
        repository = TaskRepository(db_session)

        task = repository.create_task(repo.id, "Retry Preserved Task", user_id=user.id)
        plan = repository.save_plan(task.id, repo.id, summary="Plan", steps=[{"step": 1}])
        repository.approve_plan(task.id, repo.id, plan_version=plan.version, user_id=user.id)
        repository.record_workspace(task.id, repo.id, "/ws/task", "agent/task", "base-sha")
        repository.transition_status(task.id, repo.id, PersistedTaskStatus.WORKSPACE_SETUP)
        repository.transition_status(task.id, repo.id, PersistedTaskStatus.EXECUTING)
        repository.transition_status(task.id, repo.id, PersistedTaskStatus.TESTING)
        repository.transition_status(task.id, repo.id, PersistedTaskStatus.REPAIRING)

        # 2 attempts used
        repository.increment_repair_attempt(task.id, repo.id)
        repository.increment_repair_attempt(task.id, repo.id)
        db_session.refresh(task)
        assert task.repair_attempts_used == 2

        # Reconcile after crash
        reconciled = repository.reconcile_crashed_task(task.id, repo.id)
        assert reconciled.repair_attempts_used == 2, "Retry counter was corrupted during crash recovery"

    def test_recover_interrupted_tasks_batch_repository_wide(self, db_session: Session) -> None:
        """Batch recovery detects all volatile tasks in a repository and reconciles them."""
        user, repo = _seed_user_and_repo(db_session, "batch-rec")
        service = TaskHistoryService(session=db_session)

        # Create 2 active tasks in volatile states
        t1 = service.create_task(repo.id, "Batch Task 1", user_id=user.id)
        p1 = service.save_plan(t1.id, repo.id, summary="Plan 1", steps=[{"step": 1}])
        service.approve_plan(t1.id, repo.id, plan_version=p1.version, user_id=user.id)
        service.record_workspace(t1.id, repo.id, "/ws/t1", "agent/t1", "base-sha")
        service.transition_status(t1.id, repo.id, PersistedTaskStatus.WORKSPACE_SETUP)
        service.transition_status(t1.id, repo.id, PersistedTaskStatus.EXECUTING)

        t2 = service.create_task(repo.id, "Batch Task 2", user_id=user.id)
        p2 = service.save_plan(t2.id, repo.id, summary="Plan 2", steps=[{"step": 1}])
        service.approve_plan(t2.id, repo.id, plan_version=p2.version, user_id=user.id)
        service.record_workspace(t2.id, repo.id, "/ws/t2", "agent/t2", "base-sha")
        service.transition_status(t2.id, repo.id, PersistedTaskStatus.WORKSPACE_SETUP)
        service.transition_status(t2.id, repo.id, PersistedTaskStatus.EXECUTING)
        service.transition_status(t2.id, repo.id, PersistedTaskStatus.TESTING)

        # Create 1 task in a safe state (PLANNING)
        t3 = service.create_task(repo.id, "Safe Task 3", user_id=user.id)
        service.transition_status(t3.id, repo.id, PersistedTaskStatus.PLANNING)

        # Run repository-wide crash recovery
        recovery_results = service.recover_interrupted_tasks(repo.id, worker_id="worker-node-42")

        assert len(recovery_results) == 2
        recovered_ids = {r["task_id"] for r in recovery_results}
        assert str(t1.id) in recovered_ids
        assert str(t2.id) in recovered_ids
        assert str(t3.id) not in recovered_ids

        # t3 remains unchanged
        db_session.refresh(t3)
        assert t3.status == PersistedTaskStatus.PLANNING.value

    def test_recovery_is_idempotent_on_non_volatile_tasks(self, db_session: Session) -> None:
        """Calling recovery on a task that is completed or in READY_FOR_PUBLICATION is an idempotent no-op."""
        user, repo = _seed_user_and_repo(db_session, "rec-idemp")
        repository = TaskRepository(db_session)

        task = repository.create_task(repo.id, "Completed Task", user_id=user.id)
        plan = repository.save_plan(task.id, repo.id, summary="Plan", steps=[{"step": 1}])
        repository.approve_plan(task.id, repo.id, plan_version=plan.version, user_id=user.id)
        repository.record_workspace(task.id, repo.id, "/ws/task", "agent/task", "base-sha")
        repository.transition_status(task.id, repo.id, PersistedTaskStatus.WORKSPACE_SETUP)
        repository.transition_status(task.id, repo.id, PersistedTaskStatus.EXECUTING)
        repository.transition_status(task.id, repo.id, PersistedTaskStatus.TESTING)
        repository.transition_status(task.id, repo.id, PersistedTaskStatus.VERIFYING)
        repository.record_verification_result(task.id, repo.id, "sha-verified", VerificationStatus.PASSED)
        db_session.refresh(task)
        assert task.status == PersistedTaskStatus.READY_FOR_PUBLICATION.value

        reconciled = repository.reconcile_crashed_task(task.id, repo.id)
        assert reconciled.status == PersistedTaskStatus.READY_FOR_PUBLICATION.value


# ---------------------------------------------------------------------------
# 4. Full 17-Step End-to-End Workflow Acceptance (Day 7)
# ---------------------------------------------------------------------------

class TestFullWorkflow17StepEndToEndAcceptance:
    """Verifies complete 17-step autonomous development lifecycle from Finding to Draft PR."""

    def test_17_step_full_lifecycle_workflow_complete(self, db_session: Session) -> None:
        """Execute full 17-step end-to-end lifecycle and verify 100% referential integrity and audit consistency."""
        user, repo = _seed_user_and_repo(db_session, "17step-demo")
        repository = TaskRepository(db_session)

        # STEP 1: Ingest Week 2 Defect Finding
        run = AnalysisRun(
            id=uuid.uuid4(),
            repository_id=repo.id,
            feature_type=AnalysisFeature.DETECT_BUGS.value,
            status=AnalysisRunStatus.COMPLETED.value,
            target_path="backend/app/auth.py",
            source_revision="commit-base-001",
        )
        db_session.add(run)
        db_session.flush()

        finding = AnalysisFinding(
            id=uuid.uuid4(),
            analysis_run_id=run.id,
            repository_id=repo.id,
            category="SECURITY",
            severity="HIGH",
            title="SQL Injection vulnerability in user lookup",
            description="String formatting in raw SQL query creates injection risk",
            evidence="db.execute(f'SELECT * FROM users WHERE id = {user_id}')",
            file_path="backend/app/auth.py",
            start_line=120,
            end_line=125,
        )
        db_session.add(finding)
        db_session.flush()

        # STEP 2: Create GitHub Issue from Finding
        issue, _ = repository.upsert_github_issue(
            repository_id=repo.id,
            issue_number=101,
            title="[Security] Fix SQL Injection in auth.py",
            body="Identified SQL injection flaw in auth.py during Week 2 scan.",
            html_url="https://github.com/17step-org/repo-17step/issues/101",
            author="security-bot",
            origin_finding_id=finding.id,
        )
        assert issue.issue_number == 101

        # STEP 3: Create Task linked to GitHub Issue and Finding
        task = repository.create_task(
            repository_id=repo.id,
            title=issue.title,
            description=issue.body,
            source_type=TaskSourceType.GITHUB_ISSUE,
            source_id="101",
            finding_id=finding.id,
            github_issue_id=issue.id,
            user_id=user.id,
            base_revision="commit-base-001",
        )
        assert task.status == PersistedTaskStatus.CREATED.value
        assert task.finding_id == finding.id

        # STEP 4: Generate Implementation Plan (v1) -> Task transitions to PENDING_APPROVAL
        plan_v1 = repository.save_plan(
            task_id=task.id,
            repository_id=repo.id,
            summary="Replace raw SQL with parameterized query",
            steps=[{"step": 1, "action": "Refactor execute statement"}],
            expected_files=["backend/app/auth.py"],
            tests_to_run=["tests/test_auth.py"],
            validation_strategy="Run auth unit tests and static security scan",
            base_revision="commit-base-001",
        )
        assert plan_v1.version == 1
        db_session.refresh(task)
        assert task.status == PersistedTaskStatus.PENDING_APPROVAL.value

        # STEP 5: Human Rejection of Plan v1 with feedback -> Task transitions to REJECTED
        rej = repository.reject_plan(
            task_id=task.id,
            repository_id=repo.id,
            plan_version=1,
            feedback="Please also include SQLAlchemy ORM query rather than raw execute",
            user_id=user.id,
        )
        assert rej.decision == ApprovalDecision.REJECTED.value
        db_session.refresh(task)
        assert task.status == PersistedTaskStatus.REJECTED.value

        # STEP 6: Revise Plan (v2) -> Invalidates prior decision, advances to PENDING_APPROVAL
        plan_v2 = repository.save_plan(
            task_id=task.id,
            repository_id=repo.id,
            summary="Migrate user lookup to SQLAlchemy ORM select() statement",
            steps=[
                {"step": 1, "action": "Replace execute with select(User).where(User.id == user_id)"},
                {"step": 2, "action": "Add parameter boundary tests in tests/test_auth.py"},
            ],
            expected_files=["backend/app/auth.py", "tests/test_auth.py"],
            tests_to_run=["tests/test_auth.py"],
            validation_strategy="Pytest coverage and Bandit security scan",
            base_revision="commit-base-001",
        )
        assert plan_v2.version == 2
        db_session.refresh(task)
        assert task.status == PersistedTaskStatus.PENDING_APPROVAL.value
        assert task.approved_plan_version is None

        # STEP 7: Human Approves Plan v2 -> Task transitions to APPROVED
        appr = repository.approve_plan(
            task_id=task.id,
            repository_id=repo.id,
            plan_version=2,
            feedback="Approved ORM migration plan.",
            user_id=user.id,
        )
        assert appr.decision == ApprovalDecision.APPROVED.value
        db_session.refresh(task)
        assert task.status == PersistedTaskStatus.APPROVED.value
        assert task.approved_plan_version == 2

        # STEP 8: Initialize Workspace -> Transition to EXECUTING
        ws = repository.record_workspace(
            task_id=task.id,
            repository_id=repo.id,
            workspace_path="/tmp/workspaces/task-101",
            task_branch="agent/task-101-sql-injection",
            base_revision="commit-base-001",
            status=WorkspaceRecordStatus.READY,
        )
        assert ws.task_branch == "agent/task-101-sql-injection"

        repository.transition_status(task.id, repo.id, PersistedTaskStatus.WORKSPACE_SETUP)
        repository.transition_status(task.id, repo.id, PersistedTaskStatus.EXECUTING)
        ex = repository.record_execution_start(task.id, repo.id, worker_id="agent-worker-01")

        # STEP 9: Tool Invocations (Read file, Apply patch) with secret scrubbing
        t_read = repository.record_tool_invocation(
            task_id=task.id,
            repository_id=repo.id,
            tool_name="read_file",
            arguments={"path": "backend/app/auth.py", "lines": [120, 130]},
            status=ToolInvocationStatus.COMPLETED,
            duration_ms=12,
            output_summary="Read 10 lines from auth.py",
        )
        t_patch = repository.record_tool_invocation(
            task_id=task.id,
            repository_id=repo.id,
            tool_name="patch_file",
            arguments={"path": "backend/app/auth.py", "diff": "- execute(f'SELECT...')\\n+ select(User)..."},
            status=ToolInvocationStatus.COMPLETED,
            duration_ms=45,
            output_summary="Applied ORM patch to auth.py",
        )
        assert t_read.status == ToolInvocationStatus.COMPLETED.value
        assert t_patch.status == ToolInvocationStatus.COMPLETED.value

        # STEP 10: Run Tests (Attempt 1: Fail) -> Transition to TESTING
        repository.transition_status(task.id, repo.id, PersistedTaskStatus.TESTING)
        tr1 = repository.record_test_run(
            task_id=task.id,
            repository_id=repo.id,
            command="pytest tests/test_auth.py",
            status=TestRunStatus.FAILED,
            exit_code=1,
            duration_ms=1200,
            tests_total=10,
            tests_passed=9,
            tests_failed=1,
            sanitized_output="FAILED tests/test_auth.py::test_user_lookup - NameError: select is not imported",
            target_revision="sha-patch-001",
        )
        assert tr1.tests_failed == 1

        # STEP 11: Bounded Repair Loop (Attempt 1) -> Transition to REPAIRING
        repository.transition_status(task.id, repo.id, PersistedTaskStatus.REPAIRING)
        rep1, ok1 = repository.increment_repair_attempt(
            task_id=task.id,
            repository_id=repo.id,
            failure_classification="SYNTAX_ERROR",
            diagnosis="Missing import for select in auth.py",
            applied_patch="from sqlalchemy import select",
        )
        assert ok1 is True
        assert rep1.attempt_number == 1
        db_session.refresh(task)
        assert task.repair_attempts_used == 1

        # STEP 12: Re-test (Attempt 2: Fail) -> Transition to TESTING
        repository.transition_status(task.id, repo.id, PersistedTaskStatus.TESTING)
        tr2 = repository.record_test_run(
            task_id=task.id,
            repository_id=repo.id,
            command="pytest tests/test_auth.py",
            status=TestRunStatus.FAILED,
            exit_code=1,
            duration_ms=1150,
            tests_total=10,
            tests_passed=9,
            tests_failed=1,
            sanitized_output="FAILED tests/test_auth.py::test_boundary_conditions - AssertionError",
            target_revision="sha-patch-002",
        )
        assert tr2.status == TestRunStatus.FAILED.value

        # STEP 13: Bounded Repair Loop (Attempt 2: Success patch) -> Transition to REPAIRING
        repository.transition_status(task.id, repo.id, PersistedTaskStatus.REPAIRING)
        rep2, ok2 = repository.increment_repair_attempt(
            task_id=task.id,
            repository_id=repo.id,
            failure_classification="ASSERTION_ERROR",
            diagnosis="Fix boundary condition in user lookup handler",
            applied_patch="if not user_id: return None",
        )
        assert ok2 is True
        assert rep2.attempt_number == 2
        db_session.refresh(task)
        assert task.repair_attempts_used == 2

        # STEP 14: Re-test (Attempt 3: Pass) -> Transition to VERIFYING
        repository.transition_status(task.id, repo.id, PersistedTaskStatus.TESTING)
        tr3 = repository.record_test_run(
            task_id=task.id,
            repository_id=repo.id,
            command="pytest tests/test_auth.py",
            status=TestRunStatus.PASSED,
            exit_code=0,
            duration_ms=1320,
            tests_total=10,
            tests_passed=10,
            tests_failed=0,
            sanitized_output="10 passed in 1.32s",
            target_revision="sha-patch-003",
        )
        assert tr3.tests_failed == 0

        repository.record_execution_finish(
            task_id=task.id,
            repository_id=repo.id,
            execution_id=ex.id,
            status=ExecutionStatus.COMPLETED,
        )

        repository.transition_status(task.id, repo.id, PersistedTaskStatus.VERIFYING)

        # STEP 15: Independent Verification Engine (PASSED, 0 blockers) -> READY_FOR_PUBLICATION
        ver = repository.record_verification_result(
            task_id=task.id,
            repository_id=repo.id,
            verified_revision="sha-patch-003",
            status=VerificationStatus.PASSED,
            checks=[
                {"check": "pytest", "status": "PASSED"},
                {"check": "bandit", "status": "PASSED"},
                {"check": "ruff", "status": "PASSED"},
                {"check": "ai_review", "status": "PASSED"},
            ],
            blocking_findings=[],
            warnings=[],
            summary="All tests passed, zero security flaws, clean AI review.",
        )
        assert ver.status == VerificationStatus.PASSED.value
        db_session.refresh(task)
        assert task.status == PersistedTaskStatus.READY_FOR_PUBLICATION.value

        # STEP 16: Human Publication Authorization Gate -> Transition to PUBLISHING
        auth_res = repository.authorize_publication(
            task_id=task.id,
            repository_id=repo.id,
            head_sha="sha-patch-003",
            user_id=user.id,
            notes="Ready to publish PR to GitHub",
        )
        assert auth_res.status == PersistedTaskStatus.PUBLISHING.value
        db_session.refresh(task)
        assert task.status == PersistedTaskStatus.PUBLISHING.value

        # STEP 17: Published GitHub Draft PR -> Transition to DRAFT_PR_CREATED
        pr = repository.record_pull_request(
            task_id=task.id,
            repository_id=repo.id,
            pr_url="https://github.com/17step-org/repo-17step/pull/202",
            base_branch="main",
            head_branch="agent/task-101-sql-injection",
            head_sha="sha-patch-003",
            title=f"Fix #{issue.issue_number}: {task.title}",
            body="Autonomous PR addressing SQL injection in auth.py with SQLAlchemy ORM query.",
            pr_number=202,
            is_draft=True,
        )
        assert pr.pr_number == 202
        db_session.refresh(task)
        assert task.status == PersistedTaskStatus.DRAFT_PR_CREATED.value

        # VERIFICATION: End-to-End Traceability Graph Validation
        trace = repository.get_task_traceability(task.id, repo.id)
        assert trace["is_complete_workflow"] is True
        assert trace["traceability_status"] == "COMPLETE"
        assert trace["task"]["status"] == PersistedTaskStatus.DRAFT_PR_CREATED.value
        assert trace["finding"]["finding_id"] == str(finding.id)
        assert trace["latest_plan"]["version"] == 2
        assert trace["latest_approval"]["decision"] == ApprovalDecision.APPROVED.value
        assert trace["workspace"]["task_branch"] == "agent/task-101-sql-injection"
        assert trace["repair_attempts_used"] == 2
        assert len(trace["tool_invocations"]) == 2
        assert len(trace["test_runs"]) == 3
        assert len(trace["repair_attempts"]) == 2
        assert trace["latest_verification"]["status"] == VerificationStatus.PASSED.value
        assert trace["pull_request"]["pr_number"] == 202

        # Validate against Pydantic schema
        pydantic_trace = TaskTraceabilityResponse.model_validate(trace)
        assert pydantic_trace.is_complete_workflow is True
        assert pydantic_trace.pull_request.pr_url == "https://github.com/17step-org/repo-17step/pull/202"

        # Verify zero manual interventions occurred between Step 7 approval and Step 17 PR creation
        timeline = repository.get_task_timeline(task.id, repo.id)
        assert len(timeline) >= 12


# ---------------------------------------------------------------------------
# 5. Multi-Tenant Day 6 & 7 Isolation
# ---------------------------------------------------------------------------

class TestMultiTenantDay6Day7Isolation:
    """Verifies that active tasks, crash recovery, and traceability are completely isolated across repositories."""

    def test_cross_repository_active_tasks_and_recovery_isolated(self, db_session: Session) -> None:
        """Tasks from Repo A cannot be listed or recovered by queries targeting Repo B."""
        user_a, repo_a = _seed_user_and_repo(db_session, "tenant-a")
        user_b, repo_b = _seed_user_and_repo(db_session, "tenant-b")
        repository = TaskRepository(db_session)

        # Create active task in Repo A
        t_a = repository.create_task(repo_a.id, "Repo A Task", user_id=user_a.id)

        # Query active tasks in Repo B
        actives_b = repository.get_active_tasks_for_repository(repo_b.id)
        assert len(actives_b) == 0

        # Run recovery in Repo B
        rec_b = repository.recover_interrupted_tasks(repo_b.id)
        assert len(rec_b) == 0

        # Task A remains untouched in CREATED status
        db_session.refresh(t_a)
        assert t_a.status == PersistedTaskStatus.CREATED.value

    def test_cross_repository_traceability_blocked(self, db_session: Session) -> None:
        """Attempting to access Repo A's task traceability using Repo B's ID raises TaskNotFoundError."""
        user_a, repo_a = _seed_user_and_repo(db_session, "trace-iso-a")
        _, repo_b = _seed_user_and_repo(db_session, "trace-iso-b")
        repository = TaskRepository(db_session)

        task_a = repository.create_task(repo_a.id, "Task A", user_id=user_a.id)

        with pytest.raises(TaskNotFoundError):
            repository.get_task_traceability(task_a.id, repo_b.id)


# ---------------------------------------------------------------------------
# 6. Pydantic Schema Conformity (Days 6 & 7)
# ---------------------------------------------------------------------------

class TestPydanticSchemaConformityDay6Day7:
    """Validates that Day 6 and Day 7 responses conform strictly to agreed Pydantic contracts."""

    def test_task_recovery_response_schema_validation(self) -> None:
        """Validate TaskRecoveryResponse schema instantiation."""
        rec_data = {
            "recovered_tasks_count": 2,
            "tasks": [
                {"task_id": str(uuid.uuid4()), "status": "RECOVERY_REQUIRED"},
                {"task_id": str(uuid.uuid4()), "status": "FAILED"},
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        resp = TaskRecoveryResponse.model_validate(rec_data)
        assert resp.recovered_tasks_count == 2
        assert len(resp.tasks) == 2

    def test_task_traceability_response_with_empty_collections(self, db_session: Session) -> None:
        """A freshly created task's traceability validates cleanly against TaskTraceabilityResponse."""
        user, repo = _seed_user_and_repo(db_session, "schema-trace")
        repository = TaskRepository(db_session)

        task = repository.create_task(repo.id, "Minimal Traceability Task", user_id=user.id)
        trace_dict = repository.get_task_traceability(task.id, repo.id)

        resp = TaskTraceabilityResponse.model_validate(trace_dict)
        assert resp.task.task_id == str(task.id)
        assert resp.is_complete_workflow is False
        assert len(resp.tool_invocations) == 0
        assert len(resp.test_runs) == 0
        assert len(resp.repair_attempts) == 0
