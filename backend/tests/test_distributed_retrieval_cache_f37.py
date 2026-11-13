"""
Comprehensive Tests for Feature F37 (Issue #218 & task5.md):
Distributed Retrieval Query Cache & Cache Invalidation.
"""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from ai.retrieval.base import CodeChunk
from ai.retrieval.cache import (
    InMemoryRetrievalCache,
    RedisRetrievalCache,
    RetrievalResultCache,
    TwoLevelRetrievalCache,
    get_retrieval_cache,
)
from ai.retrieval.cache_keys import (
    build_retrieval_cache_key,
    bump_repository_index_version_async,
    generate_query_hash,
    get_repository_index_version,
    get_repository_index_version_async,
    normalize_retrieval_query,
    set_repository_index_version,
    set_repository_index_version_async,
)
from ai.retrieval.cache_serialization import (
    CURRENT_SCHEMA_VERSION,
    deserialize_chunks,
    deserialize_retrieval_payload,
    serialize_chunks,
    serialize_retrieval_payload,
)
from ai.services.retrieval_optimizer import (
    AgentTokenBudgetManager,
    LRUQueryCache,
    RetrievalLatencyOptimizer,
    TokenBudgetExhaustedError,
)


def _make_chunk(name: str = "chunk") -> CodeChunk:
    return CodeChunk(
        id=uuid4(),
        repository_id=uuid4(),
        file_id=uuid4(),
        symbol_id=uuid4(),
        content=f"def {name}(): return True",
        token_count=10,
        start_line=1,
        end_line=3,
        content_hash="chash123",
        score=0.95,
        file_path=f"src/{name}.py",
    )


# ---------------------------------------------------------------------------
# 1. Query Normalization & Hashing
# ---------------------------------------------------------------------------

def test_query_normalization():
    assert normalize_retrieval_query("  SELECT   * FROM   Users \n") == "select * from users"
    assert normalize_retrieval_query("") == ""
    assert normalize_retrieval_query("UserAuth\t\tLogin") == "userauth login"


def test_query_hash_determinism_and_uniqueness():
    h1 = generate_query_hash("search auth", {"intent": "conceptual", "top_k": 8})
    h2 = generate_query_hash("  search   auth  ", {"intent": "conceptual", "top_k": 8})
    assert h1 == h2

    # Intent change produces distinct hash
    h_intent = generate_query_hash("search auth", {"intent": "exact_symbol", "top_k": 8})
    assert h1 != h_intent

    # top_k change produces distinct hash
    h_topk = generate_query_hash("search auth", {"intent": "conceptual", "top_k": 20})
    assert h1 != h_topk


def test_build_retrieval_cache_key_with_index_version():
    repo_id = uuid4()
    k1 = build_retrieval_cache_key("find user", repo_id, index_version="v1")
    k2 = build_retrieval_cache_key("find user", repo_id, index_version="v1")
    assert k1 == k2

    # Different index versions isolate keys
    k_v2 = build_retrieval_cache_key("find user", repo_id, index_version="v2")
    assert k1 != k_v2


# ---------------------------------------------------------------------------
# 2. Serialization & Deserialization
# ---------------------------------------------------------------------------

def test_generic_payload_serialization():
    payload = {"query": "login", "matches": [1, 2, 3], "meta": {"elapsed": 12.5}}
    serialized = serialize_retrieval_payload(payload)
    deserialized = deserialize_retrieval_payload(serialized)
    assert deserialized == payload


def test_chunk_serialization_and_generic_fallback():
    chunk = _make_chunk("sample")
    serialized = serialize_retrieval_payload([chunk])
    deserialized = deserialize_retrieval_payload(serialized)
    assert isinstance(deserialized, list)
    assert len(deserialized) == 1
    assert deserialized[0].id == chunk.id
    assert deserialized[0].content == chunk.content


def test_corrupt_payload_handling():
    assert deserialize_retrieval_payload("") is None
    assert deserialize_retrieval_payload("invalid json") is None
    assert deserialize_retrieval_payload(json.dumps({"schema_version": "99.0", "data": "old"})) is None


# ---------------------------------------------------------------------------
# 3. Local LRU Cache & Invalidation
# ---------------------------------------------------------------------------

def test_lru_query_cache_ttl_and_eviction():
    cache = LRUQueryCache(maxsize=2, ttl_seconds=0.1)
    cache.set("k1", "v1")
    cache.set("k2", "v2")
    assert cache.get("k1") == "v1"

    # Eviction on maxsize
    cache.set("k3", "v3")
    assert cache.get("k2") is None  # k2 was oldest accessed
    assert cache.get("k1") == "v1"
    assert cache.get("k3") == "v3"

    # TTL expiration
    time.sleep(0.12)
    assert cache.get("k1") is None
    assert cache.get("k3") is None


def test_lru_query_cache_invalidation_by_repo():
    cache = LRUQueryCache(maxsize=10, ttl_seconds=300)
    repo_a = str(uuid4())
    repo_b = str(uuid4())

    cache.set(f"retrieval:v2:default:{repo_a}:v1:hash1", "val_a1")
    cache.set(f"retrieval:v2:default:{repo_a}:v1:hash2", "val_a2")
    cache.set(f"retrieval:v2:default:{repo_b}:v1:hash3", "val_b1")

    assert cache.get(f"retrieval:v2:default:{repo_a}:v1:hash1") == "val_a1"
    deleted = cache.invalidate_repository(repo_a)
    assert deleted == 2

    assert cache.get(f"retrieval:v2:default:{repo_a}:v1:hash1") is None
    assert cache.get(f"retrieval:v2:default:{repo_a}:v1:hash2") is None
    assert cache.get(f"retrieval:v2:default:{repo_b}:v1:hash3") == "val_b1"


# ---------------------------------------------------------------------------
# 4. Redis Cache Adapter & Error Resilience
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_redis_retrieval_cache_get_set_delete():
    mock_redis = AsyncMock()
    cache = RedisRetrievalCache(redis_client=mock_redis, enabled=True)

    data = {"result": "success"}
    mock_redis.get.return_value = serialize_retrieval_payload(data)

    val = await cache.get("key101")
    assert val == data
    mock_redis.get.assert_called_once_with("key101")

    mock_redis.set.return_value = True
    ok = await cache.set("key101", data, ttl_seconds=60)
    assert ok is True
    mock_redis.set.assert_called_once()

    mock_redis.delete.return_value = 1
    deleted = await cache.delete("key101")
    assert deleted is True


@pytest.mark.asyncio
async def test_redis_retrieval_cache_handles_connection_error_gracefully():
    mock_redis = AsyncMock()
    mock_redis.get.side_effect = ConnectionError("Redis server unavailable")
    mock_redis.set.side_effect = ConnectionError("Redis server unavailable")

    cache = RedisRetrievalCache(redis_client=mock_redis, enabled=True)

    # get returns None without raising
    val = await cache.get("any_key")
    assert val is None

    # set returns False without raising
    res = await cache.set("any_key", {"foo": "bar"})
    assert res is False


# ---------------------------------------------------------------------------
# 5. Two-Level Cache Coordination (L1 + L2)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_two_level_cache_l1_hit_avoids_redis():
    mock_redis = AsyncMock()
    l1 = InMemoryRetrievalCache(maxsize=100)
    l2 = RedisRetrievalCache(redis_client=mock_redis, enabled=True)
    coordinator = TwoLevelRetrievalCache(l1_cache=l1, l2_cache=l2)

    # Seed L1 directly
    await l1.set("k1", "cached_in_l1")

    val = await coordinator.get("k1")
    assert val == "cached_in_l1"
    # Redis should never be queried when L1 hits
    mock_redis.get.assert_not_called()
    assert coordinator.stats["local_hits"] == 1
    assert coordinator.stats["redis_hits"] == 0


@pytest.mark.asyncio
async def test_two_level_cache_l2_hit_populates_l1():
    mock_redis = AsyncMock()
    l1 = InMemoryRetrievalCache(maxsize=100)
    l2 = RedisRetrievalCache(redis_client=mock_redis, enabled=True)
    coordinator = TwoLevelRetrievalCache(l1_cache=l1, l2_cache=l2)

    data = {"chunks": ["chunk1", "chunk2"]}
    mock_redis.get.return_value = serialize_retrieval_payload(data)

    # 1st call: L1 miss, L2 hit -> populates L1
    val1 = await coordinator.get("k_shared")
    assert val1 == data
    assert coordinator.stats["local_hits"] == 0
    assert coordinator.stats["redis_hits"] == 1

    # 2nd call: L1 should now hit directly without calling Redis again!
    mock_redis.get.reset_mock()
    val2 = await coordinator.get("k_shared")
    assert val2 == data
    mock_redis.get.assert_not_called()
    assert coordinator.stats["local_hits"] == 1


@pytest.mark.asyncio
async def test_two_level_cache_set_populates_both_layers():
    mock_redis = AsyncMock()
    l1 = InMemoryRetrievalCache(maxsize=100)
    l2 = RedisRetrievalCache(redis_client=mock_redis, enabled=True)
    coordinator = TwoLevelRetrievalCache(l1_cache=l1, l2_cache=l2)

    data = {"test": "data"}
    await coordinator.set("k_both", data, ttl_seconds=120)

    # In L1
    assert await l1.get("k_both") == data
    # In L2 Redis
    mock_redis.set.assert_called_once()


@pytest.mark.asyncio
async def test_two_level_cache_stampede_lock():
    mock_redis = AsyncMock()
    mock_redis.set.return_value = True
    mock_redis.get.return_value = "token-123"
    mock_redis.delete.return_value = 1

    l2 = RedisRetrievalCache(redis_client=mock_redis, enabled=True)
    coordinator = TwoLevelRetrievalCache(l2_cache=l2)

    token = await coordinator.acquire_stampede_lock("stampede_key", ttl_seconds=5)
    assert token is not None

    released = await coordinator.release_stampede_lock("stampede_key", "token-123")
    assert released is True


# ---------------------------------------------------------------------------
# 6. Repository Index Version Invalidation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_repository_index_version_lifecycle():
    repo_id = uuid4()
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None

    # Initial version defaults to "0"
    v0 = await get_repository_index_version_async(repo_id, mock_redis)
    assert v0 == "0"

    # Set new version
    await set_repository_index_version_async(repo_id, "commit-sha-abc", mock_redis)
    mock_redis.set.assert_called_once()

    # Bumping version produces a new timestamped version
    new_v = await bump_repository_index_version_async(repo_id, mock_redis)
    assert new_v.startswith("v")


@pytest.mark.asyncio
async def test_repository_invalidation_updates_version_and_clears_keys():
    repo_id = uuid4()
    mock_redis = AsyncMock()

    async def mock_scan_iter(match: str, count: int = 100):
        yield f"retrieval:v2:default:{repo_id}:0:hash1"

    mock_redis.scan_iter = mock_scan_iter
    mock_redis.delete.return_value = 1

    l1 = InMemoryRetrievalCache(maxsize=100)
    l2 = RedisRetrievalCache(redis_client=mock_redis, enabled=True)
    coordinator = TwoLevelRetrievalCache(l1_cache=l1, l2_cache=l2)

    # Seed L1
    key = f"retrieval:v2:default:{repo_id}:0:hash1"
    await l1.set(key, "data")
    assert await l1.get(key) == "data"

    # Invalidate repository
    deleted = await coordinator.invalidate_repository(repo_id, new_index_version="commit-2")
    assert deleted >= 1
    # L1 key was removed
    assert await l1.get(key) is None


# ---------------------------------------------------------------------------
# 7. RetrievalLatencyOptimizer with Two-Level Cache & SLO
# ---------------------------------------------------------------------------

def test_optimizer_backward_compatibility():
    optimizer = RetrievalLatencyOptimizer(target_p95_ms=400.0)

    call_count = 0
    def mock_fetch(q: str):
        nonlocal call_count
        call_count += 1
        return {"query": q}

    # Cold miss
    res1, d1 = optimizer.execute_optimized_retrieval("test query", mock_fetch)
    assert call_count == 1
    assert res1 == {"query": "test query"}

    # Warm hit
    res2, d2 = optimizer.execute_optimized_retrieval("test query", mock_fetch)
    assert call_count == 1  # Not called again
    assert d2 == 0.5

    percentiles = optimizer.get_latency_percentiles()
    assert percentiles.target_met is True
    assert percentiles.p95_ms < 400.0


@pytest.mark.asyncio
async def test_optimizer_execute_optimized_retrieval_async():
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None  # Cold miss on Redis

    l1 = InMemoryRetrievalCache(maxsize=100)
    l2 = RedisRetrievalCache(redis_client=mock_redis, enabled=True)
    coord = TwoLevelRetrievalCache(l1_cache=l1, l2_cache=l2)

    optimizer = RetrievalLatencyOptimizer(distributed_cache=coord)

    call_count = 0
    async def async_retrieval(q: str):
        nonlocal call_count
        call_count += 1
        return ["chunk_a", "chunk_b"]

    # 1st call: cold miss -> executes retrieval
    res1, d1 = await optimizer.execute_optimized_retrieval_async("search payments", async_retrieval)
    assert call_count == 1
    assert res1 == ["chunk_a", "chunk_b"]

    # 2nd call: warm L1 hit -> sub-millisecond, does not call retrieval
    res2, d2 = await optimizer.execute_optimized_retrieval_async("search payments", async_retrieval)
    assert call_count == 1
    assert d2 == 0.5
    assert res2 == ["chunk_a", "chunk_b"]

    # Percentiles reflect low latency
    p = optimizer.get_latency_percentiles()
    assert p.target_met is True
    assert p.sample_count == 2
