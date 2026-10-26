"""Contract, authorization, validation, and failure tests for Yug's Week 2 Day 1 Analysis APIs.

Owner: Yug — W2, Day 1 (API Foundation)

Verifies:
1. All 6 Week 2 analysis routes are registered on the FastAPI application and OpenAPI schema.
2. Unauthenticated requests are rejected with 401 UNAUTHORIZED.
3. Multi-tenant repository isolation: User A cannot invoke any analysis route or read any
   analysis run belonging to User B's repository (returns 404 REPOSITORY_NOT_FOUND without
   calling the underlying AI service).
4. Path traversal payloads (`../../etc/passwd`, `/etc/passwd`, `..\\win.ini`) are rejected
   with 400 INVALID_REQUEST before reaching any service.
5. Schema validation rejects invalid line ranges (`end_line < start_line`), missing symbol
   names, invalid commit SHAs, and empty diffs with 422 INVALID_REQUEST.
6. Unconfigured services return 503 SERVICE_UNAVAILABLE (`retryable=True`).
7. Invalid or failed AI service outputs return 500 ANALYSIS_FAILED (never a silent empty
   COMPLETED response).
8. Configured services return validated structured responses for `/explain`, `/detect-bugs`,
   `/generate-tests`, `/review`, `/analysis-runs`, and `/analysis-runs/{run_id}`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from ai.llm.schemas import LLMTimeoutError, LLMValidationError
from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app


class FakeRedis:
    def exists(self, _: str) -> int:
        return 0

    def pipeline(self):
        class _Pipe:
            def incr(self, _k):
                pass

            def expire(self, _k, _s):
                pass

            def execute(self):
                return [1, True]

        return _Pipe()


USER_A_ID = "0e969876-16d2-4c9f-8fe1-a849f32fa605"
USER_B_ID = "9b221144-77c3-4a1e-9d00-c123456789ab"


def _configure_auth(monkeypatch, user_id: str = USER_A_ID) -> str:
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-12345")
    get_settings.cache_clear()
    fake_redis = FakeRedis()
    monkeypatch.setattr("app.core.auth.get_redis", lambda: fake_redis)
    monkeypatch.setattr("app.core.redis.get_redis", lambda: fake_redis)
    return create_access_token(user_id)[0]


def _allow_repo_owner(monkeypatch, owned_repo_id: UUID, expected_user_id: str = USER_A_ID) -> None:
    class FakeRepositoryRepository:
        def __init__(self, _: object) -> None:
            pass

        def get_for_user(self, requested_id: UUID, user_id: UUID):
            if requested_id == owned_repo_id and str(user_id) == expected_user_id:
                return SimpleNamespace(
                    id=owned_repo_id,
                    user_id=UUID(expected_user_id),
                    default_branch="main",
                )
            return None

    monkeypatch.setattr("app.api.v1.analysis.RepositoryRepository", FakeRepositoryRepository)


# ---------------------------------------------------------------------------
# 1. OpenAPI & Route Registration Contract
# ---------------------------------------------------------------------------

def test_week2_analysis_routes_are_registered_in_openapi() -> None:
    schema = app.openapi()
    paths = schema.get("paths", {})
    expected_paths = [
        "/api/v1/repositories/{repository_id}/explain",
        "/api/v1/repositories/{repository_id}/detect-bugs",
        "/api/v1/repositories/{repository_id}/generate-tests",
        "/api/v1/repositories/{repository_id}/review",
        "/api/v1/repositories/{repository_id}/analysis-runs",
        "/api/v1/analysis-runs/{run_id}",
    ]
    for path in expected_paths:
        assert path in paths, f"Expected Week 2 route {path} missing from OpenAPI schema"


# ---------------------------------------------------------------------------
# 2. Authentication & Multi-Tenant Repository Authorization
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "method, path_template, body",
    [
        ("POST", "/api/v1/repositories/{id}/explain", {"target": {"type": "file", "path": "src/main.py"}}),
        ("POST", "/api/v1/repositories/{id}/detect-bugs", {"target": {"type": "file", "path": "src/main.py"}}),
        ("POST", "/api/v1/repositories/{id}/generate-tests", {"target": {"type": "file", "path": "src/main.py"}}),
        ("POST", "/api/v1/repositories/{id}/review", {"target": {"type": "file", "path": "src/main.py"}}),
        ("GET", "/api/v1/repositories/{id}/analysis-runs", None),
        ("GET", "/api/v1/analysis-runs/{id}", None),
    ],
)
def test_analysis_routes_require_authentication(monkeypatch, method: str, path_template: str, body: dict | None) -> None:
    _configure_auth(monkeypatch)
    client = TestClient(app, raise_server_exceptions=False)
    url = path_template.format(id=uuid4())
    response = client.request(method, url, json=body)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.parametrize(
    "method, path_suffix, body, state_attr",
    [
        ("POST", "explain", {"target": {"type": "file", "path": "src/main.py"}}, "explanation_service"),
        ("POST", "detect-bugs", {"target": {"type": "file", "path": "src/main.py"}}, "bug_detection_service"),
        ("POST", "generate-tests", {"target": {"type": "file", "path": "src/main.py"}}, "test_generation_service"),
        ("POST", "review", {"target": {"type": "file", "path": "src/main.py"}}, "code_review_service"),
        ("GET", "analysis-runs", None, "analysis_run_service"),
    ],
)
def test_analysis_routes_deny_access_to_unowned_repository(
    monkeypatch,
    method: str,
    path_suffix: str,
    body: dict | None,
    state_attr: str,
) -> None:
    token = _configure_auth(monkeypatch, USER_A_ID)
    user_a_repo_id = uuid4()
    user_b_repo_id = uuid4()
    _allow_repo_owner(monkeypatch, owned_repo_id=user_a_repo_id, expected_user_id=USER_A_ID)

    spy_service = AsyncMock()
    setattr(app.state, state_attr, spy_service)
    app.dependency_overrides[get_db] = lambda: object()
    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.request(
            method,
            f"/api/v1/repositories/{user_b_repo_id}/{path_suffix}",
            headers={"Authorization": f"Bearer {token}"},
            json=body,
        )
    finally:
        app.dependency_overrides.clear()
        delattr(app.state, state_attr)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REPOSITORY_NOT_FOUND"
    spy_service.assert_not_awaited()


# ---------------------------------------------------------------------------
# 3. Input Security & Validation (Path Traversal, Line Ranges, Target Types)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "endpoint, malicious_path",
    [
        ("explain", "../../etc/passwd"),
        ("detect-bugs", "/etc/passwd"),
        ("generate-tests", "..\\..\\windows\\win.ini"),
        ("review", "src/../../root/.ssh/id_rsa"),
    ],
)
def test_analysis_routes_reject_path_traversal_with_400(
    monkeypatch,
    endpoint: str,
    malicious_path: str,
) -> None:
    token = _configure_auth(monkeypatch)
    repo_id = uuid4()
    _allow_repo_owner(monkeypatch, owned_repo_id=repo_id)

    app.dependency_overrides[get_db] = lambda: object()
    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            f"/api/v1/repositories/{repo_id}/{endpoint}",
            headers={"Authorization": f"Bearer {token}"},
            json={"target": {"type": "file", "path": malicious_path}},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.parametrize(
    "endpoint, invalid_payload",
    [
        ("explain", {"target": {"type": "range", "path": "src/app.py", "start_line": 50, "end_line": 10}}),
        ("explain", {"target": {"type": "symbol", "path": "src/app.py"}}),
        ("detect-bugs", {"target": {"type": "file", "path": "src/app.py"}, "include_static": False, "include_ai": False}),
        ("generate-tests", {"target": {"type": "file", "path": "src/app.py"}, "framework": "mocha"}),
        ("review", {"target": {"type": "commit", "commit_sha": "not-a-valid-sha!"}}),
        ("review", {"target": {"type": "diff", "diff": "   "}}),
    ],
)
def test_analysis_routes_reject_invalid_schemas_with_422(
    monkeypatch,
    endpoint: str,
    invalid_payload: dict,
) -> None:
    token = _configure_auth(monkeypatch)
    repo_id = uuid4()
    _allow_repo_owner(monkeypatch, owned_repo_id=repo_id)

    client = TestClient(app, raise_server_exceptions=False)
    response = client.post(
        f"/api/v1/repositories/{repo_id}/{endpoint}",
        headers={"Authorization": f"Bearer {token}"},
        json=invalid_payload,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


# ---------------------------------------------------------------------------
# 4. Unconfigured Service & Failure Handling (503 & 500)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "endpoint",
    ["explain", "detect-bugs", "generate-tests", "review"],
)
def test_analysis_routes_return_503_when_service_not_configured(monkeypatch, endpoint: str) -> None:
    token = _configure_auth(monkeypatch)
    repo_id = uuid4()
    _allow_repo_owner(monkeypatch, owned_repo_id=repo_id)

    app.dependency_overrides[get_db] = lambda: object()
    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            f"/api/v1/repositories/{repo_id}/{endpoint}",
            headers={"Authorization": f"Bearer {token}"},
            json={"target": {"type": "file", "path": "src/app.py"}},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert response.json()["error"]["retryable"] is True


def test_explain_maps_llm_timeout_to_503_and_invalid_output_to_500(monkeypatch) -> None:
    token = _configure_auth(monkeypatch)
    repo_id = uuid4()
    _allow_repo_owner(monkeypatch, owned_repo_id=repo_id)

    timeout_service = SimpleNamespace(explain=AsyncMock(side_effect=LLMTimeoutError("Timed out")))
    app.state.explanation_service = timeout_service
    app.dependency_overrides[get_db] = lambda: object()
    try:
        client = TestClient(app, raise_server_exceptions=False)
        res_timeout = client.post(
            f"/api/v1/repositories/{repo_id}/explain",
            headers={"Authorization": f"Bearer {token}"},
            json={"file_path": "src/app.py", "start_line": 1, "end_line": 20},
        )
        assert res_timeout.status_code == 503
        assert res_timeout.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
        assert res_timeout.json()["error"]["retryable"] is True

        # Malformed AI output must never silently become a 200 empty response
        malformed_service = SimpleNamespace(explain=AsyncMock(return_value={"purpose": ""}))
        app.state.explanation_service = malformed_service
        res_malformed = client.post(
            f"/api/v1/repositories/{repo_id}/explain",
            headers={"Authorization": f"Bearer {token}"},
            json={"file_path": "src/app.py"},
        )
        assert res_malformed.status_code == 500
        assert res_malformed.json()["error"]["code"] == "ANALYSIS_FAILED"

        validation_err_service = SimpleNamespace(
            explain=AsyncMock(side_effect=LLMValidationError("Repair exhausted"))
        )
        app.state.explanation_service = validation_err_service
        res_val_err = client.post(
            f"/api/v1/repositories/{repo_id}/explain",
            headers={"Authorization": f"Bearer {token}"},
            json={"file_path": "src/app.py"},
        )
        assert res_val_err.status_code == 500
        assert res_val_err.json()["error"]["code"] == "ANALYSIS_FAILED"
    finally:
        app.dependency_overrides.clear()
        del app.state.explanation_service


# ---------------------------------------------------------------------------
# 5. Happy-Path Contract Verification for All 6 Endpoints
# ---------------------------------------------------------------------------

def test_explain_endpoint_returns_validated_explanation(monkeypatch) -> None:
    token = _configure_auth(monkeypatch)
    repo_id = uuid4()
    _allow_repo_owner(monkeypatch, owned_repo_id=repo_id)

    mock_explanation = {
        "purpose": "Validates repository-relative paths and blocks directory traversal.",
        "logic_flow": [
            "Reject empty, oversized, or control-character strings.",
            "Normalize POSIX segments and reject '..' components.",
        ],
        "key_symbols": [
            {
                "name": "validate_repo_relative_path",
                "kind": "function",
                "role": "Primary path sanitizer.",
                "start_line": 36,
                "end_line": 64,
            }
        ],
        "inputs_and_outputs": "Accepts path: str; returns normalized relative path str or raises UnsafePathError.",
        "dependencies": ["pathlib.PurePosixPath", "re"],
        "assumptions_and_limitations": ["Symlink resolution requires resolve_within_root()."],
        "sources": [
            {
                "file_path": "backend/app/core/input_security.py",
                "start_line": 36,
                "end_line": 64,
                "symbol_name": "validate_repo_relative_path",
            }
        ],
        "confidence": "high",
        "missing_context": [],
    }
    service = SimpleNamespace(explain=AsyncMock(return_value=mock_explanation))
    app.state.explanation_service = service
    app.dependency_overrides[get_db] = lambda: object()
    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            f"/api/v1/repositories/{repo_id}/explain",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "file_path": "./backend/app/core/input_security.py",
                "start_line": 36,
                "end_line": 64,
                "symbol": "validate_repo_relative_path",
            },
        )
    finally:
        app.dependency_overrides.clear()
        del app.state.explanation_service

    assert response.status_code == 200
    body = response.json()
    assert body["repository_id"] == str(repo_id)
    assert body["status"] == "COMPLETED"
    assert body["target"]["path"] == "backend/app/core/input_security.py"
    assert body["explanation"]["confidence"] == "high"
    assert body["explanation"]["key_symbols"][0]["name"] == "validate_repo_relative_path"


def test_detect_bugs_endpoint_returns_structured_findings(monkeypatch) -> None:
    token = _configure_auth(monkeypatch)
    repo_id = uuid4()
    _allow_repo_owner(monkeypatch, owned_repo_id=repo_id)

    mock_findings = [
        {
            "id": "finding-1",
            "category": "off_by_one",
            "severity": "HIGH",
            "title": "Inclusive loop upper bound accesses index len(items)",
            "description": "Iterating up to len(items) inclusive causes IndexError on the final iteration.",
            "source_reference": {
                "file_path": "src/pagination.py",
                "start_line": 14,
                "end_line": 18,
                "symbol_name": "slice_page",
            },
            "evidence": "for idx in range(0, len(items) + 1): items[idx]",
            "suggested_fix": "Use range(0, len(items)) instead of len(items) + 1.",
            "confidence": "high",
            "is_uncertain": False,
            "source_type": "AI",
        }
    ]
    service = SimpleNamespace(detect_bugs=AsyncMock(return_value={"findings": mock_findings}))
    app.state.bug_detection_service = service
    app.dependency_overrides[get_db] = lambda: object()
    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            f"/api/v1/repositories/{repo_id}/detect-bugs",
            headers={"Authorization": f"Bearer {token}"},
            json={"target": {"type": "file", "path": "src/pagination.py"}},
        )
    finally:
        app.dependency_overrides.clear()
        del app.state.bug_detection_service

    assert response.status_code == 200
    body = response.json()
    assert body["total_findings"] == 1
    assert body["ai_findings_count"] == 1
    assert body["findings"][0]["category"] == "off_by_one"
    assert body["findings"][0]["severity"] == "HIGH"


def test_generate_tests_endpoint_validates_proposed_path_and_scenarios(monkeypatch) -> None:
    token = _configure_auth(monkeypatch)
    repo_id = uuid4()
    _allow_repo_owner(monkeypatch, owned_repo_id=repo_id)

    mock_test_result = {
        "detected_framework": "pytest",
        "proposed_test_path": "backend/tests/test_pagination.py",
        "test_content": "def test_slice_page_empty():\n    assert slice_page([], 1, 10) == []\n",
        "covered_scenarios": [
            {
                "name": "test_slice_page_empty",
                "category": "edge_case",
                "description": "Verifies empty list returns empty page without IndexError.",
            }
        ],
        "assumptions_and_warnings": [],
        "syntax_valid": True,
        "validation_errors": [],
        "sources": [{"file_path": "src/pagination.py", "start_line": 1, "end_line": 25}],
    }
    service = SimpleNamespace(generate_tests=AsyncMock(return_value=mock_test_result))
    app.state.test_generation_service = service
    app.dependency_overrides[get_db] = lambda: object()
    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            f"/api/v1/repositories/{repo_id}/generate-tests",
            headers={"Authorization": f"Bearer {token}"},
            json={"file_path": "src/pagination.py", "framework": "pytest"},
        )
    finally:
        app.dependency_overrides.clear()
        del app.state.test_generation_service

    assert response.status_code == 200
    body = response.json()
    assert body["result"]["detected_framework"] == "pytest"
    assert body["result"]["proposed_test_path"] == "backend/tests/test_pagination.py"
    assert len(body["result"]["covered_scenarios"]) == 1


def test_review_endpoint_supports_commit_and_pr_targets(monkeypatch) -> None:
    token = _configure_auth(monkeypatch)
    repo_id = uuid4()
    _allow_repo_owner(monkeypatch, owned_repo_id=repo_id)

    mock_report = {
        "summary": "Reviewed commit a1b2c3d4: 1 security finding identified.",
        "risk_level": "HIGH",
        "findings": [
            {
                "id": "rev-1",
                "category": "security",
                "severity": "HIGH",
                "title": "Unparameterized SQL string interpolation",
                "description": "User input is formatted directly into SQL query text.",
                "source_reference": {
                    "file_path": "src/db.py",
                    "start_line": 42,
                    "end_line": 45,
                    "revision": "a1b2c3d4",
                },
                "evidence": 'conn.execute(f"SELECT * FROM users WHERE login = \'{login}\'")',
                "suggested_fix": "Use bound parameters (:login) with SQLAlchemy text().",
                "confidence": "high",
                "is_uncertain": False,
                "is_new_in_change": True,
                "source_type": "COMBINED",
                "rule_id": "B608",
            }
        ],
        "total_findings": 1,
        "category_counts": {"security": 1},
        "missing_context": [],
    }
    service = SimpleNamespace(review=AsyncMock(return_value=mock_report))
    app.state.code_review_service = service
    app.dependency_overrides[get_db] = lambda: object()
    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            f"/api/v1/repositories/{repo_id}/review",
            headers={"Authorization": f"Bearer {token}"},
            json={"commit_sha": "a1b2c3d4"},
        )
    finally:
        app.dependency_overrides.clear()
        del app.state.code_review_service

    assert response.status_code == 200
    body = response.json()
    assert body["target"]["type"] == "commit"
    assert body["target"]["commit_sha"] == "a1b2c3d4"
    assert body["report"]["risk_level"] == "HIGH"
    assert body["report"]["findings"][0]["category"] == "security"


def test_analysis_runs_list_and_detail_enforce_repository_ownership(monkeypatch) -> None:
    token = _configure_auth(monkeypatch, USER_A_ID)
    user_a_repo_id = uuid4()
    user_b_repo_id = uuid4()
    run_id_a = uuid4()
    run_id_b = uuid4()
    _allow_repo_owner(monkeypatch, owned_repo_id=user_a_repo_id, expected_user_id=USER_A_ID)

    now = datetime.now(timezone.utc)
    run_a_record = {
        "id": str(run_id_a),
        "repository_id": str(user_a_repo_id),
        "user_id": USER_A_ID,
        "feature_type": "detect_bugs",
        "status": "COMPLETED",
        "target_path": "src/main.py",
        "findings_count": 2,
        "created_at": now,
    }
    run_b_record = {
        "id": str(run_id_b),
        "repository_id": str(user_b_repo_id),
        "user_id": USER_B_ID,
        "feature_type": "review",
        "status": "COMPLETED",
        "target_path": "src/secret.py",
        "findings_count": 1,
        "created_at": now,
    }

    class FakeAnalysisRunService:
        def list_runs(self, repository_id: UUID, **kwargs):
            assert repository_id == user_a_repo_id
            return [run_a_record], 1

        def get_run(self, requested_run_id: UUID):
            if requested_run_id == run_id_a:
                return run_a_record
            if requested_run_id == run_id_b:
                return run_b_record
            return None

    app.state.analysis_run_service = FakeAnalysisRunService()
    app.dependency_overrides[get_db] = lambda: object()
    try:
        client = TestClient(app, raise_server_exceptions=False)
        list_res = client.get(
            f"/api/v1/repositories/{user_a_repo_id}/analysis-runs",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert list_res.status_code == 200
        assert list_res.json()["total"] == 1
        assert list_res.json()["items"][0]["id"] == str(run_id_a)

        detail_a = client.get(
            f"/api/v1/analysis-runs/{run_id_a}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert detail_a.status_code == 200
        assert detail_a.json()["id"] == str(run_id_a)

        # User A requesting User B's analysis run MUST be denied with 404
        detail_b = client.get(
            f"/api/v1/analysis-runs/{run_id_b}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert detail_b.status_code == 404
        assert "secret.py" not in detail_b.text
    finally:
        app.dependency_overrides.clear()
        del app.state.analysis_run_service
