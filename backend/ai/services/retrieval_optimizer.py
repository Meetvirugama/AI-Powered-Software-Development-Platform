"""Retrieval Latency Optimizer & Agent Token Budget Manager.

Owner: Meet (Week 3 Day 6: Retrieval latency optimization (target P95 < 400ms) and agent token budget checks)
Reference: Docs/week3.md §6 & §8 Day 6.

Key Responsibilities:
1. RetrievalLatencyOptimizer:
   - Concurrent retrieval execution reducing serialization bottlenecks.
   - In-memory LRU query & symbol cache with configurable TTL.
   - Comprehensive latency percentile tracking (P50, P90, P95, P99).
   - Validates that retrieval operations stay strictly within the P95 < 400ms target.
2. AgentTokenBudgetManager:
   - Server-enforced task-level and step-level token ceiling guards.
   - Accurate token estimation and safe window truncation for prompt & tool outputs.
   - Rejects execution attempts when the allocated token budget is exhausted.
   - Emits structured audit records for token consumption telemetry.
"""

from __future__ import annotations

import collections
import hashlib
import logging
import math
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TASK_TOKEN_BUDGET: int = 30000
DEFAULT_STEP_TOKEN_BUDGET: int = 4000
TARGET_P95_LATENCY_MS: float = 400.0


class TokenBudgetExhaustedError(RuntimeError):
    """Raised when an agent task or step exceeds its allocated token budget."""


@dataclass
class TokenUsageRecord:
    """Record of tokens consumed in an individual agent operation."""

    operation: str
    tokens_consumed: int
    cumulative_tokens: int
    remaining_tokens: int
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class LatencyPercentiles:
    """Statistical summary of retrieval latency distributions."""

    sample_count: int
    p50_ms: float
    p90_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    avg_ms: float
    target_met: bool = True


class AgentTokenBudgetManager:
    """Tracks, bounds, and enforces hard token ceilings across task lifecycles."""

    def __init__(
        self,
        max_budget_tokens: int = DEFAULT_TASK_TOKEN_BUDGET,
        max_step_tokens: int = DEFAULT_STEP_TOKEN_BUDGET,
    ) -> None:
        self.max_budget_tokens = max_budget_tokens
        self.max_step_tokens = max_step_tokens
        self._tokens_used: int = 0
        self._usage_history: list[TokenUsageRecord] = []

    @property
    def tokens_used(self) -> int:
        return self._tokens_used

    @property
    def tokens_remaining(self) -> int:
        return max(0, self.max_budget_tokens - self._tokens_used)

    @property
    def is_exhausted(self) -> bool:
        return self._tokens_used >= self.max_budget_tokens

    @staticmethod
    def estimate_tokens(text: str | Any) -> int:
        """Estimate token count using standardized ~4 chars per token rule of thumb."""
        if not text:
            return 0
        if not isinstance(text, str):
            text = str(text)
        return max(1, math.ceil(len(text) / 4.0))

    def check_headroom(self, estimated_tokens: int) -> bool:
        """Check if requested tokens fit within remaining task headroom."""
        return (self._tokens_used + estimated_tokens) <= self.max_budget_tokens

    def consume(self, operation: str, tokens_consumed: int) -> TokenUsageRecord:
        """Record token consumption. Raises TokenBudgetExhaustedError if ceiling is exceeded."""
        if tokens_consumed < 0:
            raise ValueError("Consumed tokens cannot be negative.")

        projected = self._tokens_used + tokens_consumed
        if projected > self.max_budget_tokens:
            msg = (
                f"Token budget exhausted for operation '{operation}': "
                f"requested {tokens_consumed} tokens, used {self._tokens_used}/{self.max_budget_tokens}."
            )
            logger.warning("token_budget_exhausted", extra={"used": self._tokens_used, "limit": self.max_budget_tokens})
            raise TokenBudgetExhaustedError(msg)

        self._tokens_used = projected
        remaining = self.max_budget_tokens - self._tokens_used
        record = TokenUsageRecord(
            operation=operation,
            tokens_consumed=tokens_consumed,
            cumulative_tokens=self._tokens_used,
            remaining_tokens=remaining,
        )
        self._usage_history.append(record)
        return record

    def truncate_to_budget(self, text: str, max_allowed_tokens: int | None = None) -> str:
        """Safely truncate text so it does not exceed remaining budget or specified token limit."""
        token_cap = max_allowed_tokens or min(self.max_step_tokens, self.tokens_remaining)
        char_cap = token_cap * 4

        if len(text) <= char_cap:
            return text

        truncated = text[:char_cap] + "... [TRUNCATED DUE TO TOKEN BUDGET]"
        return truncated

    def get_history(self) -> list[TokenUsageRecord]:
        return list(self._usage_history)

    def reset(self) -> None:
        self._tokens_used = 0
        self._usage_history.clear()


class LRUQueryCache:
    """In-memory LRU cache with entry time-to-live expiration."""

    def __init__(self, maxsize: int = 256, ttl_seconds: float = 300.0) -> None:
        self.maxsize = maxsize
        self.ttl_seconds = ttl_seconds
        self._cache: collections.OrderedDict[str, tuple[float, Any]] = collections.OrderedDict()
        self._key_map: dict[str, str] = {}
        self._hits = 0
        self._misses = 0

    def _hash_key(self, key: Any) -> str:
        serialized = str(key)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def get(self, key: Any) -> Any | None:
        h = self._hash_key(key)
        if h not in self._cache:
            self._misses += 1
            return None

        insert_time, val = self._cache[h]
        if time.time() - insert_time > self.ttl_seconds:
            del self._cache[h]
            self._key_map.pop(h, None)
            self._misses += 1
            return None

        self._cache.move_to_end(h)
        self._hits += 1
        return val

    def set(self, key: Any, value: Any) -> None:
        h = self._hash_key(key)
        if h in self._cache:
            self._cache.move_to_end(h)
        self._cache[h] = (time.time(), value)
        self._key_map[h] = str(key)
        if len(self._cache) > self.maxsize:
            oldest_key, _ = self._cache.popitem(last=False)
            self._key_map.pop(oldest_key, None)

    def delete(self, key: Any) -> bool:
        h = self._hash_key(key)
        if h in self._cache:
            del self._cache[h]
            self._key_map.pop(h, None)
            return True
        return False

    def invalidate_repository(self, repository_id: str | Any) -> int:
        repo_str = str(repository_id)
        to_del = [
            h for h, orig_key in self._key_map.items()
            if repo_str in orig_key
        ]
        for h in to_del:
            self._cache.pop(h, None)
            self._key_map.pop(h, None)
        return len(to_del)

    @property
    def stats(self) -> dict[str, int]:
        return {"hits": self._hits, "misses": self._misses, "size": len(self._cache)}

    def clear(self) -> None:
        self._cache.clear()
        self._key_map.clear()
        self._hits = 0
        self._misses = 0


class RetrievalLatencyOptimizer:
    """Optimizes retrieval throughput and tracks latency percentiles against P95 < 400ms target."""

    def __init__(
        self,
        target_p95_ms: float = TARGET_P95_LATENCY_MS,
        cache_size: int = 256,
        max_workers: int = 4,
        *,
        distributed_cache: Any | None = None,
        redis_client: Any | None = None,
        repo_id: str | None = None,
    ) -> None:
        self.target_p95_ms = target_p95_ms
        self.cache = LRUQueryCache(maxsize=cache_size)
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self._latencies: list[float] = []
        self.repo_id = repo_id

        # Two-level cache coordinator integration
        self.two_level_cache = distributed_cache
        if self.two_level_cache is None and redis_client is not None:
            try:
                from ai.retrieval.cache import (
                    InMemoryRetrievalCache,
                    RedisRetrievalCache,
                    TwoLevelRetrievalCache,
                )
                l1 = InMemoryRetrievalCache(lru=self.cache)
                l2 = RedisRetrievalCache(redis_client=redis_client)
                self.two_level_cache = TwoLevelRetrievalCache(l1_cache=l1, l2_cache=l2)
            except Exception:
                self.two_level_cache = None

    def execute_optimized_retrieval(
        self,
        query: str,
        retrieval_fn: Callable[[str], Any],
        *,
        use_cache: bool = True,
        repo_id: str | None = None,
        index_version: str | None = None,
    ) -> tuple[Any, float]:
        """Execute a retrieval function with caching, concurrent dispatch, and latency tracking."""
        effective_repo = repo_id or self.repo_id
        if use_cache:
            cache_lookup_key = (
                f"{effective_repo}:{index_version}:{query}"
                if (effective_repo and index_version)
                else query
            )
            cached = self.cache.get(cache_lookup_key)
            if cached is None and cache_lookup_key != query:
                cached = self.cache.get(query)

            if cached is not None:
                # Local Cache hits are sub-millisecond
                self._record_latency(0.5)
                return cached, 0.5

        start = time.perf_counter()
        result = retrieval_fn(query)
        duration_ms = (time.perf_counter() - start) * 1000.0

        if use_cache:
            store_key = (
                f"{effective_repo}:{index_version}:{query}"
                if (effective_repo and index_version)
                else query
            )
            self.cache.set(store_key, result)

        self._record_latency(duration_ms)
        return result, duration_ms

    async def execute_optimized_retrieval_async(
        self,
        query: str,
        retrieval_fn: Callable[[str], Any],
        *,
        use_cache: bool = True,
        repo_id: str | None = None,
        index_version: str | None = None,
        intent: str = "conceptual",
        top_k: int = 8,
    ) -> tuple[Any, float]:
        """
        Asynchronous retrieval execution with full two-level caching (L1 local-first, L2 Redis).
        """
        import inspect
        from ai.retrieval.cache_keys import build_retrieval_cache_key, get_repository_index_version_async

        effective_repo = repo_id or self.repo_id or "default"
        resolved_version = index_version
        if resolved_version is None and self.two_level_cache and self.two_level_cache.l2:
            resolved_version = await get_repository_index_version_async(
                effective_repo, self.two_level_cache.l2._get_client()
            )
        effective_version = resolved_version or "0"

        cache_key = build_retrieval_cache_key(
            query=query,
            repository_id=effective_repo,
            index_version=effective_version,
            intent=intent,
            top_k=top_k,
        )

        if use_cache:
            # 1. Check L1 / two_level_cache
            if self.two_level_cache is not None:
                # Check L1 first
                l1_hit = await self.two_level_cache.l1.get(cache_key)
                if l1_hit is not None:
                    self.two_level_cache._local_hits += 1
                    self._record_latency(0.5)
                    return l1_hit, 0.5

                # Check L2 Redis
                if self.two_level_cache.l2 is not None and self.two_level_cache.l2.enabled:
                    l2_start = time.perf_counter()
                    l2_hit = await self.two_level_cache.l2.get(cache_key)
                    l2_duration_ms = (time.perf_counter() - l2_start) * 1000.0
                    if l2_hit is not None:
                        self.two_level_cache._redis_hits += 1
                        await self.two_level_cache.l1.set(cache_key, l2_hit)
                        self._record_latency(max(0.5, l2_duration_ms))
                        return l2_hit, l2_duration_ms

                self.two_level_cache._misses += 1
            else:
                cached = self.cache.get(cache_key)
                if cached is not None:
                    self._record_latency(0.5)
                    return cached, 0.5

        # Execute retrieval function
        start = time.perf_counter()
        if inspect.iscoroutinefunction(retrieval_fn):
            result = await retrieval_fn(query)
        else:
            result = retrieval_fn(query)
        duration_ms = (time.perf_counter() - start) * 1000.0

        if use_cache:
            if self.two_level_cache is not None:
                await self.two_level_cache.set(cache_key, result)
            else:
                self.cache.set(cache_key, result)

        self._record_latency(duration_ms)
        return result, duration_ms

    async def invalidate_repository_cache(
        self,
        repo_id: str,
        new_index_version: str | None = None,
    ) -> int:
        """Invalidate repository cached queries across local and distributed layers."""
        if self.two_level_cache is not None:
            return await self.two_level_cache.invalidate_repository(repo_id, new_index_version)
        return self.cache.invalidate_repository(repo_id)

    def execute_concurrent_search(
        self,
        query: str,
        vector_fn: Callable[[str], Any],
        lexical_fn: Callable[[str], Any],
        merge_fn: Callable[[Any, Any], Any] | None = None,
    ) -> tuple[Any, float]:
        """Execute vector and lexical retrievals concurrently to eliminate serial latency overhead."""
        start = time.perf_counter()

        future_vec = self.executor.submit(vector_fn, query)
        future_lex = self.executor.submit(lexical_fn, query)

        vec_res = future_vec.result()
        lex_res = future_lex.result()

        if merge_fn:
            merged = merge_fn(vec_res, lex_res)
        else:
            merged = {"vector": vec_res, "lexical": lex_res}

        duration_ms = (time.perf_counter() - start) * 1000.0
        self._record_latency(duration_ms)
        return merged, duration_ms

    def _record_latency(self, latency_ms: float) -> None:
        self._latencies.append(latency_ms)

    def get_latency_percentiles(self) -> LatencyPercentiles:
        """Compute statistical latency percentiles across all recorded operations."""
        if not self._latencies:
            return LatencyPercentiles(
                sample_count=0,
                p50_ms=0.0,
                p90_ms=0.0,
                p95_ms=0.0,
                p99_ms=0.0,
                min_ms=0.0,
                max_ms=0.0,
                avg_ms=0.0,
                target_met=True,
            )

        sorted_vals = sorted(self._latencies)
        n = len(sorted_vals)

        def percentile(p: float) -> float:
            idx = math.ceil(p * n) - 1
            idx = max(0, min(idx, n - 1))
            return sorted_vals[idx]

        p50 = percentile(0.50)
        p90 = percentile(0.90)
        p95 = percentile(0.95)
        p99 = percentile(0.99)
        min_v = sorted_vals[0]
        max_v = sorted_vals[-1]
        avg_v = sum(sorted_vals) / n

        return LatencyPercentiles(
            sample_count=n,
            p50_ms=round(p50, 2),
            p90_ms=round(p90, 2),
            p95_ms=round(p95, 2),
            p99_ms=round(p99, 2),
            min_ms=round(min_v, 2),
            max_ms=round(max_v, 2),
            avg_ms=round(avg_v, 2),
            target_met=(p95 <= self.target_p95_ms),
        )

    def reset_stats(self) -> None:
        self._latencies.clear()
        self.cache.clear()
