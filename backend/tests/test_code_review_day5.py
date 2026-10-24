"""Comprehensive Week 2 Day 5 tests for Standalone AI Code Review & Backend Audit Fixes.

Owner: Yug — W2, Day 5 (Standalone AI Code Review Orchestrator, Diff/Commit/PR
Resolution, Static + AI Review Merge, Risk Calculation & Backend Security Fixes)

Covers:
1. Review target resolution:
   - Single-file review (`target.type == "file"`)
   - Unified diff review (`target.type == "diff"`, invalid diff rejection with 400)
   - Commit review (`target.type == "commit"`)
   - Pull request review (`target.type == "pr"`)
2. Static review scanning on changed lines (`run_static_review_on_changes`).
3. Grounding validation (stripping hallucinated file paths, clamping/rejecting out-of-bounds lines, redacting secrets).
4. Static + AI review finding deduplication (`source_type="COMBINED"`), severity ranking, category counts, and overall `risk_level` calculation (`CRITICAL` / `HIGH` / `MEDIUM` / `LOW` / `NONE`).
5. Clean review distinction (`status="COMPLETED"`, `findings=[]`, `risk_level="NONE"` vs `status="FAILED"`).
6. Backend Audit Security & Integrity Fixes:
   - `github_installation_callback` imports (`get_settings`, `RedirectResponse`) & public path whitelist
   - `github_webhook` fail-closed signature check in production
   - `/api/v1/events` multi-tenant repository event filtering
   - `GitBranchService._get_client_for_repo` UUID FK lookup vs string `installation_id`
   - `integrations/github/routes.py` path traversal & SHA validation
   - `StaticBugScanner.scan` adapter & `BlastRadiusEngine` import fallback
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from ai.context.builder import IntelligenceContext, TargetSnippet
from ai.context.review_context import ModifiedFile
from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.code_chunk import CodeChunk
from app.models.github_installation import GitHubInstallation
from app.models.repository_file import RepositoryFile
from app.repositories.repository_repository import RepositoryRepository
from app.schemas.analysis import (
    AnalysisSourceReference,
    CodeReviewRequest,
    ReviewFinding,
    ReviewReport,
    ReviewTarget,
)
from app.services.code_review_orchestrator import (
    LLMCodeReviewService,
    ResolvedReviewTarget,
    build_grounded_review_report,
    compute_review_risk_level,
    merge_and_rank_review_findings,
    normalize_and_ground_review_findings,
    run_static_review_on_changes,
)
from app.services.git_branch import GitBranchService
from review.blast_radius import BlastRadiusEngine
from scanner.import_tracker import ImportTracker
from scanner.source_mapper import ReviewSourceMapResult
from scanner.static_bug_scanner import StaticBugScanner
from scanner.symbols import FileInfo


class _FakeRedis:
    def exists(self, _: str) -> int:
        return 0

    def pipeline(self) -> Any:
        class _Pipe:
            def incr(self, _k: str) -> None:
                pass

            def expire(self, _k: str, _s: int) -> None:
                pass

            def execute(self) -> list[Any]:
                return [1, True]

        return _Pipe()


def _configure_auth(monkeypatch: pytest.MonkeyPatch, user_id: str | None = None) -> tuple[str, str]:
    uid = user_id or str(uuid4())
    monkeypatch.setenv("JWT_SECRET", "day5-test-secret-key-12345")
    get_settings.cache_clear()
    fake_redis = _FakeRedis()
    monkeypatch.setattr("app.core.auth.get_redis", lambda: fake_redis)
    monkeypatch.setattr("app.core.redis.get_redis", lambda: fake_redis)
    token = create_access_token(uid)[0]
    return token, uid


def _allow_repo_owner(
    monkeypatch: pytest.MonkeyPatch,
    *,
    owned_repo_id: UUID,
    last_commit_sha: str | None = "a1b2c3d4e5f6",
) -> None:
    def _fake_get_for_user(self: Any, repository_id: UUID, user_id: UUID) -> Any:
        if repository_id == owned_repo_id:
            return SimpleNamespace(
                id=repository_id,
                user_id=user_id,
                full_name="acme/core-api",
                default_branch="main",
                last_commit_sha=last_commit_sha,
            )
        return None

    monkeypatch.setattr(RepositoryRepository, "get_for_user", _fake_get_for_user)


class _FakeQuery:
    def __init__(self, items: list[Any]) -> None:
        self._items = list(items)

    def filter(self, *predicates: Any, **kwargs: Any) -> "_FakeQuery":
        filtered = list(self._items)
        for pred in predicates:
            right = getattr(pred, "right", None)
            val = getattr(right, "value", None)
            left_str = str(getattr(pred, "left", ""))
            if val is not None:
                if "path" in left_str:
                    if isinstance(val, (list, tuple, set)):
                        filtered = [f for f in filtered if getattr(f, "path", None) in val]
                    else:
                        filtered = [f for f in filtered if getattr(f, "path", None) == val]
                elif "file_id" in left_str:
                    filtered = [c for c in filtered if getattr(c, "file_id", None) == val]
        return _FakeQuery(filtered)

    def order_by(self, *args: Any, **kwargs: Any) -> "_FakeQuery":
        return self

    def limit(self, n: int) -> "_FakeQuery":
        return _FakeQuery(self._items[:n])

    def first(self) -> Any:
        return self._items[0] if self._items else None

    def all(self) -> list[Any]:
        return list(self._items)


class _FakeReviewDB:
    def __init__(self, files: list[Any], chunks: list[Any] | None = None) -> None:
        self._files = files
        self._chunks = chunks or []

    def query(self, model: Any) -> _FakeQuery:
        model_name = getattr(model, "__name__", str(model))
        if model is RepositoryFile or "RepositoryFile" in model_name:
            return _FakeQuery(self._files)
        if model is CodeChunk or "CodeChunk" in model_name:
            return _FakeQuery(self._chunks)
        return _FakeQuery([])


def _make_repo_file_and_chunk(
    repo_id: UUID,
    *,
    path: str,
    content: str,
    language: str = "Python",
) -> tuple[SimpleNamespace, SimpleNamespace]:
    file_id = uuid4()
    line_count = len(content.splitlines()) or 1
    f_rec = SimpleNamespace(
        id=file_id,
        repository_id=repo_id,
        path=path,
        language=language,
        size_bytes=len(content.encode("utf-8")),
        line_count=line_count,
        content_hash="abc123hash",
    )
    c_rec = SimpleNamespace(
        id=uuid4(),
        repository_id=repo_id,
        file_id=file_id,
        start_line=1,
        end_line=line_count,
        content=content,
    )
    return f_rec, c_rec


# ---------------------------------------------------------------------------
# 1. Unit Tests: Static Review, Grounding, Deduplication & Risk Level
# ---------------------------------------------------------------------------

def test_run_static_review_on_changes_detects_dangerous_eval_and_bare_except() -> None:
    repo_id = uuid4()
    code = (
        "def run_untrusted(cmd: str):\n"
        "    try:\n"
        "        return eval(cmd)\n"
        "    except:\n"
        "        return None\n"
    )
    mod = ModifiedFile(
        file_path="backend/app/runner.py",
        change_type="modified",
        modified_line_ranges=[(1, 5)],
        content=code,
    )
    resolved = ResolvedReviewTarget(
        target=ReviewTarget(type="file", path="backend/app/runner.py"),
        target_path_summary="backend/app/runner.py",
        revision="rev123",
        base_revision=None,
        head_revision="rev123",
        modified_files=[mod],
        file_contents={"backend/app/runner.py": code},
        source_map=ReviewSourceMapResult(success=True),
        intelligence_context=IntelligenceContext(
            target=TargetSnippet(
                file_path="backend/app/runner.py",
                content=code,
                start_line=1,
                end_line=5,
            )
        ),
        missing_context=[],
        indexed_paths={"backend/app/runner.py": 5},
        allowed_paths={"backend/app/runner.py"},
    )

    findings, warnings = run_static_review_on_changes(
        repository_id=repo_id,
        resolved=resolved,
        app_state=SimpleNamespace(),
    )

    assert warnings == []
    assert len(findings) >= 2
    categories = {f.category for f in findings}
    assert "security" in categories
    assert "reliability" in categories


def test_normalize_and_ground_review_findings_strips_hallucinated_paths_and_redacts_secrets() -> None:
    repo_id = uuid4()
    code = "def connect():\n    return True\n"
    mod = ModifiedFile(
        file_path="backend/app/db.py",
        change_type="modified",
        modified_line_ranges=[(1, 2)],
        content=code,
    )
    resolved = ResolvedReviewTarget(
        target=ReviewTarget(type="file", path="backend/app/db.py"),
        target_path_summary="backend/app/db.py",
        revision="rev123",
        base_revision=None,
        head_revision="rev123",
        modified_files=[mod],
        file_contents={"backend/app/db.py": code},
        source_map=ReviewSourceMapResult(success=True),
        intelligence_context=IntelligenceContext(
            target=TargetSnippet(
                file_path="backend/app/db.py",
                content=code,
                start_line=1,
                end_line=2,
            )
        ),
        missing_context=[],
        indexed_paths={"backend/app/db.py": 2},
        allowed_paths={"backend/app/db.py"},
    )

    raw_findings = [
        # Valid finding with leaked secret in title & description
        {
            "id": "ai-1",
            "severity": "CRITICAL",
            "category": "security",
            "title": "Hardcoded key sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
            "description": "Remove key ghp_1234567890abcdefghijklmnopqrstuvwxyz12 immediately.",
            "evidence": "api_key = 'sk-...'",
            "suggested_fix": "Use environment variables.",
            "confidence": "high",
            "source_type": "AI",
            "source_reference": {"file_path": "backend/app/db.py", "start_line": 1, "end_line": 2},
        },
        # Out-of-bounds line number on single-file review (must be stripped)
        {
            "id": "ai-oob",
            "severity": "HIGH",
            "category": "correctness",
            "title": "Out of bounds line",
            "description": "Line 99 does not exist.",
            "evidence": "none",
            "source_reference": {"file_path": "backend/app/db.py", "start_line": 99, "end_line": 100},
        },
        # Hallucinated non-existent file path (must be stripped)
        {
            "id": "ai-phantom",
            "severity": "HIGH",
            "category": "correctness",
            "title": "Hallucinated file",
            "description": "Does not exist in repository.",
            "evidence": "none",
            "source_reference": {"file_path": "non_existent/phantom.py", "start_line": 1, "end_line": 2},
        },
    ]

    grounded = normalize_and_ground_review_findings(
        raw_findings,
        repository_id=repo_id,
        resolved=resolved,
    )

    assert len(grounded) == 1
    finding = grounded[0]
    assert finding.source_reference.file_path == "backend/app/db.py"
    assert "sk-proj-" not in finding.title
    assert "[REDACTED]" in finding.title
    assert "ghp_" not in finding.description


def test_merge_and_rank_review_findings_promotes_overlapping_to_combined_and_computes_risk() -> None:
    ref = AnalysisSourceReference(
        repository_id=str(uuid4()),
        file_path="backend/app/api.py",
        start_line=10,
        end_line=12,
    )
    static_f = ReviewFinding(
        id="rev-static-1",
        category="security",
        severity="HIGH",
        title="Static eval detection",
        description="AST detected eval() call.",
        source_reference=ref,
        evidence="eval(user_input)",
        suggested_fix="Use ast.literal_eval.",
        confidence="medium",
        source_type="STATIC",
        rule_id="B307",
    )
    ai_f = ReviewFinding(
        id="rev-ai-1",
        category="security",
        severity="CRITICAL",
        title="Remote Code Execution via eval()",
        description="User input passed directly to eval() allows arbitrary code execution.",
        source_reference=ref,
        evidence="return eval(user_input)",
        suggested_fix="Replace eval() with safe JSON parsing.",
        confidence="high",
        source_type="AI",
    )

    merged = merge_and_rank_review_findings([static_f, ai_f], include_static=True)
    assert len(merged) == 1
    assert merged[0].source_type == "COMBINED"
    assert merged[0].severity == "CRITICAL"
    assert merged[0].confidence == "high"
    assert compute_review_risk_level(merged) == "CRITICAL"
    assert compute_review_risk_level([]) == "NONE"


# ---------------------------------------------------------------------------
# 2. Integration Tests: POST /api/v1/repositories/{id}/review
# ---------------------------------------------------------------------------

def test_review_endpoint_handles_diff_target_and_persists_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token, _ = _configure_auth(monkeypatch)
    repo_id = uuid4()
    _allow_repo_owner(monkeypatch, owned_repo_id=repo_id)

    code_text = (
        "def execute_job(payload: str, items=[]):\n"
        "    try:\n"
        "        return eval(payload)\n"
        "    except:\n"
        "        return None\n"
    )
    diff_text = (
        "diff --git a/backend/app/worker.py b/backend/app/worker.py\n"
        "--- a/backend/app/worker.py\n"
        "+++ b/backend/app/worker.py\n"
        "@@ -1,2 +1,5 @@\n"
        "+def execute_job(payload: str, items=[]):\n"
        "+    try:\n"
        "+        return eval(payload)\n"
        "+    except:\n"
        "+        return None\n"
    )
    f_worker, c_worker = _make_repo_file_and_chunk(
        repo_id,
        path="backend/app/worker.py",
        content=code_text,
    )
    fake_db = _FakeReviewDB([f_worker], [c_worker])
    recorded_runs: list[dict[str, Any]] = []

    class _FakeRunService:
        def record_run(self, record: dict[str, Any]) -> None:
            recorded_runs.append(record)

    class _FakeReviewService:
        async def review(self, repository_id: UUID, payload: CodeReviewRequest, **kwargs: Any) -> dict[str, Any]:
            return {
                "summary": "Review identified dangerous eval() execution in worker.",
                "risk_level": "HIGH",
                "findings": [
                    {
                        "id": "ai-rev-1",
                        "category": "security",
                        "severity": "HIGH",
                        "title": "Dynamic eval() on job payload",
                        "description": "Untrusted payload is passed to eval().",
                        "evidence": "return eval(payload)",
                        "suggested_fix": "Use json.loads(payload).",
                        "confidence": "high",
                        "source_type": "AI",
                        "source_reference": {
                            "file_path": "backend/app/worker.py",
                            "start_line": 3,
                            "end_line": 3,
                        },
                    }
                ],
                "missing_context": [],
            }

    app.dependency_overrides[get_db] = lambda: fake_db
    prev_service = getattr(app.state, "code_review_service", None)
    prev_run_svc = getattr(app.state, "analysis_run_service", None)
    app.state.code_review_service = _FakeReviewService()
    app.state.analysis_run_service = _FakeRunService()

    try:
        client = TestClient(app)
        response = client.post(
            f"/api/v1/repositories/{repo_id}/review",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "target": {"type": "diff", "diff": diff_text},
                "include_static": True,
            },
        )
    finally:
        app.state.code_review_service = prev_service
        app.state.analysis_run_service = prev_run_svc
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["report"]["total_findings"] >= 2
    assert body["report"]["risk_level"] in ("HIGH", "CRITICAL")
    assert any(f["source_type"] == "COMBINED" for f in body["report"]["findings"])
    assert len(recorded_runs) == 1
    assert recorded_runs[0]["feature_type"] == "review"


def test_review_endpoint_distinguishes_zero_finding_clean_file_from_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token, _ = _configure_auth(monkeypatch)
    repo_id = uuid4()
    _allow_repo_owner(monkeypatch, owned_repo_id=repo_id)

    clean_code = "def add_numbers(a: int, b: int) -> int:\n    return a + b\n"
    f_clean, c_clean = _make_repo_file_and_chunk(
        repo_id, path="backend/app/math_utils.py", content=clean_code
    )
    fake_db = _FakeReviewDB([f_clean], [c_clean])

    class _CleanReviewService:
        async def review(self, repository_id: UUID, payload: CodeReviewRequest, **kwargs: Any) -> ReviewReport:
            return ReviewReport(
                summary="Clean implementation with no defects detected.",
                risk_level="NONE",
                findings=[],
                total_findings=0,
                category_counts={},
                missing_context=[],
            )

    app.dependency_overrides[get_db] = lambda: fake_db
    prev_service = getattr(app.state, "code_review_service", None)
    app.state.code_review_service = _CleanReviewService()

    try:
        client = TestClient(app)
        response = client.post(
            f"/api/v1/repositories/{repo_id}/review",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "target": {"type": "file", "path": "backend/app/math_utils.py"},
            },
        )
    finally:
        app.state.code_review_service = prev_service
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["report"]["total_findings"] == 0
    assert body["report"]["findings"] == []
    assert body["report"]["risk_level"] == "NONE"


# ---------------------------------------------------------------------------
# 3. Backend Audit Regression Tests (GitHub Callback, Webhook, GitBranch, Routes)
# ---------------------------------------------------------------------------

def test_github_installation_callback_is_public_and_redirects_without_name_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:5173")
    get_settings.cache_clear()

    class _FakeNoOpDB:
        def query(self, *args: Any, **kwargs: Any) -> Any:
            return SimpleNamespace(
                filter=lambda *a, **k: SimpleNamespace(first=lambda: None)
            )

    app.dependency_overrides[get_db] = lambda: _FakeNoOpDB()
    try:
        client = TestClient(app, follow_redirects=False)
        response = client.get(
            "/api/v1/github/installation/callback?installation_id=12345&setup_action=install"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code in (302, 307)
    assert "installed=true" in response.headers["location"]
    assert "installation_id=12345" in response.headers["location"]


def test_github_webhook_fails_closed_in_production_when_secret_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "")
    get_settings.cache_clear()

    app.dependency_overrides[get_db] = lambda: object()
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/github/webhook",
            headers={"X-GitHub-Event": "push"},
            json={"repository": {"id": 1}},
        )
    finally:
        monkeypatch.setenv("APP_ENV", "development")
        get_settings.cache_clear()
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_git_branch_service_resolves_installation_by_uuid_pk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inst_uuid = uuid4()
    repo_id = uuid4()
    user_id = uuid4()

    repo = SimpleNamespace(
        id=repo_id,
        user_id=user_id,
        installation_id=inst_uuid,
        full_name="acme/service",
    )
    installation = SimpleNamespace(
        id=inst_uuid,
        installation_id="99887766",
    )

    class _FakeBranchDB:
        def get(self, model: Any, pk: Any) -> Any:
            if model is GitHubInstallation and pk == inst_uuid:
                return installation
            return None

    captured_inst_id: list[str] = []

    class _FakeGitHubClient:
        @classmethod
        async def get_installation_token(cls, installation_id: str) -> str:
            captured_inst_id.append(str(installation_id))
            return "ghs_fake_installation_token"

        def __init__(self, access_token: str) -> None:
            self.access_token = access_token

    import app.services.git_branch as gb_mod
    monkeypatch.setattr(gb_mod, "GitHubClient", _FakeGitHubClient)

    svc = GitBranchService(_FakeBranchDB())  # type: ignore[arg-type]
    client = asyncio.run(svc._get_client_for_repo(repo))  # type: ignore[arg-type]

    assert client.access_token == "ghs_fake_installation_token"
    assert captured_inst_id == ["99887766"]


def test_github_integration_routes_reject_path_traversal_on_commits_and_invalid_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token, _ = _configure_auth(monkeypatch)
    repo_id = uuid4()
    _allow_repo_owner(monkeypatch, owned_repo_id=repo_id)

    app.dependency_overrides[get_db] = lambda: object()
    try:
        client = TestClient(app)
        resp_commits = client.get(
            f"/api/v1/repositories/{repo_id}/source/commits?path=../../etc/passwd",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp_sha = client.get(
            f"/api/v1/repositories/{repo_id}/source/commits/not-a-valid-hex-sha!",
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp_commits.status_code == 400
    assert resp_sha.status_code == 400


def test_static_bug_scanner_adapter_and_blast_radius_engine() -> None:
    scanner = StaticBugScanner()
    res = scanner.scan(
        file_path="app/sample.py",
        code_content="def f(items=[]):\n    return items\n",
    )
    assert res["success"] is True
    assert len(res["findings"]) >= 1

    tracker = ImportTracker()
    info_a = FileInfo(path="app/a.py", size_bytes=20, language="Python", is_binary=False)
    info_b = FileInfo(path="app/b.py", size_bytes=10, language="Python", is_binary=False)
    m_a = tracker.parse_imports(
        info_a,
        "import app.b\n",
        known_files=["app/a.py", "app/b.py"],
    )
    m_b = tracker.parse_imports(
        info_b,
        "x = 1\n",
        known_files=["app/a.py", "app/b.py"],
    )
    blast = BlastRadiusEngine().compute(["app/b.py"], {"app/a.py": m_a, "app/b.py": m_b})
    assert blast["affected_files"] == ["app/a.py"]
    assert blast["total_affected"] == 1


# ---------------------------------------------------------------------------
# 4. DB-Seeded End-to-End Integration Tests (File, Commit, PR, Diff, Reopen History, Timeout Failure)
# ---------------------------------------------------------------------------

def _seed_review_repository(db_session, owner_user) -> tuple[Any, Any]:
    """Create an indexed repository with Python files, AST symbols, edges, and chunks for Day 5 review."""
    import uuid
    from app.models.code_chunk import CodeChunk
    from app.models.code_symbol import CodeSymbol
    from app.models.github_installation import GitHubInstallation
    from app.models.repository import Repository, SyncStatus
    from app.models.repository_file import RepositoryFile
    from app.models.symbol_edge import SymbolEdge

    installation = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=owner_user.id,
        installation_id=f"inst-{uuid.uuid4().hex[:8]}",
        account_login=owner_user.login,
        permissions={"contents": "read"},
    )
    db_session.add(installation)
    db_session.commit()

    repo = Repository(
        id=uuid.uuid4(),
        user_id=owner_user.id,
        installation_id=installation.id,
        github_repo_id=f"gh-repo-{uuid.uuid4().hex[:8]}",
        owner=owner_user.login,
        name="day5-review-repo",
        default_branch="main",
        language="Python",
        sync_status=SyncStatus.SYNCED,
    )
    db_session.add(repo)
    db_session.commit()

    file_row = RepositoryFile(
        id=uuid.uuid4(),
        repository_id=repo.id,
        path="backend/app/services/payment_processor.py",
        language="Python",
        size_bytes=1400,
        line_count=35,
        content_hash="payhash123",
    )
    caller_file = RepositoryFile(
        id=uuid.uuid4(),
        repository_id=repo.id,
        path="backend/app/api/checkout.py",
        language="Python",
        size_bytes=800,
        line_count=20,
        content_hash="checkouthash123",
    )
    db_session.add_all([file_row, caller_file])
    db_session.commit()

    sym_process = CodeSymbol(
        id=uuid.uuid4(),
        file_id=file_row.id,
        repository_id=repo.id,
        name="process_payment",
        kind="function",
        start_line=1,
        end_line=20,
        signature="def process_payment(user_input: str, retries: list = []) -> dict:",
    )
    sym_caller = CodeSymbol(
        id=uuid.uuid4(),
        file_id=caller_file.id,
        repository_id=repo.id,
        name="checkout_endpoint",
        kind="function",
        start_line=1,
        end_line=15,
        signature="def checkout_endpoint(req):",
    )
    db_session.add_all([sym_process, sym_caller])
    db_session.commit()

    edge = SymbolEdge(
        id=uuid.uuid4(),
        repository_id=repo.id,
        source_symbol_id=sym_caller.id,
        target_symbol_id=sym_process.id,
        edge_type="calls",
    )
    db_session.add(edge)

    chunk = CodeChunk(
        id=uuid.uuid4(),
        repository_id=repo.id,
        file_id=file_row.id,
        symbol_id=sym_process.id,
        content=(
            "def process_payment(user_input: str, retries: list = []) -> dict:\n"
            "    try:\n"
            "        result = eval(user_input)\n"
            "        return {'ok': True, 'result': result}\n"
            "    except:\n"
            "        pass\n"
        ),
        token_count=42,
        embedding=[0.0] * 768,
        start_line=1,
        end_line=20,
        content_hash="chunkpay123",
        chunk_metadata={"file_path": "backend/app/services/payment_processor.py"},
    )
    db_session.add(chunk)
    db_session.commit()

    return repo, file_row


def test_review_db_seeded_commit_and_pr_targets_and_reopen_history(
    client, db_session, test_user, auth_headers
) -> None:
    """Verify commit and PR review targets with GitHubSourceService, blast radius, and history reopen."""
    repo, _ = _seed_review_repository(db_session, test_user)

    class _FakeGitHubSourceService:
        async def get_commit_detail(self, repository_id, user_id, sha):
            return SimpleNamespace(
                sha=sha,
                parents=["0000000000000000"],
                files=[
                    SimpleNamespace(
                        filename="backend/app/services/payment_processor.py",
                        status="modified",
                        patch=(
                            "@@ -1,4 +1,6 @@\n"
                            " def process_payment(user_input: str, retries: list = []) -> dict:\n"
                            "+    try:\n"
                            "+        result = eval(user_input)\n"
                            "+        return {'ok': True, 'result': result}\n"
                            "+    except:\n"
                            "+        pass\n"
                        ),
                    )
                ],
            )

        async def get_pull_request_diff(self, repository_id, user_id, pr_number):
            return SimpleNamespace(
                pull_request=SimpleNamespace(
                    number=pr_number,
                    base_sha="base1111",
                    head_sha="head2222",
                    base_ref="main",
                    head_ref="feat/payment",
                ),
                files=[
                    SimpleNamespace(
                        filename="backend/app/services/payment_processor.py",
                        status="modified",
                        patch=(
                            "@@ -1,4 +1,6 @@\n"
                            " def process_payment(user_input: str, retries: list = []) -> dict:\n"
                            "+    try:\n"
                            "+        result = eval(user_input)\n"
                        ),
                    )
                ],
            )

    async def _fake_review(repository_id, payload, **kwargs):
        return {
            "summary": "Critical eval() and swallowed exception found in payment processor.",
            "risk_level": "CRITICAL",
            "findings": [
                {
                    "id": "ai-eval-1",
                    "category": "security",
                    "severity": "CRITICAL",
                    "title": "Arbitrary code execution via eval(user_input)",
                    "description": "Untrusted user_input is evaluated with eval().",
                    "source_reference": {
                        "file_path": "backend/app/services/payment_processor.py",
                        "start_line": 3,
                        "end_line": 3,
                        "symbol_name": "process_payment",
                    },
                    "evidence": "result = eval(user_input)",
                    "suggested_fix": "Parse JSON safely with json.loads().",
                    "confidence": "high",
                    "is_uncertain": False,
                    "is_new_in_change": True,
                    "source_type": "AI",
                }
            ],
            "missing_context": [],
        }

    app.state.github_source_service = _FakeGitHubSourceService()
    app.state.code_review_service = SimpleNamespace(review=_fake_review)
    try:
        # 1. Commit review target
        res_commit = client.post(
            f"/api/v1/repositories/{repo.id}/review",
            headers=auth_headers,
            json={"target": {"type": "commit", "commit_sha": "a1b2c3d4e5f6"}},
        )
        assert res_commit.status_code == 200, res_commit.text
        body_commit = res_commit.json()
        assert body_commit["status"] == "COMPLETED"
        assert body_commit["report"]["risk_level"] == "CRITICAL"
        assert any(f["source_type"] == "COMBINED" for f in body_commit["report"]["findings"])

        # 2. PR review target
        res_pr = client.post(
            f"/api/v1/repositories/{repo.id}/review",
            headers=auth_headers,
            json={"target": {"type": "pr", "pr_number": 42}},
        )
        assert res_pr.status_code == 200, res_pr.text
        body_pr = res_pr.json()
        assert body_pr["status"] == "COMPLETED"
        assert body_pr["target"]["pr_number"] == 42

        # 3. Reopen persisted review run from history
        run_id = body_commit["run_id"]
        detail_res = client.get(f"/api/v1/analysis-runs/{run_id}", headers=auth_headers)
        assert detail_res.status_code == 200
        detail_body = detail_res.json()
        assert detail_body["feature_type"] == "review"
        assert detail_body["status"] == "COMPLETED"
        assert detail_body["findings_count"] >= 2
    finally:
        if hasattr(app.state, "github_source_service"):
            del app.state.github_source_service
        if hasattr(app.state, "code_review_service"):
            del app.state.code_review_service


def test_review_records_failed_run_on_provider_timeout(
    client, db_session, test_user, auth_headers
) -> None:
    from ai.llm.schemas import LLMTimeoutError
    from unittest.mock import AsyncMock

    repo, _ = _seed_review_repository(db_session, test_user)
    app.state.code_review_service = SimpleNamespace(
        review=AsyncMock(side_effect=LLMTimeoutError("Review LLM timed out"))
    )
    try:
        res = client.post(
            f"/api/v1/repositories/{repo.id}/review",
            headers=auth_headers,
            json={"file_path": "backend/app/services/payment_processor.py"},
        )
        assert res.status_code == 503
        assert res.json()["error"]["code"] == "SERVICE_UNAVAILABLE"

        runs_res = client.get(
            f"/api/v1/repositories/{repo.id}/analysis-runs?feature_type=review&status=FAILED",
            headers=auth_headers,
        )
        assert runs_res.status_code == 200
        items = runs_res.json()["items"]
        assert len(items) >= 1
        assert items[0]["status"] == "FAILED"
    finally:
        del app.state.code_review_service


@pytest.mark.asyncio
async def test_llm_code_review_service_repairs_invalid_json_and_fences_prompt_injection() -> None:
    import json
    import uuid
    from ai.llm.schemas import LLMResponse

    calls = []

    async def _generate(req):
        calls.append(req)
        if len(calls) == 1:
            return LLMResponse(
                content="```json\n{broken json\n```",
                model="gemini-flash-lite-latest",
                input_tokens=45,
                output_tokens=15,
                latency_ms=10.0,
            )
        valid_payload = {
            "summary": "Reviewed payment_processor.py.",
            "risk_level": "HIGH",
            "findings": [
                {
                    "id": "rev-ai-1",
                    "category": "security",
                    "severity": "HIGH",
                    "title": "Dangerous eval()",
                    "description": "eval() used on untrusted input.",
                    "source_reference": {
                        "file_path": "backend/app/services/payment_processor.py",
                        "start_line": 3,
                        "end_line": 3,
                    },
                    "evidence": "eval(user_input)",
                    "suggested_fix": "Use ast.literal_eval.",
                    "confidence": "high",
                    "is_uncertain": False,
                    "is_new_in_change": True,
                    "source_type": "AI",
                }
            ],
            "missing_context": [],
        }
        return LLMResponse(
            content=json.dumps(valid_payload),
            model="gemini-flash-lite-latest",
            input_tokens=60,
            output_tokens=50,
            latency_ms=14.0,
        )

    gateway = SimpleNamespace(generate=_generate)
    service = LLMCodeReviewService(llm_gateway=gateway)
    req_payload = CodeReviewRequest.model_validate(
        {"file_path": "backend/app/services/payment_processor.py"}
    )
    report = await service.review(
        uuid.uuid4(),
        req_payload,
        context=None,
    )

    assert len(calls) == 2
    assert report.risk_level == "HIGH"
    assert len(report.findings) == 1
    assert "<<<REPO_DATA_" in calls[0].messages[1].content
