"""Small lazy Redis client wrapper shared by auth and background jobs."""

from functools import lru_cache

from redis import Redis
from redis.asyncio import Redis as AsyncRedis

from app.core.config import get_settings


@lru_cache
def get_redis() -> Redis:
    """Create one synchronous Redis client per process without connecting at import time."""
    return Redis.from_url(get_settings().redis_url, decode_responses=True)


async def get_redis_async() -> AsyncRedis:
    """Create an async Redis client for use in async startup contexts."""
    return AsyncRedis.from_url(get_settings().redis_url, decode_responses=True)
