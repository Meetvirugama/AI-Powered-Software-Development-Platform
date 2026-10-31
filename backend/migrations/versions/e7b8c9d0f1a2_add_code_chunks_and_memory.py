"""add code chunks and memory entries

Revision ID: e7b8c9d0f1a2
Revises: cb4e2a7d0f31
Create Date: 2026-10-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector


revision: str = "e7b8c9d0f1a2"
down_revision: Union[str, Sequence[str], None] = "cb4e2a7d0f31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. code_chunks
    op.create_table(
        "code_chunks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("repository_id", sa.UUID(), nullable=False),
        sa.Column("file_id", sa.UUID(), nullable=False),
        sa.Column("symbol_id", sa.UUID(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(768), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"]),
        sa.ForeignKeyConstraint(["file_id"], ["repository_files.id"]),
        sa.ForeignKeyConstraint(["symbol_id"], ["code_symbols.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_code_chunks_embedding_hnsw",
        "code_chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_code_chunks_content_gin",
        "code_chunks",
        [sa.text("to_tsvector('english', content)")],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index("ix_code_chunks_repo_hash", "code_chunks", ["repository_id", "content_hash"], unique=False)
    op.create_index(op.f("ix_code_chunks_repository_id"), "code_chunks", ["repository_id"], unique=False)
    op.create_index(op.f("ix_code_chunks_file_id"), "code_chunks", ["file_id"], unique=False)

    # 2. memory_entries
    op.execute("DO $$ BEGIN CREATE TYPE memorytype AS ENUM ('project', 'decision', 'rule', 'task_summary', 'failure'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE memorystatus AS ENUM ('active', 'stale', 'archived'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;")
    op.create_table(
        "memory_entries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("repository_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("ALTER TABLE memory_entries ALTER COLUMN type TYPE memorytype USING type::memorytype")
    op.execute("ALTER TABLE memory_entries ALTER COLUMN status TYPE memorystatus USING status::memorystatus")
    op.create_index(op.f("ix_memory_entries_repository_id"), "memory_entries", ["repository_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_memory_entries_repository_id"), table_name="memory_entries")
    op.drop_table("memory_entries")
    sa.Enum(name="memorystatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="memorytype").drop(op.get_bind(), checkfirst=True)

    op.drop_index(op.f("ix_code_chunks_file_id"), table_name="code_chunks")
    op.drop_index(op.f("ix_code_chunks_repository_id"), table_name="code_chunks")
    op.drop_index("ix_code_chunks_repo_hash", table_name="code_chunks")
    op.drop_index("ix_code_chunks_content_gin", table_name="code_chunks")
    op.drop_index("ix_code_chunks_embedding_hnsw", table_name="code_chunks")
    op.drop_table("code_chunks")
