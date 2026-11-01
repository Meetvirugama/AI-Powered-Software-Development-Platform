"""add workflow automation tables

Revision ID: b3c4d5e6f7a8
Revises: a1b2c3d4e5f6
Create Date: 2026-10-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. tasks table
    op.create_table(
        "tasks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("repository_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="CREATED", nullable=False),
        sa.Column("source_type", sa.String(length=64), server_default="GITHUB_ISSUE", nullable=False),
        sa.Column("source_id", sa.String(length=256), nullable=True),
        sa.Column("source_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("finding_id", sa.UUID(), nullable=True),
        sa.Column("base_revision", sa.String(length=128), server_default="main", nullable=False),
        sa.Column("plan_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("approved_plan_version", sa.Integer(), nullable=True),
        sa.Column("repair_attempts_used", sa.Integer(), server_default="0", nullable=False),
        sa.Column("repair_attempts_max", sa.Integer(), server_default="3", nullable=False),
        sa.Column("context_summary", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["finding_id"], ["analysis_findings.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tasks_repository_id"), "tasks", ["repository_id"], unique=False)
    op.create_index(op.f("ix_tasks_user_id"), "tasks", ["user_id"], unique=False)
    op.create_index(op.f("ix_tasks_status"), "tasks", ["status"], unique=False)
    op.create_index(op.f("ix_tasks_source_type"), "tasks", ["source_type"], unique=False)
    op.create_index(op.f("ix_tasks_finding_id"), "tasks", ["finding_id"], unique=False)
    op.create_index(
        "ix_tasks_repo_status",
        "tasks",
        ["repository_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_tasks_repo_created",
        "tasks",
        ["repository_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_tasks_repo_source",
        "tasks",
        ["repository_id", "source_type", "source_id"],
        unique=False,
    )

    # 2. task_plans table
    op.create_table(
        "task_plans",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("base_revision", sa.String(length=128), nullable=False),
        sa.Column("summary", sa.String(length=512), nullable=False),
        sa.Column("problem_statement", sa.Text(), nullable=True),
        sa.Column("steps", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expected_files", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("tests_to_run", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("validation_strategy", sa.Text(), nullable=True),
        sa.Column("risks", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="PROPOSED", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_task_plans_task_id"), "task_plans", ["task_id"], unique=False)
    op.create_index(op.f("ix_task_plans_status"), "task_plans", ["status"], unique=False)
    op.create_index(
        "ix_task_plans_task_version",
        "task_plans",
        ["task_id", "version"],
        unique=True,
    )

    # 3. task_approvals table
    op.create_table(
        "task_approvals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_task_approvals_task_id"), "task_approvals", ["task_id"], unique=False)
    op.create_index(op.f("ix_task_approvals_user_id"), "task_approvals", ["user_id"], unique=False)
    op.create_index(
        "ix_task_approvals_task_plan",
        "task_approvals",
        ["task_id", "plan_version"],
        unique=False,
    )

    # 4. workspaces table
    op.create_table(
        "workspaces",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("workspace_path", sa.String(length=1024), nullable=False),
        sa.Column("task_branch", sa.String(length=256), nullable=False),
        sa.Column("base_revision", sa.String(length=128), nullable=False),
        sa.Column("current_revision", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="NOT_CREATED", nullable=False),
        sa.Column("cleanup_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id"),
    )
    op.create_index(op.f("ix_workspaces_task_id"), "workspaces", ["task_id"], unique=True)
    op.create_index(op.f("ix_workspaces_status"), "workspaces", ["status"], unique=False)

    # 5. task_executions table
    op.create_table(
        "task_executions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), server_default="1", nullable=False),
        sa.Column("worker_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="STARTED", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_task_executions_task_id"), "task_executions", ["task_id"], unique=False)
    op.create_index(op.f("ix_task_executions_status"), "task_executions", ["status"], unique=False)

    # 6. tool_invocations table
    op.create_table(
        "tool_invocations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("sanitized_arguments", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("output_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tool_invocations_task_id"), "tool_invocations", ["task_id"], unique=False)
    op.create_index(op.f("ix_tool_invocations_tool_name"), "tool_invocations", ["tool_name"], unique=False)
    op.create_index(op.f("ix_tool_invocations_status"), "tool_invocations", ["status"], unique=False)

    # 7. test_runs table
    op.create_table(
        "test_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("command", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("tests_total", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tests_passed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tests_failed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("sanitized_output", sa.Text(), nullable=True),
        sa.Column("target_revision", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_test_runs_task_id"), "test_runs", ["task_id"], unique=False)
    op.create_index(op.f("ix_test_runs_status"), "test_runs", ["status"], unique=False)

    # 8. repair_attempts table
    op.create_table(
        "repair_attempts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("failure_classification", sa.String(length=128), nullable=True),
        sa.Column("diagnosis", sa.Text(), nullable=True),
        sa.Column("applied_patch", sa.Text(), nullable=True),
        sa.Column("result", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_repair_attempts_task_id"), "repair_attempts", ["task_id"], unique=False)
    op.create_index(
        "ix_repair_attempts_task_attempt",
        "repair_attempts",
        ["task_id", "attempt_number"],
        unique=True,
    )

    # 9. verification_results table
    op.create_table(
        "verification_results",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("verified_revision", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("checks", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("blocking_findings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_verification_results_task_id"), "verification_results", ["task_id"], unique=False)
    op.create_index(op.f("ix_verification_results_verified_revision"), "verification_results", ["verified_revision"], unique=False)
    op.create_index(op.f("ix_verification_results_status"), "verification_results", ["status"], unique=False)

    # 10. task_checkpoints table
    op.create_table(
        "task_checkpoints",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("step_name", sa.String(length=128), nullable=False),
        sa.Column("state_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("recovery_instructions", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_task_checkpoints_task_id"), "task_checkpoints", ["task_id"], unique=False)
    op.create_index(op.f("ix_task_checkpoints_step_name"), "task_checkpoints", ["step_name"], unique=False)

    # 11. task_events table
    op.create_table(
        "task_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("event_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_task_events_task_id"), "task_events", ["task_id"], unique=False)
    op.create_index(op.f("ix_task_events_event_type"), "task_events", ["event_type"], unique=False)
    op.create_index(op.f("ix_task_events_user_id"), "task_events", ["user_id"], unique=False)
    op.create_index(
        "ix_task_events_task_created",
        "task_events",
        ["task_id", "created_at"],
        unique=False,
    )

    # 12. task_pull_requests table
    op.create_table(
        "task_pull_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("repository_id", sa.UUID(), nullable=False),
        sa.Column("github_pr_id", sa.Integer(), nullable=True),
        sa.Column("pr_number", sa.Integer(), nullable=True),
        sa.Column("pr_url", sa.String(length=512), nullable=False),
        sa.Column("base_branch", sa.String(length=256), nullable=False),
        sa.Column("head_branch", sa.String(length=256), nullable=False),
        sa.Column("head_sha", sa.String(length=128), nullable=False),
        sa.Column("is_draft", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id"),
    )
    op.create_index(op.f("ix_task_pull_requests_task_id"), "task_pull_requests", ["task_id"], unique=True)
    op.create_index(op.f("ix_task_pull_requests_repository_id"), "task_pull_requests", ["repository_id"], unique=False)
    op.create_index(op.f("ix_task_pull_requests_pr_number"), "task_pull_requests", ["pr_number"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_task_pull_requests_pr_number"), table_name="task_pull_requests")
    op.drop_index(op.f("ix_task_pull_requests_repository_id"), table_name="task_pull_requests")
    op.drop_index(op.f("ix_task_pull_requests_task_id"), table_name="task_pull_requests")
    op.drop_table("task_pull_requests")

    op.drop_index("ix_task_events_task_created", table_name="task_events")
    op.drop_index(op.f("ix_task_events_user_id"), table_name="task_events")
    op.drop_index(op.f("ix_task_events_event_type"), table_name="task_events")
    op.drop_index(op.f("ix_task_events_task_id"), table_name="task_events")
    op.drop_table("task_events")

    op.drop_index(op.f("ix_task_checkpoints_step_name"), table_name="task_checkpoints")
    op.drop_index(op.f("ix_task_checkpoints_task_id"), table_name="task_checkpoints")
    op.drop_table("task_checkpoints")

    op.drop_index(op.f("ix_verification_results_status"), table_name="verification_results")
    op.drop_index(op.f("ix_verification_results_verified_revision"), table_name="verification_results")
    op.drop_index(op.f("ix_verification_results_task_id"), table_name="verification_results")
    op.drop_table("verification_results")

    op.drop_index("ix_repair_attempts_task_attempt", table_name="repair_attempts")
    op.drop_index(op.f("ix_repair_attempts_task_id"), table_name="repair_attempts")
    op.drop_table("repair_attempts")

    op.drop_index(op.f("ix_test_runs_status"), table_name="test_runs")
    op.drop_index(op.f("ix_test_runs_task_id"), table_name="test_runs")
    op.drop_table("test_runs")

    op.drop_index(op.f("ix_tool_invocations_status"), table_name="tool_invocations")
    op.drop_index(op.f("ix_tool_invocations_tool_name"), table_name="tool_invocations")
    op.drop_index(op.f("ix_tool_invocations_task_id"), table_name="tool_invocations")
    op.drop_table("tool_invocations")

    op.drop_index(op.f("ix_task_executions_status"), table_name="task_executions")
    op.drop_index(op.f("ix_task_executions_task_id"), table_name="task_executions")
    op.drop_table("task_executions")

    op.drop_index(op.f("ix_workspaces_status"), table_name="workspaces")
    op.drop_index(op.f("ix_workspaces_task_id"), table_name="workspaces")
    op.drop_table("workspaces")

    op.drop_index("ix_task_approvals_task_plan", table_name="task_approvals")
    op.drop_index(op.f("ix_task_approvals_user_id"), table_name="task_approvals")
    op.drop_index(op.f("ix_task_approvals_task_id"), table_name="task_approvals")
    op.drop_table("task_approvals")

    op.drop_index("ix_task_plans_task_version", table_name="task_plans")
    op.drop_index(op.f("ix_task_plans_status"), table_name="task_plans")
    op.drop_index(op.f("ix_task_plans_task_id"), table_name="task_plans")
    op.drop_table("task_plans")

    op.drop_index("ix_tasks_repo_source", table_name="tasks")
    op.drop_index("ix_tasks_repo_created", table_name="tasks")
    op.drop_index("ix_tasks_repo_status", table_name="tasks")
    op.drop_index(op.f("ix_tasks_finding_id"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_source_type"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_status"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_user_id"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_repository_id"), table_name="tasks")
    op.drop_table("tasks")
