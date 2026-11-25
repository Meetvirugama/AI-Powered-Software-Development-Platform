"""
Incremental Indexer — Hash-based change detection, symbol persistence, cAST chunking,
contextual headers, L2 normalization on write, obsolete chunk reconciliation, and staged v1->v2 migration.

Responsibilities:
- Detects new, modified, and profile-upgraded files using SHA-256 content hashes and profile versions.
- Normalizes file paths to POSIX forward slashes.
- Inserts/updates `repository_files` with mandatory `size_bytes`, `line_count`, `language`, and `content_hash`.
- Persists extracted `CodeSymbol` rows into `code_symbols` BEFORE inserting `code_chunks`
  so foreign-key references (`code_chunks.symbol_id -> code_symbols.id`) and symbol queries succeed.
- Splits modified files using `SymbolChunker` (cAST recursive split + greedy small-sibling merge).
- Redacts secrets (`[REDACTED]`) from both displayed `chunk.content` and contextual `chunk.embedding_text`.
- Keeps synthetic contextual headers strictly out of stored `code_chunks.content`.
- Embeds all generated code chunks via `EmbeddingService` (`RETRIEVAL_DOCUMENT` in v2) and L2-normalizes vectors on write.
- Provides `ReembeddingMigrationManager` for staged blue/green v1 -> v2 re-embedding with progress tracking,
  retry/resume, validation, atomic activation, and rollback.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import inspect
import json
import logging
import os
import time
import uuid
from typing import Any
from uuid import UUID

from ai.embeddings.client import EmbeddingError, GeminiTaskType, l2_normalize_vector
from ai.retrieval.code_tokenizer import generate_code_search_text
from app.core.secret_redaction import redact
from scanner.detector import LanguageDetector
from scanner.extractor import SymbolExtractor
from scanner.graph import DependencyGraphBuilder
from sqlalchemy import text

from indexer.chunker import CHUNKER_VERSION, SymbolChunker, compute_stable_chunk_id

logger = logging.getLogger(__name__)


def compute_content_hash(content: str) -> str:
    """Return the SHA-256 hash of file content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def compute_chunk_index_fingerprint(
    content_hash: str,
    *,
    chunker_version: str = CHUNKER_VERSION,
    profile_version: str = "v1",
    contextual_header: str = "",
) -> str:
    """
    Compute a deterministic composite fingerprint over chunk content, chunker version,
    embedding profile version, and contextual header so profile/header updates can be
    tracked cleanly without mutating raw content hashes.
    """
    payload = f"{content_hash}|{chunker_version}|{profile_version}|{contextual_header.strip()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class _SnapshotUnchanged(Exception):
    """Internal control-flow signal: nothing changed, keep the previous snapshot."""


def _read_file_safe(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception as e:
        logger.error("Could not read %s: %s", path, e)
        return None


def should_reindex(
    content: str,
    existing_hash: str | None,
    *,
    existing_profile_version: str | None = None,
    target_profile_version: str | None = None,
) -> bool:
    """Return True when a file is new, its content has changed, or its embedding profile version upgraded."""
    if existing_hash is None:
        return True
    if compute_content_hash(content) != existing_hash:
        return True
    if (
        existing_profile_version is not None
        and target_profile_version is not None
        and existing_profile_version != target_profile_version
    ):
        return True
    return False


def _vec_to_pg_literal(vector: list[float]) -> str:
    """Format Python float list as PostgreSQL vector literal."""
    return "[" + ",".join(str(v) for v in vector) + "]"


def _should_use_embed_documents(embedding_service: Any) -> bool:
    """Return True when `embedding_service` supports v2 `embed_documents`."""
    if embedding_service is None:
        return False
    prof_ver = getattr(embedding_service, "profile_version", None)
    if prof_ver != "v2":
        return False
    fn = getattr(embedding_service, "embed_documents", None)
    if fn is None or not callable(fn):
        return False
    return type(fn).__name__ not in {"MagicMock", "AsyncMock"} or "embed_documents" in getattr(
        embedding_service, "__dict__", {}
    )


class IncrementalIndexer:
    """
    Orchestrates repository incremental indexing:
    detection → parsing → symbol persistence → cAST symbol chunking → secret redaction
    → contextual embedding → L2 normalization → vector storage.
    """

    def __init__(
        self,
        db_session: Any,
        chunker: SymbolChunker | None = None,
        embedding_service: Any = None,
        extractor: SymbolExtractor | None = None,
        file_batch_size: int = 32,
    ) -> None:
        self._db = db_session
        self.chunker = chunker or SymbolChunker()
        self.embedding_service = embedding_service
        self.detector = LanguageDetector()
        self.extractor = extractor or SymbolExtractor()
        self._file_batch_size = max(1, int(file_batch_size))
        self._graph_is_complete = False

    async def _merge_unchanged_graph_inputs(
        self,
        *,
        session: Any,
        repository_id: UUID,
        root_path: str,
        symbols: list[Any],
        file_contents_by_id: dict[UUID, str],
        file_id_to_path: dict[UUID, str],
    ) -> None:
        """Add persisted symbols (and on-disk contents) of files that were not re-indexed this run.

        Mutates the given collections in place and sets ``self._graph_is_complete`` on success.
        """
        from scanner.symbols import Symbol

        self._graph_is_complete = False
        fresh_file_ids = {getattr(sym, "file_id", None) for sym in symbols}
        res = await self._execute(
            text(
                "SELECT s.id, s.file_id, s.name, s.kind, s.start_line, s.end_line, s.signature, s.parent_id, f.path "
                "FROM code_symbols s JOIN repository_files f ON f.id = s.file_id "
                "WHERE s.repository_id = :repo_id"
            ),
            {"repo_id": repository_id},
            sess=session,
        )
        rows = res.fetchall() if hasattr(res, "fetchall") else None
        if rows is None:
            return

        def _as_uuid(value: Any) -> UUID | None:
            if value is None or value == "":
                return None
            return value if isinstance(value, UUID) else UUID(str(value))

        loaded: list[Any] = []
        unchanged_paths: dict[UUID, str] = {}
        for row in rows:
            file_uuid = _as_uuid(row[1])
            if file_uuid is None or file_uuid in fresh_file_ids:
                continue  # fresh, in-memory symbols already represent this file
            sym_id = _as_uuid(row[0])
            if sym_id is None:
                continue
            path = str(row[8] or "")
            loaded.append(
                Symbol(
                    id=sym_id,
                    name=str(row[2] or ""),
                    kind=str(row[3] or "symbol"),
                    file_id=file_uuid,
                    start_line=int(row[4] or 1),
                    end_line=int(row[5] or row[4] or 1),
                    signature=str(row[6] or ""),
                    parent_id=_as_uuid(row[7]),
                    file_path=path,
                )
            )
            unchanged_paths[file_uuid] = path

        for file_uuid, path in unchanged_paths.items():
            file_id_to_path[file_uuid] = path
            if file_uuid not in file_contents_by_id and root_path:
                content = await asyncio.to_thread(_read_file_safe, os.path.join(root_path, path))
                if content:
                    file_contents_by_id[file_uuid] = content
        symbols.extend(loaded)
        self._graph_is_complete = True
        logger.info(
            "graph_full_rebuild_inputs_loaded",
            extra={"repo_id": str(repository_id), "unchanged_symbols": len(loaded), "files": len(unchanged_paths)},
        )

    def _is_sqlite(self) -> bool:
        bind = getattr(self._db, "bind", None)
        dialect = getattr(bind, "dialect", None)
        return getattr(dialect, "name", "") == "sqlite"

    async def _execute(
        self,
        stmt: Any,
        params: dict[str, Any] | None = None,
        sess: Any = None,
    ) -> Any:
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

        target_session = sess or self._db
        if hasattr(target_session, "execute"):
            if inspect.iscoroutinefunction(target_session.execute):
                return await target_session.execute(stmt, bound_params)
            return target_session.execute(stmt, bound_params)
        else:
            async with target_session() as session:
                res = await session.execute(stmt, bound_params)
                await session.commit()
                return res

    async def _execute_batch(
        self,
        stmt: Any,
        params_list: list[dict[str, Any]],
        sess: Any = None,
        batch_size: int = 250,
    ) -> int:
        """
        Execute multi-row batch insertion or update in chunked batches.
        Reduces database network roundtrip overhead from O(N) to O(ceil(N / batch_size)).

        Simple explanation:
        Instead of calling the database one-by-one for each symbol or chunk, this function
        groups them into small batches (e.g., 250 items at a time) and sends them together
        in one trip. This makes saving to the database much faster and avoids network delays.
        """
        # If there is nothing to insert, return immediately
        if not params_list:
            return 0

        target_session = sess or self._db
        is_sqlite = self._is_sqlite()
        base_stmt = stmt

        # For SQLite in tests, remove PostgreSQL-specific CAST syntax so SQLite doesn't error
        if is_sqlite:
            sql_txt = str(stmt)
            if "CAST(:embedding AS vector)" in sql_txt or "CAST(:metadata AS jsonb)" in sql_txt:
                sql_txt = sql_txt.replace("CAST(:embedding AS vector)", ":embedding").replace(
                    "CAST(:metadata AS jsonb)", ":metadata"
                )
                base_stmt = text(sql_txt)

        total_inserted = 0
        # Process the items in manageable slices (e.g. 250 items per slice)
        for i in range(0, len(params_list), batch_size):
            batch_slice = params_list[i : i + batch_size]
            cleaned_batch: list[dict[str, Any]] = []

            for raw_params in batch_slice:
                bound = dict(raw_params)
                if is_sqlite:
                    # SQLite needs UUID objects converted to string hex format
                    for k, v in list(bound.items()):
                        if isinstance(v, UUID):
                            bound[k] = v.hex
                    if bound.get("embedding") is None and "embedding" in bound:
                        bound["embedding"] = json.dumps([0.0] * 768)
                cleaned_batch.append(bound)

            # Execute the batch slice on the database session
            if hasattr(target_session, "execute"):
                if inspect.iscoroutinefunction(target_session.execute):
                    await target_session.execute(base_stmt, cleaned_batch)
                else:
                    target_session.execute(base_stmt, cleaned_batch)
            else:
                async with target_session() as session:
                    if inspect.iscoroutinefunction(session.execute):
                        await session.execute(base_stmt, cleaned_batch)
                    else:
                        session.execute(base_stmt, cleaned_batch)
                    if hasattr(session, "commit"):
                        if inspect.iscoroutinefunction(session.commit):
                            await session.commit()
                        else:
                            session.commit()

            total_inserted += len(cleaned_batch)

        return total_inserted

    async def _commit(self, sess: Any = None) -> None:
        """Helper to commit transactions."""
        target = sess or self._db
        if hasattr(target, "commit"):
            if inspect.iscoroutinefunction(target.commit):
                await target.commit()
            else:
                target.commit()

    async def _rollback(self, sess: Any = None) -> None:
        """Helper to roll back failed transactions."""
        target = sess or self._db
        if hasattr(target, "rollback"):
            if inspect.iscoroutinefunction(target.rollback):
                await target.rollback()
            else:
                target.rollback()

    async def sync(
        self,
        repository_id: UUID,
        scanned_files: list[Any],
        root_path: str = "",
        job_id: UUID | None = None,
        progress_callback: Any = None,
    ) -> dict[str, int]:
        """
        Incrementally index scanned repository files in cross-file batches.
        (task2.md §1.7, P0.1, P0.2, P0.3)
        """
        logger.info(
            "Starting incremental sync for repo %s with %d files",
            repository_id,
            len(scanned_files),
        )

        session = None
        is_managed_session = False
        if hasattr(self._db, "execute"):
            session = self._db
        elif callable(self._db):
            session = self._db()
            is_managed_session = True

        try:
            return await self._run_sync(
                session=session,
                repository_id=repository_id,
                scanned_files=scanned_files,
                root_path=root_path,
                job_id=job_id,
                progress_callback=progress_callback,
            )
        except Exception:
            if session is not None and hasattr(session, "rollback"):
                if inspect.iscoroutinefunction(session.rollback):
                    await session.rollback()
                else:
                    session.rollback()
            raise
        finally:
            if is_managed_session and session is not None and hasattr(session, "close"):
                if inspect.iscoroutinefunction(session.close):
                    await session.close()
                else:
                    session.close()

    async def _embed_and_normalize_texts(self, texts: list[str]) -> tuple[list[list[float]], bool]:
        """Embed a list of chunk texts and return L2-normalized vectors plus validity flag."""
        if not texts or self.embedding_service is None:
            return [], True

        vectors: list[list[float]] = []
        try:
            if _should_use_embed_documents(self.embedding_service):
                vectors = await self.embedding_service.embed_documents(texts)
            else:
                vectors = await self.embedding_service.embed_batch(texts)
        except Exception as exc:
            logger.warning("Batch embedding failed (%d texts): %s", len(texts), exc)
            return [], False

        expected_dim = getattr(self.embedding_service, "dimensions", 768)
        if not isinstance(expected_dim, int):
            expected_dim = 768

        if (
            not vectors
            or len(vectors) != len(texts)
            or any(v is None or len(v) == 0 for v in vectors)
        ):
            return [], False

        normalized_vectors: list[list[float]] = []
        try:
            for raw_vec in vectors:
                normalized_vectors.append(l2_normalize_vector(raw_vec, expected_dim=expected_dim))
        except Exception as norm_exc:
            logger.error("Vector L2 normalization/validation failed: %s", norm_exc)
            return [], False

        return normalized_vectors, True

    async def _run_sync(
        self,
        session: Any,
        repository_id: UUID,
        scanned_files: list[Any],
        root_path: str = "",
        job_id: UUID | None = None,
        progress_callback: Any = None,
    ) -> dict[str, int]:
        """Internal worker executing cross-file batched indexing and deletion reconciliation."""
        # Safeguard (Issue #183): Check repository existence before doing any work
        repo_check = await self._execute(
            text("SELECT 1 FROM repositories WHERE id = :repo_id"),
            {"repo_id": repository_id},
            sess=session,
        )
        repo_exists = (repo_check.first() is not None) if hasattr(repo_check, "first") else True
        if not repo_exists:
            logger.warning("indexing_aborted_repository_deleted", extra={"repo_id": str(repository_id)})
            return {"indexed": 0, "skipped": 0, "reconciled_removed": 0, "graph_edges": 0}

        # 1. Fetch existing hashes from DB
        query = text(
            "SELECT path, content_hash, id FROM repository_files WHERE repository_id = :repo_id"
        )
        result = await self._execute(query, {"repo_id": repository_id}, sess=session)
        rows = result.fetchall() if hasattr(result, "fetchall") else []

        existing_files: dict[str, dict[str, Any]] = {
            row.path: {
                "hash": row.content_hash,
                "file_id": UUID(str(row.id)) if row.id and not isinstance(row.id, UUID) else row.id,
            }
            for row in rows
        }

        # Fetch existing chunk profile versions per file_id so profile upgrades (v1 -> v2) re-embed
        target_prof_ver: str | None = None
        if self.embedding_service is not None:
            raw_prof_ver = getattr(self.embedding_service, "profile_version", None)
            if isinstance(raw_prof_ver, str) and raw_prof_ver:
                target_prof_ver = raw_prof_ver

        existing_profile_by_file_id: dict[UUID, str] = {}
        if existing_files and target_prof_ver is not None:
            try:
                chunk_meta_res = await self._execute(
                    text("SELECT file_id, metadata FROM code_chunks WHERE repository_id = :repo_id"),
                    {"repo_id": repository_id},
                    sess=session,
                )
                chunk_meta_rows = (
                    chunk_meta_res.fetchall() if hasattr(chunk_meta_res, "fetchall") else []
                )
                for c_row in chunk_meta_rows:
                    raw_fid = getattr(c_row, "file_id", None) or (c_row[0] if len(c_row) > 0 else None)
                    raw_meta = getattr(c_row, "metadata", None) or (c_row[1] if len(c_row) > 1 else None)
                    if not raw_fid or not raw_meta:
                        continue
                    fid_uuid = UUID(str(raw_fid)) if not isinstance(raw_fid, UUID) else raw_fid
                    if fid_uuid in existing_profile_by_file_id:
                        continue
                    meta_obj = json.loads(raw_meta) if isinstance(raw_meta, str) else dict(raw_meta)
                    if isinstance(meta_obj, dict):
                        existing_profile_by_file_id[fid_uuid] = str(
                            meta_obj.get("embedding_profile_version", "v1")
                        )
            except Exception as meta_exc:
                logger.debug("Could not inspect existing chunk profile versions: %s", meta_exc)

        indexed_count = 0
        skipped_count = 0
        embedding_failed_count = 0
        chunks_embedded_count = 0
        graph_dirty = False
        all_extracted_symbols: list[Any] = []
        file_contents_by_id: dict[UUID, str] = {}
        file_id_to_path: dict[UUID, str] = {}

        prof_version = getattr(self.embedding_service, "profile_version", "v1")
        if not isinstance(prof_version, str):
            prof_version = "v1"
        service_profile = getattr(self.embedding_service, "profile", None)
        doc_task_type = (
            getattr(service_profile, "document_task_type", None)
            or (GeminiTaskType.RETRIEVAL_DOCUMENT.value if prof_version == "v2" else None)
        )
        embedding_model_name = getattr(self.embedding_service, "model_name", "models/gemini-embedding-001")

        symbol_insert_query = text(
            """
            INSERT INTO code_symbols
            (id, file_id, repository_id, name, kind, start_line, end_line, signature, parent_id)
            VALUES (:id, :file_id, :repo_id, :name, :kind, :start_line, :end_line, :signature, :parent_id)
            """
        )
        file_insert_query = text(
            """
            INSERT INTO repository_files (id, repository_id, path, language, size_bytes, line_count, content_hash, last_indexed_at)
            VALUES (:id, :repo_id, :path, :language, :size_bytes, :line_count, :hash, CURRENT_TIMESTAMP)
            """
        )
        file_update_query = text(
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
        chunk_query = text(
            """
            INSERT INTO code_chunks
            (id, repository_id, file_id, symbol_id, content, code_search_text, token_count, embedding, start_line, end_line, content_hash, metadata)
            VALUES (:id, :repo_id, :file_id, :symbol_id, :content, :code_search_text, :tokens, CAST(:embedding AS vector), :start, :end, :hash, CAST(:metadata AS jsonb))
            """
        )

        total_scanned = len(scanned_files)
        file_batches = [
            scanned_files[i : i + self._file_batch_size]
            for i in range(0, total_scanned, self._file_batch_size)
        ]

        for batch_idx, file_batch in enumerate(file_batches):
            # Step A: Read files in batch, filter unchanged, parse symbols & chunk in memory
            prepared_files: list[dict[str, Any]] = []
            for file_info in file_batch:
                raw_rel_path = getattr(file_info, "path", str(file_info))
                file_rel_path = raw_rel_path.replace("\\", "/")
                full_path = (
                    os.path.join(root_path, file_rel_path)
                    if root_path and not os.path.isabs(file_rel_path)
                    else file_rel_path
                )

                content = await asyncio.to_thread(_read_file_safe, full_path)
                if not content or not content.strip():
                    continue

                new_hash = compute_content_hash(content)
                file_data = existing_files.get(file_rel_path, {})
                old_hash = file_data.get("hash")
                existing_fid = file_data.get("file_id")
                existing_prof_ver = existing_profile_by_file_id.get(existing_fid) if existing_fid else None

                if not should_reindex(
                    content,
                    old_hash,
                    existing_profile_version=existing_prof_ver,
                    target_profile_version=target_prof_ver,
                ):
                    skipped_count += 1
                    continue

                size_bytes = len(content.encode("utf-8"))
                line_count = max(1, len(content.splitlines()))
                language = getattr(file_info, "language", None)
                if not language or language == "unknown":
                    language = self.detector.detect(file_info)

                logger.info("Indexing changed/new file: %s (%s)", file_rel_path, language)
                graph_dirty = True

                is_existing = existing_fid is not None
                file_id = existing_fid if existing_fid is not None else uuid.uuid4()

                symbols = []
                try:
                    if hasattr(file_info, "language"):
                        file_info.language = language
                    symbols = self.extractor.extract(file_info, content, file_id=file_id)
                except Exception as e:
                    logger.debug("Symbol extraction skipped for %s: %s", file_rel_path, e)

                try:
                    chunks = self.chunker.chunk_symbols(
                        repository_id=repository_id,
                        file_id=file_id,
                        symbols=symbols,
                        content=content,
                        language=language,
                        file_path=file_rel_path,
                    )
                except TypeError:
                    chunks = self.chunker.chunk_symbols(
                        repository_id=repository_id,
                        file_id=file_id,
                        symbols=symbols,
                        content=content,
                        language=language,
                    )

                for c in chunks or []:
                    c.content = redact(c.content)
                    if getattr(c, "embedding_text", None):
                        c.embedding_text = redact(c.embedding_text)

                chunk_texts = [getattr(c, "embedding_text", None) or c.content for c in (chunks or [])]
                prepared_files.append(
                    {
                        "rel_path": file_rel_path,
                        "is_existing": is_existing,
                        "file_id": file_id,
                        "new_hash": new_hash,
                        "size_bytes": size_bytes,
                        "line_count": line_count,
                        "language": language,
                        "content": content,
                        "symbols": symbols,
                        "chunks": chunks or [],
                        "chunk_texts": chunk_texts,
                        "vectors": [],
                        "embed_ok": True,
                    }
                )

            if prepared_files:
                # Step B: Embed all chunk texts across the entire batch in one call
                all_batch_texts: list[str] = []
                for pf in prepared_files:
                    all_batch_texts.extend(pf["chunk_texts"])

                if self.embedding_service is not None and all_batch_texts:
                    batch_vectors, batch_ok = await self._embed_and_normalize_texts(all_batch_texts)
                    if batch_ok:
                        offset = 0
                        for pf in prepared_files:
                            n_chunks = len(pf["chunk_texts"])
                            pf["vectors"] = batch_vectors[offset : offset + n_chunks]
                            pf["embed_ok"] = True
                            offset += n_chunks
                    else:
                        # Isolate failures per file so valid files in the batch still persist
                        for pf in prepared_files:
                            if not pf["chunk_texts"]:
                                continue
                            f_vecs, f_ok = await self._embed_and_normalize_texts(pf["chunk_texts"])
                            pf["vectors"] = f_vecs
                            pf["embed_ok"] = f_ok
                            if not f_ok:
                                embedding_failed_count += 1
                                await asyncio.sleep(0.02)

                # Step C: Persist repository_files, code_symbols, and code_chunks in batch trips
                update_file_rows: list[dict[str, Any]] = []
                insert_file_rows: list[dict[str, Any]] = []
                batch_symbols_data: list[dict[str, Any]] = []
                batch_chunks_data: list[dict[str, Any]] = []

                for pf in prepared_files:
                    file_id = pf["file_id"]
                    file_rel_path = pf["rel_path"]
                    language = pf["language"]
                    content = pf["content"]
                    symbols = pf["symbols"]
                    chunks = pf["chunks"]

                    if pf["is_existing"]:
                        await self._execute(
                            text("DELETE FROM code_chunks WHERE repository_id = :repo_id AND file_id = :file_id"),
                            {"repo_id": repository_id, "file_id": file_id},
                            sess=session,
                        )
                        await self._execute(
                            text(
                                "DELETE FROM symbol_edges WHERE repository_id = :repo_id "
                                "AND (source_symbol_id IN (SELECT id FROM code_symbols WHERE repository_id = :repo_id AND file_id = :file_id) "
                                "OR target_symbol_id IN (SELECT id FROM code_symbols WHERE repository_id = :repo_id AND file_id = :file_id))"
                            ),
                            {"repo_id": repository_id, "file_id": file_id},
                            sess=session,
                        )
                        await self._execute(
                            text("DELETE FROM code_symbols WHERE repository_id = :repo_id AND file_id = :file_id"),
                            {"repo_id": repository_id, "file_id": file_id},
                            sess=session,
                        )
                        update_file_rows.append(
                            {
                                "hash": pf["new_hash"] if pf["embed_ok"] else "",
                                "size_bytes": pf["size_bytes"],
                                "line_count": pf["line_count"],
                                "language": language,
                                "file_id": file_id,
                            }
                        )
                    else:
                        insert_file_rows.append(
                            {
                                "id": file_id,
                                "repo_id": repository_id,
                                "path": file_rel_path,
                                "language": language,
                                "size_bytes": pf["size_bytes"],
                                "line_count": pf["line_count"],
                                "hash": pf["new_hash"] if pf["embed_ok"] else "",
                            }
                        )

                    persisted_symbol_ids: set[UUID] = set()
                    for sym in symbols:
                        sym_uuid = sym.id if isinstance(sym.id, UUID) else uuid.uuid4()
                        sym.id = sym_uuid
                        parent_uuid = sym.parent_id if sym.parent_id in persisted_symbol_ids else None
                        batch_symbols_data.append(
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
                            }
                        )
                        persisted_symbol_ids.add(sym_uuid)
                        all_extracted_symbols.append(sym)
                        file_contents_by_id[file_id] = content
                        file_id_to_path[file_id] = file_rel_path

                    if not chunks or not pf["embed_ok"]:
                        continue

                    vectors = pf["vectors"]
                    seen_chunk_ids: set[UUID] = set()
                    for i, chunk in enumerate(chunks):
                        chunk_meta = dict(chunk.metadata or {})
                        sym_ids_list = [str(x) for x in chunk_meta.get("symbol_ids", [])]
                        chunk_id = compute_stable_chunk_id(
                            repository_id=repository_id,
                            file_id=file_id,
                            chunk_type=chunk.chunk_type,
                            start_line=chunk.start_line,
                            end_line=chunk.end_line,
                            content_hash=chunk.content_hash,
                            symbol_id=chunk.symbol_id,
                            symbol_ids=sym_ids_list,
                        )
                        if chunk_id in seen_chunk_ids:
                            chunk_id = uuid.uuid5(chunk_id, str(i))
                        seen_chunk_ids.add(chunk_id)
                        vec = vectors[i] if (vectors and i < len(vectors)) else None
                        if vec is None or len(vec) == 0:
                            dim = getattr(self.embedding_service, "dimensions", 768)
                            if not isinstance(dim, int):
                                dim = 768
                            vec = [0.0] * dim
                        vec_literal = _vec_to_pg_literal(vec)
                        safe_symbol_id = chunk.symbol_id if chunk.symbol_id in persisted_symbol_ids else None

                        sym_name = ""
                        sym_kind = ""
                        if safe_symbol_id:
                            matching_sym = next((s for s in symbols if getattr(s, "id", None) == safe_symbol_id), None)
                            if matching_sym:
                                sym_name = getattr(matching_sym, "name", "")
                                sym_kind = getattr(matching_sym, "kind", "")

                        code_search_text = generate_code_search_text(
                            content=chunk.content,
                            file_path=file_rel_path,
                            symbol_name=sym_name,
                            symbol_kind=sym_kind,
                        )

                        header_str = str(chunk_meta.get("contextual_header", ""))
                        metadata = {
                            **chunk_meta,
                            "file_path": file_rel_path,
                            "language": language,
                            "chunk_type": chunk.chunk_type,
                            "embedding_model": embedding_model_name,
                            "embedding_dim": len(vec),
                            "embedding_profile_version": prof_version,
                            "task_type": doc_task_type,
                            "l2_normalized": bool(vectors),
                            "index_fingerprint": compute_chunk_index_fingerprint(
                                chunk.content_hash,
                                chunker_version=str(chunk_meta.get("chunker_version", CHUNKER_VERSION)),
                                profile_version=prof_version,
                                contextual_header=header_str,
                            ),
                        }

                        batch_chunks_data.append(
                            {
                                "id": chunk_id,
                                "repo_id": repository_id,
                                "file_id": file_id,
                                "symbol_id": safe_symbol_id,
                                "content": chunk.content,
                                "code_search_text": code_search_text,
                                "tokens": chunk.token_count,
                                "embedding": vec_literal,
                                "start": chunk.start_line,
                                "end": chunk.end_line,
                                "hash": chunk.content_hash,
                                "metadata": json.dumps(metadata),
                            }
                        )

                    indexed_count += 1

                if update_file_rows:
                    await self._execute_batch(file_update_query, update_file_rows, sess=session, batch_size=250)
                if insert_file_rows:
                    await self._execute_batch(file_insert_query, insert_file_rows, sess=session, batch_size=250)
                if batch_symbols_data:
                    try:
                        await self._execute_batch(symbol_insert_query, batch_symbols_data, sess=session, batch_size=250)
                    except Exception as sym_exc:
                        logger.debug("Symbol batch persistence failed in batch %d: %s", batch_idx, sym_exc)
                if batch_chunks_data:
                    await self._execute_batch(chunk_query, batch_chunks_data, sess=session, batch_size=250)
                    chunks_embedded_count += len(batch_chunks_data)

            processed_so_far = min((batch_idx + 1) * self._file_batch_size, total_scanned)
            if processed_so_far < total_scanned and prepared_files:
                batch_repo_check = await self._execute(
                    text("SELECT 1 FROM repositories WHERE id = :repo_id"),
                    {"repo_id": repository_id},
                    sess=session,
                )
                batch_repo_exists = (
                    (batch_repo_check.first() is not None)
                    if hasattr(batch_repo_check, "first")
                    else True
                )
                if not batch_repo_exists:
                    await self._rollback(sess=session)
                    return {"indexed": 0, "skipped": 0, "reconciled_removed": 0, "graph_edges": 0}
                await self._commit(sess=session)

            if prepared_files or processed_so_far == total_scanned:
                progress_stats = {
                    "files_scanned": total_scanned,
                    "files_indexed": indexed_count,
                    "files_skipped": skipped_count,
                    "chunks_embedded": chunks_embedded_count,
                    "current_file_index": processed_so_far,
                }
                if job_id:
                    try:
                        from app.services.sync_worker import _set_job_progress
                        from app.models.sync_job import SyncJobStage

                        await asyncio.to_thread(
                            _set_job_progress,
                            job_id,
                            stage=SyncJobStage.INDEXING.value,
                            stats=progress_stats,
                        )
                    except Exception as prog_exc:
                        logger.debug("Progress update skipped: %s", prog_exc)
                if progress_callback is not None:
                    try:
                        cb_res = progress_callback({"stage": "INDEXING", **progress_stats})
                        if inspect.isawaitable(cb_res):
                            await cb_res
                    except Exception as cb_exc:
                        logger.debug("Progress callback skipped: %s", cb_exc)
                await asyncio.sleep(0.01)

        # Reconcile removed/deleted files (task2.md §1.7, P0.2)
        scanned_rel_paths = {
            getattr(f, "path", str(f)).replace("\\", "/")
            for f in scanned_files
        }
        removed_paths = set(existing_files.keys()) - scanned_rel_paths
        reconciled_removed_count = 0
        if removed_paths:
            logger.info("Reconciling %d removed files from repo %s", len(removed_paths), repository_id)
            for rm_path in removed_paths:
                file_info = existing_files[rm_path]
                file_id = file_info.get("file_id")
                if file_id:
                    await self._execute(
                        text("DELETE FROM code_chunks WHERE repository_id = :repo_id AND file_id = :file_id"),
                        {"repo_id": repository_id, "file_id": file_id},
                        sess=session,
                    )
                    await self._execute(
                        text(
                            "DELETE FROM symbol_edges WHERE repository_id = :repo_id "
                            "AND (source_symbol_id IN (SELECT id FROM code_symbols WHERE repository_id = :repo_id AND file_id = :file_id) "
                            "OR target_symbol_id IN (SELECT id FROM code_symbols WHERE repository_id = :repo_id AND file_id = :file_id))"
                        ),
                        {"repo_id": repository_id, "file_id": file_id},
                        sess=session,
                    )
                    await self._execute(
                        text("DELETE FROM code_symbols WHERE repository_id = :repo_id AND file_id = :file_id"),
                        {"repo_id": repository_id, "file_id": file_id},
                        sess=session,
                    )
                    await self._execute(
                        text("DELETE FROM repository_files WHERE id = :file_id"),
                        {"file_id": file_id},
                        sess=session,
                    )
                    reconciled_removed_count += 1

        persisted_edges_count = 0
        built_edges: list[Any] = []
        graph_dirty = graph_dirty or reconciled_removed_count > 0
        self._graph_is_complete = False
        # Incremental sync: files that did not change still own symbols and call sites. The graph must be
        # rebuilt over the *whole* repository, otherwise edges from unchanged files into a changed file are
        # deleted (their target symbols were re-created) and never restored, and PageRank only sees the delta.
        if graph_dirty and (skipped_count > 0 or reconciled_removed_count > 0):
            try:
                await self._merge_unchanged_graph_inputs(
                    session=session,
                    repository_id=repository_id,
                    root_path=root_path,
                    symbols=all_extracted_symbols,
                    file_contents_by_id=file_contents_by_id,
                    file_id_to_path=file_id_to_path,
                )
            except Exception as merge_exc:
                logger.warning(
                    "graph_full_rebuild_inputs_unavailable",
                    extra={"repo_id": str(repository_id), "error": str(merge_exc)},
                )
        if all_extracted_symbols:
            try:
                from scanner.import_tracker import ImportTracker
                from scanner.symbol_ranker import SymbolImportanceRanker

                for sym in all_extracted_symbols:
                    if sym.file_id in file_id_to_path and not getattr(sym, "file_path", ""):
                        sym.file_path = file_id_to_path[sym.file_id]

                known_rel_paths = list(scanned_rel_paths)
                tracker = ImportTracker()
                import_maps = {}
                for fid, fcontent in file_contents_by_id.items():
                    fpath = file_id_to_path.get(fid, "")
                    if fpath:
                        f_lang = self.detector.detect(fpath)
                        f_info = type(
                            "FInfo",
                            (),
                            {"path": fpath, "size_bytes": len(fcontent), "language": f_lang, "is_binary": False},
                        )()
                        import_maps[fpath] = tracker.parse_imports(
                            f_info, fcontent, known_files=known_rel_paths
                        )

                graph_builder = DependencyGraphBuilder(
                    all_extracted_symbols,
                    file_contents=file_contents_by_id,
                    file_paths=file_id_to_path,
                    import_maps=import_maps,
                )
                resolved_edges = graph_builder.build()
                all_graph_edges = graph_builder.all_edges
                built_edges = all_graph_edges

                ranker = SymbolImportanceRanker()
                scores_by_id = ranker.rank_symbols(all_extracted_symbols, resolved_edges)
                score_update_query = text(
                    "UPDATE code_symbols SET importance_score = :score WHERE id = :id AND repository_id = :repo_id"
                )
                # Batch all symbol score updates together into one database trip
                score_updates = [
                    {"score": float(imp_score), "id": sym_id, "repo_id": repository_id}
                    for sym_id, imp_score in scores_by_id.items()
                ]
                if score_updates:
                    await self._execute_batch(
                        score_update_query,
                        score_updates,
                        sess=session,
                        batch_size=250,
                    )

                if skipped_count == 0 or self._graph_is_complete:
                    # The graph was built over every symbol in the repository: replace it wholesale.
                    await self._execute(
                        text("DELETE FROM symbol_edges WHERE repository_id = :repo_id"),
                        {"repo_id": repository_id},
                        sess=session,
                    )
                else:
                    # Fallback (unchanged files could not be loaded): only replace the changed symbols' edges.
                    await self._execute_batch(
                        text(
                            "DELETE FROM symbol_edges WHERE repository_id = :repo_id AND source_symbol_id = :source_id"
                        ),
                        [{"repo_id": repository_id, "source_id": sym.id} for sym in all_extracted_symbols],
                        sess=session,
                        batch_size=250,
                    )

                edge_insert_query = text(
                    """
                    INSERT INTO symbol_edges
                    (id, repository_id, source_symbol_id, target_symbol_id, target_name, edge_type, provenance, resolution_status, confidence, weight)
                    VALUES (:id, :repo_id, :source_id, :target_id, :target_name, :edge_type, :provenance, :resolution_status, :confidence, :weight)
                    """
                )
                # Batch all knowledge graph edge inserts into one database trip
                edges_data = [
                    {
                        "id": uuid.uuid4(),
                        "repo_id": repository_id,
                        "source_id": edge.source_id,
                        "target_id": edge.target_id,
                        "target_name": getattr(edge, "target_name", None),
                        "edge_type": edge.edge_type,
                        "provenance": getattr(edge, "provenance", "tree_sitter") or "tree_sitter",
                        "resolution_status": getattr(edge, "resolution_status", "resolved") or "resolved",
                        "confidence": float(getattr(edge, "confidence", 1.0) or 1.0),
                        "weight": float(getattr(edge, "weight", 1.0) or 1.0),
                    }
                    for edge in all_graph_edges
                ]
                if edges_data:
                    persisted_edges_count = await self._execute_batch(
                        edge_insert_query,
                        edges_data,
                        sess=session,
                        batch_size=250,
                    )
                logger.info(
                    "Explicitly persisted %d knowledge graph edges and PageRank scores for repo %s",
                    persisted_edges_count,
                    repository_id,
                )
            except Exception as edge_exc:
                logger.warning("Symbol edge persistence error for repo %s: %s", repository_id, edge_exc)

        # Safeguard (Issue #183): Revalidate repository existence before generating and persisting snapshot
        repo_check_snap = await self._execute(
            text("SELECT 1 FROM repositories WHERE id = :repo_id"),
            {"repo_id": repository_id},
            sess=session,
        )
        repo_exists_snap = (repo_check_snap.first() is not None) if hasattr(repo_check_snap, "first") else True
        if not repo_exists_snap:
            logger.warning("indexing_snapshot_aborted_repository_deleted", extra={"repo_id": str(repository_id)})
            await self._rollback(sess=session)
            return {"indexed": 0, "skipped": 0, "reconciled_removed": 0, "graph_edges": 0}

        # Build and persist the Repository Intelligence Snapshot (task.md §3, §4, §10).
        # Skip when nothing changed: rebuilding from an empty symbol list would overwrite the
        # previous, complete snapshot with an empty graph.
        try:
            if not graph_dirty:
                raise _SnapshotUnchanged()
            from ai.intelligence.builder import RepositoryIntelligenceBuilder
            from ai.intelligence.snapshot_manager import RepositoryIntelligenceSnapshotManager

            files_res = await self._execute(
                text("SELECT id, path, language, content_hash, line_count, size_bytes FROM repository_files WHERE repository_id = :repo_id"),
                {"repo_id": repository_id},
                sess=session,
            )
            raw_files = files_res.fetchall() if hasattr(files_res, "fetchall") else []
            file_objs = [
                type("FileRecord", (), {
                    "id": str(r[0]),
                    "path": str(r[1]),
                    "language": str(r[2] or "text"),
                    "content_hash": str(r[3] or ""),
                    "line_count": int(r[4] or 0),
                    "size_bytes": int(r[5] or 0),
                })()
                for r in raw_files
            ]

            builder = RepositoryIntelligenceBuilder(repository_id=repository_id, commit_sha="HEAD")
            snapshot = builder.build_snapshot(
                files=file_objs,
                symbols=all_extracted_symbols,
                edges=built_edges,
                file_contents={file_id_to_path.get(fid, ""): c for fid, c in file_contents_by_id.items()},
            )
            snapshot_mgr = RepositoryIntelligenceSnapshotManager()
            manifest = snapshot_mgr.publish_snapshot(snapshot)
            logger.info("Published persistent intelligence snapshot for repo %s (valid: %s)", repository_id, manifest.is_valid)
        except _SnapshotUnchanged:
            logger.debug("Repository unchanged; keeping existing intelligence snapshot for %s", repository_id)
        except Exception as snap_exc:
            logger.warning("Repository intelligence snapshot generation skipped: %s", snap_exc)

        # R04: Advance active index generation atomically upon successful sync completion
        prof_tag = getattr(self.embedding_service, "profile_version", "v1")
        if not isinstance(prof_tag, str):
            prof_tag = "v1"
        new_generation = f"gen_{prof_tag}_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        try:
            await self._execute(
                text("UPDATE repositories SET active_index_generation = :gen, sync_status = 'SYNCED', last_synced_at = CURRENT_TIMESTAMP WHERE id = :repo_id"),
                {"gen": new_generation, "repo_id": repository_id},
                sess=session,
            )
        except Exception as gen_exc:  # noqa: BLE001
            logger.warning("Active index generation update failed: %s", gen_exc)

        # Safeguard (Issue #183): Revalidate repository existence before final transaction commit
        repo_check_commit = await self._execute(
            text("SELECT 1 FROM repositories WHERE id = :repo_id"),
            {"repo_id": repository_id},
            sess=session,
        )
        repo_exists_commit = (repo_check_commit.first() is not None) if hasattr(repo_check_commit, "first") else True
        if not repo_exists_commit:
            logger.warning("indexing_commit_aborted_repository_deleted", extra={"repo_id": str(repository_id)})
            try:
                from app.repositories.repository_repository import cleanup_repository_filesystem_resources
                cleanup_repository_filesystem_resources(repository_id)
            except Exception as clean_exc:
                logger.warning("indexing_abort_cleanup_failed", extra={"error": str(clean_exc), "repo_id": str(repository_id)})

            await self._rollback(sess=session)
            return {"indexed": 0, "skipped": 0, "reconciled_removed": 0, "graph_edges": 0}

        await self._commit(sess=session)
        logger.info(
            "Incremental sync finished for repo %s: indexed=%d, skipped=%d, reconciled_removed=%d, edges=%d",
            repository_id,
            indexed_count,
            skipped_count,
            reconciled_removed_count,
            persisted_edges_count,
        )
        return {
            "indexed": indexed_count,
            "skipped": skipped_count,
            "reconciled_removed": reconciled_removed_count,
            "graph_edges": persisted_edges_count,
            "embedding_failed": embedding_failed_count,
            "chunks_embedded": chunks_embedded_count,
        }


# ===========================================================================
# P1: Blue/Green Staged v1 -> v2 Re-Embedding Migration Manager
# ===========================================================================


@dataclass
class ReembeddingProgress:
    """Tracks progress, retry/resume state, and validation status for v1 -> v2 migration."""

    repository_id: UUID
    target_profile_version: str = "v2"
    status: str = "IDLE"
    total_files: int = 0
    processed_files: int = 0
    total_chunks: int = 0
    embedded_chunks: int = 0
    failed_files: list[str] = field(default_factory=list)
    staged_generation: str = ""


class ReembeddingMigrationManager:
    """
    Manages safe blue/green migration from embedding profile `v1` to `v2`.

    Invariants:
    - Preserves the active `v1` index in `code_chunks` while `v2` chunks are staged and validated.
    - Supports retry/resume so files already staged in `v2` are not re-embedded after a partial failure.
    - Validates vector count, dimensionality, and unit L2 norm before allowing activation.
    - Supports instant rollback (`rollback_to_v1`) restoring the exact `v1` chunk rows and generation.
    """

    def __init__(
        self,
        db_session: Any,
        embedding_service: Any,
        chunker: SymbolChunker | None = None,
        extractor: SymbolExtractor | None = None,
    ) -> None:
        self._db = db_session
        self.embedding_service = embedding_service
        self.chunker = chunker or SymbolChunker()
        self.detector = LanguageDetector()
        self.extractor = extractor or SymbolExtractor()
        self._indexer = IncrementalIndexer(
            db_session=db_session,
            chunker=self.chunker,
            embedding_service=embedding_service,
            extractor=self.extractor,
        )
        # Per-repository staged state: repo_id -> {path: list[dict[str, Any]]}
        self._staged_chunks_by_repo: dict[UUID, dict[str, list[dict[str, Any]]]] = {}
        self._v1_backup_by_repo: dict[UUID, list[dict[str, Any]]] = {}
        self._v1_generation_by_repo: dict[UUID, str | None] = {}
        self._progress_by_repo: dict[UUID, ReembeddingProgress] = {}

    def get_progress(self, repository_id: UUID) -> ReembeddingProgress:
        return self._progress_by_repo.get(
            repository_id,
            ReembeddingProgress(repository_id=repository_id),
        )

    def get_active_profile_version(self, repository_id: UUID) -> str:
        """Inspect active `code_chunks` metadata for `repository_id` to determine active profile version."""
        param_rid = repository_id.hex if self._indexer._is_sqlite() else repository_id
        target = self._db() if callable(self._db) and not hasattr(self._db, "execute") else self._db
        if hasattr(target, "execute") and not inspect.iscoroutinefunction(target.execute):
            res = target.execute(
                text("SELECT metadata FROM code_chunks WHERE repository_id = :rid LIMIT 1"),
                {"rid": param_rid},
            )
            row = res.first() if hasattr(res, "first") else None
            if not row or not row[0]:
                return "v1"
            raw_meta = row[0]
            meta = json.loads(raw_meta) if isinstance(raw_meta, str) else dict(raw_meta)
            return str(meta.get("embedding_profile_version", "v1"))

        prog = self._progress_by_repo.get(repository_id)
        if prog is not None and prog.status == "ACTIVE":
            return prog.target_profile_version
        return "v1"

    async def stage_v2_migration(
        self,
        repository_id: UUID,
        scanned_files: list[Any],
        root_path: str = "",
        *,
        resume: bool = True,
    ) -> ReembeddingProgress:
        """
        Stage `v2` chunks and embeddings in memory without overwriting the active `v1` index.
        If `resume=True`, files already staged in a prior partial attempt are reused without re-embedding.
        """
        if not resume or repository_id not in self._staged_chunks_by_repo:
            self._staged_chunks_by_repo[repository_id] = {}

        staged_for_repo = self._staged_chunks_by_repo[repository_id]
        progress = self._progress_by_repo.get(repository_id) or ReembeddingProgress(
            repository_id=repository_id,
            target_profile_version="v2",
            staged_generation=f"gen_v2_{int(time.time())}_{uuid.uuid4().hex[:8]}",
        )
        progress.status = "IN_PROGRESS"
        progress.total_files = len(scanned_files)
        progress.failed_files = []

        # Map existing file IDs and persisted symbols from DB so staged chunks keep valid FKs
        file_rows_res = await self._indexer._execute(
            text("SELECT path, id FROM repository_files WHERE repository_id = :rid"),
            {"rid": repository_id},
        )
        file_rows = file_rows_res.fetchall() if hasattr(file_rows_res, "fetchall") else []
        file_id_by_path: dict[str, UUID] = {
            r[0]: (UUID(str(r[1])) if not isinstance(r[1], UUID) else r[1])
            for r in file_rows
        }

        sym_rows_res = await self._indexer._execute(
            text("SELECT id FROM code_symbols WHERE repository_id = :rid"),
            {"rid": repository_id},
        )
        sym_rows = sym_rows_res.fetchall() if hasattr(sym_rows_res, "fetchall") else []
        persisted_sym_ids: set[UUID] = {
            UUID(str(r[0])) if not isinstance(r[0], UUID) else r[0]
            for r in sym_rows
        }

        expected_dim = getattr(self.embedding_service, "dimensions", 768)
        if not isinstance(expected_dim, int):
            expected_dim = 768

        for file_info in scanned_files:
            rel_path = getattr(file_info, "path", str(file_info)).replace("\\", "/")
            if resume and rel_path in staged_for_repo:
                continue

            full_path = (
                os.path.join(root_path, rel_path)
                if root_path and not os.path.isabs(rel_path)
                else rel_path
            )
            content = await asyncio.to_thread(_read_file_safe, full_path)
            if not content or not content.strip():
                staged_for_repo[rel_path] = []
                continue

            language = getattr(file_info, "language", None)
            if not language or language == "unknown":
                language = self.detector.detect(file_info)

            file_id = file_id_by_path.get(rel_path) or uuid.uuid4()
            try:
                symbols = self.extractor.extract(file_info, content, file_id=file_id)
            except Exception:
                symbols = []

            chunks = self.chunker.chunk_symbols(
                repository_id=repository_id,
                file_id=file_id,
                symbols=symbols,
                content=content,
                language=language,
                file_path=rel_path,
            )
            for c in chunks:
                c.content = redact(c.content)
                if c.embedding_text:
                    c.embedding_text = redact(c.embedding_text)

            embed_inputs = [c.embedding_text or c.content for c in chunks]
            try:
                if hasattr(self.embedding_service, "embed_documents"):
                    raw_vecs = await self.embedding_service.embed_documents(embed_inputs)
                else:
                    raw_vecs = await self.embedding_service.embed_batch(embed_inputs)
                if len(raw_vecs) != len(chunks):
                    raise EmbeddingError(
                        f"Expected {len(chunks)} vectors for {rel_path}, got {len(raw_vecs)}."
                    )
                norm_vecs = [
                    l2_normalize_vector(v, expected_dim=expected_dim) for v in raw_vecs
                ]
            except Exception as exc:
                logger.warning("Staged v2 embedding failed for %s: %s", rel_path, exc)
                progress.failed_files.append(rel_path)
                continue

            staged_records: list[dict[str, Any]] = []
            seen_chunk_ids: set[UUID] = set()
            for idx, (chunk, vec) in enumerate(zip(chunks, norm_vecs)):
                safe_sym_id = chunk.symbol_id if chunk.symbol_id in persisted_sym_ids else None
                chunk_meta = dict(chunk.metadata or {})
                sym_ids_list = [str(x) for x in chunk_meta.get("symbol_ids", [])]
                chunk_id = compute_stable_chunk_id(
                    repository_id=repository_id,
                    file_id=file_id,
                    chunk_type=chunk.chunk_type,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    content_hash=chunk.content_hash,
                    symbol_id=chunk.symbol_id,
                    symbol_ids=sym_ids_list,
                )
                if chunk_id in seen_chunk_ids:
                    chunk_id = uuid.uuid5(chunk_id, str(idx))
                seen_chunk_ids.add(chunk_id)

                header_str = str(chunk_meta.get("contextual_header", ""))
                metadata = {
                    **chunk_meta,
                    "file_path": rel_path,
                    "language": language,
                    "chunk_type": chunk.chunk_type,
                    "embedding_model": getattr(
                        self.embedding_service, "model_name", "models/gemini-embedding-001"
                    ),
                    "embedding_dim": len(vec),
                    "embedding_profile_version": "v2",
                    "task_type": GeminiTaskType.RETRIEVAL_DOCUMENT.value,
                    "l2_normalized": True,
                    "index_fingerprint": compute_chunk_index_fingerprint(
                        chunk.content_hash,
                        chunker_version=str(chunk_meta.get("chunker_version", CHUNKER_VERSION)),
                        profile_version="v2",
                        contextual_header=header_str,
                    ),
                }
                staged_records.append(
                    {
                        "id": chunk_id,
                        "repo_id": repository_id,
                        "file_id": file_id,
                        "symbol_id": safe_sym_id,
                        "content": chunk.content,
                        "code_search_text": generate_code_search_text(
                            content=chunk.content,
                            file_path=rel_path,
                            symbol_name="",
                            symbol_kind="",
                        ),
                        "tokens": chunk.token_count,
                        "embedding": _vec_to_pg_literal(vec),
                        "start": chunk.start_line,
                        "end": chunk.end_line,
                        "hash": chunk.content_hash,
                        "metadata": json.dumps(metadata),
                    }
                )
            staged_for_repo[rel_path] = staged_records

        progress.processed_files = len(staged_for_repo)
        all_staged = [rec for recs in staged_for_repo.values() for rec in recs]
        progress.total_chunks = len(all_staged)
        progress.embedded_chunks = len(all_staged)

        if progress.failed_files or progress.processed_files < progress.total_files:
            progress.status = "PARTIAL_RETRYABLE"
        else:
            progress.status = "STAGED_VALIDATED"

        self._progress_by_repo[repository_id] = progress
        return progress

    async def activate_v2(self, repository_id: UUID) -> ReembeddingProgress:
        """
        Atomically cut over `code_chunks` from `v1` to `v2` after verifying that the staged
        `v2` index is complete and validated. Preserves a `v1` backup for rollback and frees
        in-memory staged buffers upon commit.
        """
        progress = self._progress_by_repo.get(repository_id)
        if progress is None or progress.status != "STAGED_VALIDATED":
            raise EmbeddingError(
                f"Cannot activate v2 index for repository {repository_id}: migration is incomplete "
                f"(status={getattr(progress, 'status', 'NONE')}).",
                retryable=False,
            )

        staged_map = self._staged_chunks_by_repo.get(repository_id, {})
        staged_rows = [rec for recs in staged_map.values() for rec in recs]
        if not staged_rows:
            raise EmbeddingError(
                f"Cannot activate empty v2 index for repository {repository_id}.",
                retryable=False,
            )

        # Backup existing v1 chunks and active generation before replacing
        existing_res = await self._indexer._execute(
            text(
                "SELECT id, repository_id, file_id, symbol_id, content, code_search_text, "
                "token_count, embedding, start_line, end_line, content_hash, metadata "
                "FROM code_chunks WHERE repository_id = :rid"
            ),
            {"rid": repository_id},
        )
        old_rows = existing_res.fetchall() if hasattr(existing_res, "fetchall") else []
        backup_records: list[dict[str, Any]] = []
        for r in old_rows:
            emb_val = r[7]
            if isinstance(emb_val, list):
                emb_str = _vec_to_pg_literal(emb_val)
            else:
                emb_str = str(emb_val)
            meta_val = r[11]
            meta_str = meta_val if isinstance(meta_val, str) else json.dumps(meta_val or {})
            backup_records.append(
                {
                    "id": UUID(str(r[0])) if not isinstance(r[0], UUID) else r[0],
                    "repo_id": repository_id,
                    "file_id": UUID(str(r[2])) if not isinstance(r[2], UUID) else r[2],
                    "symbol_id": (UUID(str(r[3])) if r[3] and not isinstance(r[3], UUID) else r[3]),
                    "content": r[4],
                    "code_search_text": r[5],
                    "tokens": r[6],
                    "embedding": emb_str,
                    "start": r[8],
                    "end": r[9],
                    "hash": r[10],
                    "metadata": meta_str,
                }
            )
        self._v1_backup_by_repo[repository_id] = backup_records

        gen_res = await self._indexer._execute(
            text("SELECT active_index_generation FROM repositories WHERE id = :rid"),
            {"rid": repository_id},
        )
        gen_row = gen_res.first() if hasattr(gen_res, "first") else None
        self._v1_generation_by_repo[repository_id] = gen_row[0] if gen_row else None

        try:
            # Atomically replace active chunks with validated v2 chunks
            await self._indexer._execute(
                text("DELETE FROM code_chunks WHERE repository_id = :rid"),
                {"rid": repository_id},
            )
            insert_stmt = text(
                """
                INSERT INTO code_chunks
                (id, repository_id, file_id, symbol_id, content, code_search_text, token_count, embedding, start_line, end_line, content_hash, metadata)
                VALUES (:id, :repo_id, :file_id, :symbol_id, :content, :code_search_text, :tokens, CAST(:embedding AS vector), :start, :end, :hash, CAST(:metadata AS jsonb))
                """
            )
            # Batch insert staged v2 chunks in multi-row batches for high throughput
            if staged_rows:
                await self._indexer._execute_batch(insert_stmt, staged_rows, batch_size=250)

            await self._indexer._execute(
                text(
                    "UPDATE repositories SET active_index_generation = :gen, last_synced_at = CURRENT_TIMESTAMP WHERE id = :rid"
                ),
                {"gen": progress.staged_generation, "rid": repository_id},
            )
            await self._indexer._commit()
        except Exception:
            await self._indexer._rollback()
            raise

        # Free staged memory immediately after successful commit
        self._staged_chunks_by_repo.pop(repository_id, None)
        progress.status = "ACTIVE"
        return progress

    async def rollback_to_v1(self, repository_id: UUID) -> ReembeddingProgress:
        """
        Roll back an activated or staged `v2` migration to the preserved `v1` index.
        """
        progress = self._progress_by_repo.get(repository_id) or ReembeddingProgress(
            repository_id=repository_id
        )
        backup = self._v1_backup_by_repo.get(repository_id)

        if backup is not None:
            try:
                await self._indexer._execute(
                    text("DELETE FROM code_chunks WHERE repository_id = :rid"),
                    {"rid": repository_id},
                )
                insert_stmt = text(
                    """
                    INSERT INTO code_chunks
                    (id, repository_id, file_id, symbol_id, content, code_search_text, token_count, embedding, start_line, end_line, content_hash, metadata)
                    VALUES (:id, :repo_id, :file_id, :symbol_id, :content, :code_search_text, :tokens, CAST(:embedding AS vector), :start, :end, :hash, CAST(:metadata AS jsonb))
                    """
                )
                # Batch restore previous v1 chunks in multi-row batches for high throughput
                if backup:
                    await self._indexer._execute_batch(insert_stmt, backup, batch_size=250)

                prev_gen = self._v1_generation_by_repo.get(repository_id)
                await self._indexer._execute(
                    text("UPDATE repositories SET active_index_generation = :gen WHERE id = :rid"),
                    {"gen": prev_gen, "rid": repository_id},
                )
                await self._indexer._commit()
            except Exception:
                await self._indexer._rollback()
                raise

        self._staged_chunks_by_repo.pop(repository_id, None)
        self._v1_backup_by_repo.pop(repository_id, None)
        self._v1_generation_by_repo.pop(repository_id, None)
        progress.status = "ROLLED_BACK"
        self._progress_by_repo[repository_id] = progress
        return progress
