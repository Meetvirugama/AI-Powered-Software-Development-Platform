"""add sync jobs

Revision ID: cb4e2a7d0f31
Revises: aef3bb17eb34
Create Date: 2026-09-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "cb4e2a7d0f31"
down_revision: Union[str, Sequence[str], None] = "aef3bb17eb34"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enum via raw SQL to avoid SQLAlchemy 2.1.x DuplicateObject bug
    op.execute("DO $$ BEGIN CREATE TYPE syncjobstatus AS ENUM ('QUEUED', 'RUNNING', 'COMPLETED', 'FAILED'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;")
    op.create_table(
        "sync_jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("repository_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("ALTER TABLE sync_jobs ALTER COLUMN status TYPE syncjobstatus USING status::syncjobstatus")
    op.create_index(op.f("ix_sync_jobs_repository_id"), "sync_jobs", ["repository_id"], unique=False)
    op.create_index(op.f("ix_sync_jobs_user_id"), "sync_jobs", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_sync_jobs_user_id"), table_name="sync_jobs")
    op.drop_index(op.f("ix_sync_jobs_repository_id"), table_name="sync_jobs")
    op.drop_table("sync_jobs")
    sa.Enum(name="syncjobstatus").drop(op.get_bind(), checkfirst=True)
