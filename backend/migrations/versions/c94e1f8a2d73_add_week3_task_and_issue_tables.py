"""add week3 task, plan, approval, event, and github_issues tables

Revision ID: c94e1f8a2d73
Revises: b627460d74e0
Create Date: 2026-10-28 14:00:00.000000

Owner: Om — Week 3 Day 1–2 Persistence & Recovery Schema Migration.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c94e1f8a2d73"
down_revision: Union[str, Sequence[str], None] = "b627460d74e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. github_issues table
    op.create_table(
        "github_issues",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "repository_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("issue_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("state", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("labels", sa.JSON(), nullable=False),
        sa.Column("html_url", sa.String(length=1024), nullable=False),
        sa.Column("author", sa.String(length=255), nullable=True),
        sa.Column(
            "origin_finding_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("analysis_findings.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("repository_id", "issue_number", name="uq_github_issues_repo_issue_number"),
    )
    op.create_index("ix_github_issues_repository_id", "github_issues", ["repository_id"], unique=False)
    op.create_index("ix_github_issues_origin_finding_id", "github_issues", ["origin_finding_id"], unique=False)
    op.create_index("ix_github_issues_repo_number", "github_issues", ["repository_id", "issue_number"], unique=False)

    # 2. tasks table
    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "repository_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "github_issue_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("github_issues.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "origin_finding_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("analysis_findings.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False, server_default="CREATED"),
        sa.Column("source_type", sa.String(length=64), nullable=False, server_default="USER_PROMPT"),
        sa.Column("source_ref", sa.JSON(), nullable=False),
        sa.Column("requirements", sa.JSON(), nullable=False),
        sa.Column("assumptions", sa.JSON(), nullable=False),
        sa.Column("constraints", sa.JSON(), nullable=False),
        sa.Column("base_revision", sa.String(length=128), nullable=True),
        sa.Column("plan_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("approved_plan_version", sa.Integer(), nullable=True),
        sa.Column("repair_attempts_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("repair_attempts_max", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_tasks_repository_id", "tasks", ["repository_id"], unique=False)
    op.create_index("ix_tasks_user_id", "tasks", ["user_id"], unique=False)
    op.create_index("ix_tasks_github_issue_id", "tasks", ["github_issue_id"], unique=False)
    op.create_index("ix_tasks_origin_finding_id", "tasks", ["origin_finding_id"], unique=False)
    op.create_index("ix_tasks_status", "tasks", ["status"], unique=False)
    op.create_index("ix_tasks_repo_status", "tasks", ["repository_id", "status"], unique=False)
    op.create_index("ix_tasks_user_created", "tasks", ["user_id", "created_at"], unique=False)

    # 3. task_plans table
    op.create_table(
        "task_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("base_revision", sa.String(length=128), nullable=True),
        sa.Column("plan_hash", sa.String(length=128), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("problem_statement", sa.Text(), nullable=False, server_default=""),
        sa.Column("assumptions", sa.JSON(), nullable=False),
        sa.Column("relevant_files", sa.JSON(), nullable=False),
        sa.Column("relevant_symbols", sa.JSON(), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("expected_files", sa.JSON(), nullable=False),
        sa.Column("tests_to_run", sa.JSON(), nullable=False),
        sa.Column("validation_strategy", sa.JSON(), nullable=False),
        sa.Column("risks", sa.JSON(), nullable=False),
        sa.Column("required_permissions", sa.JSON(), nullable=False),
        sa.Column("resource_budget", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False, server_default="PENDING_APPROVAL"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("task_id", "plan_version", name="uq_task_plans_task_version"),
    )
    op.create_index("ix_task_plans_task_id", "task_plans", ["task_id"], unique=False)
    op.create_index("ix_task_plans_task_version", "task_plans", ["task_id", "plan_version"], unique=False)

    # 4. task_approvals table
    op.create_table(
        "task_approvals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "plan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column(
            "approver_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("base_revision", sa.String(length=128), nullable=True),
        sa.Column("plan_hash", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_task_approvals_task_id", "task_approvals", ["task_id"], unique=False)
    op.create_index("ix_task_approvals_plan_id", "task_approvals", ["plan_id"], unique=False)
    op.create_index("ix_task_approvals_approver_id", "task_approvals", ["approver_id"], unique=False)
    op.create_index("ix_task_approvals_task_version", "task_approvals", ["task_id", "plan_version"], unique=False)

    # 5. task_events table
    op.create_table(
        "task_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("from_status", sa.String(length=64), nullable=True),
        sa.Column("to_status", sa.String(length=64), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_task_events_task_id", "task_events", ["task_id"], unique=False)
    op.create_index("ix_task_events_event_type", "task_events", ["event_type"], unique=False)
    op.create_index("ix_task_events_task_created", "task_events", ["task_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_task_events_task_created", table_name="task_events")
    op.drop_index("ix_task_events_event_type", table_name="task_events")
    op.drop_index("ix_task_events_task_id", table_name="task_events")
    op.drop_table("task_events")

    op.drop_index("ix_task_approvals_task_version", table_name="task_approvals")
    op.drop_index("ix_task_approvals_approver_id", table_name="task_approvals")
    op.drop_index("ix_task_approvals_plan_id", table_name="task_approvals")
    op.drop_index("ix_task_approvals_task_id", table_name="task_approvals")
    op.drop_table("task_approvals")

    op.drop_index("ix_task_plans_task_version", table_name="task_plans")
    op.drop_index("ix_task_plans_task_id", table_name="task_plans")
    op.drop_table("task_plans")

    op.drop_index("ix_tasks_user_created", table_name="tasks")
    op.drop_index("ix_tasks_repo_status", table_name="tasks")
    op.drop_index("ix_tasks_status", table_name="tasks")
    op.drop_index("ix_tasks_origin_finding_id", table_name="tasks")
    op.drop_index("ix_tasks_github_issue_id", table_name="tasks")
    op.drop_index("ix_tasks_user_id", table_name="tasks")
    op.drop_index("ix_tasks_repository_id", table_name="tasks")
    op.drop_table("tasks")

    op.drop_index("ix_github_issues_repo_number", table_name="github_issues")
    op.drop_index("ix_github_issues_origin_finding_id", table_name="github_issues")
    op.drop_index("ix_github_issues_repository_id", table_name="github_issues")
    op.drop_table("github_issues")
