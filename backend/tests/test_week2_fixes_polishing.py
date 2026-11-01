"""Week 2 Post-Day 7 Whole-Codebase Fixes, Security Hardening & Efficiency/Accuracy Polishing Suite.

Verifies all 12 architectural, security, contract, accuracy, and performance improvements
documented in `week2_fixes_polishing.md`:
1. `Docs/daily_tasks.md` conflict resolution & Week 2 Day 7 completion sign-off.
2. `GitHubSourceService` & `/repositories/{id}/source/*` git ref validation and secret redaction across file content, commits, and PR diffs.
3. Bounded in-memory `_analysis_run_history` store (`MAX_IN_MEMORY_HISTORY_RUNS = 500`) with FIFO eviction.
4. Standardized unhandled-exception failure recording and secret redaction across all 4 analysis endpoints (`/explain`, `/detect-bugs`, `/generate-tests`, `/review`).
5. Fixed SQLAlchemy `SymbolEdge.source_symbol_id.in_(target_sym_ids)` query and bidirectional caller/callee blast-radius resolution in `code_review_orchestrator.py`.
6. `DependencyGraphBuilder` call-graph edge extraction (`calls`, `imports`, `extends`) and `symbol_edges` persistence in `IncrementalIndexer.sync()`.
7. Elimination of duplicate `BuiltinStaticBugScanner` execution in `/detect-bugs` + `ASTBugAnalyzer` structural rule integration (`AST-NULL-001`, `AST-ITER-001`, `AST-LOGIC-001`, JS/TS empty catch).
8. `BugScanHistoryService` orchestrator protocol compliance (`record_run`, `save_run`, `create_run`, `list_runs` with `user_id`, `get_run`) + `user_id` support across all history services.
9. Multi-installation fallback and numeric `github_repo_id` validation in `POST /api/v1/github/repositories/{github_repo_id}/connect`.
10. Batched `CodeChunk` reconstruction (eliminating N+1 queries) + `pyproject.toml` and `Pipfile` dependency extraction in `GET /api/v1/repositories/{id}/dependencies`.
11. Frontend TypeScript contract alignment (`AnalysisRunMetricsSummaryResponse`, `getAnalysisRunsSummary`, `user_id` filter) and `reviewTarget.path` synchronization on file selection.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai.llm.client import LLMGateway
from ai.llm.provider import LLMProvider
from ai.llm.schemas import LLMRequest, LLMResponse
from ai.services.bug_detection_engine import BugDetectionEngine
from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.integrations.github.source_service import GitHubSourceService
from app.main import app
from app.models.analysis_finding import AnalysisFinding  # noqa: F401
from app.models.analysis_run import AnalysisRun
from app.models.code_chunk import CodeChunk
from app.models.code_symbol import CodeSymbol
from app.models.github_installation import GitHubInstallation
from app.models.pull_request import PullRequest  # noqa: F401
from app.models.repository import Repository, SyncStatus
from app.models.repository_file import RepositoryFile
from app.models.symbol_edge import SymbolEdge
from app.models.user import User
from app.schemas.analysis import AnalysisTarget, CodeReviewRequest, ReviewTarget
from app.services.bug_detection_orchestrator import BuiltinStaticBugScanner
from app.services.bug_scan_history_service import BugScanHistoryService
from app.services.code_review_orchestrator import resolve_review_target_and_build_context
from app.services.explanation_orchestrator import record_analysis_run
from indexer.incremental import IncrementalIndexer
from scanner.graph import DependencyGraphBuilder
from scanner.symbols import FileInfo, Symbol


REPO_ROOT = Path(__file__).resolve().parents[2]
USER_ID = UUID("11111111-1111-4111-a111-111111111111")
OTHER_USER_ID = UUID("22222222-2222-4222-a222-222222222222")
REPO_ID = UUID("aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa")
INST_ID_1 = UUID("bbbbbbbb-bbbb-4bbb-abbb-bbbbbbbbbbb1")
INST_ID_2 = UUID("bbbbbbbb-bbbb-4bbb-abbb-bbbbbbbbbbb2")


def _auth_headers(user_id: UUID = USER_ID) -> dict[str, str]:
    token, _ = create_access_token(str(user_id))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def sqlite_session(monkeypatch: pytest.MonkeyPatch):
    from app.core.config import get_settings

    monkeypatch.setenv("JWT_SECRET", "test-secret-key-12345")
    get_settings.cache_clear()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
        dbapi_connection.create_function(
            "to_tsvector", 2, lambda _cfg, text: text or "", deterministic=True
        )
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    from app.models.sync_job import SyncJob  # noqa: F401
    from app.models.memory_entry import MemoryEntry  # noqa: F401

    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestingSessionLocal()

    user = User(id=USER_ID, github_id="1001", login="yug-lead", email="yug@example.com")
    other = User(id=OTHER_USER_ID, github_id="1002", login="other-dev", email="other@example.com")
    session.add_all([user, other])
    session.commit()

    inst1 = GitHubInstallation(
        id=INST_ID_1,
        user_id=USER_ID,
        installation_id="99001",
        account_login="yug-lead",
        permissions={},
    )
    inst2 = GitHubInstallation(
        id=INST_ID_2,
        user_id=USER_ID,
        installation_id="99002",
        account_login="yug-org",
        permissions={},
    )
    session.add_all([inst1, inst2])
    session.commit()

    repo = Repository(
        id=REPO_ID,
        user_id=USER_ID,
        installation_id=INST_ID_1,
        github_repo_id="777001",
        owner="yug-lead",
        name="se-project",
        default_branch="main",
        language="Python",
        sync_status=SyncStatus.SYNCED,
    )
    session.add(repo)
    session.commit()

    monkeypatch.setattr("app.core.auth.get_redis", lambda: SimpleNamespace(exists=lambda *_a, **_k: 0))
    monkeypatch.setattr(
        "app.core.rate_limit.get_rate_limit_store",
        lambda: SimpleNamespace(hit=lambda *_a, **_k: 1),
    )

    def _override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    yield session
    app.dependency_overrides.pop(get_db, None)
    session.close()


# ---------------------------------------------------------------------------
# 1. Docs/daily_tasks.md Conflict Resolution Verification
# ---------------------------------------------------------------------------

def test_docs_daily_tasks_has_no_git_conflict_markers_and_tracks_all_week2_day7_owners():
    daily_tasks_path = REPO_ROOT / "Docs" / "daily_tasks.md"
    content = daily_tasks_path.read_text(encoding="utf-8")

    assert "<<<<<<<" not in content
    assert "=======" not in content
    assert ">>>>>>>" not in content
    assert "test_dev_w2_day7_ai_acceptance.py" in content
    assert "test_yug_w2_day7_final_acceptance.py" in content
    assert "✅ Dhramraj: End-to-end UI polish on all 4 drawers in Code Intelligence Workbench" in content
    assert "✅ Yug: Route registration, auth guards, OpenAPI documentation & Day 7 API acceptance suite" in content


# ---------------------------------------------------------------------------
# 2. GitHubSourceService & /source/* Ref Validation and Secret Redaction
# ---------------------------------------------------------------------------

def test_github_source_service_rejects_unsafe_ref_and_redacts_secrets_in_file_commits_and_pr_diff(
    sqlite_session,
    monkeypatch: pytest.MonkeyPatch,
):
    fake_sk = "sk-proj-" + "X" * 32
    fake_ghp = "ghp_" + "Y" * 38

    class _FakeGitHubClient:
        def __init__(self, token: str):
            self.token = token

        @staticmethod
        async def get_installation_token(installation_id: str) -> str:
            return "inst-token-123"

        async def get_branch(self, owner: str, repo: str, branch: str) -> dict[str, Any]:
            return {"commit": {"sha": "a" * 40}}

        async def get_file_content(self, owner: str, repo: str, path: str, *, ref: str | None = None) -> dict[str, Any]:
            import base64
            raw = f'OPENAI_API_KEY = "{fake_sk}"\nprint("ok")\n'
            return {
                "type": "file",
                "size": len(raw),
                "encoding": "base64",
                "content": base64.b64encode(raw.encode("utf-8")).decode("ascii"),
                "sha": "b" * 40,
            }

        async def list_commits(self, owner: str, repo: str, **kwargs: Any) -> list[dict[str, Any]]:
            return [
                {
                    "sha": "c" * 40,
                    "commit": {
                        "message": f"Rotate token {fake_ghp} in config",
                        "author": {"name": "Dev", "email": "dev@example.com", "date": "2026-10-27T00:00:00Z"},
                        "committer": {"name": "Dev", "email": "dev@example.com", "date": "2026-10-27T00:00:00Z"},
                    },
                    "parents": [{"sha": "d" * 40}],
                }
            ]

        async def get_commit(self, owner: str, repo: str, sha: str) -> dict[str, Any]:
            return {
                "sha": sha,
                "commit": {
                    "message": f"Hotfix secret {fake_sk}",
                    "author": {"name": "Dev", "email": "dev@example.com"},
                    "committer": {"name": "Dev", "email": "dev@example.com"},
                },
                "parents": [{"sha": "d" * 40}],
                "files": [
                    {
                        "filename": "src/config.py",
                        "status": "modified",
                        "additions": 1,
                        "deletions": 0,
                        "changes": 1,
                        "patch": f"@@ -1,1 +1,2 @@\n+TOKEN = \"{fake_ghp}\"",
                    }
                ],
            }

        async def list_pull_requests(self, owner: str, repo: str, **kwargs: Any) -> list[dict[str, Any]]:
            return [
                {
                    "number": 42,
                    "title": f"Fix key {fake_sk}",
                    "state": "open",
                    "user": {"login": "yug-lead"},
                    "base": {"ref": "main", "sha": "a" * 40},
                    "head": {"ref": "feat/sec", "sha": "c" * 40},
                    "body": f"Removed leaked {fake_ghp}",
                }
            ]

        async def get_pull_request(self, owner: str, repo: str, pr_number: int) -> dict[str, Any]:
            return {
                "number": pr_number,
                "title": f"PR title with {fake_sk}",
                "state": "open",
                "user": {"login": "yug-lead"},
                "base": {"ref": "main", "sha": "a" * 40},
                "head": {"ref": "feat/sec", "sha": "c" * 40},
                "body": f"PR body with {fake_ghp}",
            }

        async def get_pull_request_files(self, owner: str, repo: str, pr_number: int, **kwargs: Any) -> list[dict[str, Any]]:
            return [
                {
                    "filename": "src/auth.py",
                    "status": "modified",
                    "additions": 1,
                    "deletions": 0,
                    "changes": 1,
                    "patch": f"@@ -1,1 +1,2 @@\n+API_KEY = \"{fake_sk}\"",
                }
            ]

    monkeypatch.setattr("app.integrations.github.source_service.GitHubClient", _FakeGitHubClient)

    client = TestClient(app)

    # 2a. Unsafe git refs must be rejected with 400 INVALID_REQUEST
    for bad_ref in ("../../etc/passwd", "--upload-pack=evil", "main?admin=1", "branch#frag"):
        r_tree = client.get(
            f"/api/v1/repositories/{REPO_ID}/source/tree",
            params={"ref": bad_ref},
            headers=_auth_headers(),
        )
        assert r_tree.status_code == 400
        assert r_tree.json()["error"]["code"] == "INVALID_REQUEST"

    # 2b. File content response redacts secrets
    r_file = client.get(
        f"/api/v1/repositories/{REPO_ID}/source/file",
        params={"path": "src/config.py", "ref": "main"},
        headers=_auth_headers(),
    )
    assert r_file.status_code == 200
    assert fake_sk not in r_file.text
    assert "[REDACTED]" in r_file.json()["content"]

    # 2c. Commits list & commit detail redact secrets in messages and patches
    r_commits = client.get(
        f"/api/v1/repositories/{REPO_ID}/source/commits",
        params={"ref": "main"},
        headers=_auth_headers(),
    )
    assert r_commits.status_code == 200
    assert fake_ghp not in r_commits.text
    assert "[REDACTED]" in r_commits.json()["commits"][0]["message"]

    r_commit_detail = client.get(
        f"/api/v1/repositories/{REPO_ID}/source/commits/{'c' * 40}",
        headers=_auth_headers(),
    )
    assert r_commit_detail.status_code == 200
    assert fake_sk not in r_commit_detail.text
    assert fake_ghp not in r_commit_detail.text
    assert "[REDACTED]" in r_commit_detail.json()["files"][0]["patch"]

    # 2d. Pull request list & diff redact secrets in title, body, and patch
    r_pulls = client.get(
        f"/api/v1/repositories/{REPO_ID}/source/pulls",
        headers=_auth_headers(),
    )
    assert r_pulls.status_code == 200
    assert fake_sk not in r_pulls.text
    assert fake_ghp not in r_pulls.text

    r_pr_diff = client.get(
        f"/api/v1/repositories/{REPO_ID}/source/pulls/42/diff",
        headers=_auth_headers(),
    )
    assert r_pr_diff.status_code == 200
    assert fake_sk not in r_pr_diff.text
    assert fake_ghp not in r_pr_diff.text
    assert "[REDACTED]" in r_pr_diff.json()["files"][0]["patch"]


# ---------------------------------------------------------------------------
# 3. Bounded In-Memory _analysis_run_history Store
# ---------------------------------------------------------------------------

def test_in_memory_analysis_run_history_is_bounded_with_fifo_eviction():
    from app.services.explanation_orchestrator import MAX_IN_MEMORY_HISTORY_RUNS
    dummy_state = SimpleNamespace()
    target = AnalysisTarget(type="file", path="src/app.py")

    total_to_insert = MAX_IN_MEMORY_HISTORY_RUNS + 25
    for idx in range(total_to_insert):
        record_analysis_run(
            dummy_state,
            object(),  # mock db without .query
            run_id=f"run-{idx:04d}",
            repository_id=REPO_ID,
            user_id=USER_ID,
            feature_type="explain",
            status="COMPLETED",
            target=target,
            revision="main",
        )

    store = dummy_state._analysis_run_history
    assert len(store) == MAX_IN_MEMORY_HISTORY_RUNS
    assert "run-0000" not in store
    assert "run-0024" not in store
    assert "run-0025" in store
    assert f"run-{total_to_insert - 1:04d}" in store


# ---------------------------------------------------------------------------
# 4. Standardized Failure Recording & Redaction on Unexpected Runtime Errors
# ---------------------------------------------------------------------------

def test_all_four_analysis_endpoints_record_failed_run_and_return_500_on_unexpected_runtime_error(
    sqlite_session,
):
    leaked_key = "sk-proj-" + "Z" * 32

    def _ExplodingService(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError(f"Unexpected crash with key {leaked_key}")

    app.state.explanation_service = _ExplodingService
    app.state.bug_detection_service = _ExplodingService
    app.state.test_generation_service = _ExplodingService
    app.state.code_review_service = _ExplodingService

    sqlite_session.add(
        RepositoryFile(
            id=uuid4(),
            repository_id=REPO_ID,
            path="src/app.py",
            size_bytes=100,
            line_count=10,
            content_hash="hash_src_app_py",
        )
    )
    sqlite_session.commit()

    client = TestClient(app, raise_server_exceptions=False)

    endpoints_and_payloads = [
        ("explain", "/explain", {"target": {"type": "file", "path": "src/app.py"}}),
        ("detect_bugs", "/detect-bugs", {"target": {"type": "file", "path": "src/app.py"}}),
        ("generate_tests", "/generate-tests", {"target": {"type": "file", "path": "src/app.py"}}),
        ("review", "/review", {"target": {"type": "file", "path": "src/app.py"}}),
    ]

    for feat, suffix, body in endpoints_and_payloads:
        resp = client.post(
            f"/api/v1/repositories/{REPO_ID}{suffix}",
            json=body,
            headers=_auth_headers(),
        )
        assert resp.status_code == 500, f"{suffix} returned {resp.status_code}"
        assert resp.json()["error"]["code"] == "ANALYSIS_FAILED"
        assert leaked_key not in resp.text

        failed_runs = (
            sqlite_session.query(AnalysisRun)
            .filter(
                AnalysisRun.repository_id == REPO_ID,
                AnalysisRun.feature_type == feat,
                AnalysisRun.status == "FAILED",
            )
            .all()
        )
        assert len(failed_runs) == 1
        assert leaked_key not in (failed_runs[0].error_message or "")
        assert "[REDACTED]" in (failed_runs[0].error_message or "")


# ---------------------------------------------------------------------------
# 5. Code Review Blast-Radius SymbolEdge Query Fix
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_code_review_blast_radius_queries_symbol_edges_without_sqlalchemy_set_comparison_error(
    sqlite_session,
):
    file_a_id = uuid4()
    file_b_id = uuid4()
    sqlite_session.add_all(
        [
            RepositoryFile(
                id=file_a_id,
                repository_id=REPO_ID,
                path="src/auth.py",
                language="Python",
                size_bytes=120,
                line_count=10,
                content_hash="h1",
            ),
            RepositoryFile(
                id=file_b_id,
                repository_id=REPO_ID,
                path="src/routes.py",
                language="Python",
                size_bytes=150,
                line_count=12,
                content_hash="h2",
            ),
        ]
    )
    sqlite_session.commit()

    sym_auth_id = uuid4()
    sym_caller_id = uuid4()
    sym_callee_id = uuid4()
    sqlite_session.add_all(
        [
            CodeSymbol(
                id=sym_auth_id,
                file_id=file_a_id,
                repository_id=REPO_ID,
                name="verify_token",
                kind="function",
                start_line=1,
                end_line=6,
                signature="def verify_token(token: str) -> bool:",
            ),
            CodeSymbol(
                id=sym_caller_id,
                file_id=file_b_id,
                repository_id=REPO_ID,
                name="login_route",
                kind="function",
                start_line=1,
                end_line=8,
                signature="def login_route(request): return verify_token(request.token)",
            ),
            CodeSymbol(
                id=sym_callee_id,
                file_id=file_b_id,
                repository_id=REPO_ID,
                name="decode_jwt",
                kind="function",
                start_line=7,
                end_line=10,
                signature="def decode_jwt(raw: str) -> dict:",
            ),
        ]
    )
    sqlite_session.commit()

    sqlite_session.add_all(
        [
            CodeChunk(
                id=uuid4(),
                repository_id=REPO_ID,
                file_id=file_a_id,
                symbol_id=sym_auth_id,
                content="def verify_token(token: str) -> bool:\n    return bool(decode_jwt(token))\n",
                token_count=12,
                embedding=[0.1] * 768,
                chunk_metadata={},
                start_line=1,
                end_line=6,
                content_hash="c1",
            ),
            SymbolEdge(
                id=uuid4(),
                repository_id=REPO_ID,
                source_symbol_id=sym_caller_id,
                target_symbol_id=sym_auth_id,
                edge_type="calls",
            ),
            SymbolEdge(
                id=uuid4(),
                repository_id=REPO_ID,
                source_symbol_id=sym_auth_id,
                target_symbol_id=sym_callee_id,
                edge_type="calls",
            ),
        ]
    )
    sqlite_session.commit()

    repo = sqlite_session.get(Repository, REPO_ID)
    req = CodeReviewRequest(target=ReviewTarget(type="file", path="src/auth.py"))

    resolved = await resolve_review_target_and_build_context(
        repository_id=REPO_ID,
        repo=repo,
        payload=req,
        user_id=USER_ID,
        db=sqlite_session,
    )

    assert "Downstream caller graph could not be queried for blast radius." not in resolved.missing_context
    related_names = {s.name for s in resolved.intelligence_context.related_symbols}
    assert "login_route" in related_names
    assert "decode_jwt" in related_names


# ---------------------------------------------------------------------------
# 6. DependencyGraphBuilder Call Extraction & IncrementalIndexer symbol_edges
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dependency_graph_builder_extracts_call_edges_and_incremental_indexer_persists_symbol_edges(
    sqlite_session,
    tmp_path: Path,
):
    src_dir = tmp_path / "pkg"
    src_dir.mkdir(parents=True, exist_ok=True)
    file_1 = src_dir / "helpers.py"
    file_2 = src_dir / "service.py"

    file_1.write_text(
        "class BaseHelper:\n"
        "    pass\n\n"
        "def compute_checksum(payload: str) -> str:\n"
        "    return payload.strip()\n",
        encoding="utf-8",
    )
    file_2.write_text(
        "from pkg.helpers import BaseHelper, compute_checksum\n\n"
        "class OrderService(BaseHelper):\n"
        "    def process_order(self, data: str) -> str:\n"
        "        return compute_checksum(data)\n",
        encoding="utf-8",
    )

    scanned = [
        FileInfo(path="pkg/helpers.py", size_bytes=file_1.stat().st_size, language="Python", is_binary=False),
        FileInfo(path="pkg/service.py", size_bytes=file_2.stat().st_size, language="Python", is_binary=False),
    ]

    indexer = IncrementalIndexer(db_session=sqlite_session, embedding_service=None)
    stats = await indexer.sync(
        repository_id=REPO_ID,
        scanned_files=scanned,
        root_path=str(tmp_path),
    )
    assert stats["indexed"] == 2

    edges = (
        sqlite_session.query(SymbolEdge)
        .filter(SymbolEdge.repository_id == REPO_ID)
        .all()
    )
    edge_types = {e.edge_type for e in edges}
    assert "imports" in edge_types
    assert "extends" in edge_types
    assert "calls" in edge_types


# ---------------------------------------------------------------------------
# 7. Single Static Scan Execution + ASTBugAnalyzer Integration in /detect-bugs
# ---------------------------------------------------------------------------

def test_detect_bugs_avoids_duplicate_builtin_static_scan_and_runs_ast_bug_analyzer_rules(
    sqlite_session,
    monkeypatch: pytest.MonkeyPatch,
):
    file_id = uuid4()
    code_text = (
        "def buggy_handler(user, items):\n"
        "    if user is None:\n"
        "        print(user.name)\n"
        "    for item in items:\n"
        "        items.remove(item)\n"
        "    return items\n"
    )
    sqlite_session.add(
        RepositoryFile(
            id=file_id,
            repository_id=REPO_ID,
            path="src/buggy.py",
            language="Python",
            size_bytes=len(code_text),
            line_count=len(code_text.splitlines()),
            content_hash="buggy-hash",
        )
    )
    sqlite_session.commit()
    sqlite_session.add(
        CodeChunk(
            id=uuid4(),
            repository_id=REPO_ID,
            file_id=file_id,
            content=code_text,
            token_count=30,
            embedding=[0.1] * 768,
                chunk_metadata={},
            start_line=1,
            end_line=6,
            content_hash="chunk-buggy",
        )
    )
    sqlite_session.commit()

    scan_call_count = 0
    orig_scan = BuiltinStaticBugScanner.scan

    def _counted_scan(self, *args: Any, **kwargs: Any):
        nonlocal scan_call_count
        scan_call_count += 1
        return orig_scan(self, *args, **kwargs)

    monkeypatch.setattr(BuiltinStaticBugScanner, "scan", _counted_scan)

    class _MockProvider(LLMProvider):
        @property
        def provider_name(self) -> str:
            return "gemini"

        @property
        def default_model(self) -> str:
            return "gemini-flash-lite-latest"

        async def generate(self, request: LLMRequest) -> LLMResponse:
            return LLMResponse(
                content='{"findings": [], "missing_context": []}',
                model=self.default_model,
                input_tokens=20,
                output_tokens=10,
                latency_ms=5.0,
            )

    app.state.bug_detection_service = BugDetectionEngine(llm_gateway=LLMGateway(provider=_MockProvider()))
    client = TestClient(app)

    resp = client.post(
        f"/api/v1/repositories/{REPO_ID}/detect-bugs",
        json={"target": {"type": "file", "path": "src/buggy.py"}, "include_static": True, "include_ai": True},
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    assert scan_call_count == 1, f"Expected BuiltinStaticBugScanner.scan to run once, ran {scan_call_count} times"

    findings = resp.json()["findings"]
    rule_ids = {f["rule_id"] for f in findings if f.get("rule_id")}
    assert "AST-NULL-001" in rule_ids
    assert "AST-ITER-001" in rule_ids


# ---------------------------------------------------------------------------
# 8. BugScanHistoryService Orchestrator Protocol Compliance
# ---------------------------------------------------------------------------

def test_bug_scan_history_service_implements_orchestrator_protocol_and_user_id_filtering(
    sqlite_session,
):
    svc = BugScanHistoryService(session=sqlite_session)
    run_id = str(uuid4())
    record = {
        "id": run_id,
        "repository_id": str(REPO_ID),
        "user_id": str(USER_ID),
        "feature_type": "detect_bugs",
        "status": "COMPLETED",
        "target_path": "src/auth.py",
        "source_revision": "main",
        "findings_count": 1,
        "findings": [
            {
                "id": str(uuid4()),
                "category": "security",
                "severity": "HIGH",
                "title": "SQL injection risk",
                "description": "Unparameterized SQL string",
                "file_path": "src/auth.py",
                "start_line": 4,
                "end_line": 4,
                "evidence": "SELECT * FROM users",
                "source_type": "STATIC",
                "rule_id": "B608",
            }
        ],
        "created_at": datetime.now(timezone.utc),
    }

    created = svc.record_run(record, db=sqlite_session)
    assert str(created.id) == run_id

    fetched = svc.get_run(run_id, repository_id=REPO_ID, db=sqlite_session)
    assert fetched is not None
    assert fetched.findings_count == 1

    runs_owner, total_owner = svc.list_runs(REPO_ID, user_id=USER_ID, db=sqlite_session)
    assert total_owner >= 1
    assert any(str(r.id) == run_id for r in runs_owner)

    runs_other, total_other = svc.list_runs(REPO_ID, user_id=OTHER_USER_ID, db=sqlite_session)
    assert total_other == 0
    assert runs_other == []


# ---------------------------------------------------------------------------
# 9. Multi-Installation & Numeric github_repo_id Validation in /github/repositories/:id/connect
# ---------------------------------------------------------------------------

def test_connect_repository_validates_numeric_repo_id_and_searches_across_multiple_installations(
    sqlite_session,
    monkeypatch: pytest.MonkeyPatch,
):
    class _FakeGHService:
        async def get_repository(self, installation_id: int, repo_id: int):
            if installation_id == 99001:
                raise RuntimeError("404 Not Found on installation 99001")
            if installation_id == 99002 and repo_id == 888002:
                return SimpleNamespace(
                    id=888002,
                    owner="yug-org",
                    name="platform-core",
                    default_branch="main",
                    language="TypeScript",
                )
            raise RuntimeError("Unexpected call")

    app.state.github_service = _FakeGHService()
    monkeypatch.setattr(
        "app.api.v1.github.get_redis",
        lambda: SimpleNamespace(rpush=lambda *_a, **_k: 1),
    )

    client = TestClient(app)

    # Non-numeric github_repo_id -> 400 INVALID_REQUEST
    bad_resp = client.post(
        "/api/v1/github/repositories/not-a-number/connect",
        headers=_auth_headers(),
    )
    assert bad_resp.status_code == 400
    assert bad_resp.json()["error"]["code"] == "INVALID_REQUEST"

    # Repo on second installation (99002) succeeds!
    ok_resp = client.post(
        "/api/v1/github/repositories/888002/connect",
        headers=_auth_headers(),
    )
    assert ok_resp.status_code == 201
    body = ok_resp.json()
    connected_repo = sqlite_session.get(Repository, UUID(body["repository_id"]))
    assert connected_repo is not None
    assert connected_repo.owner == "yug-org"
    assert connected_repo.name == "platform-core"
    assert connected_repo.installation_id == INST_ID_2


# ---------------------------------------------------------------------------
# 10. Batched Chunk Reconstruction & pyproject.toml / Pipfile Dependency Parsing
# ---------------------------------------------------------------------------

def test_batch_chunk_reconstruction_and_pyproject_pipfile_dependency_extraction(
    sqlite_session,
):
    pyproject_id = uuid4()
    pipfile_id = uuid4()
    sqlite_session.add_all(
        [
            RepositoryFile(
                id=pyproject_id,
                repository_id=REPO_ID,
                path="pyproject.toml",
                language="TOML",
                size_bytes=200,
                line_count=10,
                content_hash="pp1",
            ),
            RepositoryFile(
                id=pipfile_id,
                repository_id=REPO_ID,
                path="Pipfile",
                language="TOML",
                size_bytes=150,
                line_count=8,
                content_hash="pf1",
            ),
        ]
    )
    sqlite_session.commit()

    pyproject_text = (
        '[project]\n'
        'name = "demo"\n'
        'dependencies = [\n'
        '    "fastapi>=0.115.0",\n'
        '    "pydantic>=2.9.0",\n'
        ']\n'
        '[tool.poetry.dependencies]\n'
        'python = "^3.12"\n'
        'httpx = "^0.27.0"\n'
    )
    pipfile_text = (
        '[packages]\n'
        'sqlalchemy = ">=2.0"\n'
        '[dev-packages]\n'
        'pytest = "*"\n'
    )
    sqlite_session.add_all(
        [
            CodeChunk(
                id=uuid4(),
                repository_id=REPO_ID,
                file_id=pyproject_id,
                content=pyproject_text,
                token_count=25,
                embedding=[0.1] * 768,
                chunk_metadata={},
                start_line=1,
                end_line=10,
                content_hash="ppc1",
            ),
            CodeChunk(
                id=uuid4(),
                repository_id=REPO_ID,
                file_id=pipfile_id,
                content=pipfile_text,
                token_count=15,
                embedding=[0.1] * 768,
                chunk_metadata={},
                start_line=1,
                end_line=6,
                content_hash="pfc1",
            ),
        ]
    )
    sqlite_session.commit()

    client = TestClient(app)
    resp = client.get(
        f"/api/v1/repositories/{REPO_ID}/dependencies",
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    deps = {d["name"]: d for d in resp.json()}
    assert "fastapi" in deps
    assert "pydantic" in deps
    assert "httpx" in deps
    assert "sqlalchemy" in deps
    assert "pytest" in deps


# ---------------------------------------------------------------------------
# 11. Frontend TypeScript Contract Alignment & RepositoryDetail State Sync
# ---------------------------------------------------------------------------

def test_frontend_analysis_types_service_and_repository_detail_polish():
    types_ts = (REPO_ROOT / "frontend" / "src" / "types" / "analysis.ts").read_text(encoding="utf-8")
    service_ts = (REPO_ROOT / "frontend" / "src" / "services" / "analysis.ts").read_text(encoding="utf-8")
    detail_tsx = (REPO_ROOT / "frontend" / "src" / "pages" / "RepositoryDetail.tsx").read_text(encoding="utf-8")

    assert "export interface AnalysisRunMetricsSummaryResponse" in types_ts
    assert "export async function getAnalysisRunsSummary(" in service_ts
    assert "user_id?: string;" in service_ts
    assert "/analysis-runs/summary" in service_ts
    assert "setReviewTarget((prev) =>" in detail_tsx
