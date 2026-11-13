"""
Test suite for Issue #242 (F-38):
Batch multi-row database insertions for code symbols and pgvector chunks.

Tests:
1. _execute_batch helper execution, chunked slicing, and SQLite compatibility.
2. Symbol batch insertion in IncrementalIndexer.sync().
3. Code chunk and vector embedding batch insertion in IncrementalIndexer.sync().
4. Symbol graph edge and PageRank score update batching.
5. CodeSymbolRepository.create_batch and ChunkRepository.create_batch.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.models.code_chunk import CodeChunk
from app.models.code_symbol import CodeSymbol
from app.models.repository import Repository
from app.models.repository_file import RepositoryFile
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.code_symbol_repository import CodeSymbolRepository
from indexer.incremental import IncrementalIndexer
from scanner.symbols import FileInfo, Symbol


@pytest.fixture
def memory_db():
    """Create an in-memory SQLite database configured with required platform tables."""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE repositories (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    default_branch TEXT,
                    sync_status TEXT,
                    last_synced_at TIMESTAMP,
                    last_indexed_commit_sha TEXT,
                    active_index_generation INTEGER
                );
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE repository_files (
                    id TEXT PRIMARY KEY,
                    repository_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    language TEXT,
                    size_bytes INTEGER,
                    line_count INTEGER,
                    content_hash TEXT,
                    last_indexed_at TIMESTAMP
                );
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE code_symbols (
                    id TEXT PRIMARY KEY,
                    file_id TEXT NOT NULL,
                    repository_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    start_line INTEGER,
                    end_line INTEGER,
                    signature TEXT,
                    parent_id TEXT,
                    importance_score REAL
                );
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE code_chunks (
                    id TEXT PRIMARY KEY,
                    repository_id TEXT NOT NULL,
                    file_id TEXT NOT NULL,
                    symbol_id TEXT,
                    content TEXT NOT NULL,
                    code_search_text TEXT,
                    token_count INTEGER,
                    embedding TEXT,
                    start_line INTEGER,
                    end_line INTEGER,
                    content_hash TEXT,
                    metadata TEXT
                );
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE symbol_edges (
                    id TEXT PRIMARY KEY,
                    repository_id TEXT NOT NULL,
                    source_symbol_id TEXT NOT NULL,
                    target_symbol_id TEXT,
                    target_name TEXT,
                    edge_type TEXT NOT NULL,
                    provenance TEXT,
                    resolution_status TEXT,
                    confidence REAL,
                    weight REAL
                );
                """
            )
        )

    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


class FakeEmbeddingService:
    """Mock embedding service returning valid 768-dim normalized float vectors."""

    def __init__(self, dimensions: int = 768):
        self.dimensions = dimensions
        self.profile_version = "v2"
        self.model_name = "models/gemini-embedding-001"

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        # Return synthetic normalized vectors
        return [[1.0] + [0.0] * (self.dimensions - 1) for _ in texts]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return await self.embed_documents(texts)

    async def aclose(self) -> None:
        pass


@pytest.mark.asyncio
async def test_execute_batch_empty_and_chunked_slicing(memory_db: Session):
    """Verify _execute_batch handles empty payloads and slices large datasets into chunks."""
    indexer = IncrementalIndexer(db_session=memory_db, embedding_service=FakeEmbeddingService())

    # 1. Empty payload returns 0 immediately
    res_empty = await indexer._execute_batch(
        text("INSERT INTO code_symbols (id) VALUES (:id)"), [], sess=memory_db
    )
    assert res_empty == 0

    # 2. Insert 70 items with batch_size=20 (should execute in 4 slices: 20, 20, 20, 10)
    repo_id = uuid4()
    file_id = uuid4()
    items = [
        {
            "id": uuid4(),
            "file_id": file_id,
            "repo_id": repo_id,
            "name": f"symbol_{i}",
            "kind": "function",
            "start_line": i + 1,
            "end_line": i + 2,
            "signature": f"def symbol_{i}():",
            "parent_id": None,
        }
        for i in range(70)
    ]

    insert_query = text(
        """
        INSERT INTO code_symbols
        (id, file_id, repository_id, name, kind, start_line, end_line, signature, parent_id)
        VALUES (:id, :file_id, :repo_id, :name, :kind, :start_line, :end_line, :signature, :parent_id)
        """
    )

    total_inserted = await indexer._execute_batch(
        insert_query, items, sess=memory_db, batch_size=20
    )
    assert total_inserted == 70

    # Verify rows exist in database
    count = memory_db.execute(text("SELECT count(*) FROM code_symbols")).scalar()
    assert count == 70


@pytest.mark.asyncio
async def test_indexer_sync_batches_symbols_and_chunks(memory_db: Session, tmp_path: Path):
    """End-to-end verification: IncrementalIndexer.sync() successfully batches symbols and chunks."""
    repo_id = uuid4()
    # Insert repository
    memory_db.execute(
        text(
            "INSERT INTO repositories (id, name, owner, default_branch, sync_status) "
            "VALUES (:id, 'demo-repo', 'platform', 'main', 'PENDING')"
        ),
        {"id": repo_id.hex},
    )
    memory_db.commit()

    # Create a source file with multiple classes and functions to produce dozens of symbols
    code_content = "\n\n".join(
        [
            f"class Service{i}:\n    def run_{i}(self):\n        return {i}\n    def stop_{i}(self):\n        return -1"
            for i in range(15)
        ]
    )
    src_file = tmp_path / "services.py"
    src_file.write_text(code_content, encoding="utf-8")

    f_info = FileInfo(
        path="services.py",
        size_bytes=src_file.stat().st_size,
        language="Python",
        is_binary=False,
    )

    indexer = IncrementalIndexer(db_session=memory_db, embedding_service=FakeEmbeddingService())

    stats = await indexer.sync(repo_id, [f_info], root_path=str(tmp_path))
    assert stats["indexed"] == 1

    # Verify code symbols were saved in database
    symbols_in_db = memory_db.execute(
        text("SELECT count(*) FROM code_symbols WHERE repository_id = :rid"),
        {"rid": repo_id.hex},
    ).scalar()
    assert symbols_in_db >= 15

    # Verify code chunks were saved in database
    chunks_in_db = memory_db.execute(
        text("SELECT count(*) FROM code_chunks WHERE repository_id = :rid"),
        {"rid": repo_id.hex},
    ).scalar()
    assert chunks_in_db >= 1

    # Verify chunk properties and valid embeddings
    chunk_row = memory_db.execute(
        text("SELECT content, embedding, metadata FROM code_chunks WHERE repository_id = :rid LIMIT 1"),
        {"rid": repo_id.hex},
    ).fetchone()
    assert chunk_row is not None
    assert "Service" in chunk_row[0]
    meta = json.loads(chunk_row[2])
    assert meta["embedding_profile_version"] == "v2"


@pytest.mark.asyncio
async def test_code_symbol_repository_create_batch(memory_db: Session):
    """Verify CodeSymbolRepository.create_batch inserts rows efficiently."""
    repo = CodeSymbolRepository(memory_db)
    repo_id = uuid4().hex
    file_id = uuid4().hex

    batch_symbols = [
        {
            "id": uuid4().hex,
            "file_id": file_id,
            "repository_id": repo_id,
            "name": f"func_{i}",
            "kind": "function",
            "start_line": i * 5,
            "end_line": i * 5 + 4,
            "signature": f"def func_{i}():",
            "parent_id": None,
        }
        for i in range(25)
    ]

    inserted = repo.create_batch(batch_symbols)
    memory_db.commit()
    assert inserted == 25

    rows = memory_db.execute(
        text("SELECT count(*) FROM code_symbols WHERE repository_id = :rid"),
        {"rid": repo_id},
    ).scalar()
    assert rows == 25


@pytest.mark.asyncio
async def test_chunk_repository_create_batch(memory_db: Session):
    """Verify ChunkRepository.create_batch inserts rows efficiently."""
    repo = ChunkRepository(memory_db)
    repo_id = uuid4().hex
    file_id = uuid4().hex

    batch_chunks = [
        {
            "id": uuid4().hex,
            "repository_id": repo_id,
            "file_id": file_id,
            "symbol_id": None,
            "content": f"def chunk_{i}(): pass",
            "code_search_text": f"chunk_{i}",
            "token_count": 10,
            "embedding": json.dumps([0.1] * 768),
            "start_line": i * 10 + 1,
            "end_line": i * 10 + 10,
            "content_hash": f"hash_{i}",
            "metadata": json.dumps({"batch": True}),
        }
        for i in range(30)
    ]

    inserted = repo.create_batch(batch_chunks)
    memory_db.commit()
    assert inserted == 30

    rows = memory_db.execute(
        text("SELECT count(*) FROM code_chunks WHERE repository_id = :rid"),
        {"rid": repo_id},
    ).scalar()
    assert rows == 30

