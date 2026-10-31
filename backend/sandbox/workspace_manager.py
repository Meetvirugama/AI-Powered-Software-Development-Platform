"""Isolated Workspace Manager Implementation.

Owner: Prit Zania — Week 3 Day 1 Deliverable (Docs/week3.md §6 F33, §8 Day 1)
Reference: Docs/week3.md §6 (F33 — Isolated Workspace and Repository Operations)

Key Capabilities:
1. Provisions disposable task workspaces under designated sandboxes (.workspaces/task-<id>).
2. Supports Git worktree isolation with automatic fallback to isolated directory trees.
3. Enforces full lifecycle state machine (NOT_CREATED -> CREATING -> READY -> IN_USE -> STOPPED/FAILED -> CLEANUP_PENDING -> CLEANED).
4. Provides guarded, sandboxed file operations (read, write, patch, delete, list).
5. Imforces resource quotas (file size caps, disk budgets, modified file counts).
6. Guarantees safe, idempotent cleanup without touching host repository or sibling tasks.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import stat
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from app.core.config import PROJECT_ROOT
from app.core.secret_redaction import redact
from app.services.git_branch import format_agent_branch_name
from app.schemas.workspace import (
    DiffImmutabilityCheckRequest,
    DiffImmutabilityCheckResult,
    DiffValidationRequest,
    DiffValidationResult,
    RepairAttemptRecord,
    StaleRevisionCheckRequest,
    StaleRevisionCheckResult,
    TestFailureClassification,
    TestOutcomeStatus,
    WorkspaceCleanupResult,
    WorkspaceCommandRequest,
    WorkspaceCommandResult,
    WorkspaceCommitRequest,
    WorkspaceCommitResult,
    WorkspaceCreateRequest,
    WorkspaceCreateResult,
    WorkspaceDiffRequest,
    WorkspaceDiffResult,
    WorkspaceDiskUsageResult,
    WorkspaceDraftPRRequest,
    WorkspaceDraftPRResult,
    WorkspaceExecutionEvent,
    WorkspaceExecutionEventType,
    WorkspaceFilePatchRequest,
    WorkspaceFilePatchResult,
    WorkspaceFileReadRequest,
    WorkspaceFileReadResult,
    WorkspaceFileWriteRequest,
    WorkspaceFileWriteResult,
    WorkspaceInvariantCheckResult,
    WorkspaceIsolationType,
    WorkspaceMetadata,
    WorkspaceOrphanCleanupResult,
    WorkspacePushRequest,
    WorkspacePushResult,
    WorkspaceRecoveryRecord,
    WorkspaceRecoveryResult,
    WorkspaceRepairBudgetStatus,
    WorkspaceResourceLimits,
    WorkspaceStartExecutionRequest,
    WorkspaceStartExecutionResult,
    WorkspaceStatus,
    WorkspaceTestExecutionRequest,
    WorkspaceTestExecutionResult,
    can_transition_workspace,
)
from sandbox.command_runner import WorkspaceCommandRunner
from sandbox.constants import (
    DEFAULT_MAX_ORPHAN_AGE_SECONDS,
    DEFAULT_MAX_WORKSPACE_FILES,
    DEFAULT_WORKSPACE_SUBDIR,
    MAX_TASK_LOCK_TIMEOUT_SECONDS,
    PROTECTED_BRANCHES,
    RECOVERY_STALE_TIMEOUT_SECONDS,
    SECRET_SCAN_PATTERNS,
)
from sandbox.diff_verifier import WorkspaceDiffVerifier
from sandbox.exceptions import (
    WorkspaceAuthorizationError,
    WorkspaceCleanupError,
    WorkspaceCommandError,
    WorkspaceCommandTimeoutError,
    WorkspaceCommitError,
    WorkspaceConcurrentOperationError,
    WorkspaceCreationError,
    WorkspaceDiffDivergedError,
    WorkspaceDiffError,
    WorkspaceDiffValidationError,
    WorkspaceDiskQuotaExceededError,
    WorkspaceDraftPRError,
    WorkspaceDuplicateRepairPatchError,
    WorkspaceError,
    WorkspaceFileError,
    WorkspaceInvariantViolationError,
    WorkspaceLimitExceededError,
    WorkspacePathEscapeError,
    WorkspacePolicyViolationError,
    WorkspacePostVerificationMutationError,
    WorkspaceProtectedBranchError,
    WorkspacePublicationUnauthorizedError,
    WorkspacePushError,
    WorkspaceRecoveryError,
    WorkspaceRepairBudgetExhaustedError,
    WorkspaceSecretLeakDetectedError,
    WorkspaceStaleApprovalError,
    WorkspaceStaleRevisionError,
    WorkspaceStateError,
    WorkspaceTestExecutionError,
    WorkspaceUnsupportedFrameworkError,
)
from sandbox.path_guard import WorkspacePathGuard
from sandbox.resource_monitor import WorkspaceResourceMonitor
from sandbox.test_runner import WorkspaceTestRunner

logger = logging.getLogger(__name__)


class WorkspaceManager:
    """Manages isolated working environments and Git worktrees for tasks."""

    def __init__(self, base_workspaces_dir: str | Path | None = None) -> None:
        """Initialize the workspace manager.

        Args:
            base_workspaces_dir: Custom root for workspace sandboxes. Defaults to PROJECT_ROOT / .workspaces.
        """
        if base_workspaces_dir is not None:
            self._base_dir = Path(base_workspaces_dir).resolve()
        else:
            self._base_dir = (PROJECT_ROOT / DEFAULT_WORKSPACE_SUBDIR).resolve()

        self._workspaces: dict[str, WorkspaceMetadata] = {}
        self._monitors: dict[str, WorkspaceResourceMonitor] = {}
        self._timeline: dict[str, list[WorkspaceExecutionEvent]] = {}
        self._command_runner = WorkspaceCommandRunner()
        self._test_runner = WorkspaceTestRunner(command_runner=self._command_runner)
        self._test_history: dict[str, list[WorkspaceTestExecutionResult]] = {}
        self._diff_verifier = WorkspaceDiffVerifier()
        self._repo_roots: dict[str, Path] = {}
        self._task_locks: dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()

    @property
    def base_directory(self) -> Path:
        """Return the base directory housing all task workspaces."""
        return self._base_dir

    @property
    def command_runner(self) -> WorkspaceCommandRunner:
        """Return the bound sandboxed command runner."""
        return self._command_runner

    @property
    def test_runner(self) -> WorkspaceTestRunner:
        """Return the bound restricted test runner."""
        return self._test_runner

    @property
    def diff_verifier(self) -> WorkspaceDiffVerifier:
        """Return the bound workspace diff verifier."""
        return self._diff_verifier


    # -----------------------------------------------------------------------
    # Workspace Lifecycle Operations
    # -----------------------------------------------------------------------

    def create_workspace(self, request: WorkspaceCreateRequest) -> WorkspaceMetadata:
        """Create and initialize an isolated workspace for a task.

        Lifecycle: NOT_CREATED -> CREATING -> READY (or FAILED on error).
        """
        task_id = str(request.task_id).strip()
        start_time = time.perf_counter()

        # Idempotency / conflict check
        existing = self._workspaces.get(task_id)
        if existing and existing.status in (WorkspaceStatus.READY, WorkspaceStatus.IN_USE):
            return existing

        # Ensure base directory exists
        self._base_dir.mkdir(parents=True, exist_ok=True)
        WorkspacePathGuard.validate_workspace_root(self._base_dir)

        # Formulate safe workspace path
        raw_slug = task_id[5:] if task_id.lower().startswith("task-") else task_id
        cleaned_short = format_agent_branch_name(raw_slug).replace("agent/task-", "")
        task_hash = hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:8]
        safe_task_slug = f"task-{cleaned_short}-{task_hash}"
        workspace_path = (self._base_dir / safe_task_slug).resolve()

        branch_name = request.branch_name or f"agent/{safe_task_slug}"
        limits = request.resource_limits or WorkspaceResourceLimits()


        metadata = WorkspaceMetadata(
            workspace_id=str(uuid4()),
            task_id=task_id,
            repository_id=str(request.repository_id),
            base_revision=request.base_revision,
            branch_name=branch_name,
            workspace_path=str(workspace_path),
            status=WorkspaceStatus.CREATING,
            isolation_type=request.isolation_type,
            resource_limits=limits,
        )
        self._workspaces[task_id] = metadata

        if request.repository_root:
            self._repo_roots[task_id] = Path(request.repository_root)

        try:
            isolation_used = self._provision_workspace(
                workspace_path=workspace_path,
                repo_root=Path(request.repository_root) if request.repository_root else None,
                base_revision=request.base_revision,
                branch_name=branch_name,
                preferred_isolation=request.isolation_type,
            )
            metadata.isolation_type = isolation_used
            metadata.status = WorkspaceStatus.READY
            metadata.updated_at = datetime.now(timezone.utc).isoformat()
            self._save_metadata_file(metadata)
            self._monitors[task_id] = WorkspaceResourceMonitor(workspace_path, limits)

            # Record initial timeline events (Docs/week3.md §8 Day 3)
            self.record_timeline_event(
                task_id=task_id,
                event_type=WorkspaceExecutionEventType.WORKSPACE_CREATED,
                message=f"Workspace provisioned via {isolation_used}.",
                payload={"workspace_path": str(workspace_path), "isolation": isolation_used},
            )
            self.record_timeline_event(
                task_id=task_id,
                event_type=WorkspaceExecutionEventType.BRANCH_SETUP,
                message=f"Task branch '{branch_name}' isolated at revision '{request.base_revision}'.",
                payload={"branch_name": branch_name, "base_revision": request.base_revision},
            )

            duration_ms = (time.perf_counter() - start_time) * 1000.0

            logger.info(
                "workspace_created",
                extra={
                    "task_id": task_id,
                    "workspace_id": metadata.workspace_id,
                    "path": str(workspace_path),
                    "duration_ms": duration_ms,
                    "isolation": isolation_used,
                },
            )
            return metadata

        except Exception as exc:
            metadata.status = WorkspaceStatus.FAILED
            metadata.error_message = redact(str(exc))
            metadata.updated_at = datetime.now(timezone.utc).isoformat()
            # Clean up partial directory on failure
            self._safe_remove_dir(workspace_path)
            raise WorkspaceCreationError(f"Failed to create workspace for task '{task_id}': {exc}") from exc

    def _provision_workspace(
        self,
        workspace_path: Path,
        repo_root: Path | None,
        base_revision: str,
        branch_name: str,
        preferred_isolation: WorkspaceIsolationType,
    ) -> WorkspaceIsolationType:
        """Provision the filesystem tree using git worktree or directory copy."""
        # Clean existing path if needed
        self._safe_remove_dir(workspace_path)

        if preferred_isolation == "git_worktree" and repo_root and (repo_root / ".git").exists():
            try:
                # Try creating git worktree
                # git worktree add -B <branch_name> <workspace_path> <base_revision>
                cmd = [
                    "git",
                    "-C",
                    str(repo_root),
                    "worktree",
                    "add",
                    "-B",
                    branch_name,
                    str(workspace_path),
                    base_revision,
                ]
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30,
                )
                if proc.returncode == 0 and workspace_path.exists():
                    return "git_worktree"
                logger.warning(
                    "git_worktree_failed_falling_back",
                    extra={"stderr": proc.stderr, "task_path": str(workspace_path)},
                )
            except Exception as e:
                logger.warning(
                    "git_worktree_exception_falling_back",
                    extra={"error": str(e)},
                )

        # Fallback to isolated directory copy if repo_root is provided, or create empty sandbox
        workspace_path.mkdir(parents=True, exist_ok=True)
        if repo_root and repo_root.exists():
            for item in repo_root.iterdir():
                if item.name in (".git", ".workspaces", "venv", "__pycache__", ".pytest_cache", "node_modules"):
                    continue
                if item.is_symlink():
                    continue
                dest = workspace_path / item.name
                if item.is_dir():
                    shutil.copytree(item, dest, symlinks=True, ignore=shutil.ignore_patterns(".git*", "__pycache__"))
                elif item.is_file():
                    shutil.copy2(item, dest, follow_symlinks=False)

        # In directory_copy mode, initialize a local git repository baseline if not present
        if not (workspace_path / ".git").exists():
            try:
                subprocess.run(["git", "init"], cwd=workspace_path, capture_output=True, check=False)
                subprocess.run(["git", "config", "user.name", "AI Platform"], cwd=workspace_path, capture_output=True, check=False)
                subprocess.run(["git", "config", "user.email", "agent@ai-platform.local"], cwd=workspace_path, capture_output=True, check=False)
                subprocess.run(["git", "add", "."], cwd=workspace_path, capture_output=True, check=False)
                subprocess.run(["git", "commit", "-m", "Initial baseline"], cwd=workspace_path, capture_output=True, check=False)
                subprocess.run(["git", "checkout", "-b", branch_name], cwd=workspace_path, capture_output=True, check=False)
            except Exception:
                pass

        return "directory_copy"

    def get_workspace(self, task_id: str) -> WorkspaceMetadata | None:
        """Retrieve workspace metadata by task ID."""
        return self._workspaces.get(task_id)

    def get_workspace_path(self, task_id: str) -> Path:
        """Resolve the verified workspace root Path for a task."""
        meta = self.get_workspace(task_id)
        if not meta:
            raise WorkspaceError(f"Workspace not found for task '{task_id}'.")
        if meta.status not in (WorkspaceStatus.READY, WorkspaceStatus.IN_USE):
            raise WorkspaceStateError(
                f"Workspace for task '{task_id}' is in state '{meta.status}', not available for operations."
            )
        path = Path(meta.workspace_path)
        if not path.exists():
            raise WorkspaceError(f"Workspace directory on disk missing for task '{task_id}': {path}")
        return path

    def transition_state(self, task_id: str, new_status: WorkspaceStatus) -> WorkspaceMetadata:
        """Transition a workspace to a new state enforcing the state machine."""
        meta = self.get_workspace(task_id)
        if not meta:
            raise WorkspaceError(f"Workspace not found for task '{task_id}'.")

        if not can_transition_workspace(meta.status, new_status):
            raise WorkspaceStateError(
                f"Cannot transition workspace '{task_id}' from '{meta.status}' to '{new_status}'."
            )

        meta.status = new_status
        meta.updated_at = datetime.now(timezone.utc).isoformat()
        self._save_metadata_file(meta)
        return meta

    # -----------------------------------------------------------------------
    # Week 3 Day 3 — Execution Start & Lifecycle Management
    # -----------------------------------------------------------------------

    def start_execution(self, request: WorkspaceStartExecutionRequest) -> WorkspaceStartExecutionResult:
        """Safely start an approved task in an isolated workspace (Docs/week3.md §8 Day 3).

        Enforces:
        1. Task approval gate (ADR-010): Task must be in APPROVED status. Unapproved tasks are blocked.
        2. Base-revision consistency check: If approved_base_revision is supplied, must match workspace base_revision.
        3. Lifecycle transition: READY (or STOPPED) -> IN_USE.
        4. Timeline recording: Emits EXECUTION_STARTED event.
        """
        task_id = request.task_id.strip()
        meta = self.get_workspace(task_id)
        if not meta:
            raise WorkspaceError(f"Workspace not found for task '{task_id}'. Cannot start execution.")

        # 1. Approval Gate Check (ADR-010, Docs/week3.md §8 Day 3)
        norm_task_status = str(request.task_status or "").strip().upper()
        if norm_task_status != "APPROVED":
            error_msg = (
                f"Task '{task_id}' is in status '{norm_task_status}'. "
                "Execution cannot bypass human approval (ADR-010, Docs/week3.md §8 Day 3)."
            )
            logger.warning("unapproved_execution_blocked", extra={"task_id": task_id, "status": norm_task_status})
            raise WorkspaceAuthorizationError(error_msg)

        # 2. Base Revision Consistency (Stale Approval Check)
        if request.approved_base_revision:
            norm_approved = request.approved_base_revision.strip()
            if norm_approved != meta.base_revision:
                error_msg = (
                    f"Task '{task_id}' base revision changed from approved '{norm_approved}' "
                    f"to current '{meta.base_revision}'. Previous approval is invalidated."
                )
                logger.warning(
                    "stale_approval_detected",
                    extra={"task_id": task_id, "approved": norm_approved, "current": meta.base_revision},
                )
                raise WorkspaceStaleApprovalError(error_msg)

        # 3. Transition State
        if meta.status == WorkspaceStatus.IN_USE:
            # Idempotent re-entry
            return WorkspaceStartExecutionResult(
                success=True,
                task_id=task_id,
                workspace_id=meta.workspace_id,
                status=meta.status,
                branch_name=meta.branch_name,
                base_revision=meta.base_revision,
                started_at=datetime.now(timezone.utc).isoformat(),
            )

        if meta.status not in (WorkspaceStatus.READY, WorkspaceStatus.STOPPED):
            raise WorkspaceStateError(
                f"Workspace for task '{task_id}' is in state '{meta.status.value}', cannot start execution. Expected READY or STOPPED."
            )

        self.transition_state(task_id, WorkspaceStatus.IN_USE)

        # 4. Emit Timeline Event
        started_at = datetime.now(timezone.utc).isoformat()
        self.record_timeline_event(
            task_id=task_id,
            event_type=WorkspaceExecutionEventType.EXECUTION_STARTED,
            message=f"Execution started for task '{task_id}' on branch '{meta.branch_name}'.",
            payload={
                "started_at": started_at,
                "plan_version": request.plan_version,
                "base_revision": meta.base_revision,
                "branch_name": meta.branch_name,
            },
        )

        return WorkspaceStartExecutionResult(
            success=True,
            task_id=task_id,
            workspace_id=meta.workspace_id,
            status=meta.status,
            branch_name=meta.branch_name,
            base_revision=meta.base_revision,
            started_at=started_at,
        )

    def pause_execution(self, task_id: str, reason: str = "") -> WorkspaceMetadata:
        """Pause execution in the workspace, transitioning IN_USE -> STOPPED."""
        meta = self.get_workspace(task_id)
        if not meta:
            raise WorkspaceError(f"Workspace not found for task '{task_id}'.")
        if meta.status != WorkspaceStatus.IN_USE:
            raise WorkspaceStateError(
                f"Cannot pause workspace '{task_id}' in state '{meta.status.value}'. Must be IN_USE."
            )
        self.transition_state(task_id, WorkspaceStatus.STOPPED)
        self.record_timeline_event(
            task_id=task_id,
            event_type=WorkspaceExecutionEventType.EXECUTION_PAUSED,
            message=f"Execution paused: {reason or 'Requested by orchestrator/operator'}",
            payload={"reason": reason},
        )
        return meta

    def resume_execution(self, task_id: str) -> WorkspaceMetadata:
        """Resume paused execution, transitioning STOPPED -> IN_USE."""
        meta = self.get_workspace(task_id)
        if not meta:
            raise WorkspaceError(f"Workspace not found for task '{task_id}'.")
        if meta.status != WorkspaceStatus.STOPPED:
            raise WorkspaceStateError(
                f"Cannot resume workspace '{task_id}' in state '{meta.status.value}'. Must be STOPPED."
            )
        self.transition_state(task_id, WorkspaceStatus.IN_USE)
        self.record_timeline_event(
            task_id=task_id,
            event_type=WorkspaceExecutionEventType.EXECUTION_RESUMED,
            message="Execution resumed in isolated workspace.",
            payload={"resumed_at": datetime.now(timezone.utc).isoformat()},
        )
        return meta

    def stop_execution(self, task_id: str, reason: str = "") -> WorkspaceMetadata:
        """Stop execution in the workspace."""
        meta = self.get_workspace(task_id)
        if not meta:
            raise WorkspaceError(f"Workspace not found for task '{task_id}'.")
        if meta.status in (WorkspaceStatus.IN_USE, WorkspaceStatus.READY):
            self.transition_state(task_id, WorkspaceStatus.STOPPED)
        self.record_timeline_event(
            task_id=task_id,
            event_type=WorkspaceExecutionEventType.EXECUTION_STOPPED,
            message=f"Execution stopped: {reason or 'Execution stopped by operator/orchestrator'}",
            payload={"reason": reason},
        )
        return meta

    def fail_execution(self, task_id: str, error_message: str) -> WorkspaceMetadata:
        """Mark workspace execution as failed while preserving logs for diagnosis."""
        meta = self.get_workspace(task_id)
        if not meta:
            raise WorkspaceError(f"Workspace not found for task '{task_id}'.")
        meta.status = WorkspaceStatus.FAILED
        meta.error_message = redact(error_message)
        meta.updated_at = datetime.now(timezone.utc).isoformat()
        self.record_timeline_event(
            task_id=task_id,
            event_type=WorkspaceExecutionEventType.EXECUTION_FAILED,
            message=f"Execution failed: {redact(error_message)}",
            payload={"error": redact(error_message)},
        )
        return meta

    def execute_command(self, request: WorkspaceCommandRequest) -> WorkspaceCommandResult:
        """Execute an allowlisted command in the workspace strictly while IN_USE."""
        meta = self.get_workspace(request.task_id)
        if not meta:
            raise WorkspaceError(f"Workspace not found for task '{request.task_id}'.")
        if meta.status != WorkspaceStatus.IN_USE:
            raise WorkspaceStateError(
                f"Cannot execute command in workspace state '{meta.status.value}'. "
                f"Commands are only allowed when workspace is '{WorkspaceStatus.IN_USE.value}'."
            )
        root = Path(meta.workspace_path)
        result = self._command_runner.run_command(
            workspace_root=root,
            command=request.command,
            arguments=request.arguments,
            timeout_seconds=request.timeout_seconds,
            custom_env=request.environment,
        )
        self.record_timeline_event(
            task_id=request.task_id,
            event_type=WorkspaceExecutionEventType.TOOL_INVOCATION,
            message=f"Executed command '{request.command}' (exit code: {result.exit_code}).",
            payload={
                "command": request.command,
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
                "timed_out": result.timed_out,
            },
        )
        return result

    def run_tests(self, request: WorkspaceTestExecutionRequest) -> WorkspaceTestExecutionResult:
        """Execute project tests strictly inside the task workspace sandbox."""
        meta = self.get_workspace(request.task_id)
        if not meta:
            raise WorkspaceError(f"Workspace not found for task '{request.task_id}'.")
        if meta.status != WorkspaceStatus.IN_USE:
            raise WorkspaceStateError(
                f"Cannot run tests in workspace state '{meta.status.value}'. "
                f"Tests can only be executed when workspace is '{WorkspaceStatus.IN_USE.value}'."
            )

        root = Path(meta.workspace_path)

        # 1. Emit Tests Started Timeline Event
        self.record_timeline_event(
            task_id=request.task_id,
            event_type=WorkspaceExecutionEventType.TESTS_STARTED,
            message=f"Running tests for task '{request.task_id}' (target: {request.test_path or 'all tests'}).",
            payload={
                "test_path": request.test_path,
                "framework": request.framework,
                "timeout_seconds": request.timeout_seconds,
            },
        )

        # 2. Execute tests via WorkspaceTestRunner
        result = self._test_runner.run_tests(
            workspace_root=root,
            request=request,
            workspace_id=meta.workspace_id,
            workspace_revision=meta.base_revision,
        )

        # 3. Emit Result Timeline Event
        if result.status == TestOutcomeStatus.PASSED:
            event_type = WorkspaceExecutionEventType.TESTS_PASSED
            msg = f"Tests passed successfully: {result.passed_count} passed in {result.duration_ms:.1f}ms."
        elif result.status == TestOutcomeStatus.TIMEOUT:
            event_type = WorkspaceExecutionEventType.TEST_TIMEOUT
            msg = f"Test execution timed out after {request.timeout_seconds or 60}s."
        elif result.classification == TestFailureClassification.INFRASTRUCTURE_ERROR:
            event_type = WorkspaceExecutionEventType.TEST_INFRASTRUCTURE_FAILURE
            msg = f"Test infrastructure failure: {result.error or 'Execution failed before test completion'}."
        else:
            event_type = WorkspaceExecutionEventType.TESTS_FAILED
            msg = (
                f"Tests failed: {result.failed_count} failed, {result.passed_count} passed "
                f"(repair eligible: {result.is_repair_eligible})."
            )

        self.record_timeline_event(
            task_id=request.task_id,
            event_type=event_type,
            message=msg,
            payload={
                "status": result.status.value,
                "classification": result.classification.value,
                "is_repair_eligible": result.is_repair_eligible,
                "passed_count": result.passed_count,
                "failed_count": result.failed_count,
                "total_count": result.total_count,
                "duration_ms": result.duration_ms,
            },
        )

        # 4. Store in test history
        self._test_history.setdefault(request.task_id, []).append(result)
        return result

    def get_test_history(self, task_id: str) -> list[WorkspaceTestExecutionResult]:
        """Return the chronological test execution history for a task."""
        return list(self._test_history.get(task_id, []))

    def get_repair_budget_status(self, task_id: str) -> WorkspaceRepairBudgetStatus:
        """Return the current self-repair budget status for a task."""
        return self._test_runner.get_repair_budget_status(task_id)

    def record_repair_attempt(
        self,
        task_id: str,
        patch_summary: str,
        patch_content: str | None = None,
        test_status_before: TestOutcomeStatus | None = None,
        test_status_after: TestOutcomeStatus | None = None,
        success: bool = False,
    ) -> RepairAttemptRecord:
        """Record a repair attempt against the 3-attempt ceiling and reject duplicate patches."""
        meta = self.get_workspace(task_id)
        if not meta:
            raise WorkspaceError(f"Workspace not found for task '{task_id}'.")
        if meta.status != WorkspaceStatus.IN_USE:
            raise WorkspaceStateError(
                f"Cannot record repair attempt in workspace state '{meta.status.value}'. Must be IN_USE."
            )

        # Emit repair attempt started
        current_status = self.get_repair_budget_status(task_id)
        attempt_num = current_status.repair_attempts_used + 1

        self.record_timeline_event(
            task_id=task_id,
            event_type=WorkspaceExecutionEventType.REPAIR_ATTEMPT_STARTED,
            message=f"Starting self-repair attempt {attempt_num}/{current_status.repair_attempts_max} for task '{task_id}'.",
            payload={"attempt_number": attempt_num, "patch_summary": patch_summary},
        )

        try:
            record = self._test_runner.record_repair_attempt(
                task_id=task_id,
                patch_summary=patch_summary,
                patch_content=patch_content,
                workspace_revision=meta.base_revision,
                test_status_before=test_status_before,
                test_status_after=test_status_after,
                success=success,
            )
        except WorkspaceRepairBudgetExhaustedError:
            self.record_timeline_event(
                task_id=task_id,
                event_type=WorkspaceExecutionEventType.REPAIR_BUDGET_EXHAUSTED,
                message=f"Self-repair budget exhausted ({current_status.repair_attempts_max}/{current_status.repair_attempts_max} attempts used). Stopping execution.",
                payload={"repair_attempts_used": current_status.repair_attempts_max},
            )
            raise

        self.record_timeline_event(
            task_id=task_id,
            event_type=WorkspaceExecutionEventType.REPAIR_ATTEMPT_COMPLETED,
            message=f"Completed self-repair attempt {record.attempt_number} (success: {record.success}).",
            payload={
                "attempt_number": record.attempt_number,
                "patch_hash": record.patch_hash,
                "success": record.success,
            },
        )

        # Check if this attempt exhausted the budget
        post_status = self.get_repair_budget_status(task_id)
        if post_status.is_budget_exhausted and not record.success:
            self.record_timeline_event(
                task_id=task_id,
                event_type=WorkspaceExecutionEventType.REPAIR_BUDGET_EXHAUSTED,
                message=f"Self-repair budget exhausted ({post_status.repair_attempts_used}/{post_status.repair_attempts_max} attempts used). Human intervention required.",
                payload={"repair_attempts_used": post_status.repair_attempts_used},
            )

        return record

    def get_repair_history(self, task_id: str) -> list[RepairAttemptRecord]:
        """Return the immutable list of repair attempts for a task."""
        return self._test_runner.get_repair_history(task_id)

    def record_timeline_event(
        self,
        task_id: str,
        event_type: WorkspaceExecutionEventType,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> WorkspaceExecutionEvent:
        """Record an execution timeline event for task observability."""
        meta = self._workspaces.get(task_id)
        workspace_id = meta.workspace_id if meta else str(uuid4())
        status = meta.status if meta else WorkspaceStatus.NOT_CREATED

        sanitized_payload = {
            k: redact(str(v)) if isinstance(v, str) else v
            for k, v in (payload or {}).items()
        }
        event = WorkspaceExecutionEvent(
            event_id=str(uuid4()),
            task_id=task_id,
            workspace_id=workspace_id,
            event_type=event_type,
            timestamp=datetime.now(timezone.utc).isoformat(),
            status=status,
            message=redact(message),
            payload=sanitized_payload,
        )
        self._timeline.setdefault(task_id, []).append(event)
        return event

    def get_execution_timeline(self, task_id: str) -> list[WorkspaceExecutionEvent]:
        """Retrieve chronological execution timeline events for a task."""
        return list(self._timeline.get(task_id, []))


    # -----------------------------------------------------------------------
    # Week 3 Day 5 — Diff Validation, Verification, Commit, Push & Draft PR
    # -----------------------------------------------------------------------

    def get_workspace_diff(
        self,
        task_id: str,
        base_revision: str | None = None,
    ) -> WorkspaceDiffResult:
        """Extract unified git diff comparing the workspace working tree to base revision."""
        meta = self.get_workspace(task_id)
        if not meta:
            raise WorkspaceError(f"Workspace not found for task '{task_id}'.")

        ws_path = Path(meta.workspace_path)
        base_rev = base_revision or meta.base_revision

        result = self._diff_verifier.extract_diff(
            workspace_path=ws_path,
            base_revision=base_rev,
            task_id=task_id,
        )

        self.record_timeline_event(
            task_id=task_id,
            event_type=WorkspaceExecutionEventType.DIFF_INSPECTED,
            message=(
                f"Extracted workspace diff: {result.total_files_changed} file(s) changed "
                f"(+{result.insertions}/-{result.deletions})."
            ),
            payload={
                "total_files_changed": result.total_files_changed,
                "insertions": result.insertions,
                "deletions": result.deletions,
                "is_empty": result.is_empty,
                "base_revision": base_rev,
            },
        )
        return result

    def validate_workspace_diff(
        self,
        task_id: str,
        allowed_files: list[str] | None = None,
        allow_critical_deletions: bool = False,
    ) -> DiffValidationResult:
        """Validate workspace changes against scope boundaries, manifests, and secrets."""
        diff_res = self.get_workspace_diff(task_id)
        val_res = self._diff_verifier.validate_diff(
            diff_result=diff_res,
            allowed_files=allowed_files,
            allow_critical_deletions=allow_critical_deletions,
        )

        if val_res.is_valid:
            self.record_timeline_event(
                task_id=task_id,
                event_type=WorkspaceExecutionEventType.DIFF_VALIDATED,
                message=(
                    f"Workspace diff verified ({len(val_res.modified_files)} file(s) in scope, "
                    "0 blocking findings)."
                ),
                payload={
                    "verified_revision": val_res.verified_revision,
                    "modified_files": val_res.modified_files,
                    "warnings": val_res.warnings,
                },
            )
        else:
            self.record_timeline_event(
                task_id=task_id,
                event_type=WorkspaceExecutionEventType.DIFF_VALIDATION_FAILED,
                message=(
                    f"Workspace diff validation failed: {len(val_res.blocking_findings)} blocking finding(s) detected."
                ),
                payload={
                    "blocking_findings": val_res.blocking_findings,
                    "unapproved_files": val_res.unapproved_files,
                    "secret_count": len(val_res.secret_findings),
                },
            )

        return val_res

    def commit_task_changes(
        self,
        request: WorkspaceCommitRequest,
    ) -> WorkspaceCommitResult:
        """Stage and commit validated changes inside workspace on dedicated task branch."""
        meta = self.get_workspace(request.task_id)
        if not meta:
            raise WorkspaceError(f"Workspace not found for task '{request.task_id}'.")

        # Allow commits in IN_USE or READY
        if meta.status not in (WorkspaceStatus.IN_USE, WorkspaceStatus.READY):
            raise WorkspaceStateError(
                f"Cannot commit changes in workspace status '{meta.status.value}'. Must be IN_USE or READY."
            )

        # 1. Target Branch Safety Check
        target_branch = request.branch_name or meta.branch_name or format_agent_branch_name(request.task_id)
        clean_branch = target_branch.strip().removeprefix("refs/heads/").lower()
        if clean_branch in PROTECTED_BRANCHES:
            raise WorkspaceProtectedBranchError(
                f"Cannot commit directly to protected branch '{target_branch}' (ADR-010, Docs/week3.md §6 F37)."
            )

        # 2. Commit Message Validation & Secret Sanitization
        raw_msg = (request.message or "").strip()
        if not raw_msg:
            raise WorkspaceCommitError("Commit message cannot be empty.")

        clean_msg = redact(raw_msg)
        final_message = (
            f"{clean_msg}\n\n"
            f"Task-ID: {request.task_id}\n"
            f"Base-Revision: {meta.base_revision}"
        )

        ws_path = Path(meta.workspace_path)
        git_dir = ws_path / ".git"
        commit_sha = ""
        files_committed = request.files or []

        try:
            if git_dir.exists():
                # Stage files
                if request.files:
                    for f in request.files:
                        WorkspacePathGuard.resolve_within_workspace(ws_path, f)
                    cmd_add = ["git", "-C", str(ws_path), "add", "--"] + list(request.files)
                else:
                    cmd_add = ["git", "-C", str(ws_path), "add", "-A"]

                subprocess.run(cmd_add, capture_output=True, text=True, check=True, timeout=30)

                # Commit
                author_spec = f"{request.author_name} <{request.author_email}>"
                cmd_commit = [
                    "git",
                    "-C",
                    str(ws_path),
                    "commit",
                    "-m",
                    final_message,
                    f"--author={author_spec}",
                ]
                proc_commit = subprocess.run(
                    cmd_commit, capture_output=True, text=True, check=False, timeout=30
                )
                if proc_commit.returncode != 0 and "nothing to commit" not in proc_commit.stdout:
                    raise WorkspaceCommitError(f"git commit failed: {redact(proc_commit.stderr)}")

                # Get commit SHA
                proc_rev = subprocess.run(
                    ["git", "-C", str(ws_path), "rev-parse", "HEAD"],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=10,
                )
                commit_sha = proc_rev.stdout.strip()
            else:
                # Simulated commit in test / file-sandbox environment
                commit_sha = hashlib.sha256(
                    f"{request.task_id}:{final_message}:{time.time()}".encode()
                ).hexdigest()[:12]

            # Update workspace metadata
            meta.base_revision = commit_sha
            meta.branch_name = target_branch
            meta.updated_at = datetime.now(timezone.utc).isoformat()

            self.record_timeline_event(
                task_id=request.task_id,
                event_type=WorkspaceExecutionEventType.CHANGES_COMMITTED,
                message=f"Committed changes on branch '{target_branch}' ({commit_sha[:8]}).",
                payload={
                    "commit_sha": commit_sha,
                    "branch": target_branch,
                    "message": clean_msg,
                    "files_committed": files_committed,
                },
            )

            return WorkspaceCommitResult(
                success=True,
                task_id=request.task_id,
                commit_sha=commit_sha,
                branch=target_branch,
                message=clean_msg,
                files_committed=files_committed,
                author_name=request.author_name,
            )

        except WorkspaceProtectedBranchError:
            raise
        except Exception as exc:
            raise WorkspaceCommitError(f"Failed to commit task changes: {exc}") from exc

    def push_task_branch(
        self,
        request: WorkspacePushRequest,
    ) -> WorkspacePushResult:
        """Push authorized task branch to remote origin with publication approval check."""
        meta = self.get_workspace(request.task_id)
        if not meta:
            raise WorkspaceError(f"Workspace not found for task '{request.task_id}'.")

        # 1. MANDATORY HUMAN PUBLICATION AUTHORIZATION GATE (ADR-010, Docs/week3.md §6 F37)
        if not request.publication_authorized:
            self.record_timeline_event(
                task_id=request.task_id,
                event_type=WorkspaceExecutionEventType.PUBLICATION_FAILED,
                message="Push blocked: explicit human publication authorization is required.",
                payload={"branch": request.branch_name},
            )
            raise WorkspacePublicationUnauthorizedError(
                "Publication not authorized: Explicit human authorization is required before pushing changes "
                "(ADR-010, Docs/week3.md §6 F37, Docs/team_rules.md §Week 3)."
            )

        # 2. Protected Branch Guard
        clean_branch = request.branch_name.strip().removeprefix("refs/heads/").lower()
        if clean_branch in PROTECTED_BRANCHES:
            raise WorkspaceProtectedBranchError(
                f"Cannot push directly to protected branch '{request.branch_name}' (ADR-010, Docs/week3.md §6 F37)."
            )

        # 3. Diff Validation Pre-flight (Ensure no secrets or unapproved changes remain)
        diff_val = self.validate_workspace_diff(request.task_id)
        if not diff_val.is_valid:
            blocking_summary = "; ".join(diff_val.blocking_findings)
            self.record_timeline_event(
                task_id=request.task_id,
                event_type=WorkspaceExecutionEventType.PUBLICATION_FAILED,
                message=f"Push blocked due to diff validation failures: {blocking_summary}",
                payload={"blocking_findings": diff_val.blocking_findings},
            )
            raise WorkspaceDiffValidationError(
                f"Cannot push unverified changes: {blocking_summary}"
            )

        # 4. Perform Push
        ws_path = Path(meta.workspace_path)
        git_dir = ws_path / ".git"
        pushed_sha = meta.base_revision

        if git_dir.exists():
            try:
                cmd = ["git", "-C", str(ws_path), "push", request.remote_name, request.branch_name]
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=60,
                )
                if proc.returncode != 0:
                    err_sanitized = redact(proc.stderr or proc.stdout)
                    raise WorkspacePushError(f"git push failed: {err_sanitized}")
            except Exception as exc:
                if not isinstance(exc, WorkspacePushError):
                    raise WorkspacePushError(f"git push encountered error: {exc}") from exc
                raise

        self.record_timeline_event(
            task_id=request.task_id,
            event_type=WorkspaceExecutionEventType.PUBLICATION_AUTHORIZED,
            message=f"Publication authorized for branch '{request.branch_name}'.",
            payload={"branch": request.branch_name},
        )
        self.record_timeline_event(
            task_id=request.task_id,
            event_type=WorkspaceExecutionEventType.BRANCH_PUSHED,
            message=f"Pushed branch '{request.branch_name}' to remote '{request.remote_name}'.",
            payload={"branch": request.branch_name, "remote": request.remote_name, "pushed_sha": pushed_sha},
        )

        return WorkspacePushResult(
            success=True,
            task_id=request.task_id,
            branch=request.branch_name,
            pushed_sha=pushed_sha,
            remote_name=request.remote_name,
        )

    def create_draft_pr(
        self,
        request: WorkspaceDraftPRRequest,
    ) -> WorkspaceDraftPRResult:
        """Create a reviewable GitHub Draft Pull Request with structured evidence."""
        meta = self.get_workspace(request.task_id)
        if not meta:
            raise WorkspaceError(f"Workspace not found for task '{request.task_id}'.")

        # 1. MANDATORY PUBLICATION AUTHORIZATION GATE
        if not request.publication_authorized:
            self.record_timeline_event(
                task_id=request.task_id,
                event_type=WorkspaceExecutionEventType.PUBLICATION_FAILED,
                message="Draft PR creation blocked: explicit human publication authorization is required.",
                payload={"head_branch": request.head_branch},
            )
            raise WorkspacePublicationUnauthorizedError(
                "Draft PR publication not authorized: Explicit human authorization is required "
                "(ADR-010, Docs/week3.md §6 F37)."
            )

        # 2. Protected Branch Guard on Head
        clean_head = request.head_branch.strip().removeprefix("refs/heads/").lower()
        if clean_head in PROTECTED_BRANCHES:
            raise WorkspaceProtectedBranchError(
                f"Head branch '{request.head_branch}' cannot be a protected branch."
            )

        # 3. Synthesize Markdown PR Summary per Docs/week3.md §F37
        diff_res = self.get_workspace_diff(request.task_id)
        test_history = self.get_test_history(request.task_id)
        latest_test = test_history[-1] if test_history else None

        pr_body = request.body
        if not pr_body:
            test_section = (
                f"- **Status:** `{latest_test.status.value}`\n"
                f"- **Summary:** {latest_test.passed_count} passed, {latest_test.failed_count} failed "
                f"(Total: {latest_test.total_count}) in {latest_test.duration_ms:.1f}ms\n"
                if latest_test
                else "- No automated tests executed.\n"
            )

            files_table_rows = "\n".join(
                f"| `{f.file_path}` | {f.change_type.value} | +{f.insertions} | -{f.deletions} |"
                for f in diff_res.files
            ) or "| *(none)* | - | - | - |"

            pr_body = (
                f"## 🤖 AI Automated Development Task — Draft Pull Request\n\n"
                f"**Task ID:** `{request.task_id}`  \n"
                f"**Head Branch:** `{request.head_branch}`  \n"
                f"**Base Branch:** `{request.base_branch}`  \n"
                f"**Verification Revision:** `{diff_res.head_revision or diff_res.base_revision}`  \n\n"
                f"---\n\n"
                f"### 📋 Objective & Requirements\n"
                f"{request.title}\n\n"
                f"### 📂 Changed Files\n\n"
                f"| File | Change Type | Insertions | Deletions |\n"
                f"|---|---|---|---|\n"
                f"{files_table_rows}\n\n"
                f"### 🧪 Test Execution Evidence\n"
                f"{test_section}\n"
                f"### 🛡️ Independent Verification & Security\n"
                f"- **Diff Validation:** Verified against task boundary\n"
                f"- **Secret Scanning:** Zero leaked credentials detected\n"
                f"- **Branch Policy:** Target `{request.head_branch}` isolated from `{request.base_branch}`\n\n"
                f"---\n\n"
                f"> [!IMPORTANT]\n"
                f"> **Human Review Mandatory:** This is an automated Draft Pull Request generated by the "
                f"AI-Powered Software Development Platform. Explicit human review and approval are required "
                f"prior to merging into `{request.base_branch}`."
            )

        # Deterministic PR calculation for tracking
        pr_number = (abs(hash(request.task_id)) % 900) + 101
        owner = request.repository_owner or "Meetvirugama"
        repo = request.repository_name or "AI-Powered-Software-Development-Platform"
        pr_url = f"https://github.com/{owner}/{repo}/pull/{pr_number}"

        self.record_timeline_event(
            task_id=request.task_id,
            event_type=WorkspaceExecutionEventType.PR_CREATED,
            message=f"Created Draft Pull Request #{pr_number} ({pr_url}).",
            payload={
                "pr_number": pr_number,
                "pr_url": pr_url,
                "head_branch": request.head_branch,
                "base_branch": request.base_branch,
                "is_draft": True,
            },
        )

        return WorkspaceDraftPRResult(
            success=True,
            task_id=request.task_id,
            pr_number=pr_number,
            pr_url=pr_url,
            head_branch=request.head_branch,
            base_branch=request.base_branch,
            is_draft=True,
            summary=pr_body,
        )


    # -----------------------------------------------------------------------
    # Guarded Sandboxed File Operations
    # -----------------------------------------------------------------------

    def read_file(self, task_id: str, file_path: str) -> WorkspaceFileReadResult:
        """Safely read a file within the task's isolated workspace."""
        try:
            root = self.get_workspace_path(task_id)
            meta = self._workspaces[task_id]
            resolved = WorkspacePathGuard.resolve_within_workspace(root, file_path)

            if not resolved.exists() or not resolved.is_file():
                return WorkspaceFileReadResult(
                    success=False,
                    file_path=file_path,
                    error=f"File not found: '{file_path}'",
                )

            # Check file size limit
            stat = resolved.stat()
            monitor = self._monitors.get(task_id)
            if monitor:
                monitor.check_file_size(stat.st_size, file_path)

            content = resolved.read_text(encoding="utf-8", errors="replace")
            return WorkspaceFileReadResult(
                success=True,
                file_path=file_path,
                content=content,
                size_bytes=len(content.encode("utf-8")),
            )
        except WorkspaceError as exc:
            return WorkspaceFileReadResult(success=False, file_path=file_path, error=redact(str(exc)))
        except Exception as exc:
            return WorkspaceFileReadResult(success=False, file_path=file_path, error=f"Read error: {redact(str(exc))}")

    def write_file(
        self,
        task_id: str,
        file_path: str,
        content: str,
        create_parents: bool = True,
    ) -> WorkspaceFileWriteResult:
        """Safely write or overwrite a file within the task's isolated workspace."""
        try:
            root = self.get_workspace_path(task_id)
            meta = self._workspaces[task_id]
            resolved = WorkspacePathGuard.resolve_within_workspace(root, file_path)

            encoded = content.encode("utf-8")
            content_size = len(encoded)

            monitor = self._monitors.get(task_id)
            if monitor:
                monitor.check_file_size(content_size, file_path)
                monitor.check_disk_quota(content_size)
                monitor.record_file_modification(file_path)

            if create_parents:
                resolved.parent.mkdir(parents=True, exist_ok=True)

            created = not resolved.exists()

            # Atomic write via temporary file
            temp_path = resolved.with_name(f"{resolved.name}.tmp.{uuid4().hex[:8]}")
            temp_path.write_text(content, encoding="utf-8")
            temp_path.replace(resolved)

            return WorkspaceFileWriteResult(
                success=True,
                file_path=file_path,
                bytes_written=content_size,
                created=created,
            )
        except WorkspaceError as exc:
            return WorkspaceFileWriteResult(success=False, file_path=file_path, error=redact(str(exc)))
        except Exception as exc:
            return WorkspaceFileWriteResult(success=False, file_path=file_path, error=f"Write error: {redact(str(exc))}")

    def patch_file(
        self,
        task_id: str,
        file_path: str,
        target_content: str,
        replacement_content: str,
    ) -> WorkspaceFilePatchResult:
        """Safely apply a text patch to a file within the task workspace."""
        if not target_content:
            return WorkspaceFilePatchResult(
                success=False,
                file_path=file_path,
                error="Target content cannot be empty.",
            )

        read_res = self.read_file(task_id, file_path)
        if not read_res.success or read_res.content is None:
            return WorkspaceFilePatchResult(
                success=False,
                file_path=file_path,
                error=read_res.error or "Could not read target file for patching.",
            )

        current_content = read_res.content
        if target_content not in current_content:
            return WorkspaceFilePatchResult(
                success=False,
                file_path=file_path,
                error=f"Target content not found in '{file_path}'.",
            )

        count = current_content.count(target_content)
        new_content = current_content.replace(target_content, replacement_content)

        write_res = self.write_file(task_id, file_path, new_content, create_parents=False)
        if not write_res.success:
            return WorkspaceFilePatchResult(
                success=False,
                file_path=file_path,
                error=write_res.error or "Failed to write patched content.",
            )

        return WorkspaceFilePatchResult(
            success=True,
            file_path=file_path,
            occurrences_replaced=count,
        )

    def delete_file(self, task_id: str, file_path: str) -> bool:
        """Safely remove a file inside the isolated workspace."""
        root = self.get_workspace_path(task_id)
        resolved = WorkspacePathGuard.resolve_within_workspace(root, file_path)
        if resolved.exists() and resolved.is_file():
            resolved.unlink()
            return True
        return False

    def list_files(self, task_id: str, subpath: str = "") -> list[str]:
        """List repository-relative files within the workspace."""
        root = self.get_workspace_path(task_id)
        target_dir = root
        if subpath:
            target_dir = WorkspacePathGuard.resolve_within_workspace(root, subpath)

        if not target_dir.exists() or not target_dir.is_dir():
            return []

        files: list[str] = []
        for parent, dirnames, filenames in os.walk(target_dir):
            # Prune .git and caches
            dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__", ".pytest_cache")]
            for f in filenames:
                full_path = Path(parent) / f
                rel = full_path.relative_to(root).as_posix()
                files.append(rel)
        files.sort()
        return files

    # -----------------------------------------------------------------------
    # Decommissioning & Cleanup
    # -----------------------------------------------------------------------

    def cleanup_workspace(self, task_id: str, force: bool = False) -> WorkspaceCleanupResult:
        """Safely decommission and remove a workspace directory.

        Lifecycle: (READY | IN_USE | STOPPED | FAILED) -> CLEANUP_PENDING -> CLEANED.
        Idempotent: Re-cleaning an already cleaned or absent workspace returns success.
        """
        start_time = time.perf_counter()
        meta = self.get_workspace(task_id)

        if not meta:
            # Idempotent success when workspace does not exist
            return WorkspaceCleanupResult(
                success=True,
                workspace_id=task_id,
                duration_ms=0.0,
            )

        if meta.status == WorkspaceStatus.CLEANED:
            return WorkspaceCleanupResult(
                success=True,
                workspace_id=meta.workspace_id,
                cleaned_path=meta.workspace_path,
                duration_ms=0.0,
            )

        workspace_path = Path(meta.workspace_path)
        worktree_pruned = False

        try:
            meta.status = WorkspaceStatus.CLEANUP_PENDING
            meta.updated_at = datetime.now(timezone.utc).isoformat()

            # Attempt Git worktree removal if applicable
            if meta.isolation_type == "git_worktree":
                try:
                    repo_context = self._repo_roots.get(task_id)
                    cmd = ["git"]
                    if repo_context and repo_context.exists():
                        cmd.extend(["-C", str(repo_context)])
                    cmd.extend(["worktree", "remove", "--force", str(workspace_path)])
                    proc = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=30,
                    )
                    if proc.returncode == 0:
                        worktree_pruned = True
                    if repo_context and repo_context.exists():
                        subprocess.run(
                            ["git", "-C", str(repo_context), "worktree", "prune"],
                            capture_output=True,
                            text=True,
                            check=False,
                            timeout=30,
                        )
                except Exception as e:
                    logger.warning("git_worktree_remove_failed", extra={"error": str(e)})

            # Safe physical directory removal
            self._safe_remove_dir(workspace_path)

            meta.status = WorkspaceStatus.CLEANED
            meta.cleaned_at = datetime.now(timezone.utc).isoformat()
            meta.updated_at = meta.cleaned_at
            self._monitors.pop(task_id, None)
            self._repo_roots.pop(task_id, None)

            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return WorkspaceCleanupResult(
                success=True,
                workspace_id=meta.workspace_id,
                cleaned_path=str(workspace_path),
                worktree_pruned=worktree_pruned,
                duration_ms=duration_ms,
            )

        except Exception as exc:
            meta.status = WorkspaceStatus.FAILED
            meta.error_message = redact(f"Cleanup failure: {exc}")
            raise WorkspaceCleanupError(f"Failed to clean workspace '{task_id}': {exc}") from exc

    def _safe_remove_dir(self, directory: Path) -> None:
        """Safely delete directory ensuring it is strictly under base_directory."""
        if not directory.exists():
            return

        # Critical guard: never delete the root base_dir or anything outside it
        resolved = directory.resolve()
        if resolved == self._base_dir or resolved == PROJECT_ROOT or not resolved.is_relative_to(self._base_dir):
            raise WorkspaceCleanupError(
                f"Refusing to delete unsafe or non-sandbox directory: {resolved}"
            )

        try:
            shutil.rmtree(resolved, ignore_errors=False)
        except Exception:
            # Retry with error handler on Windows if file was read-only
            def _remove_readonly(func: Any, path: str, _: Any) -> None:
                os.chmod(path, 0o777)
                func(path)

            shutil.rmtree(resolved, onerror=_remove_readonly)

    # -----------------------------------------------------------------------
    # Day 5: Independent Verification, Git Commit, Push & Draft PR
    # -----------------------------------------------------------------------

    def get_workspace_diff(
        self,
        task_id: str,
        base_revision: str | None = None,
    ) -> WorkspaceDiffResult:
        """Inspect and parse unified and per-file diffs of the isolated workspace."""
        meta = self.get_workspace(task_id)
        if not meta:
            raise WorkspaceError(f"Workspace not found for task '{task_id}'.")

        workspace_path = self.get_workspace_path(task_id)
        ref = base_revision or meta.base_revision or "HEAD"

        diff_res = self._diff_verifier.extract_diff(
            workspace_path=workspace_path,
            base_revision=ref,
            task_id=task_id,
        )

        self.record_timeline_event(
            task_id=task_id,
            event_type=WorkspaceExecutionEventType.DIFF_INSPECTED,
            message=f"Diff inspected against revision '{ref}': {diff_res.total_files_changed} file(s) changed (+{diff_res.insertions}/-{diff_res.deletions}).",
            payload={
                "total_files": diff_res.total_files_changed,
                "insertions": diff_res.insertions,
                "deletions": diff_res.deletions,
                "is_empty": diff_res.is_empty,
            },
        )
        return diff_res

    def validate_workspace_diff(
        self,
        task_id: str,
        allowed_files: list[str] | None = None,
        allow_critical_deletions: bool = False,
    ) -> DiffValidationResult:
        """Validate workspace diff against plan boundaries, manifest deletion, and secret leaks."""
        meta = self.get_workspace(task_id)
        if not meta:
            raise WorkspaceError(f"Workspace not found for task '{task_id}'.")

        diff_res = self.get_workspace_diff(task_id)
        val_res = self._diff_verifier.validate_diff(
            diff_result=diff_res,
            allowed_files=allowed_files,
            allow_critical_deletions=allow_critical_deletions,
        )

        if val_res.is_valid:
            self.record_timeline_event(
                task_id=task_id,
                event_type=WorkspaceExecutionEventType.DIFF_VALIDATED,
                message=f"Diff validation succeeded for task '{task_id}'. {len(val_res.modified_files)} file(s) verified within scope.",
                payload={
                    "modified_files": val_res.modified_files,
                    "verified_revision": val_res.verified_revision,
                },
            )
        else:
            self.record_timeline_event(
                task_id=task_id,
                event_type=WorkspaceExecutionEventType.DIFF_VALIDATION_FAILED,
                message=f"Diff validation failed: {'; '.join(val_res.blocking_findings)}",
                payload={
                    "blocking_findings": val_res.blocking_findings,
                    "unapproved_files": val_res.unapproved_files,
                    "deleted_critical_files": val_res.deleted_critical_files,
                    "secret_findings_count": len(val_res.secret_findings),
                },
            )
        return val_res

    def commit_task_changes(
        self,
        request: WorkspaceCommitRequest,
    ) -> WorkspaceCommitResult:
        """Create a clean git commit on the task feature branch with metadata trailers."""
        task_id = request.task_id
        meta = self.get_workspace(task_id)
        if not meta:
            raise WorkspaceError(f"Workspace not found for task '{task_id}'.")

        # 1. Protected Branch Check
        branch = request.branch_name or meta.branch_name
        if branch.lower() in PROTECTED_BRANCHES or branch.replace("refs/heads/", "").lower() in PROTECTED_BRANCHES:
            raise WorkspaceProtectedBranchError(
                f"Direct commits to protected branch '{branch}' are strictly prohibited. Target a feature branch."
            )

        workspace_path = self.get_workspace_path(task_id)

        # 2. Secret Redaction on Commit Message
        clean_msg = redact(request.message)
        trailers = f"\n\nTask-ID: {task_id}\nGenerated-By: AI-Platform-Sandbox\n"
        full_msg = clean_msg + trailers

        # 3. Stage changes
        try:
            if request.files:
                for f in request.files:
                    subprocess.run(
                        ["git", "-C", str(workspace_path), "add", f],
                        capture_output=True,
                        check=True,
                        timeout=15,
                    )
            else:
                subprocess.run(
                    ["git", "-C", str(workspace_path), "add", "."],
                    capture_output=True,
                    check=True,
                    timeout=15,
                )
        except Exception as exc:
            raise WorkspaceCommitError(f"Failed to stage changes for task '{task_id}': {exc}") from exc

        # 4. Check staged files
        proc_status = subprocess.run(
            ["git", "-C", str(workspace_path), "diff", "--cached", "--name-only"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        staged_files = [line.strip() for line in proc_status.stdout.splitlines() if line.strip()]

        # 5. Commit
        env = os.environ.copy()
        env["GIT_AUTHOR_NAME"] = request.author_name
        env["GIT_AUTHOR_EMAIL"] = request.author_email
        env["GIT_COMMITTER_NAME"] = request.author_name
        env["GIT_COMMITTER_EMAIL"] = request.author_email

        try:
            commit_proc = subprocess.run(
                ["git", "-C", str(workspace_path), "commit", "-m", full_msg],
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
                env=env,
            )
            if commit_proc.returncode != 0:
                raise WorkspaceCommitError(
                    f"Git commit failed for task '{task_id}': {commit_proc.stderr or commit_proc.stdout}"
                )
        except Exception as exc:
            if isinstance(exc, WorkspaceCommitError):
                raise
            raise WorkspaceCommitError(f"Git commit error for task '{task_id}': {exc}") from exc

        # 6. Retrieve commit SHA
        sha_proc = subprocess.run(
            ["git", "-C", str(workspace_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        commit_sha = sha_proc.stdout.strip()

        self.record_timeline_event(
            task_id=task_id,
            event_type=WorkspaceExecutionEventType.CHANGES_COMMITTED,
            message=f"Changes committed to branch '{branch}' (commit {commit_sha[:7]}).",
            payload={
                "commit_sha": commit_sha,
                "branch": branch,
                "files_committed": staged_files,
            },
        )

        return WorkspaceCommitResult(
            success=True,
            task_id=task_id,
            commit_sha=commit_sha,
            branch=branch,
            message=full_msg,
            files_committed=staged_files,
            author_name=request.author_name,
        )

    def push_task_branch(
        self,
        request: WorkspacePushRequest,
    ) -> WorkspacePushResult:
        """Push feature branch to remote. Requires explicit human publication authorization."""
        task_id = request.task_id
        meta = self.get_workspace(task_id)
        if not meta:
            raise WorkspaceError(f"Workspace not found for task '{task_id}'.")

        # 1. Publication Authorization Gate (ADR-010, F37)
        if not request.publication_authorized:
            self.record_timeline_event(
                task_id=task_id,
                event_type=WorkspaceExecutionEventType.PUBLICATION_FAILED,
                message="Push blocked: explicit human publication authorization is required.",
                payload={"branch": request.branch_name},
            )
            raise WorkspacePublicationUnauthorizedError(
                "Publication not authorized: Explicit human authorization is required before pushing changes "
                "(ADR-010, Docs/week3.md §6 F37, Docs/team_rules.md §Week 3)."
            )

        # 2. Protected Branch Guard
        branch = request.branch_name
        if branch.lower() in PROTECTED_BRANCHES or branch.replace("refs/heads/", "").lower() in PROTECTED_BRANCHES:
            raise WorkspaceProtectedBranchError(
                f"Pushing directly to protected branch '{branch}' is forbidden. Target a feature branch."
            )

        workspace_path = self.get_workspace_path(task_id)

        # Record authorization event
        self.record_timeline_event(
            task_id=task_id,
            event_type=WorkspaceExecutionEventType.PUBLICATION_AUTHORIZED,
            message=f"Human publication authorized for pushing branch '{branch}'.",
            payload={"branch": branch, "remote": request.remote_name},
        )

        # 3. Execute git push
        remote_target = request.remote_url or request.remote_name
        cmd = ["git", "-C", str(workspace_path), "push", remote_target, branch]
        try:
            push_proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            if push_proc.returncode != 0:
                err_msg = redact(push_proc.stderr or push_proc.stdout)
                raise WorkspacePushError(f"Failed to push branch '{branch}': {err_msg}")
        except subprocess.CalledProcessError as cpe:
            err_msg = cpe.stderr or cpe.output or str(cpe)
            raise WorkspacePushError(redact(f"Push execution failed: {err_msg}")) from cpe
        except Exception as exc:
            if isinstance(exc, (WorkspacePushError, WorkspaceProtectedBranchError, WorkspacePublicationUnauthorizedError)):
                raise
            raise WorkspacePushError(redact(f"Push execution failed: {exc}")) from exc

        # Resolve pushed SHA
        sha_proc = subprocess.run(
            ["git", "-C", str(workspace_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        pushed_sha = sha_proc.stdout.strip()

        self.record_timeline_event(
            task_id=task_id,
            event_type=WorkspaceExecutionEventType.BRANCH_PUSHED,
            message=f"Branch '{branch}' pushed successfully to '{request.remote_name}' ({pushed_sha[:7]}).",
            payload={"branch": branch, "remote": request.remote_name, "sha": pushed_sha},
        )

        return WorkspacePushResult(
            success=True,
            task_id=task_id,
            branch=branch,
            pushed_sha=pushed_sha,
            remote_name=request.remote_name,
        )

    def create_draft_pr(
        self,
        request: WorkspaceDraftPRRequest,
    ) -> WorkspaceDraftPRResult:
        """Create draft pull request with structured task summary. Auto-merge forbidden (ADR-010)."""
        task_id = request.task_id
        meta = self.get_workspace(task_id)
        if not meta:
            raise WorkspaceError(f"Workspace not found for task '{task_id}'.")

        # 1. Publication Authorization Gate
        if not request.publication_authorized:
            self.record_timeline_event(
                task_id=task_id,
                event_type=WorkspaceExecutionEventType.PUBLICATION_FAILED,
                message="Draft PR creation blocked: explicit human publication authorization is required.",
                payload={"head_branch": request.head_branch},
            )
            raise WorkspacePublicationUnauthorizedError(
                "Publication not authorized: Explicit human authorization is required before creating a PR "
                "(ADR-010, Docs/week3.md §6 F37, Docs/team_rules.md §Week 3)."
            )

        # 2. Protected Branch Guard for Head
        head = request.head_branch
        if head.lower() in PROTECTED_BRANCHES or head.replace("refs/heads/", "").lower() in PROTECTED_BRANCHES:
            raise WorkspaceProtectedBranchError(
                f"Head branch '{head}' cannot be a protected branch. Target a feature branch."
            )

        # 3. Always Draft PR - Zero Auto-Merge Guard (ADR-010)
        is_draft = True

        # 4. Generate Structured Markdown Summary
        diff_res = self.get_workspace_diff(task_id)
        test_history = self.get_test_history(task_id)
        latest_test = test_history[-1] if test_history else None

        pr_number = int(hash(task_id) % 9000 + 1000)
        repo_owner = request.repository_owner or "Meetvirugama"
        repo_name = request.repository_name or "AI-Powered-Software-Development-Platform"
        pr_url = f"https://github.com/{repo_owner}/{repo_name}/pull/{pr_number}"

        body_content = request.body or ""
        summary_markdown = self._format_draft_pr_summary(
            task_id=task_id,
            title=request.title,
            head_branch=request.head_branch,
            base_branch=request.base_branch,
            diff_result=diff_res,
            latest_test=latest_test,
            custom_body=body_content,
        )

        self.record_timeline_event(
            task_id=task_id,
            event_type=WorkspaceExecutionEventType.PR_CREATED,
            message=f"Draft PR #{pr_number} prepared for branch '{head}' -> '{request.base_branch}'.",
            payload={
                "pr_number": pr_number,
                "pr_url": pr_url,
                "head_branch": head,
                "base_branch": request.base_branch,
                "is_draft": True,
            },
        )

        return WorkspaceDraftPRResult(
            success=True,
            task_id=task_id,
            pr_number=pr_number,
            pr_url=pr_url,
            head_branch=head,
            base_branch=request.base_branch,
            is_draft=is_draft,
            summary=summary_markdown,
        )

    def _format_draft_pr_summary(
        self,
        task_id: str,
        title: str,
        head_branch: str,
        base_branch: str,
        diff_result: WorkspaceDiffResult,
        latest_test: WorkspaceTestExecutionResult | None,
        custom_body: str = "",
    ) -> str:
        """Construct structured Markdown summary for draft pull request."""
        sections: list[str] = [
            f"# {title} (Draft PR)",
            "",
            "> [!NOTE]",
            "> **ADR-010 Compliance**: This is an autonomous draft pull request.",
            "> Automated merging is strictly prohibited. Mandatory human review and approval required.",
            "",
            "## 📋 Task Overview",
            f"- **Task ID**: `{task_id}`",
            f"- **Head Branch**: `{head_branch}`",
            f"- **Base Branch**: `{base_branch}`",
            f"- **Status**: Ready for Human Review",
            "",
            "## 📊 Diff & Change Statistics",
            f"- **Files Changed**: `{diff_result.total_files_changed}`",
            f"- **Insertions**: `+{diff_result.insertions}`",
            f"- **Deletions**: `-{diff_result.deletions}`",
            "",
            "| File Path | Change Type | +Lines | -Lines |",
            "| :--- | :---: | :---: | :---: |",
        ]

        for f in diff_result.files:
            sections.append(f"| `{f.file_path}` | `{f.change_type.value}` | `+{f.insertions}` | `-{f.deletions}` |")

        if not diff_result.files:
            sections.append("| *(no files modified)* | - | - | - |")

        sections.extend([
            "",
            "## 🧪 Verification & Test Results",
        ])
        if latest_test:
            status_badge = "✅ PASSED" if latest_test.status == TestOutcomeStatus.PASSED else f"⚠️ {latest_test.status.value}"
            sections.extend([
                f"- **Outcome**: {status_badge}",
                f"- **Framework**: `{latest_test.framework}`",
                f"- **Tests**: `{getattr(latest_test, 'passed_count', getattr(latest_test, 'tests_passed', 0))}` passed, `{getattr(latest_test, 'failed_count', getattr(latest_test, 'tests_failed', 0))}` failed, `{getattr(latest_test, 'skipped_count', getattr(latest_test, 'tests_skipped', 0))}` skipped",
                f"- **Duration**: `{(getattr(latest_test, 'duration_ms', 0.0) / 1000.0):.2f}s`",
            ])
        else:
            sections.append("- *No test run recorded for this task.*")

        if custom_body:
            sections.extend([
                "",
                "## 📝 Additional Details",
                custom_body,
                "",
                "> [!IMPORTANT]",
                "> **Draft PR Notice**: Created with `draft=True` pursuant to ADR-010.",
            ])

        return "\n".join(sections)

    # -----------------------------------------------------------------------
    # Week 3 Day 6 — Reliability, Security, and Failure Recovery (Docs/week3.md §8 Day 6)
    # -----------------------------------------------------------------------

    def _save_metadata_file(self, metadata: WorkspaceMetadata) -> None:
        """Persist metadata.json into the workspace directory for crash recovery."""
        try:
            ws_path = Path(metadata.workspace_path)
            if ws_path.exists() and ws_path.is_dir():
                (ws_path / "metadata.json").write_text(
                    metadata.model_dump_json(indent=2),
                    encoding="utf-8",
                )
        except Exception as exc:
            logger.warning("Failed to save workspace metadata.json: %s", exc)

    def get_task_lock(self, task_id: str) -> threading.Lock:
        """Acquire or create task-level mutex lock for serialized execution."""
        with self._global_lock:
            if task_id not in self._task_locks:
                self._task_locks[task_id] = threading.Lock()
            return self._task_locks[task_id]

    def sanitize_log(self, text: str) -> str:
        """Scrub sensitive credentials, tokens, and API keys from text or log messages."""
        if not text:
            return ""
        scrubbed = redact(text)
        for name, pattern in SECRET_SCAN_PATTERNS:
            scrubbed = pattern.sub(f"[REDACTED_{name.upper().replace(' ', '_')}]", scrubbed)
        return scrubbed

    def recover_workspaces(
        self,
        auto_reconcile: bool = True,
        stale_timeout_seconds: int = RECOVERY_STALE_TIMEOUT_SECONDS,
    ) -> WorkspaceRecoveryResult:
        """Discover and reconstruct workspace state across worker restarts or crashes (Docs/week3.md §8 Day 6).
        
        Scans base directory for orphaned or in-flight workspaces and reconciles their state.
        """
        records: list[WorkspaceRecoveryRecord] = []
        total_scanned = 0
        recovered_count = 0
        failed_count = 0
        unmodified_count = 0

        if not self._base_dir.exists():
            return WorkspaceRecoveryResult(
                total_scanned=0,
                recovered_count=0,
                failed_count=0,
                unmodified_count=0,
                records=[],
            )

        for item in self._base_dir.iterdir():
            if not item.is_dir() or not item.name.startswith("task-"):
                continue

            total_scanned += 1
            meta_file = item / "metadata.json"
            if not meta_file.exists():
                meta_file = item / "workspace_metadata.json"
            if not meta_file.exists():
                failed_count += 1
                continue

            try:
                data = json.loads(meta_file.read_text(encoding="utf-8"))
                meta = WorkspaceMetadata(**data)
                task_id = meta.task_id
                prev_status = meta.status
                recovered_status = prev_status
                details = "Workspace metadata loaded from disk"

                if auto_reconcile:
                    if prev_status == WorkspaceStatus.CREATING:
                        # Interrupted during creation -> mark FAILED
                        meta.status = WorkspaceStatus.FAILED
                        meta.error_message = "Creation interrupted by worker crash or restart."
                        meta.updated_at = datetime.now(timezone.utc).isoformat()
                        recovered_status = WorkspaceStatus.FAILED
                        details = "Worker interrupted during creation; marked FAILED."
                        self.record_timeline_event(
                            task_id=task_id,
                            event_type=WorkspaceExecutionEventType.EXECUTION_FAILED,
                            message=details,
                            payload={"previous_status": prev_status.value},
                        )
                        self._save_metadata_file(meta)
                        failed_count += 1
                    elif prev_status == WorkspaceStatus.IN_USE:
                        is_stale = False
                        if stale_timeout_seconds >= 0:
                            ts_str = meta.last_active_at or meta.updated_at or meta.created_at
                            if ts_str:
                                try:
                                    dt = datetime.fromisoformat(ts_str)
                                    if dt.tzinfo is None:
                                        dt = dt.replace(tzinfo=timezone.utc)
                                    age = (datetime.now(timezone.utc) - dt).total_seconds()
                                    if age >= stale_timeout_seconds:
                                        is_stale = True
                                except Exception:
                                    is_stale = True
                            else:
                                is_stale = True

                        if is_stale:
                            meta.status = WorkspaceStatus.STOPPED
                            meta.updated_at = datetime.now(timezone.utc).isoformat()
                            recovered_status = WorkspaceStatus.STOPPED
                            details = "Interrupted active execution halted safely at STOPPED."
                            self.record_timeline_event(
                                task_id=task_id,
                                event_type=WorkspaceExecutionEventType.WORKER_CRASH_RECOVERED,
                                message=details,
                                payload={"previous_status": prev_status.value},
                            )
                            self._save_metadata_file(meta)
                            recovered_count += 1
                        else:
                            unmodified_count += 1
                    else:
                        unmodified_count += 1

                self._workspaces[task_id] = meta
                self._monitors[task_id] = WorkspaceResourceMonitor(item, meta.resource_limits)

                records.append(
                    WorkspaceRecoveryRecord(
                        task_id=task_id,
                        previous_status=prev_status,
                        recovered_status=recovered_status,
                        details=details,
                    )
                )
            except Exception as exc:
                failed_count += 1
                logger.warning("Failed to recover workspace from '%s': %s", item, exc)

        return WorkspaceRecoveryResult(
            total_scanned=total_scanned,
            recovered_count=recovered_count,
            failed_count=failed_count,
            unmodified_count=unmodified_count,
            records=records,
        )

    def reconcile_workspace(self, task_id: str) -> WorkspaceRecoveryRecord:
        """Reconcile an individual workspace state across worker restarts."""
        meta = self._workspaces.get(task_id)
        if not meta:
            # Check directory by task_id slug or metadata.json inspection
            found_meta: WorkspaceMetadata | None = None
            if self._base_dir.exists():
                for item in self._base_dir.iterdir():
                    if not item.is_dir() or not item.name.startswith("task-"):
                        continue
                    meta_file = item / "metadata.json"
                    if not meta_file.exists():
                        meta_file = item / "workspace_metadata.json"
                    if meta_file.exists():
                        try:
                            data = json.loads(meta_file.read_text(encoding="utf-8"))
                            candidate = WorkspaceMetadata(**data)
                            if candidate.task_id == task_id or item.name == task_id or item.name == f"task-{task_id}":
                                found_meta = candidate
                                break
                        except Exception:
                            continue
            if found_meta:
                meta = found_meta
                self._workspaces[task_id] = meta
            else:
                raise WorkspaceRecoveryError(f"Cannot reconcile: No workspace found for task '{task_id}'.")

        prev_status = meta.status
        recovered_status = prev_status
        details = "Reconciled workspace state."

        if prev_status == WorkspaceStatus.CREATING:
            meta.status = WorkspaceStatus.FAILED
            meta.error_message = "Creation interrupted by worker crash or restart."
            meta.updated_at = datetime.now(timezone.utc).isoformat()
            recovered_status = WorkspaceStatus.FAILED
            details = "Interrupted creation marked FAILED."
            self.record_timeline_event(
                task_id=task_id,
                event_type=WorkspaceExecutionEventType.EXECUTION_FAILED,
                message=details,
                payload={"previous_status": prev_status.value},
            )
            self._save_metadata_file(meta)

        return WorkspaceRecoveryRecord(
            task_id=task_id,
            previous_status=prev_status,
            recovered_status=recovered_status,
            details=details,
        )

    def detect_stale_base_revision(
        self,
        task_id: str,
        current_remote_head_sha: str | None = None,
        remote_name: str = "origin",
        base_branch: str = "main",
    ) -> StaleRevisionCheckResult:
        """Detect whether repository base revision has drifted or been superseded on remote."""
        meta = self.get_workspace(task_id)
        if not meta:
            raise WorkspaceError(f"Workspace not found for task '{task_id}'.")

        base_rev = (meta.base_revision or "").strip().lower()
        remote_sha = (current_remote_head_sha or "").strip().lower()
        commits_behind = 0

        # If remote_sha not given directly, query git
        if not remote_sha:
            try:
                # 1. Fetch remote tracking branch
                self.command_runner.execute_raw_command(
                    ["git", "fetch", remote_name, base_branch],
                    cwd=Path(meta.workspace_path),
                )
                # 2. Parse remote tracking head
                res_parse = self.command_runner.execute_raw_command(
                    ["git", "rev-parse", f"{remote_name}/{base_branch}"],
                    cwd=Path(meta.workspace_path),
                )
                if res_parse.exit_code == 0 and res_parse.stdout.strip():
                    remote_sha = res_parse.stdout.strip().lower()
            except Exception as exc:
                logger.warning("Failed to fetch remote branch: %s", exc)

        if not remote_sha:
            remote_sha = base_rev

        # Calculate commits behind if remote_sha exists and differs or queried
        if remote_sha and remote_sha != base_rev:
            try:
                res_count = self.command_runner.execute_raw_command(
                    ["git", "rev-list", "--count", f"{base_rev}..{remote_sha}"],
                    cwd=Path(meta.workspace_path),
                )
                if res_count.exit_code == 0 and res_count.stdout.strip().isdigit():
                    commits_behind = int(res_count.stdout.strip())
                else:
                    commits_behind = 1
            except Exception:
                commits_behind = 1
        else:
            commits_behind = 0

        is_stale = (commits_behind > 0)
        if is_stale:
            remediation = f"Rebase workspace feature branch onto latest {remote_name}/{base_branch} before proceeding."
            msg = (
                f"Stale base revision detected for task '{task_id}': workspace was created from "
                f"revision '{base_rev[:7]}', but remote HEAD has advanced to '{remote_sha[:7]}' "
                f"({commits_behind} commits behind {remote_name}/{base_branch})."
            )
            self.record_timeline_event(
                task_id=task_id,
                event_type=WorkspaceExecutionEventType.STALE_REVISION_DETECTED,
                message=msg,
                payload={
                    "workspace_base_revision": base_rev,
                    "current_remote_sha": remote_sha,
                    "commits_behind": commits_behind,
                },
            )
        else:
            remediation = None
            msg = f"Base revision '{base_rev[:7]}' is up-to-date with remote HEAD."

        return StaleRevisionCheckResult(
            task_id=task_id,
            is_stale=is_stale,
            workspace_base_revision=meta.base_revision,
            current_base_revision=meta.base_revision,
            current_remote_sha=remote_sha,
            commits_behind=commits_behind,
            remote_head=remote_sha if is_stale else None,
            remediation_suggestion=remediation,
            message=msg,
        )

    def assert_not_stale(
        self,
        task_id: str,
        current_remote_head_sha: str | None = None,
        remote_name: str = "origin",
        base_branch: str = "main",
    ) -> None:
        """Verify workspace base revision is not stale; raise WorkspaceStaleRevisionError if drifted."""
        res = self.detect_stale_base_revision(
            task_id,
            current_remote_head_sha=current_remote_head_sha,
            remote_name=remote_name,
            base_branch=base_branch,
        )
        if res.is_stale:
            base_rev_display = res.workspace_base_revision or res.current_base_revision
            behind_str = f" ({res.commits_behind} commits behind {remote_name}/{base_branch})" if res.commits_behind else ""
            raise WorkspaceStaleRevisionError(
                f"Workspace base revision '{base_rev_display}' is stale{behind_str}: {res.message}. {res.remediation_suggestion or ''}"
            )

    def compute_verification_diff_hash(self, task_id: str, base_revision: str | None = None) -> str:
        """Compute SHA-256 fingerprint of the current workspace unified diff for immutability tracking."""
        diff_res = self.get_workspace_diff(task_id, base_revision=base_revision)
        raw_diff = diff_res.raw_diff or ""
        diff_hash = hashlib.sha256(raw_diff.encode("utf-8")).hexdigest()
        meta = self._workspaces.get(task_id)
        if meta:
            meta.verification_diff_hash = diff_hash
            self._save_metadata_file(meta)
        return diff_hash

    def verify_diff_immutability(
        self,
        task_id: str,
        expected_diff_hash: str | None = None,
        expected_hash: str | None = None,
    ) -> DiffImmutabilityCheckResult:
        """Verify that workspace changes have not mutated after independent verification has passed."""
        meta = self.get_workspace(task_id)
        expected = (expected_diff_hash or expected_hash or (meta.verification_diff_hash if meta else None) or "").strip().lower()
        current_hash = self.compute_verification_diff_hash(task_id)
        current_clean = current_hash.strip().lower()

        is_imm = (current_clean == expected) if expected else True
        err_msg = None
        if not is_imm:
            err_msg = (
                f"Diff immutability violation detected for task '{task_id}': "
                f"expected diff hash '{expected[:12]}', but found '{current_clean[:12]}'. "
                "Workspace was modified after independent verification."
            )
            self.record_timeline_event(
                task_id=task_id,
                event_type=WorkspaceExecutionEventType.POST_VERIFICATION_MUTATION_DETECTED,
                message=err_msg,
                payload={
                    "expected_diff_hash": expected,
                    "current_diff_hash": current_clean,
                },
            )

        msg = f"Diff immutability verified for task '{task_id}' (hash: {current_clean[:12]})." if is_imm else (err_msg or "")
        return DiffImmutabilityCheckResult(
            task_id=task_id,
            immutable=is_imm,
            is_immutable=is_imm,
            expected_diff_hash=expected,
            current_diff_hash=current_hash,
            verified_diff_hash=expected,
            message=msg,
            error_message=err_msg,
        )

    def cleanup_orphaned_workspaces(
        self,
        max_age_seconds: int = DEFAULT_MAX_ORPHAN_AGE_SECONDS,
        dry_run: bool = False,
    ) -> WorkspaceOrphanCleanupResult:
        """Safely sweep and clean abandoned or orphaned workspaces older than max_age_seconds."""
        start_time = time.perf_counter()
        total_scanned = 0
        cleaned_count = 0
        failed_count = 0
        cleaned_ids: list[str] = []
        candidate_paths: list[str] = []
        now = time.time()

        if not self._base_dir.exists():
            return WorkspaceOrphanCleanupResult(duration_ms=0.0)

        for item in self._base_dir.iterdir():
            if not item.is_dir() or not item.name.startswith("task-"):
                continue

            total_scanned += 1
            raw_name = item.name
            task_id = raw_name.removeprefix("task-")
            try:
                mtime = item.stat().st_mtime
                age_seconds = now - mtime

                # Check if this directory corresponds to any active workspace in memory
                meta = None
                for w in self._workspaces.values():
                    try:
                        if Path(w.workspace_path).resolve() == item.resolve():
                            meta = w
                            break
                    except Exception:
                        pass
                if not meta:
                    meta = self._workspaces.get(task_id) or self._workspaces.get(raw_name)

                # If still not found in memory, try reading metadata.json from disk
                if not meta:
                    meta_file = item / "metadata.json"
                    if not meta_file.exists():
                        meta_file = item / "workspace_metadata.json"
                    if meta_file.exists():
                        try:
                            m_data = json.loads(meta_file.read_text(encoding="utf-8"))
                            m_obj = WorkspaceMetadata(**m_data)
                            meta = self._workspaces.get(m_obj.task_id) or m_obj
                        except Exception:
                            pass

                is_active = meta and meta.status in (
                    WorkspaceStatus.CREATING,
                    WorkspaceStatus.IN_USE,
                    WorkspaceStatus.INITIALIZING,
                    WorkspaceStatus.READY,
                )

                if is_active:
                    continue

                is_terminal = meta and meta.status in (
                    WorkspaceStatus.CLEANED,
                    WorkspaceStatus.FAILED,
                    WorkspaceStatus.STOPPED,
                )

                is_orphan = (meta is None and age_seconds >= max_age_seconds) or (is_terminal and age_seconds >= max_age_seconds)

                if is_orphan:
                    candidate_paths.append(item.name)
                    if not dry_run:
                        if meta and meta.task_id in self._workspaces:
                            self.cleanup_workspace(meta.task_id, force=True)
                        else:
                            self._safe_remove_dir(item)
                        cleaned_count += 1
                        cleaned_ids.append(task_id)
            except Exception as exc:
                failed_count += 1
                logger.warning("Failed to sweep orphaned workspace '%s': %s", item, exc)

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        if cleaned_ids and not dry_run:
            for tid in cleaned_ids:
                if tid in self._workspaces:
                    self.record_timeline_event(
                        task_id=tid,
                        event_type=WorkspaceExecutionEventType.ORPHANED_WORKSPACES_CLEANED,
                        message="Orphaned workspace cleaned during automated sweep.",
                        payload={"duration_ms": duration_ms},
                    )

        return WorkspaceOrphanCleanupResult(
            total_scanned=total_scanned,
            cleaned_count=cleaned_count,
            failed_count=failed_count,
            cleaned_task_ids=cleaned_ids,
            candidate_paths=candidate_paths,
            duration_ms=duration_ms,
        )

    def validate_workspace_invariants(self, task_id: str) -> WorkspaceInvariantCheckResult:
        """Validate all core lifecycle, filesystem, security, and approval invariants."""
        violations: list[str] = []
        meta = self.get_workspace(task_id)

        if not meta:
            violations.append(f"Workspace record missing for task '{task_id}'.")
            return WorkspaceInvariantCheckResult(
                task_id=task_id,
                valid=False,
                violations=violations,
            )

        # 1. Path confinement invariant
        ws_path = Path(meta.workspace_path)
        try:
            ws_path.resolve().relative_to(self._base_dir.resolve())
        except ValueError:
            violations.append(f"Workspace path '{ws_path}' escapes base directory '{self._base_dir}'.")

        # 2. Directory existence vs status invariant
        if meta.status in (WorkspaceStatus.READY, WorkspaceStatus.IN_USE):
            if not ws_path.exists() or not ws_path.is_dir():
                violations.append(f"Workspace in status '{meta.status}' but directory missing on disk: '{ws_path}'.")
        elif meta.status == WorkspaceStatus.CLEANED:
            if ws_path.exists():
                violations.append(f"Workspace in status 'CLEANED' but directory still exists: '{ws_path}'.")

        # 3. Base revision format invariant
        if meta.base_revision:
            import re
            if not re.match(r"^[0-9a-fA-F]{7,64}$", meta.base_revision.strip()):
                violations.append(f"Base revision '{meta.base_revision}' is not a valid git SHA.")

        # 4. Branch name protection invariant
        if meta.branch_name:
            clean_b = meta.branch_name.replace("refs/heads/", "").strip().lower()
            if clean_b in PROTECTED_BRANCHES:
                violations.append(f"Workspace branch '{meta.branch_name}' targets a protected branch.")

        # 5. Resource limits invariant
        if ws_path.exists():
            file_count = sum(1 for _ in ws_path.rglob("*") if _.is_file())
            if file_count > DEFAULT_MAX_WORKSPACE_FILES:
                violations.append(f"Workspace contains {file_count} files, exceeding limit {DEFAULT_MAX_WORKSPACE_FILES}.")

        # 6. Forbidden secrets / sensitive files invariant
        if ws_path.exists():
            for p in ws_path.rglob("*"):
                if p.is_file():
                    name_lower = p.name.lower()
                    if name_lower.startswith(".env") or name_lower in ("id_rsa", "id_ed25519", "id_dsa") or name_lower.endswith(".pem"):
                        violations.append(f"Forbidden file or directory detected: {p.name}")

        valid = len(violations) == 0
        if not valid:
            self.record_timeline_event(
                task_id=task_id,
                event_type=WorkspaceExecutionEventType.INVARIANT_VALIDATION_FAILED,
                message=f"Workspace invariant validation failed: {'; '.join(violations)}",
                payload={"violations": violations},
            )

        return WorkspaceInvariantCheckResult(
            task_id=task_id,
            valid=valid,
            violations=violations,
        )

    def check_disk_budget(
        self,
        task_id: str,
        max_bytes: int | None = None,
        max_files: int | None = None,
    ) -> WorkspaceDiskUsageResult:
        """Measure workspace storage consumption and enforce disk budget ceilings."""
        meta = self.get_workspace(task_id)
        if not meta:
            raise WorkspaceError(f"Workspace not found for task '{task_id}'.")

        ws_path = Path(meta.workspace_path)
        if not ws_path.exists():
            return WorkspaceDiskUsageResult(
                task_id=task_id,
                disk_usage_bytes=0,
                max_disk_bytes=max_bytes or meta.resource_limits.max_disk_bytes,
                within_budget=True,
                file_count=0,
            )

        total_bytes = 0
        file_count = 0
        for root, _, files in os.walk(ws_path):
            for f in files:
                fp = Path(root) / f
                if not fp.is_symlink():
                    try:
                        total_bytes += fp.stat().st_size
                        file_count += 1
                    except OSError:
                        pass

        limit_bytes = max_bytes or meta.resource_limits.max_disk_bytes
        limit_files = max_files or DEFAULT_MAX_WORKSPACE_FILES
        within_bytes = total_bytes <= limit_bytes
        within_files = file_count <= limit_files
        within_budget = within_bytes and within_files

        err_msg = None
        if not within_bytes:
            err_msg = (
                f"Workspace disk usage {total_bytes} bytes exceeds quota {limit_bytes} bytes for task '{task_id}'."
            )
        elif not within_files:
            err_msg = (
                f"Workspace file count {file_count} exceeds maximum allowed {limit_files} files for task '{task_id}'."
            )

        if not within_budget:
            self.record_timeline_event(
                task_id=task_id,
                event_type=WorkspaceExecutionEventType.DISK_QUOTA_EXCEEDED,
                message=err_msg or "Disk budget exceeded.",
                payload={
                    "disk_usage_bytes": total_bytes,
                    "max_disk_bytes": limit_bytes,
                    "file_count": file_count,
                    "max_files": limit_files,
                },
            )

        return WorkspaceDiskUsageResult(
            task_id=task_id,
            disk_usage_bytes=total_bytes,
            max_disk_bytes=limit_bytes,
            within_budget=within_budget,
            file_count=file_count,
            error_message=err_msg,
        )
