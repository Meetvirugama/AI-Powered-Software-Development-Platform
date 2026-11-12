"""
Optional Local Code Embedding Provider (`nomic-ai/CodeRankEmbed`) & ADR-008 Compliance Guard.

P3 Scope:
- Evaluates `nomic-ai/CodeRankEmbed` (137M bi-encoder, 768 dimensions, 8192 max tokens,
  query prefix `"Represent this query for searching relevant code: "`, MIT/Apache-2.0).
- Enforces ADR-008: Local embeddings are disabled by default because ADR-008 restricts
  default production AI providers to Google Gemini and Groq (`ai_quality_evaluator.py`).
- Requires explicit `allow_local_embeddings=True` opt-in and uses a distinct
  `EmbeddingProfile` (`provider="local_coderank"`, `model="nomic-ai/CodeRankEmbed"`)
  so local vectors are never mixed with Gemini vectors.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
import importlib.util
from typing import Any

from .client import (
    EmbeddingError,
    EmbeddingProfile,
    EmbeddingProvider,
    l2_normalize_vector,
)


@dataclass(frozen=True)
class LocalEmbeddingModelSpec:
    """Verified technical specification for an optional local code embedding model."""

    provider_name: str
    model_name: str
    dimensions: int
    max_seq_length: int
    query_prefix: str
    document_prefix: str
    pooling: str
    license_spdx: str
    parameters_millions: int


CODERANK_MODEL_SPEC = LocalEmbeddingModelSpec(
    provider_name="local_coderank",
    model_name="nomic-ai/CodeRankEmbed",
    dimensions=768,
    max_seq_length=8192,
    query_prefix="Represent this query for searching relevant code: ",
    document_prefix="",
    pooling="cls",
    license_spdx="MIT",
    parameters_millions=137,
)


def evaluate_local_embedding_candidate() -> dict[str, Any]:
    """
    Evaluate `nomic-ai/CodeRankEmbed` runtime availability, hardware/dependency readiness,
    and ADR-008 policy status without loading model weights into memory.
    """
    has_sentence_transformers = importlib.util.find_spec("sentence_transformers") is not None
    has_torch = importlib.util.find_spec("torch") is not None
    return {
        "provider": CODERANK_MODEL_SPEC.provider_name,
        "model": CODERANK_MODEL_SPEC.model_name,
        "dimensions": CODERANK_MODEL_SPEC.dimensions,
        "max_seq_length": CODERANK_MODEL_SPEC.max_seq_length,
        "query_prefix": CODERANK_MODEL_SPEC.query_prefix,
        "pooling": CODERANK_MODEL_SPEC.pooling,
        "license": CODERANK_MODEL_SPEC.license_spdx,
        "parameters_millions": CODERANK_MODEL_SPEC.parameters_millions,
        "sentence_transformers_installed": has_sentence_transformers,
        "torch_installed": has_torch,
        "adr_008_default_allowed": False,
        "requires_explicit_opt_in": True,
        "schema_compatible_768d": True,
    }


class CodeRankEmbedProvider(EmbeddingProvider):
    """
    Optional local `nomic-ai/CodeRankEmbed` provider gated behind explicit ADR-008 opt-in.
    """

    def __init__(
        self,
        *,
        allow_local_embeddings: bool = False,
        model_name: str = CODERANK_MODEL_SPEC.model_name,
        dimensions: int = CODERANK_MODEL_SPEC.dimensions,
        query_prefix: str = CODERANK_MODEL_SPEC.query_prefix,
        embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
    ) -> None:
        if not allow_local_embeddings:
            raise EmbeddingError(
                "Local embedding provider 'local_coderank' (nomic-ai/CodeRankEmbed) is disabled by default "
                "under ADR-008 (which restricts default AI providers to Gemini and Groq). "
                "Pass allow_local_embeddings=True and explicitly authorize 'local_coderank' in AIQualityEvaluator "
                "to enable local evaluation.",
                retryable=False,
                provider=CODERANK_MODEL_SPEC.provider_name,
            )
        if dimensions != CODERANK_MODEL_SPEC.dimensions:
            raise ValueError(
                f"CodeRankEmbed requires {CODERANK_MODEL_SPEC.dimensions} dimensions, got {dimensions}."
            )

        self._model_name = model_name
        self._dimensions = dimensions
        self._query_prefix = query_prefix
        self._embed_fn = embed_fn
        self._st_model: Any = None

    @property
    def provider_name(self) -> str:
        return CODERANK_MODEL_SPEC.provider_name

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def embedding_dimensions(self) -> int:
        return self._dimensions

    @property
    def profile(self) -> EmbeddingProfile:
        return EmbeddingProfile(
            provider=self.provider_name,
            model=self._model_name,
            dimensions=self._dimensions,
            normalization=True,
            distance_metric="cosine",
            profile_version="v2",
            document_task_type="RETRIEVAL_DOCUMENT",
            query_task_type="CODE_RETRIEVAL_QUERY",
            active_task_type="RETRIEVAL_DOCUMENT",
            contextual_headers=True,
            chunker_version="v2_cast",
        )

    def _encode_sync(self, texts: list[str]) -> list[list[float]]:
        if self._embed_fn is not None:
            raw_vectors = self._embed_fn(texts)
        else:
            if self._st_model is None:
                try:
                    from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]
                except ImportError as exc:
                    raise EmbeddingError(
                        "sentence-transformers is required to run nomic-ai/CodeRankEmbed locally.",
                        retryable=False,
                        provider=self.provider_name,
                    ) from exc
                self._st_model = SentenceTransformer(self._model_name, trust_remote_code=True)
            encoded = self._st_model.encode(texts, normalize_embeddings=True)
            raw_vectors = [list(map(float, row)) for row in encoded]

        return [
            l2_normalize_vector(vec, expected_dim=self._dimensions, provider=self.provider_name)
            for vec in raw_vectors
        ]

    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        return await asyncio.to_thread(self._encode_sync, list(texts))

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed code chunks without query prefix and L2-normalize outputs."""
        return await self.embed_batch(texts)

    async def embed_query(self, text: str) -> list[float]:
        """Prepend CodeRankEmbed asymmetric query prefix and L2-normalize output."""
        prefixed = (
            text
            if text.startswith(self._query_prefix)
            else f"{self._query_prefix}{text}"
        )
        results = await self.embed_batch([prefixed])
        if not results:
            raise EmbeddingError(
                "CodeRankEmbed returned empty vector for query.",
                retryable=False,
                provider=self.provider_name,
            )
        return results[0]
