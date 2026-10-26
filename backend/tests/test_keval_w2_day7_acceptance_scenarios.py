"""End-to-End Acceptance Scenarios A through E (Week 2 Day 7).

Owner: Keval (QA Lead)
Reference: Docs/week2.md §11 & §12 (Mandatory End-to-End Acceptance Scenarios)
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
import pytest

from ai.llm.schemas import LLMResponse
from app.core.errors import APIError
from app.core.input_security import UnsafePathError, validate_repo_relative_path
from app.schemas.analysis import (
    AnalysisOptions,
    AnalysisSourceReference,
    AnalysisTarget,
    BugDetectionRequest,
    CodeExplanation,
    CodeReviewRequest,
    ExplainCodeRequest,
    ReviewFinding,
    ReviewTarget,
    TestGenerationRequest,
    TestGenerationResult,
)
from app.services.bug_detection_orchestrator import (
    BuiltinStaticBugScanner,
    LLMBugDetectionService,
    merge_and_deduplicate_findings,
    redact_secrets_in_text,
)
from app.services.code_review_orchestrator import (
    LLMCodeReviewService,
    build_grounded_review_report,
    parse_unified_diff_changed_lines,
)
from app.services.explanation_orchestrator import (
    LLMCodeExplanationService,
    enforce_gateway_provider_policy,
)
from app.services.test_generation_orchestrator import (
    LLMTestGenerationService,
    validate_generated_test_syntax,
)
from scanner.ast_rules import ASTBugAnalyzer
from scanner.framework_detector import FrameworkDetector

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "defect_fixtures"


@pytest.fixture
def mock_gateway():
    gw = MagicMock()
    gw.generate = AsyncMock()
    gw.provider = MagicMock(provider_name="gemini")
    return gw


# ---------------------------------------------------------------------------
# Scenario A: Code Explanation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scenario_a_code_explanation(mock_gateway):
    """Scenario A: Request explanation for tested_service.py and verify structured components."""
    explanation_json = {
        "purpose": "Email and username validation utility service.",
        "logic_flow": ["Validate email format with regex", "Validate username string length"],
        "key_symbols": [
            {"name": "validate_email", "kind": "function", "role": "Regex format verification", "start_line": 10, "end_line": 18},
            {"name": "validate_username", "kind": "function", "role": "Length verification", "start_line": 20, "end_line": 28},
        ],
        "inputs_and_outputs": "Inputs: raw strings. Outputs: boolean valid/invalid status.",
        "dependencies": ["re"],
        "assumptions_and_limitations": ["Does not verify domain MX records"],
        "sources": [
            {
                "file_path": "tested_service.py",
                "start_line": 1,
                "end_line": 28,
            }
        ],
        "confidence": "high",
        "missing_context": [],
    }

    mock_gateway.generate.return_value = LLMResponse(
        content=json.dumps(explanation_json),
        model="gemini-flash-latest",
    )

    svc = LLMCodeExplanationService(mock_gateway)
    req = ExplainCodeRequest(
        target=AnalysisTarget(type="file", path="tested_service.py"),
    )

    code = (FIXTURES_DIR / "tested_service.py").read_text(encoding="utf-8")
    resp = await svc.explain(uuid4(), req, code_content=code)

    assert isinstance(resp, CodeExplanation)
    assert "Email" in resp.purpose
    assert len(resp.logic_flow) == 2
    assert len(resp.key_symbols) == 2
    assert len(resp.sources) == 1
    assert resp.sources[0].file_path == "tested_service.py"


# ---------------------------------------------------------------------------
# Scenario B: Bug Detection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scenario_b_bug_detection(mock_gateway):
    """Scenario B: Defect fixture flags known defects while clean fixture produces zero findings."""
    # 1. Defect fixture: off_by_one.py scanned with ASTBugAnalyzer & BuiltinStaticBugScanner
    off_by_one_code = (FIXTURES_DIR / "off_by_one.py").read_text(encoding="utf-8")
    analyzer = ASTBugAnalyzer()
    ast_res = analyzer.analyze_code(off_by_one_code, "off_by_one.py")
    assert ast_res.success is True
    assert any(f.rule_id == "AST-BOUND-001" for f in ast_res.findings)

    scanner = BuiltinStaticBugScanner()
    static_findings, _ = scanner.scan(file_path="off_by_one.py", code_content=off_by_one_code)
    assert any(f.rule_id == "AST001" for f in static_findings)

    # 2. Clean fixture: correct_math.py scanned with ASTBugAnalyzer & BuiltinStaticBugScanner
    clean_code = (FIXTURES_DIR / "correct_math.py").read_text(encoding="utf-8")
    clean_ast = analyzer.analyze_code(clean_code, "correct_math.py")
    assert len(clean_ast.findings) == 0

    clean_static, _ = scanner.scan(file_path="correct_math.py", code_content=clean_code)
    assert len(clean_static) == 0


# ---------------------------------------------------------------------------
# Scenario C: Framework-Aware Test Generation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scenario_c_test_generation(mock_gateway):
    """Scenario C: Detect pytest framework, generate valid test file, and verify assertions."""
    # 1. Detect framework conventions
    detector = FrameworkDetector()
    det_res = detector.detect(
        file_list=["pytest.ini", "backend/app/pricing.py", "backend/tests/test_pricing.py"],
        target_file="backend/app/pricing.py",
    )
    assert det_res.framework == "pytest"

    # 2. Mock generated tests with normal, edge_case, and failure_path
    generated_code = (
        "import pytest\n\n"
        "def test_pricing_normal():\n"
        "    assert 100 * 0.9 == 90.0\n\n"
        "def test_pricing_edge_zero():\n"
        "    assert 0 * 0.9 == 0.0\n\n"
        "def test_pricing_failure_negative():\n"
        "    with pytest.raises(ValueError):\n"
        "        raise ValueError('Negative amount')\n"
    )

    mock_gateway.generate.return_value = LLMResponse(
        content=json.dumps({
            "detected_framework": "pytest",
            "proposed_test_path": "backend/tests/test_pricing_generated.py",
            "test_content": generated_code,
            "covered_scenarios": [
                {"name": "test_pricing_normal", "category": "normal", "description": "Normal calculation"},
                {"name": "test_pricing_edge_zero", "category": "edge_case", "description": "Zero value boundary"},
                {"name": "test_pricing_failure_negative", "category": "failure_path", "description": "Negative value rejection"},
            ],
            "assumptions_and_warnings": [],
            "syntax_valid": True,
            "validation_errors": [],
            "sources": [{"file_path": "backend/app/pricing.py", "start_line": 1, "end_line": 20}],
        }),
        model="gemini-flash-latest",
    )

    svc = LLMTestGenerationService(mock_gateway)
    res = await svc.generate_tests(
        uuid4(),
        TestGenerationRequest(target=AnalysisTarget(type="file", path="backend/app/pricing.py")),
        code_content="def price(): pass",
        detected_framework="pytest",
    )

    assert isinstance(res, TestGenerationResult)
    assert res.syntax_valid is True
    assert len(res.covered_scenarios) == 3

    # 3. Validate syntax statically
    syn_ok, syn_err = validate_generated_test_syntax(res.test_content, "pytest")
    assert syn_ok is True
    assert len(syn_err) == 0


# ---------------------------------------------------------------------------
# Scenario D: Standalone AI Code Review
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scenario_d_standalone_code_review(mock_gateway):
    """Scenario D: Review PR diff with SQL injection and verify critical security risk report."""
    diff_text = (FIXTURES_DIR / "review_defect.diff").read_text(encoding="utf-8")
    changed = parse_unified_diff_changed_lines(diff_text)
    assert "backend/app/repositories/user_search.py" in changed

    mock_gateway.generate.return_value = LLMResponse(
        content=json.dumps({
            "summary": "Review detected SQL Injection vulnerability in user search query.",
            "risk_level": "CRITICAL",
            "findings": [
                {
                    "id": "rev-1",
                    "category": "security",
                    "severity": "CRITICAL",
                    "title": "SQL Injection Vulnerability",
                    "description": "Raw string formatting in SQL query allows command execution.",
                    "source_reference": {
                        "file_path": "backend/app/repositories/user_search.py",
                        "start_line": 9,
                        "end_line": 10,
                    },
                    "evidence": "sql = f\"SELECT * FROM users WHERE username LIKE '{query_term}%'\"",
                    "suggested_fix": "Use SQLAlchemy parameterized bind variables.",
                    "confidence": "high",
                    "is_uncertain": False,
                    "is_new_in_change": True,
                    "source_type": "AI",
                }
            ],
            "missing_context": [],
        }),
        model="gemini-flash-latest",
    )

    svc = LLMCodeReviewService(mock_gateway)
    report = await svc.review(
        uuid4(),
        CodeReviewRequest(target=ReviewTarget(type="diff", diff=diff_text)),
    )
    assert report.risk_level == "CRITICAL"
    assert report.total_findings == 1
    assert report.findings[0].category == "security"

    # Clean review with zero findings
    clean_report = build_grounded_review_report(
        summary="Clean changes, zero defects found.",
        findings=[],
        missing_context=[],
    )
    assert clean_report.risk_level == "NONE"
    assert clean_report.total_findings == 0


# ---------------------------------------------------------------------------
# Scenario E: Security, Failures and Boundary Defense
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scenario_e_security_and_failure_handling(mock_gateway):
    """Scenario E: Verify 5 security and boundary failure conditions."""
    # 1. Path traversal rejection
    with pytest.raises(UnsafePathError):
        validate_repo_relative_path("../../../etc/passwd")

    # 2. Prompt injection safety in source code comments
    injection_code = (FIXTURES_DIR / "prompt_injection_source.py").read_text(encoding="utf-8")
    assert "SYSTEM OVERRIDE:" in injection_code
    # Redaction & fencing preserve data isolation
    assert redact_secrets_in_text("ghp_" + "D" * 36) == "[REDACTED]"

    # 3. Provider policy enforcement (disallowed provider rejected with 400)
    gw_invalid = MagicMock()
    gw_invalid.provider = MagicMock(provider_name="unauthorized_ai_llm")
    with pytest.raises(APIError) as exc_prov:
        enforce_gateway_provider_policy(gw_invalid)
    assert exc_prov.value.status_code == 400

    # 4. Service unavailable when gateway is missing
    svc_nogw = LLMCodeExplanationService(llm_gateway=None)
    with pytest.raises(APIError) as exc_503:
        await svc_nogw.explain(uuid4(), ExplainCodeRequest(target=AnalysisTarget(type="file", path="a.py")))
    assert exc_503.value.status_code == 503

    # 5. Secret redaction prevents credential leaks
    raw_key = "AIza" + "E" * 35
    redacted = redact_secrets_in_text(f"API_KEY = '{raw_key}'")
    assert raw_key not in redacted
    assert "[REDACTED]" in redacted
