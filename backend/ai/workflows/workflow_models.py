"""Data models for durable autonomous task workflow execution.

Defines:
- AutonomousWorkflowStatus: Lifecycle states for autonomous execution.
- AutonomousWorkflowInput: Serializable inputs for durable workflows.
- WorkflowStepRecord: Step-level execution tracking.
- AutonomousWorkflowResult: Complete durable workflow execution outcome.
- WorkflowStatusResponse: Public API response schema.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AutonomousWorkflowStatus(str, Enum):
    """Lifecycle states for autonomous task execution workflow."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SYNTHESIZING = "SYNTHESIZING"
    VALIDATING = "VALIDATING"
    TESTING = "TESTING"
    REPAIRING = "REPAIRING"
    VERIFYING = "VERIFYING"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AutonomousWorkflowInput(BaseModel):
    """Serializable input payload for durable workflow execution."""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(..., description="Target task UUID.")
    actor_id: str | None = Field(default=None, description="Initiating user UUID.")
    approved_plan_version: int | None = Field(default=None, description="Plan version approved by operator.")
    approved_base_revision: str | None = Field(default=None, description="Base commit SHA or branch ref.")
    step_payloads: dict[str, Any] = Field(default_factory=dict, description="Optional caller-supplied step inputs.")
    run_tests: bool = Field(default=True, description="Whether to execute tests after steps.")
    auto_repair: bool = Field(default=True, description="Whether to attempt bounded self-repair on test failure.")
    publication_authorized: bool = Field(default=False, description="Whether human has authorized Draft PR creation.")
    pr_title: str | None = Field(default=None, max_length=512, description="Custom Draft PR title.")
    pr_body: str | None = Field(default=None, max_length=10000, description="Custom Draft PR body.")


class WorkflowStepRecord(BaseModel):
    """Durable telemetry record for an individual workflow step."""

    step_name: str
    status: str  # "COMPLETED", "FAILED", "SKIPPED", "RUNNING"
    started_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    completed_at: str | None = None
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class AutonomousWorkflowResult(BaseModel):
    """Complete persistent state and execution outcome of a durable workflow."""

    workflow_id: str
    task_id: str
    status: AutonomousWorkflowStatus
    current_step: str | None = None
    completed_steps: list[str] = Field(default_factory=list)
    step_records: dict[str, WorkflowStepRecord] = Field(default_factory=dict)
    verification: dict[str, Any] | None = None
    pull_request: dict[str, Any] | None = None
    error_summary: str | None = None
    started_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    completed_at: str | None = None
    resumed_from_checkpoint: bool = False


class WorkflowStatusResponse(BaseModel):
    """API response schema for GET /api/v1/tasks/{task_id}/workflow-status."""

    task_id: str
    workflow_id: str
    status: AutonomousWorkflowStatus
    current_step: str | None = None
    completed_steps: list[str] = Field(default_factory=list)
    progress_percentage: int = 0
    verification: dict[str, Any] | None = None
    pull_request: dict[str, Any] | None = None
    error_summary: str | None = None
    started_at: str
    updated_at: str
    completed_at: str | None = None
    status_url: str = ""
