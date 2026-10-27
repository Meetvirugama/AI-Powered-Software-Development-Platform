"""Acceptance and QA tests for Standalone AI Code Review (Week 2 Day 5).

Owner: Keval (QA Lead)
Reference: Docs/week2.md §9 & §12 (Scenario D)
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
import pytest

from ai.llm.schemas import LLMResponse
from app.schemas.analysis import (
    AnalysisOptions,
    AnalysisSourceReference,
    CodeReviewRequest,
    ReviewCategory,
    ReviewFinding,
    ReviewReport,
    ReviewTarget,
)
from app.services.code_review_orchestrator import (
    LLMCodeReviewService,
    build_grounded_review_report,
    compute_category_counts,
    compute_review_risk_level,
    map_to_review_category,
    merge_and_rank_review_findings,
    parse_unified_diff_changed_lines,
    sanitize_review_finding,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "defect_fixtures"


@pytest.fixture
def mock_gateway():
    gw = MagicMock()
    gw.generate = AsyncMock()
    gw.provider = MagicMock(provider_name="gemini")
    return gw


def test_code_review_qa_diff_parser_and_source_mapping():
    """Verify unified diff parser identifies modified files and exact changed line sets."""
    diff_path = FIXTURES_DIR / "review_defect.diff"
    diff_text = diff_path.read_text(encoding="utf-8")

    changed_lines = parse_unified_diff_changed_lines(diff_text)
    assert len(changed_lines) == 1
    assert "backend/app/repositories/user_search.py" in changed_lines
    lines = changed_lines["backend/app/repositories/user_search.py"]
    assert len(lines) > 0


def test_code_review_qa_category_mapping():
    """Verify raw static/AST defect categories map cleanly to the 5 review dimensions."""
    assert map_to_review_category("sql_injection") == "security"
    assert map_to_review_category("hardcoded_secret") == "security"
    assert map_to_review_category("off_by_one") == "correctness"
    assert map_to_review_category("null_safety") == "reliability"
    assert map_to_review_category("slow_query") == "performance"
    assert map_to_review_category("resource_leak") == "reliability"
    assert map_to_review_category("unhandled_exception") == "reliability"
    assert map_to_review_category("dead_code") == "maintainability"


@pytest.mark.asyncio
async def test_code_review_qa_ai_reasoning_on_security_defect(mock_gateway):
    """Verify review service flags SQL injection defect in review_defect.diff with CRITICAL risk."""
    mock_payload = {
        "summary": "Critical SQL injection vulnerability detected in user search repository.",
        "risk_level": "CRITICAL",
        "findings": [
            {
                "id": "rev-ai-1",
                "category": "security",
                "severity": "CRITICAL",
                "title": "SQL Injection in User Search Query",
                "description": "User-supplied query_term is directly formatted into raw SQL via f-string.",
                "source_reference": {
                    "file_path": "backend/app/repositories/user_search.py",
                    "start_line": 9,
                    "end_line": 10,
                },
                "evidence": "sql = f\"SELECT * FROM users WHERE username LIKE '{query_term}%'\"",
                "suggested_fix": "Use parameterized queries with SQLAlchemy text(:param).",
                "confidence": "high",
                "is_uncertain": False,
                "is_new_in_change": True,
                "source_type": "AI",
            }
        ],
        "missing_context": [],
    }

    mock_gateway.generate.return_value = LLMResponse(
        content=json.dumps(mock_payload),
        model="gemini-flash-latest",
    )

    diff_text = (FIXTURES_DIR / "review_defect.diff").read_text(encoding="utf-8")
    svc = LLMCodeReviewService(mock_gateway)
    req = CodeReviewRequest(
        target=ReviewTarget(type="diff", diff=diff_text),
    )

    report = await svc.review(uuid4(), req)
    assert isinstance(report, ReviewReport)
    assert report.risk_level == "CRITICAL"
    assert report.total_findings == 1
    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.category == "security"
    assert finding.severity == "CRITICAL"
    assert finding.is_new_in_change is True
    assert "SQL Injection" in finding.title


def test_code_review_qa_zero_defect_clean_diff():
    """Verify that a clean code review with no defects produces risk_level NONE and 0 findings."""
    report = build_grounded_review_report(
        summary="All changes adhere to clean code practices and tests pass cleanly.",
        findings=[],
        missing_context=[],
    )
    assert report.risk_level == "NONE"
    assert report.total_findings == 0
    assert len(report.findings) == 0
    assert report.category_counts == {}


def test_code_review_qa_merging_and_deduplication():
    """Verify overlapping static and AI review findings merge into COMBINED."""
    f_static = ReviewFinding(
        id="rev-s-1",
        category="security",
        severity="HIGH",
        title="Insecure SQL Formatting",
        description="Static check flagged raw SQL string formatting.",
        source_reference=AnalysisSourceReference(file_path="search.py", start_line=10, end_line=12),
        evidence="f'SELECT ... {term}'",
        source_type="STATIC",
        rule_id="B608",
    )
    f_ai = ReviewFinding(
        id="rev-a-1",
        category="security",
        severity="CRITICAL",
        title="SQL Injection Vulnerability",
        description="AI model confirms direct injection possibility.",
        source_reference=AnalysisSourceReference(file_path="search.py", start_line=10, end_line=12),
        evidence="term interpolated into query",
        source_type="AI",
    )

    merged = merge_and_rank_review_findings([f_static, f_ai])
    assert len(merged) == 1
    assert merged[0].source_type == "COMBINED"
    assert merged[0].severity == "CRITICAL"


def test_code_review_qa_secret_redaction():
    """Verify credentials in review finding descriptions and evidence are redacted."""
    raw_token = "ghp_" + "B" * 36
    finding = ReviewFinding(
        id="rev-sec-1",
        category="security",
        severity="CRITICAL",
        title="Exposed GitHub Token",
        description=f"Found leaked token {raw_token} in pull request diff.",
        source_reference=AnalysisSourceReference(file_path="auth.py", start_line=15, end_line=15),
        evidence=f"AUTH_TOKEN = '{raw_token}'",
        suggested_fix=f"Revoke {raw_token} immediately.",
        source_type="AI",
    )

    sanitized = sanitize_review_finding(finding)
    assert raw_token not in sanitized.description
    assert raw_token not in sanitized.evidence
    assert raw_token not in sanitized.suggested_fix
    assert "[REDACTED]" in sanitized.description
