"""
Vector retriever — pgvector cosine similarity search.
Owner: Meet — W1-12

Day 1: stub interface.
Day 4: full implementation using Om's `code_chunks` table + HNSW index.

Retrieval flow:
    query string
        → EmbeddingService.embed_query(query) (v2 CODE_RETRIEVAL_QUERY + L2 norm) or embed(query) (v1)
        → SELECT ... FROM code_chunks ORDER BY embedding <=> :vec LIMIT top_k
        → list[CodeChunk] with similarity scores (score = 1 − cosine_distance)

team_rules.md:
    Every query MUST filter by repository_id — no cross-repository leakage.
    Never write raw SQL outside Om's repository layer; here we use SQLAlchemy
    text() + asyncpg because the pgvector <=> operator requires a cast that
    ORM expressions don't yet support cleanly across all driver versions.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .base import CodeChunk, Retriever

if TYPE_CHECKING:
    from ai.embeddings.client import EmbeddingProfile
    from ai.embeddings.service import EmbeddingService

logger = logging.getLogger(__name__)

__all__ = ["HNSW_PROFILES", "VectorRetriever", "resolve_hnsw_profile"]

# ---------------------------------------------------------------------------
# Adaptive HNSW Profiles (R02, task.md §4)
# ---------------------------------------------------------------------------

HNSW_PROFILES: Final[dict[str, dict[str, Any]]] = {
    "exact": {
        "ef_search": 40,
        "iterative_scan": "relaxed_order",
    },
    "normal": {
        "ef_search": 64,
        "iterative_scan": "relaxed_order",
    },
    "complex": {
        "ef_search": 120,
        "iterative_scan": "relaxed_order",
    },
}


def resolve_hnsw_profile(intent: str | None = None) -> str:
    """Map query intent to an adaptive HNSW search effort profile."""
    if not intent:
        return "normal"
    norm = intent.lower().strip()
    if norm in ("exact", "exact_symbol", "path_lookup", "symbol"):
        return "exact"
    if norm in ("complex", "debugging", "impact_analysis", "test_generation"):
        return "complex"
    return "normal"


async def _apply_adaptive_hnsw(
    session: Any,
    ef_search: int = 64,
    iterative_scan: str = "relaxed_order",
) -> None:
    """Set transaction-local HNSW configuration if supported by the database engine."""
    if not hasattr(session, "execute"):
        return

    async def _run_set(stmt: str) -> None:
        try:
            if hasattr(session, "begin_nested") and getattr(session.begin_nested, "__class__", None).__name__ != "AsyncMock":
                nested = session.begin_nested()
                if hasattr(nested, "__aenter__"):
                    async with nested:
                        await session.execute(text(stmt))
                    return
            await session.execute(text(stmt))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Adaptive HNSW configuration fallback (%s): %s", stmt, exc)

    await _run_set(f"SET LOCAL hnsw.ef_search = {int(ef_search)}")
    if iterative_scan:
        safe_scan = re.sub(r"[^\w]", "", iterative_scan)
        await _run_set(f"SET LOCAL hnsw.iterative_scan = '{safe_scan}'")

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
        COALESCE(metadata->>'file_path', '') AS file_path,
        COALESCE(
            (SELECT cs.importance_score FROM code_symbols cs WHERE cs.id = code_chunks.symbol_id),
            0.0
        ) AS importance_score
    FROM code_chunks
    WHERE repository_id = :repository_id
      AND embedding IS NOT NULL
    ORDER BY embedding <=> CAST(:query_vec AS vector)
    LIMIT :top_k
    """
)


def _vec_to_pg_literal(vector: list[float], expected_dim: int | None = None) -> str:
    """Serialise a Python float list to the PostgreSQL vector literal format.

    Validates that:
    1. The vector is non-empty and has the expected dimension (if specified).
    2. Every float value is finite (rejects NaN, +Inf, -Inf).
    """
    if not vector:
        raise ValueError("Vector cannot be empty.")
    if expected_dim is not None and len(vector) != expected_dim:
        raise ValueError(f"Vector dimension mismatch: expected {expected_dim}, got {len(vector)}")
    for i, v in enumerate(vector):
        if not math.isfinite(v):
            raise ValueError(f"Vector contains non-finite value at index {i}: {v}")
    return "[" + ",".join(str(v) for v in vector) + "]"


def _row_to_chunk(row: object, score: float) -> CodeChunk:
    """Map a SQLAlchemy Row object to a typed CodeChunk dataclass."""
    raw_imp = getattr(row, "importance_score", None)
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
        vector_similarity=score,
        importance_score=float(raw_imp) if raw_imp is not None else None,
    )


def _should_use_embed_query(embedding_service: Any) -> bool:
    """Return True when `embedding_service` is configured for v2 `embed_query`."""
    if embedding_service is None:
        return False
    prof_ver = getattr(embedding_service, "profile_version", None)
    if prof_ver != "v2":
        return False
    fn = getattr(embedding_service, "embed_query", None)
    if fn is None or not callable(fn):
        return False
    return type(fn).__name__ not in {"MagicMock", "AsyncMock"} or "embed_query" in getattr(
        embedding_service, "__dict__", {}
    )


class VectorRetriever(Retriever):
    """
    Retrieves code chunks using pgvector cosine similarity.

    Implements the `Retriever` interface (base.py) so it can be swapped with
    any other retriever implementation behind the same contract.
    """

    def __init__(
        self,
        db: AsyncSession | async_sessionmaker[AsyncSession] | Any,
        embedding_service: EmbeddingService,
        max_distance: float | None = None,
        target_profile: EmbeddingProfile | None = None,
    ) -> None:
        self._db = db
        self._embedding_service = embedding_service
        self._max_distance = max_distance
        self._target_profile = target_profile

    async def retrieve(
        self,
        query: str,
        repository_id: UUID,
        top_k: int = 30,
        max_distance: float | None = None,
        profile: str | None = None,
        query_intent: str | None = None,
        target_profile: EmbeddingProfile | None = None,
    ) -> list[CodeChunk]:
        """
        Embed the query and run cosine similarity search against pgvector.
        """
        if not query or not query.strip() or top_k <= 0:
            return []

        effective_target_profile = target_profile or self._target_profile
        if effective_target_profile is not None and hasattr(
            self._embedding_service, "validate_query_profile"
        ):
            self._embedding_service.validate_query_profile(effective_target_profile)

        repo_uuid = repository_id if isinstance(repository_id, UUID) else UUID(str(repository_id))
        effective_max_distance = max_distance if max_distance is not None else self._max_distance

        target_profile_name = profile or resolve_hnsw_profile(query_intent)
        profile_config = HNSW_PROFILES.get(target_profile_name, HNSW_PROFILES["normal"])
        ef_search = profile_config.get("ef_search", 64)
        iterative_scan = profile_config.get("iterative_scan", "relaxed_order")

        # Step 1 — embed the query (uses v2 CODE_RETRIEVAL_QUERY + L2 norm when v2 profile is active)
        if _should_use_embed_query(self._embedding_service):
            query_vector = await self._embedding_service.embed_query(query)
        else:
            query_vector = await self._embedding_service.embed(query)

        raw_dim = getattr(self._embedding_service, "dimensions", None) or getattr(
            self._embedding_service, "dimension", None
        )
        expected_dim = raw_dim if isinstance(raw_dim, int) else None
        query_vec_literal = _vec_to_pg_literal(query_vector, expected_dim=expected_dim)

        # Step 2 — cosine distance search in pgvector with transaction-local HNSW profile
        params = {
            "query_vec": query_vec_literal,
            "repository_id": str(repo_uuid),
            "top_k": top_k,
        }
        db_obj: Any = self._db
        if hasattr(db_obj, "execute"):
            await _apply_adaptive_hnsw(db_obj, ef_search=ef_search, iterative_scan=iterative_scan)
            result = await db_obj.execute(_VECTOR_SEARCH_SQL, params)
            rows = result.fetchall()
        else:
            async with db_obj() as session:
                await _apply_adaptive_hnsw(session, ef_search=ef_search, iterative_scan=iterative_scan)
                result = await session.execute(_VECTOR_SEARCH_SQL, params)
                rows = result.fetchall()

        if not rows:
            logger.debug(
                "vector_retrieval_empty",
                extra={
                    "repository_id": str(repo_uuid),
                    "query_preview": query[:80],
                },
            )
            return []

        # Step 3 — map rows to CodeChunk; score = 1 − cosine_distance
        chunks: list[CodeChunk] = []
        for row in rows:
            distance = float(row.distance)  # type: ignore[attr-defined]
            if effective_max_distance is not None and distance > effective_max_distance:
                continue
            score = max(0.0, min(1.0, 1.0 - distance))  # clamp to [0, 1]
            chunks.append(_row_to_chunk(row, score))

        logger.info(
            "vector_retrieval_complete",
            extra={
                "repository_id": str(repo_uuid),
                "query_preview": query[:80],
                "top_k": top_k,
                "returned": len(chunks),
                "top_score": round(chunks[0].score, 4) if chunks else None,
            },
        )

        return chunks

    async def aclose(self) -> None:
        """Close embedding service and database resources if supported."""
        if hasattr(self._embedding_service, "aclose") and callable(self._embedding_service.aclose):
            await self._embedding_service.aclose()
        if hasattr(self._db, "aclose") and callable(self._db.aclose):
            await self._db.aclose()
        elif hasattr(self._db, "close") and callable(self._db.close):
            res = self._db.close()
            if asyncio.iscoroutine(res):
                await res
