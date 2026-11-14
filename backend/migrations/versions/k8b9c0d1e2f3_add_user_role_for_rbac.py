"""Add role column to users table for Role-Based Access Control (RBAC).

Revision ID: k8b9c0d1e2f3
Revises: j7a8b9c0d1e2
Create Date: 2026-11-13 22:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "k8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = "j7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    user_cols = {col["name"] for col in inspector.get_columns("users")}
    if "role" not in user_cols:
        op.add_column(
            "users",
            sa.Column(
                "role",
                sa.String(length=32),
                nullable=False,
                server_default="developer",
            ),
        )

    user_indexes = {idx["name"] for idx in inspector.get_indexes("users")}
    if "ix_users_role" not in user_indexes:
        op.create_index(
            "ix_users_role",
            "users",
            ["role"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    user_indexes = {idx["name"] for idx in inspector.get_indexes("users")}
    if "ix_users_role" in user_indexes:
        op.drop_index("ix_users_role", table_name="users")

    user_cols = {col["name"] for col in inspector.get_columns("users")}
    if "role" in user_cols:
        op.drop_column("users", "role")
