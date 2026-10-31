"""
ContextBuilder — Assembles token-bounded AgentContext for repository-aware Q&A and intelligence.
Owner: Meet — W1-12

Architecture Notice:
This module acts as the canonical facade for the modularized `ai.context` package:
- Dataclasses and schemas: `ai.context.models`
- Token budgeting and estimation: `ai.context.token_budget`
- Chat context and memory fitting: `ai.context.chat_context`
- Intelligence context and symbol fitting: `ai.context.intelligence_context`
- Untrusted prompt section formatting: `ai.context.renderers`
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from ai.retrieval.base import CodeChunk
from .chat_context import build_chat_context, dedup_memory
from .intelligence_context import build_intelligence_context
from .models import (
    AgentContext,
    ChatMessage,
    ContextLimits,
    ContextStatus,
    IntelligenceContext,
    IntelligenceContextRequest,
    IntelligenceContextResponse,
    MemoryEntry,
    MissingContextInfo,
    RepositoryFile,
    SymbolContext,
    TargetSnippet,
)
from .renderers import (
    format_chunk as _format_chunk,
    format_history_message as _format_history_message,
    format_memory as _format_memory,
    render_history_section,
    render_intelligence_data,
    render_related_files_section,
    render_repository_data,
)
from .token_budget import (
    _ENCODING_NAME,
    _OVERHEAD_TOKENS,
    _get_encoder,
    count_tokens,
    fit_history as _fit_history_budget,
    fit_items as _fit_items_budget,
)

logger = logging.getLogger(__name__)

__all__ = [
    "AgentContext",
    "ChatMessage",
    "ContextBuilder",
    "ContextLimits",
    "ContextStatus",
    "IntelligenceContext",
    "IntelligenceContextRequest",
    "IntelligenceContextResponse",
    "MemoryEntry",
    "MissingContextInfo",
    "RepositoryFile",
    "SymbolContext",
    "TargetSnippet",
    "_ENCODING_NAME",
    "_OVERHEAD_TOKENS",
    "_format_chunk",
    "_format_history_message",
    "_format_memory",
    "_get_encoder",
    "count_tokens",
    "render_history_section",
    "render_intelligence_data",
    "render_related_files_section",
    "render_repository_data",
]


class ContextBuilder:
    """
    Assembles a token-budget-aware AgentContext from retrieval results and memory.

    Key Responsibilities & Invariants:
    1. System/Data Boundary: Repository code and memory live in untrusted user sections.
    2. Memory Deduplication: Deduplicated by entry ID (last-write wins), sorted descending by recency.
    3. Token Budgeting: Enforces max_context_tokens ceiling via tiktoken.
    4. Truncation Order: History preserved newest-first; memory fitted next; ranked chunks fitted greedy.
    """

    _OVERHEAD_TOKENS: int = _OVERHEAD_TOKENS

    def __init__(
        self,
        max_context_tokens: int = 100_000,
        overhead_tokens: int = _OVERHEAD_TOKENS,
        encoding_name: str = _ENCODING_NAME,
    ) -> None:
        if max_context_tokens <= 0:
            raise ValueError(f"max_context_tokens must be positive, got {max_context_tokens}")
        if overhead_tokens < 0:
            raise ValueError(f"overhead_tokens cannot be negative, got {overhead_tokens}")

        self._max_tokens = max_context_tokens
        self._overhead_tokens = overhead_tokens
        self._encoding_name = encoding_name

    @property
    def max_tokens(self) -> int:
        """Configured maximum token budget."""
        return self._max_tokens

    @property
    def overhead_tokens(self) -> int:
        """Static overhead tokens reserved for section headers and separators."""
        return self._overhead_tokens

    def build(
        self,
        chunks: Sequence[CodeChunk] | None = None,
        memory: Sequence[MemoryEntry] | None = None,
        history: Sequence[ChatMessage | Mapping[str, Any] | Any] | None = None,
        related_files: Sequence[RepositoryFile] | None = None,
    ) -> AgentContext:
        """Assemble token-bounded context for an LLM call."""
        return build_chat_context(
            max_tokens=self._max_tokens,
            overhead_tokens=self._overhead_tokens,
            chunks=chunks,
            memory=memory,
            history=history,
            related_files=related_files,
        )

    def render_repository_data(self, ctx: AgentContext) -> str:
        """Render the REPOSITORY DATA and MEMORY sections as a plain string."""
        return render_repository_data(ctx)

    def render_history_section(self, ctx: AgentContext) -> str:
        """Render recent conversation history as formatted text turns."""
        return render_history_section(ctx)

    def render_related_files_section(self, ctx: AgentContext) -> str:
        """Render repository file hierarchy summary if present."""
        return render_related_files_section(ctx)

    def build_intelligence_context(
        self,
        target: TargetSnippet,
        related_symbols: Sequence[SymbolContext] | None = None,
        relevant_chunks: Sequence[Any] | None = None,
        repository_files: Sequence[RepositoryFile] | None = None,
        project_rules: Sequence[str] | None = None,
        token_budget: int = 10_000,
        limits: ContextLimits | None = None,
        revision: str | None = None,
    ) -> IntelligenceContext:
        """Build an enriched, token-bounded context for developer intelligence features."""
        return build_intelligence_context(
            target=target,
            related_symbols=related_symbols,
            relevant_chunks=relevant_chunks,
            repository_files=repository_files,
            project_rules=project_rules,
            token_budget=token_budget,
            limits=limits,
            revision=revision,
        )

    def render_intelligence_data(self, ctx: IntelligenceContext) -> str:
        """Render the complete intelligence context into structured prompt data sections."""
        return render_intelligence_data(ctx)

    # ------------------------------------------------------------------
    # Backwards-compatibility internal static helper aliases
    # ------------------------------------------------------------------

    @staticmethod
    def _dedup_memory(entries: Sequence[MemoryEntry]) -> list[MemoryEntry]:
        return dedup_memory(entries)

    @staticmethod
    def _fit_history(
        history: Sequence[ChatMessage],
        budget: int,
    ) -> tuple[int, list[ChatMessage]]:
        return _fit_history_budget(history, budget, _format_history_message)

    @staticmethod
    def _fit_items(
        items: Sequence[Any],
        budget: int,
        formatter: Callable[[Any], str],
    ) -> tuple[int, list[Any]]:
        return _fit_items_budget(items, budget, formatter)
