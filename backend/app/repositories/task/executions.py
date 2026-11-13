"""Task workspace, execution, tool invocation, test run, repair, verification, checkpoint, and recovery aggregate."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional, Tuple

from sqlalchemy import desc, func, select
from sqlalchemy.orm import selectinload

from app.models.task import (
    ExecutionStatus,
    RepairAttempt,
    RepairResult,
    Task,
    TaskCheckpoint,
    TaskEventType,
    TaskExecution,
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
from app.repositories.task.exceptions import (
    InvalidStateTransitionError,
    TaskNotFoundError,
    _ensure_uuid,
    scrub_sensitive_data,
    scrub_sensitive_text,
)

from app.repositories.task.core import TaskCoreMixin


class TaskExecutionMixin:
    """Execution attempts, workspaces, checkpoints, bounded repairs, tests, and crash recovery."""

    def save_checkpoint(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        step_name: str,
        state_data: dict[str, Any],
        recovery_instructions: Optional[str] = None,
    ) -> TaskCheckpoint:
        """Persist a clean, secret-scrubbed recovery snapshot."""
        task = self.get_task(task_id, repository_id)
        if not task:
            raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")

        clean_data = scrub_sensitive_data(state_data)

        checkpoint = TaskCheckpoint(
            id=uuid.uuid4(),
            task_id=task.id,
            step_name=step_name,
            state_data=clean_data,
            recovery_instructions=scrub_sensitive_text(recovery_instructions),
        )
        self.session.add(checkpoint)
        self.session.flush()

        self.record_event(
            task_id=task.id,
            repository_id=task.repository_id,
            event_type=TaskEventType.CHECKPOINT_SAVED.value,
            event_data={"step_name": step_name},
        )

        self.session.commit()
        self.session.refresh(checkpoint)
        return checkpoint

    def get_latest_checkpoint(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
    ) -> Optional[TaskCheckpoint]:
        """Fetch latest recovery checkpoint for a task."""
        t_uuid = _ensure_uuid(task_id)
        r_uuid = _ensure_uuid(repository_id)
        if not t_uuid or not r_uuid:
            return None

        stmt = (
            select(TaskCheckpoint)
            .join(Task, Task.id == TaskCheckpoint.task_id)
            .where(TaskCheckpoint.task_id == t_uuid, Task.repository_id == r_uuid)
            .order_by(desc(TaskCheckpoint.created_at))
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list_checkpoints(
        self,
        task_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
    ) -> list[TaskCheckpoint]:
        """List all recovery checkpoints for a task, ordered newest-first."""
        t_uuid = _ensure_uuid(task_id)
        if t_uuid is None:
            return []
        if repository_id is not None:
            task = self.get_task(task_id, repository_id)
            if not task:
                raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")
        stmt = (
            select(TaskCheckpoint)
            .where(TaskCheckpoint.task_id == t_uuid)
            .order_by(TaskCheckpoint.created_at.desc())
        )
        return list(self.session.scalars(stmt).all())

    def increment_repair_attempt(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        failure_classification: Optional[str] = None,
        diagnosis: Optional[str] = None,
        applied_patch: Optional[str] = None,
    ) -> Tuple[RepairAttempt, bool]:
        """Enforce maximum 3 task-level repair attempts; returns (attempt, is_available)."""
        task = self.get_task(task_id, repository_id)
        if not task:
            raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")

        # Check if budget is already exhausted
        if task.repair_attempts_used >= task.repair_attempts_max:
            attempt = RepairAttempt(
                id=uuid.uuid4(),
                task_id=task.id,
                attempt_number=task.repair_attempts_used + 1,
                failure_classification=failure_classification,
                diagnosis=scrub_sensitive_text(diagnosis),
                applied_patch=scrub_sensitive_text(applied_patch),
                result=RepairResult.RETRY_EXHAUSTED.value,
            )
            self.session.add(attempt)
            task.status = TaskStatus.FAILED.value
            task.error_message = f"Retry budget exhausted: reached maximum {task.repair_attempts_max} attempts."
            self.session.flush()

            self.record_event(
                task_id=task.id,
                repository_id=task.repository_id,
                event_type=TaskEventType.EXECUTION_FAILED.value,
                event_data={"reason": task.error_message},
            )
            self.session.commit()
            return attempt, False

        # Budget is available: increment
        task.repair_attempts_used += 1
        current_attempt_num = task.repair_attempts_used

        attempt = RepairAttempt(
            id=uuid.uuid4(),
            task_id=task.id,
            attempt_number=current_attempt_num,
            failure_classification=failure_classification,
            diagnosis=scrub_sensitive_text(diagnosis),
            applied_patch=scrub_sensitive_text(applied_patch),
            result=RepairResult.SUCCESS.value,
        )
        self.session.add(attempt)
        self.session.flush()

        self.record_event(
            task_id=task.id,
            repository_id=task.repository_id,
            event_type=TaskEventType.REPAIR_ATTEMPTED.value,
            event_data={
                "attempt_number": current_attempt_num,
                "remaining_budget": task.repair_attempts_max - current_attempt_num,
                "failure_classification": failure_classification,
            },
        )
        self.session.commit()
        self.session.refresh(attempt)
        return attempt, True

    def get_repair_attempts(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
    ) -> list[RepairAttempt]:
        """Fetch all repair attempts for an authorized task ordered by attempt number."""
        task = self.get_task(task_id, repository_id)
        if not task:
            raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")

        stmt = select(RepairAttempt).where(RepairAttempt.task_id == task.id).order_by(RepairAttempt.attempt_number.asc())
        return list(self.session.execute(stmt).scalars().all())

    def list_repair_attempts(self, task_id: uuid.UUID | str) -> list[RepairAttempt]:
        """List all persisted RepairAttempt records for a task ordered by attempt_number asc."""
        t_uuid = _ensure_uuid(task_id)
        if t_uuid is None:
            return []
        stmt = (
            select(RepairAttempt)
            .where(RepairAttempt.task_id == t_uuid)
            .order_by(RepairAttempt.attempt_number.asc())
        )
        return list(self.session.scalars(stmt).all())

    def list_repair_records(self, task_id: uuid.UUID | str) -> list[RepairAttempt]:
        """Alias for list_repair_attempts for backward compatibility."""
        return self.list_repair_attempts(task_id)

    def record_workspace(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        workspace_path: str,
        task_branch: str,
        base_revision: str,
        status: WorkspaceStatus | str = WorkspaceStatus.READY,
    ) -> Workspace:
        """Register isolated task workspace."""
        task = self.get_task(task_id, repository_id)
        if not task:
            raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")

        status_val = status.value if isinstance(status, WorkspaceStatus) else str(status)

        existing = self.session.execute(
            select(Workspace).where(Workspace.task_id == task.id)
        ).scalar_one_or_none()

        if existing:
            existing.workspace_path = workspace_path
            existing.task_branch = task_branch
            existing.base_revision = base_revision
            existing.status = status_val
            ws = existing
        else:
            ws = Workspace(
                id=uuid.uuid4(),
                task_id=task.id,
                workspace_path=workspace_path,
                task_branch=task_branch,
                base_revision=base_revision,
                status=status_val,
            )
            self.session.add(ws)

        self.session.flush()
        self.record_event(
            task_id=task.id,
            repository_id=task.repository_id,
            event_type=TaskEventType.WORKSPACE_CREATED.value,
            event_data={
                "workspace_path": workspace_path,
                "task_branch": task_branch,
                "base_revision": base_revision,
            },
        )
        self.session.commit()
        self.session.refresh(ws)
        return ws

    def get_workspace(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        user_id: Optional[uuid.UUID | str] = None,
    ) -> Optional[Workspace]:
        """Fetch isolated workspace for an authorized task."""
        task = self.get_task(task_id, repository_id=repository_id, user_id=user_id)
        if not task:
            raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")

        return self.session.execute(
            select(Workspace).where(Workspace.task_id == task.id)
        ).scalar_one_or_none()

    def get_workspace_record(
        self,
        task_id: uuid.UUID | str,
        user_id: Optional[uuid.UUID | str] = None,
    ) -> Optional[Workspace]:
        """Return persisted Workspace record for an authorized task if one exists."""
        t_uuid = _ensure_uuid(task_id)
        if t_uuid is None:
            return None
        if user_id is not None:
            task = self.get_task(t_uuid, user_id=user_id)
            if not task:
                return None
        stmt = select(Workspace).where(Workspace.task_id == t_uuid)
        return self.session.execute(stmt).scalar_one_or_none()

    def update_workspace_status(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        status: WorkspaceStatus | str,
        current_revision: Optional[str] = None,
        cleanup_at: Optional[datetime] = None,
    ) -> Workspace:
        """Update workspace lifecycle status, current revision, or cleanup timestamp."""
        task = self.get_task(task_id, repository_id)
        if not task:
            raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")

        ws = self.session.execute(
            select(Workspace).where(Workspace.task_id == task.id)
        ).scalar_one_or_none()
        if not ws:
            raise RuntimeError(f"Workspace not initialized for task {task_id}")

        status_val = status.value if isinstance(status, WorkspaceStatus) else str(status)
        ws.status = status_val
        if current_revision is not None:
            ws.current_revision = current_revision
        if cleanup_at is not None:
            ws.cleanup_at = cleanup_at

        self.session.flush()
        self.session.commit()
        self.session.refresh(ws)
        return ws

    def record_tool_invocation(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        tool_name: str,
        arguments: Optional[dict[str, Any]] = None,
        status: ToolInvocationStatus | str = ToolInvocationStatus.COMPLETED,
        duration_ms: Optional[int] = None,
        output_summary: Optional[str] = None,
        tool_version: Optional[str] = None,
        tool_source: str = "builtin",
        provider_id: Optional[str] = None,
        risk_tier: str = "low",
        schema_fingerprint: Optional[str] = None,
        execution_timeout_s: Optional[int] = None,
        execution_timed_out: bool = False,
        rate_limit_status: Optional[str] = None,
        error_category: Optional[str] = None,
    ) -> ToolInvocation:
        """Record a validated tool invocation with enhanced audit metadata."""
        task = self.get_task(task_id, repository_id)
        if not task:
            raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")

        status_val = status.value if isinstance(status, ToolInvocationStatus) else str(status)

        inv = ToolInvocation(
            id=uuid.uuid4(),
            task_id=task.id,
            tool_name=tool_name,
            sanitized_arguments=scrub_sensitive_data(arguments),
            status=status_val,
            duration_ms=duration_ms,
            output_summary=scrub_sensitive_text(output_summary),
            tool_version=tool_version,
            tool_source=tool_source,
            provider_id=provider_id,
            risk_tier=risk_tier,
            schema_fingerprint=schema_fingerprint,
            execution_timeout_s=execution_timeout_s,
            execution_timed_out=execution_timed_out,
            rate_limit_status=rate_limit_status,
            error_category=error_category,
        )
        self.session.add(inv)
        self.session.flush()

        self.record_event(
            task_id=task.id,
            repository_id=task.repository_id,
            event_type=TaskEventType.TOOL_INVOKED.value,
            event_data={
                "tool_name": tool_name,
                "status": status_val,
                "duration_ms": duration_ms,
                "risk_tier": risk_tier,
                "error_category": error_category,
            },
        )
        self.session.commit()
        self.session.refresh(inv)
        return inv

    def get_tool_invocations(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
    ) -> list[ToolInvocation]:
        """Fetch all tool invocations for an authorized task ordered chronologically."""
        task = self.get_task(task_id, repository_id)
        if not task:
            raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")

        stmt = select(ToolInvocation).where(ToolInvocation.task_id == task.id).order_by(ToolInvocation.created_at.asc())
        return list(self.session.execute(stmt).scalars().all())

    def record_execution_start(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        worker_id: Optional[str] = None,
        attempt_number: Optional[int] = None,
    ) -> TaskExecution:
        """Record the start of a worker execution attempt."""
        task = self.get_task(task_id, repository_id)
        if not task:
            raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")

        if attempt_number is None:
            highest_attempt = (
                self.session.execute(
                    select(func.max(TaskExecution.attempt_number)).where(TaskExecution.task_id == task.id)
                ).scalar_one_or_none()
                or 0
            )
            attempt_number = highest_attempt + 1

        execution = TaskExecution(
            id=uuid.uuid4(),
            task_id=task.id,
            attempt_number=attempt_number,
            worker_id=worker_id,
            status=ExecutionStatus.RUNNING.value,
            started_at=datetime.now(timezone.utc),
        )
        self.session.add(execution)
        self.session.flush()
        self.session.commit()
        self.session.refresh(execution)
        return execution

    def record_execution_finish(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        execution_id: uuid.UUID | str,
        status: ExecutionStatus | str = ExecutionStatus.COMPLETED,
        error_message: Optional[str] = None,
    ) -> TaskExecution:
        """Record the completion or failure of a worker execution attempt."""
        task = self.get_task(task_id, repository_id)
        if not task:
            raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")

        e_uuid = _ensure_uuid(execution_id)
        execution = self.session.execute(
            select(TaskExecution).where(TaskExecution.id == e_uuid, TaskExecution.task_id == task.id)
        ).scalar_one_or_none()
        if not execution:
            raise LookupError(f"Execution {execution_id} not found for task {task_id}")

        status_val = status.value if isinstance(status, ExecutionStatus) else str(status)
        execution.status = status_val
        execution.completed_at = datetime.now(timezone.utc)
        execution.error_message = scrub_sensitive_text(error_message)

        self.session.flush()
        self.session.commit()
        self.session.refresh(execution)
        return execution

    def get_executions(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
    ) -> list[TaskExecution]:
        """Fetch all execution attempts for an authorized task ordered ascending."""
        task = self.get_task(task_id, repository_id)
        if not task:
            raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")

        stmt = select(TaskExecution).where(TaskExecution.task_id == task.id).order_by(TaskExecution.attempt_number.asc())
        return list(self.session.execute(stmt).scalars().all())

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
    ) -> TestRun:
        """Record permitted test execution results and logs."""
        task = self.get_task(task_id, repository_id)
        if not task:
            raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")

        status_val = status.value if isinstance(status, TestRunStatus) else str(status)

        run = TestRun(
            id=uuid.uuid4(),
            task_id=task.id,
            command=command,
            status=status_val,
            exit_code=exit_code,
            duration_ms=duration_ms,
            tests_total=tests_total,
            tests_passed=tests_passed,
            tests_failed=tests_failed,
            sanitized_output=scrub_sensitive_text(sanitized_output),
            target_revision=target_revision,
        )
        self.session.add(run)
        self.session.flush()

        self.record_event(
            task_id=task.id,
            repository_id=task.repository_id,
            event_type=TaskEventType.TESTS_EXECUTED.value,
            event_data={
                "command": command,
                "status": status_val,
                "passed": tests_passed,
                "failed": tests_failed,
            },
        )
        self.session.commit()
        self.session.refresh(run)
        return run

    def get_test_runs(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
    ) -> list[TestRun]:
        """Fetch all test runs for an authorized task ordered chronologically."""
        task = self.get_task(task_id, repository_id)
        if not task:
            raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")

        stmt = select(TestRun).where(TestRun.task_id == task.id).order_by(TestRun.created_at.asc())
        return list(self.session.execute(stmt).scalars().all())

    def list_test_runs(self, task_id: uuid.UUID | str) -> list[TestRun]:
        """List all persisted TestRun records for a task in chronological order."""
        t_uuid = _ensure_uuid(task_id)
        if t_uuid is None:
            return []
        stmt = (
            select(TestRun)
            .where(TestRun.task_id == t_uuid)
            .order_by(TestRun.created_at.asc())
        )
        return list(self.session.scalars(stmt).all())

    def get_latest_test_run(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
    ) -> Optional[TestRun]:
        """Fetch the most recent test run for an authorized task."""
        task = self.get_task(task_id, repository_id)
        if not task:
            raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")

        stmt = select(TestRun).where(TestRun.task_id == task.id).order_by(desc(TestRun.created_at))
        return self.session.execute(stmt).scalars().first()

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
    ) -> VerificationResult:
        """Record independent verification outcome strictly bound to verified revision (Day 5)."""
        task = self.get_task(task_id, repository_id)
        if not task:
            raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")

        if task.status in {TaskStatus.FAILED.value, TaskStatus.CANCELLED.value}:
            raise InvalidStateTransitionError(
                f"Cannot record verification result for task in terminal status '{task.status}'."
            )

        status_val = status.value if isinstance(status, VerificationStatus) else str(status)

        res = VerificationResult(
            id=uuid.uuid4(),
            task_id=task.id,
            verified_revision=verified_revision,
            status=status_val,
            checks=scrub_sensitive_data(checks),
            blocking_findings=scrub_sensitive_data(blocking_findings),
            warnings=scrub_sensitive_data(warnings),
            summary=scrub_sensitive_text(summary),
        )
        self.session.add(res)

        # State transition based on verification outcome (§7.1, §7.2)
        has_blocking = bool(blocking_findings and len(blocking_findings) > 0)
        if status_val in {VerificationStatus.PASSED.value, "PASS"} and not has_blocking:
            task.status = TaskStatus.READY_FOR_PUBLICATION.value
        elif status_val in {VerificationStatus.FAILED.value, "FAIL"} or has_blocking:
            task.status = TaskStatus.BLOCKED.value

        self.session.flush()

        self.record_event(
            task_id=task.id,
            repository_id=task.repository_id,
            event_type=TaskEventType.VERIFICATION_COMPLETED.value,
            event_data={
                "verified_revision": verified_revision,
                "status": status_val,
                "blocking_count": len(blocking_findings or []),
                "task_status": task.status,
            },
        )
        self.session.commit()
        self.session.refresh(res)
        return res

    def get_verification_results(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
    ) -> list[VerificationResult]:
        """Fetch all verification results for an authorized task ordered newest-first (Day 5)."""
        task = self.get_task(task_id, repository_id)
        if not task:
            raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")

        stmt = (
            select(VerificationResult)
            .where(VerificationResult.task_id == task.id)
            .order_by(VerificationResult.created_at.desc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def get_latest_verification_result(
        self,
        task_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
    ) -> Optional[VerificationResult]:
        """Fetch the most recent verification result for an authorized task (Day 5)."""
        if repository_id is not None:
            results = self.get_verification_results(task_id, repository_id)
            return results[0] if results else None
        t_uuid = _ensure_uuid(task_id)
        if t_uuid is None:
            return None
        stmt = (
            select(VerificationResult)
            .where(VerificationResult.task_id == t_uuid)
            .order_by(VerificationResult.created_at.desc())
        )
        return self.session.scalars(stmt).first()

    def reconcile_interrupted_tasks(
        self,
        repository_id: Optional[uuid.UUID | str] = None,
    ) -> list[uuid.UUID]:
        """Transition any in-flight tasks interrupted by worker restart to RECOVERY_REQUIRED (F39)."""
        in_flight_statuses = [
            TaskStatus.WORKSPACE_SETUP.value,
            TaskStatus.EXECUTING.value,
            TaskStatus.TESTING.value,
            TaskStatus.REPAIRING.value,
            TaskStatus.VERIFYING.value,
            TaskStatus.PUBLISHING.value,
        ]
        stmt = select(Task).where(Task.status.in_(in_flight_statuses))
        if repository_id is not None:
            r_uuid = _ensure_uuid(repository_id)
            if r_uuid is not None:
                stmt = stmt.where(Task.repository_id == r_uuid)

        interrupted = list(self.session.scalars(stmt).all())
        reconciled_ids: list[uuid.UUID] = []
        for task in interrupted:
            prev_status = task.status
            task.status = TaskStatus.RECOVERY_REQUIRED.value
            task.error_message = (
                f"Worker interrupted while task was in '{prev_status}'; marked RECOVERY_REQUIRED for safe recovery."
            )
            self.record_event(
                task_id=task.id,
                repository_id=task.repository_id,
                event_type=TaskEventType.RECOVERY_TRIGGERED.value,
                event_data={
                    "previous_status": prev_status,
                    "new_status": TaskStatus.RECOVERY_REQUIRED.value,
                    "reason": "startup_worker_reconciliation",
                },
                from_status=prev_status,
                to_status=TaskStatus.RECOVERY_REQUIRED.value,
                summary=f"Worker restart reconciled interrupted task from {prev_status} to RECOVERY_REQUIRED.",
            )
            reconciled_ids.append(task.id)

        if reconciled_ids:
            self.session.commit()
        return reconciled_ids

    def get_active_tasks_for_repository(
        self,
        repository_id: uuid.UUID | str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Task]:
        """Fetch active non-terminal tasks using composite index (repository_id, status)."""
        r_uuid = _ensure_uuid(repository_id)
        if not r_uuid:
            return []
        terminal_statuses = {
            TaskStatus.DRAFT_PR_CREATED.value,
            TaskStatus.CANCELLED.value,
            TaskStatus.FAILED.value,
        }
        stmt = (
            select(Task)
            .where(
                Task.repository_id == r_uuid,
                Task.status.notin_(terminal_statuses),
            )
            .options(
                selectinload(Task.plans),
                selectinload(Task.approvals),
                selectinload(Task.workspace),
            )
            .order_by(Task.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.scalars(stmt).all())

    def reconcile_crashed_task(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        reason: str = "Worker crash detected during execution",
    ) -> Task:
        """Reconcile an individual task interrupted by worker failure (Docs/week3.md §8, §6 F39)."""
        task = self.get_task(task_id, repository_id)
        if not task:
            raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")

        volatile_states = {
            TaskStatus.WORKSPACE_SETUP.value,
            TaskStatus.EXECUTING.value,
            TaskStatus.TESTING.value,
            TaskStatus.REPAIRING.value,
        }

        # If task is not in a volatile state, recovery is an idempotent no-op
        if task.status not in volatile_states:
            return task

        # Fail any open running execution records
        open_executions = (
            self.session.execute(
                select(TaskExecution).where(
                    TaskExecution.task_id == task.id,
                    TaskExecution.status.in_([ExecutionStatus.STARTED.value, ExecutionStatus.RUNNING.value]),
                )
            )
            .scalars()
            .all()
        )
        for ex in open_executions:
            ex.status = ExecutionStatus.FAILED.value
            ex.completed_at = datetime.now(timezone.utc)
            ex.error_message = reason
        self.session.flush()

        # Check if retry budget is exhausted
        if task.repair_attempts_used >= task.repair_attempts_max:
            old_status = task.status
            task.status = TaskStatus.FAILED.value
            task.error_message = "Task recovery failed: repair attempt budget exhausted."
            task.updated_at = datetime.now(timezone.utc)
            self.session.flush()

            self.record_event(
                task_id=task.id,
                repository_id=task.repository_id,
                event_type="RECOVERY_FAILED",
                event_data={
                    "from_status": old_status,
                    "to_status": task.status,
                    "repair_attempts_used": task.repair_attempts_used,
                    "repair_attempts_max": task.repair_attempts_max,
                    "reason": "Repair retry budget exhausted during crash recovery",
                },
                from_status=old_status,
                to_status=task.status,
                summary="Task marked as FAILED during crash recovery: repair retry budget exhausted.",
            )
            self.session.commit()
            return task

        # Check for latest valid checkpoint
        latest_cp = self.get_latest_checkpoint(task.id, repository_id)
        old_status = task.status
        task.status = TaskStatus.RECOVERY_REQUIRED.value
        task.error_message = reason
        task.updated_at = datetime.now(timezone.utc)
        self.session.flush()

        if latest_cp:
            event_type = "CRASH_RECOVERED"
            event_summary = f"Crash recovery performed using checkpoint {latest_cp.step_name}."
            event_data = {
                "checkpoint_id": str(latest_cp.id),
                "step_name": latest_cp.step_name,
                "recovery_instructions": latest_cp.recovery_instructions,
                "from_status": old_status,
                "to_status": task.status,
                "repair_attempts_used": task.repair_attempts_used,
            }
        else:
            event_type = "CRASH_DETECTED"
            event_summary = "Crash detected with no available checkpoint. Marked as RECOVERY_REQUIRED."
            event_data = {
                "from_status": old_status,
                "to_status": task.status,
                "repair_attempts_used": task.repair_attempts_used,
                "reason": reason,
            }

        self.record_event(
            task_id=task.id,
            repository_id=task.repository_id,
            event_type=event_type,
            event_data=event_data,
            from_status=old_status,
            to_status=task.status,
            summary=event_summary,
        )
        self.session.commit()
        return task

    def recover_interrupted_tasks(
        self,
        repository_id: uuid.UUID | str,
        worker_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Find and reconcile all tasks left in volatile states across a repository."""
        r_uuid = _ensure_uuid(repository_id)
        if not r_uuid:
            return []

        volatile_states = [
            TaskStatus.WORKSPACE_SETUP.value,
            TaskStatus.EXECUTING.value,
            TaskStatus.TESTING.value,
            TaskStatus.REPAIRING.value,
        ]

        stmt = select(Task).where(
            Task.repository_id == r_uuid,
            Task.status.in_(volatile_states),
        )
        tasks = list(self.session.scalars(stmt).all())
        results = []

        for task in tasks:
            reconciled = self.reconcile_crashed_task(
                task_id=task.id,
                repository_id=r_uuid,
                reason=f"Worker failure detected for worker {worker_id or 'unknown'}",
            )
            results.append({
                "task_id": str(reconciled.id),
                "status": reconciled.status,
                "repair_attempts_used": reconciled.repair_attempts_used,
                "error_message": reconciled.error_message,
            })

        return results


class TaskExecutionRepository(TaskExecutionMixin, TaskCoreMixin):
    """Standalone domain aggregate for task executions and recovery."""
