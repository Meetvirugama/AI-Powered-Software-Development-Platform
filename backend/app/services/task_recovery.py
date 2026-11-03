"""Task Recovery, Resilience & Safe Lifecycle Service.

Fulfills Week 3 Day 6 Deliverable (Docs/daily_tasks.md lines 653-660 & Docs/week3.md §6 F39, §8 Day 6).
Responsibilities:
- Reconcile task and external GitHub state across worker crashes and restarts.
- Detect base-revision drift and stale commits before or during execution.
- Enforce canonical state-transition policy guards (preventing approval bypass or retry counter reset).
- Safely clean up isolated task workspaces with traversal confinement.
- Ensure idempotent operations and standardize failure recovery states (RECOVERY_REQUIRED, BLOCKED, FAILED).
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any
from uuid import UUID

from app.core.errors import APIError, ErrorCode
from app.core.input_security import UnsafePathError, validate_repo_relative_path
from app.models.repository import Repository
from app.schemas.task import TaskStatus, can_transition

logger = logging.getLogger(__name__)


class TaskRecoveryService:
    """Provides failure recovery, state reconciliation, and cleanup operations."""

    def __init__(self, db: Any = None) -> None:
        self._db = db

    @staticmethod
    def validate_task_transition(current_status: str | TaskStatus, target_status: str | TaskStatus) -> None:
        """Validate state transition against canonical state machine.

        Raises APIError(400, INVALID_STATE_TRANSITION) if illegal.
        """
        curr = TaskStatus(current_status) if not isinstance(current_status, TaskStatus) else current_status
        target = TaskStatus(target_status) if not isinstance(target_status, TaskStatus) else target_status

        if not can_transition(curr, target):
            raise APIError(
                400,
                ErrorCode.INVALID_STATE_TRANSITION,
                f"Illegal task transition from '{curr.value}' to '{target.value}'.",
            )

    @staticmethod
    def detect_base_revision_drift(
        recorded_base_sha: str,
        current_remote_sha: str,
    ) -> bool:
        """Return True if remote base branch SHA has moved past the recorded task base SHA."""
        if not recorded_base_sha or not current_remote_sha:
            return False
        return recorded_base_sha.strip().lower() != current_remote_sha.strip().lower()

    async def reconcile_task_state(
        self,
        task_id: UUID | str,
        repository_id: UUID | str,
        last_known_status: str | TaskStatus,
        recorded_base_sha: str | None = None,
        remote_branch_exists: bool = False,
        remote_pr_exists: bool = False,
        current_remote_base_sha: str | None = None,
        repair_attempts_used: int = 0,
    ) -> dict[str, Any]:
        """Reconcile in-flight task state after worker restart or network failure.

        Rules:
        1. If base revision drift detected -> status must transition to RECOVERY_REQUIRED.
        2. If remote PR already created -> reconcile status to DRAFT_PR_CREATED.
        3. If worker crashed during EXECUTING and branch exists -> resume at WORKSPACE_SETUP or EXECUTING.
        4. Budget count is strictly preserved; cannot be reset by a worker restart.
        """
        task_uuid = UUID(str(task_id)) if not isinstance(task_id, UUID) else task_id
        curr_status = TaskStatus(last_known_status) if not isinstance(last_known_status, TaskStatus) else last_known_status

        drift_detected = False
        if recorded_base_sha and current_remote_base_sha:
            drift_detected = self.detect_base_revision_drift(recorded_base_sha, current_remote_base_sha)

        if drift_detected:
            return {
                "task_id": task_uuid,
                "reconciled_status": TaskStatus.RECOVERY_REQUIRED.value,
                "base_drift_detected": True,
                "recovery_action": "REPLAN_REQUIRED",
                "message": "Base revision drifted on remote. Re-planning or base update required.",
                "repair_attempts_used": repair_attempts_used,
            }

        if remote_pr_exists:
            return {
                "task_id": task_uuid,
                "reconciled_status": TaskStatus.DRAFT_PR_CREATED.value,
                "base_drift_detected": False,
                "recovery_action": "NONE",
                "message": "Draft PR confirmed on GitHub remote. Task complete.",
                "repair_attempts_used": repair_attempts_used,
            }

        # Handle recovery for tasks interrupted during execution
        if curr_status in (TaskStatus.EXECUTING, TaskStatus.TESTING, TaskStatus.REPAIRING):
            new_status = TaskStatus.WORKSPACE_SETUP if remote_branch_exists else TaskStatus.APPROVED
            return {
                "task_id": task_uuid,
                "reconciled_status": new_status.value,
                "base_drift_detected": False,
                "recovery_action": "RESUME_EXECUTION",
                "message": f"Worker recovered. Resuming task from safe state '{new_status.value}'.",
                "repair_attempts_used": repair_attempts_used,
            }

        return {
            "task_id": task_uuid,
            "reconciled_status": curr_status.value,
            "base_drift_detected": False,
            "recovery_action": "NONE",
            "message": f"Task state '{curr_status.value}' is consistent.",
            "repair_attempts_used": repair_attempts_used,
        }

    @staticmethod
    def cleanup_task_workspace(
        workspace_path: Path | str,
        task_id: UUID | str,
        workspace_root: Path | None = None,
    ) -> bool:
        """Safely delete disposable task workspace directory with boundary verification.

        Guards:
        - Must be strictly within workspace_root.
        - Cannot delete system directories or root.
        - Idempotent: returns True if directory does not exist or was deleted.
        """
        from app.services.git_branch import _DEFAULT_WORKSPACE_ROOT

        allowed_root = (workspace_root or _DEFAULT_WORKSPACE_ROOT).resolve()
        target = Path(workspace_path).resolve()

        # Confinement check
        try:
            target.relative_to(allowed_root)
        except ValueError as exc:
            raise APIError(
                400,
                ErrorCode.INVALID_REQUEST,
                f"Workspace path '{target}' escapes allowed workspace root '{allowed_root}'.",
            ) from exc

        # Do not allow deleting the root directory itself
        if target == allowed_root:
            raise APIError(400, ErrorCode.INVALID_REQUEST, "Cannot delete the entire workspace root directory.")

        if not target.exists():
            return True

        try:
            shutil.rmtree(target, ignore_errors=False)
            logger.info("Cleaned up task workspace %s for task %s", target, task_id)
            return True
        except Exception as exc:
            logger.warning("Failed to remove task workspace %s: %s", target, exc)
            return False
