"""
Vector retriever — pgvector cosine similarity search.
Owner: Meet — W1-12

Day 1: stub interface.
Day 4: full implementation using Om's `code_chunks` table + HNSW index.

Retrieval flow:
    query string
        → EmbeddingService.embed(query)
        → SELECT ... FROM code_chunks ORDER BY embedding <=> :vec LIMIT top_k
        → list[CodeChunk] with similarity scores (score = 1 − cosine_distance)

team_rules.md:
    Every query MUST filter by repository_id — no cross-repository leakage.
    Never write raw SQL outside Om's repository layer; here we use SQLAlchemy
    text() + asyncpg because the pgvector <=> operator requires a cast that
    ORM expressions don't yet support cleanly across all driver versions.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .base import CodeChunk, Retriever

if TYPE_CHECKING:
    from ai.embeddings.service import EmbeddingService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQL — pgvector cosine distance operator (<=>)
# We compute similarity as  1 − distance  so higher = more relevant.
# The HNSW index on code_chunks.embedding is used automatically.
# ---------------------------------------------------------------------------

_VECTOR_SEARCH_SQL = text(
    """
    SELECT
        id,
        repository_id,
        file_id,
        symbol_id,
        content,
        token_count,
        start_line,
        end_line,
        content_hash,
        (embedding <=> CAST(:query_vec AS vector)) AS distance,
        COALESCE(metadata->>'file_path', '') AS file_path
    FROM code_chunks
    WHERE repository_id = :repository_id
      AND embedding IS NOT NULL
    ORDER BY embedding <=> CAST(:query_vec AS vector)
    LIMIT :top_k
    """
)


def _vec_to_pg_literal(vector: list[float]) -> str:
    """
    Serialise a Python float list to the PostgreSQL vector literal format.
    e.g. [0.1, 0.2, 0.3] → '[0.1,0.2,0.3]'
    pgvector accepts this format when the value is cast to vector.
    """
    return "[" + ",".join(str(v) for v in vector) + "]"


def _row_to_chunk(row: object, score: float) -> CodeChunk:
    """Map a SQLAlchemy Row object to a typed CodeChunk dataclass."""
    return CodeChunk(
        id=row.id,  # type: ignore[attr-defined]
        repository_id=row.repository_id,  # type: ignore[attr-defined]
        file_id=row.file_id,  # type: ignore[attr-defined]
        symbol_id=row.symbol_id,  # type: ignore[attr-defined]
        content=row.content,  # type: ignore[attr-defined]
        token_count=row.token_count,  # type: ignore[attr-defined]
        start_line=row.start_line,  # type: ignore[attr-defined]
        end_line=row.end_line,  # type: ignore[attr-defined]
        content_hash=row.content_hash,  # type: ignore[attr-defined]
        score=score,
        file_path=row.file_path or "",  # type: ignore[attr-defined]
    )


class VectorRetriever(Retriever):
    """
    Retrieves code chunks using pgvector cosine similarity.

    Implements the `Retriever` interface (base.py) so it can be swapped with
    any other retriever implementation behind the same contract.

    Args:
        db:                 SQLAlchemy AsyncSession — injected by the caller.
                            Must be scoped to the current request / task.
        embedding_service:  EmbeddingService — used to embed the query string.
                            Injected to keep this class testable without a real API.

    Example::

        retriever = VectorRetriever(db=session, embedding_service=svc)
        chunks = await retriever.retrieve(
            query="where is authentication handled?",
            repository_id=repo_id,
            top_k=30,
        )
    """

    def __init__(
        self,
        db: AsyncSession,
        embedding_service: "EmbeddingService",
    ) -> None:
        self._db = db
        self._embedding_service = embedding_service

    async def retrieve(
        self,
        query: str,
        repository_id: UUID,
        top_k: int = 30,
    ) -> list[CodeChunk]:
        """
        Embed the query and run cosine similarity search against pgvector.

        Steps:
        1. Embed `query` using EmbeddingService (retries handled inside service).
        2. Execute SQL with pgvector `<=>` cosine distance operator.
        3. Convert each row to a typed `CodeChunk`; score = 1 − distance.

        Args:
            query:         Natural-language or code query string.
            repository_id: Scope results to this repository only.
                           Enforced at SQL level — no cross-repo leakage.
            top_k:         Maximum number of chunks to return (default 30 for RRF).

        Returns:
            List of `CodeChunk` sorted by descending similarity score (best first).
            Returns an empty list if the repository has no indexed chunks.

        Raises:
            EmbeddingError: If the embedding service fails after retries.
            SQLAlchemyError: If the database is unreachable.
        """
        # Step 1 — embed the query
        query_vector: list[float] = await self._embedding_service.embed(query)
        query_vec_literal = _vec_to_pg_literal(query_vector)

        # Step 2 — cosine distance search in pgvector
        result = await self._db.execute(
            _VECTOR_SEARCH_SQL,
            {
                "query_vec": query_vec_literal,
                "repository_id": str(repository_id),
                "top_k": top_k,
            },
        )
        rows = result.fetchall()

        if not rows:
            logger.debug(
                "vector_retrieval_empty",
                extra={
                    "repository_id": str(repository_id),
                    "query_preview": query[:80],
                },
            )
            return []

        # Step 3 — map rows to CodeChunk; score = 1 − cosine_distance
        chunks: list[CodeChunk] = []
        for row in rows:
            distance = float(row.distance)  # type: ignore[attr-defined]
            score = max(0.0, 1.0 - distance)  # clamp to [0, 1]
            chunks.append(_row_to_chunk(row, score))

        logger.info(
            "vector_retrieval_complete",
            extra={
                "repository_id": str(repository_id),
                "query_preview": query[:80],
                "top_k": top_k,
                "returned": len(chunks),
                "top_score": round(chunks[0].score, 4) if chunks else None,
            },
        )

        return chunks
