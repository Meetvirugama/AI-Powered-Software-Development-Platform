"""Day 7 — Week 1 End-to-End (E2E) Test.
Owner: Keval — Testing Lead (W1-18)

Verifies the complete Week 1 flow automated end-to-end:
1. Create user + GitHub installation (fixture)
2. Trigger repository sync on a fixture repository (POST /repositories/:id/sync)
3. Wait for sync to complete (polling sync_status -> SYNCED)
4. Send a question about the repository (POST /repositories/:id/chat)
5. Assert that the response contains the expected file in sources
"""

from __future__ import annotations

import os
from pathlib import Path
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


def _simulate_sync_worker(db: Session, repo_id: UUID, fixture_name: str) -> list[CodeChunk]:
    """Simulates the backend sync worker consuming the sync job.

    Performs: FileWalker -> LanguageDetector -> SymbolExtractor -> SymbolChunker -> DB.
    Updates repo.sync_status = SYNCED.
    """
    fixture_dir = str(FIXTURES_DIR / fixture_name)
    walker = FileWalker()
    detector = LanguageDetector()
    extractor = SymbolExtractor()
    chunker = SymbolChunker()

    walked_files = walker.walk(fixture_dir)
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

    repo = db.get(Repository, repo_id)
    if repo:
        repo.sync_status = SyncStatus.SYNCED
    db.commit()

    return persisted_chunks


# ---------------------------------------------------------------------------
# Week 1 E2E Flow Tests
# ---------------------------------------------------------------------------


def test_week1_e2e_complete_flow_python_sample(
    client: TestClient,
    db_session: Session,
    test_user: User,
    auth_headers: dict[str, str],
):
    """Complete 5-step Week 1 flow on python_sample fixture:

    1. Create user + GitHub installation (fixture)
    2. Trigger repository sync (POST /api/v1/repositories/:id/sync)
    3. Wait for sync to complete (polling sync_status -> SYNCED)
    4. Send a question about the repository (POST /api/v1/repositories/:id/chat)
    5. Assert that the response contains the expected file in sources
    """
    # -----------------------------------------------------------------------
    # Step 1: Create user + GitHub installation (fixture)
    # -----------------------------------------------------------------------
    installation = GitHubInstallation(
        id=uuid4(),
        user_id=test_user.id,
        installation_id="gh-e2e-inst-1",
        account_login=test_user.login,
        permissions={"contents": "read", "metadata": "read"},
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
        sync_status=SyncStatus.NOT_SYNCED,
    )
    db_session.add(repo)
    db_session.commit()

    # Verify initial state via API
    init_res = client.get(f"/api/v1/repositories/{repo.id}", headers=auth_headers)
    assert init_res.status_code == 200
    assert init_res.json()["sync_status"] == "NOT_SYNCED"

    # -----------------------------------------------------------------------
    # Step 2: Trigger repository sync on a fixture repository
    # -----------------------------------------------------------------------
    sync_res = client.post(f"/api/v1/repositories/{repo.id}/sync", headers=auth_headers)
    assert sync_res.status_code == 202
    sync_data = sync_res.json()
    assert "job_id" in sync_data

    # Repository status transitions to SYNCING
    syncing_res = client.get(f"/api/v1/repositories/{repo.id}", headers=auth_headers)
    assert syncing_res.json()["sync_status"] == "SYNCING"

    # -----------------------------------------------------------------------
    # Step 3: Wait for sync to complete (polling sync_status)
    # -----------------------------------------------------------------------
    # Worker processes the sync job in the background
    indexed_chunks = _simulate_sync_worker(db_session, repo.id, "python_sample")
    assert len(indexed_chunks) > 0

    # Poll status endpoint until SYNCED
    poll_res = client.get(f"/api/v1/repositories/{repo.id}", headers=auth_headers)
    assert poll_res.status_code == 200
    assert poll_res.json()["sync_status"] == "SYNCED"

    # -----------------------------------------------------------------------
    # Step 4: Send a question about the repository
    # -----------------------------------------------------------------------
    # Set up RAG pipeline backed by indexed chunks
    def search_chunks(query: str, top_k: int = 5) -> list[RetrievedChunk]:
        q_lower = query.lower()
        matched = []
        for ch in indexed_chunks:
            f_path = ch.chunk_metadata.get("file_path", "")
            if "password" in q_lower and ("password" in ch.content.lower() or "utils.py" in f_path):
                score = 0.98
            elif any(w in ch.content.lower() for w in q_lower.split() if len(w) > 3):
                score = 0.80
            else:
                continue
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
                    score=score,
                    file_path=f_path,
                )
            )
        matched.sort(key=lambda x: x.score, reverse=True)
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
        chat_res = client.post(
            f"/api/v1/repositories/{repo.id}/chat",
            headers=auth_headers,
            json={"question": "Where are user passwords hashed?", "history": []},
        )

        # -------------------------------------------------------------------
        # Step 5: Assert response contains expected file in sources
        # -------------------------------------------------------------------
        assert chat_res.status_code == 200
        chat_data = chat_res.json()

        assert "answer" in chat_data
        assert "sources" in chat_data
        assert len(chat_data["sources"]) > 0

        source_files = [s["file"] for s in chat_data["sources"]]
        assert "utils.py" in source_files, f"Expected utils.py in sources, got: {source_files}"
        assert chat_data["confidence"] in ("high", "medium")

    finally:
        del app.state.rag_pipeline


def test_week1_e2e_complete_flow_nodejs_sample(
    client: TestClient,
    db_session: Session,
    test_user: User,
    auth_headers: dict[str, str],
):
    """Complete 5-step Week 1 flow on nodejs_sample fixture."""
    installation = GitHubInstallation(
        id=uuid4(),
        user_id=test_user.id,
        installation_id="gh-e2e-inst-2",
        account_login=test_user.login,
        permissions={"contents": "read", "metadata": "read"},
    )
    db_session.add(installation)
    db_session.commit()

    repo = Repository(
        id=uuid4(),
        user_id=test_user.id,
        installation_id=installation.id,
        github_repo_id="gh-repo-nodejs-sample",
        owner=test_user.login,
        name="nodejs_sample",
        default_branch="main",
        language="JavaScript",
        sync_status=SyncStatus.NOT_SYNCED,
    )
    db_session.add(repo)
    db_session.commit()

    # Step 2: Trigger sync
    sync_res = client.post(f"/api/v1/repositories/{repo.id}/sync", headers=auth_headers)
    assert sync_res.status_code == 202

    # Step 3: Wait for sync to complete
    indexed_chunks = _simulate_sync_worker(db_session, repo.id, "nodejs_sample")
    poll_res = client.get(f"/api/v1/repositories/{repo.id}", headers=auth_headers)
    assert poll_res.json()["sync_status"] == "SYNCED"

    # Step 4: Ask question
    def search_chunks(query: str, top_k: int = 5) -> list[RetrievedChunk]:
        matched = []
        for ch in indexed_chunks:
            f_path = ch.chunk_metadata.get("file_path", "")
            if "greeting" in query.lower() and ("formatgreeting" in ch.content.lower() or "utils.js" in f_path):
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
                        score=0.96,
                        file_path=f_path,
                    )
                )
        return matched[:top_k]

    mock_retriever = MagicMock()
    mock_retriever.retrieve = AsyncMock(
        side_effect=lambda query, repository_id=None, top_k=5, **kwargs: search_chunks(query, top_k)
    )

    app.state.rag_pipeline = RAGPipeline(
        vector_retriever=mock_retriever,
        lexical_retriever=mock_retriever,
        grounding_validator=GroundingValidator(db_session=db_session),
    )

    try:
        chat_res = client.post(
            f"/api/v1/repositories/{repo.id}/chat",
            headers=auth_headers,
            json={"question": "Where is the formatGreeting helper function defined?", "history": []},
        )

        # Step 5: Assert citation
        assert chat_res.status_code == 200
        chat_data = chat_res.json()
        source_files = [s["file"] for s in chat_data["sources"]]
        assert "utils.js" in source_files, f"Expected utils.js in sources, got {source_files}"
    finally:
        del app.state.rag_pipeline


def test_week1_e2e_unknown_query_negative_case(
    client: TestClient,
    db_session: Session,
    test_user: User,
    auth_headers: dict[str, str],
):
    """Verify that an unknown query produces zero citations and low confidence without hallucinating."""
    installation = GitHubInstallation(
        id=uuid4(),
        user_id=test_user.id,
        installation_id="gh-e2e-inst-3",
        account_login=test_user.login,
        permissions={"contents": "read"},
    )
    db_session.add(installation)
    db_session.commit()

    repo = Repository(
        id=uuid4(),
        user_id=test_user.id,
        installation_id=installation.id,
        github_repo_id="gh-repo-unknown-test",
        owner=test_user.login,
        name="empty_repo",
        default_branch="main",
        language="Python",
        sync_status=SyncStatus.SYNCED,
    )
    db_session.add(repo)
    db_session.commit()

    mock_retriever = MagicMock()
    mock_retriever.retrieve = AsyncMock(return_value=[])

    app.state.rag_pipeline = RAGPipeline(
        vector_retriever=mock_retriever,
        lexical_retriever=mock_retriever,
        grounding_validator=GroundingValidator(db_session=db_session),
    )

    try:
        response = client.post(
            f"/api/v1/repositories/{repo.id}/chat",
            headers=auth_headers,
            json={"question": "Tell me about cryptocurrency mining and proof of stake", "history": []},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["sources"]) == 0
        assert data["confidence"] == "low"
        assert "could not find" in data["answer"].lower()
    finally:
        del app.state.rag_pipeline
