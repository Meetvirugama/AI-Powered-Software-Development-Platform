"""
Hybrid Retriever — Concurrent Vector + Lexical Search with RRF, Graph Expansion, Redis Caching, and Cross-Encoder Reranking.
Owner: Meet — W1-12

Integrates:
1. VectorRetriever (pgvector cosine similarity with adaptive HNSW ef_search)
2. LexicalRetriever (PostgreSQL code-aware full-text search)
3. RRFFusion (Adaptive Reciprocal Rank Fusion with intent-directed weights)
4. Bounded SymbolGraphExpander (1-hop symbol relationship graph expansion)
5. RetrievalResultCache (Asynchronous Redis result caching with generation invalidation)
6. Optional CrossEncoderReranker (MiniLM cross-encoder joint scoring)
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Self
from uuid import UUID

from .base import CodeChunk, RetrievalUnavailableError, Retriever
from .cache import RetrievalResultCache
from .cache_keys import build_retrieval_cache_key
from .fusion import RRFFusion
from .graph_expansion import SymbolGraphExpander
from .reranker import CrossEncoderReranker
from .vector import resolve_hnsw_profile

logger = logging.getLogger(__name__)

__all__ = ["HybridRetriever", "RetrievalUnavailableError"]


class HybridRetriever(Retriever):
    """
    Production hybrid retriever combining vector similarity, lexical full-text search,
    symbol graph expansion, Redis result caching, and cross-encoder reranking.
    """

    _DEFAULT_CANDIDATE_TOP_K: int = 30
    _DEFAULT_FINAL_TOP_K: int = 8

    def __init__(
        self,
        vector_retriever: Retriever | None = None,
        lexical_retriever: Retriever | None = None,
        fusion: RRFFusion | None = None,
        reranker: CrossEncoderReranker | None = None,
        graph_expander: SymbolGraphExpander | None = None,
        cache: RetrievalResultCache | None = None,
        vector_top_k: int = _DEFAULT_CANDIDATE_TOP_K,
        lexical_top_k: int = _DEFAULT_CANDIDATE_TOP_K,
    ) -> None:
        self._vector_retriever = vector_retriever
        self._lexical_retriever = lexical_retriever
        self._fusion = fusion or RRFFusion()
        self._reranker = reranker
        self._graph_expander = graph_expander
        self._cache = cache
        self._vector_top_k = vector_top_k
        self._lexical_top_k = lexical_top_k

    @property
    def vector_retriever(self) -> Retriever | None:
        """Configured vector search retriever."""
        return self._vector_retriever

    @property
    def lexical_retriever(self) -> Retriever | None:
        """Configured lexical search retriever."""
        return self._lexical_retriever

    @property
    def reranker(self) -> CrossEncoderReranker | None:
        """Optional cross-encoder reranker."""
        return self._reranker

    @property
    def graph_expander(self) -> SymbolGraphExpander | None:
        """Optional symbol-graph expander."""
        return self._graph_expander

    @property
    def cache(self) -> RetrievalResultCache | None:
        """Optional Redis result cache."""
        return self._cache

    async def retrieve(
        self,
        query: str,
        repository_id: UUID | str,
        top_k: int = _DEFAULT_FINAL_TOP_K,
        index_generation: int | str = 0,
        query_intent: str | None = None,
    ) -> list[CodeChunk]:
        """
        Execute concurrent hybrid retrieval with caching, intent routing, graph expansion,
        and optional reranking.
        """
        if not query or not query.strip() or top_k <= 0:
            return []

        repo_uuid = (
            repository_id
            if isinstance(repository_id, UUID)
            else UUID(str(repository_id))
        )

        # Step 1: Detect query intent
        intent = query_intent or self._fusion.detect_query_intent(query)

        # Step 2: Check Two-Level / Distributed Cache
        effective_index_gen = index_generation
        if (effective_index_gen == 0 or effective_index_gen == "0") and self._cache is not None:
            from .cache_keys import get_repository_index_version_async
            client = getattr(self._cache, "_get_client", lambda: None)() if hasattr(self._cache, "_get_client") else None
            effective_index_gen = await get_repository_index_version_async(repo_uuid, client)

        cache_key = build_retrieval_cache_key(
            query=query,
            repository_id=repo_uuid,
            index_generation=effective_index_gen,
            intent=str(intent),
            top_k=top_k,
            vector_top_k=self._vector_top_k,
            lexical_top_k=self._lexical_top_k,
        )

        if self._cache is not None:
            cached_results = await self._cache.get(cache_key)
            if cached_results is not None:
                logger.debug(
                    "hybrid_retrieval_cache_hit",
                    extra={"repo_id": str(repo_uuid), "key": cache_key, "count": len(cached_results)},
                )
                return cached_results

        # Step 3: Run vector and lexical retrieval concurrently
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
            # Check if vector_retriever supports profile/query_intent
            vec_sig = inspect.signature(self._vector_retriever.retrieve)
            vec_kwargs: dict[str, Any] = {
                "query": query,
                "repository_id": repo_uuid,
                "top_k": self._vector_top_k,
            }
            if "query_intent" in vec_sig.parameters:
                vec_kwargs["query_intent"] = str(intent)
            if "profile" in vec_sig.parameters:
                vec_kwargs["profile"] = resolve_hnsw_profile(str(intent))

            tasks.append(("vector", self._vector_retriever.retrieve(**vec_kwargs)))
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

        candidate_n = max(top_k, self._DEFAULT_CANDIDATE_TOP_K)

        # Step 4: Initial Reciprocal Rank Fusion
        fused = self._fusion.fuse_adaptive(
            query,
            vector_chunks,
            lexical_chunks,
            top_n=candidate_n,
        )

        if not fused:
            return []

        # Step 5: Bounded Symbol-Graph Expansion
        if self._graph_expander is not None:
            try:
                graph_chunks = await self._graph_expander.expand(
                    candidates=fused,
                    repository_id=repo_uuid,
                    intent=str(intent),
                )
                if graph_chunks:
                    fused = self._fusion.fuse_adaptive(
                        query,
                        vector_chunks,
                        lexical_chunks,
                        graph_results=graph_chunks,
                        top_n=candidate_n,
                    )
            except Exception as graph_exc:  # noqa: BLE001
                logger.warning(
                    "hybrid_retrieval_graph_expansion_error",
                    extra={"repo_id": str(repo_uuid), "error": str(graph_exc)},
                )

        # Step 6: Optional Cross-Encoder Reranking
        final_results: list[CodeChunk]
        if self._reranker is not None:
            final_results = await asyncio.to_thread(
                self._reranker.rerank,
                query=query,
                candidates=fused,
                top_n=top_k,
            )
        else:
            final_results = fused[:top_k]

        # Step 7: Store Final Results in Redis Cache (skip caching degraded fallback results)
        if self._cache is not None and final_results and not fallback_used:
            await self._cache.set(cache_key, final_results)

        return final_results

    async def aclose(self) -> None:
        """Close child retriever resources safely."""
        first_err: Exception | None = None
        for retriever in (self._vector_retriever, self._lexical_retriever):
            if retriever is not None and hasattr(retriever, "aclose") and callable(retriever.aclose):
                try:
                    await retriever.aclose()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("hybrid_retriever_child_close_error", extra={"error": str(exc)})
                    if first_err is None:
                        first_err = exc
        if first_err is not None:
            raise first_err

    async def __aenter__(self: Self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        await self.aclose()
