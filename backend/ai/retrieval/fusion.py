"""
Reciprocal Rank Fusion (RRF) — combines vector + lexical results.
Owner: Meet — W1-12

Day 1: stub + algorithm docstring.
Day 5: full implementation.

RRF formula:
    score(chunk) = Σ 1 / (k + rank_i)
    where k=60 (constant) and rank_i is the chunk's 1-based position in each list.

Input:  two lists of CodeChunk (top-30 each from Vector and Lexical retrievers)
Output: single merged list of up to 30 unique chunks, sorted by RRF score desc.
"""

from __future__ import annotations

import dataclasses
import logging
from collections import defaultdict
from uuid import UUID

from .base import CodeChunk

logger = logging.getLogger(__name__)

_RRF_K = 60          # Standard constant — do not change without benchmarking
_DEFAULT_TOP_N = 30  # Max fused candidates passed to CrossEncoderReranker


class RRFFusion:
    """
    Merges results from multiple retrieval sources using Reciprocal Rank Fusion.

    RRF is a rank-aggregation method that gives each chunk a score based on
    its position (rank) in each source list, not its raw similarity score.
    This makes it robust to different score scales across retrieval methods.

    Formula:
        score(chunk) = Σ  1 / (k + rank_i)

    where ``k=60`` is a smoothing constant and ``rank_i`` is the chunk's
    1-based position in result list ``i``.

    Usage::

        fusion = RRFFusion()
        combined = fusion.fuse(vector_results, lexical_results)
        # combined → top-30 unique chunks by RRF score, ready for reranker
    """

    def fuse(
        self,
        *result_lists: list[CodeChunk],
        k: int = _RRF_K,
        top_n: int = _DEFAULT_TOP_N,
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

        Returns:
            Merged, deduplicated list of ``CodeChunk`` sorted by descending
            RRF score. Each chunk's ``.score`` field holds the RRF score.
            Length ≤ ``top_n``.

        Example::

            fusion = RRFFusion()
            top30 = fusion.fuse(vector_top30, lexical_top30)
            # top30[0] is the chunk with the highest RRF score
        """
        if not result_lists:
            return []

        # Accumulate RRF scores across all source lists
        scores: dict[UUID, float] = defaultdict(float)
        chunk_map: dict[UUID, CodeChunk] = {}

        for results in result_lists:
            for rank, chunk in enumerate(results, start=1):
                scores[chunk.id] += 1.0 / (k + rank)
                # Keep the latest seen object (all should be identical by id)
                chunk_map[chunk.id] = chunk

        # Sort by RRF score descending, take top_n
        sorted_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)
        top_ids = sorted_ids[:top_n]

        fused: list[CodeChunk] = [
            dataclasses.replace(chunk_map[cid], score=round(scores[cid], 6))
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
