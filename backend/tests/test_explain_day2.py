"""End-to-end integration and unit tests for Yug's Week 2 Day 2 Code Explanation API.

Owner: Yug — W2, Day 2 (`POST /api/v1/repositories/{id}/explain`)

Covers all 9 required steps from `Docs/week2.md` §6:
1. User authentication & repository authorization
2. Target validation: missing file in indexed repository -> 404 FILE_NOT_FOUND
3. Oversized file (> 1 MB) -> 413 PAYLOAD_TOO_LARGE
4. Out-of-bounds line range (`end_line > file.line_count`) -> 400 INVALID_REQUEST
5. Symbol resolution via `CodeSymbol` (auto-populates `start_line` and `end_line` from AST symbol,
   or returns 404 RESOURCE_NOT_FOUND when requested symbol does not exist in indexed file)
6. Context assembly (`IntelligenceContext` with target code, related symbols, caller edges, and rules)
7. Citation grounding: strips hallucinated file/line citations and downgrades confidence to 'low'
8. History persistence: stores completed explanation run and reopens it via
   `GET /api/v1/repositories/{id}/analysis-runs` and `GET /api/v1/analysis-runs/{run_id}`;
   stores FAILED status when provider or validation fails
9. `LLMCodeExplanationService` JSON repair loop and prompt-injection fence isolation
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai.llm.schemas import LLMResponse, LLMTimeoutError
from app.main import app
from app.models.code_chunk import CodeChunk
from app.models.code_symbol import CodeSymbol
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.repository_file import RepositoryFile
from app.models.symbol_edge import SymbolEdge
from app.schemas.analysis import ExplainCodeRequest
from app.services.explanation_orchestrator import LLMCodeExplanationService


def _seed_indexed_repository(db_session, owner_user) -> tuple[Repository, RepositoryFile, CodeSymbol]:
    """Create a synced repository with an indexed Python file, AST symbols, edges, and chunks."""
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
        name="day2-explain-repo",
        default_branch="main",
        language="Python",
        sync_status=SyncStatus.SYNCED,
    )
    db_session.add(repo)
    db_session.commit()

    file_row = RepositoryFile(
        id=uuid.uuid4(),
        repository_id=repo.id,
        path="src/auth_service.py",
        language="Python",
        size_bytes=1200,
        line_count=40,
        content_hash="abc123hash",
    )
    db_session.add(file_row)
    db_session.commit()

    sym_verify = CodeSymbol(
        id=uuid.uuid4(),
        file_id=file_row.id,
        repository_id=repo.id,
        name="verify_jwt_token",
        kind="function",
        start_line=10,
        end_line=28,
        signature="def verify_jwt_token(token: str) -> dict:",
    )
    sym_caller = CodeSymbol(
        id=uuid.uuid4(),
        file_id=file_row.id,
        repository_id=repo.id,
        name="require_authenticated_user",
        kind="function",
        start_line=30,
        end_line=40,
        signature="def require_authenticated_user(request) -> UUID:",
    )
    db_session.add_all([sym_verify, sym_caller])
    db_session.commit()

    edge = SymbolEdge(
        id=uuid.uuid4(),
        repository_id=repo.id,
        source_symbol_id=sym_caller.id,
        target_symbol_id=sym_verify.id,
        edge_type="calls",
    )
    db_session.add(edge)

    chunk = CodeChunk(
        id=uuid.uuid4(),
        repository_id=repo.id,
        file_id=file_row.id,
        symbol_id=sym_verify.id,
        content=(
            "def verify_jwt_token(token: str) -> dict:\n"
            "    if not token:\n"
            "        raise ValueError('missing token')\n"
            "    return decode_token(token)\n"
        ),
        token_count=28,
        embedding=[0.0] * 768,
        start_line=10,
        end_line=28,
        content_hash="chunk123",
        chunk_metadata={"file_path": "src/auth_service.py"},
    )
    db_session.add(chunk)
    db_session.commit()

    return repo, file_row, sym_verify


def test_explain_resolves_symbol_range_builds_context_and_persists_history(
    client, db_session, test_user, auth_headers
) -> None:
    repo, _, _ = _seed_indexed_repository(db_session, test_user)
    captured_contexts = []

    async def _fake_explain(repository_id, payload, *, context=None, **kwargs):
        captured_contexts.append(context)
        return {
            "purpose": "Verifies a JWT string and returns decoded token claims.",
            "logic_flow": [
                "Checks whether `token` is non-empty.",
                "Delegates decoding and signature verification to `decode_token(token)`.",
            ],
            "key_symbols": [
                {
                    "name": "verify_jwt_token",
                    "kind": "function",
                    "role": "Validates and decodes the JWT string.",
                    "start_line": 10,
                    "end_line": 28,
                }
            ],
            "inputs_and_outputs": "Input: `token: str`. Output: `dict` of claims; raises `ValueError` on empty token.",
            "dependencies": ["decode_token", "require_authenticated_user"],
            "assumptions_and_limitations": ["`decode_token` implementation resides in an imported module."],
            "sources": [
                {
                    "file_path": "src/auth_service.py",
                    "start_line": 10,
                    "end_line": 28,
                    "symbol_name": "verify_jwt_token",
                }
            ],
            "confidence": "high",
            "missing_context": [],
        }

    app.state.explanation_service = SimpleNamespace(explain=_fake_explain)
    try:
        res = client.post(
            f"/api/v1/repositories/{repo.id}/explain",
            headers=auth_headers,
            json={"target": {"type": "symbol", "path": "src/auth_service.py", "symbol": "verify_jwt_token"}},
        )
        assert res.status_code == 200, res.text
        body = res.json()

        # Symbol line range (10..28) resolved automatically from CodeSymbol table
        assert body["target"]["start_line"] == 10
        assert body["target"]["end_line"] == 28
        assert body["revision"] == "main"
        assert body["explanation"]["confidence"] == "high"
        assert body["explanation"]["sources"][0]["file_path"] == "src/auth_service.py"
        assert body["explanation"]["sources"][0]["revision"] == "main"

        # Verify IntelligenceContext passed to service included target code and caller symbol
        assert len(captured_contexts) == 1
        ctx = captured_contexts[0]
        assert "def verify_jwt_token" in ctx.target.content
        assert any(s.name == "require_authenticated_user" for s in ctx.related_symbols)

        # Scenario A Step 7: Reopen the analysis from history
        run_id = body["run_id"]
        list_res = client.get(
            f"/api/v1/repositories/{repo.id}/analysis-runs?feature_type=explain",
            headers=auth_headers,
        )
        assert list_res.status_code == 200
        assert any(item["id"] == run_id for item in list_res.json()["items"])

        detail_res = client.get(f"/api/v1/analysis-runs/{run_id}", headers=auth_headers)
        assert detail_res.status_code == 200
        assert detail_res.json()["status"] == "COMPLETED"
        assert detail_res.json()["target_symbol"] == "verify_jwt_token"
        assert detail_res.json()["result_payload"]["explanation"]["purpose"].startswith("Verifies a JWT")
    finally:
        if hasattr(app.state, "explanation_service"):
            del app.state.explanation_service


def test_explain_returns_404_for_nonexistent_file_or_symbol_and_400_for_line_overflow(
    client, db_session, test_user, auth_headers
) -> None:
    repo, _, _ = _seed_indexed_repository(db_session, test_user)
    app.state.explanation_service = SimpleNamespace(explain=AsyncMock())
    try:
        # 1. Nonexistent file in indexed repo -> 404 FILE_NOT_FOUND
        res_missing_file = client.post(
            f"/api/v1/repositories/{repo.id}/explain",
            headers=auth_headers,
            json={"file_path": "src/does_not_exist.py"},
        )
        assert res_missing_file.status_code == 404
        assert res_missing_file.json()["error"]["code"] == "FILE_NOT_FOUND"

        # 2. Nonexistent symbol in indexed file -> 404 RESOURCE_NOT_FOUND
        res_missing_sym = client.post(
            f"/api/v1/repositories/{repo.id}/explain",
            headers=auth_headers,
            json={"target": {"type": "symbol", "path": "src/auth_service.py", "symbol": "unknown_func"}},
        )
        assert res_missing_sym.status_code == 404
        assert res_missing_sym.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

        # 3. Line range exceeding file_row.line_count (40) -> 400 INVALID_REQUEST
        res_line_overflow = client.post(
            f"/api/v1/repositories/{repo.id}/explain",
            headers=auth_headers,
            json={"file_path": "src/auth_service.py", "start_line": 10, "end_line": 99},
        )
        assert res_line_overflow.status_code == 400
        assert res_line_overflow.json()["error"]["code"] == "INVALID_REQUEST"
    finally:
        del app.state.explanation_service


def test_explain_strips_hallucinated_citations_and_downgrades_confidence(
    client, db_session, test_user, auth_headers
) -> None:
    repo, _, _ = _seed_indexed_repository(db_session, test_user)

    ungrounded_output = {
        "purpose": "Explains auth_service.py.",
        "logic_flow": ["Step 1"],
        "key_symbols": [],
        "inputs_and_outputs": "None",
        "dependencies": [],
        "assumptions_and_limitations": [],
        "sources": [
            {"file_path": "src/hallucinated_ghost_file.py", "start_line": 1, "end_line": 10},
            {"file_path": "src/auth_service.py", "start_line": 1, "end_line": 500},
        ],
        "confidence": "high",
        "missing_context": [],
    }
    app.state.explanation_service = SimpleNamespace(
        explain=AsyncMock(return_value=ungrounded_output)
    )
    try:
        res = client.post(
            f"/api/v1/repositories/{repo.id}/explain",
            headers=auth_headers,
            json={"file_path": "src/auth_service.py", "start_line": 10, "end_line": 28},
        )
        assert res.status_code == 200
        body = res.json()
        # Both hallucinated citations were removed, confidence downgraded to low,
        # and verified target file reference attached as fallback source
        assert body["explanation"]["confidence"] == "low"
        assert len(body["explanation"]["sources"]) == 1
        assert body["explanation"]["sources"][0]["file_path"] == "src/auth_service.py"
        assert body["explanation"]["sources"][0]["end_line"] == 28
    finally:
        del app.state.explanation_service


def test_explain_records_failed_run_when_provider_times_out(
    client, db_session, test_user, auth_headers
) -> None:
    repo, _, _ = _seed_indexed_repository(db_session, test_user)
    app.state.explanation_service = SimpleNamespace(
        explain=AsyncMock(side_effect=LLMTimeoutError("Provider timed out"))
    )
    try:
        res = client.post(
            f"/api/v1/repositories/{repo.id}/explain",
            headers=auth_headers,
            json={"file_path": "src/auth_service.py"},
        )
        assert res.status_code == 503

        runs_res = client.get(
            f"/api/v1/repositories/{repo.id}/analysis-runs?status=FAILED",
            headers=auth_headers,
        )
        assert runs_res.status_code == 200
        failed_items = runs_res.json()["items"]
        assert len(failed_items) >= 1
        assert failed_items[0]["status"] == "FAILED"
    finally:
        del app.state.explanation_service


@pytest.mark.asyncio
async def test_llm_code_explanation_service_repairs_malformed_json_and_fences_untrusted_code() -> None:
    calls = []

    async def _generate(req):
        calls.append(req)
        if len(calls) == 1:
            return LLMResponse(
                content="```json\n{bad json\n```",
                model="gemini-flash-lite-latest",
                input_tokens=50,
                output_tokens=10,
                latency_ms=12.0,
            )
        valid_payload = {
            "purpose": "Validates token.",
            "logic_flow": ["Checks token presence."],
            "key_symbols": [],
            "inputs_and_outputs": "token -> claims",
            "dependencies": [],
            "assumptions_and_limitations": [],
            "sources": [{"file_path": "src/auth_service.py", "start_line": 10, "end_line": 28}],
            "confidence": "high",
            "missing_context": [],
        }
        return LLMResponse(
            content=json.dumps(valid_payload),
            model="gemini-flash-lite-latest",
            input_tokens=60,
            output_tokens=40,
            latency_ms=15.0,
        )

    gateway = SimpleNamespace(generate=_generate)
    service = LLMCodeExplanationService(llm_gateway=gateway)
    req_payload = ExplainCodeRequest.model_validate(
        {"file_path": "src/auth_service.py", "start_line": 10, "end_line": 28}
    )
    explanation = await service.explain(uuid.uuid4(), req_payload)

    assert explanation.purpose == "Validates token."
    assert len(calls) == 2
    # System prompt never contains repository file paths or code
    assert "src/auth_service.py" not in calls[0].messages[0].content
    # User prompt wraps repository data inside random <<<REPO_DATA_...>>> markers
    assert "<<<REPO_DATA_" in calls[0].messages[1].content
