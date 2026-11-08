"""
Distributed Embedding Rate Limiter.

Coordinates embedding API request quotas across multiple worker processes
using Redis sliding-window sorted sets, with local in-memory fallback.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["DistributedEmbeddingRateLimiter", "EmbeddingRateLimitExceededError"]


class EmbeddingRateLimitExceededError(RuntimeError):
    """Raised when embedding rate limiter exceeds maximum wait time without obtaining quota."""

    pass


_ACQUIRE_LUA = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
local count = redis.call('ZCARD', KEYS[1])
if count >= tonumber(ARGV[3]) then
  local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
  local oldest_score = (oldest and #oldest >= 2) and oldest[2] or ARGV[2]
  return {0, tostring(oldest_score)}
end
redis.call('ZADD', KEYS[1], ARGV[2], ARGV[4])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[5]))
return {1, '0'}
"""


class DistributedEmbeddingRateLimiter:
    """
    Distributed sliding-window rate limiter for AI embedding providers.

    Coordinates concurrent workers to ensure total requests per minute across
    all workers do not exceed provider quotas (e.g. Gemini 120 RPM).
    """

    def __init__(
        self,
        redis: Any = None,
        max_requests_per_minute: int = 120,
        key_prefix: str = "rate_limit:embeddings",
        window_seconds: float = 60.0,
    ) -> None:
        self.redis = redis
        self.max_requests_per_minute = max_requests_per_minute
        self.key_prefix = key_prefix
        self.window_seconds = window_seconds
        # Local in-memory fallback when Redis is absent
        self._local_history: list[float] = []
        self._local_lock = asyncio.Lock()

    async def acquire(self, provider: str = "gemini", cost: int = 1, max_wait_total: float = 60.0) -> float:
        """
        Acquire permission to make an embedding API request.

        If rate limit is reached, smoothly delays execution until quota is available.
        Returns the duration waited in seconds.
        """
        waited_seconds = 0.0
        start_wait = time.monotonic()

        while True:
            allowed, retry_after = await self._check_and_record(provider)
            if allowed:
                return waited_seconds

            elapsed = time.monotonic() - start_wait
            if elapsed >= max_wait_total:
                logger.warning(
                    "embedding_rate_limiter_max_wait_exceeded",
                    extra={"provider": provider, "waited": round(elapsed, 2)},
                )
                raise EmbeddingRateLimitExceededError(
                    f"Embedding rate limit for '{provider}' exceeded maximum wait timeout of {max_wait_total}s (waited {round(elapsed, 2)}s)"
                )

            sleep_time = min(max(retry_after, 0.05), 5.0)
            waited_seconds += sleep_time
            await asyncio.sleep(sleep_time)

    async def _check_and_record(self, provider: str) -> tuple[bool, float]:
        """
        Check if request is permitted under sliding window.
        Returns (allowed, retry_after_seconds).
        """
        now = time.time()
        window_start = now - self.window_seconds
        key = f"{self.key_prefix}:{provider}"

        # If Redis is available with eval, execute atomic sliding window check-and-record
        if self.redis is not None and hasattr(self.redis, "eval"):
            try:
                member = f"{now}:{uuid.uuid4().hex[:6]}"
                ttl = int(self.window_seconds * 2)
                res = await self.redis.eval(
                    _ACQUIRE_LUA,
                    1,
                    key,
                    str(window_start),
                    str(now),
                    str(self.max_requests_per_minute),
                    member,
                    str(ttl),
                )
                status = int(res[0]) if isinstance(res, (list, tuple)) and len(res) >= 1 else 0
                if status == 1:
                    return True, 0.0

                oldest_score = float(res[1]) if isinstance(res, (list, tuple)) and len(res) >= 2 else now
                retry_after = max(0.05, (oldest_score + self.window_seconds) - now)
                return False, retry_after
            except Exception as exc:
                logger.debug("redis_rate_limiter_fallback", extra={"error": str(exc)})
                # Fall through to local fallback on Redis failure
        elif self.redis is not None and hasattr(self.redis, "zremrangebyscore") and hasattr(self.redis, "zcard"):
            try:
                await self.redis.zremrangebyscore(key, "-inf", window_start)
                current_count = await self.redis.zcard(key)

                if current_count >= self.max_requests_per_minute:
                    oldest_items = []
                    if hasattr(self.redis, "zrange"):
                        oldest_items = await self.redis.zrange(key, 0, 0, withscores=True)

                    retry_after = 1.0
                    if oldest_items:
                        oldest_score = oldest_items[0][1]
                        retry_after = max(0.05, (oldest_score + self.window_seconds) - now)
                    return False, retry_after

                member = f"{now}:{uuid.uuid4().hex[:6]}"
                if hasattr(self.redis, "zadd"):
                    await self.redis.zadd(key, {member: now})
                if hasattr(self.redis, "expire"):
                    await self.redis.expire(key, int(self.window_seconds * 2))

                return True, 0.0
            except Exception as exc:
                logger.debug("redis_rate_limiter_fallback", extra={"error": str(exc)})

        # Local in-memory sliding window fallback
        async with self._local_lock:
            self._local_history = [t for t in self._local_history if t > window_start]
            if len(self._local_history) >= self.max_requests_per_minute:
                oldest = self._local_history[0]
                retry_after = max(0.05, (oldest + self.window_seconds) - now)
                return False, retry_after

            self._local_history.append(now)
            return True, 0.0

    async def aclose(self) -> None:
        """Cleanup resources."""
        pass
