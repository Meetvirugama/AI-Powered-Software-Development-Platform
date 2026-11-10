"""Extend task_approvals table for tool permissions and MCP elicitation.

Part of F19 — Human approval gate (Issue #199).
Adds:
- approval_type (plan, tool, mcp_elicitation)
- tool_name (exact tool name)
- argument_hash (SHA-256 digest of canonical validated arguments)
- sanitized_arguments (redacted arguments for audit and UI display)
- risk_level (evaluated risk tier)
- status (pending, approved, rejected, expired, consumed)
- expires_at (expiration timestamp)
- consumed_at (timestamp when approval was consumed)
- session_id (MCP session identity)
- elicitation_type (form, url)
- elicitation_payload (schema / URL metadata)
- elicitation_response (user input / cancellation)

Revision ID: h5e6f7a8b9c0
Revises: g4d5e6f7a8b9
Create Date: 2026-11-09 18:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "h5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "g4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add tool approval and MCP elicitation columns to task_approvals table."""
    with op.batch_alter_table("task_approvals") as batch_op:
        batch_op.add_column(
            sa.Column("approval_type", sa.String(length=32), nullable=False, server_default="plan")
        )
        batch_op.add_column(sa.Column("tool_name", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("argument_hash", sa.String(length=128), nullable=True))
        batch_op.add_column(
            sa.Column("sanitized_arguments", sa.JSON().with_variant(JSONB, "postgresql"), nullable=True)
        )
        batch_op.add_column(sa.Column("risk_level", sa.String(length=32), nullable=True))
        batch_op.add_column(
            sa.Column("status", sa.String(length=32), nullable=False, server_default="approved")
        )
        batch_op.add_column(sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("session_id", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("elicitation_type", sa.String(length=32), nullable=True))
        batch_op.add_column(
            sa.Column("elicitation_payload", sa.JSON().with_variant(JSONB, "postgresql"), nullable=True)
        )
        batch_op.add_column(
            sa.Column("elicitation_response", sa.JSON().with_variant(JSONB, "postgresql"), nullable=True)
        )
        batch_op.alter_column("plan_version", existing_type=sa.Integer(), nullable=True)
        batch_op.create_index(batch_op.f("ix_task_approvals_tool_name"), ["tool_name"], unique=False)
        batch_op.create_index(batch_op.f("ix_task_approvals_argument_hash"), ["argument_hash"], unique=False)
        batch_op.create_index(batch_op.f("ix_task_approvals_status"), ["status"], unique=False)
        batch_op.create_index(batch_op.f("ix_task_approvals_session_id"), ["session_id"], unique=False)


def downgrade() -> None:
    """Drop tool approval and MCP elicitation columns from task_approvals table."""
    with op.batch_alter_table("task_approvals") as batch_op:
        batch_op.drop_index(batch_op.f("ix_task_approvals_session_id"))
        batch_op.drop_index(batch_op.f("ix_task_approvals_status"))
        batch_op.drop_index(batch_op.f("ix_task_approvals_argument_hash"))
        batch_op.drop_index(batch_op.f("ix_task_approvals_tool_name"))
        batch_op.alter_column("plan_version", existing_type=sa.Integer(), nullable=False)
        batch_op.drop_column("elicitation_response")
        batch_op.drop_column("elicitation_payload")
        batch_op.drop_column("elicitation_type")
        batch_op.drop_column("session_id")
        batch_op.drop_column("consumed_at")
        batch_op.drop_column("expires_at")
        batch_op.drop_column("status")
        batch_op.drop_column("risk_level")
        batch_op.drop_column("sanitized_arguments")
        batch_op.drop_column("argument_hash")
        batch_op.drop_column("tool_name")
        batch_op.drop_column("approval_type")

