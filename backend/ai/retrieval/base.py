"""
Abstract Retriever interface + CodeChunk model.
Owner: Meet — W1-12

All retrieval implementations (vector, lexical, hybrid) share this contract.
Concrete implementations:
- vector.py:    VectorRetriever (pgvector cosine similarity)
- lexical.py:   LexicalRetriever (PostgreSQL full-text search)
- hybrid.py:    HybridRetriever (Concurrent vector + lexical + RRF + optional rerank)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Self
from uuid import UUID


class RetrievalUnavailableError(RuntimeError):
    """Raised when all configured retrieval backends fail (e.g. both vector and lexical search error)."""

    def __init__(
        self,
        message: str = "Retrieval service unavailable: both vector and lexical search failed.",
        vector_error: Exception | None = None,
        lexical_error: Exception | None = None,
        repo_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.vector_error = vector_error
        self.lexical_error = lexical_error
        self.repo_id = repo_id


@dataclass
class CodeChunk:
    """
    A single code chunk returned by any retriever.
    Mirrors the `code_chunks` table schema (Om — W1-02).
    """

    id: UUID
    repository_id: UUID
    file_id: UUID
    symbol_id: UUID | None
    content: str
    token_count: int
    start_line: int
    end_line: int
    content_hash: str
    score: float  # Relevance score from retriever (cosine sim, ts_rank, RRF, or reranker logit)
    file_path: str  # Denormalised for context builder convenience
    rrf_score: float | None = None
    reranker_logit: float | None = None
    vector_similarity: float | None = None
    lexical_rank: float | None = None

    def __post_init__(self) -> None:
        """Defensively ensure UUID types for primary identification fields."""
        if not isinstance(self.id, UUID):
            self.id = UUID(str(self.id))
        if not isinstance(self.repository_id, UUID):
            self.repository_id = UUID(str(self.repository_id))
        if not isinstance(self.file_id, UUID):
            self.file_id = UUID(str(self.file_id))
        if self.symbol_id is not None and not isinstance(self.symbol_id, UUID):
            self.symbol_id = UUID(str(self.symbol_id))

    @property
    def header(self) -> str:
        """Formatted header representation for context assembly."""
        return f"--- {self.file_path} (lines {self.start_line}–{self.end_line}) ---"

    def to_dict(self) -> dict[str, Any]:
        """Convert chunk to a serializable dictionary representation."""
        data = asdict(self)
        data["id"] = str(self.id)
        data["repository_id"] = str(self.repository_id)
        data["file_id"] = str(self.file_id)
        data["symbol_id"] = str(self.symbol_id) if self.symbol_id else None
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CodeChunk:
        """Construct a CodeChunk instance from a mapping or database dictionary."""
        sym_id = data.get("symbol_id")
        return cls(
            id=UUID(str(data["id"])),
            repository_id=UUID(str(data["repository_id"])),
            file_id=UUID(str(data["file_id"])),
            symbol_id=UUID(str(sym_id)) if sym_id else None,
            content=str(data.get("content", "")),
            token_count=int(data.get("token_count", 0)),
            start_line=int(data.get("start_line", 1)),
            end_line=int(data.get("end_line", 1)),
            content_hash=str(data.get("content_hash", "")),
            score=float(data.get("score", 0.0)),
            file_path=str(data.get("file_path", "")),
            rrf_score=float(data["rrf_score"]) if data.get("rrf_score") is not None else None,
            reranker_logit=float(data["reranker_logit"]) if data.get("reranker_logit") is not None else None,
            vector_similarity=float(data["vector_similarity"]) if data.get("vector_similarity") is not None else None,
            lexical_rank=float(data["lexical_rank"]) if data.get("lexical_rank") is not None else None,
        )

    @classmethod
    def from_any(cls, item: Any) -> CodeChunk:
        """Coerce CodeChunk, Mapping, or duck-typed object into a CodeChunk."""
        if isinstance(item, cls):
            return item
        if isinstance(item, Mapping):
            return cls.from_dict(item)
        return cls(
            id=UUID(str(item.id)),
            repository_id=UUID(str(item.repository_id)),
            file_id=UUID(str(item.file_id)),
            symbol_id=(
                UUID(str(item.symbol_id))
                if getattr(item, "symbol_id", None)
                else None
            ),
            content=str(getattr(item, "content", "")),
            token_count=int(getattr(item, "token_count", 0)),
            start_line=int(getattr(item, "start_line", 1)),
            end_line=int(getattr(item, "end_line", 1)),
            content_hash=str(getattr(item, "content_hash", "")),
            score=float(getattr(item, "score", 0.0)),
            file_path=str(getattr(item, "file_path", "")),
            rrf_score=getattr(item, "rrf_score", None),
            reranker_logit=getattr(item, "reranker_logit", None),
            vector_similarity=getattr(item, "vector_similarity", None),
            lexical_rank=getattr(item, "lexical_rank", None),
        )


class Retriever(ABC):
    """
    Abstract retriever interface.
    VectorRetriever, LexicalRetriever, and HybridRetriever implement this contract.
    """

    @abstractmethod
    async def retrieve(
        self,
        query: str,
        repository_id: UUID,
        top_k: int = 30,
    ) -> list[CodeChunk]:
        """
        Retrieve the top-k most relevant code chunks for a query.

        Args:
            query: Natural-language or code query string.
            repository_id: Scope results to this repository only.
            top_k: Maximum number of chunks to return (default 30 for RRF input).

        Returns:
            List of CodeChunk sorted by descending relevance score.
        """
        ...

    async def aclose(self) -> None:
        """Release underlying connections or models (default no-op)."""

    async def __aenter__(self: Self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        await self.aclose()
