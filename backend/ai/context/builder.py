"""
Context Builder — assembles retrieved code + memory + metadata into LLM prompt context.
Owner: Meet — W1-12

Day 1: AgentContext dataclass + builder skeleton.
Day 6: full implementation — REPOSITORY DATA section, token counting, truncation.

team_rules.md rule:
    Repository content goes into a clearly-labelled REPOSITORY DATA: section —
    never into the system prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..retrieval.base import CodeChunk


@dataclass
class MemoryEntry:
    """A single project memory entry (architecture note, decision, rule, etc.)."""
    id: str
    content: str
    type: str       # "architecture" | "decision" | "rule" | "task" | "failure"
    created_at: str  # ISO 8601


@dataclass
class RepositoryFile:
    """Lightweight file metadata — path, language, size."""
    id: str
    path: str
    language: str
    size_bytes: int
    line_count: int


@dataclass
class ChatMessage:
    """A single turn in the conversation history."""
    role: str   # "user" | "assistant"
    content: str


@dataclass
class AgentContext:
    """
    The fully assembled context passed to the LLM for repository Q&A.

    Assembled by ContextBuilder.build() — never constructed ad-hoc.
    """
    code_chunks: list["CodeChunk"] = field(default_factory=list)
    memory_chunks: list[MemoryEntry] = field(default_factory=list)
    related_files: list[RepositoryFile] = field(default_factory=list)
    recent_history: list[ChatMessage] = field(default_factory=list)
    total_tokens: int = 0  # Set by builder after assembly


class ContextBuilder:
    """
    Assembles an AgentContext from retrieval results and memory.

    Rules enforced:
    - Repository content goes into REPOSITORY DATA: section only
    - Memory entries are de-duplicated and sorted by recency
    - Total context must not exceed the LLM context window limit (tracked via token count)
    """

    def __init__(self, max_context_tokens: int = 100_000) -> None:
        self._max_tokens = max_context_tokens

    def build(
        self,
        chunks: list["CodeChunk"],
        memory: list[MemoryEntry],
        history: list[ChatMessage],
        related_files: list[RepositoryFile] | None = None,
    ) -> AgentContext:
        """
        Assemble context for an LLM call.

        Args:
            chunks:        Reranked top-8 code chunks from RAG pipeline.
            memory:        Relevant memory entries from project memory store.
            history:       Last N conversation turns.
            related_files: Optional file metadata for additional context.

        Returns:
            AgentContext ready to be serialised into a prompt by Dev's PromptBuilder.
        """
        # Day 6 implementation:
        #   1. De-duplicate memory entries by id
        #   2. Sort memory by created_at desc
        #   3. Count tokens for each section using tiktoken
        #   4. Truncate chunks / memory if total exceeds max_context_tokens
        #   5. Set ctx.total_tokens
        raise NotImplementedError("ContextBuilder.build() implemented on Day 6.")
