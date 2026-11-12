"""
Embedding Service — Batching, Dimension Validation, L2 Normalization, Concurrency Control, and Query Caching.

Coordinates embedding operations across the application:
- Enforces strict vector dimensionality and finite-value contracts before ingestion or search.
- Supports asymmetric document (`embed_documents`) vs code-retrieval query (`embed_query`) task types.
- Normalizes vectors to unit L2 length on write (`l2_normalize_vector`) while rejecting zero-norm vectors.
- Splits large item collections into provider-optimal sub-batches (default: 100).
- Governs concurrent sub-batch execution via asyncio.Semaphore to prevent socket exhaustion.
- Preserves 1:1 positional ordering between input text sequences and output vectors.
- Provides CachedEmbeddingService with profile-versioned and task-type-isolated L1/L2 caching.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
import hashlib
import json
import logging
import math
import time
from collections.abc import Sequence
from typing import Any, Self

from .client import (
    DimensionMismatchError,
    EmbeddingError,
    EmbeddingProfile,
    EmbeddingProvider,
    GeminiTaskType,
    InvalidVectorError,
    l2_normalize_vector,
)

logger = logging.getLogger(__name__)

# Maximum number of texts sent to the provider in a single API call.
# Capped at 100 to balance network throughput and blast radius of individual retries.
_BATCH_SIZE: int = 100
_DEFAULT_MAX_CONCURRENCY: int = 10


class EmbeddingService:
    """
    High-level embedding orchestrator used across indexing, retrieval, and Q&A.

    Wraps an ``EmbeddingProvider`` with:
    - **Dimension & Finite Validation**: Rejects malformed vectors immediately (non-retryable).
    - **Task-Aware Document/Query Embedding**: Dispatches `RETRIEVAL_DOCUMENT` for indexing
      and `CODE_RETRIEVAL_QUERY` for search queries, with consistent L2 normalization.
    - **Batching & Concurrency Limits**: Partitions large text sets into sub-batches
      and executes them concurrently under a Semaphore ceiling.
    """

    def __init__(
        self,
        provider: EmbeddingProvider,
        batch_size: int = _BATCH_SIZE,
        max_concurrency: int = _DEFAULT_MAX_CONCURRENCY,
        rate_limiter: Any = None,
    ) -> None:
        if batch_size <= 0:
            raise ValueError(f"batch_size must be positive, got {batch_size}")
        if max_concurrency <= 0:
            raise ValueError(f"max_concurrency must be positive, got {max_concurrency}")

        self._provider = provider
        self._batch_size = batch_size
        self._max_concurrency = max_concurrency
        self._rate_limiter = rate_limiter

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def provider(self) -> EmbeddingProvider:
        """Underlying embedding provider."""
        return self._provider

    @property
    def dimensions(self) -> int:
        """Expected output vector length (from provider)."""
        return self._provider.embedding_dimensions

    @property
    def batch_size(self) -> int:
        """Configured sub-batch partition size."""
        return self._batch_size

    @property
    def max_concurrency(self) -> int:
        """Maximum concurrent API requests permitted."""
        return self._max_concurrency

    @property
    def rate_limiter(self) -> Any:
        """Underlying distributed or local rate limiter, if configured."""
        return self._rate_limiter

    @property
    def model_name(self) -> str:
        """Configured model name from underlying provider."""
        return getattr(self._provider, "model_name", "models/gemini-embedding-001")

    @property
    def profile(self) -> EmbeddingProfile:
        """Declared embedding profile for this service."""
        return self._provider.profile

    @property
    def profile_version(self) -> str:
        """Active profile version."""
        return self.profile.profile_version

    def validate_query_profile(self, target_profile: EmbeddingProfile | None) -> None:
        """
        Validate that target indexed profile matches this embedding service's profile.

        Raises:
            DimensionMismatchError: if dimensions differ.
            EmbeddingError: if provider, model, profile_version, or task types are incompatible.
        """
        if target_profile is None:
            return
        if not self.profile.is_compatible_with(target_profile):
            if self.profile.dimensions != target_profile.dimensions:
                raise DimensionMismatchError(
                    expected=target_profile.dimensions,
                    actual=self.profile.dimensions,
                    provider=self.profile.provider,
                )
            raise EmbeddingError(
                f"Embedding profile mismatch: current service is "
                f"{self.profile.provider}/{self.profile.model} (version={self.profile.profile_version}) "
                f"but target index was created with "
                f"{target_profile.provider}/{target_profile.model} (version={target_profile.profile_version})",
                retryable=False,
                provider=self.profile.provider,
            )

    def normalize_vector(self, vector: Sequence[float]) -> list[float]:
        """Validate and L2-normalize a single vector according to this service's dimension contract."""
        return l2_normalize_vector(
            vector,
            expected_dim=self.dimensions,
            provider=self._provider.provider_name,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def embed(self, text: str, *, normalize: bool = False) -> list[float]:
        """
        Embed a single text string with strict dimension validation.
        """
        if text is None:
            raise ValueError("text to embed cannot be None.")

        if self._rate_limiter is not None and hasattr(self._rate_limiter, "acquire"):
            await self._rate_limiter.acquire(getattr(self._provider, "provider_name", "gemini"))

        start_time = time.perf_counter()
        vector = await self._provider.embed(text)
        self._validate_dimensions(vector)
        if normalize:
            vector = self.normalize_vector(vector)

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        logger.debug(
            "embedding_produced",
            extra={
                "dims": len(vector),
                "provider": self._provider.provider_name,
                "duration_ms": round(duration_ms, 2),
            },
        )
        return vector

    async def embed_query(self, text: str, *, normalize: bool = True) -> list[float]:
        """
        Embed a code search query using `CODE_RETRIEVAL_QUERY` task type and L2 normalization.
        """
        if text is None:
            raise ValueError("text to embed cannot be None.")

        if self._rate_limiter is not None and hasattr(self._rate_limiter, "acquire"):
            await self._rate_limiter.acquire(getattr(self._provider, "provider_name", "gemini"))

        start_time = time.perf_counter()
        if hasattr(self._provider, "embed_query") and callable(self._provider.embed_query):
            vector = await self._provider.embed_query(text)
        else:
            vector = await self._provider.embed(text)

        self._validate_dimensions(vector)
        if normalize:
            vector = self.normalize_vector(vector)

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        logger.debug(
            "query_embedding_produced",
            extra={
                "dims": len(vector),
                "provider": self._provider.provider_name,
                "profile_version": self.profile_version,
                "duration_ms": round(duration_ms, 2),
            },
        )
        return vector

    async def embed_documents(
        self,
        texts: Sequence[str],
        *,
        normalize: bool = True,
    ) -> list[list[float]]:
        """
        Embed repository code chunks using `RETRIEVAL_DOCUMENT` task type, bounded concurrency,
        and strict L2 normalization on write.
        """
        if not texts:
            return []

        text_list = list(texts)
        total_count = len(text_list)
        start_time = time.perf_counter()

        sub_batches: list[list[str]] = [
            text_list[i : i + self._batch_size]
            for i in range(0, total_count, self._batch_size)
        ]

        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def _run_doc_sub_batch(batch: list[str]) -> list[list[float]]:
            async with semaphore:
                if self._rate_limiter is not None and hasattr(self._rate_limiter, "acquire"):
                    await self._rate_limiter.acquire(getattr(self._provider, "provider_name", "gemini"))
                if hasattr(self._provider, "embed_documents") and callable(self._provider.embed_documents):
                    return await self._provider.embed_documents(batch)
                return await self._provider.embed_batch(batch)

        batch_results: list[list[list[float]]] = await asyncio.gather(
            *[_run_doc_sub_batch(batch) for batch in sub_batches]
        )

        all_vectors: list[list[float]] = []
        for idx, (batch, batch_vectors) in enumerate(zip(sub_batches, batch_results)):
            if len(batch_vectors) != len(batch):
                raise EmbeddingError(
                    f"Provider returned {len(batch_vectors)} vectors for sub-batch {idx} of {len(batch)} inputs."
                )
            for vector in batch_vectors:
                self._validate_dimensions(vector)
                if normalize:
                    vector = self.normalize_vector(vector)
                all_vectors.append(vector)

        if len(all_vectors) != total_count:
            raise EmbeddingError(
                f"EmbeddingService total vector count mismatch: expected {total_count}, got {len(all_vectors)}."
            )

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        logger.info(
            "document_batch_embedding_complete",
            extra={
                "total_texts": total_count,
                "num_batches": len(sub_batches),
                "provider": self._provider.provider_name,
                "profile_version": self.profile_version,
                "duration_ms": round(duration_ms, 2),
            },
        )
        return all_vectors

    async def embed_batch(self, texts: Sequence[str], *, normalize: bool = False) -> list[list[float]]:
        """
        Embed a sequence of texts with automatic batching and bounded concurrency.
        """
        if not texts:
            return []

        text_list = list(texts)
        total_count = len(text_list)
        start_time = time.perf_counter()

        sub_batches: list[list[str]] = [
            text_list[i : i + self._batch_size]
            for i in range(0, total_count, self._batch_size)
        ]

        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def _run_sub_batch(batch: list[str]) -> list[list[float]]:
            async with semaphore:
                if self._rate_limiter is not None and hasattr(self._rate_limiter, "acquire"):
                    await self._rate_limiter.acquire(getattr(self._provider, "provider_name", "gemini"))
                return await self._provider.embed_batch(batch)

        batch_results: list[list[list[float]]] = await asyncio.gather(
            *[_run_sub_batch(batch) for batch in sub_batches]
        )

        all_vectors: list[list[float]] = []
        for idx, (batch, batch_vectors) in enumerate(zip(sub_batches, batch_results)):
            if len(batch_vectors) != len(batch):
                raise EmbeddingError(
                    f"Provider returned {len(batch_vectors)} vectors for sub-batch {idx} of {len(batch)} inputs."
                )
            for vector in batch_vectors:
                self._validate_dimensions(vector)
                if normalize:
                    vector = self.normalize_vector(vector)
                all_vectors.append(vector)

        if len(all_vectors) != total_count:
            raise EmbeddingError(
                f"EmbeddingService total vector count mismatch: expected {total_count}, got {len(all_vectors)}."
            )

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        logger.info(
            "batch_embedding_complete",
            extra={
                "total_texts": total_count,
                "num_batches": len(sub_batches),
                "provider": self._provider.provider_name,
                "duration_ms": round(duration_ms, 2),
            },
        )
        return all_vectors

    async def aclose(self) -> None:
        """Release underlying provider and rate limiter resources."""
        if hasattr(self._provider, "aclose"):
            await self._provider.aclose()
        if self._rate_limiter is not None and hasattr(self._rate_limiter, "aclose"):
            await self._rate_limiter.aclose()

    async def __aenter__(self: Self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _validate_dimensions(self, vector: list[float]) -> None:
        """
        Assert the returned vector matches the provider's declared dimension and contains finite numbers.

        Raises:
            DimensionMismatchError: (retryable=False) on vector length mismatch.
            InvalidVectorError: on non-finite numeric values (NaN / Inf).
        """
        expected = self._provider.embedding_dimensions
        actual = len(vector)
        if actual != expected:
            raise DimensionMismatchError(
                expected=expected,
                actual=actual,
                provider=self._provider.provider_name,
            )
        for v in vector:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise InvalidVectorError(
                    "Vector contains non-finite or invalid numeric values (NaN/Inf).",
                    provider=self._provider.provider_name,
                )


class CachedEmbeddingService(EmbeddingService):
    """EmbeddingService subclass with L1 in-memory LRU cache and optional Redis L2 cache (OPT-03)."""

    def __init__(
        self,
        provider: EmbeddingProvider,
        batch_size: int = _BATCH_SIZE,
        max_concurrency: int = _DEFAULT_MAX_CONCURRENCY,
        redis_client: Any = None,
        ttl_seconds: int = 3600,
        max_memory_entries: int = 512,
    ) -> None:
        super().__init__(provider=provider, batch_size=batch_size, max_concurrency=max_concurrency)
        self._redis = redis_client
        self._ttl_seconds = ttl_seconds
        self._max_memory_entries = max(1, max_memory_entries)
        self._memory_cache: OrderedDict[str, list[float]] = OrderedDict()

    def _cache_key(self, text: str, *, task_type: str | None = None, normalize: bool = False) -> str:
        digest = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
        prof_ver = self.profile_version or "v1"
        if task_type is None and not normalize and prof_ver == "v1":
            return f"emb:v1:{self.model_name}:{self.dimensions}:{digest}"
        task_segment = task_type or "default"
        norm_segment = "norm" if normalize else "raw"
        return f"emb:{prof_ver}:{self.model_name}:{self.dimensions}:{task_segment}:{norm_segment}:{digest}"

    async def embed(self, text: str, *, normalize: bool = False) -> list[float]:
        if text is None:
            raise ValueError("text to embed cannot be None.")

        key = self._cache_key(text, task_type=None, normalize=normalize)

        if key in self._memory_cache:
            self._memory_cache.move_to_end(key)
            return list(self._memory_cache[key])

        if self._redis is not None:
            try:
                raw = self._redis.get(key)
                if asyncio.iscoroutine(raw):
                    raw = await raw
                if raw:
                    vec = [float(x) for x in json.loads(raw)]
                    self._validate_dimensions(vec)
                    self._store_memory(key, vec)
                    return vec
            except Exception as exc:
                logger.debug("embedding_cache_read_failed", extra={"error": str(exc)})

        vec = await super().embed(text, normalize=normalize)
        self._store_memory(key, vec)

        if self._redis is not None:
            try:
                res = self._redis.setex(key, self._ttl_seconds, json.dumps(vec))
                if asyncio.iscoroutine(res):
                    await res
            except Exception as exc:
                logger.debug("embedding_cache_write_failed", extra={"error": str(exc)})

        return vec

    async def embed_documents(
        self,
        texts: Sequence[str],
        *,
        normalize: bool = True,
    ) -> list[list[float]]:
        """
        Embed documents with L1/L2 cache lookup and in-batch deduplication so identical
        chunks reuse cached `RETRIEVAL_DOCUMENT` embeddings without duplicate API calls.
        """
        if not texts:
            return []

        doc_task = (
            getattr(self._provider, "document_task_type", None)
            or self.profile.document_task_type
            or GeminiTaskType.RETRIEVAL_DOCUMENT.value
        )
        text_list = list(texts)
        keys = [
            self._cache_key(t, task_type=str(doc_task), normalize=normalize)
            for t in text_list
        ]

        results_by_key: dict[str, list[float]] = {}
        missing_texts_by_key: OrderedDict[str, str] = OrderedDict()

        for text_item, key in zip(text_list, keys):
            if key in results_by_key:
                continue
            if key in self._memory_cache:
                self._memory_cache.move_to_end(key)
                results_by_key[key] = list(self._memory_cache[key])
                continue
            if self._redis is not None:
                try:
                    raw = self._redis.get(key)
                    if asyncio.iscoroutine(raw):
                        raw = await raw
                    if raw:
                        vec = [float(x) for x in json.loads(raw)]
                        self._validate_dimensions(vec)
                        self._store_memory(key, vec)
                        results_by_key[key] = vec
                        continue
                except Exception as exc:
                    logger.debug("embedding_doc_cache_read_failed", extra={"error": str(exc)})
            missing_texts_by_key[key] = text_item

        if missing_texts_by_key:
            unique_missing_keys = list(missing_texts_by_key.keys())
            unique_missing_texts = list(missing_texts_by_key.values())
            computed_vecs = await super().embed_documents(unique_missing_texts, normalize=normalize)
            for m_key, vec in zip(unique_missing_keys, computed_vecs):
                results_by_key[m_key] = vec
                self._store_memory(m_key, vec)
                if self._redis is not None:
                    try:
                        res = self._redis.setex(m_key, self._ttl_seconds, json.dumps(vec))
                        if asyncio.iscoroutine(res):
                            await res
                    except Exception as exc:
                        logger.debug("embedding_doc_cache_write_failed", extra={"error": str(exc)})

        return [list(results_by_key[k]) for k in keys]

    async def embed_query(self, text: str, *, normalize: bool = True) -> list[float]:
        if text is None:
            raise ValueError("text to embed cannot be None.")

        query_task = (
            getattr(self._provider, "query_task_type", None)
            or self.profile.query_task_type
            or GeminiTaskType.CODE_RETRIEVAL_QUERY.value
        )
        key = self._cache_key(text, task_type=str(query_task), normalize=normalize)

        if key in self._memory_cache:
            self._memory_cache.move_to_end(key)
            return list(self._memory_cache[key])

        if self._redis is not None:
            try:
                raw = self._redis.get(key)
                if asyncio.iscoroutine(raw):
                    raw = await raw
                if raw:
                    vec = [float(x) for x in json.loads(raw)]
                    self._validate_dimensions(vec)
                    self._store_memory(key, vec)
                    return vec
            except Exception as exc:
                logger.debug("embedding_cache_read_failed", extra={"error": str(exc)})

        vec = await super().embed_query(text, normalize=normalize)
        self._store_memory(key, vec)

        if self._redis is not None:
            try:
                res = self._redis.setex(key, self._ttl_seconds, json.dumps(vec))
                if asyncio.iscoroutine(res):
                    await res
            except Exception as exc:
                logger.debug("embedding_cache_write_failed", extra={"error": str(exc)})

        return vec

    def _store_memory(self, key: str, vector: list[float]) -> None:
        self._memory_cache[key] = list(vector)
        self._memory_cache.move_to_end(key)
        while len(self._memory_cache) > self._max_memory_entries:
            self._memory_cache.popitem(last=False)
