"""
Lexical retriever — PostgreSQL full-text search.
Owner: Meet — W1-12

Day 1: stub interface.
Day 5: full implementation using PostgreSQL FTS (tsvector / tsquery).

Retrieval flow:
    query string
        → sanitize to tsquery tokens (strip non-alphanumeric, join with &)
        → match against tsvector index on code_chunks.content
        → rank by ts_rank
        → list[CodeChunk] with normalised rank scores [0, 1]
"""

from __future__ import annotations

import logging
import re
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .base import CodeChunk, Retriever

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQL — PostgreSQL full-text search
#
# Combines strict AND matches (boosted 2.0x) with OR fallback matches
# (`regexp_replace(:tsquery, '&', '|', 'g')`) using cover-density ranking
# (`ts_rank_cd`) so multi-word natural-language questions still retrieve
# high-signal code chunks when not every conversational word appears in one chunk.
# ---------------------------------------------------------------------------

_LEXICAL_SEARCH_SQL = text(
    """
    WITH ranked AS (
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
            COALESCE(metadata->>'file_path', '') AS file_path,
            (
                CASE
                    WHEN to_tsvector('english', content) @@ to_tsquery('english', :tsquery)
                    THEN ts_rank_cd(to_tsvector('english', content), to_tsquery('english', :tsquery)) * 2.0
                    ELSE ts_rank_cd(
                        to_tsvector('english', content),
                        to_tsquery('english', regexp_replace(:tsquery, '&', '|', 'g'))
                    )
                END
            ) AS rank
        FROM code_chunks
        WHERE
            repository_id = :repository_id
            AND (
                to_tsvector('english', content) @@ to_tsquery('english', :tsquery)
                OR to_tsvector('english', content) @@ to_tsquery('english', regexp_replace(:tsquery, '&', '|', 'g'))
            )
    ),
    max_rank AS (
        SELECT COALESCE(NULLIF(MAX(rank), 0.0), 1.0) AS max_r FROM ranked
    )
    SELECT
        r.*,
        r.rank / m.max_r AS normalised_rank
    FROM ranked r, max_rank m
    ORDER BY r.rank DESC
    LIMIT :top_k
    """
)


def _sanitize_query(query: str) -> str:
    """
    Convert a natural-language query to a safe PostgreSQL tsquery expression.

    Strategy:
    1. Lower-case and strip everything except alphanumeric + underscores.
    2. Split into tokens, drop empty/single-char tokens (noise words).
    3. Join surviving tokens with the & (AND) tsquery operator.
    4. Fall back to a broad plainto_tsquery-style unquoted string if the
       sanitized token list is empty (caller should check and skip FTS if so).

    Returns:
        A string like ``'authenticate & user & service'`` suitable for passing
        to ``to_tsquery('english', ...)`` inside a parameterised query.

    Raises:
        ValueError: If the query produces zero searchable tokens.
    """
    # Keep letters, digits, underscores — replace everything else with a space
    cleaned = re.sub(r"[^\w\s]", " ", query.lower())

    tokens = [t for t in cleaned.split() if len(t) > 1]

    if not tokens:
        raise ValueError(
            f"Query '{query}' produced no searchable tokens after sanitization. "
            "FTS search skipped."
        )

    return " & ".join(tokens)


def _row_to_chunk(row: object, score: float) -> CodeChunk:
    """Map a SQLAlchemy Row to a typed CodeChunk dataclass."""
    return CodeChunk(
        id=row.id,                          # type: ignore[attr-defined]
        repository_id=row.repository_id,    # type: ignore[attr-defined]
        file_id=row.file_id,                # type: ignore[attr-defined]
        symbol_id=row.symbol_id,            # type: ignore[attr-defined]
        content=row.content,                # type: ignore[attr-defined]
        token_count=row.token_count,        # type: ignore[attr-defined]
        start_line=row.start_line,          # type: ignore[attr-defined]
        end_line=row.end_line,              # type: ignore[attr-defined]
        content_hash=row.content_hash,      # type: ignore[attr-defined]
        score=score,
        file_path=row.file_path or "",      # type: ignore[attr-defined]
        lexical_rank=score,
    )


class LexicalRetriever(Retriever):
    """
    Retrieves code chunks using PostgreSQL full-text search (tsvector / tsquery).

    Scores are ts_rank_cd values normalised to [0, 1] so RRFFusion can
    combine them fairly with vector similarity scores.
    """

    def __init__(self, db: AsyncSession | async_sessionmaker[AsyncSession] | Any) -> None:
        self._db = db

    async def retrieve(
        self,
        query: str,
        repository_id: UUID,
        top_k: int = 30,
    ) -> list[CodeChunk]:
        """Run a full-text search query against the ``code_chunks.content`` tsvector index."""
        if not query or not query.strip() or top_k <= 0:
            return []

        repo_uuid = repository_id if isinstance(repository_id, UUID) else UUID(str(repository_id))

        # Step 1 — sanitize to a valid tsquery expression
        try:
            tsquery = _sanitize_query(query)
        except ValueError as exc:
            logger.warning(
                "lexical_retrieval_skipped",
                extra={
                    "repository_id": str(repo_uuid),
                    "reason": str(exc),
                },
            )
            return []

        # Step 2 — execute FTS query against the GIN index
        params = {
            "tsquery": tsquery,
            "repository_id": str(repo_uuid),
            "top_k": top_k,
        }
        db_obj: Any = self._db
        if hasattr(db_obj, "execute"):
            result = await db_obj.execute(_LEXICAL_SEARCH_SQL, params)
            rows = result.fetchall()
        else:
            async with db_obj() as session:
                result = await session.execute(_LEXICAL_SEARCH_SQL, params)
                rows = result.fetchall()

        if not rows:
            logger.debug(
                "lexical_retrieval_empty",
                extra={
                    "repository_id": str(repo_uuid),
                    "query_preview": query[:80],
                    "tsquery": tsquery,
                },
            )
            return []

        # Step 3 — map rows to CodeChunk using the normalised rank as score
        chunks: list[CodeChunk] = [
            _row_to_chunk(row, max(0.0, min(1.0, float(row.normalised_rank))))  # type: ignore[attr-defined]
            for row in rows
        ]

        logger.info(
            "lexical_retrieval_complete",
            extra={
                "repository_id": str(repo_uuid),
                "query_preview": query[:80],
                "tsquery": tsquery,
                "top_k": top_k,
                "returned": len(chunks),
                "top_score": round(chunks[0].score, 4) if chunks else None,
            },
        )

        return chunks
