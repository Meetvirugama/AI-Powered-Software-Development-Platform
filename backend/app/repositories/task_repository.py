"""Task and Workflow Persistence Repository (Week 3 — Day 1 & Day 2).

Merged from:
- Om (Week 3 Day 1 Persistence, Checkpoints, Bounded Repair & Recovery — F39)
- Yug & Om (Week 3 Day 1-2 Task Intake, GitHub Issues, Plans, Approvals & Governance — F31, F32)

Responsibilities:
1. Persist and deduplicate GitHub issues by `(repository_id, issue_number)`.
2. Persist `Task` (`AgentTask`) records with source traceability (issue, bug finding, review finding, user prompt).
3. Enforce valid state transitions (`VALID_TRANSITIONS` / `can_transition`) at the persistence/service boundary (§7.1, §7.2).
4. Persist versioned `TaskPlan` items and automatically invalidate prior approvals when a plan or `base_revision` changes materially.
5. Record immutable `TaskApproval` entries and ordered `TaskEvent` audit timeline events.
6. Checkpoint management with automated secret scrubbing (Zero Credential Invariant).
7. Bounded repair loop accounting (max 3 task-level attempts ceiling).
8. Tool invocation, test run, verification result, and draft pull request persistence.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional, Sequence, Tuple

from sqlalchemy import delete, desc, func, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import APIError, ErrorCode
from app.core.secret_redaction import redact, redact_obj
from app.models.analysis_finding import AnalysisFinding
from app.models.task import (
    AgentTask,
    ApprovalDecision,
    ExecutionStatus,
    GitHubIssue,
    RepairAttempt,
    RepairResult,
    Task,
    TaskApproval,
    TaskApprovalRecord,
    TaskCheckpoint,
    TaskEvent,
    TaskEventRecord,
    TaskEventType,
    TaskExecution,
    TaskPlan,
    TaskPlanRecord,
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
from app.schemas.plan import PlannerSchema
from app.schemas.task import TaskIntakePayload, can_transition


class InvalidStateTransitionError(APIError, ValueError):
    """Raised when an illegal lifecycle state transition is requested."""

    def __init__(
        self,
        message: str = "Invalid state transition.",
        status_code: int = 409,
        code: str = ErrorCode.INVALID_STATE_TRANSITION,
        *,
        retryable: bool = False,
    ):
        APIError.__init__(self, status_code=status_code, code=code, message=message, retryable=retryable)
        ValueError.__init__(self, message)


class TaskNotFoundError(APIError, LookupError):
    """Raised when a task cannot be found in the specified repository."""

    def __init__(
        self,
        message: str = "Task not found.",
        status_code: int = 404,
        code: str = ErrorCode.TASK_NOT_FOUND,
        *,
        retryable: bool = False,
    ):
        APIError.__init__(self, status_code=status_code, code=code, message=message, retryable=retryable)
        LookupError.__init__(self, message)


class PlanNotFoundError(APIError, LookupError):
    """Raised when a referenced plan version does not exist."""

    def __init__(
        self,
        message: str = "Plan not found.",
        status_code: int = 404,
        code: str = ErrorCode.NOT_FOUND,
        *,
        retryable: bool = False,
    ):
        APIError.__init__(self, status_code=status_code, code=code, message=message, retryable=retryable)
        LookupError.__init__(self, message)


# ---------------------------------------------------------------------------
# State-Transition Rules Specification (Week 3 — §7.1 & §7.2)
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.CREATED: {TaskStatus.PLANNING, TaskStatus.CANCELLED, TaskStatus.FAILED, TaskStatus.BLOCKED},
    TaskStatus.PLANNING: {TaskStatus.PENDING_APPROVAL, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.BLOCKED},
    TaskStatus.PENDING_APPROVAL: {TaskStatus.APPROVED, TaskStatus.REJECTED, TaskStatus.PLANNING, TaskStatus.CANCELLED},
    TaskStatus.REJECTED: {TaskStatus.PLANNING, TaskStatus.CANCELLED},
    TaskStatus.APPROVED: {TaskStatus.WORKSPACE_SETUP, TaskStatus.EXECUTING, TaskStatus.PLANNING, TaskStatus.CANCELLED, TaskStatus.FAILED, TaskStatus.BLOCKED},
    TaskStatus.WORKSPACE_SETUP: {TaskStatus.EXECUTING, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.RECOVERY_REQUIRED, TaskStatus.BLOCKED},
    TaskStatus.EXECUTING: {TaskStatus.TESTING, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.RECOVERY_REQUIRED, TaskStatus.BLOCKED},
    TaskStatus.TESTING: {TaskStatus.VERIFYING, TaskStatus.REPAIRING, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.RECOVERY_REQUIRED, TaskStatus.BLOCKED},
    TaskStatus.REPAIRING: {TaskStatus.TESTING, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.RECOVERY_REQUIRED, TaskStatus.BLOCKED},
    TaskStatus.VERIFYING: {TaskStatus.READY_FOR_PUBLICATION, TaskStatus.REPAIRING, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.RECOVERY_REQUIRED, TaskStatus.BLOCKED},
    TaskStatus.READY_FOR_PUBLICATION: {TaskStatus.PUBLISHING, TaskStatus.VERIFYING, TaskStatus.CANCELLED, TaskStatus.BLOCKED},
    TaskStatus.PUBLISHING: {TaskStatus.DRAFT_PR_CREATED, TaskStatus.FAILED, TaskStatus.RECOVERY_REQUIRED, TaskStatus.BLOCKED},
    TaskStatus.DRAFT_PR_CREATED: set(),
    TaskStatus.FAILED: {TaskStatus.RECOVERY_REQUIRED, TaskStatus.PLANNING},
    TaskStatus.CANCELLED: set(),
    TaskStatus.RECOVERY_REQUIRED: {
        TaskStatus.PLANNING,
        TaskStatus.APPROVED,
        TaskStatus.WORKSPACE_SETUP,
        TaskStatus.EXECUTING,
        TaskStatus.TESTING,
        TaskStatus.VERIFYING,
        TaskStatus.READY_FOR_PUBLICATION,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.BLOCKED: {
        TaskStatus.PLANNING,
        TaskStatus.PENDING_APPROVAL,
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
    redacted = redact(text)
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
    return redact_obj(val) if val is not None else None


def _ensure_uuid(val: Any) -> Optional[uuid.UUID]:
    if val is None:
        return None
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except (ValueError, TypeError):
        return None


_to_uuid = _ensure_uuid


# ---------------------------------------------------------------------------
# TaskRepository Implementation
# ---------------------------------------------------------------------------

class TaskRepository:
    """High-performance database query and persistence layer for Week 3 workflow entities."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.db = session

    # ------------------------------------------------------------------
    # 1. GitHub Issues (F31)
    # ------------------------------------------------------------------

    def get_issue_by_number(
        self,
        repository_id: uuid.UUID | str,
        issue_number: int,
    ) -> Optional[GitHubIssue]:
        """Find an existing GitHubIssue by `(repository_id, issue_number)`."""
        repo_uuid = _ensure_uuid(repository_id)
        if repo_uuid is None:
            return None
        stmt = select(GitHubIssue).where(
            GitHubIssue.repository_id == repo_uuid,
            GitHubIssue.issue_number == int(issue_number),
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def upsert_github_issue(
        self,
        *,
        repository_id: uuid.UUID | str,
        issue_number: int,
        title: str,
        body: str = "",
        state: str = "open",
        labels: Sequence[str] | None = None,
        html_url: str,
        author: str | None = None,
        origin_finding_id: uuid.UUID | str | None = None,
    ) -> tuple[GitHubIssue, bool]:
        """Insert or update a GitHubIssue record. Returns `(issue, created_new)`."""
        repo_uuid = _ensure_uuid(repository_id)
        if repo_uuid is None:
            raise ValueError(f"Invalid repository_id: {repository_id}")

        finding_uuid = _ensure_uuid(origin_finding_id)
        safe_title = scrub_sensitive_text((title or "").strip()) or f"Issue #{issue_number}"
        safe_body = scrub_sensitive_text(body or "") or ""
        safe_labels = [scrub_sensitive_text(str(lbl).strip()) for lbl in (labels or []) if str(lbl).strip()]
        safe_url = (html_url or "").strip()

        existing = self.get_issue_by_number(repo_uuid, issue_number)
        if existing is not None:
            existing.title = safe_title
            existing.body = safe_body
            existing.state = state or existing.state
            existing.labels = safe_labels
            if safe_url:
                existing.html_url = safe_url
            if author is not None:
                existing.author = author
            if finding_uuid is not None and existing.origin_finding_id is None:
                existing.origin_finding_id = finding_uuid
            self.session.commit()
            self.session.refresh(existing)
            return existing, False

        issue = GitHubIssue(
            repository_id=repo_uuid,
            issue_number=int(issue_number),
            title=safe_title,
            body=safe_body,
            state=state or "open",
            labels=safe_labels,
            html_url=safe_url,
            author=author,
            origin_finding_id=finding_uuid,
        )
        self.session.add(issue)
        self.session.commit()
        self.session.refresh(issue)
        return issue, True

    def list_issues_by_repository(
        self,
        repository_id: uuid.UUID | str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[GitHubIssue]:
        """List persisted GitHub issues for a repository, ordered by issue_number desc."""
        repo_uuid = _ensure_uuid(repository_id)
        if repo_uuid is None:
            return []
        stmt = (
            select(GitHubIssue)
            .where(GitHubIssue.repository_id == repo_uuid)
            .order_by(GitHubIssue.issue_number.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def get_task_by_issue(
        self,
        repository_id: uuid.UUID | str,
        github_issue_id: uuid.UUID | str,
    ) -> Optional[Task]:
        """Return an existing active task linked to `(repository_id, github_issue_id)`."""
        repo_uuid = _ensure_uuid(repository_id)
        issue_uuid = _ensure_uuid(github_issue_id)
        if repo_uuid is None or issue_uuid is None:
            return None
        stmt = (
            select(Task)
            .where(
                Task.repository_id == repo_uuid,
                Task.github_issue_id == issue_uuid,
            )
            .order_by(Task.created_at.desc())
            .options(
                selectinload(Task.plans),
                selectinload(Task.approvals),
                selectinload(Task.events),
                selectinload(Task.workspace),
                selectinload(Task.executions),
            )
        )
        return self.session.scalars(stmt).first()

    # ------------------------------------------------------------------
    # 2. Tasks & Intake (F31, F32, F39)
    # ------------------------------------------------------------------

    def create_task(
        self,
        repository_id: uuid.UUID | str | None = None,
        title: Optional[str] = None,
        source_type: TaskSourceType | str = TaskSourceType.DIRECT,
        description: Optional[str] = None,
        source_id: Optional[str] = None,
        source_metadata: Optional[dict[str, Any]] = None,
        finding_id: Optional[uuid.UUID | str] = None,
        user_id: Optional[uuid.UUID | str] = None,
        base_revision: Optional[str] = None,
        *,
        intake: Optional[TaskIntakePayload] = None,
        github_issue_id: uuid.UUID | str | None = None,
        origin_finding_id: uuid.UUID | str | None = None,
        initial_event_type: Optional[str] = None,
        initial_event_summary: Optional[str] = None,
    ) -> Task:
        """Create and persist a new workflow task with source and finding traceability."""
        if intake is not None:
            repo_val = intake.repository_id
            title_val = intake.title
            desc_val = intake.description
            source_type_val = intake.source.type
            source_dict = scrub_sensitive_data(intake.source.model_dump(mode="json"))
            source_metadata = source_dict if isinstance(source_dict, dict) else {}
            reqs_list = scrub_sensitive_data([r.model_dump(mode="json") for r in intake.requirements])
            asms_list = scrub_sensitive_data([a.model_dump(mode="json") for a in intake.assumptions])
            csts_list = scrub_sensitive_data([c.model_dump(mode="json") for c in intake.constraints])
            base_rev_val = intake.base_revision or intake.source.base_revision or base_revision or "main"
            finding_val = origin_finding_id or intake.source.finding_id or finding_id
            issue_val = github_issue_id
            source_id_val = source_id or (str(intake.source.issue_number) if intake.source.issue_number else None)
        else:
            repo_val = repository_id
            title_val = title
            desc_val = description
            source_type_val = source_type.value if isinstance(source_type, TaskSourceType) else str(source_type)
            reqs_list = []
            asms_list = []
            csts_list = []
            base_rev_val = base_revision or "main"
            finding_val = finding_id or origin_finding_id
            issue_val = github_issue_id
            source_id_val = source_id

        repo_uuid = _ensure_uuid(repo_val)
        if not repo_uuid:
            raise ValueError("A valid repository_id is required.")

        user_uuid = _ensure_uuid(user_id)
        finding_uuid = _ensure_uuid(finding_val)
        issue_uuid = _ensure_uuid(issue_val)

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
        safe_title = scrub_sensitive_text((title_val or "").strip()) or "Untitled Task"
        safe_desc = scrub_sensitive_text(desc_val)

        task = Task(
            id=uuid.uuid4(),
            repository_id=repo_uuid,
            user_id=user_uuid,
            github_issue_id=issue_uuid,
            finding_id=finding_uuid,
            origin_finding_id=finding_uuid,
            title=safe_title,
            description=safe_desc,
            status=TaskStatus.CREATED.value,
            source_type=source_type_val,
            source_id=source_id_val,
            source_metadata=clean_metadata,
            source_ref=clean_metadata or {},
            requirements=reqs_list if isinstance(reqs_list, list) else [],
            assumptions=asms_list if isinstance(asms_list, list) else [],
            constraints=csts_list if isinstance(csts_list, list) else [],
            base_revision=base_rev_val,
            plan_version=1,
            approved_plan_version=None,
            repair_attempts_used=0,
            repair_attempts_max=3,
        )
        self.session.add(task)
        self.session.flush()

        evt_type = (
            initial_event_type
            or (
                TaskEventType.ISSUE_IMPORTED.value
                if source_type_val in (TaskSourceType.GITHUB_ISSUE.value, "GITHUB_ISSUE")
                else TaskEventType.TASK_CREATED.value
            )
        )
        self.record_event(
            task_id=task.id,
            repository_id=repo_uuid,
            event_type=evt_type,
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
        repository_id: Optional[uuid.UUID | str] = None,
    ) -> Optional[Task]:
        """Fetch a task with eager-loaded related entities, optionally isolated to a repository."""
        t_uuid = _ensure_uuid(task_id)
        if not t_uuid:
            return None

        stmt = (
            select(Task)
            .where(Task.id == t_uuid)
            .options(
                selectinload(Task.plans),
                selectinload(Task.approvals),
                selectinload(Task.events),
                selectinload(Task.workspace),
                selectinload(Task.executions),
            )
        )
        if repository_id is not None:
            r_uuid = _ensure_uuid(repository_id)
            if not r_uuid:
                return None
            stmt = stmt.where(Task.repository_id == r_uuid)

        return self.session.execute(stmt).scalar_one_or_none()

    def get_task_for_user(
        self,
        task_id: uuid.UUID | str,
        user_id: uuid.UUID | str,
    ) -> Optional[Task]:
        """Fetch a task verifying user ownership."""
        t_uuid = _ensure_uuid(task_id)
        u_uuid = _ensure_uuid(user_id)
        if not t_uuid or not u_uuid:
            return None

        stmt = (
            select(Task)
            .where(Task.id == t_uuid, Task.user_id == u_uuid)
            .options(
                selectinload(Task.plans),
                selectinload(Task.approvals),
                selectinload(Task.events),
                selectinload(Task.workspace),
                selectinload(Task.executions),
            )
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list_tasks(
        self,
        repository_id: uuid.UUID | str,
        status: Optional[TaskStatus | str] = None,
        source_type: Optional[TaskSourceType | str] = None,
        user_id: Optional[uuid.UUID | str] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> Tuple[List[Task], int]:
        """List tasks filtered by repository, status, and source type, returning (items, total)."""
        repo_uuid = _ensure_uuid(repository_id)
        if not repo_uuid:
            return [], 0

        filters = [Task.repository_id == repo_uuid]

        if status:
            status_val = status.value if isinstance(status, TaskStatus) else str(status)
            filters.append(Task.status == status_val)

        if source_type:
            src_val = source_type.value if isinstance(source_type, TaskSourceType) else str(source_type)
            filters.append(Task.source_type == src_val)

        if user_id:
            u_uuid = _ensure_uuid(user_id)
            if u_uuid:
                filters.append(Task.user_id == u_uuid)

        count_stmt = select(func.count(Task.id)).where(*filters)
        total = self.session.scalar(count_stmt) or 0

        stmt = (
            select(Task)
            .where(*filters)
            .order_by(desc(Task.created_at))
            .offset(offset)
            .limit(limit)
            .options(
                selectinload(Task.plans),
                selectinload(Task.approvals),
                selectinload(Task.events),
            )
        )
        items = list(self.session.scalars(stmt).all())
        return items, int(total)

    def list_tasks_for_user(
        self,
        user_id: uuid.UUID | str,
        *,
        repository_id: uuid.UUID | str | None = None,
        status: Optional[TaskStatus | str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Task], int]:
        """List tasks owned by a user with pagination and total count."""
        u_uuid = _ensure_uuid(user_id)
        if not u_uuid:
            return [], 0

        filters = [Task.user_id == u_uuid]
        if repository_id is not None:
            r_uuid = _ensure_uuid(repository_id)
            if r_uuid:
                filters.append(Task.repository_id == r_uuid)
        if status is not None:
            status_val = status.value if isinstance(status, TaskStatus) else str(status)
            filters.append(Task.status == status_val)

        count_stmt = select(func.count(Task.id)).where(*filters)
        total = self.session.scalar(count_stmt) or 0

        stmt = (
            select(Task)
            .where(*filters)
            .order_by(Task.created_at.desc())
            .offset(offset)
            .limit(limit)
            .options(
                selectinload(Task.plans),
                selectinload(Task.approvals),
                selectinload(Task.events),
            )
        )
        items = list(self.session.scalars(stmt).all())
        return items, int(total)

    def transition_status(
        self,
        task_or_id: uuid.UUID | str | Task,
        repository_id_or_status: uuid.UUID | str | TaskStatus,
        new_status: TaskStatus | str | None = None,
        user_id: Optional[uuid.UUID | str] = None,
        reason: Optional[str] = None,
        *,
        actor_id: uuid.UUID | str | None = None,
        event_type: str | None = None,
        summary: str | None = None,
        payload: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> Task:
        """Validate and execute a task state transition, recording an audit event."""
        if isinstance(task_or_id, Task):
            task = task_or_id
            target_status_raw = repository_id_or_status
            u_id = actor_id or user_id
        else:
            if new_status is not None:
                task_id = task_or_id
                repo_id = repository_id_or_status
                target_status_raw = new_status
                u_id = user_id or actor_id
                task = self.get_task(task_id, repo_id)
                if not task:
                    raise TaskNotFoundError(f"Task {task_id} not found in repository {repo_id}")
            else:
                task_id = task_or_id
                target_status_raw = repository_id_or_status
                u_id = user_id or actor_id
                task = self.get_task(task_id)
                if not task:
                    raise TaskNotFoundError(f"Task {task_id} not found")

        target_status_enum = TaskStatus(target_status_raw) if isinstance(target_status_raw, str) else target_status_raw
        current_status_enum = TaskStatus(task.status)

        allowed_targets = VALID_TRANSITIONS.get(current_status_enum, set())
        if target_status_enum not in allowed_targets:
            raise InvalidStateTransitionError(
                f"Invalid state transition from {current_status_enum.value} to {target_status_enum.value}. "
                f"Permitted next states: {[s.value for s in allowed_targets]}"
            )

        # Precondition checks (§7.2)
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

        # Emit audit event
        safe_reason = scrub_sensitive_text(reason)
        event_dict = {
            "from_status": old_status,
            "to_status": target_status_enum.value,
        }
        if safe_reason:
            event_dict["reason"] = safe_reason
        if payload:
            event_dict.update(scrub_sensitive_data(payload))

        evt_type = event_type or TaskEventType.STATE_TRANSITIONED.value
        safe_summary = scrub_sensitive_text(summary) or f"Task transitioned from {old_status} to {target_status_enum.value}."

        self.record_event(
            task_id=task.id,
            repository_id=task.repository_id,
            event_type=evt_type,
            event_data=event_dict,
            user_id=u_id,
            from_status=old_status,
            to_status=target_status_enum.value,
            summary=safe_summary,
        )

        if commit:
            self.session.commit()
            self.session.refresh(task)
        return task

    # ------------------------------------------------------------------
    # 3. Plan Management & Approval Invalidation (F32, F39)
    # ------------------------------------------------------------------

    def save_plan(
        self,
        task_id: uuid.UUID | str | Task | None = None,
        repository_id: uuid.UUID | str | None = None,
        summary: Optional[str] = None,
        steps: Optional[list[dict[str, Any]]] = None,
        base_revision: Optional[str] = None,
        problem_statement: Optional[str] = None,
        expected_files: Optional[list[str]] = None,
        tests_to_run: Optional[list[str]] = None,
        validation_strategy: Optional[str | list[str]] = None,
        risks: Optional[list[str] | list[dict[str, Any]]] = None,
        *,
        task: Optional[Task] = None,
        plan_schema: Optional[PlannerSchema] = None,
        actor_id: uuid.UUID | str | None = None,
    ) -> TaskPlan:
        """Create and version a structured implementation plan, invalidating stale approvals."""
        target_task: Optional[Task] = None
        if task is not None:
            target_task = task
        elif isinstance(task_id, Task):
            target_task = task_id
        elif task_id is not None:
            target_task = self.get_task(task_id, repository_id)

        if target_task is None:
            raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")

        # Plan schema path (Sukun Planner / Week 3 Day 2 intake)
        if plan_schema is not None:
            # Enforce forbidden_files disjointness against task constraints
            forbidden_lower: dict[str, str] = {}
            for cst in target_task.constraints or []:
                if isinstance(cst, dict):
                    for f_path in cst.get("forbidden_files", []) or []:
                        forbidden_lower[str(f_path).lower()] = str(f_path)

            violating_files = [
                f for f in plan_schema.expected_files if f.lower() in forbidden_lower
            ]
            if violating_files:
                raise APIError(
                    400,
                    ErrorCode.POLICY_VIOLATION,
                    f"Generated plan modifies forbidden protected file(s): {', '.join(sorted(set(violating_files)))}",
                )

            effective_base_rev = base_revision or target_task.base_revision
            new_hash = plan_schema.compute_plan_hash(effective_base_rev)

            existing_plans = self.list_plans(target_task.id)
            highest_v = existing_plans[0].plan_version if existing_plans else 0
            next_version = highest_v + 1

            curr_status = TaskStatus(target_task.status)
            if curr_status != TaskStatus.PLANNING:
                if not can_transition(curr_status, TaskStatus.PLANNING):
                    raise APIError(
                        409,
                        ErrorCode.INVALID_STATE_TRANSITION,
                        f"Cannot generate plan when task is in state '{curr_status.value}'.",
                    )
                target_task.status = TaskStatus.PLANNING.value

            prior_approved = target_task.approved_plan_version
            approval_invalidated = prior_approved is not None

            target_task.plan_version = next_version
            target_task.approved_plan_version = None
            if effective_base_rev:
                target_task.base_revision = effective_base_rev
                if isinstance(target_task.source_ref, dict):
                    updated_ref = dict(target_task.source_ref)
                    updated_ref["base_revision"] = effective_base_rev
                    target_task.source_ref = updated_ref

            plan_record = TaskPlan(
                id=uuid.uuid4(),
                task_id=target_task.id,
                version=next_version,
                base_revision=effective_base_rev,
                plan_hash=new_hash,
                summary=scrub_sensitive_text(plan_schema.summary),
                problem_statement=scrub_sensitive_text(plan_schema.problem_statement),
                assumptions=scrub_sensitive_data([a.model_dump(mode="json") for a in plan_schema.assumptions]),
                relevant_files=list(plan_schema.relevant_files),
                relevant_symbols=list(plan_schema.relevant_symbols),
                steps=scrub_sensitive_data([s.model_dump(mode="json") for s in plan_schema.steps]),
                expected_files=list(plan_schema.expected_files),
                tests_to_run=list(plan_schema.tests_to_run),
                validation_strategy=scrub_sensitive_text("; ".join(plan_schema.validation_strategy) if isinstance(plan_schema.validation_strategy, list) else plan_schema.validation_strategy),
                risks=scrub_sensitive_data([r.model_dump(mode="json") for r in plan_schema.risks]),
                required_permissions=list(plan_schema.required_permissions),
                resource_budget=plan_schema.resource_budget.model_dump(mode="json"),
                status=TaskPlanStatus.PENDING_APPROVAL.value,
            )
            self.session.add(plan_record)

            for old_p in existing_plans:
                if old_p.status in (TaskPlanStatus.PROPOSED.value, TaskPlanStatus.APPROVED.value, "PENDING_APPROVAL", "APPROVED"):
                    old_p.status = "SUPERSEDED"

            target_task.status = TaskStatus.PENDING_APPROVAL.value

            self.record_event(
                task_id=target_task.id,
                repository_id=target_task.repository_id,
                event_type=TaskEventType.PLAN_GENERATED.value,
                event_data={
                    "plan_version": next_version,
                    "plan_hash": new_hash,
                    "base_revision": effective_base_rev,
                    "steps_count": len(plan_schema.steps),
                    "approval_invalidated": approval_invalidated,
                    "prior_approved_plan_version": prior_approved,
                },
                user_id=actor_id,
                from_status=curr_status.value,
                to_status=TaskStatus.PENDING_APPROVAL.value,
                summary=(
                    f"Generated structured implementation plan v{next_version} ({len(plan_schema.steps)} steps)."
                    + (f" Previous approval for v{prior_approved} invalidated." if approval_invalidated else "")
                ),
            )
            self.session.commit()
            self.session.refresh(plan_record)
            self.session.refresh(target_task)
            return plan_record

        # Direct argument path (Om Day 1 Persistence)
        highest_v = (
            self.session.execute(
                select(func.max(TaskPlan.version)).where(TaskPlan.task_id == target_task.id)
            ).scalar_one_or_none()
            or 0
        )
        new_version = highest_v + 1
        rev = base_revision or target_task.base_revision

        validation_str = (
            "; ".join(validation_strategy)
            if isinstance(validation_strategy, list)
            else validation_strategy
        )

        plan = TaskPlan(
            id=uuid.uuid4(),
            task_id=target_task.id,
            version=new_version,
            base_revision=rev,
            summary=scrub_sensitive_text((summary or "").strip()),
            problem_statement=scrub_sensitive_text(problem_statement),
            steps=scrub_sensitive_data(steps or []),
            expected_files=expected_files or [],
            tests_to_run=tests_to_run or [],
            validation_strategy=scrub_sensitive_text(validation_str),
            risks=scrub_sensitive_data(risks) if isinstance(risks, list) else [],
            status=TaskPlanStatus.PROPOSED.value,
        )
        self.session.add(plan)

        target_task.plan_version = new_version
        if target_task.approved_plan_version is not None:
            target_task.approved_plan_version = None

        if target_task.status in (TaskStatus.CREATED.value, TaskStatus.PLANNING.value):
            target_task.status = TaskStatus.PENDING_APPROVAL.value

        self.session.flush()

        self.record_event(
            task_id=target_task.id,
            repository_id=target_task.repository_id,
            event_type=TaskEventType.PLAN_GENERATED.value,
            event_data={
                "plan_version": new_version,
                "summary": plan.summary,
                "step_count": len(steps or []),
                "base_revision": rev,
            },
            user_id=actor_id,
        )

        self.session.commit()
        self.session.refresh(plan)
        return plan

    def get_latest_plan(self, task_id: uuid.UUID | str) -> Optional[TaskPlan]:
        """Return the most recent plan version for a task."""
        t_uuid = _ensure_uuid(task_id)
        if t_uuid is None:
            return None
        stmt = (
            select(TaskPlan)
            .where(TaskPlan.task_id == t_uuid)
            .order_by(TaskPlan.version.desc())
        )
        return self.session.scalars(stmt).first()

    def get_plan_by_version(
        self,
        task_id: uuid.UUID | str,
        plan_version: int,
    ) -> Optional[TaskPlan]:
        """Return a specific version of a plan for a task."""
        t_uuid = _ensure_uuid(task_id)
        if t_uuid is None:
            return None
        stmt = select(TaskPlan).where(
            TaskPlan.task_id == t_uuid,
            TaskPlan.version == int(plan_version),
        )
        return self.session.scalars(stmt).first()

    def list_plans(self, task_id: uuid.UUID | str) -> list[TaskPlan]:
        """List all plan versions for a task, ordered by version descending."""
        t_uuid = _ensure_uuid(task_id)
        if t_uuid is None:
            return []
        stmt = (
            select(TaskPlan)
            .where(TaskPlan.task_id == t_uuid)
            .order_by(TaskPlan.version.desc())
        )
        return list(self.session.scalars(stmt).all())

    def approve_plan(
        self,
        task_id: uuid.UUID | str | Task | None = None,
        repository_id: uuid.UUID | str | None = None,
        plan_version: Optional[int] = None,
        user_id: Optional[uuid.UUID | str] = None,
        feedback: Optional[str] = None,
        *,
        task: Optional[Task] = None,
        approver_id: uuid.UUID | str | None = None,
        base_revision: str | None = None,
        comment: str | None = None,
    ) -> TaskApproval:
        """Record an immutable plan approval and advance task to APPROVED."""
        target_task: Optional[Task] = None
        if task is not None:
            target_task = task
        elif isinstance(task_id, Task):
            target_task = task_id
        elif task_id is not None:
            target_task = self.get_task(task_id, repository_id)

        if target_task is None:
            raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")

        effective_user_id = user_id or approver_id
        u_uuid = _ensure_uuid(effective_user_id)

        latest_plan = self.get_latest_plan(target_task.id)
        if latest_plan is None:
            raise APIError(
                409,
                ErrorCode.INVALID_STATE_TRANSITION,
                "Cannot approve task before an implementation plan has been generated.",
            )

        target_version = plan_version if plan_version is not None else latest_plan.plan_version

        if plan_version is not None and int(plan_version) != latest_plan.plan_version:
            plan_record = self.get_plan_by_version(target_task.id, plan_version)
            if not plan_record:
                raise PlanNotFoundError(f"Plan version {plan_version} does not exist for task {target_task.id}")
            raise APIError(
                409,
                ErrorCode.PLAN_VERSION_MISMATCH,
                f"Requested approval for plan_version {plan_version}, but current plan_version is {latest_plan.plan_version}.",
            )

        if base_revision is not None and latest_plan.base_revision and base_revision.strip() != latest_plan.base_revision:
            raise APIError(
                409,
                ErrorCode.PLAN_VERSION_MISMATCH,
                f"Base revision '{base_revision}' does not match plan base revision '{latest_plan.base_revision}'. Please re-plan.",
            )

        if target_task.base_revision and latest_plan.base_revision and target_task.base_revision != latest_plan.base_revision:
            raise APIError(
                409,
                ErrorCode.PLAN_VERSION_MISMATCH,
                "Task base revision has drifted from the plan base revision. Please generate a new plan version.",
            )

        curr_status = TaskStatus(target_task.status)
        if curr_status == TaskStatus.REJECTED:
            raise APIError(
                409,
                ErrorCode.INVALID_STATE_TRANSITION,
                "A rejected plan cannot be approved directly. Generate a revised plan first.",
            )

        safe_feedback = scrub_sensitive_text(feedback or comment)

        approval = TaskApproval(
            id=uuid.uuid4(),
            task_id=target_task.id,
            plan_id=latest_plan.id,
            plan_version=target_version,
            user_id=u_uuid,
            decision=ApprovalDecision.APPROVED.value,
            feedback=safe_feedback,
            plan_hash=latest_plan.plan_hash,
            base_revision=latest_plan.base_revision,
        )
        self.session.add(approval)

        latest_plan.status = TaskPlanStatus.APPROVED.value
        prev_status = target_task.status
        target_task.approved_plan_version = target_version
        target_task.status = TaskStatus.APPROVED.value
        self.session.flush()

        self.record_event(
            task_id=target_task.id,
            repository_id=target_task.repository_id,
            event_type=TaskEventType.PLAN_APPROVED.value,
            event_data={
                "plan_version": target_version,
                "plan_hash": latest_plan.plan_hash,
                "base_revision": latest_plan.base_revision,
                "decision": approval.decision,
                "comment": safe_feedback,
            },
            user_id=effective_user_id,
            from_status=prev_status,
            to_status=TaskStatus.APPROVED.value,
            summary=f"Plan v{target_version} approved by user.",
        )

        self.session.commit()
        self.session.refresh(approval)
        self.session.refresh(target_task)
        return approval

    def reject_plan(
        self,
        task_id: uuid.UUID | str | Task | None = None,
        repository_id: uuid.UUID | str | None = None,
        plan_version: Optional[int] = None,
        user_id: Optional[uuid.UUID | str] = None,
        feedback: Optional[str] = None,
        *,
        task: Optional[Task] = None,
        approver_id: uuid.UUID | str | None = None,
        reason: str | None = None,
    ) -> TaskApproval:
        """Reject the current pending implementation plan version."""
        target_task: Optional[Task] = None
        if task is not None:
            target_task = task
        elif isinstance(task_id, Task):
            target_task = task_id
        elif task_id is not None:
            target_task = self.get_task(task_id, repository_id)

        if target_task is None:
            raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")

        effective_user_id = user_id or approver_id
        u_uuid = _ensure_uuid(effective_user_id)

        latest_plan = self.get_latest_plan(target_task.id)
        if latest_plan is None:
            raise APIError(
                409,
                ErrorCode.INVALID_STATE_TRANSITION,
                "Cannot reject task before an implementation plan has been generated.",
            )

        target_version = plan_version if plan_version is not None else latest_plan.plan_version

        if plan_version is not None and int(plan_version) != latest_plan.plan_version:
            plan_record = self.get_plan_by_version(target_task.id, plan_version)
            if not plan_record:
                raise PlanNotFoundError(f"Plan version {plan_version} does not exist for task {target_task.id}")
            raise APIError(
                409,
                ErrorCode.PLAN_VERSION_MISMATCH,
                f"Requested rejection for plan_version {plan_version}, but current plan_version is {latest_plan.plan_version}.",
            )

        safe_reason = scrub_sensitive_text(feedback or reason)

        approval = TaskApproval(
            id=uuid.uuid4(),
            task_id=target_task.id,
            plan_id=latest_plan.id,
            plan_version=target_version,
            user_id=u_uuid,
            decision=ApprovalDecision.REJECTED.value,
            feedback=safe_reason,
            plan_hash=latest_plan.plan_hash,
            base_revision=latest_plan.base_revision,
        )
        self.session.add(approval)

        latest_plan.status = TaskPlanStatus.REJECTED.value
        prev_status = target_task.status
        target_task.status = TaskStatus.REJECTED.value
        target_task.approved_plan_version = None
        self.session.flush()

        self.record_event(
            task_id=target_task.id,
            repository_id=target_task.repository_id,
            event_type="PLAN_REJECTED",
            event_data={
                "plan_version": target_version,
                "plan_hash": latest_plan.plan_hash,
                "base_revision": latest_plan.base_revision,
                "decision": approval.decision,
                "reason": safe_reason,
            },
            user_id=effective_user_id,
            from_status=prev_status,
            to_status=TaskStatus.REJECTED.value,
            summary=f"Plan v{target_version} rejected by user.",
        )

        self.session.commit()
        self.session.refresh(approval)
        self.session.refresh(target_task)
        return approval

    def verify_execution_approval_gate(self, task: Task) -> TaskPlan:
        """Server-enforced approval gate (Sukun W3 Day 2 — Docs/week3.md §6 F32 & §7.2).

        Blocks execution unless:
        1. `task.status` is `APPROVED` (or `WORKSPACE_SETUP` / `EXECUTING` when already started).
        2. `task.approved_plan_version` is non-null and equals `task.plan_version`.
        3. The latest `TaskPlan` matches `task.approved_plan_version` and `task.base_revision`.
        4. An immutable `TaskApproval` with `decision == 'APPROVED'` exists for `(task.id, latest_plan.plan_version, latest_plan.plan_hash)`.
        5. Recomputes the structural SHA-256 `plan_hash` from the persisted `latest_plan` steps/files/base_revision to detect any post-approval tampering.
        """
        curr_status = TaskStatus(task.status)
        if curr_status in (TaskStatus.CREATED, TaskStatus.PLANNING, TaskStatus.PENDING_APPROVAL):
            raise APIError(
                403,
                ErrorCode.APPROVAL_REQUIRED,
                "The task cannot execute until the implementation plan is explicitly approved by a human.",
            )
        if curr_status == TaskStatus.REJECTED:
            raise APIError(
                403,
                ErrorCode.APPROVAL_REQUIRED,
                "The implementation plan was rejected. Generate and approve a revised plan before executing.",
            )
        if curr_status in (TaskStatus.CANCELLED, TaskStatus.FAILED, TaskStatus.BLOCKED):
            raise APIError(
                409,
                ErrorCode.INVALID_STATE_TRANSITION,
                f"Task in terminal/blocked status '{curr_status.value}' cannot be executed.",
            )

        if task.approved_plan_version is None:
            raise APIError(
                403,
                ErrorCode.APPROVAL_REQUIRED,
                "Task has no approved plan version. Human approval is required before execution.",
            )

        if task.approved_plan_version != task.plan_version:
            raise APIError(
                409,
                ErrorCode.PLAN_VERSION_MISMATCH,
                f"Approved plan version (v{task.approved_plan_version}) does not match current plan version (v{task.plan_version}). Renewed approval is required.",
            )

        latest_plan = self.get_latest_plan(task.id)
        if latest_plan is None:
            raise APIError(
                404,
                ErrorCode.RESOURCE_NOT_FOUND,
                f"No plan records found for task {task.id}.",
            )

        if latest_plan.plan_version != task.approved_plan_version:
            raise APIError(
                409,
                ErrorCode.PLAN_VERSION_MISMATCH,
                f"Latest plan version (v{latest_plan.plan_version}) does not match approved version (v{task.approved_plan_version}).",
            )

        if task.base_revision and latest_plan.base_revision and task.base_revision != latest_plan.base_revision:
            raise APIError(
                409,
                ErrorCode.PLAN_VERSION_MISMATCH,
                f"Task base revision '{task.base_revision}' differs from plan base revision '{latest_plan.base_revision}'. Re-plan and renewed approval required.",
            )

        # Confirm that an immutable approval record exists
        stmt = (
            select(TaskApproval)
            .where(
                TaskApproval.task_id == task.id,
                TaskApproval.plan_version == latest_plan.plan_version,
                TaskApproval.decision == "APPROVED",
            )
            .order_by(TaskApproval.created_at.desc())
        )
        approval_rec = self.session.scalars(stmt).first()
        if approval_rec is None:
            raise APIError(
                403,
                ErrorCode.APPROVAL_REQUIRED,
                f"No valid immutable approval record found for plan v{latest_plan.plan_version}.",
            )

        if latest_plan.plan_hash and approval_rec.plan_hash and latest_plan.plan_hash != approval_rec.plan_hash:
            raise APIError(
                409,
                ErrorCode.PLAN_VERSION_MISMATCH,
                "Tampering detected: plan hash does not match approval record hash. Renewed approval required.",
            )

        # Tampering check: recompute plan hash if schema can be constructed
        if latest_plan.plan_hash:
            try:
                reconstructed_schema = PlannerSchema(
                    summary=latest_plan.summary,
                    problem_statement=latest_plan.problem_statement or "",
                    assumptions=latest_plan.assumptions or [],
                    relevant_files=latest_plan.relevant_files or [],
                    relevant_symbols=latest_plan.relevant_symbols or [],
                    steps=latest_plan.steps or [],
                    expected_files=latest_plan.expected_files or [],
                    tests_to_run=latest_plan.tests_to_run or [],
                    validation_strategy=latest_plan.validation_strategy if isinstance(latest_plan.validation_strategy, list) else ([latest_plan.validation_strategy] if latest_plan.validation_strategy else []),
                    risks=latest_plan.risks or [],
                    required_permissions=latest_plan.required_permissions or [],
                    resource_budget=latest_plan.resource_budget or {},
                )
                computed_hash = reconstructed_schema.compute_plan_hash(latest_plan.base_revision)
                if computed_hash != latest_plan.plan_hash:
                    raise APIError(
                        409,
                        ErrorCode.PLAN_VERSION_MISMATCH,
                        "Plan tampering detected: recomputed plan hash does not match stored hash. Execution halted.",
                    )
            except APIError:
                raise
            except Exception:
                pass

        return latest_plan

    # ------------------------------------------------------------------
    # 4. Checkpoints, Bounded Repair & Recovery (F39)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # 5. Timeline & Audit Events
    # ------------------------------------------------------------------

    def record_event(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str | None = None,
        event_type: str = "EVENT",
        event_data: Optional[dict[str, Any]] = None,
        user_id: Optional[uuid.UUID | str] = None,
        *,
        from_status: str | None = None,
        to_status: str | None = None,
        summary: str = "",
    ) -> TaskEvent:
        """Append ordered timeline audit event."""
        t_uuid = _ensure_uuid(task_id)
        u_uuid = _ensure_uuid(user_id)

        clean_event_data = scrub_sensitive_data(event_data)
        safe_summary = scrub_sensitive_text(summary) or ""

        event = TaskEvent(
            id=uuid.uuid4(),
            task_id=t_uuid,
            event_type=event_type,
            event_data=clean_event_data,
            user_id=u_uuid,
            actor_id=u_uuid,
            from_status=from_status,
            to_status=to_status,
            summary=safe_summary,
        )
        self.session.add(event)
        self.session.flush()
        return event

    def _append_event(
        self,
        *,
        task_id: uuid.UUID | str,
        event_type: str,
        actor_id: uuid.UUID | str | None = None,
        from_status: str | None = None,
        to_status: str | None = None,
        summary: str = "",
        payload: dict[str, Any] | None = None,
    ) -> TaskEvent:
        """Internal helper alias for appending timeline events."""
        return self.record_event(
            task_id=task_id,
            event_type=event_type,
            event_data=payload,
            user_id=actor_id,
            from_status=from_status,
            to_status=to_status,
            summary=summary,
        )

    def list_events(self, task_id: uuid.UUID | str) -> list[TaskEvent]:
        """List all events for a task, ordered by created_at asc."""
        t_uuid = _ensure_uuid(task_id)
        if t_uuid is None:
            return []
        stmt = (
            select(TaskEvent)
            .where(TaskEvent.task_id == t_uuid)
            .order_by(TaskEvent.created_at.asc())
        )
        return list(self.session.scalars(stmt).all())

    def list_approvals(self, task_id: uuid.UUID | str) -> list[TaskApproval]:
        """List immutable approval records for a task, ordered by created_at asc."""
        t_uuid = _ensure_uuid(task_id)
        if t_uuid is None:
            return []
        stmt = (
            select(TaskApproval)
            .where(TaskApproval.task_id == t_uuid)
            .order_by(TaskApproval.created_at.asc())
        )
        return list(self.session.scalars(stmt).all())

    def get_task_timeline(
        self,
        task_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
    ) -> Sequence[TaskEvent]:
        """Fetch chronologically ordered audit events for a task."""
        t_uuid = _ensure_uuid(task_id)
        if not t_uuid:
            return []

        if repository_id is not None:
            task = self.get_task(t_uuid, repository_id)
            if not task:
                raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")

        return (
            self.session.execute(
                select(TaskEvent)
                .where(TaskEvent.task_id == t_uuid)
                .order_by(TaskEvent.created_at.asc())
            )
            .scalars()
            .all()
        )


__all__ = [
    "TaskRepository",
    "InvalidStateTransitionError",
    "TaskNotFoundError",
    "PlanNotFoundError",
    "scrub_sensitive_text",
    "scrub_sensitive_data",
    "VALID_TRANSITIONS",
]
