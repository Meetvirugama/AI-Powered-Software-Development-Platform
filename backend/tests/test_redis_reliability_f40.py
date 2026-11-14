"""Unit and integration tests for F40: Redis reliability, thread/coroutine-safe singleton initialization, and bounded connection pooling."""

from __future__ import annotations

import asyncio
import concurrent.futures
from unittest.mock import AsyncMock, patch

import pytest
from app.core import redis as redis_mod
from app.core.config import get_settings
from app.core.redis import (
    RedisPoolExhaustedError,
    close_redis,
    close_redis_async,
    get_async_connection_pool,
    get_async_redis_client,
    get_redis,
    get_redis_async,
    get_sync_connection_pool,
    is_redis_pool_exhausted_error,
    run_with_redis_retry,
)
from redis.asyncio import Redis as AsyncRedis
from redis.exceptions import (
    ConnectionError as RedisConnectionError,
)
from redis.exceptions import (
    TimeoutError as RedisTimeoutError,
)


@pytest.fixture(autouse=True)
async def cleanup_redis_singletons():
    """Ensure clean Redis singleton state before and after each test."""
    close_redis()
    await close_redis_async()
    yield
    close_redis()
    await close_redis_async()


# ---------------------------------------------------------------------------
# 1. Singleton Initialization & Concurrency Safety
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_concurrent_async_redis_initialization_single_instance():
    """Verify concurrent requests during application startup instantiate exactly one async client and pool."""
    # Launch 50 concurrent coroutines acquiring the async Redis client
    clients = await asyncio.gather(*[get_redis_async() for _ in range(50)])

    first_client = clients[0]
    assert all(c is first_client for c in clients), "All coroutines must receive the identical singleton client"

    pool = get_async_connection_pool()
    assert first_client.connection_pool is pool
    assert pool.max_connections == get_settings().redis_max_connections


def test_concurrent_multithreaded_get_async_redis_client():
    """Verify concurrent calls from multiple OS worker threads return the exact same async singleton client."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
        futures = [executor.submit(get_async_redis_client) for _ in range(32)]
        clients = [f.result() for f in concurrent.futures.as_completed(futures)]

    unique_client_ids = {id(c) for c in clients}
    assert len(unique_client_ids) == 1, "All worker threads must receive the exact same singleton instance"


def test_concurrent_multithreaded_get_sync_redis_client():
    """Verify concurrent calls from multiple OS worker threads return the exact same sync singleton client."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
        futures = [executor.submit(get_redis) for _ in range(32)]
        clients = [f.result() for f in concurrent.futures.as_completed(futures)]

    unique_client_ids = {id(c) for c in clients}
    assert len(unique_client_ids) == 1, "All worker threads must receive the exact same synchronous singleton"


# ---------------------------------------------------------------------------
# 2. Explicit Bounded Connection Pooling
# ---------------------------------------------------------------------------

def test_bounded_connection_pool_configuration():
    """Verify connection pool ceilings are strictly bounded by Settings."""
    settings = get_settings()
    default_max = settings.redis_max_connections
    assert default_max == 50, "Default redis_max_connections should be 50"

    sync_pool = get_sync_connection_pool()
    assert sync_pool.max_connections == default_max

    async_pool = get_async_connection_pool()
    assert async_pool.max_connections == default_max


def test_custom_connection_pool_ceiling(monkeypatch):
    """Verify setting a custom redis_max_connections bounds the instantiated pool accordingly."""
    close_redis()
    monkeypatch.setattr(get_settings(), "redis_max_connections", 25)

    sync_pool = get_sync_connection_pool()
    assert sync_pool.max_connections == 25

    async_pool = get_async_connection_pool()
    assert async_pool.max_connections == 25


# ---------------------------------------------------------------------------
# 3. Clean Shutdown & Resource Draining
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_close_redis_async_drains_and_resets():
    """Verify close_redis_async drains connection pool and resets globals."""
    client = await get_redis_async()
    pool = get_async_connection_pool()
    assert redis_mod._async_redis_client is not None
    assert redis_mod._async_connection_pool is not None

    with patch.object(client, "aclose", new_callable=AsyncMock) as mock_aclose, \
         patch.object(pool, "disconnect", new_callable=AsyncMock) as mock_disconnect:
        await close_redis_async()
        mock_aclose.assert_called_once()
        mock_disconnect.assert_called_once()

    assert redis_mod._async_redis_client is None
    assert redis_mod._async_connection_pool is None

    # Idempotent second call
    await close_redis_async()
    assert redis_mod._async_redis_client is None


def test_close_sync_redis_drains_and_resets():
    """Verify close_redis drains sync connection pool and resets globals."""
    client = get_redis()
    pool = get_sync_connection_pool()
    assert redis_mod._sync_redis_client is not None
    assert redis_mod._sync_connection_pool is not None

    with patch.object(client, "close") as mock_close, \
         patch.object(pool, "disconnect") as mock_disconnect:
        close_redis()
        mock_close.assert_called_once()
        mock_disconnect.assert_called_once()

    assert redis_mod._sync_redis_client is None
    assert redis_mod._sync_connection_pool is None

    # Cache clear backward compatibility
    get_redis.cache_clear()
    assert redis_mod._sync_redis_client is None


# ---------------------------------------------------------------------------
# 4. Graceful Degradation & Backoff on Pool Exhaustion
# ---------------------------------------------------------------------------

def test_is_redis_pool_exhausted_error():
    """Verify detection of connection pool exhaustion error variants."""
    assert is_redis_pool_exhausted_error(RedisConnectionError("Too many connections"))
    assert is_redis_pool_exhausted_error(RedisConnectionError("Connection pool exhausted"))
    assert is_redis_pool_exhausted_error(ConnectionError("Max connections reached on server"))
    assert is_redis_pool_exhausted_error(RedisTimeoutError("Connection pool busy"))

    assert not is_redis_pool_exhausted_error(ValueError("Invalid syntax"))
    assert not is_redis_pool_exhausted_error(KeyError("missing_key"))


@pytest.mark.asyncio
async def test_run_with_redis_retry_success_after_transient_exhaustion():
    """Verify run_with_redis_retry retries with backoff and succeeds after transient exhaustion."""
    attempts = 0

    async def mock_redis_operation():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RedisConnectionError("Too many connections")
        return "operation_success"

    result = await run_with_redis_retry(
        mock_redis_operation,
        max_retries=3,
        base_delay=0.01,
        max_delay=0.05,
    )

    assert result == "operation_success"
    assert attempts == 3


@pytest.mark.asyncio
async def test_run_with_redis_retry_raises_exhausted_error_when_persistent():
    """Verify persistent pool saturation raises RedisPoolExhaustedError instead of unhandled 500 crash."""
    attempts = 0

    async def failing_operation():
        nonlocal attempts
        attempts += 1
        raise RedisConnectionError("Too many connections")

    with pytest.raises(RedisPoolExhaustedError) as exc_info:
        await run_with_redis_retry(
            failing_operation,
            max_retries=2,
            base_delay=0.01,
            max_delay=0.02,
        )

    assert attempts == 3  # Initial + 2 retries
    assert "connection pool saturation" in str(exc_info.value)


@pytest.mark.asyncio
async def test_run_with_redis_retry_propagates_non_connection_errors_immediately():
    """Verify non-connection errors fail fast without redundant retry delays."""
    call_count = 0

    async def bad_command():
        nonlocal call_count
        call_count += 1
        raise ValueError("Invalid Redis command argument")

    with pytest.raises(ValueError, match="Invalid Redis command argument"):
        await run_with_redis_retry(bad_command, max_retries=3)

    assert call_count == 1, "Should not retry non-connection exceptions"


# ---------------------------------------------------------------------------
# 5. Zero Breaking Changes
# ---------------------------------------------------------------------------

def test_sync_and_async_interface_compatibility():
    """Verify all existing calling conventions continue operating without code changes."""
    # Sync caller
    sync_c = get_redis()
    assert sync_c is not None

    # Async caller requesting without await
    async_c1 = get_async_redis_client()
    assert isinstance(async_c1, AsyncRedis)

    # Async caller requesting with await
    loop = asyncio.new_event_loop()
    try:
        async_c2 = loop.run_until_complete(get_redis_async())
        assert async_c1 is async_c2
    finally:
        loop.close()
