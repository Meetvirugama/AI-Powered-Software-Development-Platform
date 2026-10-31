"""Tests for indexer chunker and incremental indexing."""

from __future__ import annotations

from uuid import uuid4

import pytest

from indexer.chunker import SymbolChunker, reconstruct_file_from_chunks
from indexer.incremental import compute_content_hash, should_reindex
from scanner.symbols import Symbol


def test_reconstruct_file_from_chunks_deduplication():
    repo_id = uuid4()
    file_id = uuid4()
    source = "\n".join(
        [
            "import os",
            "",
            "class Greeter:",
            "    def hello(self):",
            "        return 'hi'",
            "",
            "    def bye(self):",
            "        return 'bye'",
        ]
    )
    symbols = [
        Symbol(id=uuid4(), name="import os", kind="import", file_id=file_id, start_line=1, end_line=1, signature="import os"),
        Symbol(id=uuid4(), name="Greeter", kind="class", file_id=file_id, start_line=3, end_line=8, signature="class Greeter:"),
        Symbol(id=uuid4(), name="hello", kind="method", file_id=file_id, start_line=4, end_line=5, signature="def hello(self):"),
        Symbol(id=uuid4(), name="bye", kind="method", file_id=file_id, start_line=7, end_line=8, signature="def bye(self):"),
    ]
    chunks = SymbolChunker().chunk_symbols(
        repository_id=repo_id,
        file_id=file_id,
        symbols=symbols,
        content=source,
        language="Python",
    )
    assert len(chunks) >= 3
    reconstructed = reconstruct_file_from_chunks(chunks)
    assert reconstructed.count("def hello(self):") == 1
    assert reconstructed.count("def bye(self):") == 1
    assert reconstructed.splitlines() == source.splitlines()


def test_reconstruct_file_with_line_slices():
    repo_id = uuid4()
    file_id = uuid4()
    source = "\n".join([f"line {i}" for i in range(1, 21)])
    chunks = SymbolChunker().chunk_text(
        repository_id=repo_id,
        file_id=file_id,
        content=source,
        language="Python",
    )
    reconstructed = reconstruct_file_from_chunks(chunks, start_line=5, end_line=10)
    lines = reconstructed.splitlines()
    assert lines[0] == "line 5"
    assert lines[-1] == "line 10"


def test_symbol_chunker_redacts_secrets():
    repo_id = uuid4()
    file_id = uuid4()
    source = 'SECRET_TOKEN = "ghp_123456789012345678901234567890123456"\n'
    chunks = SymbolChunker().chunk_text(
        repository_id=repo_id,
        file_id=file_id,
        content=source,
        language="Python",
    )
    assert len(chunks) > 0
    assert "ghp_1234567890" not in chunks[0].content
    assert "[REDACTED]" in chunks[0].content


def test_incremental_hash_helpers():
    content1 = "def foo(): pass"
    content2 = "def foo(): return 1"
    h1 = compute_content_hash(content1)
    h2 = compute_content_hash(content2)
    assert h1 != h2
    assert should_reindex(content1, None) is True
    assert should_reindex(content1, h1) is False
    assert should_reindex(content2, h1) is True
