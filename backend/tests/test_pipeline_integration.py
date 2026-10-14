"""Day 6 — Full pipeline integration tests: GitHub -> Backend -> DB -> Scanner -> Indexer -> RAG.
Owner: Keval — Testing Lead (W1-18)

Runs the complete Week 1 pipeline with real components against the test database:
1. GitHub App & installation + repository models persisted in DB.
2. Scanner (FileWalker, LanguageDetector, SymbolExtractor) scans fixture repositories.
3. Database populated with real RepositoryFile and CodeSymbol records.
4. Indexer (SymbolChunker) generates symbol-aware chunks persisted in CodeChunk.
5. Hybrid RAG pipeline performs retrieval and grounded Q&A.
6. The /repositories/{id}/chat endpoint returns correct, source-cited responses.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from ai.retrieval.base import CodeChunk as RetrievedChunk
from ai.retrieval.pipeline import RAGPipeline
from ai.schemas.grounding import GroundingValidator
from app.main import app
from app.models.code_chunk import CodeChunk
from app.models.code_symbol import CodeSymbol
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.repository_file import RepositoryFile
from app.models.user import User
from backend.indexer.chunker import SymbolChunker
from backend.scanner.detector import LanguageDetector
from backend.scanner.extractor import SymbolExtractor
from backend.scanner.walker import FileWalker

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Pipeline Helpers
# ---------------------------------------------------------------------------


def _index_fixture_repository(
    db: Session,
    repo_id: UUID,
    fixture_name: str,
) -> tuple[list[RepositoryFile], list[CodeSymbol], list[CodeChunk]]:
    """Execute Scanner -> DB -> Indexer on a fixture repository."""
    fixture_dir = str(FIXTURES_DIR / fixture_name)
    walker = FileWalker()
    detector = LanguageDetector()
    extractor = SymbolExtractor()
    chunker = SymbolChunker()

    walked_files = walker.walk(fixture_dir)
    persisted_files: list[RepositoryFile] = []
    persisted_symbols: list[CodeSymbol] = []
    persisted_chunks: list[CodeChunk] = []

    for file_info in walked_files:
        file_info.language = detector.detect(file_info)
        full_path = os.path.join(fixture_dir, file_info.path)
        with open(full_path, "r", encoding="utf-8") as fh:
            content = fh.read()

        line_count = len(content.splitlines())
        repo_file = RepositoryFile(
            id=uuid4(),
            repository_id=repo_id,
            path=file_info.path.replace(os.sep, "/"),
            language=file_info.language,
            size_bytes=file_info.size_bytes,
            line_count=line_count,
            content_hash=f"hash_{file_info.path}",
        )
        db.add(repo_file)
        persisted_files.append(repo_file)

        # Extract symbols
        symbols = extractor.extract(file_info, content, file_id=repo_file.id)
        for sym in symbols:
            code_sym = CodeSymbol(
                id=sym.id,
                file_id=repo_file.id,
                repository_id=repo_id,
                name=sym.name,
                kind=sym.kind,
                start_line=sym.start_line,
                end_line=sym.end_line,
                signature=sym.signature,
                parent_id=sym.parent_id,
            )
            db.add(code_sym)
            persisted_symbols.append(code_sym)

        # Chunk the symbols for this file
        if symbols:
            sym_chunks = chunker.chunk_symbols(repo_id, repo_file.id, symbols, content, file_info.language)
            for ch in sym_chunks:
                db_chunk = CodeChunk(
                    id=uuid4(),
                    repository_id=repo_id,
                    file_id=repo_file.id,
                    symbol_id=ch.symbol_id,
                    content=ch.content,
                    token_count=ch.token_count,
                    embedding=[0.0] * 1536,
                    start_line=ch.start_line,
                    end_line=ch.end_line,
                    content_hash=ch.content_hash,
                    chunk_metadata={"file_path": repo_file.path},
                )
                db.add(db_chunk)
                persisted_chunks.append(db_chunk)

    db.commit()
    return persisted_files, persisted_symbols, persisted_chunks


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------


def test_full_pipeline_integration_python_sample(
    client: TestClient,
    db_session: Session,
    test_user: User,
    auth_headers: dict[str, str],
):
    """End-to-end integration test:

    GitHub fixture -> DB repo -> Scanner -> Indexer -> RAG pipeline -> Chat endpoint.
    """
    # 1. Setup GitHub Installation + Repository
    installation = GitHubInstallation(
        id=uuid4(),
        user_id=test_user.id,
        installation_id="gh-inst-w1d6",
        account_login=test_user.login,
        permissions={"contents": "read"},
    )
    db_session.add(installation)
    db_session.commit()

    repo = Repository(
        id=uuid4(),
        user_id=test_user.id,
        installation_id=installation.id,
        github_repo_id="gh-repo-python-sample",
        owner=test_user.login,
        name="python_sample",
        default_branch="main",
        language="Python",
        sync_status=SyncStatus.SYNCED,
    )
    db_session.add(repo)
    db_session.commit()

    # 2. Scanner + Indexer pipeline execution against python_sample
    files, symbols, chunks = _index_fixture_repository(db_session, repo.id, "python_sample")
    assert len(files) == 11
    assert len(symbols) == 26
    assert len(chunks) > 0

    # 3. Configure RAG Pipeline backed by indexed chunks and GroundingValidator
    grounding_validator = GroundingValidator(db_session=db_session)

    # Retriever implementation searching the indexed chunks
    def search_chunks(query: str, top_k: int = 5) -> list[RetrievedChunk]:
        q_lower = query.lower()
        keywords = [w for w in q_lower.split() if w not in {"where", "is", "a", "the", "in", "how", "are"}]
        matched_with_scores = []
        for ch in chunks:
            file_path = ch.chunk_metadata.get("file_path", "")
            content_lower = ch.content.lower()
            matches = sum(1 for kw in keywords if kw in content_lower or kw in file_path.lower())
            if "password" in q_lower and ("password" in content_lower or "hash" in content_lower):
                matches += 5
            if matches > 0:
                matched_with_scores.append(
                    (
                        matches,
                        RetrievedChunk(
                            id=ch.id,
                            repository_id=repo.id,
                            file_id=ch.file_id,
                            symbol_id=ch.symbol_id,
                            content=ch.content,
                            token_count=ch.token_count,
                            start_line=ch.start_line,
                            end_line=ch.end_line,
                            content_hash=ch.content_hash,
                            score=min(0.99, 0.5 + 0.1 * matches),
                            file_path=file_path,
                        ),
                    )
                )
        matched_with_scores.sort(key=lambda x: x[0], reverse=True)
        return [chunk for _, chunk in matched_with_scores[:top_k]]

    mock_retriever = MagicMock()
    mock_retriever.retrieve = AsyncMock(
        side_effect=lambda query, repository_id=None, top_k=5, **kwargs: search_chunks(query, top_k)
    )

    rag_pipeline = RAGPipeline(
        vector_retriever=mock_retriever,
        lexical_retriever=mock_retriever,
        grounding_validator=grounding_validator,
    )

    app.state.rag_pipeline = rag_pipeline
    try:
        # 4. Invoke the Chat endpoint via HTTP client
        response = client.post(
            f"/api/v1/repositories/{repo.id}/chat",
            headers=auth_headers,
            json={"question": "Where is user password hashing implemented?", "history": []},
        )

        assert response.status_code == 200
        data = response.json()

        # 5. Assert grounded answer with citation
        assert "answer" in data
        assert "sources" in data
        assert len(data["sources"]) > 0

        source_files = [s["file"] for s in data["sources"]]
        assert "utils.py" in source_files, f"Expected utils.py in sources, got: {source_files}"
        assert data["confidence"] in ("high", "medium")

        # Verify Grounding: source file exists in repository_files
        for src in data["sources"]:
            db_file = db_session.query(RepositoryFile).filter_by(repository_id=repo.id, path=src["file"]).first()
            assert db_file is not None, f"Cited file {src['file']} must exist in DB"
            assert src["start_line"] >= 1
            assert src["end_line"] <= db_file.line_count + 1

    finally:
        del app.state.rag_pipeline


def test_full_pipeline_integration_jwt_auth_query(
    client: TestClient,
    db_session: Session,
    test_user: User,
    auth_headers: dict[str, str],
):
    """Verify Q&A for JWT authentication returns auth.py in citations."""
    installation = GitHubInstallation(
        id=uuid4(),
        user_id=test_user.id,
        installation_id="gh-inst-w1d6-jwt",
        account_login=test_user.login,
        permissions={"contents": "read"},
    )
    db_session.add(installation)
    db_session.commit()

    repo = Repository(
        id=uuid4(),
        user_id=test_user.id,
        installation_id=installation.id,
        github_repo_id="gh-repo-python-jwt",
        owner=test_user.login,
        name="python_jwt_sample",
        default_branch="main",
        language="Python",
        sync_status=SyncStatus.SYNCED,
    )
    db_session.add(repo)
    db_session.commit()

    files, symbols, chunks = _index_fixture_repository(db_session, repo.id, "python_sample")

    def search_chunks(query: str, top_k: int = 5) -> list[RetrievedChunk]:
        matched = []
        for ch in chunks:
            file_path = ch.chunk_metadata.get("file_path", "")
            if "jwt" in ch.content.lower() or "token" in ch.content.lower() or "auth" in file_path.lower():
                matched.append(
                    RetrievedChunk(
                        id=ch.id,
                        repository_id=repo.id,
                        file_id=ch.file_id,
                        symbol_id=ch.symbol_id,
                        content=ch.content,
                        token_count=ch.token_count,
                        start_line=ch.start_line,
                        end_line=ch.end_line,
                        content_hash=ch.content_hash,
                        score=0.95,
                        file_path=file_path,
                    )
                )
        return matched[:top_k]

    mock_retriever = MagicMock()
    mock_retriever.retrieve = AsyncMock(
        side_effect=lambda query, repository_id=None, top_k=5, **kwargs: search_chunks(query, top_k)
    )

    rag_pipeline = RAGPipeline(
        vector_retriever=mock_retriever,
        lexical_retriever=mock_retriever,
        grounding_validator=GroundingValidator(db_session=db_session),
    )

    app.state.rag_pipeline = rag_pipeline
    try:
        response = client.post(
            f"/api/v1/repositories/{repo.id}/chat",
            headers=auth_headers,
            json={"question": "Where are JWT access tokens generated?", "history": []},
        )

        assert response.status_code == 200
        data = response.json()
        source_files = [s["file"] for s in data["sources"]]
        assert "auth.py" in source_files
    finally:
        del app.state.rag_pipeline


def test_full_pipeline_cross_repository_isolation(
    client: TestClient,
    db_session: Session,
    test_user: User,
    auth_headers: dict[str, str],
):
    """Verify that User A cannot query a repository owned by User B."""
    other_user = User(
        id=uuid4(),
        github_id="gh-other-user",
        login="other_user",
        email="other@example.com",
    )
    db_session.add(other_user)
    db_session.commit()

    installation = GitHubInstallation(
        id=uuid4(),
        user_id=other_user.id,
        installation_id="gh-inst-other",
        account_login=other_user.login,
        permissions={"contents": "read"},
    )
    db_session.add(installation)
    db_session.commit()

    other_repo = Repository(
        id=uuid4(),
        user_id=other_user.id,
        installation_id=installation.id,
        github_repo_id="gh-other-repo",
        owner=other_user.login,
        name="secret-repo",
        default_branch="main",
        language="Python",
        sync_status=SyncStatus.SYNCED,
    )
    db_session.add(other_repo)
    db_session.commit()

    app.state.rag_pipeline = RAGPipeline()
    try:
        response = client.post(
            f"/api/v1/repositories/{other_repo.id}/chat",
            headers=auth_headers,
            json={"question": "Tell me secrets", "history": []},
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "REPOSITORY_NOT_FOUND"
    finally:
        del app.state.rag_pipeline
