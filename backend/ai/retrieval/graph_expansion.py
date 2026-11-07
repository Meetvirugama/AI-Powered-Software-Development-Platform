"""
Bounded Symbol-Graph Expansion for Hybrid Retrieval (R06).
Owner: Meet — W1-12

Expands candidate retrieval sets using PostgreSQL symbol graph relationships
(calls, imports, extends, implements) with strict repository isolation,
one-hop bounds, and intent-aware edge selection.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .base import CodeChunk

logger = logging.getLogger(__name__)

__all__ = ["SymbolGraphExpander"]

_DEFAULT_MAX_SEEDS = 5
_DEFAULT_MAX_HOPS = 1
_DEFAULT_MAX_RELATED_PER_SEED = 10
_DEFAULT_MAX_EXPANDED_CHUNKS = 30


class SymbolGraphExpander:
    """
    Expands retrieval candidates along code symbol dependency edges.

    Key guarantees:
    - 1-hop bounded expansion (never executes recursive/unbounded graph queries).
    - Repository isolation (every SQL query strictly filters by repository_id).
    - Intent-directed edge selection (impact analysis vs debugging vs exact symbol).
    - Graceful fallback: database/syntax errors log a warning and return empty results.
    """

    def __init__(
        self,
        db: AsyncSession | async_sessionmaker[AsyncSession] | Any = None,
        max_seeds: int = _DEFAULT_MAX_SEEDS,
        max_hops: int = _DEFAULT_MAX_HOPS,
        max_related_per_seed: int = _DEFAULT_MAX_RELATED_PER_SEED,
        max_expanded_chunks: int = _DEFAULT_MAX_EXPANDED_CHUNKS,
        enabled: bool = True,
    ) -> None:
        self._db = db
        self._max_seeds = max_seeds
        self._max_hops = max_hops
        self._max_related_per_seed = max_related_per_seed
        self._max_expanded_chunks = max_expanded_chunks
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def expand(
        self,
        candidates: list[CodeChunk],
        repository_id: UUID | str,
        intent: str = "conceptual",
    ) -> list[CodeChunk]:
        """
        Identify seed symbols from top candidates and fetch 1-hop related code chunks.

        Args:
            candidates: Initial candidates from Vector and/or Lexical retrieval.
            repository_id: Target repository UUID for strict tenant isolation.
            intent: Query intent string to determine edge selection strategy.

        Returns:
            List of expanded CodeChunk objects (up to max_expanded_chunks),
            or empty list if graph expansion is disabled, inapplicable, or fails.
        """
        if not self._enabled or self._db is None or not candidates:
            return []

        # Graph expansion is not useful for file path lookups
        normalized_intent = str(intent).lower()
        if normalized_intent == "path_lookup":
            return []

        repo_uuid = (
            repository_id
            if isinstance(repository_id, UUID)
            else UUID(str(repository_id))
        )

        try:
            return await self._do_expand(
                candidates=candidates,
                repo_uuid=repo_uuid,
                intent=normalized_intent,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "symbol_graph_expansion_failed",
                extra={
                    "repo_id": str(repo_uuid),
                    "intent": normalized_intent,
                    "error": str(exc),
                },
            )
            return []

    async def _do_expand(
        self,
        candidates: list[CodeChunk],
        repo_uuid: UUID,
        intent: str,
    ) -> list[CodeChunk]:
        # 1. Identify seed symbols from candidates (up to max_seeds)
        seed_symbol_ids: list[UUID] = []
        candidate_chunk_ids = {c.id for c in candidates}

        for c in candidates:
            if c.symbol_id is not None and c.symbol_id not in seed_symbol_ids:
                seed_symbol_ids.append(c.symbol_id)
                if len(seed_symbol_ids) >= self._max_seeds:
                    break

        if not seed_symbol_ids:
            return []

        # 2. Query edges according to query intent
        # Convert UUIDs to strings/UUIDs suitable for SQL binding
        seed_id_strs = [str(sid) for sid in seed_symbol_ids]

        db_obj = self._db
        if hasattr(db_obj, "execute"):
            return await self._query_graph(db_obj, seed_symbol_ids, seed_id_strs, repo_uuid, intent, candidate_chunk_ids)
        else:
            async with db_obj() as session:
                return await self._query_graph(session, seed_symbol_ids, seed_id_strs, repo_uuid, intent, candidate_chunk_ids)

    async def _query_graph(
        self,
        session: Any,
        seed_symbol_ids: list[UUID],
        seed_id_strs: list[str],
        repo_uuid: UUID,
        intent: str,
        candidate_chunk_ids: set[UUID],
    ) -> list[CodeChunk]:
        seed_set = set(seed_symbol_ids)

        # Build intent-specific edge query
        # Strict repository_id check on symbol_edges
        in_params = {f"seed_{i}": sid for i, sid in enumerate(seed_id_strs)}
        in_clause = ", ".join(f":seed_{i}" for i in range(len(seed_id_strs)))

        if intent == "impact_analysis":
            # Incoming edges: who calls, imports, extends, or implements these seed symbols
            edge_sql = text(
                f"""
                SELECT source_symbol_id, target_symbol_id, edge_type
                FROM symbol_edges
                WHERE repository_id = :repo_id
                  AND target_symbol_id IN ({in_clause})
                """
            )
        elif intent == "debugging":
            # Call graph: both callers and callees
            edge_sql = text(
                f"""
                SELECT source_symbol_id, target_symbol_id, edge_type
                FROM symbol_edges
                WHERE repository_id = :repo_id
                  AND edge_type = 'calls'
                  AND (source_symbol_id IN ({in_clause}) OR target_symbol_id IN ({in_clause}))
                """
            )
        elif intent == "test_generation":
            # Callers, callees, and imported symbols
            edge_sql = text(
                f"""
                SELECT source_symbol_id, target_symbol_id, edge_type
                FROM symbol_edges
                WHERE repository_id = :repo_id
                  AND edge_type IN ('calls', 'imports')
                  AND (source_symbol_id IN ({in_clause}) OR target_symbol_id IN ({in_clause}))
                """
            )
        elif intent in ("exact_symbol", "symbol"):
            # Limited call graph
            edge_sql = text(
                f"""
                SELECT source_symbol_id, target_symbol_id, edge_type
                FROM symbol_edges
                WHERE repository_id = :repo_id
                  AND edge_type = 'calls'
                  AND (source_symbol_id IN ({in_clause}) OR target_symbol_id IN ({in_clause}))
                """
            )
        else:
            # Conceptual: general relationships
            edge_sql = text(
                f"""
                SELECT source_symbol_id, target_symbol_id, edge_type
                FROM symbol_edges
                WHERE repository_id = :repo_id
                  AND (source_symbol_id IN ({in_clause}) OR target_symbol_id IN ({in_clause}))
                """
            )

        query_params = {"repo_id": str(repo_uuid), **in_params}
        edge_rows = (await session.execute(edge_sql, query_params)).fetchall()

        # Group related symbols per seed symbol, bounded by max_related_per_seed
        per_seed_neighbors: dict[UUID, list[UUID]] = defaultdict(list)
        all_neighbors: set[UUID] = set()

        for row in edge_rows:
            src = UUID(str(row[0])) if not isinstance(row[0], UUID) else row[0]
            tgt = UUID(str(row[1])) if not isinstance(row[1], UUID) else row[1]

            # Determine which side is the seed and which is neighbor
            if src in seed_set and tgt not in seed_set:
                seed, neighbor = src, tgt
            elif tgt in seed_set and src not in seed_set:
                seed, neighbor = tgt, src
            else:
                continue

            if len(per_seed_neighbors[seed]) < self._max_related_per_seed:
                per_seed_neighbors[seed].append(neighbor)
                all_neighbors.add(neighbor)

        if not all_neighbors:
            return []

        neighbor_strs = [str(nid) for nid in all_neighbors]
        chunk_params = {f"n_{i}": nid for i, nid in enumerate(neighbor_strs)}
        chunk_in_clause = ", ".join(f":n_{i}" for i in range(len(neighbor_strs)))

        chunk_sql = text(
            f"""
            SELECT cc.id, cc.repository_id, cc.file_id, cc.symbol_id,
                   cc.content, cc.token_count, cc.start_line, cc.end_line,
                   cc.content_hash, rf.path AS file_path
            FROM code_chunks cc
            JOIN repository_files rf ON cc.file_id = rf.id
            WHERE cc.repository_id = :repo_id
              AND cc.symbol_id IN ({chunk_in_clause})
            LIMIT :max_expanded
            """
        )
        chunk_query_params = {
            "repo_id": str(repo_uuid),
            "max_expanded": self._max_expanded_chunks,
            **chunk_params,
        }

        chunk_rows = (await session.execute(chunk_sql, chunk_query_params)).fetchall()

        expanded_chunks: list[CodeChunk] = []
        for r in chunk_rows:
            chunk_id = UUID(str(r[0])) if not isinstance(r[0], UUID) else r[0]
            if chunk_id in candidate_chunk_ids:
                continue  # Deduplicate against initial candidates

            expanded_chunks.append(
                CodeChunk(
                    id=chunk_id,
                    repository_id=UUID(str(r[1])) if not isinstance(r[1], UUID) else r[1],
                    file_id=UUID(str(r[2])) if not isinstance(r[2], UUID) else r[2],
                    symbol_id=UUID(str(r[3])) if r[3] and not isinstance(r[3], UUID) else r[3],
                    content=str(r[4]),
                    token_count=int(r[5] or 0),
                    start_line=int(r[6] or 1),
                    end_line=int(r[7] or 1),
                    content_hash=str(r[8] or ""),
                    score=0.5,
                    graph_score=0.5,
                    file_path=str(r[9] or ""),
                )
            )

        return expanded_chunks
