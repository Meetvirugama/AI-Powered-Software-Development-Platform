"""
Abstract Retriever interface + CodeChunk model.
Owner: Meet — W1-12

All retrieval implementations (vector, lexical) share this contract.
The concrete implementations live in vector.py and lexical.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID


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
    score: float  # Relevance score from retriever (cosine sim or ts_rank or RRF)
    file_path: str  # Denormalised for context builder convenience


class Retriever(ABC):
    """
    Abstract retriever. Both VectorRetriever and LexicalRetriever implement this.
    RRFFusion and CrossEncoderReranker consume list[CodeChunk] from these.
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
