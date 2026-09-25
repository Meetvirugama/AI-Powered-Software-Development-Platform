"""
Cross-encoder reranker — selects top-8 chunks from RRF-fused candidates.
Owner: Meet — W1-12

Day 1: stub + model choice documented.
Day 5: full implementation using sentence-transformers cross-encoder.

Model: cross-encoder/ms-marco-MiniLM-L-6-v2
Input:  RRF-fused candidates (up to 30 unique chunks)
Output: top-8 chunks re-scored by cross-encoder, sorted desc.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Optional

from .base import CodeChunk

logger = logging.getLogger(__name__)

_DEFAULT_TOP_N = 8
_DEFAULT_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class CrossEncoderReranker:
    """
    Reranks RRF-fused candidates using a small cross-encoder model.

    The cross-encoder scores each (query, chunk) pair **jointly** by passing
    both through the same transformer — this is significantly more accurate
    than bi-encoder cosine similarity because it models query-document
    interactions directly. The trade-off is speed: we only run it on the
    top-30 RRF candidates, not the full index.

    Model: ``cross-encoder/ms-marco-MiniLM-L-6-v2``
    - ~22M parameters — fast enough for real-time use (< 200 ms for 30 pairs).
    - Trained on MS MARCO passage ranking; generalises well to code Q&A.
    - Returns raw logit scores (not calibrated probabilities) — higher = better.

    The model is loaded **lazily** on first use so that importing this module
    does not block startup even if sentence-transformers is slow to initialise.

    Usage::

        reranker = CrossEncoderReranker()
        top8 = reranker.rerank(query, fused_candidates, top_n=8)
    """

    def __init__(self, model_name: str = _DEFAULT_MODEL) -> None:
        self._model_name = model_name
        self._model: Optional[object] = None  # Lazy-loaded CrossEncoder

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def rerank(
        self,
        query: str,
        candidates: list[CodeChunk],
        top_n: int = _DEFAULT_TOP_N,
    ) -> list[CodeChunk]:
        """
        Score each candidate against the query and return the top_n.

        Steps:
        1. Load the cross-encoder model (lazy — only on first call).
        2. Build ``(query, chunk.content)`` pairs for every candidate.
        3. Batch-predict logit scores via ``CrossEncoder.predict()``.
        4. Sort by score descending, slice top_n.
        5. Replace ``chunk.score`` with the cross-encoder logit score.

        Args:
            query:      Original user query (natural language or code).
            candidates: RRF-fused chunk list (typically ≤ 30).
                        If empty, returns [].
            top_n:      Number of highest-scoring chunks to return (default 8).

        Returns:
            Up to ``top_n`` CodeChunks with ``.score`` set to the cross-encoder
            logit score, sorted descending (most relevant first).

        Raises:
            RuntimeError: If sentence-transformers is not installed.
        """
        if not candidates:
            return []

        model = self._get_model()

        # Build input pairs for the cross-encoder
        pairs = [(query, chunk.content) for chunk in candidates]

        # Batch predict — returns numpy array of float32 logit scores
        raw_scores = model.predict(pairs)  # type: ignore[union-attr]

        # Sort by score descending and take top_n
        ranked = sorted(
            zip(raw_scores, candidates),
            key=lambda x: float(x[0]),
            reverse=True,
        )
        top_ranked = ranked[:top_n]

        reranked: list[CodeChunk] = [
            dataclasses.replace(chunk, score=round(float(score), 4))
            for score, chunk in top_ranked
        ]

        logger.info(
            "reranker_complete",
            extra={
                "model": self._model_name,
                "num_candidates": len(candidates),
                "top_n": top_n,
                "returned": len(reranked),
                "top_score": round(float(ranked[0][0]), 4) if ranked else None,
                "bottom_score": round(float(ranked[-1][0]), 4) if ranked else None,
            },
        )

        return reranked

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_model(self) -> object:
        """
        Lazily load the CrossEncoder model on first use.

        This avoids importing sentence-transformers at module load time,
        which would add ~2 s to startup and would fail in environments
        where the library is not installed.

        Raises:
            RuntimeError: If sentence-transformers is not installed.
        """
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder  # type: ignore[import]
            except ImportError as exc:
                raise RuntimeError(
                    "sentence-transformers is required for CrossEncoderReranker. "
                    "Install it with: pip install sentence-transformers"
                ) from exc

            logger.info(
                "reranker_model_loading",
                extra={"model": self._model_name},
            )
            self._model = CrossEncoder(self._model_name)
            logger.info(
                "reranker_model_loaded",
                extra={"model": self._model_name},
            )

        return self._model
