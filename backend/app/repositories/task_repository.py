"""Task and Workflow Persistence Repository (Week 3 — Day 1).

Owner: Om — Database & Persistence Lead.
Implements: Feature F39 — Persistence, Checkpoints and Recovery.

Provides production-hardened query and lifecycle methods for:
- Task creation, intake from GitHub issues and Week 2 findings
- Strict multi-tenant repository isolation
- State-transition validation and enforcement (§7.1, §7.2)
- Plan versioning and immutable approval records
- Checkpoint management with automated secret scrubbing
- Bounded repair loop accounting (max 3 task-level attempts)
- Tool invocation and test run audit tracking
- Independent verification results tied to revision
- Ordered audit timeline events
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional, Sequence, Tuple

from sqlalchemy import delete, desc, func, select
from sqlalchemy.orm import Session, selectinload

from app.models.analysis_finding import AnalysisFinding
from app.models.task import (
    ApprovalDecision,
    ExecutionStatus,
    RepairAttempt,
    RepairResult,
    Task,
    TaskApproval,
    TaskCheckpoint,
    TaskEvent,
    TaskEventType,
    TaskExecution,
    TaskPlan,
    TaskPlanStatus,
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


class InvalidStateTransitionError(ValueError):
    """Raised when an illegal lifecycle state transition is requested."""
    pass


class TaskNotFoundError(LookupError):
    """Raised when a task cannot be found in the specified repository."""
    pass


class PlanNotFoundError(LookupError):
    """Raised when a referenced plan version does not exist."""
    pass


# ---------------------------------------------------------------------------
# State-Transition Rules Specification (Week 3 — §7.1 & §7.2)
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.CREATED: {TaskStatus.PLANNING, TaskStatus.CANCELLED, TaskStatus.FAILED},
    TaskStatus.PLANNING: {TaskStatus.PENDING_APPROVAL, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.PENDING_APPROVAL: {TaskStatus.APPROVED, TaskStatus.REJECTED, TaskStatus.PLANNING, TaskStatus.CANCELLED},
    TaskStatus.REJECTED: {TaskStatus.PLANNING, TaskStatus.CANCELLED},
    TaskStatus.APPROVED: {TaskStatus.WORKSPACE_SETUP, TaskStatus.PLANNING, TaskStatus.CANCELLED, TaskStatus.FAILED},
    TaskStatus.WORKSPACE_SETUP: {TaskStatus.EXECUTING, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.RECOVERY_REQUIRED},
    TaskStatus.EXECUTING: {TaskStatus.TESTING, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.RECOVERY_REQUIRED, TaskStatus.BLOCKED},
    TaskStatus.TESTING: {TaskStatus.VERIFYING, TaskStatus.REPAIRING, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.RECOVERY_REQUIRED},
    TaskStatus.REPAIRING: {TaskStatus.TESTING, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.RECOVERY_REQUIRED, TaskStatus.BLOCKED},
    TaskStatus.VERIFYING: {TaskStatus.READY_FOR_PUBLICATION, TaskStatus.REPAIRING, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.RECOVERY_REQUIRED, TaskStatus.BLOCKED},
    TaskStatus.READY_FOR_PUBLICATION: {TaskStatus.PUBLISHING, TaskStatus.VERIFYING, TaskStatus.CANCELLED, TaskStatus.BLOCKED},
    TaskStatus.PUBLISHING: {TaskStatus.DRAFT_PR_CREATED, TaskStatus.FAILED, TaskStatus.RECOVERY_REQUIRED},
    TaskStatus.DRAFT_PR_CREATED: set(),
    TaskStatus.FAILED: {TaskStatus.RECOVERY_REQUIRED, TaskStatus.PLANNING},
    TaskStatus.CANCELLED: set(),
    TaskStatus.RECOVERY_REQUIRED: {
        TaskStatus.PLANNING,
        TaskStatus.WORKSPACE_SETUP,
        TaskStatus.EXECUTING,
        TaskStatus.TESTING,
        TaskStatus.VERIFYING,
        TaskStatus.READY_FOR_PUBLICATION,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.BLOCKED: {
        TaskStatus.EXECUTING,
        TaskStatus.TESTING,
        TaskStatus.VERIFYING,
        TaskStatus.READY_FOR_PUBLICATION,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
}


# ---------------------------------------------------------------------------
# Sensitive Data Sanitization Patterns (Zero Credential Invariant)
# ---------------------------------------------------------------------------

_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_key", re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_\-]{20,}")),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("jwt_token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("db_connection_uri", re.compile(r"(?i)\b(postgres(?:ql)?|mysql|mongodb(?:\+srv)?):\/\/([^:\s]+):([^@\s]+)@")),
    (
        "credential_assignment",
        re.compile(
            r"(?i)(\b\w*(?:api_?key|secret|password|passwd|private_?key|access_?token|auth_?token|token)\w*[\x22\x27]?\s*[:=]\s*[\x22\x27])([^\x22\x27\s]{8,})([\x22\x27])"
        ),
    ),
)


def scrub_sensitive_text(text: Optional[str]) -> Optional[str]:
    """Redact raw secrets, tokens, and credentials from text before persistence."""
    if not text or not isinstance(text, str):
        return text
    redacted = text
    for name, pattern in _SECRET_PATTERNS:
        if name == "credential_assignment":
            redacted = pattern.sub(r"\1[REDACTED]\3", redacted)
        elif name == "db_connection_uri":
            redacted = pattern.sub(r"\1://\2:[REDACTED]@", redacted)
        else:
            redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def scrub_sensitive_data(val: Any) -> Any:
    """Recursively scrub sensitive credential strings in text, dicts, or lists."""
    if isinstance(val, str):
        return scrub_sensitive_text(val)
    elif isinstance(val, dict):
        return {k: scrub_sensitive_data(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [scrub_sensitive_data(item) for item in val]
    elif isinstance(val, tuple):
        return tuple(scrub_sensitive_data(item) for item in val)
    return val


def _ensure_uuid(val: Any) -> Optional[uuid.UUID]:
    if val is None:
        return None
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# TaskRepository Implementation
# ---------------------------------------------------------------------------


class TaskRepository:
    """Production-grade query and lifecycle repository for workflow automation."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # -----------------------------------------------------------------------
    # Task Lifecycle & Intake
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
    ) -> Task:
        """Create and persist a new workflow task with source and finding traceability."""
        repo_uuid = _ensure_uuid(repository_id)
        if not repo_uuid:
            raise ValueError("A valid repository_id is required.")

        user_uuid = _ensure_uuid(user_id)
        finding_uuid = _ensure_uuid(finding_id)

        # Validate finding ownership if supplied
        if finding_uuid:
            finding = self.session.execute(
                select(AnalysisFinding).where(
                    AnalysisFinding.id == finding_uuid,
                    AnalysisFinding.repository_id == repo_uuid,
                )
            ).scalar_one_or_none()
            if not finding:
                raise ValueError("Referenced finding does not belong to this repository.")

        clean_metadata = scrub_sensitive_data(source_metadata) if source_metadata else None
        source_type_val = source_type.value if isinstance(source_type, TaskSourceType) else str(source_type)

        task = Task(
            id=uuid.uuid4(),
            repository_id=repo_uuid,
            user_id=user_uuid,
            title=title.strip(),
            description=scrub_sensitive_text(description),
            status=TaskStatus.CREATED.value,
            source_type=source_type_val,
            source_id=source_id,
            source_metadata=clean_metadata,
            finding_id=finding_uuid,
            base_revision=base_revision,
            plan_version=1,
            approved_plan_version=None,
            repair_attempts_used=0,
            repair_attempts_max=3,
        )
        self.session.add(task)
        self.session.flush()

        # Emit initial timeline event
        event_type = (
            TaskEventType.ISSUE_IMPORTED.value
            if source_type_val == TaskSourceType.GITHUB_ISSUE.value
            else TaskEventType.TASK_CREATED.value
        )
        self.record_event(
            task_id=task.id,
            repository_id=repo_uuid,
            event_type=event_type,
            event_data={
                "title": task.title,
                "source_type": task.source_type,
                "source_id": task.source_id,
                "finding_id": str(task.finding_id) if task.finding_id else None,
                "base_revision": task.base_revision,
            },
            user_id=user_uuid,
        )

        self.session.commit()
        self.session.refresh(task)
        return task

    def get_task(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
    ) -> Optional[Task]:
        """Fetch task enforcing strict multi-tenant repository isolation."""
        t_uuid = _ensure_uuid(task_id)
        r_uuid = _ensure_uuid(repository_id)
        if not t_uuid or not r_uuid:
            return None

        stmt = (
            select(Task)
            .where(Task.id == t_uuid, Task.repository_id == r_uuid)
            .options(
                selectinload(Task.plans),
                selectinload(Task.approvals),
                selectinload(Task.workspace),
                selectinload(Task.repair_attempts),
                selectinload(Task.verification_results),
                selectinload(Task.pull_request),
            )
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list_tasks(
        self,
        repository_id: uuid.UUID | str,
        status: Optional[str] = None,
        source_type: Optional[str] = None,
        user_id: Optional[uuid.UUID | str] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> Tuple[List[Task], int]:
        """Retrieve paginated tasks for repository dashboard ordered newest-first."""
        r_uuid = _ensure_uuid(repository_id)
        if not r_uuid:
            return [], 0

        query = select(Task).where(Task.repository_id == r_uuid)
        count_query = select(func.count(Task.id)).where(Task.repository_id == r_uuid)

        if status:
            query = query.where(Task.status == status)
            count_query = count_query.where(Task.status == status)

        if source_type:
            query = query.where(Task.source_type == source_type)
            count_query = count_query.where(Task.source_type == source_type)

        u_uuid = _ensure_uuid(user_id)
        if u_uuid:
            query = query.where(Task.user_id == u_uuid)
            count_query = count_query.where(Task.user_id == u_uuid)

        total = self.session.execute(count_query).scalar_one()
        stmt = query.order_by(desc(Task.created_at)).offset(offset).limit(limit)
        results = list(self.session.execute(stmt).scalars().all())
        return results, total

    def transition_status(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        new_status: TaskStatus | str,
        user_id: Optional[uuid.UUID | str] = None,
        reason: Optional[str] = None,
    ) -> Task:
        """Enforce state transition preconditions and record transition event."""
        task = self.get_task(task_id, repository_id)
        if not task:
            raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")

        target_status_enum = TaskStatus(new_status) if isinstance(new_status, str) else new_status
        current_status_enum = TaskStatus(task.status)

        allowed_targets = VALID_TRANSITIONS.get(current_status_enum, set())
        if target_status_enum not in allowed_targets:
            raise InvalidStateTransitionError(
                f"Invalid state transition from {current_status_enum.value} to {target_status_enum.value}. "
                f"Permitted next states: {[s.value for s in allowed_targets]}"
            )

        # Precondition checks
        if target_status_enum == TaskStatus.EXECUTING:
            if not task.approved_plan_version:
                raise InvalidStateTransitionError("Cannot execute task: Plan has not been approved.")
            if not task.workspace:
                raise InvalidStateTransitionError("Cannot execute task: Workspace has not been initialized.")

        if target_status_enum == TaskStatus.REPAIRING:
            if task.repair_attempts_used >= task.repair_attempts_max:
                raise InvalidStateTransitionError("Cannot enter repair state: Retry budget is exhausted.")

        old_status = task.status
        task.status = target_status_enum.value
        task.updated_at = datetime.now(timezone.utc)
        self.session.flush()

        self.record_event(
            task_id=task.id,
            repository_id=task.repository_id,
            event_type=TaskEventType.STATE_TRANSITIONED.value,
            event_data={
                "from_status": old_status,
                "to_status": target_status_enum.value,
                "reason": scrub_sensitive_text(reason),
            },
            user_id=user_id,
        )

        self.session.commit()
        self.session.refresh(task)
        return task

    # -----------------------------------------------------------------------
    # Plan Management & Approval
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
    ) -> TaskPlan:
        """Create and version a structured implementation plan, invalidating stale approvals."""
        task = self.get_task(task_id, repository_id)
        if not task:
            raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")

        # Compute next version number
        highest_v = (
            self.session.execute(
                select(func.max(TaskPlan.version)).where(TaskPlan.task_id == task.id)
            ).scalar_one_or_none()
            or 0
        )
        new_version = highest_v + 1
        rev = base_revision or task.base_revision

        plan = TaskPlan(
            id=uuid.uuid4(),
            task_id=task.id,
            version=new_version,
            base_revision=rev,
            summary=summary.strip(),
            problem_statement=scrub_sensitive_text(problem_statement),
            steps=scrub_sensitive_data(steps),
            expected_files=expected_files,
            tests_to_run=tests_to_run,
            validation_strategy=scrub_sensitive_text(validation_strategy),
            risks=risks,
            status=TaskPlanStatus.PROPOSED.value,
        )
        self.session.add(plan)

        # Update task version and invalidate existing approvals on plan change
        task.plan_version = new_version
        if task.approved_plan_version is not None:
            task.approved_plan_version = None

        if task.status in (TaskStatus.CREATED.value, TaskStatus.PLANNING.value):
            task.status = TaskStatus.PENDING_APPROVAL.value

        self.session.flush()

        self.record_event(
            task_id=task.id,
            repository_id=task.repository_id,
            event_type=TaskEventType.PLAN_GENERATED.value,
            event_data={
                "plan_version": new_version,
                "summary": plan.summary,
                "step_count": len(steps),
                "base_revision": rev,
            },
        )

        self.session.commit()
        self.session.refresh(plan)
        return plan

    def approve_plan(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        plan_version: int,
        user_id: Optional[uuid.UUID | str] = None,
        feedback: Optional[str] = None,
    ) -> TaskApproval:
        """Record an immutable plan approval and advance task to APPROVED."""
        task = self.get_task(task_id, repository_id)
        if not task:
            raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")

        plan = self.session.execute(
            select(TaskPlan).where(
                TaskPlan.task_id == task.id,
                TaskPlan.version == plan_version,
            )
        ).scalar_one_or_none()
        if not plan:
            raise PlanNotFoundError(f"Plan version {plan_version} does not exist for task {task_id}")

        approval = TaskApproval(
            id=uuid.uuid4(),
            task_id=task.id,
            plan_version=plan_version,
            user_id=_ensure_uuid(user_id),
            decision=ApprovalDecision.APPROVED.value,
            feedback=scrub_sensitive_text(feedback),
        )
        self.session.add(approval)

        plan.status = TaskPlanStatus.APPROVED.value
        task.approved_plan_version = plan_version
        task.status = TaskStatus.APPROVED.value
        self.session.flush()

        self.record_event(
            task_id=task.id,
            repository_id=task.repository_id,
            event_type=TaskEventType.PLAN_APPROVED.value,
            event_data={
                "plan_version": plan_version,
                "approver_id": str(user_id) if user_id else None,
                "decision": approval.decision,
            },
            user_id=user_id,
        )

        self.session.commit()
        self.session.refresh(approval)
        return approval

    def reject_plan(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        plan_version: int,
        user_id: Optional[uuid.UUID | str] = None,
        feedback: Optional[str] = None,
    ) -> TaskApproval:
        """Record an immutable plan rejection and transition task to REJECTED."""
        task = self.get_task(task_id, repository_id)
        if not task:
            raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")

        plan = self.session.execute(
            select(TaskPlan).where(
                TaskPlan.task_id == task.id,
                TaskPlan.version == plan_version,
            )
        ).scalar_one_or_none()
        if not plan:
            raise PlanNotFoundError(f"Plan version {plan_version} does not exist for task {task_id}")

        approval = TaskApproval(
            id=uuid.uuid4(),
            task_id=task.id,
            plan_version=plan_version,
            user_id=_ensure_uuid(user_id),
            decision=ApprovalDecision.REJECTED.value,
            feedback=scrub_sensitive_text(feedback),
        )
        self.session.add(approval)

        plan.status = TaskPlanStatus.REJECTED.value
        task.approved_plan_version = None
        task.status = TaskStatus.REJECTED.value
        self.session.flush()

        self.record_event(
            task_id=task.id,
            repository_id=task.repository_id,
            event_type=TaskEventType.PLAN_REJECTED.value,
            event_data={
                "plan_version": plan_version,
                "approver_id": str(user_id) if user_id else None,
                "feedback": approval.feedback,
            },
            user_id=user_id,
        )

        self.session.commit()
        self.session.refresh(approval)
        return approval

    # -----------------------------------------------------------------------
    # Checkpoints & Failure Recovery
    # -----------------------------------------------------------------------

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

    # -----------------------------------------------------------------------
    # Bounded Repair Accounting
    # -----------------------------------------------------------------------

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

    # -----------------------------------------------------------------------
    # Workspace & Tool Invocations
    # -----------------------------------------------------------------------

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

    def record_tool_invocation(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        tool_name: str,
        arguments: Optional[dict[str, Any]] = None,
        status: ToolInvocationStatus | str = ToolInvocationStatus.COMPLETED,
        duration_ms: Optional[int] = None,
        output_summary: Optional[str] = None,
    ) -> ToolInvocation:
        """Record a validated tool invocation."""
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
        )
        self.session.add(inv)
        self.session.flush()

        self.record_event(
            task_id=task.id,
            repository_id=task.repository_id,
            event_type=TaskEventType.TOOL_INVOKED.value,
            event_data={"tool_name": tool_name, "status": status_val, "duration_ms": duration_ms},
        )
        self.session.commit()
        self.session.refresh(inv)
        return inv

    # -----------------------------------------------------------------------
    # Test Runs & Verification Results
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
        """Record independent verification outcome strictly bound to verified revision."""
        task = self.get_task(task_id, repository_id)
        if not task:
            raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")

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
        self.session.flush()

        self.record_event(
            task_id=task.id,
            repository_id=task.repository_id,
            event_type=TaskEventType.VERIFICATION_COMPLETED.value,
            event_data={
                "verified_revision": verified_revision,
                "status": status_val,
                "blocking_count": len(blocking_findings or []),
            },
        )
        self.session.commit()
        self.session.refresh(res)
        return res

    # -----------------------------------------------------------------------
    # Pull Requests & Event Timeline
    # -----------------------------------------------------------------------

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
    ) -> TaskPullRequest:
        """Record published Draft PR and advance task to DRAFT_PR_CREATED."""
        task = self.get_task(task_id, repository_id)
        if not task:
            raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")

        pr = TaskPullRequest(
            id=uuid.uuid4(),
            task_id=task.id,
            repository_id=task.repository_id,
            github_pr_id=github_pr_id,
            pr_number=pr_number,
            pr_url=pr_url,
            base_branch=base_branch,
            head_branch=head_branch,
            head_sha=head_sha,
            is_draft=is_draft,
            title=title.strip(),
            body=scrub_sensitive_text(body),
        )
        self.session.add(pr)

        task.status = TaskStatus.DRAFT_PR_CREATED.value
        self.session.flush()

        self.record_event(
            task_id=task.id,
            repository_id=task.repository_id,
            event_type=TaskEventType.DRAFT_PR_CREATED.value,
            event_data={
                "pr_url": pr_url,
                "pr_number": pr_number,
                "base_branch": base_branch,
                "head_branch": head_branch,
                "head_sha": head_sha,
            },
        )
        self.session.commit()
        self.session.refresh(pr)
        return pr

    def record_event(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        event_type: str,
        event_data: Optional[dict[str, Any]] = None,
        user_id: Optional[uuid.UUID | str] = None,
    ) -> TaskEvent:
        """Append ordered timeline audit event."""
        t_uuid = _ensure_uuid(task_id)
        u_uuid = _ensure_uuid(user_id)

        event = TaskEvent(
            id=uuid.uuid4(),
            task_id=t_uuid,
            event_type=event_type,
            event_data=scrub_sensitive_data(event_data),
            user_id=u_uuid,
        )
        self.session.add(event)
        self.session.flush()
        return event

    def get_task_timeline(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
    ) -> List[TaskEvent]:
        """Fetch all audit events for a task in ascending chronological order."""
        t_uuid = _ensure_uuid(task_id)
        r_uuid = _ensure_uuid(repository_id)
        if not t_uuid or not r_uuid:
            return []

        stmt = (
            select(TaskEvent)
            .join(Task, Task.id == TaskEvent.task_id)
            .where(TaskEvent.task_id == t_uuid, Task.repository_id == r_uuid)
            .order_by(TaskEvent.created_at.asc())
        )
        return list(self.session.execute(stmt).scalars().all())


__all__ = [
    "TaskRepository",
    "InvalidStateTransitionError",
    "TaskNotFoundError",
    "PlanNotFoundError",
    "VALID_TRANSITIONS",
    "scrub_sensitive_text",
    "scrub_sensitive_data",
]
