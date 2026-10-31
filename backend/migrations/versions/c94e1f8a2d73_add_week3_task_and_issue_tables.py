"""add week3 github_issues table and extend task models

Revision ID: c94e1f8a2d73
Revises: b3c4d5e6f7a8
Create Date: 2026-10-28 14:00:00.000000

Owner: Om & Yug — Week 3 Day 1–2 Persistence & Recovery Schema Migration.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c94e1f8a2d73"
down_revision: Union[str, Sequence[str], None] = "b3c4d5e6f7a8"
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

    # 2. Add Week 3 Day 2 extensions to tasks table
    op.add_column(
        "tasks",
        sa.Column(
            "github_issue_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("github_issues.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_tasks_github_issue_id", "tasks", ["github_issue_id"], unique=False)
    op.add_column(
        "tasks",
        sa.Column(
            "source_ref",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "tasks",
        sa.Column(
            "requirements",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "tasks",
        sa.Column(
            "assumptions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "tasks",
        sa.Column(
            "constraints",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )

    # 3. Add Week 3 Day 2 extensions to task_plans table
    op.add_column(
        "task_plans",
        sa.Column("plan_hash", sa.String(length=128), server_default="", nullable=False),
    )
    op.add_column(
        "task_plans",
        sa.Column(
            "assumptions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "task_plans",
        sa.Column(
            "relevant_files",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "task_plans",
        sa.Column(
            "relevant_symbols",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "task_plans",
        sa.Column(
            "required_permissions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "task_plans",
        sa.Column(
            "resource_budget",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )

    # 4. Add Week 3 Day 2 extensions to task_approvals table
    op.add_column(
        "task_approvals",
        sa.Column(
            "plan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task_plans.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_task_approvals_plan_id", "task_approvals", ["plan_id"], unique=False)
    op.add_column(
        "task_approvals",
        sa.Column("plan_hash", sa.String(length=128), server_default="", nullable=False),
    )
    op.add_column(
        "task_approvals",
        sa.Column("base_revision", sa.String(length=128), nullable=True),
    )

    # 5. Add Week 3 Day 2 extensions to task_events table
    op.add_column(
        "task_events",
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "task_events",
        sa.Column("from_status", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "task_events",
        sa.Column("to_status", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "task_events",
        sa.Column("summary", sa.Text(), server_default="", nullable=False),
    )


def downgrade() -> None:
    # 5. Drop task_events extensions
    op.drop_column("task_events", "summary")
    op.drop_column("task_events", "to_status")
    op.drop_column("task_events", "from_status")
    op.drop_column("task_events", "actor_id")

    # 4. Drop task_approvals extensions
    op.drop_column("task_approvals", "base_revision")
    op.drop_column("task_approvals", "plan_hash")
    op.drop_index("ix_task_approvals_plan_id", table_name="task_approvals")
    op.drop_column("task_approvals", "plan_id")

    # 3. Drop task_plans extensions
    op.drop_column("task_plans", "resource_budget")
    op.drop_column("task_plans", "required_permissions")
    op.drop_column("task_plans", "relevant_symbols")
    op.drop_column("task_plans", "relevant_files")
    op.drop_column("task_plans", "assumptions")
    op.drop_column("task_plans", "plan_hash")

    # 2. Drop tasks extensions
    op.drop_column("tasks", "constraints")
    op.drop_column("tasks", "assumptions")
    op.drop_column("tasks", "requirements")
    op.drop_column("tasks", "source_ref")
    op.drop_index("ix_tasks_github_issue_id", table_name="tasks")
    op.drop_column("tasks", "github_issue_id")

    # 1. Drop github_issues table
    op.drop_index("ix_github_issues_origin_finding_id", table_name="github_issues")
    op.drop_index("ix_github_issues_repository_id", table_name="github_issues")
    op.drop_table("github_issues")
