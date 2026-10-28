"""Week 3 Day 1 & Day 2 (F32, F38, F39) — Task Intake, Structured Planning & Human Approval Gate APIs.

Owners:
- Yug (Task lifecycle REST endpoints: create, list, detail, plan, approve, reject, execute, cancel, events)
- Meet & Dev (TaskPlanner integration & PlannerSchema validation)
- Sukun (Server-enforced approval gate & tenant isolation)
- Om (TaskRepository persistence, versioned plans, immutable approvals, and timeline events)

Endpoints:
- POST /api/v1/tasks
- GET  /api/v1/tasks
- GET  /api/v1/tasks/{task_id}
- POST /api/v1/tasks/{task_id}/plan
- GET  /api/v1/tasks/{task_id}/plan
- POST /api/v1/tasks/{task_id}/approve
- POST /api/v1/tasks/{task_id}/reject
- POST /api/v1/tasks/{task_id}/execute
- POST /api/v1/tasks/{task_id}/cancel
- GET  /api/v1/tasks/{task_id}/events
- GET  /api/v1/repositories/{repository_id}/tasks
- POST /api/v1/repositories/{repository_id}/tasks
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from ai.services.task_planner import TaskPlanner
from app.core.database import get_db
from app.core.errors import APIError, ErrorCode
from app.core.secret_redaction import redact, redact_obj
from app.models.repository import Repository
from app.models.task import AgentTask, TaskApprovalRecord, TaskEventRecord, TaskPlanRecord
from app.repositories.repository_repository import RepositoryRepository
from app.repositories.task_repository import TaskRepository
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
    TaskAssumption,
    TaskConstraint,
    TaskCreateRequest,
    TaskDetailResponse,
    TaskRequirement,
    TaskSourceReference,
    TaskStatus,
    TaskSummaryResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tasks", tags=["tasks"])
repo_tasks_router = APIRouter(prefix="/repositories", tags=["tasks"])


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


def _owned_task(task_id: UUID, request: Request, db: Session) -> tuple[AgentTask, UUID]:
    user_id = _request_user_id(request)
    task = TaskRepository(db).get_task_for_user(task_id, user_id)
    if task is None:
        raise APIError(
            404,
            ErrorCode.TASK_NOT_FOUND,
            f"Task '{task_id}' was not found or you do not have access.",
        )
    return task, user_id


def _serialize_plan_record(plan: TaskPlanRecord, task: AgentTask) -> TaskPlanResponse:
    is_approved = (
        task.approved_plan_version is not None
        and task.approved_plan_version == plan.plan_version
        and task.status not in (TaskStatus.REJECTED.value, TaskStatus.PENDING_APPROVAL.value)
    )
    payload = {
        "plan_id": str(plan.id),
        "task_id": str(plan.task_id),
        "plan_version": plan.plan_version,
        "base_revision": plan.base_revision,
        "plan_hash": plan.plan_hash,
        "summary": redact(plan.summary),
        "problem_statement": redact(plan.problem_statement or plan.summary),
        "assumptions": [TaskAssumption.model_validate(a) for a in (plan.assumptions or [])],
        "relevant_files": list(plan.relevant_files or []),
        "relevant_symbols": list(plan.relevant_symbols or []),
        "steps": [PlanStep.model_validate(s) for s in (plan.steps or [])],
        "expected_files": list(plan.expected_files or []),
        "tests_to_run": list(plan.tests_to_run or []),
        "validation_strategy": list(plan.validation_strategy or []),
        "risks": [PlanRisk.model_validate(r) for r in (plan.risks or [])],
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
    payload = {
        "approval_id": str(record.id),
        "task_id": str(record.task_id),
        "plan_id": str(record.plan_id),
        "plan_version": record.plan_version,
        "approver_id": str(record.approver_id),
        "decision": record.decision,
        "comment": redact(record.comment) if record.comment else None,
        "base_revision": record.base_revision,
        "plan_hash": record.plan_hash,
        "task_status": TaskStatus(task.status),
        "approved_plan_version": task.approved_plan_version,
        "created_at": record.created_at.isoformat() if record.created_at else "",
    }
    return TaskApprovalResponse.model_validate(redact_obj(payload))


def _serialize_event_record(event: TaskEventRecord) -> TaskEventResponse:
    payload = {
        "event_id": str(event.id),
        "task_id": str(event.task_id),
        "event_type": event.event_type,
        "actor_id": str(event.actor_id) if event.actor_id else None,
        "from_status": event.from_status,
        "to_status": event.to_status,
        "summary": redact(event.summary),
        "payload": redact_obj(event.payload or {}),
        "created_at": event.created_at.isoformat() if event.created_at else "",
    }
    return TaskEventResponse.model_validate(payload)


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
        "description": redact(task.description),
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
    payload = {
        "task_id": str(task.id),
        "repository_id": str(task.repository_id),
        "title": redact(task.title),
        "status": TaskStatus(task.status),
        "source_type": source_ref.type,
        "source": source_ref.model_dump(mode="json"),
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
        offset=(page - 1) * page_size,
        limit=page_size,
    )
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
        plan_schema = await planner.generate_plan(
            task,
            db=db,
            revision_notes=body.revision_notes if body else None,
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

    approval = task_repo.approve_plan(
        task=task,
        approver_id=user_id,
        plan_version=body.plan_version if body else None,
        base_revision=body.base_revision if body else None,
        comment=body.comment if body else None,
    )
    return _serialize_approval_record(approval, task)


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
    return _serialize_approval_record(approval, task)


# ---------------------------------------------------------------------------
# 4. Server-Enforced Execution Gate & Timeline Events (Sukun W3 Day 2)
# ---------------------------------------------------------------------------

@router.post(
    "/{task_id}/execute",
    response_model=TaskDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Validate human approval gate and transition approved task to WORKSPACE_SETUP",
)
def execute_approved_task(
    task_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> TaskDetailResponse:
    task, user_id = _owned_task(task_id, request, db)
    task_repo = TaskRepository(db)

    verified_plan = task_repo.verify_execution_approval_gate(task)

    if TaskStatus(task.status) == TaskStatus.APPROVED:
        task_repo.transition_status(
            task,
            TaskStatus.WORKSPACE_SETUP,
            actor_id=user_id,
            event_type="EXECUTION_GATE_PASSED",
            summary=(
                f"Approval gate verified for plan v{verified_plan.plan_version} "
                f"(hash {verified_plan.plan_hash[:12]}). Entering WORKSPACE_SETUP."
            ),
            payload={
                "approved_plan_version": verified_plan.plan_version,
                "plan_hash": verified_plan.plan_hash,
                "base_revision": verified_plan.base_revision,
            },
        )

    return _serialize_task_detail(task, task_repo)


@router.post(
    "/{task_id}/cancel",
    response_model=TaskDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel an active or pending task",
)
def cancel_task(
    task_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> TaskDetailResponse:
    task, user_id = _owned_task(task_id, request, db)
    task_repo = TaskRepository(db)

    task_repo.transition_status(
        task,
        TaskStatus.CANCELLED,
        actor_id=user_id,
        event_type="TASK_CANCELLED",
        summary="Task cancelled by user.",
    )
    return _serialize_task_detail(task, task_repo)


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
# 5. Repository-Scoped Task Endpoints (Docs/week3.md §6 F31 & §7)
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
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> PaginatedTaskListResponse:
    return list_tasks(
        request=request,
        repository_id=repository_id,
        status_filter=status_filter,
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
