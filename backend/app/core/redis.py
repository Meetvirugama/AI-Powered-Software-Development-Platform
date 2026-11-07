"""Small lazy Redis client wrapper shared by auth and background jobs."""

from functools import lru_cache

from redis import Redis
from redis.asyncio import Redis as AsyncRedis

from app.core.config import get_settings

_async_redis_client: AsyncRedis | None = None


def _get_redis_options() -> dict:
    """Return tuned Redis options with Upstash serverless resilience and idle pinging."""
    settings = get_settings()
    url_lower = (settings.redis_url or "").lower()
    is_upstash = "upstash.io" in url_lower or url_lower.startswith("rediss://")
    return {
        "decode_responses": True,
        "socket_connect_timeout": 5.0,
        "socket_timeout": 10.0,
        "retry_on_timeout": True,
        "health_check_interval": 30 if is_upstash else 0,
    }


@lru_cache
def get_redis() -> Redis:
    """Create one synchronous Redis client per process without connecting at import time."""
    return Redis.from_url(
        get_settings().redis_url,
        **_get_redis_options(),
    )


def get_async_redis_client() -> AsyncRedis:
    """Return a shared async Redis client without requiring an await."""
    global _async_redis_client
    if _async_redis_client is None:
        _async_redis_client = AsyncRedis.from_url(
            get_settings().redis_url,
            **_get_redis_options(),
        )
    return _async_redis_client


async def get_redis_async() -> AsyncRedis:
    """Return a shared async Redis client per process with timeouts configured."""
    return get_async_redis_client()


async def close_redis_async() -> None:
    """Close the cached async Redis client if initialized."""
    global _async_redis_client
    if _async_redis_client is not None:
        try:
            await _async_redis_client.aclose()
        except Exception:
            pass
        _async_redis_client = None


def close_redis() -> None:
    """Close the cached synchronous Redis client if initialized."""
    try:
        client = get_redis()
        client.close()
    except Exception:
        pass
    get_redis.cache_clear()


