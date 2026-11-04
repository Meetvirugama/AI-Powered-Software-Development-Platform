"""
Reciprocal Rank Fusion (RRF) — combines vector + lexical results.
Owner: Meet — W1-12

Day 1: stub + algorithm docstring.
Day 5: full implementation.

RRF formula:
    score(chunk) = Σ w_i / (k + rank_i)
    where k=60 (constant), w_i is the source weight (default 1.0), and
    rank_i is the chunk's 1-based position in each list.

Input:  two lists of CodeChunk (top-30 each from Vector and Lexical retrievers)
Output: single merged list of up to 30 unique chunks, sorted by RRF score desc.
"""

from __future__ import annotations

import dataclasses
import logging
import re
from collections import defaultdict
from uuid import UUID

from .base import CodeChunk

logger = logging.getLogger(__name__)

_RRF_K = 60          # Standard constant — do not change without benchmarking
_DEFAULT_TOP_N = 30  # Max fused candidates passed to CrossEncoderReranker

_SYMBOL_QUERY_RE = re.compile(
    r"(`[^`]+`|[A-Za-z0-9_]+\.[A-Za-z0-9_]+|[a-z]+_[a-z0-9_]+|[a-z]+[A-Z][A-Za-z0-9]*|\b(?:def|class|fn|func|interface|struct)\s+\w+)"
)


class RRFFusion:
    """
    Merges results from multiple retrieval sources using Reciprocal Rank Fusion.

    RRF is a rank-aggregation method that gives each chunk a score based on
    its position (rank) in each source list, not its raw similarity score.
    This makes it robust to different score scales across retrieval methods.

    Formula:
        score(chunk) = Σ  w_i / (k + rank_i)

    where ``k=60`` is a smoothing constant, ``w_i`` is an optional per-source
    weight (default 1.0), and ``rank_i`` is the chunk's 1-based position in
    result list ``i``.

    Usage::

        fusion = RRFFusion()
        combined = fusion.fuse(vector_results, lexical_results)
        # combined → top-30 unique chunks by RRF score, ready for reranker
    """

    @staticmethod
    def detect_query_intent(query: str) -> str:
        """Classify query intent as 'symbol' (exact identifier/path) or 'conceptual'."""
        if not query or not query.strip():
            return "conceptual"
        if _SYMBOL_QUERY_RE.search(query):
            return "symbol"
        return "conceptual"

    def fuse(
        self,
        *result_lists: list[CodeChunk],
        k: int = _RRF_K,
        top_n: int = _DEFAULT_TOP_N,
        weights: list[float] | None = None,
    ) -> list[CodeChunk]:
        """
        Apply RRF across any number of ranked result lists.

        Each chunk is identified by its UUID. If the same chunk appears in
        multiple result lists, its RRF score is the **sum** of per-list
        contributions — rewarding chunks that are consistently retrieved.

        The ``chunk.score`` field on returned chunks is replaced with the
        computed RRF score (not the original similarity/rank score).

        Args:
            *result_lists: One or more ranked lists of CodeChunk (best first).
                           Typically two: [vector_results, lexical_results].
            k:             RRF smoothing constant (default 60 — do not tune
                           without benchmarking on the full dataset).
            top_n:         Maximum number of fused candidates to return
                           (default 30 — feeds the CrossEncoderReranker).
            weights:       Optional per-source weight multipliers matching
                           ``result_lists`` length (defaults to 1.0 for each source).

        Returns:
            Merged, deduplicated list of ``CodeChunk`` sorted by descending
            RRF score. Each chunk's ``.score`` field holds the RRF score.
            Length ≤ ``top_n``.

        Example::

            fusion = RRFFusion()
            top30 = fusion.fuse(vector_top30, lexical_top30)
            # top30[0] is the chunk with the highest RRF score
        """
        if not result_lists or top_n <= 0:
            return []
        if k <= 0:
            raise ValueError(f"RRF smoothing constant k must be positive, got {k}")

        effective_weights = weights or [1.0] * len(result_lists)
        if len(effective_weights) != len(result_lists):
            raise ValueError(
                f"weights length ({len(effective_weights)}) must match result_lists count ({len(result_lists)})"
            )

        # Accumulate RRF scores across all source lists
        scores: dict[UUID, float] = defaultdict(float)
        chunk_map: dict[UUID, CodeChunk] = {}

        for weight, results in zip(effective_weights, result_lists):
            for rank, chunk in enumerate(results, start=1):
                scores[chunk.id] += float(weight) / (k + rank)
                # Keep the latest seen object (all should be identical by id)
                chunk_map[chunk.id] = chunk

        # Sort by RRF score descending with stable UUID tie-breaking, take top_n
        sorted_ids = sorted(scores, key=lambda cid: (-scores[cid], str(cid)))
        top_ids = sorted_ids[:top_n]

        fused: list[CodeChunk] = [
            dataclasses.replace(
                chunk_map[cid],
                score=round(scores[cid], 6),
                rrf_score=round(scores[cid], 6),
            )
            for cid in top_ids
        ]

        logger.info(
            "rrf_fusion_complete",
            extra={
                "num_sources": len(result_lists),
                "unique_candidates": len(scores),
                "returned": len(fused),
                "k": k,
                "top_rrf_score": round(fused[0].score, 6) if fused else None,
            },
        )

        return fused

    def fuse_adaptive(
        self,
        query: str,
        vector_results: list[CodeChunk],
        lexical_results: list[CodeChunk],
        *,
        k: int = _RRF_K,
        top_n: int = _DEFAULT_TOP_N,
    ) -> list[CodeChunk]:
        """Fuse vector and lexical results with query-intent-aware source weights."""
        intent = self.detect_query_intent(query)
        weights = [0.8, 1.4] if intent == "symbol" else [1.2, 0.9]
        return self.fuse(vector_results, lexical_results, k=k, top_n=top_n, weights=weights)
