"""Chat context assembly and memory deduplication.
Owner: Meet — W1-12
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from ai.retrieval.base import CodeChunk
from .models import AgentContext, ChatMessage, MemoryEntry, RepositoryFile
from .renderers import format_chunk, format_history_message, format_memory
from .token_budget import fit_history, fit_items

logger = logging.getLogger(__name__)


def dedup_memory(entries: Sequence[MemoryEntry]) -> list[MemoryEntry]:
    """
    De-duplicate memory entries by id and sort by created_at descending.

    Last-write wins: later entries with duplicate ID supersede earlier ones.
    Safe against non-string IDs and missing timestamps.
    """
    seen: dict[str, MemoryEntry] = {}
    for entry in entries:
        if getattr(entry, "status", "active") in ("stale", "archived"):
            continue
        seen[str(entry.id)] = entry

    # Sort by ISO 8601 created_at string descending (newest first)
    return sorted(seen.values(), key=lambda e: str(e.created_at or ""), reverse=True)


def build_chat_context(
    max_tokens: int,
    overhead_tokens: int,
    chunks: Sequence[CodeChunk] | None = None,
    memory: Sequence[MemoryEntry] | None = None,
    history: Sequence[ChatMessage | Mapping[str, Any] | Any] | None = None,
    related_files: Sequence[RepositoryFile] | None = None,
) -> AgentContext:
    """
    Assemble token-bounded AgentContext for repository chat.

    Steps:
        1. Normalize and deduplicate memory entries by id.
        2. Sort memory by created_at desc (most recent first).
        3. Fit history, memory, and code chunks within available budget.
        4. Calculate total tokens and return AgentContext.
    """
    safe_chunks = list(chunks) if chunks is not None else []
    safe_memory = list(memory) if memory is not None else []
    safe_files = list(related_files) if related_files is not None else []
    safe_history = [ChatMessage.from_any(m) for m in (history or [])]

    # ---- Step 1 & 2: De-duplicate + sort memory -------------------------
    deduped_memory = dedup_memory(safe_memory)

    # ---- Step 3 & 4: Token-budget-aware truncation ----------------------
    effective_overhead = min(overhead_tokens, max_tokens)
    available_budget = max(0, max_tokens - effective_overhead)

    history_tokens, history_kept = fit_history(
        safe_history, available_budget, format_history_message
    )
    remaining_budget = max(0, available_budget - history_tokens)

    memory_tokens, memory_kept = fit_items(
        deduped_memory, remaining_budget, format_memory
    )
    remaining_budget = max(0, remaining_budget - memory_tokens)

    chunk_tokens, chunks_kept = fit_items(
        safe_chunks, remaining_budget, format_chunk
    )
    remaining_budget = max(0, remaining_budget - chunk_tokens)

    # ---- Step 5: Total token count --------------------------------------
    total = (
        effective_overhead
        + history_tokens
        + memory_tokens
        + chunk_tokens
    )

    ctx = AgentContext(
        code_chunks=chunks_kept,
        memory_chunks=memory_kept,
        related_files=safe_files,
        recent_history=history_kept,
        total_tokens=total,
        chunk_tokens=chunk_tokens,
        memory_tokens=memory_tokens,
        history_tokens=history_tokens,
        overhead_tokens=effective_overhead,
    )

    logger.info(
        "context_built",
        extra={
            "total_tokens": total,
            "max_tokens": max_tokens,
            "chunks_in": len(safe_chunks),
            "chunks_kept": len(chunks_kept),
            "memory_in": len(safe_memory),
            "memory_kept": len(memory_kept),
            "history_messages": len(history_kept),
            "related_files": len(safe_files),
        },
    )

    return ctx

