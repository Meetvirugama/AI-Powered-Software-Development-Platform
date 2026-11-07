"""
Unit tests for retrieval cache key stability and repository-scoped invalidation (R04).
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from backend.ai.retrieval.cache import RetrievalResultCache
from backend.ai.retrieval.cache_keys import build_retrieval_cache_key, normalize_retrieval_query


def test_normalize_retrieval_query() -> None:
    assert normalize_retrieval_query("  SELECT *   from   Users\n") == "select * from users"
    assert normalize_retrieval_query("") == ""


def test_cache_key_deterministic_and_unique() -> None:
    repo_id = uuid4()
    key1 = build_retrieval_cache_key("getUserById", repo_id, index_generation=1, intent="exact_symbol")
    key2 = build_retrieval_cache_key("getUserById", repo_id, index_generation=1, intent="exact_symbol")
    assert key1 == key2

    # Generation change produces different key
    key_gen2 = build_retrieval_cache_key("getUserById", repo_id, index_generation=2, intent="exact_symbol")
    assert key1 != key_gen2

    # Intent change produces different key
    key_intent = build_retrieval_cache_key("getUserById", repo_id, index_generation=1, intent="conceptual")
    assert key1 != key_intent

    # Query change produces different key
    key_query = build_retrieval_cache_key("createUser", repo_id, index_generation=1, intent="exact_symbol")
    assert key1 != key_query

    # top_k change produces different key
    key_topk = build_retrieval_cache_key("getUserById", repo_id, index_generation=1, intent="exact_symbol", top_k=15)
    assert key1 != key_topk

    # Version change produces different key
    key_ver = build_retrieval_cache_key(
        "getUserById",
        repo_id,
        index_generation=1,
        intent="exact_symbol",
        versions={"embedding_version": "v2"},
    )
    assert key1 != key_ver


@pytest.mark.asyncio
async def test_invalidate_repository_cursor_scan() -> None:
    repo_a = uuid4()
    mock_redis = AsyncMock()

    # Async generator simulating scan_iter
    async def mock_scan_iter(match: str, count: int = 100):
        yield f"retrieval:v2:default:{repo_a}:1:hash1"
        yield f"retrieval:v2:default:{repo_a}:1:hash2"

    mock_redis.scan_iter = mock_scan_iter
    mock_redis.delete.return_value = 2

    cache = RetrievalResultCache(redis_client=mock_redis, enabled=True)
    deleted = await cache.invalidate_repository(repo_a)

    assert deleted == 2
    mock_redis.delete.assert_called_once_with(
        f"retrieval:v2:default:{repo_a}:1:hash1",
        f"retrieval:v2:default:{repo_a}:1:hash2",
    )


@pytest.mark.asyncio
async def test_invalidate_repository_redis_exception_graceful() -> None:
    repo_id = uuid4()
    mock_redis = AsyncMock()

    async def mock_scan_iter(match: str, count: int = 100):
        raise ConnectionError("Redis unreachable")
        yield  # Make it a generator

    mock_redis.scan_iter = mock_scan_iter
    cache = RetrievalResultCache(redis_client=mock_redis, enabled=True)

    deleted = await cache.invalidate_repository(repo_id)
    assert deleted == 0
