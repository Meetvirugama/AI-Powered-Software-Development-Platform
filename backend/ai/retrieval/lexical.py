"""
Lexical retriever — PostgreSQL full-text search.
Owner: Meet — W1-12

Day 1: stub interface.
Day 4 (concurrent with vector.py): implementation using pg FTS.

Retrieval flow:
    query string
        → parse to tsquery tokens
        → match against tsvector index on code_chunks.content
        → rank by ts_rank
        → list[CodeChunk] with normalised rank scores
"""

from __future__ import annotations

from uuid import UUID

from .base import CodeChunk, Retriever


class LexicalRetriever(Retriever):
    """
    Retrieves code chunks using PostgreSQL full-text search (tsvector / tsquery).

    Scores are ts_rank values normalised to [0, 1].
    Both VectorRetriever and LexicalRetriever return top-30 so RRFFusion
    can combine them fairly.
    """

    async def retrieve(
        self,
        query: str,
        repository_id: UUID,
        top_k: int = 30,
    ) -> list[CodeChunk]:
        """
        Run a full-text search query against the `code_chunks.content` tsvector index.

        Returns top_k CodeChunks sorted by ts_rank (highest first).
        """
        # Day 5 implementation:
        #   1. tsquery = to_tsquery('english', sanitize(query))
        #   2. SELECT *, ts_rank(to_tsvector('english', content), tsquery) AS rank
        #      FROM code_chunks
        #      WHERE repository_id = :repo_id
        #        AND to_tsvector('english', content) @@ tsquery
        #      ORDER BY rank DESC LIMIT top_k
        #   3. return [_row_to_chunk(r) for r in rows]
        raise NotImplementedError("LexicalRetriever implemented on Day 5.")
