"""
Unit tests for Redis retrieval-result cache (R03).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from backend.ai.retrieval.base import CodeChunk
from backend.ai.retrieval.cache import RetrievalResultCache
from backend.ai.retrieval.cache_serialization import (
    CURRENT_SCHEMA_VERSION,
    deserialize_chunks,
    serialize_chunks,
)


def _make_chunk(name: str = "chunk") -> CodeChunk:
    return CodeChunk(
        id=uuid4(),
        repository_id=uuid4(),
        file_id=uuid4(),
        symbol_id=uuid4(),
        content=f"def {name}(): pass",
        token_count=12,
        start_line=1,
        end_line=5,
        content_hash="hash123",
        score=0.92,
        file_path=f"src/{name}.py",
        rrf_score=0.032,
        reranker_logit=1.85,
        vector_similarity=0.88,
        lexical_rank=0.75,
        graph_score=0.5,
    )


def test_serialization_round_trip() -> None:
    c1 = _make_chunk("c1")
    c2 = _make_chunk("c2")

    serialized = serialize_chunks([c1, c2])
    assert isinstance(serialized, str)

    deserialized = deserialize_chunks(serialized)
    assert deserialized is not None
    assert len(deserialized) == 2

    assert deserialized[0].id == c1.id
    assert deserialized[0].file_path == c1.file_path
    assert deserialized[0].score == c1.score
    assert deserialized[0].rrf_score == c1.rrf_score
    assert deserialized[0].reranker_logit == c1.reranker_logit
    assert deserialized[0].vector_similarity == c1.vector_similarity
    assert deserialized[0].graph_score == c1.graph_score


def test_deserialization_schema_mismatch() -> None:
    c1 = _make_chunk()
    payload = {
        "schema_version": "99.0",  # Incompatible version
        "chunks": [{"id": str(c1.id)}],
    }
    res = deserialize_chunks(json.dumps(payload))
    assert res is None


def test_deserialization_corrupt_data() -> None:
    assert deserialize_chunks("") is None
    assert deserialize_chunks("not json") is None
    assert deserialize_chunks("{bad json") is None
    assert deserialize_chunks(json.dumps({"schema_version": CURRENT_SCHEMA_VERSION, "chunks": "invalid"})) is None


@pytest.mark.asyncio
async def test_cache_hit_and_miss() -> None:
    c = _make_chunk("cached")
    serialized = serialize_chunks([c])

    mock_redis = AsyncMock()
    # 1st call: hit
    mock_redis.get.return_value = serialized
    cache = RetrievalResultCache(redis_client=mock_redis, enabled=True)

    hit = await cache.get("key1")
    assert hit is not None
    assert len(hit) == 1
    assert hit[0].id == c.id

    # 2nd call: miss
    mock_redis.get.return_value = None
    miss = await cache.get("key2")
    assert miss is None


@pytest.mark.asyncio
async def test_cache_set() -> None:
    c = _make_chunk("to_cache")
    mock_redis = AsyncMock()
    cache = RetrievalResultCache(redis_client=mock_redis, enabled=True, default_ttl_seconds=120)

    ok = await cache.set("cache_key", [c], ttl_seconds=60)
    assert ok is True
    mock_redis.set.assert_called_once()
    args, kwargs = mock_redis.set.call_args
    assert args[0] == "cache_key"
    assert kwargs.get("ex") == 60


@pytest.mark.asyncio
async def test_cache_disabled() -> None:
    mock_redis = AsyncMock()
    cache = RetrievalResultCache(redis_client=mock_redis, enabled=False)

    assert await cache.get("key") is None
    assert await cache.set("key", [_make_chunk()]) is False
    assert not mock_redis.get.called
    assert not mock_redis.set.called


@pytest.mark.asyncio
async def test_cache_redis_exception_graceful() -> None:
    mock_redis = AsyncMock()
    mock_redis.get.side_effect = ConnectionError("Redis disconnected")
    mock_redis.set.side_effect = ConnectionError("Redis disconnected")

    cache = RetrievalResultCache(redis_client=mock_redis, enabled=True)
    # Should not raise exception
    assert await cache.get("key") is None
    assert await cache.set("key", [_make_chunk()]) is False


@pytest.mark.asyncio
async def test_cache_max_payload_bytes_skipped() -> None:
    c = _make_chunk()
    mock_redis = AsyncMock()
    # Set limit very low (e.g. 50 bytes)
    cache = RetrievalResultCache(redis_client=mock_redis, enabled=True, max_payload_bytes=50)

    ok = await cache.set("key", [c])
    assert ok is False
    assert not mock_redis.set.called


@pytest.mark.asyncio
async def test_stampede_lock_acquire_and_release() -> None:
    mock_redis = AsyncMock()
    cache = RetrievalResultCache(redis_client=mock_redis, enabled=True)

    # Acquire success
    mock_redis.set.return_value = True
    token = await cache.acquire_stampede_lock("lock_key")
    assert token is not None

    # Release with matching token
    mock_redis.get.return_value = token
    released = await cache.release_stampede_lock("lock_key", token)
    assert released is True
    mock_redis.delete.assert_called_once_with("lock:lock_key")

    # Release with wrong token
    mock_redis.get.return_value = "other_token"
    mock_redis.delete.reset_mock()
    released_wrong = await cache.release_stampede_lock("lock_key", "wrong_token")
    assert released_wrong is False
    assert not mock_redis.delete.called
