"""Tests for Phase 2 & 3 latency, batching, caching, pure ASGI middleware, and studio SSE streaming."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

from ai.embeddings.service import CachedEmbeddingService
from app.core import auth as auth_core
from app.core.logging import RequestIdMiddleware
from app.core.rate_limit import AsyncRedisRateLimitStore, RateLimitMiddleware, _rules
from app.main import app
from app.models.code_chunk import CodeChunk
from app.models.code_symbol import CodeSymbol
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.repository_file import RepositoryFile
from app.models.sync_job import SyncJob, SyncJobStatus
from app.models.user import User
from app.repositories.repository_repository import RepositoryRepository
from indexer.incremental import IncrementalIndexer
from scanner.symbols import FileInfo


def test_middlewares_are_pure_asgi_and_rate_limit_covers_stream_endpoints() -> None:
    assert not issubclass(RequestIdMiddleware, BaseHTTPMiddleware)
    assert not issubclass(auth_core.JWTMiddleware, BaseHTTPMiddleware)
    assert not issubclass(RateLimitMiddleware, BaseHTTPMiddleware)

    matched_paths = [
        "/api/v1/repositories/123/explain/stream",
        "/api/v1/repositories/123/detect-bugs/stream",
        "/api/v1/repositories/123/generate-tests/stream",
        "/api/v1/repositories/123/review/stream",
    ]
    rules = _rules("/api/v1")
    for path in matched_paths:
        assert any(rule.path_pattern.search(path) for rule in rules), f"Missing rate-limit rule for {path}"


def test_blocklist_valid_token_cache_ttl_is_30s(monkeypatch: pytest.MonkeyPatch) -> None:
    auth_core.clear_blocklist_cache()

    async def _not_revoked(*_args: Any, **_kwargs: Any) -> bool:
        return False

    monkeypatch.setattr(auth_core, "_check_redis_blocklist", _not_revoked)
    before = time.monotonic()
    res = asyncio.run(auth_core._is_token_blocklisted_async("jti-valid-30s"))
    assert res is False
    cached = auth_core._BLOCKLIST_CACHE.get("jti-valid-30s")
    assert cached is not None
    is_revoked, expires_at = cached
    assert is_revoked is False
    assert (expires_at - before) >= 29.0
    auth_core.clear_blocklist_cache()


def test_async_redis_rate_limit_store_hit() -> None:
    class FakePipeline:
        def __init__(self, store: dict[str, int]) -> None:
            self.store = store
            self.ops: list[tuple[str, str, int]] = []

        def incr(self, key: str) -> "FakePipeline":
            self.ops.append(("incr", key, 0))
            return self

        def expire(self, key: str, seconds: int, nx: bool = False) -> "FakePipeline":  # noqa: ARG002
            self.ops.append(("expire", key, seconds))
            return self

        async def execute(self) -> list[int]:
            results: list[int] = []
            for op, key, val in self.ops:
                if op == "incr":
                    self.store[key] = self.store.get(key, 0) + 1
                    results.append(self.store[key])
                elif op == "expire":
                    results.append(val)
            return results

    class FakeAsyncRedis:
        def __init__(self) -> None:
            self.store: dict[str, int] = {}

        def pipeline(self) -> FakePipeline:
            return FakePipeline(self.store)

    async def _run() -> tuple[int, int]:
        store = AsyncRedisRateLimitStore(FakeAsyncRedis())
        return await store.hit("k1", 60), await store.hit("k1", 60)

    c1, c2 = asyncio.run(_run())
    assert (c1, c2) == (1, 2)


def test_denormalized_counts_and_latest_sync_errors(
    client: TestClient,
    db_session: Session,
    test_user: User,
    auth_headers: dict[str, str],
) -> None:
    inst = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=test_user.id,
        installation_id="inst-counts-1",
        account_login=test_user.login,
        permissions={"contents": "read"},
    )
    db_session.add(inst)
    db_session.commit()

    repo = Repository(
        id=uuid.uuid4(),
        user_id=test_user.id,
        installation_id=inst.id,
        github_repo_id="gh-counts-1",
        owner=test_user.login,
        name="counts-repo",
        default_branch="main",
        language="Python",
        sync_status=SyncStatus.FAILED,
    )
    db_session.add(repo)
    db_session.commit()

    f1 = RepositoryFile(
        id=uuid.uuid4(),
        repository_id=repo.id,
        path="src/app.py",
        language="Python",
        size_bytes=100,
        line_count=10,
        content_hash="h1",
    )
    db_session.add(f1)
    db_session.commit()

    sym1 = CodeSymbol(
        id=uuid.uuid4(),
        repository_id=repo.id,
        file_id=f1.id,
        name="hello",
        kind="function",
        start_line=1,
        end_line=3,
    )
    sym2 = CodeSymbol(
        id=uuid.uuid4(),
        repository_id=repo.id,
        file_id=f1.id,
        name="world",
        kind="function",
        start_line=5,
        end_line=7,
    )
    chunk1 = CodeChunk(
        id=uuid.uuid4(),
        repository_id=repo.id,
        file_id=f1.id,
        symbol_id=sym1.id,
        content="def hello(): pass",
        content_hash="ch1",
        start_line=1,
        end_line=3,
        token_count=4,
        embedding=[0.1] * 768,
    )
    db_session.add_all([sym1, sym2, chunk1])
    db_session.commit()

    repo_dao = RepositoryRepository(db_session)
    file_count, sym_count, chunk_count = repo_dao.refresh_repository_counts(repo.id)
    assert (file_count, sym_count, chunk_count) == (1, 2, 1)

    now = datetime.now(UTC)
    older_job = SyncJob(
        id=uuid.uuid4(),
        repository_id=repo.id,
        user_id=test_user.id,
        status=SyncJobStatus.FAILED,
        error_message="older failure",
        created_at=now - timedelta(minutes=10),
    )
    latest_job = SyncJob(
        id=uuid.uuid4(),
        repository_id=repo.id,
        user_id=test_user.id,
        status=SyncJobStatus.FAILED,
        error_message="newest failure",
        created_at=now,
    )
    db_session.add_all([older_job, latest_job])
    db_session.commit()

    errs = repo_dao.latest_sync_errors([repo.id])
    assert errs[repo.id] == "newest failure"

    repo_dao.mark_sync_job_failed(latest_job.id, "marked failure")
    db_session.refresh(repo)
    assert repo.last_sync_error == "marked failure"

    list_res = client.get("/api/v1/repositories", headers=auth_headers)
    assert list_res.status_code == 200
    assert list_res.json()[0]["file_count"] == 1
    assert list_res.json()[0]["symbol_count"] == 2
    assert list_res.json()[0]["chunk_count"] == 1
    assert list_res.json()[0]["last_sync_error"] == "marked failure"


def test_cached_embedding_service_forwards_rate_limiter() -> None:
    sentinel = object()

    class StubProvider:
        provider_name = "stub"
        model_name = "stub-model"
        embedding_dimensions = 768

    svc = CachedEmbeddingService(provider=StubProvider(), rate_limiter=sentinel)
    assert svc._rate_limiter is sentinel


def test_cross_file_batch_indexing_and_progress_callback(
    tmp_path: Path,
    db_session: Session,
    test_user: User,
) -> None:
    inst = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=test_user.id,
        installation_id="inst-batch-1",
        account_login=test_user.login,
        permissions={"contents": "read"},
    )
    db_session.add(inst)
    db_session.commit()

    repo = Repository(
        id=uuid.uuid4(),
        user_id=test_user.id,
        installation_id=inst.id,
        github_repo_id=f"gh-batch-{uuid.uuid4().hex[:8]}",
        owner=test_user.login,
        name="batch-repo",
        default_branch="main",
        language="Python",
        sync_status=SyncStatus.SYNCING,
    )
    db_session.add(repo)
    db_session.commit()

    file_infos: list[FileInfo] = []
    for idx in range(12):
        rel = f"src/mod_{idx}.py"
        abs_file = tmp_path / rel
        abs_file.parent.mkdir(parents=True, exist_ok=True)
        abs_file.write_text(
            f"def func_{idx}(x: int) -> int:\n    return x + {idx}\n",
            encoding="utf-8",
        )
        file_infos.append(
            FileInfo(
                path=rel,
                size_bytes=abs_file.stat().st_size,
                language="Python",
                is_binary=False,
            )
        )

    embed_calls: list[int] = []

    class BatchCountingEmbeddingService:
        dimensions = 768
        profile_version = "v2"
        model_name = "models/gemini-embedding-001"

        async def embed_documents(self, texts: list[str], **_kwargs: Any) -> list[list[float]]:
            embed_calls.append(len(texts))
            return [[1.0] + [0.0] * 767 for _ in texts]

        async def embed_batch(self, texts: list[str], **_kwargs: Any) -> list[list[float]]:
            return await self.embed_documents(texts)

    progress_events: list[dict[str, Any]] = []

    async def on_progress(progress_stats: dict[str, Any]) -> None:
        progress_events.append(progress_stats)

    indexer = IncrementalIndexer(
        db_session=db_session,
        embedding_service=BatchCountingEmbeddingService(),
        file_batch_size=5,
    )

    stats = asyncio.run(
        indexer.sync(
            repo.id,
            file_infos,
            root_path=str(tmp_path),
            progress_callback=on_progress,
        )
    )

    # 12 files with file_batch_size=5 -> 3 batches (5, 5, 2) => 3 embedding calls, NOT 12.
    assert len(embed_calls) == 3
    assert stats["indexed"] == 12
    assert stats["chunks_embedded"] >= 12
    assert len(progress_events) == 3
    assert progress_events[-1]["current_file_index"] == 12
    assert progress_events[-1]["files_scanned"] == 12


def test_github_discovery_redis_cache_and_refresh(
    client: TestClient,
    db_session: Session,
    test_user: User,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inst = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=test_user.id,
        installation_id="99123",
        account_login=test_user.login,
        permissions={"contents": "read"},
    )
    db_session.add(inst)
    db_session.commit()

    cache_store: dict[str, str] = {}

    class FakeAsyncRedis:
        async def get(self, key: str) -> str | None:
            return cache_store.get(key)

        async def set(self, key: str, value: str, ex: int | None = None) -> bool:  # noqa: ARG002
            cache_store[key] = value
            return True

        async def delete(self, key: str) -> int:
            return 1 if cache_store.pop(key, None) is not None else 0

    github_calls = 0

    class FakeGitHubService:
        async def list_repositories(self, installation_id: int) -> list[Any]:  # noqa: ARG002
            nonlocal github_calls
            github_calls += 1
            return [
                SimpleNamespace(
                    id=501 + github_calls,
                    owner=test_user.login,
                    name=f"repo-{github_calls}",
                    full_name=f"{test_user.login}/repo-{github_calls}",
                    default_branch="main",
                    language="Python",
                )
            ]

    import app.api.v1.github as github_api

    async def _get_fake_redis() -> FakeAsyncRedis:
        return FakeAsyncRedis()

    monkeypatch.setattr(github_api, "get_redis_async", _get_fake_redis)
    prev_service = getattr(app.state, "github_service", None)
    app.state.github_service = FakeGitHubService()
    try:
        # 1st call misses Redis -> calls GitHub API and caches result
        r1 = client.get("/api/v1/github/repositories", headers=auth_headers)
        assert r1.status_code == 200
        assert github_calls == 1
        assert len(cache_store) == 1

        # 2nd call hits Redis -> does NOT call GitHub API
        r2 = client.get("/api/v1/github/repositories", headers=auth_headers)
        assert r2.status_code == 200
        assert github_calls == 1
        assert r2.json()["items"][0]["name"] == r1.json()["items"][0]["name"]

        # Connect the repo in DB, verify cached list still dynamically updates is_connected!
        connected = Repository(
            id=uuid.uuid4(),
            user_id=test_user.id,
            installation_id=inst.id,
            github_repo_id=r1.json()["items"][0]["github_repo_id"],
            owner=test_user.login,
            name=r1.json()["items"][0]["name"],
            default_branch="main",
            language="Python",
            sync_status=SyncStatus.NOT_SYNCED,
        )
        db_session.add(connected)
        db_session.commit()

        r3 = client.get("/api/v1/github/repositories", headers=auth_headers)
        assert r3.status_code == 200
        assert github_calls == 1
        assert r3.json()["items"][0]["is_connected"] is True

        # refresh=true bypasses Redis cache and calls GitHub API again
        r4 = client.get("/api/v1/github/repositories?refresh=true", headers=auth_headers)
        assert r4.status_code == 200
        assert github_calls == 2
    finally:
        app.state.github_service = prev_service


def _parse_sse_events(body_text: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in body_text.strip().split("\n\n"):
        if not block.strip():
            continue
        event_name = "message"
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].strip())
        if data_lines:
            events.append((event_name, json.loads("\n".join(data_lines))))
    return events


def test_all_four_analysis_stream_endpoints_emit_status_and_done(
    client: TestClient,
    db_session: Session,
    test_user: User,
    auth_headers: dict[str, str],
) -> None:
    inst = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=test_user.id,
        installation_id="inst-sse-1",
        account_login=test_user.login,
        permissions={"contents": "read"},
    )
    db_session.add(inst)
    db_session.commit()

    repo = Repository(
        id=uuid.uuid4(),
        user_id=test_user.id,
        installation_id=inst.id,
        github_repo_id="gh-sse-1",
        owner=test_user.login,
        name="sse-repo",
        default_branch="main",
        language="Python",
        sync_status=SyncStatus.SYNCED,
    )
    db_session.add(repo)
    db_session.commit()

    src_file = RepositoryFile(
        id=uuid.uuid4(),
        repository_id=repo.id,
        path="src/calc.py",
        language="Python",
        size_bytes=80,
        line_count=4,
        content_hash="sse-hash",
    )
    db_session.add(src_file)
    db_session.commit()
    db_session.add(
        CodeChunk(
            id=uuid.uuid4(),
            repository_id=repo.id,
            file_id=src_file.id,
            content="def add(a: int, b: int) -> int:\n    return a + b\n",
            content_hash="sse-chunk-hash",
            start_line=1,
            end_line=2,
            token_count=12,
            embedding=[0.1] * 768,
        )
    )
    db_session.commit()

    class StubExplainService:
        async def explain(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            return {
                "purpose": "Simple addition helper.",
                "logic_flow": ["Accepts two integers", "Returns their sum"],
                "key_symbols": [],
                "inputs_and_outputs": "Input: a, b (int). Output: sum (int).",
                "dependencies": [],
                "assumptions_and_limitations": [],
                "sources": [],
                "confidence": "high",
            }

    class StubBugService:
        async def detect_bugs(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            return {"status": "COMPLETED", "findings": [], "missing_context": []}

    class StubTestService:
        async def generate_tests(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            return {
                "detected_framework": "pytest",
                "proposed_test_path": "tests/test_calc.py",
                "test_content": "def test_add():\n    assert 1 + 1 == 2\n",
                "covered_scenarios": [{"name": "test_add", "category": "normal", "description": "Adds two ints"}],
                "assumptions": [],
            }

    class StubReviewService:
        async def review(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            return {
                "summary": "Clean helper implementation.",
                "risk_level": "LOW",
                "findings": [],
                "missing_context": [],
            }

    saved = {
        "explanation_service": getattr(app.state, "explanation_service", None),
        "bug_detection_service": getattr(app.state, "bug_detection_service", None),
        "test_generation_service": getattr(app.state, "test_generation_service", None),
        "code_review_service": getattr(app.state, "code_review_service", None),
    }
    app.state.explanation_service = StubExplainService()
    app.state.bug_detection_service = StubBugService()
    app.state.test_generation_service = StubTestService()
    app.state.code_review_service = StubReviewService()

    try:
        cases = [
            (
                f"/api/v1/repositories/{repo.id}/explain/stream",
                {"target": {"type": "file", "path": "src/calc.py"}, "options": {"persist_run": False}},
                "retrieving_context",
            ),
            (
                f"/api/v1/repositories/{repo.id}/detect-bugs/stream",
                {"target": {"type": "file", "path": "src/calc.py"}, "include_static": False, "options": {"persist_run": False}},
                "retrieving_context",
            ),
            (
                f"/api/v1/repositories/{repo.id}/generate-tests/stream",
                {"target": {"type": "file", "path": "src/calc.py"}, "run_isolated_execution": False, "options": {"persist_run": False}},
                "detecting_framework",
            ),
            (
                f"/api/v1/repositories/{repo.id}/review/stream",
                {"target": {"type": "file", "path": "src/calc.py"}, "include_static": False, "options": {"persist_run": False}},
                "validating_grounding",
            ),
        ]

        for endpoint, body, expected_stage in cases:
            res = client.post(endpoint, json=body, headers=auth_headers)
            assert res.status_code == 200, f"{endpoint} returned {res.status_code}: {res.text}"
            assert "text/event-stream" in res.headers.get("content-type", "")
            events = _parse_sse_events(res.text)
            stages = [data.get("stage") for name, data in events if name == "status"]
            done_events = [data for name, data in events if name == "done"]
            assert expected_stage in stages, f"Expected stage {expected_stage} in {stages}"
            assert len(done_events) == 1, f"{endpoint} events={events}"
            assert done_events[0]["repository_id"] == str(repo.id)
    finally:
        for attr, val in saved.items():
            setattr(app.state, attr, val)


def test_switch_repository_branch_endpoint(
    client: TestClient,
    db_session: Session,
    test_user: User,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inst = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=test_user.id,
        installation_id="998877",
        account_login=test_user.login,
        permissions={"contents": "read"},
    )
    db_session.add(inst)
    db_session.commit()

    repo = Repository(
        id=uuid.uuid4(),
        user_id=test_user.id,
        installation_id=inst.id,
        github_repo_id="gh-branch-switch-1",
        owner=test_user.login,
        name="branch-repo",
        default_branch="main",
        language="Python",
        sync_status=SyncStatus.SYNCED,
        last_indexed_commit_sha="deadbeef1234",
    )
    db_session.add(repo)
    db_session.commit()

    class FakeGitHubService:
        async def list_branches(self, owner: str, name: str, installation_id: int) -> list[Any]:  # noqa: ARG002
            return [
                SimpleNamespace(name="main", sha="aaa111", protected=True),
                SimpleNamespace(name="feature/new-ui", sha="bbb222", protected=False),
            ]

    class FakeRedis:
        def __init__(self) -> None:
            self.pushed: list[tuple[str, Any]] = []
            self.published: list[tuple[str, Any]] = []

        def rpush(self, key: str, val: Any) -> int:
            self.pushed.append((key, val))
            return 1

        def lpush(self, key: str, val: Any) -> int:
            self.pushed.append((key, val))
            return 1

        def publish(self, channel: str, msg: Any) -> int:
            self.published.append((channel, msg))
            return 1

    import app.api.v1.repositories as repos_api

    fake_redis = FakeRedis()
    monkeypatch.setattr(repos_api, "get_redis", lambda: fake_redis)
    prev_service = getattr(app.state, "github_service", None)
    app.state.github_service = FakeGitHubService()

    try:
        # 1. Invalid branch name -> 422
        r_invalid = client.patch(
            f"/api/v1/repositories/{repo.id}/branch",
            json={"branch": "../escape"},
            headers=auth_headers,
        )
        assert r_invalid.status_code == 422

        # 2. Same branch -> no-op, switched=False
        r_same = client.patch(
            f"/api/v1/repositories/{repo.id}/branch",
            json={"branch": "main"},
            headers=auth_headers,
        )
        assert r_same.status_code == 200
        assert r_same.json()["switched"] is False
        assert r_same.json()["job_id"] is None

        # 3. Missing branch on GitHub -> 404
        r_missing = client.patch(
            f"/api/v1/repositories/{repo.id}/branch",
            json={"branch": "does-not-exist"},
            headers=auth_headers,
        )
        assert r_missing.status_code == 404

        # 4. Valid branch switch -> updates default_branch, clears commit sha, queues sync
        r_ok = client.patch(
            f"/api/v1/repositories/{repo.id}/branch",
            json={"branch": "feature/new-ui"},
            headers=auth_headers,
        )
        assert r_ok.status_code == 200, r_ok.text
        data = r_ok.json()
        assert data["switched"] is True
        assert data["branch"] == "feature/new-ui"
        assert data["job_id"] is not None
        assert data["repository"]["default_branch"] == "feature/new-ui"
        assert data["repository"]["sync_status"] == "SYNCING"

        db_session.refresh(repo)
        assert repo.default_branch == "feature/new-ui"
        assert repo.last_indexed_commit_sha is None
    finally:
        app.state.github_service = prev_service
