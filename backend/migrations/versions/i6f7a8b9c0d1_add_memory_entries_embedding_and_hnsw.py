"""Add embedding vector(768) and HNSW index to memory_entries (F36 / Issue #217).

Revision ID: i6f7a8b9c0d1
Revises: h5e6f7a8b9c0
Create Date: 2026-11-10 12:12:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision: str = "i6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "h5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    columns = {col["name"] for col in inspector.get_columns("memory_entries")}
    if "embedding" not in columns:
        op.add_column(
            "memory_entries",
            sa.Column("embedding", Vector(768), nullable=True),
        )

    dialect_name = bind.dialect.name
    if dialect_name == "postgresql":
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("memory_entries")}
        if "ix_memory_entries_embedding_hnsw" not in existing_indexes:
            op.execute(
                """
                CREATE INDEX IF NOT EXISTS ix_memory_entries_embedding_hnsw
                ON memory_entries
                USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64);
                """
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    dialect_name = bind.dialect.name
    if dialect_name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_memory_entries_embedding_hnsw;")

    columns = {col["name"] for col in inspector.get_columns("memory_entries")}
    if "embedding" in columns:
        op.drop_column("memory_entries", "embedding")
