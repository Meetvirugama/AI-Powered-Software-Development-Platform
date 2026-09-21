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

from .base import CodeChunk

_DEFAULT_TOP_N = 8
_DEFAULT_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class CrossEncoderReranker:
    """
    Reranks RRF-fused candidates using a small cross-encoder model.

    The cross-encoder scores each (query, chunk) pair jointly — this is more
    accurate than bi-encoder similarity but slower, so we only run it on the
    top-30 RRF candidates, not the full index.

    Usage (Day 5):
        reranker = CrossEncoderReranker()
        top8 = reranker.rerank(query, fused_candidates, top_n=8)
    """

    def __init__(self, model_name: str = _DEFAULT_MODEL) -> None:
        self._model_name = model_name
        # Day 5: self._model = CrossEncoder(model_name)

    def rerank(
        self,
        query: str,
        candidates: list[CodeChunk],
        top_n: int = _DEFAULT_TOP_N,
    ) -> list[CodeChunk]:
        """
        Score each candidate against the query and return the top_n.

        Args:
            query: Original user query.
            candidates: RRF-fused chunk list (typically ≤ 30).
            top_n: Number of chunks to return (default 8).

        Returns:
            top_n CodeChunks with chunk.score set to cross-encoder logit score.
        """
        # Day 5 implementation:
        #   pairs = [(query, chunk.content) for chunk in candidates]
        #   scores = self._model.predict(pairs)
        #   ranked = sorted(zip(scores, candidates), key=lambda x: x[0], reverse=True)
        #   return [dataclasses.replace(chunk, score=float(score)) for score, chunk in ranked[:top_n]]
        raise NotImplementedError("CrossEncoderReranker implemented on Day 5.")
