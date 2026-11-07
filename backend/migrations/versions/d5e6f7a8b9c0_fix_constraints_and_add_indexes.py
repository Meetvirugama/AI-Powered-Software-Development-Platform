"""Fix repository_files constraints and add missing query indexes (Audit A1.5, B4.1)

Revision ID: d5e6f7a8b9c0
Revises: c94e1f8a2d73
Create Date: 2026-11-05 21:50:00.000000
"""

from typing import Any, Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "c94e1f8a2d73"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # 1. Repoint dependent records from duplicate file rows before deleting (Audit A1.5)
    # Update code_chunks and code_symbols references from lower-ID duplicates to the surviving keeper file
    op.execute(
        """
        UPDATE code_chunks c
        SET file_id = keeper.id
        FROM repository_files dup
        JOIN repository_files keeper
          ON dup.repository_id = keeper.repository_id
         AND dup.path = keeper.path
         AND dup.id < keeper.id
        WHERE c.file_id = dup.id;
        """
    )
    op.execute(
        """
        UPDATE code_symbols s
        SET file_id = keeper.id
        FROM repository_files dup
        JOIN repository_files keeper
          ON dup.repository_id = keeper.repository_id
         AND dup.path = keeper.path
         AND dup.id < keeper.id
        WHERE s.file_id = dup.id;
        """
    )
    op.execute(
        """
        DELETE FROM repository_files a USING repository_files b
        WHERE a.id < b.id
          AND a.repository_id = b.repository_id
          AND a.path = b.path;
        """
    )

    def _create_index_if_missing(table_name: str, index_name: str, columns: list[Any], unique: bool = False) -> None:
        existing = {ix["name"] for ix in inspector.get_indexes(table_name)}
        if index_name not in existing:
            op.create_index(index_name, table_name, columns, unique=unique)

    existing_uqs = {uq["name"] for uq in inspector.get_unique_constraints("repository_files")}
    if "uq_repository_files_repo_path" not in existing_uqs:
        op.create_unique_constraint(
            "uq_repository_files_repo_path",
            "repository_files",
            ["repository_id", "path"],
        )

    _create_index_if_missing("repository_files", "ix_repository_files_repository_id_path", ["repository_id", "path"])
    _create_index_if_missing("symbol_edges", "ix_symbol_edges_source_symbol_id", ["source_symbol_id"])
    _create_index_if_missing("symbol_edges", "ix_symbol_edges_target_symbol_id", ["target_symbol_id"])
    _create_index_if_missing("code_symbols", "ix_code_symbols_repository_id_name", ["repository_id", "name"])
    _create_index_if_missing("code_chunks", "ix_code_chunks_file_id_start_line", ["file_id", "start_line"])
    _create_index_if_missing("analysis_runs", "ix_analysis_runs_repo_feature_created", ["repository_id", "feature_type", sa.text("created_at DESC")])
    _create_index_if_missing("task_events", "ix_task_events_task_id_created_at", ["task_id", "created_at"])
    _create_index_if_missing("tasks", "ix_tasks_repo_status_created_at", ["repository_id", "status", sa.text("created_at DESC")])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    def _drop_index_if_exists(table_name: str, index_name: str) -> None:
        existing = {ix["name"] for ix in inspector.get_indexes(table_name)}
        if index_name in existing:
            op.drop_index(index_name, table_name=table_name)

    _drop_index_if_exists("tasks", "ix_tasks_repo_status_created_at")
    _drop_index_if_exists("task_events", "ix_task_events_task_id_created_at")
    _drop_index_if_exists("analysis_runs", "ix_analysis_runs_repo_feature_created")
    _drop_index_if_exists("code_chunks", "ix_code_chunks_file_id_start_line")
    _drop_index_if_exists("code_symbols", "ix_code_symbols_repository_id_name")
    _drop_index_if_exists("symbol_edges", "ix_symbol_edges_target_symbol_id")
    _drop_index_if_exists("symbol_edges", "ix_symbol_edges_source_symbol_id")
    _drop_index_if_exists("repository_files", "ix_repository_files_repository_id_path")

    existing_uqs = {uq["name"] for uq in inspector.get_unique_constraints("repository_files")}
    if "uq_repository_files_repo_path" in existing_uqs:
        op.drop_constraint("uq_repository_files_repo_path", "repository_files", type_="unique")
