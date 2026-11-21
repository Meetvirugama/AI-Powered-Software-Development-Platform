"""Persistence for repository chat conversations (server-side history)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.chat_conversation import CHAT_TITLE_MAX_CHARS, ChatConversation, ChatMessageRecord

# How many earlier messages are replayed to the pipeline as history. The context builder then
# trims them to its token budget, newest first.
HISTORY_REPLAY_LIMIT = 20


def title_from_question(question: str) -> str:
    """Short, single-line conversation title derived from the first question."""
    flat = " ".join((question or "").split())
    if not flat:
        return "New conversation"
    if len(flat) <= CHAT_TITLE_MAX_CHARS:
        return flat
    return flat[: CHAT_TITLE_MAX_CHARS - 1].rstrip() + "…"


class ChatRepository:
    def __init__(self, session: Session):
        self.session = session

    # -- conversations -----------------------------------------------------

    def create_conversation(
        self, user_id: uuid.UUID, repository_id: uuid.UUID, title: Optional[str] = None
    ) -> ChatConversation:
        conv = ChatConversation(
            id=uuid.uuid4(),
            user_id=user_id,
            repository_id=repository_id,
            title=title_from_question(title) if title else "New conversation",
            message_count=0,
        )
        self.session.add(conv)
        self.session.commit()
        self.session.refresh(conv)
        return conv

    def get_owned_conversation(
        self, conversation_id: uuid.UUID, user_id: uuid.UUID, repository_id: uuid.UUID
    ) -> Optional[ChatConversation]:
        """Conversation only if it belongs to this user AND this repository (tenant isolation)."""
        stmt = select(ChatConversation).where(
            ChatConversation.id == conversation_id,
            ChatConversation.user_id == user_id,
            ChatConversation.repository_id == repository_id,
        )
        return self.session.scalars(stmt).first()

    def list_conversations(
        self, user_id: uuid.UUID, repository_id: uuid.UUID, *, offset: int = 0, limit: int = 30
    ) -> tuple[list[ChatConversation], int]:
        base = (ChatConversation.user_id == user_id, ChatConversation.repository_id == repository_id)
        total = int(self.session.scalar(select(func.count(ChatConversation.id)).where(*base)) or 0)
        stmt = (
            select(ChatConversation)
            .where(*base)
            .order_by(ChatConversation.updated_at.desc(), ChatConversation.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all()), total

    def rename_conversation(self, conv: ChatConversation, title: str) -> ChatConversation:
        conv.title = title_from_question(title)
        self.session.commit()
        self.session.refresh(conv)
        return conv

    def delete_conversation(self, conv: ChatConversation) -> None:
        self.session.execute(delete(ChatMessageRecord).where(ChatMessageRecord.conversation_id == conv.id))
        self.session.delete(conv)
        self.session.commit()

    # -- messages ----------------------------------------------------------

    def list_messages(self, conversation_id: uuid.UUID, limit: Optional[int] = None) -> list[ChatMessageRecord]:
        """Messages in chronological order; with ``limit``, only the most recent ones."""
        stmt = select(ChatMessageRecord).where(ChatMessageRecord.conversation_id == conversation_id)
        if limit is not None:
            recent = list(
                self.session.scalars(
                    stmt.order_by(ChatMessageRecord.created_at.desc(), ChatMessageRecord.id.desc()).limit(limit)
                ).all()
            )
            recent.reverse()
            return recent
        return list(self.session.scalars(stmt.order_by(ChatMessageRecord.created_at, ChatMessageRecord.id)).all())

    def history_for_pipeline(self, conversation_id: uuid.UUID) -> list[dict[str, str]]:
        return [
            {"role": m.role, "content": m.content}
            for m in self.list_messages(conversation_id, limit=HISTORY_REPLAY_LIMIT)
            if m.role in ("user", "assistant") and m.content
        ]

    def append_exchange(
        self,
        conv: ChatConversation,
        question: str,
        answer: dict[str, Any],
        mode: str,
    ) -> tuple[ChatMessageRecord, ChatMessageRecord]:
        """Persist one user question and its assistant answer atomically.

        Saved only after a successful answer, so a failed request never leaves an
        unanswered question in the stored history.
        """
        now = datetime.now(timezone.utc)
        user_msg = ChatMessageRecord(
            id=uuid.uuid4(), conversation_id=conv.id, role="user", content=question, mode=mode, created_at=now
        )
        assistant_msg = ChatMessageRecord(
            id=uuid.uuid4(),
            conversation_id=conv.id,
            role="assistant",
            content=str(answer.get("answer") or ""),
            sources=answer.get("sources") or [],
            confidence=answer.get("confidence"),
            status=answer.get("status"),
            mode=mode,
            agent_metadata=answer.get("agent_metadata"),
            # Strictly after the question so ordering is stable even with coarse DB clocks.
            created_at=now.replace(microsecond=min(now.microsecond + 1, 999_999)),
        )
        self.session.add_all([user_msg, assistant_msg])
        if conv.message_count == 0 and (not conv.title or conv.title == "New conversation"):
            conv.title = title_from_question(question)
        conv.message_count = (conv.message_count or 0) + 2
        conv.updated_at = now
        self.session.commit()
        return user_msg, assistant_msg
