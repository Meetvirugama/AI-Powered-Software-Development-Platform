"""Add FK ondelete policies to users/installations foreign keys (ISS-034)

Revision ID: l9c0d1e2f3a4
Revises: k8b9c0d1e2f3
Create Date: 2026-11-15 17:48:00

Adds CASCADE ondelete policies to foreign keys that were missing them:
- repositories.user_id → users.id
- repositories.installation_id → github_installations.id
- github_installations.user_id → users.id
- sync_jobs.user_id → users.id
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "l9c0d1e2f3a4"
down_revision: Union[str, Sequence[str], None] = "k8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add ondelete=CASCADE to FK constraints missing delete policies."""
    # Note: SQLite does not support ALTER TABLE ... DROP CONSTRAINT / ADD CONSTRAINT
    # so these migrations only run meaningfully on PostgreSQL.
    # We use batch_alter_table for SQLite compatibility in tests.
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        # repositories.user_id FK
        op.drop_constraint("repositories_user_id_fkey", "repositories", type_="foreignkey")
        op.create_foreign_key(
            "repositories_user_id_fkey",
            "repositories",
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )

        # repositories.installation_id FK
        op.drop_constraint("repositories_installation_id_fkey", "repositories", type_="foreignkey")
        op.create_foreign_key(
            "repositories_installation_id_fkey",
            "repositories",
            "github_installations",
            ["installation_id"],
            ["id"],
            ondelete="CASCADE",
        )

        # github_installations.user_id FK
        op.drop_constraint("github_installations_user_id_fkey", "github_installations", type_="foreignkey")
        op.create_foreign_key(
            "github_installations_user_id_fkey",
            "github_installations",
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )

        # sync_jobs.user_id FK
        op.drop_constraint("sync_jobs_user_id_fkey", "sync_jobs", type_="foreignkey")
        op.create_foreign_key(
            "sync_jobs_user_id_fkey",
            "sync_jobs",
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )
    # SQLite: FK constraints are not enforced; skip DDL changes.


def downgrade() -> None:
    """Remove ondelete=CASCADE, reverting to no explicit delete policy."""
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        # repositories.user_id FK — revert to no ondelete
        op.drop_constraint("repositories_user_id_fkey", "repositories", type_="foreignkey")
        op.create_foreign_key(
            "repositories_user_id_fkey",
            "repositories",
            "users",
            ["user_id"],
            ["id"],
        )

        # repositories.installation_id FK
        op.drop_constraint("repositories_installation_id_fkey", "repositories", type_="foreignkey")
        op.create_foreign_key(
            "repositories_installation_id_fkey",
            "repositories",
            "github_installations",
            ["installation_id"],
            ["id"],
        )

        # github_installations.user_id FK
        op.drop_constraint("github_installations_user_id_fkey", "github_installations", type_="foreignkey")
        op.create_foreign_key(
            "github_installations_user_id_fkey",
            "github_installations",
            "users",
            ["user_id"],
            ["id"],
        )

        # sync_jobs.user_id FK
        op.drop_constraint("sync_jobs_user_id_fkey", "sync_jobs", type_="foreignkey")
        op.create_foreign_key(
            "sync_jobs_user_id_fkey",
            "sync_jobs",
            "users",
            ["user_id"],
            ["id"],
        )
