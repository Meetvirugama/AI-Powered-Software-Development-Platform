"""
Agent Execution State Primitive (task.md §12.1).

Maintains:
- Full conversation trajectory of the current agent investigation.
- Accumulated and deduplicated repository evidence.
- Real-time budget and elapsed time tracking.
- Provider and model telemetry metadata.
- Operational progress activity event stream.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from ai.agent.budget import AgentBudget
from ai.agent.policy import MAX_TOTAL_EVIDENCE_BYTES
from ai.agent.schemas import AgentActivityEvent, AgentEvidenceItem
from ai.llm.schemas import Message


class AgentState:
    """
    Mutable state container for an active repository investigation turn.
    """

    def __init__(
        self,
        request_id: str,
        repository_id: UUID,
        question: str,
        user_id: str | None = None,
        history: list[Message] | None = None,
        budget: AgentBudget | None = None,
        max_evidence_bytes: int = MAX_TOTAL_EVIDENCE_BYTES,
    ) -> None:
        self.request_id = request_id
        self.repository_id = repository_id
        self.user_id = user_id
        self.question = question
        self.history = history or []
        self.messages: list[Message] = []
        self.evidence: list[AgentEvidenceItem] = []
        self.budget = budget or AgentBudget()
        self.max_evidence_bytes = max_evidence_bytes

        self.started_at: float = time.monotonic()
        self.completed_at: float | None = None
        self.stop_reason: str | None = None
        self.provider_used: str | None = None
        self.model_used: str | None = None
        self.activity_events: list[AgentActivityEvent] = []

        # Deduplication index: (file_path, start_line, end_line)
        self._evidence_keys: set[tuple[str, int, int]] = set()

    def add_evidence(self, items: list[AgentEvidenceItem]) -> int:
        """
        Add new evidence items, deduplicating overlapping spans and respecting total byte limits.

        Returns:
            Count of newly accepted evidence items.
        """
        added = 0
        current_bytes = sum(len(e.content.encode("utf-8")) for e in self.evidence)

        for item in items:
            key = (item.file_path, item.start_line, item.end_line)
            if key in self._evidence_keys:
                continue

            item_bytes = len(item.content.encode("utf-8"))
            if current_bytes + item_bytes > self.max_evidence_bytes:
                # Truncate content or skip if budget full
                remaining_bytes = max(0, self.max_evidence_bytes - current_bytes)
                if remaining_bytes > 256:
                    item.content = item.content[:remaining_bytes] + "\n[... Evidence capacity reached ...]"
                    item.is_truncated = True
                    self.evidence.append(item)
                    self._evidence_keys.add(key)
                    added += 1
                break

            self.evidence.append(item)
            self._evidence_keys.add(key)
            current_bytes += item_bytes
            added += 1

        return added

    def record_event(
        self,
        event_type: str,
        message: str,
        tool_name: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Record a structured operational activity event."""
        event = AgentActivityEvent(
            event_type=event_type,  # type: ignore[arg-type]
            message=message,
            tool_name=tool_name,
            data=data,
            timestamp=round(time.monotonic() - self.started_at, 3),
        )
        self.activity_events.append(event)
