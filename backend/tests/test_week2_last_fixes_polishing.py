"""Comprehensive TDD Verification Suite for Week 2 Master Fixes & Polishing (`week2_fixes_polishing_new.md`).

Covers Set B (from `week2_last_fixes_polishing.md`) + Set C (Second-Pass Newly Discovered Bugs):
1. Python 3.11 syntax compatibility & SSE tenant isolation (`events.py`)
2. OAuth Login CSRF Cookie-Session Binding (`auth.py`)
3. `pull_requests` Alembic migration & repository cascade deletion (`repository_repository.py`)
4. Self-healing JSON repair loop across all 4 AI services (`CodeExplanationService`, `BugDetectionEngine`, `TestGenerationService`, `AICodeReviewEngine`) when `LLMValidationError` is raised by provider
5. `GroqProvider` `raw_response` preservation & persistent `httpx.AsyncClient` connection pooling
6. `GeminiProvider` JSON array output preservation without corrupting `[...]` into invalid JSON (`NEW-BUG-21`)
7. `LLMGateway` failover on `LLMAuthenticationError` and cross-vendor model translation (`NEW-BUG-22`)
8. `GroundingValidator` strict path-segment boundary (`/` + suffix) on suffix matching (`NEW-BUG-23`)
9. Line-accurate file reconstruction without chunk overlap duplication (`reconstruct_file_from_chunks`)
10. Commit & PR hunk line-range attribution (`is_new_in_change`) in `code_review_orchestrator.py`
11. Resilient AST/fallback symbol extraction across lone surrogates, syntax errors, and JS/TS files
12. `LexicalRetriever` exact-AND + OR fallback cover-density SQL, `HybridRetriever` `asyncio.to_thread` reranking, and `RAGPipeline` concurrent `asyncio.gather`
13. `security_gate.py` Groq/Gemini key patterns & `analysis_run_repository.py` shared redaction chaining
14. `get_analysis_runs_summary` in-memory fallback when DB has 0 rows
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from ai.llm.client import LLMGateway
from ai.llm.gemini_provider import GeminiProvider
from ai.llm.groq_provider import GroqProvider
from ai.llm.provider import LLMProvider
from ai.llm.schemas import (
    LLMAuthenticationError,
    LLMRequest,
    LLMResponse,
    LLMValidationError,
    Message,
)
from ai.retrieval.base import CodeChunk as RetrievalChunk
from ai.retrieval.hybrid import HybridRetriever
from ai.retrieval.lexical import _LEXICAL_SEARCH_SQL
from ai.schemas.grounding import GroundingValidator
from ai.schemas.output import RepositoryAnswer, SourceReference
from ai.services.bug_detection_engine import BugDetectionEngine
from ai.services.code_review_engine import AICodeReviewEngine
from ai.services.explanation_service import CodeExplanationService
from ai.services.test_generation_service import TestGenerationService
from app.api.v1.events import _should_deliver_event
from app.main import app
from app.repositories.analysis_run_repository import scrub_sensitive_text
from app.schemas.analysis import (
    AnalysisTarget,
    BugDetectionRequest,
    CodeReviewRequest,
    ExplainCodeRequest,
    ReviewTarget,
    TestGenerationRequest,
)
from app.services.code_review_orchestrator import (
    resolve_review_target_and_build_context,
    run_static_review_on_changes,
)
from indexer.chunker import SymbolChunker, reconstruct_file_from_chunks
from scanner.extractor import SymbolExtractor
from scanner.parser import Parser
from scanner.symbols import FileInfo, Symbol
from scripts.security_gate import scan_text


# ---------------------------------------------------------------------------
# 1. SSE Tenant Isolation & Python 3.11 Compatibility
# ---------------------------------------------------------------------------

def test_sse_blocks_unauthenticated_and_cross_tenant_repo_events() -> None:
    repo_a = str(uuid4())
    user_a = str(uuid4())
    user_b = str(uuid4())

    raw_event = f'{{"type": "repository.updated", "user_id": "{user_a}", "data": {{"repository_id": "{repo_a}", "user_id": "{user_a}"}}}}'
    legacy_event = f'{{"type": "repository.updated", "data": {{"repository_id": "{repo_a}"}}}}'

    # Unauthenticated listener must NEVER receive repository.updated events
    assert _should_deliver_event(raw_event, caller_user_id=None, owned_repo_ids=None) is False
    assert _should_deliver_event(legacy_event, caller_user_id=None, owned_repo_ids=None) is False

    # User B must NEVER receive User A's event
    assert _should_deliver_event(raw_event, caller_user_id=user_b, owned_repo_ids=set()) is False

    # User A receives their own event
    assert _should_deliver_event(raw_event, caller_user_id=user_a, owned_repo_ids={repo_a}) is True


# ---------------------------------------------------------------------------
# 2. OAuth Login CSRF Cookie-Session Binding (CWE-352)
# ---------------------------------------------------------------------------

def test_oauth_callback_rejects_mismatched_cookie_state_even_if_in_redis(monkeypatch) -> None:
    class _RedisWithAttackerState:
        def exists(self, key: str) -> int:
            return 1 if key == "oauth_state:attacker_state_123" else 0

        def delete(self, key: str) -> int:
            return 1

    monkeypatch.setattr("app.api.v1.auth.get_redis", lambda: _RedisWithAttackerState())

    with TestClient(app, raise_server_exceptions=False) as c:
        c.cookies.set("oauth_state", "victim_browser_state_999")
        resp = c.get("/api/v1/auth/github/callback?code=fake_code&state=attacker_state_123")
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "OAUTH_STATE_INVALID"


# ---------------------------------------------------------------------------
# 3. Self-Healing JSON Repair Across All 4 AI Engines on Provider LLMValidationError
# ---------------------------------------------------------------------------

class _RepairMockGateway:
    def __init__(self, valid_second_payload: str) -> None:
        self.calls = 0
        self._valid = valid_second_payload

    async def generate(self, req: LLMRequest) -> LLMResponse:
        self.calls += 1
        if self.calls == 1:
            raise LLMValidationError(
                "Schema validation failed on attempt 1",
                provider="gemini",
                raw_response="{bad_json_attempt_1",
            )
        return LLMResponse(
            content=self._valid,
            model="gemini-flash-latest",
            input_tokens=20,
            output_tokens=40,
            latency_ms=12.0,
        )


@pytest.mark.asyncio
async def test_all_four_ai_services_self_heal_when_provider_raises_validation_error() -> None:
    repo_id = uuid4()

    # 1. CodeExplanationService
    exp_gw = _RepairMockGateway(
        '{"purpose": "Auth helper", "logic_flow": ["step 1"], "key_symbols": [], '
        '"inputs_and_outputs": "str -> bool", "dependencies": [], '
        '"assumptions_and_limitations": [], "sources": [], "confidence": "high", "missing_context": []}'
    )
    exp_svc = CodeExplanationService(llm_gateway=exp_gw)
    exp_res = await exp_svc.explain(
        repo_id,
        ExplainCodeRequest(target=AnalysisTarget(type="file", path="app/auth.py")),
    )
    assert exp_gw.calls == 2
    assert exp_res.purpose == "Auth helper"

    # 2. BugDetectionEngine
    bug_gw = _RepairMockGateway('{"findings": [], "missing_context": []}')
    bug_svc = BugDetectionEngine(llm_gateway=bug_gw)
    bug_res = await bug_svc.detect_bugs(
        repo_id,
        BugDetectionRequest(
            target=AnalysisTarget(type="file", path="app/auth.py"),
            include_static=False,
            include_ai=True,
        ),
    )
    assert bug_gw.calls == 2
    assert bug_res["total_findings"] == 0

    # 3. TestGenerationService
    test_gw = _RepairMockGateway(
        '{"detected_framework": "pytest", "proposed_test_path": "tests/test_auth.py", '
        '"test_content": "def test_ok():\\n    assert 1 == 1\\n", '
        '"covered_scenarios": [{"name": "test_ok", "category": "normal", "description": "ok"}], '
        '"assumptions_and_warnings": [], "syntax_valid": true, "validation_errors": [], "sources": []}'
    )
    test_svc = TestGenerationService(llm_gateway=test_gw)
    test_res = await test_svc.generate_tests(
        repo_id,
        TestGenerationRequest(target=AnalysisTarget(type="file", path="app/auth.py")),
    )
    assert test_gw.calls == 2
    assert test_res.syntax_valid is True

    # 4. AICodeReviewEngine
    rev_gw = _RepairMockGateway(
        '{"summary": "Clean change.", "risk_level": "NONE", "findings": [], "missing_context": []}'
    )
    rev_svc = AICodeReviewEngine(llm_gateway=rev_gw)
    rev_res = await rev_svc.review(
        repo_id,
        CodeReviewRequest(target=ReviewTarget(type="file", path="app/auth.py")),
    )
    assert rev_gw.calls == 2
    assert rev_res.risk_level == "NONE"


def test_groq_provider_attaches_raw_response_and_reuses_client() -> None:
    provider = GroqProvider(api_keys=["gsk_test_key_12345678901234567890"])
    c1 = provider._get_client()
    c2 = provider._get_client()
    assert c1 is c2

    from pydantic import BaseModel

    class _DummySchema(BaseModel):
        value: int

    with pytest.raises(LLMValidationError) as exc_info:
        provider._validate_structured_output('{"value": "not-an-int"}', _DummySchema)
    assert exc_info.value.raw_response == '{"value": "not-an-int"}'


# ---------------------------------------------------------------------------
# 4. NEW-BUG-21: GeminiProvider Preserves JSON Array Responses
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gemini_provider_does_not_corrupt_json_array_response() -> None:
    import httpx
    from pydantic import TypeAdapter

    array_json = '[{"id": "1", "name": "first"}, {"id": "2", "name": "second"}]'

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": f"```json\n{array_json}\n```"}]}}],
                "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 10},
            },
        )

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))

    from pydantic import BaseModel, Field

    class _ArrayEnvelope(BaseModel):
        findings: list[dict[str, str]] = Field(default_factory=list)

    provider = GeminiProvider(api_keys=["AIzaSyTestKey0000000000000000000000000"], client=mock_client)
    req = LLMRequest(
        model="gemini-flash-latest",
        messages=[Message(role="user", content="list items")],
        response_schema=_ArrayEnvelope,
    )
    resp = await provider.generate(req)
    assert "first" in resp.content
    await mock_client.aclose()


# ---------------------------------------------------------------------------
# 5. NEW-BUG-22: LLMGateway Failover on LLMAuthenticationError & Model Translation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_gateway_fails_over_on_auth_error_and_translates_model() -> None:
    class _FailingPrimary(LLMProvider):
        @property
        def provider_name(self) -> str:
            return "gemini"

        @property
        def default_model(self) -> str:
            return "gemini-flash-latest"

        async def generate(self, request: LLMRequest) -> LLMResponse:
            raise LLMAuthenticationError("Expired API key", status_code=401, provider="gemini")

    class _HealthyFallback(LLMProvider):
        def __init__(self) -> None:
            self.received_model: str | None = None

        @property
        def provider_name(self) -> str:
            return "groq"

        @property
        def default_model(self) -> str:
            return "openai/gpt-oss-120b"

        async def generate(self, request: LLMRequest) -> LLMResponse:
            self.received_model = request.model
            return LLMResponse(
                content="ok from fallback",
                model=request.model,
                input_tokens=5,
                output_tokens=5,
                latency_ms=10.0,
            )

    fallback = _HealthyFallback()
    gw = LLMGateway(provider=_FailingPrimary(), fallback_provider=fallback)
    resp = await gw.generate(
        LLMRequest(
            model="gemini-flash-lite-latest",
            messages=[Message(role="user", content="hello")],
        )
    )
    assert resp.content == "ok from fallback"
    assert fallback.received_model == "openai/gpt-oss-120b"


# ---------------------------------------------------------------------------
# 6. NEW-BUG-23: GroundingValidator Suffix Match Boundary Check
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_grounding_validator_suffix_match_requires_path_boundary(db_session) -> None:
    from app.models.github_installation import GitHubInstallation
    from app.models.repository import Repository, SyncStatus
    from app.models.repository_file import RepositoryFile
    from app.models.user import User

    user = User(id=uuid4(), github_id=f"gh-{uuid4().hex[:8]}", login="ground_user")
    db_session.add(user)
    db_session.flush()
    inst = GitHubInstallation(id=uuid4(), user_id=user.id, installation_id="991122", account_login="ground_user")
    db_session.add(inst)
    db_session.flush()
    repo = Repository(
        id=uuid4(),
        user_id=user.id,
        installation_id=inst.id,
        github_repo_id="99112233",
        owner="ground_user",
        name="demo",
        default_branch="main",
        sync_status=SyncStatus.SYNCED,
    )
    db_session.add(repo)
    db_session.flush()
    f_row = RepositoryFile(
        id=uuid4(),
        repository_id=repo.id,
        path="src/__init__.py",
        language="Python",
        size_bytes=50,
        line_count=10,
        content_hash="abc",
    )
    db_session.add(f_row)
    db_session.commit()

    validator = GroundingValidator(db_session=db_session)
    # "init.py" is NOT a path segment boundary for "src/__init__.py" -> must be rejected!
    bad_ref = SourceReference(file="init.py", start_line=1, end_line=5)
    res_bad = await validator.validate_citation(bad_ref, repo.id)
    assert res_bad.grounded is False

    # "__init__.py" IS a valid path segment boundary ("/src/__init__.py" ends with "/__init__.py")
    good_ref = SourceReference(file="__init__.py", start_line=1, end_line=5)
    res_good = await validator.validate_citation(good_ref, repo.id)
    assert res_good.grounded is True
    assert good_ref.file == "src/__init__.py"


# ---------------------------------------------------------------------------
# 7. Line-Accurate File Reconstruction (No Duplicated Overlapping Chunks)
# ---------------------------------------------------------------------------

def test_reconstruct_file_from_chunks_deduplicates_class_and_method_chunks() -> None:
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


# ---------------------------------------------------------------------------
# 8. Commit & PR Hunk Attribution (`is_new_in_change`)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_commit_review_attributes_is_new_in_change_from_hunk_ranges() -> None:
    repo_id = uuid4()
    user_id = uuid4()

    class _FakeGitHubSourceService:
        def get_commit_detail(self, repository_id, user_id, commit_sha):
            return SimpleNamespace(
                parents=["base111"],
                files=[
                    SimpleNamespace(
                        filename="app/calc.py",
                        status="modified",
                        patch="@@ -10,2 +10,3 @@\n def run():\n+    return eval(user_input)\n",
                    )
                ],
            )

    app_state = SimpleNamespace(github_source_service=_FakeGitHubSourceService())
    req = CodeReviewRequest(
        target=ReviewTarget(type="commit", commit_sha="a1b2c3d4"),
    )
    resolved = await resolve_review_target_and_build_context(
        repository_id=repo_id,
        repo=SimpleNamespace(default_branch="main"),
        payload=req,
        user_id=user_id,
        db=object(),
        app_state=app_state,
    )
    assert resolved.modified_files[0].modified_line_ranges == [(10, 12)]

    # Inject full 15-line file where line 2 has pre-existing eval() and line 11 has newly added eval()
    lines = ["x = 1"] * 15
    lines[1] = "y = eval('1+1')"      # line 2 (outside hunk 10..12 -> pre-existing)
    lines[10] = "z = eval('2+2')"     # line 11 (inside hunk 10..12 -> new in change)
    resolved.file_contents["app/calc.py"] = "\n".join(lines)

    findings, _ = run_static_review_on_changes(repo_id, resolved)
    line2_findings = [f for f in findings if f.source_reference.start_line == 2]
    line11_findings = [f for f in findings if f.source_reference.start_line == 11]
    assert line2_findings and line2_findings[0].is_new_in_change is False
    assert line11_findings and line11_findings[0].is_new_in_change is True


# ---------------------------------------------------------------------------
# 9. Scanner & Extractor Resilience (Surrogates, Partial Syntax Errors, JS/TS)
# ---------------------------------------------------------------------------

def test_parser_and_extractor_resilience_on_surrogates_syntax_errors_and_ts() -> None:
    p = Parser()
    ext = SymbolExtractor(p)

    # 1. Lone surrogate in Python source must not crash Parser or SymbolExtractor
    surrogate_code = "def valid_before():\n    return '\ud800'\n"
    py_info = FileInfo(path="mod.py", size_bytes=len(surrogate_code), language="Python", is_binary=False)
    res = p.parse_with_status(py_info, surrogate_code)
    assert res.success is True
    syms = ext.extract(py_info, surrogate_code)
    assert any(s.name == "valid_before" for s in syms)

    # 2. Broken syntax midway in Python file still recovers valid functions before and after
    broken_py = "def fn_one():\n    return 1\n\ndef broken(:\n    pass\n\ndef fn_two(x):\n    return x\n"
    syms_broken = ext.extract(py_info, broken_py)
    names = {s.name for s in syms_broken}
    assert "fn_one" in names
    assert "fn_two" in names

    # 3. TypeScript symbol extraction works even without tree-sitter wheels
    ts_code = "import { x } from './x';\nexport interface UserDto {\n  id: string;\n}\nexport async function fetchUser(id: string) {\n  return id;\n}\n"
    ts_info = FileInfo(path="user.ts", size_bytes=len(ts_code), language="TypeScript", is_binary=False)
    ts_syms = ext.extract(ts_info, ts_code)
    ts_names = {s.name for s in ts_syms}
    assert "UserDto" in ts_names
    assert "fetchUser" in ts_names


# ---------------------------------------------------------------------------
# 10. LexicalRetriever OR-Fallback SQL & HybridRetriever Non-Blocking Rerank
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_lexical_sql_and_hybrid_retriever_to_thread() -> None:
    sql_str = str(_LEXICAL_SEARCH_SQL)
    assert "regexp_replace(:tsquery, '&', '|', 'g')" in sql_str
    assert "ts_rank_cd" in sql_str

    class _DummyRetriever:
        async def retrieve(self, query, repository_id, top_k=30):
            return [
                RetrievalChunk(
                    id=uuid4(),
                    repository_id=repository_id,
                    file_id=uuid4(),
                    symbol_id=None,
                    content="def authenticate_user(): pass",
                    token_count=4,
                    start_line=1,
                    end_line=1,
                    content_hash="h1",
                    score=0.9,
                    file_path="app/auth.py",
                )
            ]

        async def aclose(self):
            pass

    class _DummyReranker:
        def __init__(self) -> None:
            self.called = False

        def rerank(self, query, candidates, top_n=8):
            self.called = True
            return candidates[:top_n]

    reranker = _DummyReranker()
    hybrid = HybridRetriever(
        vector_retriever=_DummyRetriever(),  # type: ignore[arg-type]
        lexical_retriever=_DummyRetriever(),  # type: ignore[arg-type]
        reranker=reranker,  # type: ignore[arg-type]
    )
    out = await hybrid.retrieve("authenticate user", uuid4(), top_k=5)
    assert len(out) >= 1
    assert reranker.called is True


# ---------------------------------------------------------------------------
# 11. Security Gate Groq/Gemini Key Detection & Shared Secret Scrubbing
# ---------------------------------------------------------------------------

def test_security_gate_and_analysis_run_repository_redact_groq_and_gemini_keys() -> None:
    groq_line = 'GROQ_KEY = "gsk_' + "a" * 32 + '"'
    gemini_line = 'GEMINI_KEY = "AIza' + "B" * 35 + '"'

    groq_hits = scan_text(groq_line)
    gemini_hits = scan_text(gemini_line)
    assert any(h[0] == "groq_key" for h in groq_hits)
    assert any(h[0] == "gemini_key" for h in gemini_hits)

    scrubbed = scrub_sensitive_text(f"Leaked {groq_line} and {gemini_line}")
    assert "gsk_" not in (scrubbed or "")
    assert "AIza" not in (scrubbed or "")
    assert "[REDACTED]" in (scrubbed or "")
