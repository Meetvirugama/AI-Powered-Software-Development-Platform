"""Small lazy Redis client wrapper shared by auth and background jobs."""

from functools import lru_cache

from redis import Redis

from app.core.config import get_settings


@lru_cache
def get_redis() -> Redis:
    """Create one synchronous Redis client per process without connecting at import time."""
    return Redis.from_url(get_settings().redis_url, decode_responses=True)
