"""
Abstract Embedding Provider Interface, Task Types, L2 Normalization, and Structured Error Hierarchy.

Defines the contract for embedding providers (Gemini, optional local CodeRankEmbed, etc.),
embedding profile compatibility rules (v1 and v2), strict L2 vector normalization,
and domain exceptions used throughout retrieval and vector storage pipelines.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from enum import StrEnum
import math
import struct
from typing import Any, Self

from pydantic import BaseModel, model_validator

_ZERO_NORM_EPSILON: float = 1e-12


class GeminiTaskType(StrEnum):
    """Official Google Gemini Embedding API taskType enum values."""

    RETRIEVAL_DOCUMENT = "RETRIEVAL_DOCUMENT"
    RETRIEVAL_QUERY = "RETRIEVAL_QUERY"
    CODE_RETRIEVAL_QUERY = "CODE_RETRIEVAL_QUERY"
    SEMANTIC_SIMILARITY = "SEMANTIC_SIMILARITY"
    CLASSIFICATION = "CLASSIFICATION"
    CLUSTERING = "CLUSTERING"
    QUESTION_ANSWERING = "QUESTION_ANSWERING"
    FACT_VERIFICATION = "FACT_VERIFICATION"


# Compatible task-type pairs between indexed documents and search queries
_COMPATIBLE_RETRIEVAL_TASK_TYPES: frozenset[str] = frozenset(
    {
        GeminiTaskType.RETRIEVAL_DOCUMENT.value,
        GeminiTaskType.CODE_RETRIEVAL_QUERY.value,
        GeminiTaskType.RETRIEVAL_QUERY.value,
    }
)


class EmbeddingError(Exception):
    """
    Base structured exception for all embedding-related errors.

    Attributes:
        message: Descriptive error message.
        retryable: Whether the caller should attempt to retry this operation.
        status_code: Optional HTTP status code from upstream provider.
        provider: Name of the provider that produced the error.
    """

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
        provider: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.retryable = retryable
        self.status_code = status_code
        self.provider = provider

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(message={self.message!r}, "
            f"retryable={self.retryable}, status_code={self.status_code}, provider={self.provider!r})"
        )


class RateLimitError(EmbeddingError):
    """Raised when an embedding provider returns a rate limit (HTTP 429)."""

    def __init__(
        self,
        message: str = "Embedding rate limit reached (HTTP 429).",
        *,
        retry_after: float | None = None,
        provider: str | None = None,
    ) -> None:
        super().__init__(message, retryable=True, status_code=429, provider=provider)
        self.retry_after = retry_after


class ProviderUnavailableError(EmbeddingError):
    """Raised on upstream 5xx errors or connection/timeout failures."""

    def __init__(
        self,
        message: str = "Embedding provider unavailable or request timed out.",
        *,
        status_code: int | None = 503,
        provider: str | None = None,
    ) -> None:
        super().__init__(message, retryable=True, status_code=status_code, provider=provider)


class AuthenticationError(EmbeddingError):
    """Raised when provider authentication fails (e.g. invalid API key)."""

    def __init__(
        self,
        message: str = "Embedding provider authentication failed (HTTP 401/403).",
        *,
        status_code: int = 401,
        provider: str | None = None,
    ) -> None:
        super().__init__(message, retryable=False, status_code=status_code, provider=provider)


class InvalidRequestError(EmbeddingError):
    """Raised on non-retryable 4xx client errors (e.g. malformed inputs)."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 400,
        provider: str | None = None,
    ) -> None:
        super().__init__(message, retryable=False, status_code=status_code, provider=provider)


class DimensionMismatchError(EmbeddingError):
    """
    Raised when an embedding vector does not match the provider's declared dimension.

    Indicates a critical configuration mismatch between DB schema and provider model.
    """

    def __init__(
        self,
        expected: int,
        actual: int,
        *,
        provider: str | None = None,
    ) -> None:
        message = (
            f"Embedding dimension mismatch: expected {expected}, got {actual}. "
            f"Check that the provider model matches the configured dimension."
        )
        super().__init__(message, retryable=False, status_code=None, provider=provider)
        self.expected = expected
        self.actual = actual


class InvalidVectorError(EmbeddingError, ValueError):
    """
    Raised when an embedding vector contains non-finite values (NaN/Inf)
    or has a zero / near-zero L2 norm that cannot be normalized safely.
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
    ) -> None:
        EmbeddingError.__init__(self, message, retryable=False, status_code=None, provider=provider)


def l2_normalize_vector(
    vector: Sequence[float],
    *,
    expected_dim: int | None = None,
    provider: str | None = None,
) -> list[float]:
    """
    Validate and L2-normalize an embedding vector to unit length (||v||_2 = 1.0).

    Rejects empty vectors, wrong dimensions, non-finite values (NaN/Inf),
    and zero-norm vectors without silently substituting fallback values.
    """
    if vector is None or len(vector) == 0:
        raise InvalidVectorError("Embedding vector cannot be empty.", provider=provider)

    actual_dim = len(vector)
    if expected_dim is not None and actual_dim != expected_dim:
        raise DimensionMismatchError(
            expected=expected_dim,
            actual=actual_dim,
            provider=provider,
        )

    floats: list[float] = []
    sum_sq = 0.0
    for idx, val in enumerate(vector):
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise InvalidVectorError(
                f"Vector contains non-numeric element at index {idx}: {val!r}",
                provider=provider,
            )
        fval = float(val)
        if not math.isfinite(fval):
            raise InvalidVectorError(
                f"Vector contains non-finite value at index {idx}: {fval}",
                provider=provider,
            )
        floats.append(fval)
        sum_sq += fval * fval

    norm = math.sqrt(sum_sq)
    if not math.isfinite(norm) or norm <= _ZERO_NORM_EPSILON:
        raise InvalidVectorError(
            f"Cannot L2-normalize zero-norm embedding vector (L2 norm={norm:.3e}).",
            provider=provider,
        )

    return [v / norm for v in floats]


def _quantize_float16_roundtrip(vector: Sequence[float]) -> list[float]:
    """Simulate pgvector `halfvec` IEEE-754 float16 storage roundtrip."""
    out: list[float] = []
    for v in vector:
        packed = struct.pack("<e", float(v))
        unpacked = struct.unpack("<e", packed)[0]
        out.append(float(unpacked))
    return out


def evaluate_vector_storage_modes(
    corpus_vectors: Sequence[Sequence[float]],
    query_vectors: Sequence[Sequence[float]],
    *,
    expected_dim: int = 768,
) -> dict[str, Any]:
    """
    Benchmark cosine similarity (`<=>`) vs inner product (`<#>`) and `halfvec` (float16)
    on L2-normalized vectors without changing the default `<=>` search operator.
    """
    norm_corpus = [l2_normalize_vector(v, expected_dim=expected_dim) for v in corpus_vectors]
    norm_queries = [l2_normalize_vector(q, expected_dim=expected_dim) for q in query_vectors]
    half_corpus = [_quantize_float16_roundtrip(v) for v in norm_corpus]

    max_cos_ip_diff = 0.0
    max_halfvec_err = 0.0
    top1_matches = 0

    for c_vec, h_vec in zip(norm_corpus, half_corpus):
        for a, b in zip(c_vec, h_vec):
            max_halfvec_err = max(max_halfvec_err, abs(a - b))

    for q_vec in norm_queries:
        cos_scores: list[float] = []
        ip_scores: list[float] = []
        half_scores: list[float] = []

        for c_vec, h_vec in zip(norm_corpus, half_corpus):
            dot = sum(x * y for x, y in zip(q_vec, c_vec))
            q_norm = math.sqrt(sum(x * x for x in q_vec))
            c_norm = math.sqrt(sum(y * y for y in c_vec))
            cos_sim = dot / (q_norm * c_norm)
            cos_scores.append(cos_sim)
            ip_scores.append(dot)
            max_cos_ip_diff = max(max_cos_ip_diff, abs(cos_sim - dot))

            h_dot = sum(x * y for x, y in zip(q_vec, h_vec))
            half_scores.append(h_dot)

        if cos_scores:
            best_cos = max(range(len(cos_scores)), key=lambda i: cos_scores[i])
            best_half = max(range(len(half_scores)), key=lambda i: half_scores[i])
            if best_cos == best_half:
                top1_matches += 1

    agreement = (top1_matches / len(norm_queries)) if norm_queries else 1.0
    return {
        "default_operator": "<=>",
        "evaluated_operators": ["<=>", "<#>"],
        "dimensions": expected_dim,
        "corpus_size": len(norm_corpus),
        "query_count": len(norm_queries),
        "cosine_vs_inner_product_max_diff": max_cos_ip_diff,
        "halfvec_float16_max_abs_error": max_halfvec_err,
        "top1_agreement_rate": agreement,
    }


def _normalize_gemini_model_name(provider: str, model: str) -> str:
    clean_provider = (provider or "").strip().lower()
    clean_model = (model or "").strip()
    if clean_provider == "gemini" and clean_model and clean_model != "unknown":
        if not clean_model.startswith("models/"):
            return f"models/{clean_model}"
    return clean_model


class EmbeddingProfile(BaseModel):
    """
    Standard profile defining the embedding contract across indexing and retrieval.
    """

    provider: str
    model: str
    dimensions: int
    normalization: bool = True
    distance_metric: str = "cosine"
    profile_version: str = "v1"
    document_task_type: str | None = None
    query_task_type: str | None = None
    active_task_type: str | None = None
    contextual_headers: bool = False
    chunker_version: str = "v1"

    @model_validator(mode="after")
    def _normalize_model_prefix(self) -> EmbeddingProfile:
        """Normalize Gemini model names so 'gemini-embedding-001' and 'models/gemini-embedding-001' match."""
        self.model = _normalize_gemini_model_name(self.provider, self.model)
        return self

    @classmethod
    def v2_gemini(
        cls,
        *,
        model: str = "models/gemini-embedding-001",
        dimensions: int = 768,
        document_task_type: str = GeminiTaskType.RETRIEVAL_DOCUMENT.value,
        query_task_type: str = GeminiTaskType.CODE_RETRIEVAL_QUERY.value,
        active_task_type: str | None = None,
        contextual_headers: bool = True,
        chunker_version: str = "v2_cast",
    ) -> EmbeddingProfile:
        """Create the canonical v2 Gemini embedding profile."""
        normalized_model = _normalize_gemini_model_name("gemini", model)
        return cls(
            provider="gemini",
            model=normalized_model,
            dimensions=dimensions,
            normalization=True,
            distance_metric="cosine",
            profile_version="v2",
            document_task_type=document_task_type,
            query_task_type=query_task_type,
            active_task_type=active_task_type or document_task_type,
            contextual_headers=contextual_headers,
            chunker_version=chunker_version,
        )

    def is_compatible_with(self, other: EmbeddingProfile) -> bool:
        """
        Check compatibility between query profile and indexed profile.

        Never mixes:
        - Different dimensions
        - Different providers or models
        - Different profile_version (e.g. v1 vs v2)
        - Incompatible task-type families
        """
        self_model = _normalize_gemini_model_name(self.provider, self.model)
        other_model = _normalize_gemini_model_name(other.provider, other.model)
        if (
            self.dimensions != other.dimensions
            or self.provider.strip().lower() != other.provider.strip().lower()
            or self_model != other_model
            or self.profile_version != other.profile_version
            or self.normalization != other.normalization
        ):
            return False

        # Verify task-type compatibility when specified on both profiles
        self_tasks = {
            t
            for t in (self.active_task_type, self.document_task_type, self.query_task_type)
            if t is not None
        }
        other_tasks = {
            t
            for t in (other.active_task_type, other.document_task_type, other.query_task_type)
            if t is not None
        }
        if self_tasks and other_tasks:
            if self_tasks.issubset(_COMPATIBLE_RETRIEVAL_TASK_TYPES) and other_tasks.issubset(
                _COMPATIBLE_RETRIEVAL_TASK_TYPES
            ):
                return True
            if not self_tasks.intersection(other_tasks):
                return False

        return True


class EmbeddingProvider(ABC):
    """
    Abstract base class for all embedding provider implementations.

    Implementations manage transport communication with the provider API / model.
    Batch splitting, concurrency limits, and dimension validation are handled
    by the high-level `EmbeddingService`.
    """

    @property
    def profile(self) -> EmbeddingProfile:
        """Declared embedding profile for this provider."""
        return EmbeddingProfile(
            provider=self.provider_name,
            model=getattr(self, "model_name", "unknown"),
            dimensions=self.embedding_dimensions,
            normalization=True,
            distance_metric="cosine",
            profile_version="v1",
        )

    async def embed(self, text: str) -> list[float]:
        """
        Embed a single text string.

        Default implementation delegates to `embed_batch([text])` to centralize
        batching and retry handling. Providers may override with specialized calls.
        """
        results = await self.embed_batch([text])
        if not results:
            raise EmbeddingError("Provider returned empty result for single text.", retryable=False)
        return results[0]

    @abstractmethod
    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """
        Embed multiple texts in a single batch API call.
        """
        ...

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """
        Embed repository document/code chunks using the provider's document task configuration.
        Defaults to `embed_batch(texts)` for generic providers.
        """
        return await self.embed_batch(texts)

    async def embed_query(self, text: str) -> list[float]:
        """
        Embed a search query using the provider's code-retrieval query configuration.
        Defaults to `embed(text)` for generic providers.
        """
        return await self.embed(text)

    @property
    @abstractmethod
    def embedding_dimensions(self) -> int:
        """Declared number of dimensions in each output vector (from config)."""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Canonical human-readable provider identifier (e.g. 'gemini')."""
        ...

    @property
    def model_name(self) -> str:
        """Name of the model used by the provider."""
        return "unknown"

    async def aclose(self) -> None:
        """Optional hook to release network connections and resources."""

    async def __aenter__(self: Self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        await self.aclose()
