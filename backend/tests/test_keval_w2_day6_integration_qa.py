"""Acceptance and QA tests for Cross-Feature Integration and Security Hardening (Week 2 Day 6).

Owner: Keval (QA Lead)
Reference: Docs/week2.md §10 & §12 (Scenario E)
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
import pytest

from ai.schemas.prompt_builder import _fence
from app.core.errors import APIError
from app.schemas.analysis import (
    AnalysisOptions,
    AnalysisSourceReference,
    AnalysisTarget,
    BugDetectionRequest,
    CodeReviewRequest,
    ExplainCodeRequest,
    ReviewTarget,
    TestGenerationRequest,
)
from app.services.bug_detection_orchestrator import (
    LLMBugDetectionService,
    redact_secrets_in_text,
)
from app.services.code_review_orchestrator import LLMCodeReviewService
from app.services.explanation_orchestrator import (
    LLMCodeExplanationService,
    enforce_gateway_provider_policy,
)
from app.services.test_generation_orchestrator import LLMTestGenerationService

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "defect_fixtures"


def test_integration_qa_provider_policy_whitelist():
    """Verify provider whitelist permits Gemini and Groq while rejecting non-approved providers."""
    # Permitted: Gemini
    gw_gemini = MagicMock()
    gw_gemini.provider = MagicMock(provider_name="gemini")
    enforce_gateway_provider_policy(gw_gemini)  # Should not raise

    # Permitted: Groq
    gw_groq = MagicMock()
    gw_groq.provider = MagicMock(provider_name="groq")
    enforce_gateway_provider_policy(gw_groq)  # Should not raise

    # Disallowed: OpenAI
    gw_openai = MagicMock()
    gw_openai.provider = MagicMock(provider_name="openai")
    with pytest.raises(APIError) as exc_openai:
        enforce_gateway_provider_policy(gw_openai)
    assert exc_openai.value.status_code == 400

    # Disallowed: Anthropic
    gw_anthropic = MagicMock()
    gw_anthropic.provider = MagicMock(provider_name="anthropic")
    with pytest.raises(APIError) as exc_anthropic:
        enforce_gateway_provider_policy(gw_anthropic)
    assert exc_anthropic.value.status_code == 400


def test_integration_qa_prompt_injection_fencing():
    """Verify untrusted code containing adversarial instructions is enclosed in dynamic fences."""
    injection_code = (FIXTURES_DIR / "prompt_injection_source.py").read_text(encoding="utf-8")
    fenced = _fence(injection_code)

    # Fence must open with REPO_DATA marker
    assert "<<<REPO_DATA_" in fenced
    # Raw adversarial override comment is strictly trapped inside the fence
    assert "SYSTEM OVERRIDE:" in fenced
    assert ">>>" in fenced


def test_integration_qa_shared_target_and_source_reference_contracts():
    """Verify all four feature targets share the standardized source reference schema."""
    ref = AnalysisSourceReference(
        file_path="app/services/pricing.py",
        start_line=10,
        end_line=25,
        symbol_name="calculate_total",
    )
    assert ref.file_path == "app/services/pricing.py"
    assert ref.start_line == 10
    assert ref.end_line == 25

    # Check request models use consistent target structure
    explain_req = ExplainCodeRequest(target=AnalysisTarget(type="file", path="app/services/pricing.py"))
    bug_req = BugDetectionRequest(target=AnalysisTarget(type="file", path="app/services/pricing.py"))
    test_req = TestGenerationRequest(target=AnalysisTarget(type="file", path="app/services/pricing.py"))
    review_req = CodeReviewRequest(target=ReviewTarget(type="file", path="app/services/pricing.py"))

    assert explain_req.target.path == "app/services/pricing.py"
    assert bug_req.target.path == "app/services/pricing.py"
    assert test_req.target.path == "app/services/pricing.py"
    assert review_req.target.path == "app/services/pricing.py"


def test_integration_qa_secret_redaction_consistency():
    """Verify secrets are redacted identically across all intelligence text outputs."""
    raw_token = "ghp_" + "C" * 36
    snippet = f"Authorization: Bearer {raw_token}\napi_key = '{raw_token}'"
    redacted = redact_secrets_in_text(snippet)

    assert raw_token not in redacted
    assert "[REDACTED]" in redacted


@pytest.mark.asyncio
async def test_integration_qa_service_unavailable_without_gateway():
    """Verify all four services raise APIError(503) when LLM gateway is unconfigured."""
    repo_id = uuid4()

    # 1. Explanation service without gateway
    exp_svc = LLMCodeExplanationService(llm_gateway=None)
    with pytest.raises(APIError) as exc_exp:
        await exp_svc.explain(repo_id, ExplainCodeRequest(target=AnalysisTarget(type="file", path="a.py")))
    assert exc_exp.value.status_code == 503

    # 2. Bug detection service without gateway
    bug_svc = LLMBugDetectionService(llm_gateway=None)
    with pytest.raises(APIError) as exc_bug:
        await bug_svc.detect_bugs(
            repo_id,
            BugDetectionRequest(target=AnalysisTarget(type="file", path="a.py"), include_ai=True, include_static=False),
        )
    assert exc_bug.value.status_code == 503

    # 3. Test generation service without gateway
    test_svc = LLMTestGenerationService(llm_gateway=None)
    with pytest.raises(APIError) as exc_test:
        await test_svc.generate_tests(
            repo_id,
            TestGenerationRequest(target=AnalysisTarget(type="file", path="a.py")),
        )
    assert exc_test.value.status_code == 503

    # 4. Code review service without gateway
    rev_svc = LLMCodeReviewService(llm_gateway=None)
    with pytest.raises(APIError) as exc_rev:
        await rev_svc.review(
            repo_id,
            CodeReviewRequest(target=ReviewTarget(type="file", path="a.py")),
        )
    assert exc_rev.value.status_code == 503
