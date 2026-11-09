"""Task and Workflow History Service (Week 3 — Days 2, 3 & 4).

Owner: Om — Database & Persistence Lead.
Implements: Feature F32 — Task Planner and Human Approval & F39 — Persistence, Checkpoints and Recovery.

Provides production-hardened orchestration and session management for:
1. Task creation and intake from requirements, issues, and Week 2 findings.
2. Context gathering persistence from Week 2 intelligence services.
3. Plan generation, versioning, and retrieval (latest & historical versions).
4. Human approval and rejection lifecycle, strictly bound to specific plan versions.
5. Invalidation of approvals upon plan edits/revisions, returning task to PENDING_APPROVAL.
6. State machine transition enforcement at the service boundary (§7.1, §7.2).
7. Audit event timeline tracking and safe checkpoint persistence.
8. Multi-tenant repository isolation and automated credential scrubbing.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Generator, List, Optional, Tuple

from sqlalchemy.orm import Session, sessionmaker

from app.models.task import (
    ExecutionStatus,
    RepairAttempt,
    Task,
    TaskApproval,
    TaskCheckpoint,
    TaskEvent,
    TaskExecution,
    TaskPlan,
    TaskPullRequest,
    TaskSourceType,
    TaskStatus,
    TestRun,
    TestRunStatus,
    ToolInvocation,
    ToolInvocationStatus,
    VerificationResult,
    VerificationStatus,
    Workspace,
    WorkspaceStatus,
)
from app.repositories.task_repository import (
    TaskRepository,
)

logger = logging.getLogger(__name__)


class TaskHistoryService:
    """Service managing persistent lifecycle, plans, approvals, and recovery for workflow tasks."""

    def __init__(
        self,
        session_factory: Optional[sessionmaker] = None,
        session: Optional[Session] = None,
    ) -> None:
        self.session_factory = session_factory
        self._session = session

    @contextmanager
    def _get_session(self, db: Optional[Session] = None) -> Generator[Session, None, None]:
        """Provide an active database session from argument, cached session, or session factory."""
        if db is not None:
            yield db
            return
        if self._session is not None:
            yield self._session
            return
        if self.session_factory is not None:
            s: Session = self.session_factory()
            try:
                yield s
            finally:
                s.close()
            return
        raise RuntimeError("No database session or session_factory configured for TaskHistoryService.")

    # -----------------------------------------------------------------------
    # 1. Task Intake & Lifecycle Management
    # -----------------------------------------------------------------------

    def create_task(
        self,
        repository_id: uuid.UUID | str,
        title: str,
        source_type: TaskSourceType | str = TaskSourceType.GITHUB_ISSUE,
        description: Optional[str] = None,
        source_id: Optional[str] = None,
        source_metadata: Optional[dict[str, Any]] = None,
        finding_id: Optional[uuid.UUID | str] = None,
        user_id: Optional[uuid.UUID | str] = None,
        base_revision: str = "main",
        db: Optional[Session] = None,
    ) -> Task:
        """Create and persist a new workflow task with source and finding traceability."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.create_task(
                repository_id=repository_id,
                title=title,
                source_type=source_type,
                description=description,
                source_id=source_id,
                source_metadata=source_metadata,
                finding_id=finding_id,
                user_id=user_id,
                base_revision=base_revision,
            )

    def get_task(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        db: Optional[Session] = None,
    ) -> Optional[Task]:
        """Fetch task enforcing strict multi-tenant repository isolation."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.get_task(task_id, repository_id)

    def list_tasks(
        self,
        repository_id: uuid.UUID | str,
        status: Optional[str] = None,
        source_type: Optional[str] = None,
        user_id: Optional[uuid.UUID | str] = None,
        offset: int = 0,
        limit: int = 20,
        db: Optional[Session] = None,
    ) -> Tuple[List[Task], int]:
        """Retrieve paginated tasks for repository dashboard ordered newest-first."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.list_tasks(
                repository_id=repository_id,
                status=status,
                source_type=source_type,
                user_id=user_id,
                offset=offset,
                limit=limit,
            )

    def transition_status(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        new_status: TaskStatus | str,
        user_id: Optional[uuid.UUID | str] = None,
        reason: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> Task:
        """Enforce state transition preconditions and record transition event."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.transition_status(
                task_or_id=task_id,
                repository_id_or_status=repository_id,
                new_status=new_status,
                user_id=user_id,
                reason=reason,
            )

    def update_task_context(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        context_summary: Optional[str] = None,
        base_revision: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> Task:
        """Update task context gathered through existing intelligence services."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.update_task_context(
                task_id=task_id,
                repository_id=repository_id,
                context_summary=context_summary,
                base_revision=base_revision,
            )

    # -----------------------------------------------------------------------
    # 2. Plan Generation, Versioning & Approvals (Day 2 Deliverables)
    # -----------------------------------------------------------------------

    def save_plan(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        summary: str,
        steps: list[dict[str, Any]],
        base_revision: Optional[str] = None,
        problem_statement: Optional[str] = None,
        expected_files: Optional[list[str]] = None,
        tests_to_run: Optional[list[str]] = None,
        validation_strategy: Optional[str] = None,
        risks: Optional[list[str]] = None,
        db: Optional[Session] = None,
    ) -> TaskPlan:
        """Create and version an implementation plan, superseding older versions and resetting approval."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.save_plan(
                task_id=task_id,
                repository_id=repository_id,
                summary=summary,
                steps=steps,
                base_revision=base_revision,
                problem_statement=problem_statement,
                expected_files=expected_files,
                tests_to_run=tests_to_run,
                validation_strategy=validation_strategy,
                risks=risks,
            )

    def get_plan(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        version: Optional[int] = None,
        db: Optional[Session] = None,
    ) -> Optional[TaskPlan]:
        """Fetch a specific plan version or the latest plan for an authorized task."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.get_plan(task_id, repository_id, version=version)

    def list_plans(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        db: Optional[Session] = None,
    ) -> list[TaskPlan]:
        """List all plan versions for an authorized task ordered by version ascending."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.list_plans(task_id, repository_id)

    def approve_plan(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        plan_version: int,
        user_id: Optional[uuid.UUID | str] = None,
        feedback: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> TaskApproval:
        """Record an immutable plan approval and transition task to APPROVED."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.approve_plan(
                task_id=task_id,
                repository_id=repository_id,
                plan_version=plan_version,
                user_id=user_id,
                feedback=feedback,
            )

    def reject_plan(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        plan_version: int,
        user_id: Optional[uuid.UUID | str] = None,
        feedback: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> TaskApproval:
        """Record an immutable plan rejection and transition task to REJECTED."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.reject_plan(
                task_id=task_id,
                repository_id=repository_id,
                plan_version=plan_version,
                user_id=user_id,
                feedback=feedback,
            )

    def get_approval(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        plan_version: Optional[int] = None,
        db: Optional[Session] = None,
    ) -> Optional[TaskApproval]:
        """Fetch approval for a specific plan version or latest approval for an authorized task."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.get_approval(task_id, repository_id, plan_version=plan_version)

    def list_approvals(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        db: Optional[Session] = None,
    ) -> list[TaskApproval]:
        """List all approval and rejection records for an authorized task."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.list_approvals(task_id, repository_id)

    # -----------------------------------------------------------------------
    # 3. Timeline & Checkpoint Persistence
    # -----------------------------------------------------------------------

    def get_task_timeline(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        db: Optional[Session] = None,
    ) -> list[TaskEvent]:
        """Retrieve ordered historical events for dashboard timeline."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.get_task_timeline(task_id, repository_id)

    def save_checkpoint(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        step_name: str,
        state_data: dict[str, Any],
        recovery_instructions: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> TaskCheckpoint:
        """Persist a clean, secret-scrubbed recovery snapshot."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.save_checkpoint(
                task_id=task_id,
                repository_id=repository_id,
                step_name=step_name,
                state_data=state_data,
                recovery_instructions=recovery_instructions,
            )

    def get_latest_checkpoint(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        db: Optional[Session] = None,
    ) -> Optional[TaskCheckpoint]:
        """Retrieve the most recent checkpoint for worker recovery."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.get_latest_checkpoint(task_id, repository_id)


    # -----------------------------------------------------------------------
    # 4. Workspace, Execution & Tool Invocation Persistence (Day 3)
    # -----------------------------------------------------------------------

    def record_workspace(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        workspace_path: str,
        task_branch: str,
        base_revision: str,
        status: WorkspaceStatus | str = WorkspaceStatus.READY,
        db: Optional[Session] = None,
    ) -> Workspace:
        """Register isolated task workspace directory and branch."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.record_workspace(
                task_id=task_id,
                repository_id=repository_id,
                workspace_path=workspace_path,
                task_branch=task_branch,
                base_revision=base_revision,
                status=status,
            )

    def get_workspace(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        db: Optional[Session] = None,
    ) -> Optional[Workspace]:
        """Fetch isolated workspace for an authorized task."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.get_workspace(task_id, repository_id)

    def update_workspace_status(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        status: WorkspaceStatus | str,
        current_revision: Optional[str] = None,
        cleanup_at: Optional[datetime] = None,
        db: Optional[Session] = None,
    ) -> Workspace:
        """Update workspace lifecycle status, current revision, or cleanup timestamp."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.update_workspace_status(
                task_id=task_id,
                repository_id=repository_id,
                status=status,
                current_revision=current_revision,
                cleanup_at=cleanup_at,
            )

    def record_execution_start(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        worker_id: Optional[str] = None,
        attempt_number: Optional[int] = None,
        db: Optional[Session] = None,
    ) -> TaskExecution:
        """Record the start of a worker execution attempt."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.record_execution_start(
                task_id=task_id,
                repository_id=repository_id,
                worker_id=worker_id,
                attempt_number=attempt_number,
            )

    def record_execution_finish(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        execution_id: uuid.UUID | str,
        status: ExecutionStatus | str = ExecutionStatus.COMPLETED,
        error_message: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> TaskExecution:
        """Record the completion or failure of a worker execution attempt."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.record_execution_finish(
                task_id=task_id,
                repository_id=repository_id,
                execution_id=execution_id,
                status=status,
                error_message=error_message,
            )

    def get_executions(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        db: Optional[Session] = None,
    ) -> list[TaskExecution]:
        """Fetch all execution attempts for an authorized task ordered ascending."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.get_executions(task_id, repository_id)

    def record_tool_invocation(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        tool_name: str,
        arguments: Optional[dict[str, Any]] = None,
        status: ToolInvocationStatus | str = ToolInvocationStatus.COMPLETED,
        duration_ms: Optional[int] = None,
        output_summary: Optional[str] = None,
        db: Optional[Session] = None,
        **kwargs: Any,
    ) -> ToolInvocation:
        """Record an operation routed through the controlled tool router with argument scrubbing."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.record_tool_invocation(
                task_id=task_id,
                repository_id=repository_id,
                tool_name=tool_name,
                arguments=arguments,
                status=status,
                duration_ms=duration_ms,
                output_summary=output_summary,
                **kwargs,
            )

    def get_tool_invocations(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        db: Optional[Session] = None,
    ) -> list[ToolInvocation]:
        """Fetch all tool invocations for an authorized task ordered chronologically."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.get_tool_invocations(task_id, repository_id)

    # -----------------------------------------------------------------------
    # 5. Test Execution & Bounded Repair Persistence (Day 4)
    # -----------------------------------------------------------------------

    def record_test_run(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        command: str,
        status: TestRunStatus | str,
        exit_code: Optional[int] = None,
        duration_ms: Optional[int] = None,
        tests_total: int = 0,
        tests_passed: int = 0,
        tests_failed: int = 0,
        sanitized_output: Optional[str] = None,
        target_revision: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> TestRun:
        """Record permitted test execution results, pass/fail counts, and sanitized output."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.record_test_run(
                task_id=task_id,
                repository_id=repository_id,
                command=command,
                status=status,
                exit_code=exit_code,
                duration_ms=duration_ms,
                tests_total=tests_total,
                tests_passed=tests_passed,
                tests_failed=tests_failed,
                sanitized_output=sanitized_output,
                target_revision=target_revision,
            )

    def get_test_runs(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        db: Optional[Session] = None,
    ) -> list[TestRun]:
        """Fetch all test runs for an authorized task ordered chronologically."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.get_test_runs(task_id, repository_id)

    def get_latest_test_run(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        db: Optional[Session] = None,
    ) -> Optional[TestRun]:
        """Fetch the most recent test run for an authorized task."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.get_latest_test_run(task_id, repository_id)

    def increment_repair_attempt(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        failure_classification: Optional[str] = None,
        diagnosis: Optional[str] = None,
        applied_patch: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> Tuple[RepairAttempt, bool]:
        """Enforce maximum 3 task-level repair attempts; returns (attempt, is_available)."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.increment_repair_attempt(
                task_id=task_id,
                repository_id=repository_id,
                failure_classification=failure_classification,
                diagnosis=diagnosis,
                applied_patch=applied_patch,
            )

    def get_repair_attempts(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        db: Optional[Session] = None,
    ) -> list[RepairAttempt]:
        """Fetch all repair attempts for an authorized task ordered by attempt number."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.get_repair_attempts(task_id, repository_id)


    # -----------------------------------------------------------------------
    # 6. Independent Verification, Publication Authorization & Draft PR (Day 5)
    # -----------------------------------------------------------------------

    def record_verification_result(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        verified_revision: str,
        status: VerificationStatus | str,
        checks: Optional[list[dict[str, Any]]] = None,
        blocking_findings: Optional[list[dict[str, Any]]] = None,
        warnings: Optional[list[dict[str, Any]]] = None,
        summary: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> VerificationResult:
        """Record independent verification outcome and update task status based on checks (Day 5)."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.record_verification_result(
                task_id=task_id,
                repository_id=repository_id,
                verified_revision=verified_revision,
                status=status,
                checks=checks,
                blocking_findings=blocking_findings,
                warnings=warnings,
                summary=summary,
            )

    def get_verification_results(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        db: Optional[Session] = None,
    ) -> list[VerificationResult]:
        """Fetch all verification results for an authorized task ordered newest-first (Day 5)."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.get_verification_results(task_id, repository_id)

    def get_latest_verification_result(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        db: Optional[Session] = None,
    ) -> Optional[VerificationResult]:
        """Fetch the most recent verification result for an authorized task (Day 5)."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.get_latest_verification_result(task_id, repository_id)

    def authorize_publication(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        head_sha: str,
        user_id: Optional[uuid.UUID | str] = None,
        notes: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> Task:
        """Authorize branch publication after validating passing verification and zero blocking findings (Day 5)."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.authorize_publication(
                task_id=task_id,
                repository_id=repository_id,
                head_sha=head_sha,
                user_id=user_id,
                notes=notes,
            )

    def record_pull_request(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        pr_url: str,
        base_branch: str,
        head_branch: str,
        head_sha: str,
        title: str,
        body: Optional[str] = None,
        pr_number: Optional[int] = None,
        github_pr_id: Optional[int] = None,
        is_draft: bool = True,
        db: Optional[Session] = None,
    ) -> TaskPullRequest:
        """Record published Draft PR and advance task status to DRAFT_PR_CREATED (Day 5)."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.record_pull_request(
                task_id=task_id,
                repository_id=repository_id,
                pr_url=pr_url,
                base_branch=base_branch,
                head_branch=head_branch,
                head_sha=head_sha,
                title=title,
                body=body,
                pr_number=pr_number,
                github_pr_id=github_pr_id,
                is_draft=is_draft,
            )

    def get_pull_request(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        db: Optional[Session] = None,
    ) -> Optional[TaskPullRequest]:
        """Fetch recorded Pull Request for an authorized task (Day 5)."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.get_pull_request(task_id, repository_id)

    def get_task_traceability(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        db: Optional[Session] = None,
    ) -> dict[str, Any]:
        """Return complete end-to-end traceability linking finding -> issue -> task -> plan -> workspace -> execution -> tests -> repair -> verification -> Draft PR (Day 5)."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.get_task_traceability(task_id, repository_id)

    def get_active_tasks(
        self,
        repository_id: uuid.UUID | str,
        limit: int = 50,
        offset: int = 0,
        db: Optional[Session] = None,
    ) -> list[Task]:
        """Fetch active non-terminal tasks using compound index with session management (Day 6)."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.get_active_tasks_for_repository(repository_id, limit=limit, offset=offset)

    def reconcile_crashed_task(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        reason: str = "Worker crash detected during execution",
        db: Optional[Session] = None,
    ) -> Task:
        """Reconcile an individual crashed task with session management (Day 6 & F39)."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.reconcile_crashed_task(task_id, repository_id, reason=reason)

    def recover_interrupted_tasks(
        self,
        repository_id: uuid.UUID | str,
        worker_id: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> list[dict[str, Any]]:
        """Find and reconcile all tasks left in volatile states across a repository (Day 6 & F39)."""
        with self._get_session(db) as session:
            repo = TaskRepository(session)
            return repo.recover_interrupted_tasks(repository_id, worker_id=worker_id)

