"""add analysis runs and findings

Revision ID: f1c2d3e4b5a6
Revises: e7b8c9d0f1a2
Create Date: 2026-10-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f1c2d3e4b5a6"
down_revision: Union[str, Sequence[str], None] = "e7b8c9d0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. analysis_runs table
    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("repository_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("feature_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("target_path", sa.String(length=1024), nullable=True),
        sa.Column("target_symbol", sa.String(length=256), nullable=True),
        sa.Column("start_line", sa.Integer(), nullable=True),
        sa.Column("end_line", sa.Integer(), nullable=True),
        sa.Column("source_revision", sa.String(length=128), nullable=True),
        sa.Column("findings_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("result_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("test_output", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_analysis_runs_repository_id"), "analysis_runs", ["repository_id"], unique=False)
    op.create_index(op.f("ix_analysis_runs_user_id"), "analysis_runs", ["user_id"], unique=False)
    op.create_index(op.f("ix_analysis_runs_feature_type"), "analysis_runs", ["feature_type"], unique=False)
    op.create_index(op.f("ix_analysis_runs_status"), "analysis_runs", ["status"], unique=False)
    op.create_index(op.f("ix_analysis_runs_source_revision"), "analysis_runs", ["source_revision"], unique=False)
    op.create_index(
        "ix_analysis_runs_repo_created",
        "analysis_runs",
        ["repository_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_analysis_runs_repo_feature_status",
        "analysis_runs",
        ["repository_id", "feature_type", "status"],
        unique=False,
    )
    op.create_index(
        "ix_analysis_runs_repo_revision",
        "analysis_runs",
        ["repository_id", "source_revision"],
        unique=False,
    )

    # 2. analysis_findings table
    op.create_table(
        "analysis_findings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("analysis_run_id", sa.UUID(), nullable=False),
        sa.Column("repository_id", sa.UUID(), nullable=False),
        sa.Column("category", sa.String(length=128), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("file_path", sa.String(length=1024), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=True),
        sa.Column("end_line", sa.Integer(), nullable=True),
        sa.Column("source_revision", sa.String(length=128), nullable=True),
        sa.Column("symbol_name", sa.String(length=256), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("suggested_fix", sa.Text(), nullable=True),
        sa.Column("confidence", sa.String(length=32), server_default="medium", nullable=False),
        sa.Column("is_uncertain", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_new_in_change", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("source_type", sa.String(length=32), server_default="AI", nullable=False),
        sa.Column("rule_id", sa.String(length=128), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_analysis_findings_analysis_run_id"), "analysis_findings", ["analysis_run_id"], unique=False)
    op.create_index(op.f("ix_analysis_findings_repository_id"), "analysis_findings", ["repository_id"], unique=False)
    op.create_index(op.f("ix_analysis_findings_category"), "analysis_findings", ["category"], unique=False)
    op.create_index(op.f("ix_analysis_findings_severity"), "analysis_findings", ["severity"], unique=False)
    op.create_index(op.f("ix_analysis_findings_file_path"), "analysis_findings", ["file_path"], unique=False)
    op.create_index(
        "ix_analysis_findings_run_severity",
        "analysis_findings",
        ["analysis_run_id", "severity"],
        unique=False,
    )
    op.create_index(
        "ix_analysis_findings_repo_file",
        "analysis_findings",
        ["repository_id", "file_path"],
        unique=False,
    )
    op.create_index(
        "ix_analysis_findings_repo_category",
        "analysis_findings",
        ["repository_id", "category"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_analysis_findings_repo_category", table_name="analysis_findings")
    op.drop_index("ix_analysis_findings_repo_file", table_name="analysis_findings")
    op.drop_index("ix_analysis_findings_run_severity", table_name="analysis_findings")
    op.drop_index(op.f("ix_analysis_findings_file_path"), table_name="analysis_findings")
    op.drop_index(op.f("ix_analysis_findings_severity"), table_name="analysis_findings")
    op.drop_index(op.f("ix_analysis_findings_category"), table_name="analysis_findings")
    op.drop_index(op.f("ix_analysis_findings_repository_id"), table_name="analysis_findings")
    op.drop_index(op.f("ix_analysis_findings_analysis_run_id"), table_name="analysis_findings")
    op.drop_table("analysis_findings")

    op.drop_index("ix_analysis_runs_repo_revision", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_repo_feature_status", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_repo_created", table_name="analysis_runs")
    op.drop_index(op.f("ix_analysis_runs_source_revision"), table_name="analysis_runs")
    op.drop_index(op.f("ix_analysis_runs_status"), table_name="analysis_runs")
    op.drop_index(op.f("ix_analysis_runs_feature_type"), table_name="analysis_runs")
    op.drop_index(op.f("ix_analysis_runs_user_id"), table_name="analysis_runs")
    op.drop_index(op.f("ix_analysis_runs_repository_id"), table_name="analysis_runs")
    op.drop_table("analysis_runs")
