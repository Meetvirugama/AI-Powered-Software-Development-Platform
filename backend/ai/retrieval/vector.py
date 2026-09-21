"""
Vector retriever — pgvector cosine similarity search.
Owner: Meet — W1-12

Day 1: stub interface.
Day 4: full implementation using Om's `code_chunks` table + HNSW index.

Retrieval flow:
    query string
        → EmbeddingService.embed(query)
        → SELECT ... FROM code_chunks ORDER BY embedding <=> :vec LIMIT top_k
        → list[CodeChunk] with similarity scores
"""

from __future__ import annotations

from uuid import UUID

from .base import CodeChunk, Retriever


class VectorRetriever(Retriever):
    """
    Retrieves code chunks using pgvector cosine similarity.

    Day 4 will inject:
        - AsyncSession (SQLAlchemy) for DB access via Om's repository layer
        - EmbeddingService for query embedding
    """

    async def retrieve(
        self,
        query: str,
        repository_id: UUID,
        top_k: int = 30,
    ) -> list[CodeChunk]:
        """
        Embed the query and run cosine similarity search against pgvector.

        Returns top_k CodeChunks sorted by similarity (highest first).
        Scores are cosine distances converted to similarities: score = 1 - distance.
        """
        # Day 4 implementation:
        #   1. vector = await self._embedding_service.embed(query)
        #   2. rows = await db.execute(
        #          select(CodeChunkModel)
        #          .where(CodeChunkModel.repository_id == repository_id)
        #          .order_by(CodeChunkModel.embedding.cosine_distance(vector))
        #          .limit(top_k)
        #      )
        #   3. return [_row_to_chunk(r) for r in rows]
        raise NotImplementedError("VectorRetriever implemented on Day 4.")
