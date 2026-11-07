"""
Redis-based asynchronous retrieval-result cache (R03, R04).
Owner: Meet — W1-12

Provides:
- Asynchronous get/set of final retrieval results
- Safe, cursor-based repository invalidation
- Stampede lock for concurrent cache misses
- Fault tolerance: cache failures never cause retrieval failures
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID, uuid4

from app.core.config import get_settings
from app.core.redis import get_async_redis_client
from redis.asyncio import Redis as AsyncRedis

from .base import CodeChunk
from .cache_serialization import deserialize_chunks, serialize_chunks

logger = logging.getLogger(__name__)

__all__ = ["RetrievalResultCache"]


class RetrievalResultCache:
    """
    Asynchronous Redis cache for hybrid retrieval results.
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
            enabled if enabled is not None else settings.retrieval_cache_enabled
        )
        self._default_ttl = (
            default_ttl_seconds
            if default_ttl_seconds is not None
            else settings.retrieval_cache_ttl_seconds
        )
        self._max_payload_bytes = (
            max_payload_bytes
            if max_payload_bytes is not None
            else settings.retrieval_cache_max_payload_bytes
        )

    def _get_client(self) -> AsyncRedis | Any:
        if self._redis_client is not None:
            return self._redis_client
        return get_async_redis_client()

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def get(self, key: str) -> list[CodeChunk] | None:
        """
        Fetch and deserialize cached retrieval results.

        Returns:
            List of CodeChunk on cache hit, or None on miss, failure, or disabled cache.
        """
        if not self._enabled:
            return None

        try:
            client = self._get_client()
            raw_data = await client.get(key)
            if not raw_data:
                return None
            return deserialize_chunks(raw_data)
        except Exception as exc:  # noqa: BLE001
            logger.warning("retrieval_cache_get_error", extra={"key": key, "error": str(exc)})
            return None

    async def set(
        self,
        key: str,
        chunks: list[CodeChunk],
        ttl_seconds: int | None = None,
    ) -> bool:
        """
        Serialize and cache retrieval results with TTL.

        Returns:
            True if cached successfully, False otherwise.
        """
        if not self._enabled or not chunks:
            return False

        try:
            serialized = serialize_chunks(chunks)
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

    async def invalidate_repository(self, repository_id: UUID | str) -> int:
        """
        Safely invalidate all cached retrieval keys for a specific repository
        using cursor-based SCAN (scan_iter) to avoid blocking production Redis.

        Returns:
            Count of deleted keys.
        """
        repo_str = str(repository_id)
        match_pattern = f"retrieval:v2:*:{repo_str}:*"
        deleted_count = 0

        try:
            client = self._get_client()
            keys_to_delete: list[str] = []

            # Use scan_iter for non-blocking cursor iteration
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
        """
        Acquire a short-lived lock to prevent cache stampedes on concurrent misses.

        Returns:
            Lock token string on acquisition, or None if already locked or error.
        """
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
        """
        Release a stampede lock only if the token matches ownership.
        """
        if not self._enabled or not lock_token:
            return False

        lock_key = f"lock:{key}"
        try:
            client = self._get_client()
            current_val = await client.get(lock_key)
            if current_val == lock_token:
                await client.delete(lock_key)
                return True
            return False
        except Exception as exc:  # noqa: BLE001
            logger.debug("stampede_lock_release_error", extra={"key": lock_key, "error": str(exc)})
            return False
