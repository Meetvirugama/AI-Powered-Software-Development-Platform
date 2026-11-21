"""Server-side repository chat history (conversations + messages).

Revision ID: o3c4d5e6f7a8
Revises: n2b3c4d5e6f7
Create Date: 2026-11-20 17:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "o3c4d5e6f7a8"
down_revision: Union[str, Sequence[str], None] = "n2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())

    if "chat_conversations" not in existing:
        op.create_table(
            "chat_conversations",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("user_id", sa.UUID(), nullable=False),
            sa.Column("repository_id", sa.UUID(), nullable=False),
            sa.Column("title", sa.String(length=120), nullable=False, server_default="New conversation"),
            sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_chat_conversations_user_id", "chat_conversations", ["user_id"])
        op.create_index("ix_chat_conversations_repository_id", "chat_conversations", ["repository_id"])
        op.create_index(
            "ix_chat_conversations_owner_recent",
            "chat_conversations",
            ["user_id", "repository_id", "updated_at"],
        )

    if "chat_messages" not in existing:
        op.create_table(
            "chat_messages",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("conversation_id", sa.UUID(), nullable=False),
            sa.Column("role", sa.String(length=16), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("sources", sa.JSON(), nullable=True),
            sa.Column("confidence", sa.String(length=16), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=True),
            sa.Column("mode", sa.String(length=16), nullable=True),
            sa.Column("agent_metadata", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["conversation_id"], ["chat_conversations.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_chat_messages_conversation_id", "chat_messages", ["conversation_id"])
        op.create_index(
            "ix_chat_messages_conversation_created",
            "chat_messages",
            ["conversation_id", "created_at"],
        )


def downgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "chat_messages" in existing:
        op.drop_table("chat_messages")
    if "chat_conversations" in existing:
        op.drop_table("chat_conversations")
