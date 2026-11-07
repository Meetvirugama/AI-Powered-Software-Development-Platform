"""Add code_search_text to code_chunks and index generation tracking to repositories (R01, R04)

Revision ID: e8f9a0b1c2d3
Revises: e1f2a3b4c5d6
Create Date: 2026-11-07 18:10:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "e8f9a0b1c2d3"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # 1. Add code_search_text to code_chunks if not present
    chunk_columns = {col["name"] for col in inspector.get_columns("code_chunks")}
    if "code_search_text" not in chunk_columns:
        op.add_column(
            "code_chunks",
            sa.Column("code_search_text", sa.Text(), nullable=True),
        )

    # 2. Add GIN index for simple text search on PostgreSQL
    dialect_name = bind.dialect.name
    if dialect_name == "postgresql":
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("code_chunks")}
        if "ix_code_chunks_code_search_gin" not in existing_indexes:
            op.execute(
                """
                CREATE INDEX IF NOT EXISTS ix_code_chunks_code_search_gin
                ON code_chunks
                USING gin (to_tsvector('simple', COALESCE(code_search_text, content)));
                """
            )

    # 3. Add active_index_generation and active_commit_sha to repositories
    repo_columns = {col["name"] for col in inspector.get_columns("repositories")}
    if "active_index_generation" not in repo_columns:
        op.add_column(
            "repositories",
            sa.Column("active_index_generation", sa.String(length=64), nullable=True, server_default="gen_0"),
        )
    if "active_commit_sha" not in repo_columns:
        op.add_column(
            "repositories",
            sa.Column("active_commit_sha", sa.String(length=40), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    dialect_name = bind.dialect.name
    if dialect_name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_code_chunks_code_search_gin;")

    chunk_columns = {col["name"] for col in inspector.get_columns("code_chunks")}
    if "code_search_text" in chunk_columns:
        op.drop_column("code_chunks", "code_search_text")

    repo_columns = {col["name"] for col in inspector.get_columns("repositories")}
    if "active_commit_sha" in repo_columns:
        op.drop_column("repositories", "active_commit_sha")
    if "active_index_generation" in repo_columns:
        op.drop_column("repositories", "active_index_generation")
