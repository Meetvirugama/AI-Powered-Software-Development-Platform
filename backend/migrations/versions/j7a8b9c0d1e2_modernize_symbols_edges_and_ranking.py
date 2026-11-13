"""Modernize code_symbols and symbol_edges for provenance, resolution status, and importance ranking.

Revision ID: j7a8b9c0d1e2
Revises: i6f7a8b9c0d1
Create Date: 2026-11-11 10:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "j7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "i6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # 1. code_symbols: add importance_score and index
    symbol_cols = {col["name"] for col in inspector.get_columns("code_symbols")}
    if "importance_score" not in symbol_cols:
        op.add_column(
            "code_symbols",
            sa.Column(
                "importance_score",
                sa.Float(),
                nullable=False,
                server_default="0.0",
            ),
        )

    symbol_indexes = {idx["name"] for idx in inspector.get_indexes("code_symbols")}
    if "ix_code_symbols_repository_importance" not in symbol_indexes:
        op.create_index(
            "ix_code_symbols_repository_importance",
            "code_symbols",
            ["repository_id", "importance_score"],
        )

    # 2. symbol_edges: make target_symbol_id nullable, add target_name, provenance,
    #    resolution_status, confidence, weight, and indexes
    edge_cols = {col["name"]: col for col in inspector.get_columns("symbol_edges")}
    if "target_symbol_id" in edge_cols and not edge_cols["target_symbol_id"].get("nullable", True):
        with op.batch_alter_table("symbol_edges") as batch_op:
            batch_op.alter_column(
                "target_symbol_id",
                existing_type=sa.UUID(),
                nullable=True,
            )

    if "target_name" not in edge_cols:
        op.add_column(
            "symbol_edges",
            sa.Column("target_name", sa.String(length=512), nullable=True),
        )
    if "provenance" not in edge_cols:
        op.add_column(
            "symbol_edges",
            sa.Column(
                "provenance",
                sa.String(length=64),
                nullable=False,
                server_default="tree_sitter",
            ),
        )
    if "resolution_status" not in edge_cols:
        op.add_column(
            "symbol_edges",
            sa.Column(
                "resolution_status",
                sa.String(length=32),
                nullable=False,
                server_default="resolved",
            ),
        )
    if "confidence" not in edge_cols:
        op.add_column(
            "symbol_edges",
            sa.Column(
                "confidence",
                sa.Float(),
                nullable=False,
                server_default="1.0",
            ),
        )
    if "weight" not in edge_cols:
        op.add_column(
            "symbol_edges",
            sa.Column(
                "weight",
                sa.Float(),
                nullable=False,
                server_default="1.0",
            ),
        )

    edge_indexes = {idx["name"] for idx in inspector.get_indexes("symbol_edges")}
    if "ix_symbol_edges_source" not in edge_indexes:
        op.create_index("ix_symbol_edges_source", "symbol_edges", ["source_symbol_id"])
    if "ix_symbol_edges_target" not in edge_indexes:
        op.create_index("ix_symbol_edges_target", "symbol_edges", ["target_symbol_id"])
    if "ix_symbol_edges_repo_status" not in edge_indexes:
        op.create_index(
            "ix_symbol_edges_repo_status",
            "symbol_edges",
            ["repository_id", "resolution_status"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    edge_indexes = {idx["name"] for idx in inspector.get_indexes("symbol_edges")}
    for idx_name in (
        "ix_symbol_edges_repo_status",
        "ix_symbol_edges_target",
        "ix_symbol_edges_source",
    ):
        if idx_name in edge_indexes:
            op.drop_index(idx_name, table_name="symbol_edges")

    edge_cols = {col["name"] for col in inspector.get_columns("symbol_edges")}
    for col_name in ("weight", "confidence", "resolution_status", "provenance", "target_name"):
        if col_name in edge_cols:
            op.drop_column("symbol_edges", col_name)

    symbol_indexes = {idx["name"] for idx in inspector.get_indexes("code_symbols")}
    if "ix_code_symbols_repository_importance" in symbol_indexes:
        op.drop_index("ix_code_symbols_repository_importance", table_name="code_symbols")

    symbol_cols = {col["name"] for col in inspector.get_columns("code_symbols")}
    if "importance_score" in symbol_cols:
        op.drop_column("code_symbols", "importance_score")
