"""
Hybrid Retriever — Concurrent Vector + Lexical Search with RRF and Cross-Encoder Reranking.
Owner: Meet — W1-12

Integrates:
1. VectorRetriever (pgvector cosine similarity)
2. LexicalRetriever (PostgreSQL full-text search)
3. RRFFusion (Reciprocal Rank Fusion rank aggregation)
4. Optional CrossEncoderReranker (MiniLM cross-encoder joint scoring)

Features:
- Concurrent async retrieval using ``asyncio.gather`` for minimal latency.
- Graceful degradation: if vector or lexical search fails, proceeds with surviving results.
- End-to-end typing and lifecycle management.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Self
from uuid import UUID

from .base import CodeChunk, Retriever
from .fusion import RRFFusion
from .reranker import CrossEncoderReranker

logger = logging.getLogger(__name__)


class HybridRetriever(Retriever):
    """
    Production hybrid retriever combining vector similarity and lexical full-text search.
    """

    _DEFAULT_CANDIDATE_TOP_K: int = 30
    _DEFAULT_FINAL_TOP_K: int = 8

    def __init__(
        self,
        vector_retriever: Retriever,
        lexical_retriever: Retriever,
        fusion: RRFFusion | None = None,
        reranker: CrossEncoderReranker | None = None,
        vector_top_k: int = _DEFAULT_CANDIDATE_TOP_K,
        lexical_top_k: int = _DEFAULT_CANDIDATE_TOP_K,
    ) -> None:
        self._vector_retriever = vector_retriever
        self._lexical_retriever = lexical_retriever
        self._fusion = fusion or RRFFusion()
        self._reranker = reranker
        self._vector_top_k = vector_top_k
        self._lexical_top_k = lexical_top_k

    @property
    def vector_retriever(self) -> Retriever:
        """Configured vector search retriever."""
        return self._vector_retriever

    @property
    def lexical_retriever(self) -> Retriever:
        """Configured lexical search retriever."""
        return self._lexical_retriever

    @property
    def reranker(self) -> CrossEncoderReranker | None:
        """Optional cross-encoder reranker."""
        return self._reranker

    async def retrieve(
        self,
        query: str,
        repository_id: UUID | str,
        top_k: int = _DEFAULT_FINAL_TOP_K,
    ) -> list[CodeChunk]:
        """
        Execute concurrent hybrid retrieval, RRF fusion, and optional reranking.
        """
        if not query or not query.strip() or top_k <= 0:
            return []

        repo_uuid = (
            repository_id
            if isinstance(repository_id, UUID)
            else UUID(str(repository_id))
        )

        # Step 1: Run vector and lexical retrieval concurrently
        vector_task = self._vector_retriever.retrieve(
            query=query,
            repository_id=repo_uuid,
            top_k=self._vector_top_k,
        )
        lexical_task = self._lexical_retriever.retrieve(
            query=query,
            repository_id=repo_uuid,
            top_k=self._lexical_top_k,
        )

        vector_res, lexical_res = await asyncio.gather(
            vector_task, lexical_task, return_exceptions=True
        )

        vector_chunks: list[CodeChunk] = []
        if isinstance(vector_res, Exception):
            logger.error(
                "hybrid_retrieval_vector_failed",
                extra={"error": str(vector_res), "repo_id": str(repo_uuid)},
            )
        else:
            vector_chunks = vector_res

        lexical_chunks: list[CodeChunk] = []
        if isinstance(lexical_res, Exception):
            logger.error(
                "hybrid_retrieval_lexical_failed",
                extra={"error": str(lexical_res), "repo_id": str(repo_uuid)},
            )
        else:
            lexical_chunks = lexical_res

        if not vector_chunks and not lexical_chunks:
            logger.debug(
                "hybrid_retrieval_empty",
                extra={"repo_id": str(repo_uuid), "query_preview": query[:80]},
            )
            return []

        # Step 2: Reciprocal Rank Fusion
        fused = self._fusion.fuse(
            vector_chunks,
            lexical_chunks,
            top_n=max(top_k, self._DEFAULT_CANDIDATE_TOP_K),
        )

        if not fused:
            return []

        # Step 3: Optional Cross-Encoder Reranking (offloaded to worker thread to avoid blocking event loop)
        if self._reranker is not None:
            return await asyncio.to_thread(
                self._reranker.rerank,
                query=query,
                candidates=fused,
                top_n=top_k,
            )

        return fused[:top_k]

    async def aclose(self) -> None:
        """Close child retriever resources."""
        await self._vector_retriever.aclose()
        await self._lexical_retriever.aclose()

    async def __aenter__(self: Self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        await self.aclose()
