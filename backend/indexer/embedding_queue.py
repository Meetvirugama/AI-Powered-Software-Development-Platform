from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from uuid import UUID

from app.models.code_chunk import CodeChunk
from .models import Chunk

logger = logging.getLogger(__name__)

BATCH_SIZE = 100
MAX_RETRIES = 3
QUEUE_NAME = "embedding_queue"
PROCESSING_QUEUE = "embedding_queue:processing"


class EmbeddingQueue:
    """Durable Redis-backed queue for asynchronous chunk embedding and persistence."""

    def __init__(self, redis: Any, embedding_service: Any) -> None:
        self.redis = redis
        self.embedding_service = embedding_service

    def enqueue(self, chunks: list[Chunk]) -> None:
        """Add chunks to the Redis embedding queue."""
        for chunk in chunks:
            chunk_id = str(getattr(chunk, "id", None) or getattr(chunk, "chunk_id", ""))
            payload = {
                "chunk_id": chunk_id,
                "repository_id": str(getattr(chunk, "repository_id", "")),
                "file_id": str(getattr(chunk, "file_id", "")),
                "content": chunk.content,
            }
            self.redis.rpush(QUEUE_NAME, json.dumps(payload))

    async def process_batch(self, db_session: Any = None) -> list[list[float]]:
        """Durably process up to BATCH_SIZE queued chunks and persist vectors.
        
        Only acknowledges (removes from PROCESSING_QUEUE) after embedding generation
        AND database persistence successfully commit.
        """
        raw_items: list[str] = []
        items: list[dict[str, Any]] = []

        for _ in range(BATCH_SIZE):
            # Atomically move from queue to processing to prevent data loss
            if hasattr(self.redis, "rpoplpush"):
                raw = self.redis.rpoplpush(QUEUE_NAME, PROCESSING_QUEUE)
            else:
                raw = self.redis.lpop(QUEUE_NAME)
                if raw is not None:
                    self.redis.rpush(PROCESSING_QUEUE, raw)

            if raw is None:
                break

            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")

            raw_items.append(raw)
            items.append(json.loads(raw))

        if not items:
            return []

        texts = [item["content"] for item in items]
        embeddings: list[list[float]] = []

        for attempt in range(MAX_RETRIES):
            try:
                embeddings = await self.embedding_service.embed_batch(texts)
                # Validate batch count integrity
                if len(embeddings) != len(items):
                    raise ValueError(
                        f"Embedding batch count mismatch: expected {len(items)}, got {len(embeddings)}"
                    )
                break
            except Exception as exc:
                if attempt == MAX_RETRIES - 1:
                    logger.error("embedding_queue_batch_failed", extra={"error": str(exc), "count": len(items)})
                    # Push items back to head of queue on permanent failure
                    for raw in reversed(raw_items):
                        self.redis.lpush(QUEUE_NAME, raw)
                        self.redis.lrem(PROCESSING_QUEUE, 1, raw)
                    raise
                await asyncio.sleep(2**attempt)

        # If db_session provided, persist vectors into CodeChunk
        if db_session:
            try:
                for item, vector in zip(items, embeddings):
                    chunk_id = item.get("chunk_id")
                    if chunk_id:
                        try:
                            cid = UUID(chunk_id)
                            row = db_session.get(CodeChunk, cid)
                            if row:
                                row.embedding = vector
                        except (ValueError, TypeError):
                            pass
                db_session.commit()
            except Exception as exc:
                logger.error("persist_embeddings_failed", extra={"error": str(exc)})
                if hasattr(db_session, "rollback"):
                    db_session.rollback()
                # Re-queue items back to main queue on DB persistence failure so work is not lost
                for raw in reversed(raw_items):
                    self.redis.lpush(QUEUE_NAME, raw)
                    self.redis.lrem(PROCESSING_QUEUE, 1, raw)
                raise RuntimeError(f"Database persistence failed: {exc}") from exc

        # ONLY acknowledge and clear processed items from PROCESSING_QUEUE on success
        for raw in raw_items:
            self.redis.lrem(PROCESSING_QUEUE, 1, raw)

        return embeddings

    def recover_stale_processing(self) -> int:
        """Recover unacknowledged items from PROCESSING_QUEUE back to QUEUE_NAME."""
        recovered = 0
        while True:
            raw = self.redis.rpoplpush(PROCESSING_QUEUE, QUEUE_NAME) if hasattr(self.redis, "rpoplpush") else self.redis.lpop(PROCESSING_QUEUE)
            if raw is None:
                break
            if not hasattr(self.redis, "rpoplpush"):
                self.redis.rpush(QUEUE_NAME, raw)
            recovered += 1
        return recovered