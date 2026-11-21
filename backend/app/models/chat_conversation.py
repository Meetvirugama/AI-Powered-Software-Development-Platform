"""Server-side repository chat history.

Before these tables existed the conversation lived only in the browser, so it was lost on
reload and could not follow the user to another device.
"""

import uuid
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampedModel

CHAT_TITLE_MAX_CHARS = 120


class ChatConversation(TimestampedModel, Base):
    __tablename__ = "chat_conversations"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    repository_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(CHAT_TITLE_MAX_CHARS), default="New conversation")
    message_count: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        Index("ix_chat_conversations_owner_recent", "user_id", "repository_id", "updated_at"),
    )


class ChatMessageRecord(TimestampedModel, Base):
    __tablename__ = "chat_messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text)
    # Assistant turns only: grounded citations, confidence, pipeline status, chat mode, agent metadata
    sources: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    agent_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (Index("ix_chat_messages_conversation_created", "conversation_id", "created_at"),)
