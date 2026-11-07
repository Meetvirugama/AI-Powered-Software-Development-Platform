"""Add github_webhook_events table and repository automation columns (Issue #182)

Revision ID: e1f2a3b4c5d6
Revises: d5e6f7a8b9c0
Create Date: 2026-11-07 17:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # 1. Create WebhookEventStatus enum if Postgres
    if is_postgres:
        op.execute(
            """
            DO $$ BEGIN
                CREATE TYPE webhookeventstatus AS ENUM ('PENDING', 'PROCESSING', 'SUCCEEDED', 'RETRY', 'DEAD_LETTER');
            EXCEPTION
                WHEN duplicate_object THEN NULL;
            END $$;
            """
        )

    # 2. Create github_webhook_events table
    op.create_table(
        "github_webhook_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("delivery_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=True),
        sa.Column("installation_id", sa.String(length=64), nullable=True),
        sa.Column("repository_id", sa.UUID(), nullable=True),
        sa.Column("github_repo_id", sa.String(length=64), nullable=True),
        sa.Column("payload", sa.JSON().with_variant(JSONB, "postgresql"), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="PENDING", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="5", nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("replay_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_replayed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    if is_postgres:
        op.execute(
            "ALTER TABLE github_webhook_events ALTER COLUMN status TYPE webhookeventstatus USING status::webhookeventstatus"
        )

    op.create_index(op.f("ix_github_webhook_events_delivery_id"), "github_webhook_events", ["delivery_id"], unique=True)
    op.create_index(op.f("ix_github_webhook_events_event_type"), "github_webhook_events", ["event_type"], unique=False)
    op.create_index(op.f("ix_github_webhook_events_action"), "github_webhook_events", ["action"], unique=False)
    op.create_index(op.f("ix_github_webhook_events_installation_id"), "github_webhook_events", ["installation_id"], unique=False)
    op.create_index(op.f("ix_github_webhook_events_repository_id"), "github_webhook_events", ["repository_id"], unique=False)
    op.create_index(op.f("ix_github_webhook_events_github_repo_id"), "github_webhook_events", ["github_repo_id"], unique=False)
    op.create_index(op.f("ix_github_webhook_events_status"), "github_webhook_events", ["status"], unique=False)
    op.create_index(op.f("ix_github_webhook_events_available_at"), "github_webhook_events", ["available_at"], unique=False)
    op.create_index(op.f("ix_github_webhook_events_lease_expires_at"), "github_webhook_events", ["lease_expires_at"], unique=False)

    # 3. Add automation columns to repositories
    op.add_column("repositories", sa.Column("last_indexed_commit_sha", sa.String(length=64), nullable=True))
    op.add_column("repositories", sa.Column("auto_sync_enabled", sa.Boolean(), server_default=sa.true(), nullable=False))
    op.add_column("repositories", sa.Column("pr_review_enabled", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("repositories", sa.Column("pr_review_drafts", sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # Remove columns from repositories
    op.drop_column("repositories", "pr_review_drafts")
    op.drop_column("repositories", "pr_review_enabled")
    op.drop_column("repositories", "auto_sync_enabled")
    op.drop_column("repositories", "last_indexed_commit_sha")

    # Drop github_webhook_events table
    op.drop_index(op.f("ix_github_webhook_events_lease_expires_at"), table_name="github_webhook_events")
    op.drop_index(op.f("ix_github_webhook_events_available_at"), table_name="github_webhook_events")
    op.drop_index(op.f("ix_github_webhook_events_status"), table_name="github_webhook_events")
    op.drop_index(op.f("ix_github_webhook_events_github_repo_id"), table_name="github_webhook_events")
    op.drop_index(op.f("ix_github_webhook_events_repository_id"), table_name="github_webhook_events")
    op.drop_index(op.f("ix_github_webhook_events_installation_id"), table_name="github_webhook_events")
    op.drop_index(op.f("ix_github_webhook_events_action"), table_name="github_webhook_events")
    op.drop_index(op.f("ix_github_webhook_events_event_type"), table_name="github_webhook_events")
    op.drop_index(op.f("ix_github_webhook_events_delivery_id"), table_name="github_webhook_events")
    op.drop_table("github_webhook_events")

    if is_postgres:
        op.execute("DROP TYPE IF EXISTS webhookeventstatus;")
