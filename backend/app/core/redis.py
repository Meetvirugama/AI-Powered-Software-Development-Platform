"""Small lazy Redis client wrapper shared by auth, events, and background jobs.

F40 (Issue #244):
- Thread/coroutine-safe singleton initialization via double-checked locking and asyncio.Lock.
- Bounded connection pooling with max_connections ceiling from Settings.
- Graceful degradation under connection pool exhaustion via exponential backoff.
- Clean draining and resource cleanup on shutdown.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import random
import threading
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from redis import ConnectionPool, Redis
from redis.asyncio import ConnectionPool as AsyncConnectionPool
from redis.asyncio import Redis as AsyncRedis
from redis.exceptions import (
    ConnectionError as RedisConnectionError,
)
from redis.exceptions import (
    TimeoutError as RedisTimeoutError,
)

from app.core.config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Singletons and connection pools
_async_redis_client: AsyncRedis | None = None
_async_connection_pool: AsyncConnectionPool | None = None

_sync_redis_client: Redis | None = None
_sync_connection_pool: ConnectionPool | None = None

# Thread and Coroutine locks for singleton initialization
_thread_lock = threading.Lock()
_async_lock: asyncio.Lock | None = None
_async_lock_loop: asyncio.AbstractEventLoop | None = None


class RedisPoolExhaustedError(RuntimeError):
    """Raised when Redis connection pool remains exhausted after bounded retry attempts."""


def _get_async_lock() -> asyncio.Lock:
    """Return an asyncio.Lock bound to the current running event loop."""
    global _async_lock, _async_lock_loop
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    if _async_lock is None or _async_lock_loop != current_loop:
        _async_lock = asyncio.Lock()
        _async_lock_loop = current_loop
    return _async_lock


def _get_redis_options() -> dict[str, Any]:
    """Return tuned Redis options with Upstash serverless resilience and idle pinging."""
    settings = get_settings()
    url_lower = (settings.redis_url or "").lower()
    is_upstash = "upstash.io" in url_lower or url_lower.startswith("rediss://")
    default_hc = getattr(settings, "redis_health_check_interval", 30 if is_upstash else 0)
    health_check = 30 if is_upstash else default_hc
    return {
        "decode_responses": True,
        "socket_connect_timeout": getattr(settings, "redis_connection_timeout", 5.0),
        "socket_timeout": getattr(settings, "redis_socket_timeout", 10.0),
        "retry_on_timeout": getattr(settings, "redis_retry_on_timeout", True),
        "health_check_interval": health_check,
    }


def get_redis() -> Redis:
    """Create one synchronous Redis client per process with bounded connection pooling."""
    global _sync_redis_client, _sync_connection_pool
    if _sync_redis_client is None:
        with _thread_lock:
            if _sync_redis_client is None:
                settings = get_settings()
                opts = _get_redis_options()
                max_conn = getattr(settings, "redis_max_connections", 50)
                pool = ConnectionPool.from_url(
                    settings.redis_url,
                    max_connections=max_conn,
                    **opts,
                )
                _sync_connection_pool = pool
                _sync_redis_client = Redis(connection_pool=pool)
    return _sync_redis_client


# Backward-compatible cache_clear method for callers expecting lru_cache behavior
get_redis.cache_clear = lambda: close_redis()  # type: ignore[attr-defined]


def get_async_redis_client() -> AsyncRedis:
    """Return a shared async Redis client without requiring an await.

    Uses double-checked locking with a threading.Lock to guarantee thread-safe,
    coroutine-safe singleton initialization with bounded connection pooling.
    """
    global _async_redis_client, _async_connection_pool
    if _async_redis_client is None:
        with _thread_lock:
            if _async_redis_client is None:
                settings = get_settings()
                opts = _get_redis_options()
                max_conn = getattr(settings, "redis_max_connections", 50)
                pool = AsyncConnectionPool.from_url(
                    settings.redis_url,
                    max_connections=max_conn,
                    **opts,
                )
                _async_connection_pool = pool
                _async_redis_client = AsyncRedis(connection_pool=pool)
    return _async_redis_client


async def get_redis_async() -> AsyncRedis:
    """Return a shared async Redis client per process with coroutine-safe locking."""
    if _async_redis_client is None:
        async with _get_async_lock():
            return get_async_redis_client()
    return _async_redis_client


def get_async_connection_pool() -> AsyncConnectionPool:
    """Return the underlying async Redis connection pool, initializing if necessary."""
    get_async_redis_client()
    assert _async_connection_pool is not None
    return _async_connection_pool


def get_sync_connection_pool() -> ConnectionPool:
    """Return the underlying synchronous Redis connection pool, initializing if necessary."""
    get_redis()
    assert _sync_connection_pool is not None
    return _sync_connection_pool


async def close_redis_async() -> None:
    """Close the cached async Redis client and its connection pool if initialized."""
    global _async_redis_client, _async_connection_pool, _async_lock, _async_lock_loop
    client = _async_redis_client
    pool = _async_connection_pool
    _async_redis_client = None
    _async_connection_pool = None
    _async_lock = None
    _async_lock_loop = None

    if client is not None:
        try:
            await client.aclose()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Error closing async Redis client: %s", exc)

    if pool is not None:
        try:
            await pool.disconnect()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Error disconnecting async Redis connection pool: %s", exc)


def close_redis() -> None:
    """Close the cached synchronous Redis client and connection pool if initialized."""
    global _sync_redis_client, _sync_connection_pool
    client = _sync_redis_client
    pool = _sync_connection_pool
    _sync_redis_client = None
    _sync_connection_pool = None

    if client is not None:
        try:
            client.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Error closing sync Redis client: %s", exc)

    if pool is not None:
        try:
            pool.disconnect()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Error disconnecting sync Redis connection pool: %s", exc)


def is_redis_pool_exhausted_error(exc: Exception) -> bool:
    """Check if an exception indicates connection pool exhaustion or concurrency limits."""
    msg = str(exc).lower()
    return (
        isinstance(exc, (RedisConnectionError, RedisTimeoutError, ConnectionError, TimeoutError))
        and (
            "too many connections" in msg
            or "pool exhausted" in msg
            or "max connections" in msg
            or "connection pool" in msg
            or "pool busy" in msg
        )
    )


async def run_with_redis_retry(
    operation: Callable[..., Awaitable[T] | T],
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 0.05,
    max_delay: float = 0.5,
    **kwargs: Any,
) -> T:
    """Execute a Redis async operation with controlled exponential backoff on pool exhaustion."""
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            res = operation(*args, **kwargs)
            if inspect.isawaitable(res):
                return await res
            return res  # type: ignore[return-value]
        except Exception as exc:
            if not is_redis_pool_exhausted_error(exc) and not isinstance(exc, (RedisConnectionError, RedisTimeoutError)):
                raise
            last_exc = exc
            if attempt == max_retries:
                logger.warning(
                    "redis_pool_exhausted_after_retries",
                    extra={"attempts": attempt + 1, "error": str(exc)},
                )
                raise RedisPoolExhaustedError(
                    f"Redis operation failed after {max_retries + 1} attempts due to connection pool saturation: {exc}"
                ) from exc

            delay = min(base_delay * (2 ** attempt) + random.uniform(0, 0.05), max_delay)
            logger.debug(
                "redis_pool_busy_backing_off",
                extra={"attempt": attempt + 1, "delay": delay, "error": str(exc)},
            )
            await asyncio.sleep(delay)

    assert last_exc is not None
    raise last_exc



