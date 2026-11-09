"""Distributed and memory-fallback rate limiting for agent tool execution.

Supports multi-tier sliding-window rate limiting per:
- task
- user
- provider
- tool
- global
Uses atomic Redis Lua scripts with an in-memory sliding window fallback
for local test environments or when Redis is temporarily unreachable.
"""

from dataclasses import dataclass
import logging
import threading
import time
from typing import Any
import uuid

logger = logging.getLogger(__name__)

# Redis Lua script for atomic sliding window rate limiting
SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
local clear_before = now - window

redis.call('ZREMRANGEBYSCORE', key, 0, clear_before)
local current_requests = redis.call('ZCARD', key)
if current_requests < limit then
    redis.call('ZADD', key, now, member)
    redis.call('EXPIRE', key, math.ceil(window) + 1)
    return {1, limit - current_requests - 1, 0}
else
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local retry_after = 0
    if #oldest > 0 then
        retry_after = math.max(0, math.ceil(tonumber(oldest[2]) + window - now))
    end
    return {0, 0, retry_after}
end
"""


@dataclass(frozen=True)
class RateLimitDecision:
    """Outcome of a rate limit check."""

    allowed: bool
    limit: int
    remaining: int
    retry_after_s: float
    scope: str
    key: str
    reason: str | None = None


class ToolRateLimiter:
    """Atomic sliding-window rate limiter for tool executions."""

    def __init__(
        self,
        redis_client: Any = None,
        fallback_to_memory: bool = True,
        prefix: str = "tool_ratelimit",
    ) -> None:
        self._redis_client = redis_client
        self._fallback_to_memory = fallback_to_memory
        self._prefix = prefix
        self._lua_sha: str | None = None
        self._lock = threading.Lock()
        # In-memory storage: {key: [(timestamp, uuid), ...]}
        self._memory_windows: dict[str, list[tuple[float, str]]] = {}

    def _get_redis(self) -> Any:
        if self._redis_client is not None:
            return self._redis_client
        try:
            from app.core.redis import get_redis

            client = get_redis()
            # Test connectivity lightly
            return client
        except Exception as exc:
            logger.debug("Failed to acquire Redis client for rate limiting: %s", exc)
            return None

    def _build_key(
        self,
        tool_name: str,
        scope: str,
        task_id: str | None = None,
        user_id: str | None = None,
        provider_id: str | None = None,
    ) -> str:
        """Construct scoped rate limit key."""
        scope_normalized = scope.lower().strip()
        if scope_normalized == "task":
            identifier = task_id or "unknown_task"
        elif scope_normalized == "user":
            identifier = user_id or "unknown_user"
        elif scope_normalized == "provider":
            identifier = provider_id or "unknown_provider"
        elif scope_normalized == "global":
            identifier = "global"
        else:
            identifier = task_id or user_id or "default"

        return f"{self._prefix}:{tool_name}:{scope_normalized}:{identifier}"

    def check(
        self,
        tool_name: str,
        rate_limit: Any,  # ToolRateLimit or compatible duck-type
        task_id: str | None = None,
        user_id: str | None = None,
        provider_id: str | None = None,
    ) -> RateLimitDecision:
        """Check whether execution is permitted under the configured rate limit."""
        if rate_limit is None:
            return RateLimitDecision(
                allowed=True,
                limit=-1,
                remaining=-1,
                retry_after_s=0.0,
                scope="none",
                key="none",
            )

        max_requests = getattr(rate_limit, "requests", getattr(rate_limit, "max_requests", 0))
        window_seconds = float(getattr(rate_limit, "window_seconds", 60.0))
        scope = getattr(rate_limit, "scope", "task")

        if max_requests <= 0 or window_seconds <= 0:
            return RateLimitDecision(
                allowed=True,
                limit=max_requests,
                remaining=max_requests,
                retry_after_s=0.0,
                scope=scope,
                key="disabled",
            )

        key = self._build_key(tool_name, scope, task_id, user_id, provider_id)
        now = time.time()
        member = f"{now:.6f}:{uuid.uuid4().hex[:8]}"

        redis_client = self._get_redis()
        if redis_client is not None:
            try:
                # Execute Lua script
                result = redis_client.eval(
                    SLIDING_WINDOW_LUA,
                    1,
                    key,
                    now,
                    window_seconds,
                    max_requests,
                    member,
                )
                allowed_int, remaining, retry_after = result
                allowed = bool(allowed_int)
                return RateLimitDecision(
                    allowed=allowed,
                    limit=max_requests,
                    remaining=int(remaining),
                    retry_after_s=float(retry_after),
                    scope=scope,
                    key=key,
                    reason=None if allowed else f"Rate limit exceeded: {max_requests} req / {window_seconds}s for {scope}",
                )
            except Exception as exc:
                logger.warning(
                    "Redis rate limit check failed (%s); attempting fallback",
                    exc,
                )
                if not self._fallback_to_memory:
                    # In production if fallback disallowed, fail open or fail closed? Fail closed for safety
                    return RateLimitDecision(
                        allowed=False,
                        limit=max_requests,
                        remaining=0,
                        retry_after_s=window_seconds,
                        scope=scope,
                        key=key,
                        reason=f"Rate limit verification backend unavailable: {exc}",
                    )

        # In-memory sliding window fallback
        with self._lock:
            entries = self._memory_windows.setdefault(key, [])
            clear_before = now - window_seconds
            # Purge expired entries
            valid_entries = [e for e in entries if e[0] > clear_before]
            current_count = len(valid_entries)

            if current_count < max_requests:
                valid_entries.append((now, member))
                self._memory_windows[key] = valid_entries
                return RateLimitDecision(
                    allowed=True,
                    limit=max_requests,
                    remaining=max_requests - current_count - 1,
                    retry_after_s=0.0,
                    scope=scope,
                    key=key,
                )
            else:
                self._memory_windows[key] = valid_entries
                oldest_ts = valid_entries[0][0] if valid_entries else now
                retry_after = max(0.0, (oldest_ts + window_seconds) - now)
                return RateLimitDecision(
                    allowed=False,
                    limit=max_requests,
                    remaining=0,
                    retry_after_s=retry_after,
                    scope=scope,
                    key=key,
                    reason=f"Rate limit exceeded: {max_requests} req / {window_seconds}s for {scope}",
                )

    def reset(self, key_pattern: str | None = None) -> None:
        """Reset rate limiter state (primarily for test isolation)."""
        with self._lock:
            if key_pattern is None:
                self._memory_windows.clear()
            else:
                self._memory_windows = {
                    k: v for k, v in self._memory_windows.items() if key_pattern not in k
                }

        redis_client = self._get_redis()
        if redis_client is not None:
            try:
                pattern = f"{self._prefix}:*" if key_pattern is None else f"{self._prefix}:*{key_pattern}*"
                keys = redis_client.keys(pattern)
                if keys:
                    redis_client.delete(*keys)
            except Exception:
                pass
