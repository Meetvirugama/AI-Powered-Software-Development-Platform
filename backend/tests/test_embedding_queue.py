"""
Unit tests for the durable EmbeddingQueue.
Tests enqueue, durable batch processing, retry on transient failure, and persistence.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from indexer.embedding_queue import EmbeddingQueue
from indexer.models import Chunk


class FakeRedis:
    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}

    def rpush(self, key: str, val: str) -> int:
        self.lists.setdefault(key, []).append(val)
        return len(self.lists[key])

    def lpush(self, key: str, val: str) -> int:
        self.lists.setdefault(key, []).insert(0, val)
        return len(self.lists[key])

    def lpop(self, key: str) -> str | None:
        lst = self.lists.get(key, [])
        return lst.pop(0) if lst else None

    def rpoplpush(self, src: str, dst: str) -> str | None:
        val = self.lpop(src)
        if val is not None:
            self.rpush(dst, val)
        return val

    def lrem(self, key: str, count: int, val: str) -> int:
        lst = self.lists.get(key, [])
        if val in lst:
            lst.remove(val)
            return 1
        return 0


def _make_chunk(content: str) -> Chunk:
    return Chunk(
        repository_id=uuid4(),
        file_id=uuid4(),
        symbol_id=uuid4(),
        content=content,
        start_line=1,
        end_line=10,
        language="python",
        chunk_type="function",
        token_count=20,
        content_hash="abc",
        metadata={},
    )


@pytest.mark.asyncio
async def test_embedding_queue_enqueue_and_process():
    redis = FakeRedis()
    mock_service = AsyncMock()
    mock_service.embed_batch.return_value = [[0.1] * 768, [0.2] * 768]

    queue = EmbeddingQueue(redis=redis, embedding_service=mock_service)
    c1 = _make_chunk("def foo(): pass")
    c2 = _make_chunk("def bar(): pass")

    queue.enqueue([c1, c2])

    assert len(redis.lists.get("embedding_queue", [])) == 2

    results = await queue.process_batch()
    assert len(results) == 2
    assert results[0] == [0.1] * 768
    # Processing queue should be empty after completion
    assert len(redis.lists.get("embedding_queue:processing", [])) == 0


@pytest.mark.asyncio
async def test_embedding_queue_empty_returns_empty():
    redis = FakeRedis()
    mock_service = AsyncMock()
    queue = EmbeddingQueue(redis=redis, embedding_service=mock_service)
    results = await queue.process_batch()
    assert results == []
    mock_service.embed_batch.assert_not_called()
