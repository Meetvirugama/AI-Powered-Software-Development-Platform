"""Pydantic schemas for Week 3 Workflow Automation, Task Lifecycle, and Recovery.

Owner: Om (Database & Persistence) in collaboration with Yug (API) & Meet (Planner).
Defines standard API contracts for:
- Task creation, normalized responses, and state machine transitions
- Plan proposals, steps, risks, and approvals
- Workspace, test runs, and bounded repairs
- Independent verification results
- Checkpoints and audit event timeline
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field

from app.models.task import (
    ApprovalDecision,
    ExecutionStatus,
    RepairResult,
    TaskPlanStatus,
    TaskSourceType,
    TaskStatus,
    TestRunStatus,
    ToolInvocationStatus,
    VerificationStatus,
    WorkspaceStatus,
)


class TaskSourceReference(BaseModel):
    """Source reference for imported issues, bug findings, or requirements."""

    type: str = Field(..., description="Source origin type (GITHUB_ISSUE, BUG_FINDING, etc.)")
    issue_number: Optional[int] = Field(None, description="GitHub issue number if applicable")
    url: Optional[str] = Field(None, description="Direct URL to issue or finding")
    finding_id: Optional[str] = Field(None, description="Week 2 AnalysisFinding UUID if applicable")


class TaskCreateRequest(BaseModel):
    """Request payload to create or import a workflow task."""

    title: str = Field(..., min_length=1, max_length=512, description="Short task summary")
    description: Optional[str] = Field(None, description="Detailed problem statement or requirement")
    source_type: TaskSourceType = Field(TaskSourceType.GITHUB_ISSUE, description="Task source type")
    source_id: Optional[str] = Field(None, description="External issue number or finding ID")
    source_metadata: Optional[dict[str, Any]] = Field(None, description="Source issue or finding metadata")
    finding_id: Optional[uuid.UUID] = Field(None, description="Foreign key to analysis finding")
    base_revision: str = Field("main", description="Git branch or commit SHA base revision")


class TaskResponse(BaseModel):
    """Canonical task response envelope (§7.3)."""

    task_id: str
    repository_id: str
    user_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    status: str
    source_type: str
    source_id: Optional[str] = None
    source_metadata: Optional[dict[str, Any]] = None
    finding_id: Optional[str] = None
    base_revision: str
    plan_version: int
    approved_plan_version: Optional[int] = None
    repair_attempts_used: int
    repair_attempts_max: int
    context_summary: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class TaskListResponse(BaseModel):
    """Paginated task list envelope."""

    tasks: List[TaskResponse]
    total: int
    offset: int
    limit: int


class TaskPlanStep(BaseModel):
    """Single ordered step within an implementation plan."""

    step_id: str = Field(..., description="Unique step identifier (e.g. step_1)")
    description: str = Field(..., description="Clear explanation of the change to be made")
    expected_files: List[str] = Field(default_factory=list, description="Files to inspect or modify")
    verification: List[str] = Field(default_factory=list, description="Verification criteria for this step")


class TaskPlanCreateRequest(BaseModel):
    """Request to propose or revise an implementation plan."""

    summary: str = Field(..., max_length=512, description="High-level plan summary")
    problem_statement: Optional[str] = Field(None, description="Problem breakdown")
    steps: List[TaskPlanStep] = Field(..., min_length=1, description="Ordered implementation steps")
    expected_files: Optional[List[str]] = Field(None, description="All files expected to be changed")
    tests_to_run: Optional[List[str]] = Field(None, description="Target tests to execute")
    validation_strategy: Optional[str] = Field(None, description="Verification and safety strategy")
    risks: Optional[List[str]] = Field(None, description="Identified risks or side effects")
    base_revision: Optional[str] = Field(None, description="Target base revision")


class TaskPlanResponse(BaseModel):
    """Structured implementation plan response."""

    plan_id: str
    task_id: str
    version: int
    base_revision: str
    summary: str
    problem_statement: Optional[str] = None
    steps: List[dict[str, Any]]
    expected_files: Optional[List[str]] = None
    tests_to_run: Optional[List[str]] = None
    validation_strategy: Optional[str] = None
    risks: Optional[List[str]] = None
    status: str
    created_at: Optional[str] = None


class TaskApprovalRequest(BaseModel):
    """Request to approve or reject a plan version."""

    plan_version: int = Field(..., ge=1, description="The exact plan version being decided")
    feedback: Optional[str] = Field(None, description="Optional feedback or rejection reason")


class TaskApprovalResponse(BaseModel):
    """Immutable task approval outcome."""

    approval_id: str
    task_id: str
    plan_version: int
    user_id: Optional[str] = None
    decision: str
    feedback: Optional[str] = None
    created_at: Optional[str] = None


class TaskCheckpointResponse(BaseModel):
    """Sanitized checkpoint for worker failure recovery."""

    checkpoint_id: str
    task_id: str
    step_name: str
    state_data: dict[str, Any]
    recovery_instructions: Optional[str] = None
    created_at: Optional[str] = None


class TaskEventResponse(BaseModel):
    """Ordered event item for dashboard timeline."""

    event_id: str
    task_id: str
    event_type: str
    event_data: Optional[dict[str, Any]] = None
    user_id: Optional[str] = None
    created_at: Optional[str] = None


class VerificationResultResponse(BaseModel):
    """Independent verification check outcome."""

    verification_id: str
    task_id: str
    verified_revision: str
    status: str
    checks: Optional[List[dict[str, Any]]] = None
    blocking_findings: Optional[List[dict[str, Any]]] = None
    warnings: Optional[List[dict[str, Any]]] = None
    summary: Optional[str] = None
    created_at: Optional[str] = None


class TaskPullRequestResponse(BaseModel):
    """Created GitHub Draft PR details."""

    pr_id: str
    task_id: str
    repository_id: str
    pr_number: Optional[int] = None
    pr_url: str
    base_branch: str
    head_branch: str
    head_sha: str
    is_draft: bool
    title: str
    body: Optional[str] = None
    created_at: Optional[str] = None


__all__ = [
    "TaskSourceReference",
    "TaskCreateRequest",
    "TaskResponse",
    "TaskListResponse",
    "TaskPlanStep",
    "TaskPlanCreateRequest",
    "TaskPlanResponse",
    "TaskApprovalRequest",
    "TaskApprovalResponse",
    "TaskCheckpointResponse",
    "TaskEventResponse",
    "VerificationResultResponse",
    "TaskPullRequestResponse",
]
