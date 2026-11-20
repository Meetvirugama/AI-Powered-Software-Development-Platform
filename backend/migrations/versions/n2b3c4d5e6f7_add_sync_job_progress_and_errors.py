"""Track sync-job stage, timing, commit, stats and failure reason.

Revision ID: n2b3c4d5e6f7
Revises: m1a2b3c4d5e6
Create Date: 2026-11-19 23:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "n2b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "m1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_COLUMNS = (
    ("stage", sa.String(length=32)),
    ("error_message", sa.Text()),
    ("started_at", sa.DateTime(timezone=True)),
    ("finished_at", sa.DateTime(timezone=True)),
    ("commit_sha", sa.String(length=64)),
    ("stats", sa.JSON()),
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {col["name"] for col in inspector.get_columns("sync_jobs")}
    for name, col_type in _NEW_COLUMNS:
        if name not in existing:
            op.add_column("sync_jobs", sa.Column(name, col_type, nullable=True))

    indexes = {ix["name"] for ix in inspector.get_indexes("sync_jobs")}
    if "ix_sync_jobs_repository_created" not in indexes:
        op.create_index("ix_sync_jobs_repository_created", "sync_jobs", ["repository_id", "created_at"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    indexes = {ix["name"] for ix in inspector.get_indexes("sync_jobs")}
    if "ix_sync_jobs_repository_created" in indexes:
        op.drop_index("ix_sync_jobs_repository_created", table_name="sync_jobs")
    existing = {col["name"] for col in inspector.get_columns("sync_jobs")}
    for name, _ in reversed(_NEW_COLUMNS):
        if name in existing:
            op.drop_column("sync_jobs", name)
