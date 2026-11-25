"""Denormalize repository counts and latest sync error on repositories.

Revision ID: p4d5e6f7a8b9
Revises: o3c4d5e6f7a8
Create Date: 2026-11-25 21:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "p4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "o3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "repositories",
        sa.Column("file_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "repositories",
        sa.Column("symbol_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "repositories",
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "repositories",
        sa.Column("last_sync_error", sa.String(length=512), nullable=True),
    )

    op.execute(
        """
        UPDATE repositories
        SET file_count = (
            SELECT COUNT(*) FROM repository_files
            WHERE repository_files.repository_id = repositories.id
        ),
        symbol_count = (
            SELECT COUNT(*) FROM code_symbols
            WHERE code_symbols.repository_id = repositories.id
        ),
        chunk_count = (
            SELECT COUNT(*) FROM code_chunks
            WHERE code_chunks.repository_id = repositories.id
        ),
        last_sync_error = (
            SELECT sync_jobs.error_message
            FROM sync_jobs
            WHERE sync_jobs.repository_id = repositories.id
              AND sync_jobs.status = 'FAILED'
            ORDER BY sync_jobs.created_at DESC
            LIMIT 1
        )
        WHERE sync_status = 'FAILED'
        """
    )
    op.execute(
        """
        UPDATE repositories
        SET file_count = (
            SELECT COUNT(*) FROM repository_files
            WHERE repository_files.repository_id = repositories.id
        ),
        symbol_count = (
            SELECT COUNT(*) FROM code_symbols
            WHERE code_symbols.repository_id = repositories.id
        ),
        chunk_count = (
            SELECT COUNT(*) FROM code_chunks
            WHERE code_chunks.repository_id = repositories.id
        )
        WHERE sync_status != 'FAILED' OR sync_status IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("repositories", "last_sync_error")
    op.drop_column("repositories", "chunk_count")
    op.drop_column("repositories", "symbol_count")
    op.drop_column("repositories", "file_count")
