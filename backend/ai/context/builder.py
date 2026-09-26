"""
ContextBuilder — assembles AgentContext for repository Q&A.
Owner: Meet — W1-12

Day 1: AgentContext dataclass + builder skeleton.
Day 6: full implementation — REPOSITORY DATA section, token counting, truncation.

team_rules.md rule:
    Repository content goes into a clearly-labelled REPOSITORY DATA: section —
    never into the system prompt.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import tiktoken

if TYPE_CHECKING:
    from ..retrieval.base import CodeChunk

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Token encoder (shared, GPT-4o / cl100k_base is the standard)
# ---------------------------------------------------------------------------

_ENCODING_NAME = "cl100k_base"

def _get_encoder() -> tiktoken.Encoding:
    """Return the shared tiktoken encoder (cl100k_base / GPT-4o compatible)."""
    return tiktoken.get_encoding(_ENCODING_NAME)


def count_tokens(text: str) -> int:
    """Return the number of tokens in *text* using cl100k_base encoding."""
    enc = _get_encoder()
    return len(enc.encode(text))


# ---------------------------------------------------------------------------
# Domain dataclasses
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Section formatters
# ---------------------------------------------------------------------------

def _format_chunk(chunk: "CodeChunk") -> str:
    """Render a CodeChunk into the REPOSITORY DATA section."""
    header = f"--- {chunk.file_path} (lines {chunk.start_line}–{chunk.end_line}) ---"
    return f"{header}\n{chunk.content}"


def _format_memory(entry: MemoryEntry) -> str:
    """Render a MemoryEntry into the MEMORY section."""
    return f"[{entry.type.upper()}] {entry.content}"


def _format_history_message(msg: ChatMessage) -> str:
    """Render a ChatMessage into text."""
    return f"{msg.role.upper()}: {msg.content}"


# ---------------------------------------------------------------------------
# ContextBuilder
# ---------------------------------------------------------------------------


class ContextBuilder:
    """
    Assembles an AgentContext from retrieval results and memory.

    Rules enforced:
    - Repository content goes into REPOSITORY DATA: section only
    - Memory entries are de-duplicated (by id) and sorted by recency (created_at desc)
    - Total context must not exceed the LLM context window limit (tracked via tiktoken)
    - Chunks and memory are truncated from the tail when the budget is exceeded

    Usage::

        builder = ContextBuilder(max_context_tokens=100_000)
        ctx = builder.build(
            chunks=reranked_top8,
            memory=project_memory,
            history=last_5_turns,
            related_files=file_metadata,
        )
        # ctx.total_tokens == actual tokens in assembled context
        # ctx.code_chunks may be shorter than input if truncated
    """

    # Static overhead budget: header strings, separators, labels (~500 tokens)
    _OVERHEAD_TOKENS: int = 500

    def __init__(self, max_context_tokens: int = 100_000) -> None:
        self._max_tokens = max_context_tokens

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(
        self,
        chunks: list["CodeChunk"],
        memory: list[MemoryEntry],
        history: list[ChatMessage],
        related_files: list[RepositoryFile] | None = None,
    ) -> AgentContext:
        """
        Assemble context for an LLM call.

        Steps:
            1. De-duplicate memory entries by id
            2. Sort memory by created_at desc (most recent first)
            3. Count tokens for each section using tiktoken
            4. Truncate chunks / memory from the tail if total exceeds max_context_tokens
            5. Set ctx.total_tokens

        Args:
            chunks:        Reranked top-8 (or top-N) code chunks from RAG pipeline.
            memory:        Relevant memory entries from project memory store.
            history:       Last N conversation turns.
            related_files: Optional file metadata for additional context.

        Returns:
            AgentContext ready to be serialised into a prompt by Dev's PromptBuilder.
        """
        if related_files is None:
            related_files = []

        # ---- Step 1 & 2: De-duplicate + sort memory -------------------------
        deduped_memory = self._dedup_memory(memory)

        # ---- Step 3 & 4: Token-budget-aware truncation ----------------------
        budget = self._max_tokens - self._OVERHEAD_TOKENS

        history_tokens, history_kept = self._fit_history(history, budget)
        budget -= history_tokens

        memory_tokens, memory_kept = self._fit_items(
            deduped_memory, budget, _format_memory
        )
        budget -= memory_tokens

        chunk_tokens, chunks_kept = self._fit_items(
            chunks, budget, _format_chunk
        )
        budget -= chunk_tokens

        # ---- Step 5: Total token count --------------------------------------
        total = (
            self._OVERHEAD_TOKENS
            + history_tokens
            + memory_tokens
            + chunk_tokens
        )

        ctx = AgentContext(
            code_chunks=chunks_kept,
            memory_chunks=memory_kept,
            related_files=list(related_files),
            recent_history=history_kept,
            total_tokens=total,
        )

        logger.info(
            "context_built",
            extra={
                "total_tokens": total,
                "max_tokens": self._max_tokens,
                "chunks_in": len(chunks),
                "chunks_kept": len(chunks_kept),
                "memory_in": len(memory),
                "memory_kept": len(memory_kept),
                "history_messages": len(history_kept),
            },
        )

        return ctx

    def render_repository_data(self, ctx: AgentContext) -> str:
        """
        Render the REPOSITORY DATA section as a plain string.

        This is the text that Dev's PromptBuilder places inside the **user**
        message — never the system message.

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
            A multi-line string ready for injection into the user message.
        """
        sections: list[str] = []

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

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _dedup_memory(entries: list[MemoryEntry]) -> list[MemoryEntry]:
        """
        De-duplicate memory entries by id and sort by created_at descending.

        Later entries with the same id overwrite earlier ones (last-write wins),
        then the unique set is sorted newest-first.
        """
        seen: dict[str, MemoryEntry] = {}
        for entry in entries:
            seen[entry.id] = entry  # last-write wins

        # Sort by ISO 8601 created_at string descending (lexicographic works)
        return sorted(seen.values(), key=lambda e: e.created_at, reverse=True)

    @staticmethod
    def _fit_history(
        history: list[ChatMessage],
        budget: int,
    ) -> tuple[int, list[ChatMessage]]:
        """
        Fit as many history messages as possible within *budget* tokens.

        Iterates from **newest to oldest** so that the most recent turns
        are always preserved. Returns (total_tokens_used, kept_messages)
        with messages in chronological order (oldest first).
        """
        kept: list[ChatMessage] = []
        used = 0
        for msg in reversed(history):
            tokens = count_tokens(_format_history_message(msg))
            if used + tokens > budget:
                break
            kept.append(msg)
            used += tokens

        kept.reverse()  # restore chronological order
        return used, kept

    @staticmethod
    def _fit_items(
        items: list,
        budget: int,
        formatter,
    ) -> tuple[int, list]:
        """
        Generic greedy token fitter — keeps items in order until budget is exhausted.

        Args:
            items:     Ordered list of items to include (highest priority first).
            budget:    Remaining token budget.
            formatter: Callable(item) -> str  for token counting.

        Returns:
            (tokens_used, kept_items)
        """
        kept = []
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
