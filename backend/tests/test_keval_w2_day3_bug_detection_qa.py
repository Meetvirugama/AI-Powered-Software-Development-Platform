"""Acceptance and QA tests for Dedicated Bug Detection (Week 2 Day 3).

Owner: Keval (QA Lead)
Reference: Docs/week2.md §7 & §12 (Scenario B)
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
    AnalysisTarget,
    BugDetectionRequest,
    BugFinding,
)
from app.services.bug_detection_orchestrator import (
    BuiltinStaticBugScanner,
    LLMBugDetectionService,
    filter_and_rank_findings,
    merge_and_deduplicate_findings,
    redact_secrets_in_text,
    sanitize_finding_secrets,
)
from scanner.ast_rules import ASTBugAnalyzer

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "defect_fixtures"


@pytest.fixture
def mock_gateway():
    gw = MagicMock()
    gw.generate = AsyncMock()
    gw.provider = MagicMock(provider_name="gemini")
    return gw


def test_ast_bug_analyzer_detects_known_defects():
    """Verify that ASTBugAnalyzer flags structural defect rules on the defect fixtures."""
    analyzer = ASTBugAnalyzer()

    # Analyze off_by_one.py
    off_by_one_path = FIXTURES_DIR / "off_by_one.py"
    off_by_one_code = off_by_one_path.read_text(encoding="utf-8")
    result = analyzer.analyze_code(off_by_one_code, str(off_by_one_path))
    assert result.success is True
    assert len(result.findings) >= 1
    rule_ids = [f.rule_id for f in result.findings]
    assert "AST-BOUND-001" in rule_ids

    # Analyze correct_math.py - baseline clean module produces 0 findings
    correct_code = (FIXTURES_DIR / "correct_math.py").read_text(encoding="utf-8")
    clean_result = analyzer.analyze_code(correct_code, "correct_math.py")
    assert clean_result.success is True
    assert len(clean_result.findings) == 0


def test_builtin_static_scanner_detects_loop_bounds():
    """Verify BuiltinStaticBugScanner flags loop bounds AST001 on off_by_one.py."""
    scanner = BuiltinStaticBugScanner()
    off_by_one_code = (FIXTURES_DIR / "off_by_one.py").read_text(encoding="utf-8")
    findings, warnings = scanner.scan(file_path="off_by_one.py", code_content=off_by_one_code)

    assert len(findings) >= 1
    bound_findings = [f for f in findings if f.rule_id == "AST001"]
    assert len(bound_findings) >= 1
    assert bound_findings[0].severity == "HIGH"
    assert bound_findings[0].source_type == "STATIC"


@pytest.mark.asyncio
async def test_bug_detection_qa_ai_reasoning_and_sources(mock_gateway):
    """Verify bug detection orchestrates findings with accurate category, severity, and line numbers."""
    finding_dict = {
        "id": "finding-1",
        "category": "off_by_one",
        "severity": "HIGH",
        "title": "Off-by-one boundary index access",
        "description": "Loop iterates up to len(items) + 1, causing an IndexError at runtime.",
        "source_reference": {
            "file_path": "off_by_one.py",
            "start_line": 18,
            "end_line": 19,
        },
        "evidence": "for i in range(0, min(n + 1, len(items) + 1)):",
        "suggested_fix": "Change range upper bound to len(items).",
        "rule_id": "OFF_BY_ONE_LOOP",
        "source_type": "AI",
        "confidence": "high",
    }

    mock_gateway.generate.return_value = LLMResponse(
        content=json.dumps({"findings": [finding_dict], "missing_context": []}),
        model="gemini-flash-latest",
    )

    svc = LLMBugDetectionService(mock_gateway)
    req = BugDetectionRequest(
        target=AnalysisTarget(type="file", path="off_by_one.py"),
        include_ai=True,
        include_static=False,
    )

    result = await svc.detect_bugs(uuid4(), req, code_content="fake code")
    assert "findings" in result
    assert len(result["findings"]) == 1
    f = result["findings"][0]
    assert f.severity == "HIGH"
    assert f.source_reference.start_line == 18
    assert f.category == "off_by_one"


def test_bug_detection_qa_merging_and_deduplication():
    """Verify that overlapping static and AI findings merge into COMBINED and rank by severity."""
    static_finding = BugFinding(
        id="f-static-1",
        category="off_by_one",
        severity="HIGH",
        title="Loop bound overflow",
        description="Static AST check detected loop bound exceeding collection length.",
        source_reference=AnalysisSourceReference(file_path="off_by_one.py", start_line=18, end_line=19),
        evidence="range(0, len(items) + 1)",
        suggested_fix="Fix upper bound",
        source_type="STATIC",
        rule_id="AST001",
        confidence="high",
    )
    ai_finding = BugFinding(
        id="f-ai-1",
        category="off_by_one",
        severity="MEDIUM",
        title="IndexError off-by-one risk",
        description="AI model identified index out of bounds during slice indexing.",
        source_reference=AnalysisSourceReference(file_path="off_by_one.py", start_line=18, end_line=19),
        evidence="items[i] accessed out of bounds",
        suggested_fix="Ensure i < len(items)",
        source_type="AI",
        confidence="medium",
    )
    low_finding = BugFinding(
        id="f-info-1",
        category="style",
        severity="INFO",
        title="Variable naming convention",
        description="Consider using more descriptive variable name.",
        source_reference=AnalysisSourceReference(file_path="off_by_one.py", start_line=10, end_line=10),
        evidence="n: int",
        source_type="STATIC",
        confidence="low",
    )

    # Merging overlapping findings
    merged = merge_and_deduplicate_findings([static_finding, ai_finding, low_finding])
    assert len(merged) == 2  # static + ai merged into 1, plus low_finding

    combined = [f for f in merged if f.source_type == "COMBINED"]
    assert len(combined) == 1
    assert combined[0].rule_id == "AST001"
    assert combined[0].severity == "HIGH"

    # Filter and rank by severity
    filtered = filter_and_rank_findings(merged, min_severity="HIGH")
    assert len(filtered) == 1
    assert filtered[0].severity == "HIGH"


def test_bug_detection_secret_redaction():
    """Verify secret literals are redacted in findings and text before presentation."""
    raw_token = "ghp_" + "A" * 36
    raw_secret_snippet = f"api_key = '{raw_token}'"
    redacted = redact_secrets_in_text(raw_secret_snippet)
    assert raw_token not in redacted
    assert "[REDACTED]" in redacted

    finding = BugFinding(
        id="f-sec-1",
        category="security",
        severity="CRITICAL",
        title="Hardcoded API secret found",
        description=f"Detected raw credential {raw_token} in configuration.",
        source_reference=AnalysisSourceReference(file_path="config.py", start_line=5, end_line=5),
        evidence=f"Token: {raw_token}",
        suggested_fix=f"Move {raw_token} to environment variables",
        source_type="STATIC",
        rule_id="SEC001",
    )
    sanitized = sanitize_finding_secrets(finding)
    assert raw_token not in sanitized.description
    assert raw_token not in sanitized.evidence
    assert raw_token not in sanitized.suggested_fix
    assert "[REDACTED]" in sanitized.description
