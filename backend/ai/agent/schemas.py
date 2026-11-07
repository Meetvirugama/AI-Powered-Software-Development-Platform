"""
Agent Domain Schemas — State, Evidence, Context, and Activity Primitives.
(Phase 2 / Issue #188).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from ai.retrieval.base import CodeChunk


class AgentEvidenceItem(BaseModel):
    """
    Normalized atomic evidence item collected during repository investigation.

    Can be serialized into AgentContext or converted directly into a CodeChunk
    for ingestion by the existing ContextBuilder and GroundingValidator.
    """

    evidence_id: str = Field(default_factory=lambda: f"ev_{uuid.uuid4().hex[:8]}")
    repository_id: str
    source_type: Literal["retrieval", "file_read", "symbol", "caller"]
    file_path: str
    start_line: int = Field(..., ge=1)
    end_line: int = Field(..., ge=1)
    content: str
    chunk_id: str | None = None
    file_id: str | None = None
    symbol_name: str | None = None
    score: float | None = None
    tool_name: str | None = None
    is_truncated: bool = False
    redaction_applied: bool = False

    def to_code_chunk(self) -> CodeChunk:
        """Convert evidence item into CodeChunk for existing RAG ContextBuilder compatibility."""
        chunk_uuid = (
            UUID(self.chunk_id)
            if self.chunk_id and _is_valid_uuid(self.chunk_id)
            else uuid.uuid5(uuid.NAMESPACE_DNS, f"{self.repository_id}:{self.file_path}:{self.start_line}:{self.end_line}")
        )
        repo_uuid = (
            UUID(self.repository_id)
            if _is_valid_uuid(self.repository_id)
            else uuid.uuid5(uuid.NAMESPACE_DNS, self.repository_id)
        )
        file_uuid = (
            UUID(self.file_id)
            if self.file_id and _is_valid_uuid(self.file_id)
            else uuid.uuid5(uuid.NAMESPACE_DNS, f"{self.repository_id}:{self.file_path}")
        )
        return CodeChunk(
            id=chunk_uuid,
            repository_id=repo_uuid,
            file_id=file_uuid,
            symbol_id=None,
            content=self.content,
            token_count=max(1, len(self.content.split())),
            start_line=self.start_line,
            end_line=self.end_line,
            content_hash=uuid.uuid5(uuid.NAMESPACE_DNS, self.content).hex,
            score=self.score if self.score is not None else 0.5,
            file_path=self.file_path,
        )


def _is_valid_uuid(val: str) -> bool:
    try:
        UUID(str(val))
        return True
    except (ValueError, TypeError):
        return False


@dataclass
class AgentToolContext:
    """Execution context provided to tools during agent invocation."""

    repository_id: UUID
    user_id: str | None = None
    db_session: Any = None
    retriever: Any = None
    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])


class AgentToolCall(BaseModel):
    """Normalized tool call request received from the model."""

    call_id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class AgentToolResult(BaseModel):
    """Normalized result returned after tool execution."""

    call_id: str
    tool_name: str
    result: Any = None
    evidence: list[AgentEvidenceItem] = Field(default_factory=list)
    is_error: bool = False
    error_message: str | None = None
    execution_time_ms: float = 0.0
    is_truncated: bool = False

    def to_model_content(self) -> str:
        """Serialize result payload for return to the LLM."""
        if self.is_error:
            return json.dumps({
                "error": self.error_message or "Tool execution error",
                "is_error": True,
            })
        if isinstance(self.result, str):
            return self.result
        try:
            return json.dumps(self.result, default=str)
        except (TypeError, ValueError):
            return str(self.result)


class AgentActivityEvent(BaseModel):
    """Operational progress event emitted during agentic chat execution."""

    event_type: Literal[
        "agent_started",
        "retrieval_started",
        "tool_round_started",
        "tool_call_started",
        "tool_call_completed",
        "tool_call_failed",
        "budget_warning",
        "final_answer_started",
        "grounding_completed",
        "agent_completed",
    ]
    message: str
    tool_name: str | None = None
    data: dict[str, Any] | None = None
    timestamp: float = Field(default_factory=lambda: 0.0)
