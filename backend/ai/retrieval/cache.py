"""
Distributed Two-Level Retrieval Query Cache & Invalidation (Feature F37 / Issue #218).

Provides:
- RetrievalCache: Common abstract protocol for retrieval caching.
- InMemoryRetrievalCache: Local in-process LRU cache (L1).
- RetrievalResultCache / RedisRetrievalCache: Distributed Redis cache (L2).
- TwoLevelRetrievalCache: Unified coordinator supporting L1 local-first lookup,
  L2 Redis sharing, stampede protection, and repository-scoped version invalidation.
- Full fault tolerance: Redis failures, network delays, or serialization issues
  never break retrieval execution.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import logging
import time
from typing import Any
from uuid import UUID, uuid4

from app.core.config import get_settings
from app.core.redis import get_async_redis_client
from redis.asyncio import Redis as AsyncRedis

from .base import CodeChunk
from .cache_keys import (
    bump_repository_index_version_async,
    set_repository_index_version_async,
)
from .cache_serialization import (
    deserialize_chunks,
    deserialize_retrieval_payload,
    serialize_chunks,
    serialize_retrieval_payload,
)

logger = logging.getLogger(__name__)

__all__ = [
    "InMemoryRetrievalCache",
    "RedisRetrievalCache",
    "RetrievalCache",
    "RetrievalResultCache",
    "TwoLevelRetrievalCache",
    "get_retrieval_cache",
]


class RetrievalCache(ABC):
    """Abstract interface for retrieval result caching."""

    @abstractmethod
    async def get(self, key: str) -> Any | None:
        """Retrieve cached query result."""

    @abstractmethod
    async def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None = None,
    ) -> bool:
        """Store query result in cache with optional TTL."""

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """Delete an individual cache key."""

    @abstractmethod
    async def invalidate_repository(self, repository_id: UUID | str) -> int:
        """Invalidate all cached results for a repository."""


class InMemoryRetrievalCache(RetrievalCache):
    """
    Local in-memory LRU query cache (L1).
    Provides sub-millisecond lookups within an individual application process.
    """

    def __init__(
        self,
        maxsize: int = 1000,
        default_ttl_seconds: float = 300.0,
        lru: Any | None = None,
    ) -> None:
        if lru is not None:
            self._lru = lru
        else:
            from ai.services.retrieval_optimizer import LRUQueryCache
            self._lru = LRUQueryCache(maxsize=maxsize, ttl_seconds=default_ttl_seconds)

    async def get(self, key: str) -> Any | None:
        return self._lru.get(key)

    async def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None = None,
    ) -> bool:
        self._lru.set(key, value)
        return True

    async def delete(self, key: str) -> bool:
        if hasattr(self._lru, "delete"):
            return self._lru.delete(key)
        h = self._lru._hash_key(key)
        if h in self._lru._cache:
            del self._lru._cache[h]
            return True
        return False

    async def invalidate_repository(self, repository_id: UUID | str) -> int:
        if hasattr(self._lru, "invalidate_repository"):
            return self._lru.invalidate_repository(repository_id)
        # Fallback: scan keys in cache
        repo_str = str(repository_id)
        to_del = [
            h for h, (_, val) in list(self._lru._cache.items())
            if (isinstance(val, list) and val and getattr(val[0], "repository_id", None) == repo_str)
        ]
        for h in to_del:
            self._lru._cache.pop(h, None)
        return len(to_del)

    def get_sync(self, key: str) -> Any | None:
        return self._lru.get(key)

    def set_sync(self, key: str, value: Any) -> bool:
        self._lru.set(key, value)
        return True

    def clear(self) -> None:
        self._lru.clear()

    @property
    def stats(self) -> dict[str, int]:
        return self._lru.stats


_RELEASE_STAMPEDE_LOCK_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


class RetrievalResultCache(RetrievalCache):
    """
    Asynchronous Redis distributed query cache (L2).
    Shares cached retrieval results across multiple worker instances.
    """

    def __init__(
        self,
        redis_client: AsyncRedis | Any = None,
        enabled: bool | None = None,
        default_ttl_seconds: int | None = None,
        max_payload_bytes: int | None = None,
    ) -> None:
        self._redis_client = redis_client
        settings = get_settings()
        self._enabled = (
            enabled if enabled is not None else getattr(settings, "retrieval_cache_enabled", True)
        )
        self._default_ttl = (
            default_ttl_seconds
            if default_ttl_seconds is not None
            else getattr(settings, "retrieval_cache_ttl_seconds", 300)
        )
        self._max_payload_bytes = (
            max_payload_bytes
            if max_payload_bytes is not None
            else getattr(settings, "retrieval_cache_max_payload_bytes", 500_000)
        )

    def _get_client(self) -> AsyncRedis | Any:
        if self._redis_client is not None:
            return self._redis_client
        return get_async_redis_client()

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def get(self, key: str) -> Any | None:
        """
        Fetch and deserialize cached retrieval results from Redis.

        Returns:
            Deserialized payload or list of CodeChunk on hit, None on miss or error.
        """
        if not self._enabled:
            return None

        try:
            client = self._get_client()
            raw_data = await client.get(key)
            if not raw_data:
                return None
            res = deserialize_retrieval_payload(raw_data)
            if res is not None:
                return res
            return deserialize_chunks(raw_data)
        except Exception as exc:  # noqa: BLE001
            logger.warning("retrieval_cache_get_error", extra={"key": key, "error": str(exc)})
            return None

    async def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None = None,
    ) -> bool:
        """
        Serialize and cache retrieval results in Redis with TTL.
        """
        if not self._enabled or value is None:
            return False

        try:
            if isinstance(value, list) and value and isinstance(value[0], CodeChunk):
                serialized = serialize_chunks(value)
            else:
                serialized = serialize_retrieval_payload(value)

            if len(serialized.encode("utf-8")) > self._max_payload_bytes:
                logger.info(
                    "retrieval_cache_payload_too_large_skipped",
                    extra={"key": key, "bytes": len(serialized.encode("utf-8")), "limit": self._max_payload_bytes},
                )
                return False

            ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
            client = self._get_client()
            await client.set(key, serialized, ex=ttl)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("retrieval_cache_set_error", extra={"key": key, "error": str(exc)})
            return False

    async def delete(self, key: str) -> bool:
        """Delete key from Redis."""
        if not self._enabled:
            return False
        try:
            client = self._get_client()
            res = await client.delete(key)
            return bool(res)
        except Exception as exc:  # noqa: BLE001
            logger.warning("retrieval_cache_delete_error", extra={"key": key, "error": str(exc)})
            return False

    async def invalidate_repository(self, repository_id: UUID | str) -> int:
        """
        Safely invalidate all cached retrieval keys for a specific repository
        using cursor-based SCAN (scan_iter) to avoid blocking production Redis.
        """
        repo_str = str(repository_id)
        match_pattern = f"retrieval:v2:*:{repo_str}:*"
        deleted_count = 0

        try:
            client = self._get_client()
            keys_to_delete: list[str] = []

            async for k in client.scan_iter(match=match_pattern, count=100):
                keys_to_delete.append(k)
                if len(keys_to_delete) >= 100:
                    del_res = await client.delete(*keys_to_delete)
                    deleted_count += int(del_res or 0)
                    keys_to_delete = []

            if keys_to_delete:
                del_res = await client.delete(*keys_to_delete)
                deleted_count += int(del_res or 0)

            logger.info(
                "retrieval_cache_repository_invalidated",
                extra={"repo_id": repo_str, "keys_deleted": deleted_count},
            )
            return deleted_count
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "retrieval_cache_invalidation_error",
                extra={"repo_id": repo_str, "error": str(exc)},
            )
            return 0

    async def acquire_stampede_lock(self, key: str, ttl_seconds: int = 5) -> str | None:
        """Acquire a short-lived NX lock to prevent stampedes on concurrent misses."""
        if not self._enabled:
            return None

        lock_token = str(uuid4())
        lock_key = f"lock:{key}"
        try:
            client = self._get_client()
            acquired = await client.set(lock_key, lock_token, nx=True, ex=ttl_seconds)
            if acquired:
                return lock_token
            return None
        except Exception as exc:  # noqa: BLE001
            logger.debug("stampede_lock_acquire_error", extra={"key": lock_key, "error": str(exc)})
            return None

    async def release_stampede_lock(self, key: str, lock_token: str) -> bool:
        """Atomically release a stampede lock only if the token matches ownership."""
        if not self._enabled or not lock_token:
            return False

        lock_key = f"lock:{key}"
        try:
            client = self._get_client()
            if hasattr(client, "eval"):
                try:
                    res = await client.eval(_RELEASE_STAMPEDE_LOCK_LUA, 1, lock_key, lock_token)
                    return bool(int(res or 0) == 1)
                except Exception:
                    pass
            current_val = await client.get(lock_key)
            if isinstance(current_val, bytes):
                current_val = current_val.decode("utf-8", errors="replace")
            if current_val == lock_token:
                await client.delete(lock_key)
                return True
            return False
        except Exception as exc:  # noqa: BLE001
            logger.debug("stampede_lock_release_error", extra={"key": lock_key, "error": str(exc)})
            return False


# Backward-compatible alias
RedisRetrievalCache = RetrievalResultCache


class TwoLevelRetrievalCache(RetrievalCache):
    """
    Two-Level Retrieval Cache Coordinator (L1 Local LRU + L2 Distributed Redis).

    Lookup flow:
    1. Check L1 in-memory LRU (< 0.5ms). On hit -> return.
    2. Check L2 Redis (2-5ms). On hit -> populate L1, return.
    3. On miss -> return None. Caller executes retrieval, then calls set().
    4. set() writes both L1 and L2.
    5. Invalidation invalidates L1, advances active index version, and purges L2.
    """

    def __init__(
        self,
        l1_cache: InMemoryRetrievalCache | None = None,
        l2_cache: RedisRetrievalCache | RetrievalResultCache | None = None,
        *,
        enabled: bool = True,
    ) -> None:
        self.l1: InMemoryRetrievalCache = l1_cache or InMemoryRetrievalCache()
        self.l2: RedisRetrievalCache | RetrievalResultCache | None = l2_cache
        self._enabled = enabled

        self._local_hits = 0
        self._redis_hits = 0
        self._misses = 0
        self._errors = 0
        self._invalidations = 0

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _get_client(self) -> AsyncRedis | Any:
        if self.l2 is not None and hasattr(self.l2, "_get_client"):
            return self.l2._get_client()
        return None

    async def get(self, key: str) -> Any | None:
        """Execute two-level cache lookup (L1 local-first, L2 Redis fallback)."""
        if not self._enabled:
            return None

        # 1. Local L1 Lookup (sub-millisecond)
        try:
            l1_val = await self.l1.get(key)
            if l1_val is not None:
                self._local_hits += 1
                return l1_val
        except Exception as exc:
            self._errors += 1
            logger.debug("two_level_cache_l1_get_error", extra={"key": key, "error": str(exc)})

        # 2. Distributed L2 Redis Lookup
        if self.l2 is not None and self.l2.enabled:
            try:
                l2_val = await self.l2.get(key)
                if l2_val is not None:
                    self._redis_hits += 1
                    # Populate L1 for future fast hits
                    await self.l1.set(key, l2_val)
                    return l2_val
            except Exception as exc:
                self._errors += 1
                logger.warning("two_level_cache_l2_get_error", extra={"key": key, "error": str(exc)})

        self._misses += 1
        return None

    async def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None = None,
    ) -> bool:
        """Store result across both L1 and L2 caches."""
        if not self._enabled or value is None:
            return False

        # Write to L1
        try:
            await self.l1.set(key, value, ttl_seconds)
        except Exception as exc:
            self._errors += 1
            logger.debug("two_level_cache_l1_set_error", extra={"key": key, "error": str(exc)})

        # Write to L2 Redis
        if self.l2 is not None and self.l2.enabled:
            try:
                await self.l2.set(key, value, ttl_seconds)
            except Exception as exc:
                self._errors += 1
                logger.warning("two_level_cache_l2_set_error", extra={"key": key, "error": str(exc)})

        return True

    async def delete(self, key: str) -> bool:
        """Delete from both cache layers."""
        await self.l1.delete(key)
        if self.l2 is not None and self.l2.enabled:
            try:
                await self.l2.delete(key)
            except Exception:
                pass
        return True

    async def invalidate_repository(
        self,
        repository_id: UUID | str,
        new_index_version: str | None = None,
    ) -> int:
        """
        Invalidate cached retrieval keys for a repository across both L1 and L2.
        Also bumps repository index version to isolate stale entries.
        """
        self._invalidations += 1
        repo_str = str(repository_id)

        # 1. Invalidate local L1 entries
        l1_del = await self.l1.invalidate_repository(repository_id)

        # 2. Advance repository index version
        client = getattr(self.l2, "_get_client", lambda: None)() if self.l2 else None
        if new_index_version is not None:
            await set_repository_index_version_async(repo_str, new_index_version, client)
        else:
            await bump_repository_index_version_async(repo_str, client)

        # 3. Clean up Redis L2 entries asynchronously
        l2_del = 0
        if self.l2 is not None and self.l2.enabled:
            try:
                l2_del = await self.l2.invalidate_repository(repository_id)
            except Exception as exc:
                self._errors += 1
                logger.warning("two_level_cache_l2_invalidation_error", extra={"repo_id": repo_str, "error": str(exc)})

        return l1_del + l2_del

    async def acquire_stampede_lock(self, key: str, ttl_seconds: int = 5) -> str | None:
        """Delegate stampede lock to Redis L2 if available, or generate local token."""
        if self.l2 is not None and self.l2.enabled:
            return await self.l2.acquire_stampede_lock(key, ttl_seconds)
        return str(uuid4())

    async def release_stampede_lock(self, key: str, lock_token: str) -> bool:
        """Delegate lock release to Redis L2."""
        if self.l2 is not None and self.l2.enabled:
            return await self.l2.release_stampede_lock(key, lock_token)
        return True

    @property
    def stats(self) -> dict[str, int]:
        return {
            "local_hits": self._local_hits,
            "redis_hits": self._redis_hits,
            "misses": self._misses,
            "errors": self._errors,
            "invalidations": self._invalidations,
        }

    def clear(self) -> None:
        self.l1.clear()
        self._local_hits = 0
        self._redis_hits = 0
        self._misses = 0
        self._errors = 0


_GLOBAL_RETRIEVAL_CACHE: TwoLevelRetrievalCache | None = None


def get_retrieval_cache(
    redis_client: AsyncRedis | Any = None,
    *,
    force_new: bool = False,
) -> TwoLevelRetrievalCache:
    """Return process-wide TwoLevelRetrievalCache instance."""
    global _GLOBAL_RETRIEVAL_CACHE
    if _GLOBAL_RETRIEVAL_CACHE is None or force_new:
        settings = get_settings()
        l1 = InMemoryRetrievalCache(
            maxsize=getattr(settings, "retrieval_cache_max_local_entries", 1000),
            default_ttl_seconds=getattr(settings, "retrieval_cache_ttl_seconds", 300),
        )
        redis_enabled = getattr(settings, "retrieval_redis_cache_enabled", True) and getattr(
            settings, "retrieval_cache_enabled", True
        )
        l2 = (
            RedisRetrievalCache(redis_client=redis_client, enabled=redis_enabled)
            if redis_enabled
            else None
        )
        _GLOBAL_RETRIEVAL_CACHE = TwoLevelRetrievalCache(
            l1_cache=l1,
            l2_cache=l2,
            enabled=getattr(settings, "retrieval_cache_enabled", True),
        )
    return _GLOBAL_RETRIEVAL_CACHE
