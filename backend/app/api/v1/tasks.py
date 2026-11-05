"""Week 3 Day 1–7 (F31–F39) — Task Intake, Planning, Approval Gate, Isolated Workspace, Tool Routing, Test Runner, Bounded Repair, Independent Verification, Git Branch/Commit/Push, Draft PR Publication, Checkpoints & Crash Recovery APIs.

Owners:
- Yug (Task lifecycle, execution, verification, git publication & recovery REST endpoints: create, list, detail, plan, approve, reject, execute, pause, resume, cancel, workspace, diff, tools, tests, repair-budget, repair, verify, verification, branch, commit, push, create-pr, publish, pull-request, checkpoints, recover, invariants, run-workflow, events)
- Meet & Dev (TaskPlanner, AgentExecutionLoop, BoundedRepairLoop, RequirementToCodeVerifier & VerificationResult schemas)
- Prit & Devu (WorkspaceManager, WorkspaceDiffVerifier, WorkspaceToolPolicyBridge, ToolRouter & command allowlist enforcement)
- Parth (GitBranchService, PullRequest metadata & GitHub integration)
- Sukun (Server-enforced approval gate, publication authorization gate, rate limiting & tenant isolation)
- Om (TaskRepository persistence, versioned plans, immutable approvals, test runs, repair attempts, verification results, checkpoints, pull requests & timeline events)
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.dependencies import (
    get_owned_task,
)
from ai.services.task_planner import TaskPlanner
from app.core.database import get_db
from app.core.errors import APIError, ErrorCode
from app.core.secret_redaction import redact, redact_obj
from app.models.repository import Repository
from app.models.task import (
    AgentTask,
    TaskApprovalRecord,
    TaskCheckpoint,
    TaskEventRecord,
    TaskPlanRecord,
    TaskPullRequest,
    WorkspaceStatus as DBWorkspaceStatus,
)
from app.repositories.repository_repository import RepositoryRepository
from app.repositories.task_repository import PlanNotFoundError, TaskRepository
from app.schemas.plan import (
    PlanApprovalRequest,
    PlanRejectionRequest,
    PlanResourceBudget,
    PlanRisk,
    PlanStep,
    TaskApprovalResponse,
    TaskEventResponse,
    TaskPlanGenerateRequest,
    TaskPlanResponse,
)
from app.schemas.task import (
    PaginatedTaskListResponse,
    PublicationAuthorizationRequest,
    PublicationAuthorizationResponse,
    TaskAssumption,
    TaskCheckpointResponse,
    TaskConstraint,
    TaskCreateRequest,
    TaskDetailResponse,
    TaskPullRequestResponse,
    TaskRequirement,
    TaskSourceReference,
    TaskStatus,
    TaskSummaryResponse,
    TaskTraceabilityResponse,
)
from app.schemas.workspace import (
    RepairAttemptRecord,
    TestOutcomeStatus,
    WorkspaceStatus,
)
from app.services.git_branch import format_agent_branch_name
from app.services.task_execution_orchestrator import get_task_execution_orchestrator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tasks", tags=["tasks"])
repo_tasks_router = APIRouter(prefix="/repositories", tags=["tasks"])


# ---------------------------------------------------------------------------
# Request / Response Models for Day 3–7 Execution, Tools, Tests, Repair, Verification, Git & Recovery
# ---------------------------------------------------------------------------

class TaskExecuteRequest(BaseModel):
    """Optional parameters for POST /api/v1/tasks/{task_id}/execute."""

    dry_run: bool = Field(default=False, description="If True, provisions workspace in READY state without starting IN_USE.")
    run_steps: bool = Field(default=False, description="If True, immediately executes approved plan steps in the workspace.")
    step_payloads: dict[str, Any] = Field(default_factory=dict, description="Optional per-step input payloads keyed by step_id.")
    run_tests_after: bool = Field(default=False, description="If True, executes workspace test suite after plan steps.")
    auto_repair: bool = Field(default=False, description="If True, triggers bounded self-repair if post-step tests fail.")


class TaskPauseRequest(BaseModel):
    """Optional parameters for POST /api/v1/tasks/{task_id}/pause."""

    reason: str = Field(default="Paused by user.", max_length=1000)


class TaskToolInvokeRequest(BaseModel):
    """Request payload for POST /api/v1/tasks/{task_id}/tools/{tool_name}."""

    arguments: dict[str, Any] = Field(default_factory=dict)


class TaskTestTriggerRequest(BaseModel):
    """Request payload for POST /api/v1/tasks/{task_id}/tests."""

    test_path: str | None = Field(default=None, max_length=512)
    framework: str | None = Field(default="pytest", max_length=64)
    arguments: list[str] = Field(default_factory=list)
    timeout_seconds: int = Field(default=60, ge=1, le=600)


class TaskRepairTriggerRequest(BaseModel):
    """Request payload for POST /api/v1/tasks/{task_id}/repair."""

    framework: str = Field(default="pytest", max_length=64)
    test_path: str | None = Field(default=None, max_length=512)
    patch_diff: str | None = Field(default=None, description="Optional explicit unified diff to validate and apply.")
    patch_explanation: str | None = Field(default=None, max_length=1000)
    target_files: list[str] = Field(default_factory=list)


class TaskVerifyTriggerRequest(BaseModel):
    """Optional parameters for POST /api/v1/tasks/{task_id}/verify."""

    run_tests_if_missing: bool = Field(
        default=False,
        description="If True and no test runs exist yet, runs the workspace test suite before verification.",
    )
    require_passing_tests: bool = Field(
        default=True,
        description="If True, treats passing test execution or clean baseline as mandatory for PASS.",
    )
    allow_critical_deletions: bool = Field(
        default=False,
        description="If True, permits deletion of critical project manifests with a warning instead of blocking.",
    )
    strict_scope: bool = Field(
        default=True,
        description="If True, rejects modifications to files outside the approved plan and requirement target_files.",
    )


class TaskBranchSetupRequest(BaseModel):
    """Optional parameters for POST /api/v1/tasks/{task_id}/branch."""

    branch_name: str | None = Field(
        default=None,
        max_length=256,
        description="Optional custom feature branch name (protected branches like main/master are strictly blocked).",
    )


class TaskCommitTriggerRequest(BaseModel):
    """Request payload for POST /api/v1/tasks/{task_id}/commit."""

    message: str | None = Field(default=None, max_length=1000, description="Commit message.")
    branch_name: str | None = Field(default=None, max_length=256, description="Target feature branch.")
    files: list[str] | None = Field(default=None, description="Optional list of specific relative file paths to stage.")
    author_name: str = Field(default="AI Platform Agent", max_length=128)
    author_email: str = Field(default="agent@ai-platform.local", max_length=128)


class TaskPushTriggerRequest(BaseModel):
    """Request payload for POST /api/v1/tasks/{task_id}/push."""

    publication_authorized: bool = Field(
        default=False,
        description="Mandatory explicit human publication authorization flag (ADR-010).",
    )
    human_authorized: bool = Field(
        default=False,
        description="Alias for publication_authorized.",
    )
    branch_name: str | None = Field(default=None, max_length=256)
    remote_name: str = Field(default="origin", max_length=128)
    current_remote_head_sha: str | None = Field(
        default=None,
        max_length=128,
        description="Optional remote base branch HEAD SHA for stale base-revision detection.",
    )
    strict_remote: bool = Field(default=False)

    @property
    def is_authorized(self) -> bool:
        return bool(self.publication_authorized or self.human_authorized)


class TaskDraftPRCreateRequest(BaseModel):
    """Request payload for POST /api/v1/tasks/{task_id}/create-pr (and /publish)."""

    publication_authorized: bool = Field(
        default=False,
        description="Mandatory explicit human publication authorization flag (ADR-010).",
    )
    human_authorized: bool = Field(
        default=False,
        description="Alias for publication_authorized.",
    )
    title: str | None = Field(default=None, max_length=512, description="Optional custom PR title.")
    body: str | None = Field(default=None, max_length=10000, description="Optional custom PR body markdown.")
    base_branch: str | None = Field(default=None, max_length=256, description="Target base branch (defaults to repository default_branch or 'main').")
    head_branch: str | None = Field(default=None, max_length=256, description="Source feature branch (defaults to agent/task-<id>).")
    current_remote_head_sha: str | None = Field(default=None, max_length=128)
    authorization_notes: str | None = Field(default=None, max_length=2000)

    @property
    def is_authorized(self) -> bool:
        return bool(self.publication_authorized or self.human_authorized)


class TaskCheckpointCreateRequest(BaseModel):
    """Request payload for POST /api/v1/tasks/{task_id}/checkpoints."""

    step_name: str = Field(..., min_length=1, max_length=128, description="Execution step or phase name.")
    state_data: dict[str, Any] = Field(default_factory=dict, description="Checkpoint state dictionary (secret-scrubbed prior to storage).")
    recovery_instructions: str | None = Field(default=None, max_length=2000)


class TaskRecoverTriggerRequest(BaseModel):
    """Optional parameters for POST /api/v1/tasks/{task_id}/recover."""

    target_status: TaskStatus | None = Field(
        default=None,
        description="Optional target status after reconciliation (defaults to APPROVED if plan approved, else PLANNING).",
    )
    action: str | None = Field(
        default=None,
        max_length=64,
        description="Optional recovery action hint ('retry', 'reconcile', 'reset_to_plan', 'resume').",
    )
    reason: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional recovery reason.",
    )


class TaskAutonomousWorkflowRequest(BaseModel):
    """Optional parameters for POST /api/v1/tasks/{task_id}/run-workflow."""

    step_payloads: dict[str, Any] = Field(default_factory=dict)
    run_tests: bool = Field(default=True)
    auto_repair: bool = Field(default=True)
    publication_authorized: bool = Field(default=False)
    pr_title: str | None = Field(default=None, max_length=512)
    pr_body: str | None = Field(default=None, max_length=10000)


# ---------------------------------------------------------------------------
# Internal Helpers & Serializers
# ---------------------------------------------------------------------------

def _request_user_id(request: Request) -> UUID:
    try:
        return UUID(str(request.state.user_id))
    except (AttributeError, ValueError) as exc:
        raise APIError(401, ErrorCode.UNAUTHORIZED, "Authentication is required.") from exc


def _owned_repository(repository_id: UUID, user_id: UUID, db: Session) -> Repository:
    repository = RepositoryRepository(db).get_for_user(repository_id, user_id)
    if repository is None:
        raise APIError(
            404,
            ErrorCode.REPOSITORY_NOT_FOUND,
            "Repository does not exist or you do not have access.",
        )
    return repository


_owned_task = get_owned_task


def _serialize_plan_record(plan: TaskPlanRecord, task: AgentTask) -> TaskPlanResponse:
    is_approved = (
        task.approved_plan_version is not None
        and task.approved_plan_version == plan.plan_version
        and task.status not in (TaskStatus.REJECTED.value, TaskStatus.PENDING_APPROVAL.value)
    )
    val_strat = plan.validation_strategy
    if isinstance(val_strat, str):
        val_strat_list = [s.strip() for s in val_strat.split(";") if s.strip()]
    elif isinstance(val_strat, list):
        val_strat_list = [str(s) for s in val_strat]
    else:
        val_strat_list = []

    expected_files = list(plan.expected_files or [])
    tests_to_run = list(plan.tests_to_run or [])

    payload = {
        "plan_id": str(plan.id),
        "task_id": str(plan.task_id),
        "plan_version": plan.plan_version,
        "base_revision": plan.base_revision,
        "plan_hash": plan.plan_hash,
        "summary": redact(plan.summary),
        "problem_statement": redact(plan.problem_statement or plan.summary),
        "assumptions": [
            TaskAssumption.model_validate(a) if isinstance(a, dict) else TaskAssumption(id=f"asm-{i+1}", description=str(a))
            for i, a in enumerate(plan.assumptions or [])
        ],
        "relevant_files": list(plan.relevant_files or []),
        "relevant_symbols": list(plan.relevant_symbols or []),
        "steps": [PlanStep.model_validate(s) for s in (plan.steps or [])],
        "expected_files": expected_files,
        "expected_files_to_modify": expected_files,
        "tests_to_run": tests_to_run,
        "tests_to_add": tests_to_run,
        "validation_strategy": val_strat_list,
        "risks": [
            PlanRisk.model_validate(r) if isinstance(r, dict) else PlanRisk(id=f"risk-{i+1}", description=str(r))
            for i, r in enumerate(plan.risks or [])
        ],
        "required_permissions": list(plan.required_permissions or []),
        "resource_budget": PlanResourceBudget.model_validate(plan.resource_budget or {}),
        "status": plan.status,
        "approved_plan_version": task.approved_plan_version,
        "is_approved": is_approved,
        "created_at": plan.created_at.isoformat() if plan.created_at else "",
        "updated_at": plan.updated_at.isoformat() if plan.updated_at else "",
    }
    return TaskPlanResponse.model_validate(redact_obj(payload))


def _serialize_approval_record(record: TaskApprovalRecord, task: AgentTask) -> TaskApprovalResponse:
    comment_clean = redact(record.comment) if record.comment else None
    approver_str = str(record.approver_id) if record.approver_id else ""
    payload = {
        "id": str(record.id),
        "approval_id": str(record.id),
        "task_id": str(record.task_id),
        "plan_id": str(record.plan_id) if record.plan_id else "",
        "plan_version": record.plan_version,
        "approver_id": approver_str,
        "user_id": approver_str or None,
        "decision": record.decision,
        "comment": comment_clean,
        "notes": comment_clean,
        "reason": comment_clean if record.decision == "REJECTED" else None,
        "base_revision": record.base_revision,
        "plan_hash": record.plan_hash,
        "task_status": TaskStatus(task.status),
        "status": TaskStatus(task.status),
        "approved_plan_version": task.approved_plan_version,
        "created_at": record.created_at.isoformat() if record.created_at else "",
    }
    return TaskApprovalResponse.model_validate(redact_obj(payload))


def _serialize_event_record(event: TaskEventRecord) -> TaskEventResponse:
    summary_clean = redact(event.summary or "")
    payload_clean = redact_obj(event.payload or {})
    actor_str = str(event.actor_id or event.user_id) if (event.actor_id or event.user_id) else None
    payload = {
        "id": str(event.id),
        "event_id": str(event.id),
        "task_id": str(event.task_id),
        "event_type": event.event_type,
        "actor_id": actor_str,
        "user_id": actor_str,
        "from_status": event.from_status,
        "to_status": event.to_status,
        "summary": summary_clean,
        "description": summary_clean,
        "payload": payload_clean,
        "details": payload_clean,
        "created_at": event.created_at.isoformat() if event.created_at else "",
    }
    return TaskEventResponse.model_validate(payload)


def _serialize_checkpoint_record(cp: TaskCheckpoint) -> TaskCheckpointResponse:
    payload = {
        "checkpoint_id": str(cp.id),
        "task_id": str(cp.task_id),
        "step_name": cp.step_name,
        "state_data": redact_obj(cp.state_data or {}),
        "recovery_instructions": redact(cp.recovery_instructions or "") if cp.recovery_instructions else None,
        "created_at": cp.created_at.isoformat() if cp.created_at else "",
    }
    return TaskCheckpointResponse.model_validate(payload)


def _serialize_pull_request_record(pr: TaskPullRequest) -> TaskPullRequestResponse:
    payload = {
        "pr_id": str(pr.id),
        "task_id": str(pr.task_id),
        "repository_id": str(pr.repository_id),
        "pr_number": pr.pr_number,
        "pr_url": pr.pr_url,
        "base_branch": pr.base_branch,
        "head_branch": pr.head_branch,
        "head_sha": pr.head_sha,
        "is_draft": bool(pr.is_draft),
        "title": redact(pr.title),
        "body": redact(pr.body or "") if pr.body else None,
        "created_at": pr.created_at.isoformat() if pr.created_at else "",
    }
    return TaskPullRequestResponse.model_validate(payload)


def _serialize_task_detail(task: AgentTask, task_repo: TaskRepository) -> TaskDetailResponse:
    latest_plan = task_repo.get_latest_plan(task.id)
    approvals = task_repo.list_approvals(task.id)

    source_ref = TaskSourceReference.model_validate(
        task.source_ref or {"type": task.source_type or "USER_PROMPT"}
    )
    reqs = [TaskRequirement.model_validate(r) for r in (task.requirements or [])]
    asms = [TaskAssumption.model_validate(a) for a in (task.assumptions or [])]
    csts = [TaskConstraint.model_validate(c) for c in (task.constraints or [])]

    latest_plan_dict = (
        _serialize_plan_record(latest_plan, task).model_dump(mode="json")
        if latest_plan is not None
        else None
    )
    approvals_list = [
        _serialize_approval_record(a, task).model_dump(mode="json")
        for a in approvals
    ]

    payload = {
        "task_id": str(task.id),
        "repository_id": str(task.repository_id),
        "title": redact(task.title),
        "description": redact(task.description or ""),
        "status": TaskStatus(task.status),
        "source_type": source_ref.type,
        "source": source_ref.model_dump(mode="json"),
        "requirements": [r.model_dump(mode="json") for r in reqs],
        "assumptions": [a.model_dump(mode="json") for a in asms],
        "constraints": [c.model_dump(mode="json") for c in csts],
        "base_revision": task.base_revision,
        "plan_version": task.plan_version,
        "approved_plan_version": task.approved_plan_version,
        "repair_attempts_used": task.repair_attempts_used,
        "repair_attempts_max": task.repair_attempts_max,
        "latest_plan": latest_plan_dict,
        "approvals": approvals_list,
        "created_at": task.created_at.isoformat() if task.created_at else "",
        "updated_at": task.updated_at.isoformat() if task.updated_at else "",
    }
    return TaskDetailResponse.model_validate(redact_obj(payload))


def _serialize_task_summary(task: AgentTask) -> TaskSummaryResponse:
    source_ref = TaskSourceReference.model_validate(
        task.source_ref or {"type": task.source_type or "USER_PROMPT"}
    )
    reqs = [TaskRequirement.model_validate(r) for r in (task.requirements or [])]
    asms = [TaskAssumption.model_validate(a) for a in (task.assumptions or [])]
    csts = [TaskConstraint.model_validate(c) for c in (task.constraints or [])]
    payload = {
        "task_id": str(task.id),
        "repository_id": str(task.repository_id),
        "title": redact(task.title),
        "description": redact(task.description or ""),
        "status": TaskStatus(task.status),
        "source_type": source_ref.type,
        "source": source_ref.model_dump(mode="json"),
        "requirements": [r.model_dump(mode="json") for r in reqs],
        "assumptions": [a.model_dump(mode="json") for a in asms],
        "constraints": [c.model_dump(mode="json") for c in csts],
        "base_revision": task.base_revision,
        "plan_version": task.plan_version,
        "approved_plan_version": task.approved_plan_version,
        "repair_attempts_used": task.repair_attempts_used,
        "repair_attempts_max": task.repair_attempts_max,
        "created_at": task.created_at.isoformat() if task.created_at else "",
        "updated_at": task.updated_at.isoformat() if task.updated_at else "",
    }
    return TaskSummaryResponse.model_validate(redact_obj(payload))


# ---------------------------------------------------------------------------
# 1. Create, List & Inspect Tasks
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=TaskDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new development task with segregated requirements, assumptions, and constraints",
)
def create_task(
    payload: TaskCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> TaskDetailResponse:
    user_id = _request_user_id(request)
    repo = _owned_repository(payload.repository_id, user_id, db)

    if not payload.base_revision and not payload.source.base_revision:
        payload.base_revision = repo.default_branch or "main"

    task_repo = TaskRepository(db)
    task = task_repo.create_task(user_id=user_id, intake=payload)
    return _serialize_task_detail(task, task_repo)


@router.get(
    "",
    response_model=PaginatedTaskListResponse,
    summary="List tasks for the authenticated user",
)
def list_tasks(
    request: Request,
    repository_id: UUID | None = Query(default=None, description="Optional repository filter"),
    status_filter: str | None = Query(default=None, alias="status", description="Optional status filter"),
    search: str | None = Query(default=None, description="Optional search query across title, description, and task_id"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> PaginatedTaskListResponse:
    user_id = _request_user_id(request)
    if repository_id is not None:
        _owned_repository(repository_id, user_id, db)

    task_repo = TaskRepository(db)
    items, total = task_repo.list_tasks_for_user(
        user_id,
        repository_id=repository_id,
        status=status_filter,
        offset=0 if search else (page - 1) * page_size,
        limit=200 if search else page_size,
    )
    if search and search.strip():
        q = search.strip().lower()
        filtered = [
            t
            for t in items
            if q in (t.title or "").lower()
            or q in (t.description or "").lower()
            or q in str(t.id).lower()
        ]
        total = len(filtered)
        start = (page - 1) * page_size
        items = filtered[start : start + page_size]

    return PaginatedTaskListResponse(
        items=[_serialize_task_summary(t) for t in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{task_id}",
    response_model=TaskDetailResponse,
    summary="Get complete task details, latest plan, and approval history",
)
def get_task_detail(
    task_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> TaskDetailResponse:
    task, _ = _owned_task(task_id, request, db)
    task_repo = TaskRepository(db)
    return _serialize_task_detail(task, task_repo)


# ---------------------------------------------------------------------------
# 2. Task Planning (F32 — Meet & Dev)
# ---------------------------------------------------------------------------

@router.post(
    "/{task_id}/plan",
    response_model=TaskPlanResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate or revise a structured implementation plan for a task",
)
async def generate_task_plan(
    task_id: UUID,
    request: Request,
    body: TaskPlanGenerateRequest | None = None,
    db: Session = Depends(get_db),
) -> TaskPlanResponse:
    task, user_id = _owned_task(task_id, request, db)
    task_repo = TaskRepository(db)

    if body and body.custom_plan is not None:
        plan_schema = body.custom_plan
    else:
        planner: TaskPlanner | None = getattr(request.app.state, "task_planner", None)
        if planner is None:
            llm_gateway = getattr(request.app.state, "llm_gateway", None)
            planner = TaskPlanner(llm_gateway=llm_gateway)
        effective_notes = (body.revision_notes or body.prompt_instructions) if body else None
        plan_schema = await planner.generate_plan(
            task,
            db=db,
            revision_notes=effective_notes,
        )

    effective_base_rev = (body.base_revision if body and body.base_revision else None) or task.base_revision
    plan_record = task_repo.save_plan(
        task=task,
        plan_schema=plan_schema,
        base_revision=effective_base_rev,
        actor_id=user_id,
    )
    return _serialize_plan_record(plan_record, task)


@router.get(
    "/{task_id}/plan",
    response_model=TaskPlanResponse,
    summary="Retrieve the current or specified version of a task's implementation plan",
)
def get_task_plan(
    task_id: UUID,
    request: Request,
    version: int | None = Query(default=None, ge=1, description="Optional specific plan_version"),
    db: Session = Depends(get_db),
) -> TaskPlanResponse:
    task, _ = _owned_task(task_id, request, db)
    task_repo = TaskRepository(db)

    if version is not None:
        plan_record = task_repo.get_plan_by_version(task.id, version)
    else:
        plan_record = task_repo.get_latest_plan(task.id)

    if plan_record is None:
        raise APIError(
            404,
            ErrorCode.NOT_FOUND,
            f"No implementation plan found for task '{task_id}'.",
        )
    return _serialize_plan_record(plan_record, task)


# ---------------------------------------------------------------------------
# 3. Human Approval & Rejection Gate (F32 — Sukun, Meet, Yug)
# ---------------------------------------------------------------------------

@router.post(
    "/{task_id}/approve",
    response_model=TaskApprovalResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve the current implementation plan version for execution",
)
def approve_task_plan(
    task_id: UUID,
    request: Request,
    body: PlanApprovalRequest | None = None,
    db: Session = Depends(get_db),
) -> TaskApprovalResponse:
    task, user_id = _owned_task(task_id, request, db)
    task_repo = TaskRepository(db)

    effective_comment = (body.comment or body.notes) if body else None
    try:
        approval = task_repo.approve_plan(
            task=task,
            approver_id=user_id,
            plan_version=body.plan_version if body else None,
            base_revision=body.base_revision if body else None,
            comment=effective_comment,
        )
    except PlanNotFoundError as exc:
        raise APIError(
            409,
            ErrorCode.PLAN_VERSION_MISMATCH,
            str(exc),
        )
    approval_resp = _serialize_approval_record(approval, task)
    task_detail = _serialize_task_detail(task, task_repo).model_dump(mode="json")
    merged = {**task_detail, **approval_resp.model_dump(mode="json", exclude_none=True)}
    return TaskApprovalResponse.model_validate(merged)


@router.post(
    "/{task_id}/reject",
    response_model=TaskApprovalResponse,
    status_code=status.HTTP_200_OK,
    summary="Reject the current implementation plan version",
)
def reject_task_plan(
    task_id: UUID,
    request: Request,
    body: PlanRejectionRequest | None = None,
    db: Session = Depends(get_db),
) -> TaskApprovalResponse:
    task, user_id = _owned_task(task_id, request, db)
    task_repo = TaskRepository(db)

    approval = task_repo.reject_plan(
        task=task,
        approver_id=user_id,
        plan_version=body.plan_version if body else None,
        reason=(body.reason if body else None) or "Plan rejected by reviewer.",
    )
    approval_resp = _serialize_approval_record(approval, task)
    task_detail = _serialize_task_detail(task, task_repo).model_dump(mode="json")
    merged = {**task_detail, **approval_resp.model_dump(mode="json", exclude_none=True)}
    return TaskApprovalResponse.model_validate(merged)


# ---------------------------------------------------------------------------
# 4. Isolated Workspace Execution, Pause/Resume & Tool Routing (Week 3 Day 3)
# ---------------------------------------------------------------------------

@router.post(
    "/{task_id}/execute",
    response_model=TaskDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Validate human approval gate, provision isolated workspace, and start execution",
)
def execute_approved_task(
    task_id: UUID,
    request: Request,
    body: TaskExecuteRequest | None = None,
    db: Session = Depends(get_db),
) -> TaskDetailResponse:
    task, user_id = _owned_task(task_id, request, db)
    task_repo = TaskRepository(db)
    orchestrator = get_task_execution_orchestrator(request.app.state)

    orchestrator.start_task_execution(
        task=task,
        task_repo=task_repo,
        actor_id=user_id,
        dry_run=body.dry_run if body else False,
        run_steps=body.run_steps if body else False,
        step_payloads=body.step_payloads if body else None,
        run_tests_after=body.run_tests_after if body else False,
        auto_repair=body.auto_repair if body else False,
    )
    return _serialize_task_detail(task, task_repo)


@router.post(
    "/{task_id}/pause",
    response_model=TaskDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Pause active execution in the task's isolated workspace",
)
def pause_task(
    task_id: UUID,
    request: Request,
    body: TaskPauseRequest | None = None,
    db: Session = Depends(get_db),
) -> TaskDetailResponse:
    task, user_id = _owned_task(task_id, request, db)
    task_repo = TaskRepository(db)
    orchestrator = get_task_execution_orchestrator(request.app.state)
    orchestrator.pause_task_execution(
        task=task,
        task_repo=task_repo,
        actor_id=user_id,
        reason=(body.reason if body else None) or "Paused by user.",
    )
    return _serialize_task_detail(task, task_repo)


@router.post(
    "/{task_id}/resume",
    response_model=TaskDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Resume paused execution in the task's isolated workspace",
)
def resume_task(
    task_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> TaskDetailResponse:
    task, user_id = _owned_task(task_id, request, db)
    task_repo = TaskRepository(db)
    orchestrator = get_task_execution_orchestrator(request.app.state)
    orchestrator.resume_task_execution(
        task=task,
        task_repo=task_repo,
        actor_id=user_id,
    )
    return _serialize_task_detail(task, task_repo)


@router.post(
    "/{task_id}/cancel",
    response_model=TaskDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel an active or pending task and stop its workspace",
)
def cancel_task(
    task_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> TaskDetailResponse:
    task, user_id = _owned_task(task_id, request, db)
    task_repo = TaskRepository(db)
    orchestrator = get_task_execution_orchestrator(request.app.state)

    meta = orchestrator.workspace_manager.get_workspace(str(task.id))
    if meta is not None and meta.status in (WorkspaceStatus.IN_USE, WorkspaceStatus.READY):
        try:
            orchestrator.workspace_manager.stop_execution(str(task.id), reason="Task cancelled by user")
        except Exception:
            pass

    db_ws = task_repo.get_workspace_record(task.id)
    if db_ws is not None and db_ws.status in (DBWorkspaceStatus.IN_USE.value, DBWorkspaceStatus.READY.value):
        db_ws.status = DBWorkspaceStatus.STOPPED.value

    task_repo.transition_status(
        task,
        TaskStatus.CANCELLED,
        actor_id=user_id,
        event_type="TASK_CANCELLED",
        summary="Task cancelled by user.",
    )
    return _serialize_task_detail(task, task_repo)


@router.get(
    "/{task_id}/workspace",
    summary="Get isolated workspace status and telemetry for a task",
)
def get_task_workspace(
    task_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    task, _ = _owned_task(task_id, request, db)
    task_repo = TaskRepository(db)
    orchestrator = get_task_execution_orchestrator(request.app.state)

    meta = orchestrator.ensure_workspace_loaded(task, task_repo)
    if meta is not None:
        return redact_obj(meta.model_dump(mode="json"))

    branch_name = format_agent_branch_name(task.id)
    return {
        "workspace_id": f"ws-{task.id}",
        "task_id": str(task.id),
        "repository_id": str(task.repository_id),
        "base_revision": task.base_revision or "main",
        "branch_name": branch_name,
        "workspace_path": "",
        "status": WorkspaceStatus.NOT_CREATED.value,
        "isolation_type": "directory_copy",
        "resource_limits": {
            "timeout_seconds": 60,
            "max_disk_bytes": 524_288_000,
            "max_file_size_bytes": 5_242_880,
            "max_files_modified": 50,
            "network_egress_allowed": False,
        },
        "created_at": task.created_at.isoformat() if task.created_at else "",
        "updated_at": task.updated_at.isoformat() if task.updated_at else "",
    }


@router.get(
    "/{task_id}/diff",
    summary="Get modified files and git diff telemetry from the task workspace",
)
def get_task_diff(
    task_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    task, _ = _owned_task(task_id, request, db)
    task_repo = TaskRepository(db)
    orchestrator = get_task_execution_orchestrator(request.app.state)

    meta = orchestrator.ensure_workspace_loaded(task, task_repo)
    branch_name = meta.branch_name if meta else format_agent_branch_name(task.id)
    if meta is None or meta.status not in (
        WorkspaceStatus.READY,
        WorkspaceStatus.IN_USE,
        WorkspaceStatus.STOPPED,
    ):
        return {
            "task_id": str(task.id),
            "repository_id": str(task.repository_id),
            "base_branch": task.base_revision or "main",
            "head_branch": branch_name,
            "files": [],
            "total_files_changed": 0,
            "total_additions": 0,
            "total_deletions": 0,
        }

    try:
        diff_res = orchestrator.workspace_manager.get_workspace_diff(str(task.id))
        files_out = [
            {
                "file_path": f.file_path,
                "status": f.change_type.value if hasattr(f.change_type, "value") else str(f.change_type),
                "additions": f.insertions,
                "deletions": f.deletions,
                "patch": redact(getattr(f, "patch", None) or getattr(f, "diff_text", "") or ""),
                "diff_ranges": [],
            }
            for f in diff_res.files
        ]
        return redact_obj(
            {
                "task_id": str(task.id),
                "repository_id": str(task.repository_id),
                "base_branch": diff_res.base_revision or task.base_revision or "main",
                "head_branch": branch_name,
                "files": files_out,
                "total_files_changed": diff_res.total_files_changed,
                "total_additions": diff_res.insertions,
                "total_deletions": diff_res.deletions,
                "raw_diff": redact(diff_res.raw_diff or ""),
            }
        )
    except Exception:
        return {
            "task_id": str(task.id),
            "repository_id": str(task.repository_id),
            "base_branch": task.base_revision or "main",
            "head_branch": branch_name,
            "files": [],
            "total_files_changed": 0,
            "total_additions": 0,
            "total_deletions": 0,
        }


@router.post(
    "/{task_id}/tools/{tool_name}",
    summary="Execute a policy-guarded workspace tool via ToolRouter",
)
def invoke_task_tool(
    task_id: UUID,
    tool_name: str,
    payload: TaskToolInvokeRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    task, user_id = _owned_task(task_id, request, db)
    task_repo = TaskRepository(db)
    orchestrator = get_task_execution_orchestrator(request.app.state)

    result = orchestrator.invoke_workspace_tool(
        task=task,
        task_repo=task_repo,
        tool_name=tool_name,
        arguments=payload.arguments,
        actor_id=user_id,
    )
    return redact_obj(
        {
            "task_id": str(task.id),
            "tool_name": tool_name,
            "success": result.success,
            "output": result.output,
            "error": result.error,
        }
    )


# ---------------------------------------------------------------------------
# 5. Test Runner & Bounded Repair Loop APIs (Week 3 Day 4 — F35)
# ---------------------------------------------------------------------------

@router.get(
    "/{task_id}/tests",
    summary="Get test execution history and bounded repair attempt telemetry for a task",
)
def get_task_tests(
    task_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    task, _ = _owned_task(task_id, request, db)
    task_repo = TaskRepository(db)
    orchestrator = get_task_execution_orchestrator(request.app.state)

    db_runs = task_repo.list_test_runs(task.id)
    mem_runs = orchestrator.workspace_manager.get_test_history(str(task.id))

    runs_list: list[dict[str, Any]] = []
    if db_runs:
        for idx, r in enumerate(db_runs, start=1):
            runs_list.append(
                {
                    "attempt": idx,
                    "command": r.command,
                    "status": r.status,
                    "exit_code": r.exit_code if r.exit_code is not None else (0 if r.status == "PASSED" else 1),
                    "duration_ms": r.duration_ms or 0,
                    "tests_total": r.tests_total,
                    "total_count": r.tests_total,
                    "tests_passed": r.tests_passed,
                    "passed_count": r.tests_passed,
                    "tests_failed": r.tests_failed,
                    "failed_count": r.tests_failed,
                    "stdout": redact(r.sanitized_output or ""),
                    "output_summary": redact((r.sanitized_output or "")[:500]),
                    "executed_at": r.created_at.isoformat() if r.created_at else "",
                }
            )
    elif mem_runs:
        for idx, mr in enumerate(mem_runs, start=1):
            runs_list.append(
                {
                    "attempt": idx,
                    "command": f"{mr.framework or 'pytest'}",
                    "status": mr.status.value,
                    "exit_code": 0 if mr.status == TestOutcomeStatus.PASSED else 1,
                    "duration_ms": int(mr.duration_ms),
                    "tests_total": mr.total_count,
                    "total_count": mr.total_count,
                    "tests_passed": mr.passed_count,
                    "passed_count": mr.passed_count,
                    "tests_failed": mr.failed_count,
                    "failed_count": mr.failed_count,
                    "stdout": redact(mr.stdout or ""),
                    "stderr": redact(mr.stderr or ""),
                    "output_summary": redact(f"{mr.passed_count} passed, {mr.failed_count} failed"),
                    "executed_at": task.updated_at.isoformat() if task.updated_at else "",
                }
            )

    db_repairs = task_repo.list_repair_attempts(task.id)
    repair_history = [
        {
            "attempt_number": ra.attempt_number,
            "task_id": str(task.id),
            "timestamp": ra.created_at.isoformat() if ra.created_at else "",
            "patch_summary": redact(ra.applied_patch or ra.diagnosis or f"Repair attempt {ra.attempt_number}"),
            "test_status_before": "FAILED",
            "test_status_after": "PASSED" if ra.result == "SUCCESS" else "FAILED",
            "success": ra.result == "SUCCESS",
        }
        for ra in db_repairs
    ]

    latest = runs_list[-1] if runs_list else None
    return redact_obj(
        {
            "task_id": str(task.id),
            "runs": runs_list,
            "repair_attempts_used": task.repair_attempts_used,
            "repair_attempts_max": task.repair_attempts_max,
            "repair_history": repair_history,
            "status": latest["status"] if latest else "NOT_RUN",
            "passed": latest["tests_passed"] if latest else 0,
            "failed": latest["tests_failed"] if latest else 0,
            "duration_ms": latest["duration_ms"] if latest else 0,
        }
    )


@router.post(
    "/{task_id}/tests",
    summary="Trigger restricted test execution inside the task's isolated workspace",
)
def trigger_task_tests(
    task_id: UUID,
    request: Request,
    body: TaskTestTriggerRequest | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    task, user_id = _owned_task(task_id, request, db)
    task_repo = TaskRepository(db)
    orchestrator = get_task_execution_orchestrator(request.app.state)

    orchestrator.execute_task_tests(
        task=task,
        task_repo=task_repo,
        actor_id=user_id,
        test_path=body.test_path if body else None,
        framework=body.framework if body else "pytest",
        arguments=body.arguments if body else None,
        timeout_seconds=body.timeout_seconds if body else 60,
    )
    return get_task_tests(task_id=task_id, request=request, db=db)


@router.get(
    "/{task_id}/repair-budget",
    summary="Get server-authoritative bounded self-repair budget status and history",
)
def get_task_repair_budget(
    task_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    task, _ = _owned_task(task_id, request, db)
    task_repo = TaskRepository(db)
    db_repairs = task_repo.list_repair_attempts(task.id)

    history = [
        RepairAttemptRecord(
            attempt_number=ra.attempt_number,
            task_id=str(task.id),
            timestamp=ra.created_at.isoformat() if ra.created_at else "",
            patch_summary=redact(ra.applied_patch or ra.diagnosis or f"Repair attempt {ra.attempt_number}"),
            workspace_revision=task.base_revision,
            test_status_before="FAILED",
            test_status_after="PASSED" if ra.result == "SUCCESS" else "FAILED",
            success=ra.result == "SUCCESS",
        ).model_dump(mode="json")
        for ra in db_repairs
    ]

    used = task.repair_attempts_used
    max_attempts = task.repair_attempts_max or 3
    exhausted = used >= max_attempts

    return redact_obj(
        {
            "task_id": str(task.id),
            "repair_attempts_used": used,
            "repair_attempts_max": max_attempts,
            "is_budget_exhausted": exhausted,
            "is_eligible_for_repair": not exhausted,
            "last_attempt_at": history[-1]["timestamp"] if history else None,
            "history": history,
        }
    )


@router.post(
    "/{task_id}/repair",
    summary="Trigger bounded self-repair cycle (max 3 task-level attempts)",
)
def trigger_task_repair(
    task_id: UUID,
    request: Request,
    body: TaskRepairTriggerRequest | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    task, user_id = _owned_task(task_id, request, db)
    task_repo = TaskRepository(db)
    orchestrator = get_task_execution_orchestrator(request.app.state)

    outcome = orchestrator.execute_bounded_repair(
        task=task,
        task_repo=task_repo,
        actor_id=user_id,
        framework=body.framework if body else "pytest",
        test_path=body.test_path if body else None,
        patch_diff=body.patch_diff if body else None,
        patch_explanation=body.patch_explanation if body else None,
        target_files=body.target_files if body else None,
    )
    budget = get_task_repair_budget(task_id=task_id, request=request, db=db)
    return redact_obj(
        {
            **budget,
            "success": outcome.success,
            "final_test_status": outcome.final_test_status.value,
            "final_output_summary": redact(outcome.final_output_summary),
            "error_message": redact(outcome.error_message) if outcome.error_message else None,
        }
    )


# ---------------------------------------------------------------------------
# 6. Independent Verification, Git Branch/Commit/Push & Draft PR APIs (Week 3 Day 5 — F36, F37)
# ---------------------------------------------------------------------------

@router.post(
    "/{task_id}/verify",
    summary="Execute independent multi-dimensional verification over workspace changes",
)
def trigger_task_verification(
    task_id: UUID,
    request: Request,
    body: TaskVerifyTriggerRequest | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    task, user_id = _owned_task(task_id, request, db)
    task_repo = TaskRepository(db)
    orchestrator = get_task_execution_orchestrator(request.app.state)

    ver_result = orchestrator.run_independent_verification(
        task=task,
        task_repo=task_repo,
        actor_id=user_id,
        run_tests_if_missing=body.run_tests_if_missing if body else False,
        require_passing_tests=body.require_passing_tests if body else True,
        allow_critical_deletions=body.allow_critical_deletions if body else False,
        strict_scope=body.strict_scope if body else True,
    )
    return redact_obj(
        {
            **ver_result.model_dump(mode="json"),
            "task_status": task.status,
            "is_eligible_for_publication": ver_result.is_eligible_for_publication,
        }
    )


@router.get(
    "/{task_id}/verification",
    summary="Get latest independent verification result for a task",
)
def get_task_verification(
    task_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    task, _ = _owned_task(task_id, request, db)
    task_repo = TaskRepository(db)
    ver = task_repo.get_latest_verification_result(task.id)
    if ver is None:
        return {
            "task_id": str(task.id),
            "verified_revision": task.base_revision or "main",
            "status": "INCONCLUSIVE",
            "checks": [],
            "blocking_findings": [],
            "warnings": [],
            "pr_summary": "",
            "created_at": task.updated_at.isoformat() if task.updated_at else "",
        }
    norm_status = "PASS" if ver.status == "PASSED" else ("FAIL" if ver.status == "FAILED" else ver.status)
    return redact_obj(
        {
            "task_id": str(task.id),
            "verified_revision": ver.verified_revision,
            "status": norm_status,
            "checks": ver.checks or [],
            "blocking_findings": ver.blocking_findings or [],
            "warnings": ver.warnings or [],
            "pr_summary": redact(ver.summary or ""),
            "created_at": ver.created_at.isoformat() if ver.created_at else "",
        }
    )


@router.post(
    "/{task_id}/branch",
    summary="Ensure isolated task branch agent/task-<id> and block protected branches",
)
def ensure_task_branch_endpoint(
    task_id: UUID,
    request: Request,
    body: TaskBranchSetupRequest | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    task, user_id = _owned_task(task_id, request, db)
    task_repo = TaskRepository(db)
    orchestrator = get_task_execution_orchestrator(request.app.state)

    return redact_obj(
        orchestrator.ensure_task_branch(
            task=task,
            task_repo=task_repo,
            actor_id=user_id,
            branch_name=body.branch_name if body else None,
        )
    )


@router.post(
    "/{task_id}/commit",
    summary="Stage and commit validated workspace changes on the isolated task branch",
)
def commit_task_changes_endpoint(
    task_id: UUID,
    request: Request,
    body: TaskCommitTriggerRequest | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    task, user_id = _owned_task(task_id, request, db)
    task_repo = TaskRepository(db)
    orchestrator = get_task_execution_orchestrator(request.app.state)

    res = orchestrator.commit_workspace_changes(
        task=task,
        task_repo=task_repo,
        actor_id=user_id,
        message=body.message if body else None,
        branch_name=body.branch_name if body else None,
        files=body.files if body else None,
        author_name=body.author_name if body else "AI Platform Agent",
        author_email=body.author_email if body else "agent@ai-platform.local",
    )
    return redact_obj(res.model_dump(mode="json"))


@router.post(
    "/{task_id}/push",
    summary="Push verified task branch after checking human publication authorization and diff immutability",
)
def push_task_branch_endpoint(
    task_id: UUID,
    request: Request,
    body: TaskPushTriggerRequest | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    task, user_id = _owned_task(task_id, request, db)
    task_repo = TaskRepository(db)
    orchestrator = get_task_execution_orchestrator(request.app.state)

    res = orchestrator.push_verified_branch(
        task=task,
        task_repo=task_repo,
        actor_id=user_id,
        publication_authorized=body.is_authorized if body else False,
        branch_name=body.branch_name if body else None,
        remote_name=body.remote_name if body else "origin",
        current_remote_head_sha=body.current_remote_head_sha if body else None,
        strict_remote=body.strict_remote if body else False,
    )
    return redact_obj(res.model_dump(mode="json"))


@router.post(
    "/{task_id}/authorize-publication",
    response_model=PublicationAuthorizationResponse,
    status_code=status.HTTP_200_OK,
    summary="Explicitly authorize branch publication and transition READY_FOR_PUBLICATION -> PUBLISHING",
)
def authorize_task_publication_endpoint(
    task_id: UUID,
    payload: PublicationAuthorizationRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> PublicationAuthorizationResponse:
    task, user_id = _owned_task(task_id, request, db)
    task_repo = TaskRepository(db)
    updated = task_repo.authorize_publication(
        task_id=task.id,
        repository_id=task.repository_id,
        head_sha=payload.head_sha,
        user_id=user_id,
        notes=payload.notes,
    )
    return PublicationAuthorizationResponse(
        task_id=str(updated.id),
        status=updated.status,
        head_sha=payload.head_sha,
        authorized=True,
        user_id=str(user_id),
        authorized_at=updated.updated_at.isoformat() if updated.updated_at else None,
    )


@router.post(
    "/{task_id}/create-pr",
    response_model=TaskPullRequestResponse,
    status_code=status.HTTP_200_OK,
    summary="Create a reviewable GitHub Draft Pull Request (is_draft=True, zero auto-merge)",
)
def create_task_draft_pr_endpoint(
    task_id: UUID,
    request: Request,
    body: TaskDraftPRCreateRequest | None = None,
    db: Session = Depends(get_db),
) -> TaskPullRequestResponse:
    task, user_id = _owned_task(task_id, request, db)
    task_repo = TaskRepository(db)
    orchestrator = get_task_execution_orchestrator(request.app.state)

    pr_record = orchestrator.create_draft_pull_request(
        task=task,
        task_repo=task_repo,
        actor_id=user_id,
        publication_authorized=body.is_authorized if body else False,
        title=body.title if body else None,
        body=body.body if body else None,
        base_branch=body.base_branch if body else None,
        head_branch=body.head_branch if body else None,
        current_remote_head_sha=body.current_remote_head_sha if body else None,
    )
    return _serialize_pull_request_record(pr_record)


@router.post(
    "/{task_id}/publish",
    response_model=TaskPullRequestResponse,
    status_code=status.HTTP_200_OK,
    summary="Alias for POST /api/v1/tasks/{task_id}/create-pr",
)
def publish_task_draft_pr_endpoint(
    task_id: UUID,
    request: Request,
    body: TaskDraftPRCreateRequest | None = None,
    db: Session = Depends(get_db),
) -> TaskPullRequestResponse:
    return create_task_draft_pr_endpoint(task_id=task_id, request=request, body=body, db=db)


@router.get(
    "/{task_id}/pull-request",
    response_model=TaskPullRequestResponse,
    summary="Get published GitHub Draft Pull Request details for a task",
)
def get_task_pull_request_endpoint(
    task_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> TaskPullRequestResponse:
    task, _ = _owned_task(task_id, request, db)
    task_repo = TaskRepository(db)
    pr_record = task_repo.get_pull_request(task.id, task.repository_id)
    if pr_record is None:
        raise APIError(
            404,
            ErrorCode.NOT_FOUND,
            f"No Draft Pull Request has been created for task '{task_id}'.",
        )
    return _serialize_pull_request_record(pr_record)


@router.get(
    "/{task_id}/traceability",
    response_model=TaskTraceabilityResponse,
    summary="Get end-to-end audit traceability graph from finding/issue to Draft PR (Day 5)",
)
def get_task_traceability_endpoint(
    task_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> TaskTraceabilityResponse:
    task, _ = _owned_task(task_id, request, db)
    task_repo = TaskRepository(db)
    trace = task_repo.get_task_traceability(task.id, task.repository_id)
    return TaskTraceabilityResponse.model_validate(redact_obj(trace))


@router.get(
    "/{task_id}/stale-check",
    summary="Check whether the workspace base revision has drifted relative to the repository/plan revision (Day 6)",
)
def check_task_stale_revision_endpoint(
    task_id: UUID,
    request: Request,
    current_remote_head_sha: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    task, _ = _owned_task(task_id, request, db)
    task_repo = TaskRepository(db)
    orchestrator = get_task_execution_orchestrator(request.app.state)
    return redact_obj(
        orchestrator.check_stale_base_revision(
            task=task,
            task_repo=task_repo,
            current_remote_head_sha=current_remote_head_sha,
        )
    )


# ---------------------------------------------------------------------------
# 7. Checkpoints, Crash Recovery, Invariants & Timeline Events (Week 3 Day 6 & Day 7 — F38, F39)
# ---------------------------------------------------------------------------

@router.post(
    "/{task_id}/checkpoints",
    response_model=TaskCheckpointResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Save a secret-scrubbed recovery checkpoint for a task",
)
def save_task_checkpoint_endpoint(
    task_id: UUID,
    payload: TaskCheckpointCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> TaskCheckpointResponse:
    task, _ = _owned_task(task_id, request, db)
    task_repo = TaskRepository(db)
    orchestrator = get_task_execution_orchestrator(request.app.state)

    cp = orchestrator.save_task_checkpoint(
        task=task,
        task_repo=task_repo,
        step_name=payload.step_name,
        state_data=payload.state_data,
        recovery_instructions=payload.recovery_instructions,
    )
    return _serialize_checkpoint_record(cp)


@router.get(
    "/{task_id}/checkpoints",
    response_model=list[TaskCheckpointResponse],
    summary="List persisted recovery checkpoints for a task",
)
def list_task_checkpoints_endpoint(
    task_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> list[TaskCheckpointResponse]:
    task, _ = _owned_task(task_id, request, db)
    task_repo = TaskRepository(db)
    cps = task_repo.list_checkpoints(task.id)
    return [_serialize_checkpoint_record(cp) for cp in cps]


@router.post(
    "/{task_id}/recover",
    summary="Reconcile an interrupted or failed task and its workspace while preserving the 3-attempt repair budget",
)
def recover_task_endpoint(
    task_id: UUID,
    request: Request,
    body: TaskRecoverTriggerRequest | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    task, user_id = _owned_task(task_id, request, db)
    task_repo = TaskRepository(db)
    orchestrator = get_task_execution_orchestrator(request.app.state)

    resolved_target = body.target_status if body else None
    if resolved_target is None and body and body.action == "reset_to_plan":
        resolved_target = TaskStatus.PLANNING
    recovery_res = orchestrator.recover_interrupted_task(
        task=task,
        task_repo=task_repo,
        actor_id=user_id,
        target_status=resolved_target,
    )
    return redact_obj(recovery_res)


@router.get(
    "/{task_id}/invariants",
    summary="Run Day 6 sandbox security, path confinement, disk budget, and diff immutability invariant checks",
)
def check_task_invariants_endpoint(
    task_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    task, _ = _owned_task(task_id, request, db)
    task_repo = TaskRepository(db)
    orchestrator = get_task_execution_orchestrator(request.app.state)
    return orchestrator.check_workspace_invariants(task=task, task_repo=task_repo)


@router.post(
    "/{task_id}/run-workflow",
    summary="Execute the Day 7 autonomous post-approval workflow (Execute -> Test -> Repair -> Verify -> Draft PR)",
)
def run_autonomous_workflow_endpoint(
    task_id: UUID,
    request: Request,
    body: TaskAutonomousWorkflowRequest | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    task, user_id = _owned_task(task_id, request, db)
    task_repo = TaskRepository(db)
    orchestrator = get_task_execution_orchestrator(request.app.state)

    return orchestrator.run_autonomous_post_approval_workflow(
        task=task,
        task_repo=task_repo,
        actor_id=user_id,
        step_payloads=body.step_payloads if body else None,
        run_tests=body.run_tests if body else True,
        auto_repair=body.auto_repair if body else True,
        publication_authorized=body.publication_authorized if body else False,
        pr_title=body.pr_title if body else None,
        pr_body=body.pr_body if body else None,
    )


@router.get(
    "/{task_id}/events",
    response_model=list[TaskEventResponse],
    summary="Get ordered timeline and audit events for a task",
)
def get_task_events(
    task_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> list[TaskEventResponse]:
    task, _ = _owned_task(task_id, request, db)
    task_repo = TaskRepository(db)
    events = task_repo.list_events(task.id)
    return [_serialize_event_record(e) for e in events]


# ---------------------------------------------------------------------------
# 8. Repository-Scoped Task Endpoints (Docs/week3.md §6 F31 & §7)
# ---------------------------------------------------------------------------

@repo_tasks_router.get(
    "/{repository_id}/tasks",
    response_model=PaginatedTaskListResponse,
    summary="List tasks for a specific repository",
)
def list_repository_tasks(
    repository_id: UUID,
    request: Request,
    status_filter: str | None = Query(default=None, alias="status", description="Optional status filter"),
    search: str | None = Query(default=None, description="Optional search query"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> PaginatedTaskListResponse:
    return list_tasks(
        request=request,
        repository_id=repository_id,
        status_filter=status_filter,
        search=search,
        page=page,
        page_size=page_size,
        db=db,
    )


@repo_tasks_router.post(
    "/{repository_id}/tasks",
    response_model=TaskDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a task within a specific repository",
)
def create_repository_task(
    repository_id: UUID,
    payload: TaskCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> TaskDetailResponse:
    payload.repository_id = repository_id
    return create_task(payload=payload, request=request, db=db)


# Route aliases for repo_id compatibility with Verification Gate 3.2
repo_tasks_router.add_api_route(
    "/{repo_id}/tasks",
    list_repository_tasks,
    methods=["GET"],
    response_model=PaginatedTaskListResponse,
    include_in_schema=False,
)
repo_tasks_router.add_api_route(
    "/{repo_id}/tasks",
    create_repository_task,
    methods=["POST"],
    response_model=TaskDetailResponse,
    include_in_schema=False,
)
