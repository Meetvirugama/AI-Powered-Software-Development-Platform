"""
ContextBuilder — Assembles token-bounded AgentContext for repository-aware Q&A.

Architecture & System Contracts:
- System / Data Separation: Repository source code and retrieved memory are untrusted
  data and MUST be formatted into clearly-delimited sections (e.g. REPOSITORY DATA, MEMORY).
  They must NEVER be injected into the LLM system prompt.
- Token Budget Management: Enforces a strict context window ceiling using cached
  tiktoken encoding (cl100k_base / GPT-4o standard).
- Priority-Based Truncation:
    1. Chat History: Fitted newest-to-oldest to preserve immediate conversation context.
    2. Project Memory: De-duplicated by ID (last-write wins) and ordered by recency.
    3. Code Chunks: Fitted greedily in retriever-ranked priority order (highest relevance first).
- Resiliency: Special tokens (e.g. <|endoftext|>) are safely handled without throwing
  disallowed token exceptions when ingesting untrusted user repositories.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import tiktoken

try:
    from ai.retrieval.base import CodeChunk
except ImportError:  # pragma: no cover
    from uuid import UUID

    @dataclass
    class CodeChunk:  # type: ignore[no-redef]
        id: UUID
        repository_id: UUID
        file_id: UUID
        symbol_id: UUID | None
        content: str
        token_count: int
        start_line: int
        end_line: int
        content_hash: str
        score: float
        file_path: str


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Token Encoding (Shared, GPT-4o / cl100k_base is the standard)
# ---------------------------------------------------------------------------

_ENCODING_NAME: str = "cl100k_base"


@functools.lru_cache(maxsize=8)
def _get_encoder(encoding_name: str = _ENCODING_NAME) -> tiktoken.Encoding:
    """Return the cached tiktoken encoder (thread-safe and reusable)."""
    return tiktoken.get_encoding(encoding_name)


def count_tokens(text: str, encoding_name: str = _ENCODING_NAME) -> int:
    """
    Return the number of tokens in *text* using cl100k_base encoding.

    Safety:
        Uses ``disallowed_special=()`` so untrusted repository code containing
        special tokens (e.g. ``<|endoftext|>``) does not raise a ValueError.
    """
    if not text:
        return 0
    try:
        enc = _get_encoder(encoding_name)
        return len(enc.encode(text, disallowed_special=()))
    except (ValueError, UnicodeError, TypeError, KeyError) as exc:
        logger.warning(
            "token_counting_fallback",
            extra={"error": str(exc), "text_len": len(text)},
        )
        # Sane heuristic fallback (approx. 4 characters per token) if tokenizer fails
        return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Domain Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class MemoryEntry:
    """A single project memory entry (architecture note, decision, rule, etc.)."""

    id: str
    content: str
    type: str  # "architecture" | "decision" | "rule" | "task" | "failure"
    created_at: str  # ISO 8601 string
    status: str = "active"  # "active" | "stale" | "archived"
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert entry to a serializable dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MemoryEntry:
        """Create a MemoryEntry from a mapping or database record dict."""
        return cls(
            id=str(data.get("id", "")),
            content=str(data.get("content", "")),
            type=str(data.get("type", data.get("type_", "rule"))),
            created_at=str(data.get("created_at", "")),
            status=str(data.get("status", "active")),
            source=str(data.get("source", "")),
        )


@dataclass
class RepositoryFile:
    """Lightweight repository file metadata (path, language, size)."""

    id: str
    path: str
    language: str
    size_bytes: int
    line_count: int
    content_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert repository file metadata to a serializable dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RepositoryFile:
        """Create a RepositoryFile from a dictionary."""
        return cls(
            id=str(data.get("id", "")),
            path=str(data.get("path", "")),
            language=str(data.get("language") or "text"),
            size_bytes=int(data.get("size_bytes", 0)),
            line_count=int(data.get("line_count", 0)),
            content_hash=str(data.get("content_hash", "")),
        )


@dataclass
class ChatMessage:
    """A single turn in conversation history."""

    role: str  # "user" | "assistant" | "system"
    content: str

    def to_dict(self) -> dict[str, str]:
        """Convert message to a dictionary compatible with LLM schemas."""
        return {"role": self.role, "content": self.content}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ChatMessage:
        """Create ChatMessage from a dictionary or schema payload."""
        return cls(
            role=str(data.get("role", "user")),
            content=str(data.get("content", "")),
        )

    @classmethod
    def from_any(cls, obj: Any) -> ChatMessage:
        """Coerce an object (dict, Pydantic model, or ChatMessage) into ChatMessage."""
        if isinstance(obj, ChatMessage):
            return obj
        if isinstance(obj, Mapping):
            return cls.from_dict(obj)
        role = getattr(obj, "role", "user")
        content = getattr(obj, "content", "")
        return cls(role=str(role), content=str(content))


@dataclass
class AgentContext:
    """
    The fully assembled, token-bounded context passed to the LLM for repository Q&A.

    Assembled exclusively by ContextBuilder.build() to guarantee token safety
    and strict data formatting rules.
    """

    code_chunks: list[CodeChunk] = field(default_factory=list)
    memory_chunks: list[MemoryEntry] = field(default_factory=list)
    related_files: list[RepositoryFile] = field(default_factory=list)
    recent_history: list[ChatMessage] = field(default_factory=list)
    total_tokens: int = 0
    chunk_tokens: int = 0
    memory_tokens: int = 0
    history_tokens: int = 0
    overhead_tokens: int = 0

    @property
    def is_empty(self) -> bool:
        """Return True if context contains no code chunks, memory, or history."""
        return not (self.code_chunks or self.memory_chunks or self.recent_history)

    def summary(self) -> dict[str, Any]:
        """Return a structured breakdown of context size and token allocation."""
        return {
            "total_tokens": self.total_tokens,
            "chunk_tokens": self.chunk_tokens,
            "memory_tokens": self.memory_tokens,
            "history_tokens": self.history_tokens,
            "overhead_tokens": self.overhead_tokens,
            "code_chunks_count": len(self.code_chunks),
            "memory_chunks_count": len(self.memory_chunks),
            "recent_history_count": len(self.recent_history),
            "related_files_count": len(self.related_files),
        }

    def to_dict(self) -> dict[str, Any]:
        """Return a dictionary representation of the context."""
        return {
            **self.summary(),
            "code_chunks": [
                asdict(c) if hasattr(c, "__dataclass_fields__") else vars(c)
                for c in self.code_chunks
            ],
            "memory_chunks": [m.to_dict() for m in self.memory_chunks],
            "related_files": [f.to_dict() for f in self.related_files],
            "recent_history": [h.to_dict() for h in self.recent_history],
        }


# ---------------------------------------------------------------------------
# Section Formatters
# ---------------------------------------------------------------------------

def _format_chunk(chunk: Any) -> str:
    """Render a CodeChunk into the REPOSITORY DATA section."""
    if isinstance(chunk, str):
        return chunk
    file_path = getattr(chunk, "file_path", "unknown")
    start_line = getattr(chunk, "start_line", 0)
    end_line = getattr(chunk, "end_line", 0)

    content = getattr(chunk, "content", str(chunk))
    header = f"--- {file_path} (lines {start_line}–{end_line}) ---"
    return f"{header}\n{content}"


def _format_memory(entry: MemoryEntry) -> str:
    """Render a MemoryEntry into the MEMORY section."""
    entry_type = (entry.type or "NOTE").upper()
    return f"[{entry_type}] {entry.content}"


def _format_history_message(msg: ChatMessage) -> str:
    """Render a ChatMessage into text for budgeting."""
    role = (msg.role or "USER").upper()
    return f"{role}: {msg.content}"


# ---------------------------------------------------------------------------
# ContextBuilder
# ---------------------------------------------------------------------------


class ContextBuilder:
    """
    Assembles a token-budget-aware AgentContext from retrieval results and memory.

    Key Responsibilities & Invariants:
    1. System/Data Boundary: Repository code and memory live in untrusted user sections.
    2. Memory Deduplication: Deduplicated by entry ID (last-write wins), sorted descending by recency.
    3. Token Budgeting: Enforces max_context_tokens ceiling via tiktoken.
    4. Truncation Order: History preserved newest-first; memory fitted next; ranked chunks fitted greedy.
    """

    # Static overhead budget: header strings, separators, labels (~500 tokens)
    _OVERHEAD_TOKENS: int = 500

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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(
        self,
        chunks: Sequence[CodeChunk] | None,
        memory: Sequence[MemoryEntry] | None,
        history: Sequence[ChatMessage | Mapping[str, Any] | Any] | None,
        related_files: Sequence[RepositoryFile] | None = None,
    ) -> AgentContext:
        """
        Assemble context for an LLM call.

        Steps:
            1. Normalize and deduplicate memory entries by id.
            2. Sort memory by created_at desc (most recent first).
            3. Count tokens for each section using tiktoken.
            4. Truncate chunks / memory / history if total exceeds max_context_tokens.
            5. Set total_tokens and section token breakdowns.

        Args:
            chunks:        Reranked top-N code chunks from RAG pipeline.
            memory:        Relevant memory entries from project memory store.
            history:       Conversation turns (ChatMessage, dict, or message-like objects).
            related_files: Optional file metadata for repository structure context.

        Returns:
            AgentContext ready to be serialized into a prompt by PromptBuilder.
        """
        safe_chunks = list(chunks) if chunks is not None else []
        safe_memory = list(memory) if memory is not None else []
        safe_files = list(related_files) if related_files is not None else []
        safe_history = [ChatMessage.from_any(m) for m in (history or [])]

        # ---- Step 1 & 2: De-duplicate + sort memory -------------------------
        deduped_memory = self._dedup_memory(safe_memory)

        # ---- Step 3 & 4: Token-budget-aware truncation ----------------------
        effective_overhead = min(self._overhead_tokens, self._max_tokens)
        available_budget = max(0, self._max_tokens - effective_overhead)

        history_tokens, history_kept = self._fit_history(safe_history, available_budget)
        remaining_budget = max(0, available_budget - history_tokens)

        memory_tokens, memory_kept = self._fit_items(
            deduped_memory, remaining_budget, _format_memory
        )
        remaining_budget = max(0, remaining_budget - memory_tokens)

        chunk_tokens, chunks_kept = self._fit_items(
            safe_chunks, remaining_budget, _format_chunk
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
                "max_tokens": self._max_tokens,
                "chunks_in": len(safe_chunks),
                "chunks_kept": len(chunks_kept),
                "memory_in": len(safe_memory),
                "memory_kept": len(memory_kept),
                "history_messages": len(history_kept),
                "related_files": len(safe_files),
            },
        )

        return ctx

    def render_repository_data(self, ctx: AgentContext) -> str:
        """
        Render the REPOSITORY DATA and MEMORY sections as a plain string.

        This text is injected into the user message — never the system message.

        Format::

            REPOSITORY DATA:
            ----------------
            --- path/to/file.py (lines 10–30) ---
            <code>

            MEMORY:
            -------
            [ARCHITECTURE] ...

        Args:
            ctx: An AgentContext produced by :meth:`build`.

        Returns:
            A multi-line formatted string, or "" if both chunks and memory are empty.
        """
        sections: list[str] = []

        # ---- Repository files & structure -----------------------------------
        if ctx.related_files:
            total_lines = sum(f.line_count for f in ctx.related_files)
            file_lines = [
                "REPOSITORY OVERVIEW & FILE INVENTORY:",
                "-------------------------------------",
                f"Total files: {len(ctx.related_files)}",
                f"Total lines: {total_lines}",
                "Files in repository:",
            ]
            for f in ctx.related_files[:100]:
                file_lines.append(f"- {f.path} ({f.language or 'unknown'}, {f.line_count} lines)")
            if len(ctx.related_files) > 100:
                file_lines.append(f"... and {len(ctx.related_files) - 100} more files")
            sections.append("\n".join(file_lines))

        # ---- Code chunks ----------------------------------------------------
        if ctx.code_chunks:
            chunk_texts = "\n\n".join(_format_chunk(c) for c in ctx.code_chunks)
            sections.append(
                "REPOSITORY DATA:\n"
                "----------------\n"
                f"{chunk_texts}"
            )

        # ---- Memory ---------------------------------------------------------
        if ctx.memory_chunks:
            memory_texts = "\n".join(_format_memory(m) for m in ctx.memory_chunks)
            sections.append(
                "MEMORY:\n"
                "-------\n"
                f"{memory_texts}"
            )

        return "\n\n".join(sections)

    def render_history_section(self, ctx: AgentContext) -> str:
        """Render recent conversation history as formatted text turns."""
        if not ctx.recent_history:
            return ""
        return "\n".join(_format_history_message(m) for m in ctx.recent_history)

    def render_related_files_section(self, ctx: AgentContext) -> str:
        """Render repository file hierarchy summary if present."""
        if not ctx.related_files:
            return ""
        lines = ["RELATED FILES:", "--------------"]
        for f in ctx.related_files:
            lines.append(f"- {f.path} ({f.language or 'unknown'}, {f.line_count} lines)")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Private Helpers / Algorithms
    # ------------------------------------------------------------------

    @staticmethod
    def _dedup_memory(entries: Sequence[MemoryEntry]) -> list[MemoryEntry]:
        """
        De-duplicate memory entries by id and sort by created_at descending.

        Last-write wins: later entries with duplicate ID supersede earlier ones.
        Safe against non-string IDs and missing timestamps.
        """
        seen: dict[str, MemoryEntry] = {}
        for entry in entries:
            seen[str(entry.id)] = entry

        # Sort by ISO 8601 created_at string descending (newest first)
        return sorted(seen.values(), key=lambda e: str(e.created_at or ""), reverse=True)

    @staticmethod
    def _fit_history(
        history: Sequence[ChatMessage],
        budget: int,
    ) -> tuple[int, list[ChatMessage]]:
        """
        Fit as many history messages as possible within *budget* tokens.

        Iterates from newest to oldest so recent turns take precedence.
        Returns (total_tokens_used, kept_messages) in chronological order.
        """
        if budget <= 0:
            return 0, []

        kept: list[ChatMessage] = []
        used = 0
        for msg in reversed(history):
            tokens = count_tokens(_format_history_message(msg))
            if used + tokens > budget:
                break
            kept.append(msg)
            used += tokens

        kept.reverse()  # Restore original chronological order
        return used, kept

    @staticmethod
    def _fit_items(
        items: Sequence[Any],
        budget: int,
        formatter: Callable[[Any], str],
    ) -> tuple[int, list[Any]]:
        """
        Generic greedy token fitter — preserves items in priority order.

        Args:
            items:     Ordered list of items (highest priority first).
            budget:    Remaining token budget.
            formatter: Callable(item) -> str for token counting.

        Returns:
            (tokens_used, kept_items)
        """
        if budget <= 0:
            return 0, []

        kept: list[Any] = []
        used = 0
        for item in items:
            tokens = count_tokens(formatter(item))
            if used + tokens > budget:
                logger.debug(
                    "context_truncation",
                    extra={"dropped_item_tokens": tokens, "remaining_budget": budget - used},
                )
                break
            kept.append(item)
            used += tokens
        return used, kept
