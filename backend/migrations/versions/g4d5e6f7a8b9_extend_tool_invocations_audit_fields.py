"""Extend tool_invocations table with unified tool registry audit fields.

Part of F21 — Tool router and tool policy bridge (Issue #201).
Adds:
- tool_version (SemVer of the tool definition executed)
- tool_source (builtin, mcp, plugin)
- provider_id (identifies external MCP/plugin provider)
- risk_tier (low, medium, high, critical)
- schema_fingerprint (SHA-256 fingerprint of input schema)
- execution_timeout_s (configured timeout ceiling)
- execution_timed_out (boolean flag indicating timeout condition)
- rate_limit_status (OK, LIMITED, BYPASS)
- error_category (normalized failure classification)

Revision ID: g4d5e6f7a8b9
Revises: f3c4d5e6a7b8
Create Date: 2026-11-09 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "f3c4d5e6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add extended audit and governance columns to tool_invocations table."""
    with op.batch_alter_table("tool_invocations") as batch_op:
        batch_op.add_column(sa.Column("tool_version", sa.String(length=32), nullable=True))
        batch_op.add_column(
            sa.Column("tool_source", sa.String(length=32), nullable=False, server_default="builtin")
        )
        batch_op.add_column(sa.Column("provider_id", sa.String(length=64), nullable=True))
        batch_op.add_column(
            sa.Column("risk_tier", sa.String(length=16), nullable=False, server_default="low")
        )
        batch_op.add_column(sa.Column("schema_fingerprint", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("execution_timeout_s", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "execution_timed_out",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )
        )
        batch_op.add_column(sa.Column("rate_limit_status", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("error_category", sa.String(length=64), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_tool_invocations_risk_tier"),
            ["risk_tier"],
            unique=False,
        )


def downgrade() -> None:
    """Drop extended audit columns from tool_invocations table."""
    with op.batch_alter_table("tool_invocations") as batch_op:
        batch_op.drop_index(batch_op.f("ix_tool_invocations_risk_tier"))
        batch_op.drop_column("error_category")
        batch_op.drop_column("rate_limit_status")
        batch_op.drop_column("execution_timed_out")
        batch_op.drop_column("execution_timeout_s")
        batch_op.drop_column("schema_fingerprint")
        batch_op.drop_column("risk_tier")
        batch_op.drop_column("provider_id")
        batch_op.drop_column("tool_source")
        batch_op.drop_column("tool_version")
