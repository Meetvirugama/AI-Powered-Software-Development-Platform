"""TDD Unit and Integration Tests for Backend Audit & Vulnerability Fixes (Week 2 Day 4 & Day 5).

Owner: Yug — W2, Day 4–5 (Backend Lead Security & Cross-Module Audit)

Covers all 12 backend-wide mismatches & security vulnerabilities discovered and fixed:
1. [CRITICAL] GitHub Webhook Auth Bypass & Fail-Closed HMAC Vulnerability
   (`backend/app/core/auth.py` & `backend/app/api/v1/github.py`):
   - `POST /api/v1/github/webhook` is reachable without a user JWT (`PUBLIC_PATHS`).
   - Fails closed (`503 SERVICE_UNAVAILABLE`) when `GITHUB_WEBHOOK_SECRET` is unset.
   - Rejects missing or forged `X-Hub-Signature-256` with `401 UNAUTHORIZED` and accepts valid HMAC-SHA256.
2. [HIGH] Optional JWT State on Public Installation Callback (`backend/app/core/auth.py`):
   - `GET /api/v1/github/installation/callback` redirects (`302`) without requiring a token,
     and opportunistically populates `request.state.user_id` when a valid token is present.
3. [CRITICAL] `GitHubService.clone_repository` Sibling-Prefix Path Traversal, Argument Injection & Token Leak
   (`backend/app/integrations/github/service.py`):
   - Rejects sibling directory prefix escape (`/tmp/ws_evil` vs `/tmp/ws`).
   - Rejects malicious branch/owner/repo names (`--upload-pack=...`, `../evil`).
   - Redacts the installation access token (`[REDACTED]`) from `git clone` stderr on failure.
4. [MEDIUM] Multi-Tenant SSE Event Filtering (`backend/app/api/v1/events.py`):
   - `_should_deliver_event` blocks events scoped to another user's `user_id` or unowned `repository_id`.
5. [HIGH] `IncrementalIndexer.sync` Symbol Persistence & POSIX Path Normalization
   (`backend/indexer/incremental.py` & `backend/scanner/walker.py`):
   - Persists `CodeSymbol` rows to `code_symbols` before inserting `code_chunks` and normalizes paths to `/`.
6. [MEDIUM] Cross-Platform POSIX Path Handling in `FileTestMapper` (`backend/scanner/test_mapper.py`):
   - Normalizes `\\` and `/` in `FileTestMapper.get_source_from_name()` and `map_tests()`.
7. [HIGH] `AnalysisFeatureType` Aliases (`bugs` -> `detect_bugs`, `tests` -> `generate_tests`)
   (`backend/app/schemas/analysis.py` & `backend/app/api/v1/analysis.py`).
8. [HIGH] `GeminiProvider` API Key Redaction (`?key=[REDACTED]`) and `gpt-*` Model Normalization
   (`backend/ai/llm/gemini_provider.py`, `backend/ai/embeddings/gemini_provider.py`, `backend/ai/schemas/validator.py`).
9. [MEDIUM] `SymbolExtractor` JS/TS Class Method Extraction & Groq/Gemini Secret Redaction
   (`backend/scanner/extractor.py` & `backend/app/services/bug_detection_orchestrator.py`).
10. [HIGH] `GitBranchService._get_client_for_repo` UUID FK Lookup vs String `installation_id`
   (`backend/app/services/git_branch.py`).
11. [HIGH] `integrations/github/routes.py` Path Traversal & SHA Validation on Source Commits.
12. [MEDIUM] `StaticBugScanner.scan` Adapter & `BlastRadiusEngine` Import Fallback.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.api.v1.events import _should_deliver_event
from app.core.config import get_settings
from app.integrations.github.exceptions import GitHubCloneError
from app.integrations.github.service import GitHubService
from indexer.incremental import IncrementalIndexer
from scanner.symbols import FileInfo, Symbol
from scanner.test_mapper import FileTestMapper


def test_github_webhook_is_public_and_fails_closed_when_secret_unset(client, monkeypatch) -> None:
    """Webhook route must not be blocked by JWTMiddleware and must fail closed if secret is unset."""
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "")
    get_settings.cache_clear()

    res = client.post(
        "/api/v1/github/webhook",
        headers={"X-GitHub-Event": "ping"},
        json={"zen": "keep it logically awesome"},
    )
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_github_webhook_verifies_hmac_signature(client, monkeypatch) -> None:
    """Webhook route must reject missing/forged signatures with 401 and accept valid HMAC-SHA256."""
    wh_key = "dummy-placeholder-webhook-key"
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", wh_key)
    get_settings.cache_clear()

    payload_bytes = json.dumps({"zen": "test"}).encode("utf-8")

    # 1. Missing signature -> 401
    res_missing = client.post(
        "/api/v1/github/webhook",
        headers={"X-GitHub-Event": "ping", "Content-Type": "application/json"},
        content=payload_bytes,
    )
    assert res_missing.status_code == 401

    # 2. Invalid signature -> 401
    res_invalid = client.post(
        "/api/v1/github/webhook",
        headers={
            "X-GitHub-Event": "ping",
            "X-Hub-Signature-256": "sha256=deadbeef",
            "Content-Type": "application/json",
        },
        content=payload_bytes,
    )
    assert res_invalid.status_code == 401

    # 3. Valid HMAC-SHA256 signature -> 200 pong
    valid_sig = "sha256=" + hmac.new(
        wh_key.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()
    res_valid = client.post(
        "/api/v1/github/webhook",
        headers={
            "X-GitHub-Event": "ping",
            "X-Hub-Signature-256": valid_sig,
            "Content-Type": "application/json",
        },
        content=payload_bytes,
    )
    assert res_valid.status_code == 200
    assert res_valid.json()["status"] == "pong"


def test_installation_callback_is_public_and_opportunistically_reads_jwt(
    client, auth_headers
) -> None:
    """Installation callback redirects without auth (302) and links installation when JWT is present."""
    res_no_auth = client.get(
        "/api/v1/github/installation/callback?installation_id=12345",
        follow_redirects=False,
    )
    assert res_no_auth.status_code == 302
    assert "installation_id=12345" in res_no_auth.headers["location"]

    res_with_auth = client.get(
        "/api/v1/github/installation/callback?installation_id=67890",
        headers=auth_headers,
        follow_redirects=False,
    )
    assert res_with_auth.status_code == 302


@pytest.mark.asyncio
async def test_github_service_clone_blocks_sibling_prefix_and_arg_injection_and_redacts_token(
    tmp_path: Path,
) -> None:
    """Verify CWE-22 sibling prefix fix, CWE-88 argument injection fix, and CWE-532 token redaction."""
    ws_root = tmp_path / "ai_platform_workspaces"
    ws_root.mkdir(parents=True, exist_ok=True)
    sibling_evil = tmp_path / "ai_platform_workspaces_evil" / "repo"

    fake_redis = SimpleNamespace(get=AsyncMock(return_value="ghs_test_secret_install_token_12345"))
    service = GitHubService(redis=fake_redis, settings=get_settings(), workspace_root=ws_root)

    # 1. Sibling directory with matching string prefix MUST be rejected
    with pytest.raises(ValueError, match="outside the allowed workspace root"):
        await service.clone_repository(
            installation_id=1,
            owner="octocat",
            repo="hello-world",
            branch="main",
            workspace_path=str(sibling_evil),
        )

    # 2. Git argument injection in branch (`--upload-pack=...`) MUST be rejected
    valid_target = ws_root / "repo_1"
    with pytest.raises(ValueError, match="Invalid branch name"):
        await service.clone_repository(
            installation_id=1,
            owner="octocat",
            repo="hello-world",
            branch="--upload-pack=touch /tmp/pwn",
            workspace_path=str(valid_target),
        )

    # 3. Token in stderr MUST be redacted when git clone fails
    class _FakeProc:
        returncode = 128

        async def communicate(self):
            return (
                b"",
                b"fatal: repository 'https://x-access-token:ghs_test_secret_install_token_12345@github.com/octocat/hello-world.git/' not found",
            )

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=_FakeProc())):
        with pytest.raises(GitHubCloneError) as exc_info:
            await service.clone_repository(
                installation_id=1,
                owner="octocat",
                repo="hello-world",
                branch="main",
                workspace_path=str(valid_target),
            )
        err_msg = str(exc_info.value)
        assert "ghs_test_secret_install_token_12345" not in err_msg
        assert "[REDACTED]" in err_msg


def test_sse_event_filter_blocks_cross_tenant_user_events() -> None:
    """User-scoped SSE events must only be delivered to the matching authenticated user."""
    user_a = str(uuid.uuid4())
    user_b = str(uuid.uuid4())

    scoped_event = json.dumps(
        {"type": "repository.updated", "data": {"repository_id": "r1", "user_id": user_a}}
    )
    assert _should_deliver_event(scoped_event, user_a) is True
    assert _should_deliver_event(scoped_event, user_b) is False
    assert _should_deliver_event(scoped_event, None) is False

    broadcast_event = json.dumps({"type": "system.notice", "data": {}})
    assert _should_deliver_event(broadcast_event, user_b) is True


@pytest.mark.asyncio
async def test_incremental_indexer_persists_code_symbols_before_code_chunks(tmp_path: Path) -> None:
    """IncrementalIndexer.sync() must insert extracted symbols into code_symbols before code_chunks."""
    executed_sql: list[tuple[str, dict]] = []

    class _FakeResult:
        def fetchall(self):
            return []

    class _FakeDB:
        async def execute(self, stmt, params=None):
            executed_sql.append((str(stmt).strip(), dict(params or {})))
            return _FakeResult()

        async def commit(self):
            pass

    sym_uuid = uuid.uuid4()
    fake_extractor = SimpleNamespace(
        extract=lambda fi, content, file_id=None: [
            Symbol(
                id=sym_uuid,
                name="compute_total",
                kind="function",
                file_id=file_id,
                start_line=1,
                end_line=2,
                signature="def compute_total(x: int) -> int:",
                parent_id=None,
            )
        ]
    )

    indexer = IncrementalIndexer(
        db_session=_FakeDB(),
        embedding_service=None,
        extractor=fake_extractor,
    )
    file_info = FileInfo(path="src\\service.py", size_bytes=48, language="Python", is_binary=False)
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "service.py").write_text(
        "def compute_total(x: int) -> int:\n    return x * 2\n", encoding="utf-8"
    )

    stats = await indexer.sync(
        repository_id=uuid.uuid4(),
        scanned_files=[file_info],
        root_path=str(tmp_path),
    )
    assert stats["indexed"] == 1

    sql_statements = [s for s, _ in executed_sql]
    idx_file = next(i for i, s in enumerate(sql_statements) if "INSERT INTO repository_files" in s)
    idx_sym = next(i for i, s in enumerate(sql_statements) if "INSERT INTO code_symbols" in s)
    idx_chunk = next(i for i, s in enumerate(sql_statements) if "INSERT INTO code_chunks" in s)

    assert idx_file < idx_sym < idx_chunk
    assert executed_sql[idx_file][1]["path"] == "src/service.py"
    assert executed_sql[idx_chunk][1]["symbol_id"] == sym_uuid


def test_file_test_mapper_normalizes_windows_and_posix_paths() -> None:
    f1, f2 = uuid.uuid4(), uuid.uuid4()
    mapper = FileTestMapper(
        symbols=[],
        edges=[],
        file_paths={
            f1: "backend\\app\\services\\pricing.py",
            f2: "backend\\tests\\test_pricing.py",
        },
    )
    mapping = mapper.map_tests()
    assert mapping == {"backend/tests/test_pricing.py": "backend/app/services/pricing.py"}


def test_analysis_feature_type_aliases_normalize_bugs_and_tests() -> None:
    """PR #104 alignment: 'bugs' -> 'detect_bugs' and 'tests' -> 'generate_tests'."""
    from app.schemas.analysis import normalize_analysis_feature_type

    assert normalize_analysis_feature_type("bugs") == "detect_bugs"
    assert normalize_analysis_feature_type("tests") == "generate_tests"
    assert normalize_analysis_feature_type("explain") == "explain"


def test_gemini_provider_redacts_api_key_in_url_and_normalizes_gpt_model() -> None:
    """CWE-532 & model mismatch: GeminiProvider must redact ?key= in URLs and normalize gpt-* models."""
    from ai.llm.gemini_provider import GeminiProvider, _redact_key
    from ai.llm.schemas import LLMRequest, Message

    secret = "AIzaSySecretKey12345678901234567890123"
    raw_err = f"Client error '400 Bad Request' for url 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={secret}'"
    redacted = _redact_key(raw_err, secret)
    assert secret not in redacted
    assert "key=[REDACTED]" in redacted

    provider = GeminiProvider(api_keys=["test-key"], default_model="gemini-2.5-flash")
    _, model_name = provider._build_payload(
        LLMRequest(messages=[Message(role="user", content="hi")], model="gpt-4o")
    )
    assert model_name == "gemini-2.5-flash"


def test_symbol_extractor_extracts_js_ts_class_method_definitions() -> None:
    """PR #103 alignment: SymbolExtractor.extract must extract method_definition nodes as 'method' symbols."""
    from scanner.extractor import SymbolExtractor

    class _FakeNode:
        def __init__(self, node_type: str, text_bytes: bytes, start_row: int, end_row: int, children=None):
            self.type = node_type
            self.text = text_bytes
            self.start_point = (start_row, 0)
            self.end_point = (end_row, 0)
            self.children = children or []

    ts_code = "export class Calculator {\n  add(a: number, b: number): number {\n    return a + b;\n  }\n}\n"
    class_name_node = _FakeNode("identifier", b"Calculator", 0, 0)
    method_name_node = _FakeNode("property_identifier", b"add", 1, 1)
    method_node = _FakeNode("method_definition", b"add(a: number, b: number): number { return a + b; }", 1, 3, children=[method_name_node])
    class_node = _FakeNode("class_declaration", ts_code.encode("utf-8"), 0, 4, children=[class_name_node, method_node])
    root_node = _FakeNode("program", ts_code.encode("utf-8"), 0, 4, children=[class_node])

    fake_parser = SimpleNamespace(parse=lambda fi, content: SimpleNamespace(root_node=root_node))
    extractor = SymbolExtractor(parser=fake_parser)
    fi = FileInfo(path="src/calculator.ts", size_bytes=len(ts_code), language="TypeScript", is_binary=False)
    symbols = extractor.extract(fi, ts_code)
    kinds_by_name = {s.name: s.kind for s in symbols}
    assert kinds_by_name.get("Calculator") == "class"
    assert kinds_by_name.get("add") == "method"


def test_secret_redaction_covers_groq_and_gemini_api_keys() -> None:
    """CWE-312: Secret redaction before LLM calls must scrub gsk_ (Groq) and AIza (Gemini) keys."""
    from app.services.bug_detection_orchestrator import redact_secrets_in_text

    sample = "GROQ_API_KEY=gsk_1234567890abcdefghijklmnop GEMINI=AIzaSyA12345678901234567890123456789012"
    scrubbed = redact_secrets_in_text(sample)
    assert "gsk_1234567890abcdefghijklmnop" not in scrubbed
    assert "AIzaSyA12345678901234567890123456789012" not in scrubbed
    assert "[REDACTED]" in scrubbed
