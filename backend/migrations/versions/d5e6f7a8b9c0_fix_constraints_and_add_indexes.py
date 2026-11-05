"""Fix repository_files constraints and add missing query indexes (Audit A1.5, B4.1)

Revision ID: d5e6f7a8b9c0
Revises: c94e1f8a2d73
Create Date: 2026-11-05 21:50:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "c94e1f8a2d73"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. repository_files unique constraint and composite index (Audit A1.5)
    # Deduplicate if duplicate rows exist prior to creating the unique constraint
    op.execute(
        """
        DELETE FROM repository_files a USING repository_files b
        WHERE a.id < b.id
          AND a.repository_id = b.repository_id
          AND a.path = b.path;
        """
    )
    try:
        op.create_unique_constraint(
            "uq_repository_files_repo_path",
            "repository_files",
            ["repository_id", "path"],
        )
    except Exception:
        pass

    try:
        op.create_index(
            "ix_repository_files_repository_id_path",
            "repository_files",
            ["repository_id", "path"],
            unique=False,
        )
    except Exception:
        pass

    # 2. symbol_edges source and target symbol indexes (Audit B4.1)
    try:
        op.create_index(
            "ix_symbol_edges_source_symbol_id",
            "symbol_edges",
            ["source_symbol_id"],
            unique=False,
        )
    except Exception:
        pass

    try:
        op.create_index(
            "ix_symbol_edges_target_symbol_id",
            "symbol_edges",
            ["target_symbol_id"],
            unique=False,
        )
    except Exception:
        pass

    # 3. code_symbols repo + name lookup index (Audit B4.1)
    try:
        op.create_index(
            "ix_code_symbols_repository_id_name",
            "code_symbols",
            ["repository_id", "name"],
            unique=False,
        )
    except Exception:
        pass

    # 4. code_chunks file_id + start_line index (Audit B4.1)
    try:
        op.create_index(
            "ix_code_chunks_file_id_start_line",
            "code_chunks",
            ["file_id", "start_line"],
            unique=False,
        )
    except Exception:
        pass

    # 5. analysis_runs composite index (Audit B4.1)
    try:
        op.create_index(
            "ix_analysis_runs_repo_feature_created",
            "analysis_runs",
            ["repository_id", "feature_type", sa.text("created_at DESC")],
            unique=False,
        )
    except Exception:
        pass

    # 6. task_events composite index (Audit B4.1)
    try:
        op.create_index(
            "ix_task_events_task_id_created_at",
            "task_events",
            ["task_id", "created_at"],
            unique=False,
        )
    except Exception:
        pass

    # 7. tasks composite index (Audit B4.1)
    try:
        op.create_index(
            "ix_tasks_repo_status_created_at",
            "tasks",
            ["repository_id", "status", sa.text("created_at DESC")],
            unique=False,
        )
    except Exception:
        pass


def downgrade() -> None:
    try:
        op.drop_index("ix_tasks_repo_status_created_at", table_name="tasks")
    except Exception:
        pass
    try:
        op.drop_index("ix_task_events_task_id_created_at", table_name="task_events")
    except Exception:
        pass
    try:
        op.drop_index("ix_analysis_runs_repo_feature_created", table_name="analysis_runs")
    except Exception:
        pass
    try:
        op.drop_index("ix_code_chunks_file_id_start_line", table_name="code_chunks")
    except Exception:
        pass
    try:
        op.drop_index("ix_code_symbols_repository_id_name", table_name="code_symbols")
    except Exception:
        pass
    try:
        op.drop_index("ix_symbol_edges_target_symbol_id", table_name="symbol_edges")
    except Exception:
        pass
    try:
        op.drop_index("ix_symbol_edges_source_symbol_id", table_name="symbol_edges")
    except Exception:
        pass
    try:
        op.drop_index("ix_repository_files_repository_id_path", table_name="repository_files")
    except Exception:
        pass
    try:
        op.drop_constraint("uq_repository_files_repo_path", "repository_files", type_="unique")
    except Exception:
        pass
