"""add pull_requests table

Revision ID: a1b2c3d4e5f6
Revises: f1c2d3e4b5a6
Create Date: 2026-04-06 10:00:00.000000

Owner: Om / Parth — Week 2 Day 5/7 Schema Migration for `pull_requests`.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f1c2d3e4b5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pull_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "repository_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("branch", sa.String(length=255), nullable=False),
        sa.Column("base_branch", sa.String(length=255), nullable=False, server_default="main"),
        sa.Column("changed_files", sa.JSON(), nullable=False),
        sa.Column("commit_message", sa.Text(), nullable=False),
        sa.Column("test_summary", sa.Text(), nullable=False),
        sa.Column("verification_summary", sa.Text(), nullable=False),
        sa.Column("pr_number", sa.Integer(), nullable=True),
        sa.Column("pr_url", sa.String(length=512), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="prepared"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_pull_requests_task_id", "pull_requests", ["task_id"], unique=False)
    op.create_index("ix_pull_requests_repository_id", "pull_requests", ["repository_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_pull_requests_repository_id", table_name="pull_requests")
    op.drop_index("ix_pull_requests_task_id", table_name="pull_requests")
    op.drop_table("pull_requests")
