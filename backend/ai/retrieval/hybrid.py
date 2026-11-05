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

from .base import CodeChunk, RetrievalUnavailableError, Retriever
from .fusion import RRFFusion
from .reranker import CrossEncoderReranker

logger = logging.getLogger(__name__)

__all__ = ["HybridRetriever", "RetrievalUnavailableError"]


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
        vector_chunks: list[CodeChunk] = []
        lexical_chunks: list[CodeChunk] = []
        vector_failed = False
        lexical_failed = False
        vector_exc: Exception | None = None
        lexical_exc: Exception | None = None
        vector_err_str: str | None = None
        lexical_err_str: str | None = None

        tasks = []
        if self._vector_retriever is not None:
            tasks.append(("vector", self._vector_retriever.retrieve(
                query=query,
                repository_id=repo_uuid,
                top_k=self._vector_top_k,
            )))
        else:
            vector_failed = True
            vector_err_str = "Vector retriever not configured."

        if self._lexical_retriever is not None:
            tasks.append(("lexical", self._lexical_retriever.retrieve(
                query=query,
                repository_id=repo_uuid,
                top_k=self._lexical_top_k,
            )))
        else:
            lexical_failed = True
            lexical_err_str = "Lexical retriever not configured."

        if tasks:
            results = await asyncio.gather(*(t[1] for t in tasks), return_exceptions=True)
            for (kind, _), res in zip(tasks, results):
                if kind == "vector":
                    if isinstance(res, Exception):
                        vector_failed = True
                        vector_exc = res
                        vector_err_str = str(res)
                        logger.error(
                            "hybrid_retrieval_vector_failed",
                            extra={"error": vector_err_str, "repo_id": str(repo_uuid)},
                        )
                    else:
                        vector_chunks = res or []
                elif kind == "lexical":
                    if isinstance(res, Exception):
                        lexical_failed = True
                        lexical_exc = res
                        lexical_err_str = str(res)
                        logger.error(
                            "hybrid_retrieval_lexical_failed",
                            extra={"error": lexical_err_str, "repo_id": str(repo_uuid)},
                        )
                    else:
                        lexical_chunks = res or []

        # If both retrievers failed, this is an infrastructure outage, NOT zero matching code.
        if vector_failed and lexical_failed:
            logger.error(
                "hybrid_retrieval_all_sources_failed",
                extra={
                    "repo_id": str(repo_uuid),
                    "vector_error": vector_err_str,
                    "lexical_error": lexical_err_str,
                },
            )
            raise RetrievalUnavailableError(
                message=f"Hybrid retrieval failed for repo {repo_uuid}: both vector and lexical search failed.",
                vector_error=vector_exc,
                lexical_error=lexical_exc,
                repo_id=str(repo_uuid),
            )

        fallback_used = vector_failed or lexical_failed
        if fallback_used:
            surviving = "lexical" if vector_failed else "vector"
            failed_source = "vector" if vector_failed else "lexical"
            logger.warning(
                "hybrid_retrieval_fallback_active",
                extra={
                    "repo_id": str(repo_uuid),
                    "failed_source": failed_source,
                    "surviving_source": surviving,
                    "vector_error": vector_err_str,
                    "lexical_error": lexical_err_str,
                },
            )

        # Legitimate empty result: at least one source succeeded without error, but 0 matches were found.
        if not vector_chunks and not lexical_chunks:
            logger.debug(
                "hybrid_retrieval_empty",
                extra={
                    "repo_id": str(repo_uuid),
                    "query_preview": query[:80],
                    "vector_status": "failed" if vector_failed else "success",
                    "lexical_status": "failed" if lexical_failed else "success",
                    "fallback_used": fallback_used,
                },
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
