"""
Incremental Indexer — Hash-based change detection, symbol persistence, chunking, secret redaction, and embedding.

Responsibilities:
- Detects new and modified files using SHA-256 content hashes.
- Normalizes file paths to POSIX forward slashes.
- Inserts/updates `repository_files` with mandatory `size_bytes`, `line_count`, `language`, and `content_hash`.
- Persists extracted `CodeSymbol` rows into `code_symbols` BEFORE inserting `code_chunks`
  so foreign-key references (`code_chunks.symbol_id -> code_symbols.id`) and symbol queries succeed.
- Splits modified files using `SymbolChunker` into syntax-aware or block-level chunks.
- Redacts secrets (`[REDACTED]`) from chunk content before embedding and storing in `code_chunks` (W2-S1).
- Embeds all generated code chunks via `EmbeddingService` with real 768-dimensional vectors.
- Persists chunks with pgvector embeddings and JSON metadata.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import os
import uuid
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.core.secret_redaction import redact
from indexer.chunker import SymbolChunker
from scanner.detector import LanguageDetector
from scanner.extractor import SymbolExtractor
from scanner.graph import DependencyGraphBuilder

logger = logging.getLogger(__name__)


def compute_content_hash(content: str) -> str:
    """Return the SHA-256 hash of file content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def should_reindex(
    content: str,
    existing_hash: str | None,
) -> bool:
    """Return True when a file is new or its content has changed."""
    if existing_hash is None:
        return True
    return compute_content_hash(content) != existing_hash


def _vec_to_pg_literal(vector: list[float]) -> str:
    """Format Python float list as PostgreSQL vector literal."""
    return "[" + ",".join(str(v) for v in vector) + "]"


class IncrementalIndexer:
    """
    Orchestrates repository incremental indexing:
    detection → parsing → symbol persistence → symbol chunking → secret redaction → embedding → vector storage.
    """

    def __init__(
        self,
        db_session: Any,
        chunker: SymbolChunker | None = None,
        embedding_service: Any = None,
        extractor: SymbolExtractor | None = None,
    ) -> None:
        self._db = db_session
        self.chunker = chunker or SymbolChunker()
        self.embedding_service = embedding_service
        self.detector = LanguageDetector()
        self.extractor = extractor or SymbolExtractor()

    def _is_sqlite(self) -> bool:
        bind = getattr(self._db, "bind", None)
        dialect = getattr(bind, "dialect", None)
        return getattr(dialect, "name", "") == "sqlite"

    async def _execute(self, stmt: Any, params: dict[str, Any] | None = None) -> Any:
        """Helper to run SQL across AsyncSession, sync Session, or sessionmaker."""
        bound_params = dict(params or {})
        if self._is_sqlite():
            for k, v in list(bound_params.items()):
                if isinstance(v, UUID):
                    bound_params[k] = v.hex
            sql_txt = str(stmt)
            if "CAST(:embedding AS vector)" in sql_txt or "CAST(:metadata AS jsonb)" in sql_txt:
                sql_txt = sql_txt.replace("CAST(:embedding AS vector)", ":embedding").replace(
                    "CAST(:metadata AS jsonb)", ":metadata"
                )
                stmt = text(sql_txt)
                if bound_params.get("embedding") is None:
                    bound_params["embedding"] = json.dumps([0.0] * 768)

        if hasattr(self._db, "execute"):
            if inspect.iscoroutinefunction(self._db.execute):
                return await self._db.execute(stmt, bound_params)
            return self._db.execute(stmt, bound_params)
        else:
            async with self._db() as session:
                res = await session.execute(stmt, bound_params)
                await session.commit()
                return res

    async def _commit(self) -> None:
        """Helper to commit transactions."""
        if hasattr(self._db, "commit"):
            if inspect.iscoroutinefunction(self._db.commit):
                await self._db.commit()
            else:
                self._db.commit()

    async def sync(
        self,
        repository_id: UUID,
        scanned_files: list[Any],
        root_path: str = "",
    ) -> dict[str, int]:
        """
        Incrementally index scanned repository files.

        1. Fetch existing (path, content_hash) pairs from repository_files.
        2. Compare with newly scanned files.
        3. Skip unchanged files (hash match).
        4. For changed/new files: delete old chunks & symbols, insert symbols, chunk symbols, redact secrets, embed, insert chunks.
        """
        logger.info(
            "Starting incremental sync for repo %s with %d files",
            repository_id,
            len(scanned_files),
        )

        # 1. Fetch existing hashes from DB
        query = text(
            "SELECT path, content_hash, id FROM repository_files WHERE repository_id = :repo_id"
        )
        result = await self._execute(query, {"repo_id": repository_id})
        rows = result.fetchall() if hasattr(result, "fetchall") else []

        existing_files: dict[str, dict[str, Any]] = {
            row.path: {
                "hash": row.content_hash,
                "file_id": UUID(str(row.id)) if row.id and not isinstance(row.id, UUID) else row.id,
            }
            for row in rows
        }

        indexed_count = 0
        skipped_count = 0
        all_extracted_symbols: list[Any] = []
        file_contents_by_id: dict[UUID, str] = {}

        for file_info in scanned_files:
            raw_rel_path = getattr(file_info, "path", str(file_info))
            file_rel_path = raw_rel_path.replace("\\", "/")
            full_path = (
                os.path.join(root_path, file_rel_path)
                if root_path and not os.path.isabs(file_rel_path)
                else file_rel_path
            )

            try:
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except Exception as e:
                logger.error("Could not read %s: %s", full_path, e)
                continue

            if not content.strip():
                continue

            new_hash = compute_content_hash(content)
            file_data = existing_files.get(file_rel_path, {})
            old_hash = file_data.get("hash")
            file_id = file_data.get("file_id")

            # 2 & 3. Compare hashes -> Skip unchanged
            if old_hash == new_hash:
                skipped_count += 1
                continue

            # 4. Changed or new
            size_bytes = len(content.encode("utf-8"))
            line_count = max(1, len(content.splitlines()))
            language = getattr(file_info, "language", None)
            if not language or language == "unknown":
                language = self.detector.detect(file_info)

            logger.info("Indexing changed/new file: %s (%s)", file_rel_path, language)

            if file_id:
                # Delete old chunks and old symbols for this file before re-inserting
                await self._execute(
                    text("DELETE FROM code_chunks WHERE repository_id = :repo_id AND file_id = :file_id"),
                    {"repo_id": repository_id, "file_id": file_id},
                )
                await self._execute(
                    text(
                        "DELETE FROM symbol_edges WHERE repository_id = :repo_id "
                        "AND (source_symbol_id IN (SELECT id FROM code_symbols WHERE repository_id = :repo_id AND file_id = :file_id) "
                        "OR target_symbol_id IN (SELECT id FROM code_symbols WHERE repository_id = :repo_id AND file_id = :file_id))"
                    ),
                    {"repo_id": repository_id, "file_id": file_id},
                )
                await self._execute(
                    text("DELETE FROM code_symbols WHERE repository_id = :repo_id AND file_id = :file_id"),
                    {"repo_id": repository_id, "file_id": file_id},
                )

                # Update the record in repository_files
                update_query = text(
                    """
                    UPDATE repository_files 
                    SET content_hash = :hash,
                        size_bytes = :size_bytes,
                        line_count = :line_count,
                        language = :language,
                        last_indexed_at = CURRENT_TIMESTAMP
                    WHERE id = :file_id
                    """
                )
                await self._execute(
                    update_query,
                    {
                        "hash": new_hash,
                        "size_bytes": size_bytes,
                        "line_count": line_count,
                        "language": language,
                        "file_id": file_id,
                    },
                )
            else:
                file_id = uuid.uuid4()
                insert_query = text(
                    """
                    INSERT INTO repository_files (id, repository_id, path, language, size_bytes, line_count, content_hash, last_indexed_at)
                    VALUES (:id, :repo_id, :path, :language, :size_bytes, :line_count, :hash, CURRENT_TIMESTAMP)
                    """
                )
                await self._execute(
                    insert_query,
                    {
                        "id": file_id,
                        "repo_id": repository_id,
                        "path": file_rel_path,
                        "language": language,
                        "size_bytes": size_bytes,
                        "line_count": line_count,
                        "hash": new_hash,
                    },
                )

            # Extract symbols if language is supported and persist them to code_symbols
            symbols = []
            try:
                if hasattr(file_info, "language"):
                    file_info.language = language
                symbols = self.extractor.extract(file_info, content, file_id=file_id)
            except Exception as e:
                logger.debug("Symbol extraction skipped for %s: %s", file_rel_path, e)

            persisted_symbol_ids: set[UUID] = set()
            if symbols:
                symbol_insert_query = text(
                    """
                    INSERT INTO code_symbols
                    (id, file_id, repository_id, name, kind, start_line, end_line, signature, parent_id)
                    VALUES (:id, :file_id, :repo_id, :name, :kind, :start_line, :end_line, :signature, :parent_id)
                    """
                )
                for sym in symbols:
                    sym_uuid = sym.id if isinstance(sym.id, UUID) else uuid.uuid4()
                    sym.id = sym_uuid
                    parent_uuid = sym.parent_id if sym.parent_id in persisted_symbol_ids else None
                    try:
                        await self._execute(
                            symbol_insert_query,
                            {
                                "id": sym_uuid,
                                "file_id": file_id,
                                "repo_id": repository_id,
                                "name": (sym.name or "anonymous")[:255],
                                "kind": (sym.kind or "symbol")[:50],
                                "start_line": max(1, int(sym.start_line or 1)),
                                "end_line": max(1, int(sym.end_line or sym.start_line or 1)),
                                "signature": redact(sym.signature) if sym.signature else None,
                                "parent_id": parent_uuid,
                            },
                        )
                        persisted_symbol_ids.add(sym_uuid)
                        all_extracted_symbols.append(sym)
                        file_contents_by_id[file_id] = content
                    except Exception as sym_exc:
                        logger.debug("Symbol persistence skipped for %s in %s: %s", sym.name, file_rel_path, sym_exc)

            # Chunk the file using SymbolChunker (symbol-aware or fallback line blocks)
            chunks = self.chunker.chunk_symbols(
                repository_id=repository_id,
                file_id=file_id,
                symbols=symbols,
                content=content,
                language=language,
            )

            if not chunks:
                continue

            # Security (W2-S1): Guarantee all chunk contents are redacted before embedding & DB storage
            for c in chunks:
                c.content = redact(c.content)

            # Embed the chunks
            chunk_texts = [c.content for c in chunks]
            vectors: list[list[float]] = []

            if self.embedding_service is not None:
                try:
                    vectors = await self.embedding_service.embed_batch(chunk_texts)
                except Exception as exc:
                    logger.warning(
                        "Embedding failed for file %s: %s",
                        file_rel_path,
                        exc,
                    )
                    vectors = []

            if self.embedding_service is not None and not vectors:
                logger.warning(
                    "Skipping code_chunks persistence for file %s because embeddings could not be generated.",
                    file_rel_path,
                )
                indexed_count += 1
                await asyncio.sleep(0.05)
                continue

            # Insert chunks into code_chunks
            chunk_query = text(
                """
                INSERT INTO code_chunks 
                (id, repository_id, file_id, symbol_id, content, token_count, embedding, start_line, end_line, content_hash, metadata)
                VALUES (:id, :repo_id, :file_id, :symbol_id, :content, :tokens, CAST(:embedding AS vector), :start, :end, :hash, CAST(:metadata AS jsonb))
                """
            )

            for i, chunk in enumerate(chunks):
                chunk_id = uuid.uuid4()
                vec = vectors[i] if i < len(vectors) else None
                vec_literal = _vec_to_pg_literal(vec) if vec is not None else None
                safe_symbol_id = chunk.symbol_id if chunk.symbol_id in persisted_symbol_ids else None

                metadata = {
                    "file_path": file_rel_path,
                    "language": language,
                    "chunk_type": chunk.chunk_type,
                    "embedding_model": getattr(self.embedding_service, "model_name", "models/gemini-embedding-001"),
                    "embedding_dim": len(vec) if vec is not None else (self.embedding_service.dimensions if self.embedding_service else 768),
                }

                await self._execute(
                    chunk_query,
                    {
                        "id": chunk_id,
                        "repo_id": repository_id,
                        "file_id": file_id,
                        "symbol_id": safe_symbol_id,
                        "content": chunk.content,
                        "tokens": chunk.token_count,
                        "embedding": vec_literal,
                        "start": chunk.start_line,
                        "end": chunk.end_line,
                        "hash": chunk.content_hash,
                        "metadata": json.dumps(metadata),
                    },
                )

            indexed_count += 1
            await asyncio.sleep(0.05)

        if all_extracted_symbols:
            try:
                graph_edges = DependencyGraphBuilder(
                    all_extracted_symbols,
                    file_contents=file_contents_by_id,
                ).build()
                edge_insert_query = text(
                    """
                    INSERT INTO symbol_edges (id, repository_id, source_symbol_id, target_symbol_id, edge_type)
                    VALUES (:id, :repo_id, :source_id, :target_id, :edge_type)
                    """
                )
                for edge in graph_edges:
                    await self._execute(
                        edge_insert_query,
                        {
                            "id": uuid.uuid4(),
                            "repo_id": repository_id,
                            "source_id": edge.source_id,
                            "target_id": edge.target_id,
                            "edge_type": edge.edge_type,
                        },
                    )
            except Exception as edge_exc:
                logger.debug("Symbol edge persistence skipped for repo %s: %s", repository_id, edge_exc)

        await self._commit()
        logger.info(
            "Incremental sync finished for repo %s: indexed=%d, skipped=%d",
            repository_id,
            indexed_count,
            skipped_count,
        )
        return {"indexed": indexed_count, "skipped": skipped_count}
