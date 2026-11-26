"""Regression tests for Phase 1 cold-start, pooling, gzip, and HTTP caching improvements."""

from __future__ import annotations

import asyncio
import threading
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES

from ai.retrieval.base import CodeChunk
from ai.retrieval.reranker import CrossEncoderReranker
from ai.retrieval.reranker_factory import resolve_reranker_model_source
from app.core import lifespan as lifespan_module
from app.core.http_client import close_shared_http_client, get_shared_http_client
from app.main import app
from app.models.code_chunk import CodeChunk as DBCodeChunk
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.repository_file import RepositoryFile
from app.models.user import User


def _make_chunk(name: str = "chunk", score: float = 0.5) -> CodeChunk:
    return CodeChunk(
        id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        file_id=uuid.uuid4(),
        symbol_id=uuid.uuid4(),
        content=f"def {name}(): pass",
        token_count=10,
        start_line=1,
        end_line=2,
        content_hash="h1",
        score=score,
        file_path=f"src/{name}.py",
    )


def test_gzip_compresses_large_json_and_skips_small_and_sse() -> None:
    assert "text/event-stream" in DEFAULT_EXCLUDED_CONTENT_TYPES

    with TestClient(app) as client:
        large_res = client.get("/openapi.json", headers={"Accept-Encoding": "gzip"})
        assert large_res.status_code == 200
        assert large_res.headers.get("content-encoding") == "gzip"
        assert "paths" in large_res.json()

        live_res = client.get("/api/v1/health/live", headers={"Accept-Encoding": "gzip"})
        assert live_res.status_code == 200
        assert live_res.headers.get("content-encoding") is None


def test_shared_http_client_loop_affinity_and_close() -> None:
    async def check_same_loop_and_close() -> tuple[int, int, int]:
        c1 = get_shared_http_client()
        c2 = get_shared_http_client()
        assert c1 is c2
        await close_shared_http_client()
        c3 = get_shared_http_client()
        assert c3 is not c1
        await close_shared_http_client()
        return id(c1), id(c2), id(c3)

    first_ids = asyncio.run(check_same_loop_and_close())
    assert first_ids[0] == first_ids[1]
    assert first_ids[2] != first_ids[0]

    async def get_and_close() -> object:
        c = get_shared_http_client()
        await close_shared_http_client()
        return c

    c_loop1 = asyncio.run(get_and_close())
    c_loop2 = asyncio.run(get_and_close())
    assert c_loop1 is not c_loop2


def test_reranker_non_blocking_during_warmup_then_uses_model(monkeypatch: pytest.MonkeyPatch) -> None:
    reranker = CrossEncoderReranker()
    entered_load = threading.Event()
    allow_finish = threading.Event()

    mock_model = MagicMock()
    mock_model.predict.return_value = [0.1, 0.9]

    def slow_load() -> object:
        entered_load.set()
        assert allow_finish.wait(timeout=5.0)
        return mock_model

    monkeypatch.setattr(reranker, "_load_model", slow_load)

    chunks = [_make_chunk("first"), _make_chunk("second")]

    warm_thread = threading.Thread(target=reranker.warm_up, daemon=True)
    warm_thread.start()
    assert entered_load.wait(timeout=5.0)

    # While warm_up holds _load_lock, rerank must return immediately with fallback order.
    fallback_result = reranker.rerank("query", chunks, top_n=1)
    assert [c.id for c in fallback_result] == [chunks[0].id]
    assert reranker.last_status == "fallback_warming_up"

    allow_finish.set()
    warm_thread.join(timeout=5.0)
    assert not warm_thread.is_alive()
    assert reranker.is_loaded is True

    reranked = reranker.rerank("query", chunks, top_n=2)
    assert reranker.last_status == "reranked"
    assert [c.id for c in reranked] == [chunks[1].id, chunks[0].id]


def test_reranker_load_failure_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    reranker = CrossEncoderReranker()
    calls = 0

    def failing_load() -> object:
        nonlocal calls
        calls += 1
        raise OSError("network offline")

    monkeypatch.setattr(reranker, "_load_model", failing_load)
    chunks = [_make_chunk("only")]

    res1 = reranker.rerank("query", chunks, top_n=1)
    assert [c.id for c in res1] == [chunks[0].id]
    assert reranker.last_status == "fallback_model_missing"
    assert calls == 1

    res2 = reranker.rerank("query", chunks, top_n=1)
    assert [c.id for c in res2] == [chunks[0].id]
    assert reranker.last_status == "fallback_model_missing"
    assert calls == 1


def test_resolve_reranker_model_source(tmp_path) -> None:
    local_dir = tmp_path / "reranker"
    local_dir.mkdir()
    settings_local = SimpleNamespace(
        reranker_model_path=str(local_dir),
        reranker_model_name="cross-encoder/ms-marco-MiniLM-L-6-v2",
    )
    assert resolve_reranker_model_source(settings_local) == str(local_dir)

    missing_dir = tmp_path / "missing"
    settings_missing = SimpleNamespace(
        reranker_model_path=str(missing_dir),
        reranker_model_name="cross-encoder/ms-marco-MiniLM-L-6-v2",
    )
    assert resolve_reranker_model_source(settings_missing) == "cross-encoder/ms-marco-MiniLM-L-6-v2"


def test_start_reranker_warm_up_runs_in_background(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run_test() -> None:
        started = threading.Event()
        release = threading.Event()
        dummy_app = FastAPI()

        class BlockingReranker:
            def warm_up(self) -> None:
                started.set()
                assert release.wait(timeout=5.0)

        dummy_app.state.reranker = BlockingReranker()

        monkeypatch.setattr(lifespan_module.settings, "reranker_warm_up_on_startup", False, raising=False)
        assert lifespan_module.start_reranker_warm_up(dummy_app) is None

        monkeypatch.setattr(lifespan_module.settings, "reranker_warm_up_on_startup", True, raising=False)
        task = lifespan_module.start_reranker_warm_up(dummy_app)
        assert task is not None
        assert not task.done()

        await asyncio.to_thread(started.wait, 5.0)
        assert started.is_set()
        assert not task.done()

        release.set()
        await task
        assert task.done()

    asyncio.run(_run_test())


def test_repository_files_content_and_symbols_etag_304(
    client: TestClient,
    db_session: Session,
    test_user: User,
    auth_headers: dict[str, str],
) -> None:
    installation = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=test_user.id,
        installation_id="inst-etag-1",
        account_login=test_user.login,
        permissions={"contents": "read"},
    )
    db_session.add(installation)
    db_session.commit()

    repo = Repository(
        id=uuid.uuid4(),
        user_id=test_user.id,
        installation_id=installation.id,
        github_repo_id="gh-repo-etag-1",
        owner=test_user.login,
        name="etag-repo",
        sync_status=SyncStatus.SYNCED,
        last_synced_at=datetime.now(timezone.utc),
        last_indexed_commit_sha="deadbeefcafebabe",
    )
    db_session.add(repo)
    db_session.commit()

    repo_file = RepositoryFile(
        id=uuid.uuid4(),
        repository_id=repo.id,
        path="src/app.py",
        language="python",
        size_bytes=20,
        line_count=1,
        content_hash="hash-app-py",
        last_indexed_at=datetime.now(timezone.utc),
    )
    db_session.add(repo_file)
    db_session.commit()

    chunk = DBCodeChunk(
        id=uuid.uuid4(),
        repository_id=repo.id,
        file_id=repo_file.id,
        content="print('hello world')",
        token_count=5,
        embedding=[0.0] * 768,
        start_line=1,
        end_line=1,
        content_hash="chunk-h1",
    )
    db_session.add(chunk)
    db_session.commit()

    for url in (
        f"/api/v1/repositories/{repo.id}/files",
        f"/api/v1/repositories/{repo.id}/files/{repo_file.id}/content",
        f"/api/v1/repositories/{repo.id}/symbols",
    ):
        first = client.get(url, headers=auth_headers)
        assert first.status_code == 200
        etag = first.headers.get("etag")
        assert etag

        second = client.get(url, headers={**auth_headers, "If-None-Match": etag})
        assert second.status_code == 304
        assert second.headers.get("etag") == etag
