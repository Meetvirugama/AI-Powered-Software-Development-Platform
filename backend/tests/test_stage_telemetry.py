"""Tests for stage-level latency and token usage telemetry (Week 2 Section 12 Item 14, B-14)."""

import time
from uuid import UUID, uuid4

import pytest
from app.core.telemetry import StageExecutionTimer, StageMetrics
from app.schemas.analysis import (
    AnalysisTarget,
    BugDetectionResponse,
    CodeExplanation,
    CodeExplanationResponse,
    ReviewReport,
    ReviewReportResponse,
    ReviewTarget,
    TestGenerationResponse as AnalysisTestGenResponse,
    TestGenerationResult,
)


def test_stage_execution_timer_stages_and_tokens():
    """Verify StageExecutionTimer tracks stage latencies, token consumption, and cost estimates."""
    timer = StageExecutionTimer("explain_code", context_budget=12_000)

    with timer.measure("target_resolution"):
        time.sleep(0.005)

    with timer.measure("llm_inference"):
        time.sleep(0.01)

    timer.set_model_info(provider="gemini", model="gemini-2.0-flash")
    timer.record_tokens(prompt_tokens=1500, completion_tokens=300, context_utilized=1500)

    metrics = timer.finish()
    metrics_dict = metrics.to_dict()

    assert "target_resolution" in metrics_dict["stages_ms"]
    assert "llm_inference" in metrics_dict["stages_ms"]
    assert metrics_dict["stages_ms"]["target_resolution"] >= 4.0
    assert metrics_dict["stages_ms"]["llm_inference"] >= 8.0
    assert metrics_dict["total_latency_ms"] >= 12.0

    assert metrics_dict["prompt_tokens"] == 1500
    assert metrics_dict["completion_tokens"] == 300
    assert metrics_dict["total_tokens"] == 1800
    assert metrics_dict["context_budget_tokens"] == 12_000
    assert metrics_dict["context_utilized_tokens"] == 1500
    assert metrics_dict["provider"] == "gemini"
    assert metrics_dict["model"] == "gemini-2.0-flash"
    assert metrics_dict["estimated_cost_usd"] > 0.0


def test_stage_metrics_schema_serialization():
    """Verify StageMetrics serialization across all 4 analysis response schemas."""
    sample_metrics = {
        "stages_ms": {"llm_inference": 45.2, "static_analysis": 12.1},
        "prompt_tokens": 800,
        "completion_tokens": 200,
        "total_tokens": 1000,
        "context_budget_tokens": 10000,
        "context_utilized_tokens": 800,
        "provider": "gemini",
        "model": "gemini-2.0-flash",
        "estimated_cost_usd": 0.00012,
        "total_latency_ms": 57.3,
    }

    # 1. CodeExplanationResponse
    explain_resp = CodeExplanationResponse(
        run_id=str(uuid4()),
        repository_id=str(uuid4()),
        status="COMPLETED",
        target=AnalysisTarget(type="file", path="app/test.py"),
        explanation=CodeExplanation(
            purpose="Testing",
            logic_flow=["Step 1"],
            key_symbols=[],
            inputs_and_outputs="None",
            dependencies=[],
            assumptions_and_limitations=[],
            sources=[],
            confidence="high",
            missing_context=[],
        ),
        stage_metrics=sample_metrics,
    )
    dumped_explain = explain_resp.model_dump(mode="json")
    assert dumped_explain["stage_metrics"]["stages_ms"]["llm_inference"] == 45.2
    assert dumped_explain["stage_metrics"]["prompt_tokens"] == 800

    # 2. BugDetectionResponse
    bug_resp = BugDetectionResponse(
        run_id=str(uuid4()),
        repository_id=str(uuid4()),
        status="COMPLETED",
        target=AnalysisTarget(type="file", path="app/test.py"),
        findings=[],
        total_findings=0,
        static_findings_count=0,
        ai_findings_count=0,
        missing_context=[],
        stage_metrics=sample_metrics,
    )
    dumped_bug = bug_resp.model_dump(mode="json")
    assert dumped_bug["stage_metrics"]["total_latency_ms"] == 57.3

    # 3. TestGenerationResponse
    test_resp = AnalysisTestGenResponse(
        run_id=str(uuid4()),
        repository_id=str(uuid4()),
        status="COMPLETED",
        target=AnalysisTarget(type="file", path="app/test.py"),
        result=TestGenerationResult(
            detected_framework="pytest",
            proposed_test_path="tests/test_generated.py",
            test_content="def test_foo(): pass",
            covered_scenarios=[],
            assumptions_and_warnings=[],
            syntax_valid=True,
            validation_errors=[],
        ),
        stage_metrics=sample_metrics,
    )
    dumped_test = test_resp.model_dump(mode="json")
    assert dumped_test["stage_metrics"]["provider"] == "gemini"

    # 4. ReviewReportResponse
    review_resp = ReviewReportResponse(
        run_id=str(uuid4()),
        repository_id=str(uuid4()),
        status="COMPLETED",
        target=ReviewTarget(type="file", path="app/test.py"),
        report=ReviewReport(
            summary="Clean code",
            risk_level="LOW",
            findings=[],
            total_findings=0,
            category_counts={},
            missing_context=[],
        ),
        stage_metrics=sample_metrics,
    )
    dumped_review = review_resp.model_dump(mode="json")
    assert dumped_review["stage_metrics"]["context_budget_tokens"] == 10000


def test_review_endpoint_populates_stage_metrics(monkeypatch):
    """Verify that calling /review returns stage_metrics with stage latencies and token counts."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from fastapi.testclient import TestClient
    from app.core.config import get_settings
    from app.core.database import get_db
    from app.core.security import create_access_token
    from app.main import app

    class FakeRedis:
        def exists(self, _):
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

    fake_redis = FakeRedis()
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-12345")
    get_settings.cache_clear()
    monkeypatch.setattr("app.core.auth.get_redis", lambda: fake_redis)
    monkeypatch.setattr("app.core.redis.get_redis", lambda: fake_redis)

    user_id = "0e969876-16d2-4c9f-8fe1-a849f32fa605"
    token, _ = create_access_token(user_id)
    repo_id = uuid4()

    fake_repo = SimpleNamespace(
        id=repo_id,
        user_id=UUID(user_id),
        name="test-repo",
        default_branch="main",
    )
    monkeypatch.setattr("app.api.v1.analysis._owned_repository", lambda *args, **kwargs: fake_repo)

    mock_report = {
        "summary": "Reviewed commit a1b2c3d4: clean.",
        "risk_level": "LOW",
        "findings": [],
        "total_findings": 0,
        "category_counts": {},
        "missing_context": [],
    }
    app.state.code_review_service = SimpleNamespace(review=AsyncMock(return_value=mock_report))
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
        if hasattr(app.state, "code_review_service"):
            del app.state.code_review_service

    assert response.status_code == 200
    data = response.json()
    assert "stage_metrics" in data
    metrics = data["stage_metrics"]
    assert "target_resolution_and_diff_mapping" in metrics["stages_ms"]
    assert "llm_inference" in metrics["stages_ms"]
    assert "grounding_and_ranking" in metrics["stages_ms"]
    assert metrics["total_latency_ms"] > 0.0


def test_context_budget_defaults_and_database_pool_configuration():
    """Verify per-feature context budgets and database connection pool tuning (B-14)."""
    from app.core.config import get_settings
    from app.core.database import engine
    from app.schemas.analysis import (
        DEFAULT_BUGS_CONTEXT_TOKENS,
        DEFAULT_EXPLAIN_CONTEXT_TOKENS,
        DEFAULT_REVIEW_CONTEXT_TOKENS,
        DEFAULT_TESTS_CONTEXT_TOKENS,
        BugDetectionRequest,
        CodeReviewRequest,
        ExplainCodeRequest,
        TestGenerationRequest,
    )

    # 1. Per-feature context budget defaults
    assert DEFAULT_EXPLAIN_CONTEXT_TOKENS == 4000
    assert DEFAULT_BUGS_CONTEXT_TOKENS == 6000
    assert DEFAULT_TESTS_CONTEXT_TOKENS == 6000
    assert DEFAULT_REVIEW_CONTEXT_TOKENS == 8000

    explain_req = ExplainCodeRequest(target=AnalysisTarget(type="file", path="foo.py"))
    assert explain_req.options.max_context_tokens == 4000

    bug_req = BugDetectionRequest(target=AnalysisTarget(type="file", path="foo.py"))
    assert bug_req.options.max_context_tokens == 6000

    test_req = TestGenerationRequest(target=AnalysisTarget(type="file", path="foo.py"))
    assert test_req.options.max_context_tokens == 6000

    review_req = CodeReviewRequest(target=ReviewTarget(type="file", path="foo.py"))
    assert review_req.options.max_context_tokens == 8000

    # 2. Database connection pool settings
    settings = get_settings()
    assert settings.db_pool_size == 20
    assert settings.db_max_overflow == 10
    assert settings.db_pool_timeout == 30
    assert settings.db_pool_recycle == 1800

    # If connected to PostgreSQL/QueuePool, verify pool attributes
    if hasattr(engine.pool, "size"):
        assert engine.pool.size() == 20


