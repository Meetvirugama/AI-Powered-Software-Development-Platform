"""Harden repository deletion cascades (Issue #183)

Revision ID: f3c4d5e6a7b8
Revises: e8f9a0b1c2d3
Create Date: 2026-11-08 15:30:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "f3c4d5e6a7b8"
down_revision: Union[str, Sequence[str], None] = "e8f9a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _update_fk_constraint(
    table_name: str,
    local_cols: list[str],
    ref_table: str,
    ref_cols: list[str],
    ondelete: str,
    new_constraint_name: str,
    dialect_name: str,
    inspector: sa.engine.reflection.Inspector,
) -> None:
    """Safely drop old foreign key and re-add it with target ondelete behavior."""
    if dialect_name == "sqlite":
        with op.batch_alter_table(table_name) as batch_op:
            # In SQLite batch mode, re-create foreign key with ondelete
            batch_op.create_foreign_key(
                new_constraint_name,
                ref_table,
                local_cols,
                ref_cols,
                ondelete=ondelete,
            )
        return

    # PostgreSQL / other RDBMS: locate existing constraint name and drop then recreate
    fks = inspector.get_foreign_keys(table_name)
    for fk in fks:
        if fk.get("referred_table") == ref_table and fk.get("constrained_columns") == local_cols:
            if fk.get("name"):
                op.drop_constraint(fk["name"], table_name, type_="foreignkey")
            break

    if dialect_name == "postgresql":
        op.create_foreign_key(
            new_constraint_name,
            table_name,
            ref_table,
            local_cols,
            ref_cols,
            ondelete=ondelete,
            postgresql_not_valid=True,
        )
        op.execute(sa.text(f"ALTER TABLE {table_name} VALIDATE CONSTRAINT {new_constraint_name}"))
    else:
        op.create_foreign_key(
            new_constraint_name,
            table_name,
            ref_table,
            local_cols,
            ref_cols,
            ondelete=ondelete,
        )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect_name = bind.dialect.name

    # 1. repository_files -> repositories.id (CASCADE)
    _update_fk_constraint(
        table_name="repository_files",
        local_cols=["repository_id"],
        ref_table="repositories",
        ref_cols=["id"],
        ondelete="CASCADE",
        new_constraint_name="fk_repository_files_repository_id",
        dialect_name=dialect_name,
        inspector=inspector,
    )

    # 2. code_symbols -> repositories.id (CASCADE)
    _update_fk_constraint(
        table_name="code_symbols",
        local_cols=["repository_id"],
        ref_table="repositories",
        ref_cols=["id"],
        ondelete="CASCADE",
        new_constraint_name="fk_code_symbols_repository_id",
        dialect_name=dialect_name,
        inspector=inspector,
    )

    # 3. code_symbols -> repository_files.id (CASCADE)
    _update_fk_constraint(
        table_name="code_symbols",
        local_cols=["file_id"],
        ref_table="repository_files",
        ref_cols=["id"],
        ondelete="CASCADE",
        new_constraint_name="fk_code_symbols_file_id",
        dialect_name=dialect_name,
        inspector=inspector,
    )

    # 4. code_symbols -> code_symbols.id (parent_id: SET NULL)
    _update_fk_constraint(
        table_name="code_symbols",
        local_cols=["parent_id"],
        ref_table="code_symbols",
        ref_cols=["id"],
        ondelete="SET NULL",
        new_constraint_name="fk_code_symbols_parent_id",
        dialect_name=dialect_name,
        inspector=inspector,
    )

    # 5. symbol_edges -> repositories.id (CASCADE)
    _update_fk_constraint(
        table_name="symbol_edges",
        local_cols=["repository_id"],
        ref_table="repositories",
        ref_cols=["id"],
        ondelete="CASCADE",
        new_constraint_name="fk_symbol_edges_repository_id",
        dialect_name=dialect_name,
        inspector=inspector,
    )

    # 6. symbol_edges -> code_symbols.id (source_symbol_id: CASCADE)
    _update_fk_constraint(
        table_name="symbol_edges",
        local_cols=["source_symbol_id"],
        ref_table="code_symbols",
        ref_cols=["id"],
        ondelete="CASCADE",
        new_constraint_name="fk_symbol_edges_source_symbol_id",
        dialect_name=dialect_name,
        inspector=inspector,
    )

    # 7. symbol_edges -> code_symbols.id (target_symbol_id: CASCADE)
    _update_fk_constraint(
        table_name="symbol_edges",
        local_cols=["target_symbol_id"],
        ref_table="code_symbols",
        ref_cols=["id"],
        ondelete="CASCADE",
        new_constraint_name="fk_symbol_edges_target_symbol_id",
        dialect_name=dialect_name,
        inspector=inspector,
    )

    # 8. code_chunks -> repositories.id (CASCADE)
    _update_fk_constraint(
        table_name="code_chunks",
        local_cols=["repository_id"],
        ref_table="repositories",
        ref_cols=["id"],
        ondelete="CASCADE",
        new_constraint_name="fk_code_chunks_repository_id",
        dialect_name=dialect_name,
        inspector=inspector,
    )

    # 9. code_chunks -> repository_files.id (CASCADE)
    _update_fk_constraint(
        table_name="code_chunks",
        local_cols=["file_id"],
        ref_table="repository_files",
        ref_cols=["id"],
        ondelete="CASCADE",
        new_constraint_name="fk_code_chunks_file_id",
        dialect_name=dialect_name,
        inspector=inspector,
    )

    # 10. code_chunks -> code_symbols.id (symbol_id: SET NULL)
    _update_fk_constraint(
        table_name="code_chunks",
        local_cols=["symbol_id"],
        ref_table="code_symbols",
        ref_cols=["id"],
        ondelete="SET NULL",
        new_constraint_name="fk_code_chunks_symbol_id",
        dialect_name=dialect_name,
        inspector=inspector,
    )

    # 11. memory_entries -> repositories.id (CASCADE)
    _update_fk_constraint(
        table_name="memory_entries",
        local_cols=["repository_id"],
        ref_table="repositories",
        ref_cols=["id"],
        ondelete="CASCADE",
        new_constraint_name="fk_memory_entries_repository_id",
        dialect_name=dialect_name,
        inspector=inspector,
    )

    # 12. sync_jobs -> repositories.id (CASCADE)
    _update_fk_constraint(
        table_name="sync_jobs",
        local_cols=["repository_id"],
        ref_table="repositories",
        ref_cols=["id"],
        ondelete="CASCADE",
        new_constraint_name="fk_sync_jobs_repository_id",
        dialect_name=dialect_name,
        inspector=inspector,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect_name = bind.dialect.name

    # Rollback constraints to NO ACTION (default)
    for table_name, cols, ref_table, ref_cols, c_name in [
        ("sync_jobs", ["repository_id"], "repositories", ["id"], "sync_jobs_repository_id_fkey"),
        ("memory_entries", ["repository_id"], "repositories", ["id"], "memory_entries_repository_id_fkey"),
        ("code_chunks", ["symbol_id"], "code_symbols", ["id"], "code_chunks_symbol_id_fkey"),
        ("code_chunks", ["file_id"], "repository_files", ["id"], "code_chunks_file_id_fkey"),
        ("code_chunks", ["repository_id"], "repositories", ["id"], "code_chunks_repository_id_fkey"),
        ("symbol_edges", ["target_symbol_id"], "code_symbols", ["id"], "symbol_edges_target_symbol_id_fkey"),
        ("symbol_edges", ["source_symbol_id"], "code_symbols", ["id"], "symbol_edges_source_symbol_id_fkey"),
        ("symbol_edges", ["repository_id"], "repositories", ["id"], "symbol_edges_repository_id_fkey"),
        ("code_symbols", ["parent_id"], "code_symbols", ["id"], "code_symbols_parent_id_fkey"),
        ("code_symbols", ["file_id"], "repository_files", ["id"], "code_symbols_file_id_fkey"),
        ("code_symbols", ["repository_id"], "repositories", ["id"], "code_symbols_repository_id_fkey"),
        ("repository_files", ["repository_id"], "repositories", ["id"], "repository_files_repository_id_fkey"),
    ]:
        _update_fk_constraint(
            table_name=table_name,
            local_cols=cols,
            ref_table=ref_table,
            ref_cols=ref_cols,
            ondelete="NO ACTION",
            new_constraint_name=c_name,
            dialect_name=dialect_name,
            inspector=inspector,
        )
