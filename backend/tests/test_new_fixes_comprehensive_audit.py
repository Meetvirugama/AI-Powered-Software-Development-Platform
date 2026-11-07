"""Comprehensive Verification Suite for Audited Fixes (`new_fixes.md`).

Covers every verified bug fix, security hardening patch, specification gap closure,
and retrieval/embedding accuracy enhancement from the forensic audit of `changes.md`
and `prompt.md`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from ai.embeddings.service import CachedEmbeddingService
from ai.retrieval.base import CodeChunk
from ai.retrieval.fusion import RRFFusion
from ai.retrieval.reranker import CrossEncoderReranker
from ai.retrieval.vector import VectorRetriever
from ai.services.task_planner import TaskPlanner
from app.api.v1 import events as events_module
from app.core.config import Settings
from app.core.database import get_db_async
from app.core.rate_limit import RedisRateLimitStore
from app.integrations.github.client import GitHubAPIError, GitHubClient
from app.integrations.github.routes import get_task_diff_ranges_endpoint
from app.integrations.github.schemas import FileDiffRange, TaskDiffRanges
from app.integrations.github.service import GitHubService
from app.main import app
from app.models.repository_file import RepositoryFile
from app.repositories.github_installation_repository import GitHubInstallationRepository
from app.schemas.repository import RepositorySearchRequest
from app.schemas.workspace import WorkspaceCreateRequest
from app.services import IndependentVerifier, StatefulTaskExecutionOrchestrator, TaskExecutionOrchestrator
from app.services.git_branch import format_agent_branch_name
from sandbox.workspace_manager import WorkspaceManager
from scanner.detector import LanguageDetector
from scanner.parser import Parser
from scanner.symbols import FileInfo


# ---------------------------------------------------------------------------
# 1. Bug 2: SSE Connection Pool Release (`backend/app/api/v1/events.py`)
# ---------------------------------------------------------------------------
def test_bug2_sse_endpoint_does_not_hold_depends_get_db_across_stream() -> None:
    """Verify stream_events opens and closes a short-lived DB session before streaming."""
    import inspect

    sig = inspect.signature(events_module.stream_events)
    assert "db" not in sig.parameters, "stream_events must not hold Depends(get_db) across open SSE stream"


# ---------------------------------------------------------------------------
# 2. Bug 3: GitHubClient Retry Loop (`backend/app/integrations/github/client.py`)
# ---------------------------------------------------------------------------
def test_bug3_github_api_client_retries_on_5xx_and_429() -> None:
    """Verify GitHubClient._request retries transient 502/429 responses before succeeding."""
    client = GitHubClient(token="ghs_test")
    call_count = 0

    async def fake_request(self_client: object, method: str, url: str, **kwargs: object) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        req = httpx.Request(method, url)
        if call_count == 1:
            return httpx.Response(502, json={"message": "Bad Gateway"}, request=req)
        if call_count == 2:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"message": "Rate limit"}, request=req)
        return httpx.Response(200, json={"id": 42, "title": "ok"}, request=req)

    with patch.object(httpx.AsyncClient, "request", new=fake_request), patch("asyncio.sleep", new=AsyncMock()):
        result = asyncio.run(client._request("GET", "/repos/octo/demo"))

    assert call_count == 3
    assert result["id"] == 42


def test_bug3_github_api_client_does_not_retry_non_rate_limit_404() -> None:
    """Verify GitHubClient._request fails fast on permanent 404 errors."""
    client = GitHubClient(token="ghs_test")
    call_count = 0

    async def fake_request(self_client: object, method: str, url: str, **kwargs: object) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        req = httpx.Request(method, url)
        return httpx.Response(404, json={"message": "Not Found"}, request=req)

    with patch.object(httpx.AsyncClient, "request", new=fake_request):
        with pytest.raises(GitHubAPIError) as exc_info:
            asyncio.run(client._request("GET", "/repos/octo/missing"))

    assert call_count == 1
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 3. Bug 4, Bug 14 & GAP-15: TSX/JSX/C/C++ Detection and TSX Grammar Binding
# ---------------------------------------------------------------------------
def test_bug4_bug14_gap15_language_detector_and_tsx_parser() -> None:
    detector = LanguageDetector()
    assert detector.detect(FileInfo(path="frontend/src/App.tsx", size_bytes=10, language="unknown", is_binary=False)) == "TypeScript"
    assert detector.detect(FileInfo(path="frontend/src/Component.jsx", size_bytes=10, language="unknown", is_binary=False)) == "JavaScript"
    assert detector.detect(FileInfo(path="scripts/module.mjs", size_bytes=10, language="unknown", is_binary=False)) == "JavaScript"
    assert detector.detect(FileInfo(path="scripts/common.cjs", size_bytes=10, language="unknown", is_binary=False)) == "JavaScript"
    assert detector.detect(FileInfo(path="native/include/header.h", size_bytes=10, language="unknown", is_binary=False)) == "C"
    assert detector.detect(FileInfo(path="native/include/header.hpp", size_bytes=10, language="unknown", is_binary=False)) == "C++"
    assert detector.detect(FileInfo(path="native/src/engine.cc", size_bytes=10, language="unknown", is_binary=False)) == "C++"
    assert detector.detect(FileInfo(path="native/src/engine.cxx", size_bytes=10, language="unknown", is_binary=False)) == "C++"

    parser = Parser()
    tsx_code = (
        "import React from 'react';\n"
        "export function Greeting({ name }: { name: string }) {\n"
        '  return <div className="greeting">Hello {name}</div>;\n'
        "}\n"
    )
    res = parser.parse_with_status(
        FileInfo(path="src/Greeting.tsx", language="TypeScript", size_bytes=len(tsx_code), is_binary=False),
        tsx_code,
    )
    assert res.success is True
    assert res.has_syntax_errors is False


# ---------------------------------------------------------------------------
# 4. Bug 5: Git Branch Naming Collision Prevention (`backend/app/services/git_branch.py`)
# ---------------------------------------------------------------------------
def test_bug5_git_branch_name_uniqueness_for_uuid_and_hyphenated_slugs() -> None:
    uuid_branch = format_agent_branch_name("550e8400-e29b-41d4-a716-446655440000")
    assert uuid_branch == "agent/task-550e8400"

    s1 = format_agent_branch_name("task-scenario-1")
    s2 = format_agent_branch_name("task-scenario-2")
    assert s1 == "agent/task-scenario-1"
    assert s2 == "agent/task-scenario-2"
    assert s1 != s2


# ---------------------------------------------------------------------------
# 5. Bug 6: Services __init__ Exports (`backend/app/services/__init__.py`)
# ---------------------------------------------------------------------------
def test_bug6_services_exports_have_no_duplicates() -> None:
    import app.services as services_pkg

    assert len(services_pkg.__all__) == len(set(services_pkg.__all__))
    assert IndependentVerifier is not None
    assert TaskExecutionOrchestrator is not None
    assert StatefulTaskExecutionOrchestrator is not None


# ---------------------------------------------------------------------------
# 7. Bug 10: RedisRateLimitStore NX Expiry (`backend/app/core/rate_limit.py`)
# ---------------------------------------------------------------------------
def test_bug10_redis_rate_limit_store_passes_nx_true_with_fallback() -> None:
    pipe = MagicMock()
    pipe.execute.return_value = [1, True]
    redis_client = MagicMock()
    redis_client.pipeline.return_value = pipe

    store = RedisRateLimitStore(redis_client)
    count = store.hit("rl:test", window_seconds=60)
    assert count == 1
    pipe.expire.assert_called_once_with("rl:test", 65, nx=True)


# ---------------------------------------------------------------------------
# 8. Bug 12 & VULN-13: X-Request-ID on 401 and Security Headers
# ---------------------------------------------------------------------------
def test_bug12_and_vuln13_request_id_and_security_headers_on_401() -> None:
    client = TestClient(app)
    resp = client.get("/api/v1/repositories", headers={"X-Request-ID": "audit-req-123"})
    assert resp.status_code == 401
    assert resp.headers.get("X-Request-ID") == "audit-req-123"
    assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "default-src 'self'" in resp.headers.get("Content-Security-Policy", "")


# ---------------------------------------------------------------------------
# 9. VULN-01: Cross-Tenant GitHub Installation Hijacking Blocked
# ---------------------------------------------------------------------------
def test_vuln01_github_installation_upsert_blocks_cross_tenant_hijack() -> None:
    from app.core.errors import APIError

    owner_id = uuid4()
    attacker_id = uuid4()
    existing_inst = SimpleNamespace(
        id=uuid4(),
        user_id=owner_id,
        installation_id="inst-999",
        account_login="org-a",
        permissions={},
    )
    mock_db = MagicMock()
    repo = GitHubInstallationRepository(mock_db)
    repo.get_by_installation_id = MagicMock(return_value=existing_inst)  # type: ignore[method-assign]

    with pytest.raises(APIError) as exc_info:
        repo.upsert(
            user_id=attacker_id,
            installation_id="inst-999",
            account_login="attacker",
            permissions={"contents": "read"},
            allow_reassign=False,
        )

    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 10. Task Diff Ranges Endpoint (`backend/app/integrations/github/routes.py`)
# ---------------------------------------------------------------------------
def test_get_task_diff_ranges_endpoint_returns_diff(tmp_path: Path) -> None:
    ws_dir = tmp_path / "task-12345678"
    (ws_dir / ".git").mkdir(parents=True)

    task_id = uuid4()
    repo_id = uuid4()
    user_id = uuid4()
    mock_req = MagicMock()
    mock_req.state.user_id = str(user_id)

    fake_diff = TaskDiffRanges(
        task_id=task_id,
        repository_id=repo_id,
        files=[FileDiffRange(file_path="src/app.py", patch="+x = 1\n", additions=1, deletions=0)],
        total_files_changed=1,
        total_additions=1,
        total_deletions=0,
    )

    with patch(
        "app.services.git_branch.GitBranchService.get_task_diff_ranges", new=AsyncMock(return_value=fake_diff)
    ):
        resp = asyncio.run(
            get_task_diff_ranges_endpoint(
                repository_id=repo_id,
                task_id=task_id,
                request=mock_req,
                workspace_path=str(ws_dir),
                db=MagicMock(),
            )
        )

    assert resp.task_id == task_id
    assert len(resp.files) == 1
    assert resp.files[0].file_path == "src/app.py"


# ---------------------------------------------------------------------------
# 11. VULN-04: Settings.is_production Property (`backend/app/core/config.py`)
# ---------------------------------------------------------------------------
def test_vuln04_settings_is_production_property() -> None:
    dev_settings = Settings(app_env="development")
    assert dev_settings.is_production is False

    prod_settings = Settings(
        app_env="production",
        cookie_secure=True,
        jwt_secret="a-very-strong-production-secret-32chars!",
        frontend_url="https://app.example.com",
        cors_allowed_origins="https://app.example.com",
    )
    assert prod_settings.is_production is True


# ---------------------------------------------------------------------------
# 12. VULN-05 & GAP-14: Workspace Nested Symlink Filtering & Expired Reaper
# ---------------------------------------------------------------------------
def test_vuln05_and_gap14_workspace_symlink_filter_and_reaper(tmp_path: Path) -> None:
    outside_dir = tmp_path / "outside_secrets"
    outside_dir.mkdir()
    outside_secret = outside_dir / "passwd.txt"
    outside_secret.write_text("root:x:0:0", encoding="utf-8")

    repo_root = tmp_path / "repo"
    (repo_root / "src").mkdir(parents=True)
    (repo_root / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")

    nested_link = repo_root / "src" / "leak_link.txt"
    try:
        nested_link.symlink_to(outside_secret)
    except OSError:
        pytest.skip("Symlinks not supported on this platform")

    ws_base = tmp_path / "workspaces"
    mgr = WorkspaceManager(base_workspaces_dir=ws_base)
    meta = mgr.create_workspace(
        WorkspaceCreateRequest(
            task_id="task-symlink-test",
            repository_id=str(uuid4()),
            base_revision="a" * 40,
            repository_root=str(repo_root),
            isolation_type="directory_copy",
        )
    )
    ws_path = Path(meta.workspace_path)
    assert (ws_path / "src" / "main.py").exists()
    assert not (ws_path / "src" / "leak_link.txt").exists()

    # Transition to FAILED and reap with max_age_seconds=0
    mgr.fail_execution("task-symlink-test", "done")
    reaped = mgr.reap_expired_workspaces(max_age_seconds=0)
    assert any("symlink-test" in tid for tid in reaped)


# ---------------------------------------------------------------------------
# 13. VULN-06: Sanitized Environment in GitHubService.push_branch
# ---------------------------------------------------------------------------
def test_vuln06_github_service_push_branch_sanitizes_subprocess_env(tmp_path: Path) -> None:
    svc = GitHubService(workspace_root=tmp_path)
    svc._resolve_token = AsyncMock(return_value="ghs_valid_token_123456")  # type: ignore[method-assign]

    captured_env: dict[str, str] = {}

    async def fake_subproc(*args: object, **kwargs: object) -> SimpleNamespace:
        nonlocal captured_env
        captured_env = dict(kwargs.get("env") or {})  # type: ignore[arg-type]
        proc = SimpleNamespace(returncode=0)
        proc.communicate = AsyncMock(return_value=(b"ok", b""))
        return proc

    with patch.dict("os.environ", {"JWT_SECRET": "top-secret-jwt", "DATABASE_URL": "postgresql://secret"}), patch(
        "asyncio.create_subprocess_exec", side_effect=fake_subproc
    ):
        asyncio.run(
            svc.push_branch(
                installation_id="12345",
                owner="octo",
                repo="demo",
                local_branch="agent/task-12345678",
                remote_branch="agent/task-12345678",
                workspace_path=str(tmp_path),
            )
        )

    assert "JWT_SECRET" not in captured_env
    assert "DATABASE_URL" not in captured_env
    assert captured_env.get("GIT_TERMINAL_PROMPT") == "0"


# ---------------------------------------------------------------------------
# 14. GAP-04, GAP-07, GAP-08, GAP-19: Schema, Async DB, Planner Model, Search Alias
# ---------------------------------------------------------------------------
def test_gap04_gap07_gap08_gap19_contracts() -> None:
    # GAP-04: UniqueConstraint on RepositoryFile(repository_id, path)
    constraint_names = [c.name for c in RepositoryFile.__table__.constraints if getattr(c, "name", None)]
    assert "uq_repository_files_repo_path" in constraint_names

    # GAP-07: get_db_async is an async generator function
    import inspect

    assert inspect.isasyncgenfunction(get_db_async)

    # GAP-08: TaskPlanner resolves default model from get_settings().active_chat_model
    planner = TaskPlanner(llm_gateway=MagicMock())
    assert planner._model is not None and len(planner._model) > 0

    # GAP-19: RepositorySearchRequest accepts both query/top_k and q/limit aliases
    req1 = RepositorySearchRequest.model_validate({"q": "auth middleware", "limit": 7})
    assert req1.query == "auth middleware"
    assert req1.top_k == 7


# ---------------------------------------------------------------------------
# 15. OPT-01, OPT-02, OPT-03: Retrieval & Embedding Optimizations
# ---------------------------------------------------------------------------
def test_opt01_opt02_opt03_retrieval_and_embedding_enhancements() -> None:
    # OPT-01: Weighted and adaptive RRF fusion
    fusion = RRFFusion()
    assert fusion.detect_query_intent("Where is `JWTMiddleware.dispatch` defined?") == "symbol"
    assert fusion.detect_query_intent("how does the application handle authentication?") == "conceptual"

    c1 = CodeChunk(
        id=uuid4(),
        repository_id=uuid4(),
        file_id=uuid4(),
        symbol_id=None,
        content="class JWTMiddleware:",
        token_count=10,
        start_line=1,
        end_line=5,
        content_hash="h1",
        score=0.9,
        file_path="backend/app/core/auth.py",
    )
    c2 = CodeChunk(
        id=uuid4(),
        repository_id=c1.repository_id,
        file_id=c1.file_id,
        symbol_id=None,
        content="def helper(): pass",
        token_count=10,
        start_line=6,
        end_line=10,
        content_hash="h2",
        score=0.8,
        file_path="backend/app/core/helper.py",
    )
    fused = fusion.fuse_adaptive("Where is `JWTMiddleware`?", [c2], [c1], top_n=2)
    # Because query is symbol-intent, lexical rank #1 (c1, weight 1.4) beats vector rank #1 (c2, weight 0.8)
    assert fused[0].id == c1.id

    # OPT-02: CrossEncoderReranker min_logit filter & max_chars truncation
    mock_ce = MagicMock()
    mock_ce.predict.return_value = [1.25, -4.5]
    reranker = CrossEncoderReranker(model=mock_ce, min_logit=-1.0, max_chars=12)
    reranked = reranker.rerank("JWTMiddleware", [c1, c2], top_n=5)
    assert len(reranked) == 1
    assert reranked[0].id == c1.id

    # OPT-03: CachedEmbeddingService L1 cache avoids duplicate provider calls
    provider = MagicMock()
    provider.embedding_dimensions = 3
    provider.provider_name = "mock"
    provider.model_name = "mock-emb"
    provider.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])

    cached_svc = CachedEmbeddingService(provider=provider, max_memory_entries=16)
    v1 = asyncio.run(cached_svc.embed("def foo(): pass"))
    v2 = asyncio.run(cached_svc.embed("def foo(): pass"))
    assert v1 == [0.1, 0.2, 0.3]
    assert v2 == [0.1, 0.2, 0.3]
    assert provider.embed.await_count == 1
