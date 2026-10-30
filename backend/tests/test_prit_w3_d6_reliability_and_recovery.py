"""Week 3 Day 6 Acceptance & Integration Test Suite.

Owner: Prit Zania — Week 3 Day 6 Deliverable (Docs/week3.md §6 F33, F36, F37, §8 Day 6, line 636)
Reference:
- Docs/week3.md §6 (F33 Workspace Sandbox, F36 Diff Verifier, F37 Git Integration)
- Docs/week3.md §8 (Day 6 Reliability, Security and Failure Recovery)
- Docs/daily_tasks.md (line 636: Prit Day 6 Task - Failure Recovery, Stale Revision Detection, Diff Immutability, Cleanup Hardening)
- ADR-007 (Sandbox Isolation), ADR-010 (Mandatory Approval Gate, Zero Auto-Merge)

Verifies:
1. Worker crash and restart recovery (reconciliation of interrupted, orphaned, and stale workspaces).
2. Detection and prevention of stale base-revision divergence against remote branches.
3. Verification-to-publication diff immutability and post-verification mutation detection.
4. Hardened sandbox cleanup, orphan garbage collection, and safe removal of abandoned workspaces.
5. Sandbox invariant validation (path isolation, disk quotas, process isolation, forbidden secrets).
6. Per-task concurrency control and mutex locking preventing race conditions.
7. Strict credential and secret redaction across log entries, timeline events, and error messages.
8. Complete ToolRouter registration and policy dispatch for Day 6 canonical tools.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from agent.tools.router import ToolDefinition, ToolRequest, ToolResult, ToolRouter
from app.schemas.workspace import (
    DiffImmutabilityCheckResult,
    StaleRevisionCheckResult,
    WorkspaceCreateRequest,
    WorkspaceDiskUsageResult,
    WorkspaceExecutionEventType,
    WorkspaceInvariantCheckResult,
    WorkspaceMetadata,
    WorkspaceOrphanCleanupResult,
    WorkspaceRecoveryRecord,
    WorkspaceRecoveryResult,
    WorkspaceResourceLimits,
    WorkspaceStartExecutionRequest,
    WorkspaceStatus,
)
from sandbox.constants import (
    DEFAULT_MAX_ORPHAN_AGE_SECONDS,
    DEFAULT_MAX_WORKSPACE_FILES,
    PROTECTED_BRANCHES,
    RECOVERY_STALE_TIMEOUT_SECONDS,
)
from sandbox.exceptions import (
    WorkspaceConcurrentOperationError,
    WorkspaceDiffDivergedError,
    WorkspaceDiskQuotaExceededError,
    WorkspaceError,
    WorkspaceInvariantViolationError,
    WorkspacePathEscapeError,
    WorkspacePolicyViolationError,
    WorkspacePostVerificationMutationError,
    WorkspaceRecoveryError,
    WorkspaceStaleRevisionError,
    WorkspaceStateError,
)
from sandbox.path_guard import WorkspacePathGuard
from sandbox.tool_policy_bridge import (
    CANONICAL_WORKSPACE_TOOLS,
    TOOL_CHECK_DISK_BUDGET,
    TOOL_CHECK_STALE_REVISION,
    TOOL_CLEANUP_ORPHANED,
    TOOL_RECOVER_WORKSPACE,
    TOOL_VALIDATE_INVARIANTS,
    TOOL_VERIFY_DIFF_IMMUTABILITY,
    WorkspaceToolPolicyBridge,
    register_workspace_tools,
)
from sandbox.workspace_manager import WorkspaceManager


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
        updated_meta = json.loads((ws_dir / "metadata.json").read_text(encoding="utf-8"))
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
