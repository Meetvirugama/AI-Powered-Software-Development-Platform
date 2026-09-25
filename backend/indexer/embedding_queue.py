import asyncio
import json
from typing import Any


BATCH_SIZE = 100
MAX_RETRIES = 3
QUEUE_NAME = "embedding_queue"


class EmbeddingQueue:
    """Redis-backed queue for asynchronous chunk embedding."""

    def __init__(self, redis: Any, embedding_service: Any) -> None:
        self.redis = redis
        self.embedding_service = embedding_service

    def enqueue(self, chunk: Any) -> None:
        """Add a chunk to the Redis embedding queue."""
        payload = {
            "chunk_id": str(chunk.id) if hasattr(chunk, "id") else None,
            "content": chunk.content,
        }

        self.redis.rpush(
            QUEUE_NAME,
            json.dumps(payload),
        )

    async def process_batch(self) -> list[list[float]]:
        """Process up to 100 queued chunks."""
        items: list[dict[str, Any]] = []

        for _ in range(BATCH_SIZE):
            raw = self.redis.lpop(QUEUE_NAME)

            if raw is None:
                break

            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")

            items.append(json.loads(raw))

        if not items:
            return []

        texts = [item["content"] for item in items]

        for attempt in range(MAX_RETRIES):
            try:
                return await self.embedding_service.embed_batch(texts)
            except Exception:
                if attempt == MAX_RETRIES - 1:
                    raise

                await asyncio.sleep(2**attempt)

        return []