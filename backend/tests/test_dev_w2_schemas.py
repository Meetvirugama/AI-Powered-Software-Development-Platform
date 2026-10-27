"""Unit tests for Week 2 AI output schemas, validator, and service interfaces.

Owner: Dev — W2, Day 1 Deliverable (Schema Tests & Acceptance Criteria)
Reference: Docs/week2.md §5 (Day 1 Deliverables & Acceptance Criteria)

Acceptance Criteria:
- Invalid AI output is rejected or handled through a bounded recovery path.
- It must never silently become a successful empty result.
"""

from __future__ import annotations

import json
import pytest
from pydantic import ValidationError

from ai.interfaces import (
    AICodeReviewEngineProtocol,
    BugDetectionEngineProtocol,
    BugDetectionServiceProtocol,
    CodeExplanationServiceProtocol,
    CodeReviewServiceProtocol,
    TestGenerationServiceProtocol,
)
from ai.schemas import (
    AnalysisSourceReference,
    BugFinding,
    CodeExplanation,
    OutputValidator,
    ReviewFinding,
    ReviewReport,
    TestGenerationResult,
)
from ai.llm.schemas import LLMValidationError
from tests.fixtures.w2_schema_examples import (
    INVALID_BUG_FINDING_NEGATIVE_LINE,
    INVALID_CODE_EXPLANATION_BLANK_PURPOSE,
    INVALID_REVIEW_REPORT_BLANK_SUMMARY,
    INVALID_TEST_GENERATION_PATH_TRAVERSAL,
    VALID_BUG_FINDING_DICT,
    VALID_CODE_EXPLANATION_DICT,
    VALID_REVIEW_REPORT_DICT,
    VALID_TEST_GENERATION_RESULT_DICT,
)

# Prevent pytest from mistaking imported schema/protocol classes for test suites
TestGenerationServiceProtocol.__test__ = False  # type: ignore[attr-defined]
TestGenerationResult.__test__ = False  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# 1. CodeExplanation Tests
# ---------------------------------------------------------------------------

def test_code_explanation_valid() -> None:
    """Verifies that a comprehensive explanation payload parses and validates."""
    explanation = CodeExplanation.model_validate(VALID_CODE_EXPLANATION_DICT)
    assert "backoff" in explanation.purpose.lower()
    assert len(explanation.logic_flow) == 4
    assert len(explanation.key_symbols) == 2
    assert explanation.key_symbols[0].name == "calculate_backoff"
    assert explanation.confidence == "high"
    assert len(explanation.sources) == 1
    assert explanation.sources[0].start_line == 15


def test_code_explanation_rejects_blank_purpose() -> None:
    """Rejects whitespace-only or empty explanation purpose strings."""
    with pytest.raises(ValidationError) as exc_info:
        CodeExplanation.model_validate(INVALID_CODE_EXPLANATION_BLANK_PURPOSE)
    assert "purpose" in str(exc_info.value).lower()


def test_code_explanation_missing_evidence_representation() -> None:
    """Verifies explicit representation of missing context and unmapped lines."""
    minimal_dict = {
        "purpose": "A helper function with no external callers found.",
        "inputs_and_outputs": "Takes none, returns None.",
        "sources": [],
        "missing_context": ["caller_graph", "imported_module_types"],
    }
    model = CodeExplanation.model_validate(minimal_dict)
    assert model.sources == []
    assert len(model.missing_context) == 2
    assert "caller_graph" in model.missing_context


# ---------------------------------------------------------------------------
# 2. BugFinding Tests
# ---------------------------------------------------------------------------

def test_bug_finding_valid() -> None:
    """Verifies valid defect finding creation with category, severity, and evidence."""
    finding = BugFinding.model_validate(VALID_BUG_FINDING_DICT)
    assert finding.id == "bug-bf7102a"
    assert finding.category == "off_by_one"
    assert finding.severity == "HIGH"
    assert finding.source_reference.start_line == 42
    assert finding.suggested_fix is not None
    assert finding.is_uncertain is False


def test_bug_finding_rejects_negative_line() -> None:
    """Rejects invalid negative start lines in source references."""
    with pytest.raises(ValidationError) as exc_info:
        BugFinding.model_validate(INVALID_BUG_FINDING_NEGATIVE_LINE)
    assert "start_line" in str(exc_info.value)


def test_bug_finding_missing_line_evidence_explicit_none() -> None:
    """When exact line location is unavailable, start_line/end_line must be None, never fabricated."""
    unmapped_ref = AnalysisSourceReference(
        file_path="backend/app/main.py",
        start_line=None,
        end_line=None,
    )
    finding = BugFinding(
        id="bug-unmapped",
        category="resource_leak",
        severity="MEDIUM",
        title="Unclosed session in background loop",
        description="Session is opened but not explicitly closed in exception branch.",
        source_reference=unmapped_ref,
        evidence="Global loop references session",
        suggested_fix="Use context manager",
    )
    assert finding.source_reference.start_line is None
    assert finding.source_reference.end_line is None


# ---------------------------------------------------------------------------
# 3. TestGenerationResult Tests
# ---------------------------------------------------------------------------

def test_test_generation_valid() -> None:
    """Verifies test generation result with framework and scenario metadata."""
    result = TestGenerationResult.model_validate(VALID_TEST_GENERATION_RESULT_DICT)
    assert result.detected_framework == "pytest"
    assert result.proposed_test_path == "tests/test_retry.py"
    assert len(result.covered_scenarios) == 2
    assert result.covered_scenarios[0].category == "normal"
    assert result.covered_scenarios[1].category == "edge_case"
    assert result.syntax_valid is True


def test_test_generation_rejects_path_traversal() -> None:
    """Rejects unsafe test file proposals with directory traversal."""
    with pytest.raises(ValidationError) as exc_info:
        TestGenerationResult.model_validate(INVALID_TEST_GENERATION_PATH_TRAVERSAL)
    assert "traversal" in str(exc_info.value).lower() or "proposed_test_path" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 4. ReviewReport & ReviewFinding Tests
# ---------------------------------------------------------------------------

def test_review_report_valid() -> None:
    """Verifies code review report aggregation and category finding counts."""
    report = ReviewReport.model_validate(VALID_REVIEW_REPORT_DICT)
    assert report.risk_level == "HIGH"
    assert report.total_findings == 1
    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.category == "security"
    assert finding.severity == "CRITICAL"
    assert finding.is_new_in_change is True


def test_review_report_rejects_blank_summary() -> None:
    """Rejects whitespace-only review summaries."""
    with pytest.raises(ValidationError) as exc_info:
        ReviewReport.model_validate(INVALID_REVIEW_REPORT_BLANK_SUMMARY)
    assert "summary" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 5. OutputValidator & Acceptance Criteria Tests
# ---------------------------------------------------------------------------

def test_output_validator_strips_markdown_fences() -> None:
    """Ensures validator strips ```json markdown fences returned by models."""
    validator = OutputValidator()
    raw_markdown = f"```json\n{json.dumps(VALID_CODE_EXPLANATION_DICT)}\n```"
    instance, ok = validator.validate(raw_markdown, CodeExplanation)
    assert ok is True
    assert isinstance(instance, CodeExplanation)
    assert instance.confidence == "high"


def test_output_validator_never_returns_silent_empty_result() -> None:
    """Acceptance Criterion: Invalid output must NEVER silently become a successful empty result."""
    validator = OutputValidator()

    # Case 1: Malformed JSON
    instance, ok = validator.validate("this is not json at all", CodeExplanation)
    assert ok is False
    assert instance is None

    # Case 2: Incomplete schema (missing required fields)
    instance, ok = validator.validate('{"purpose": "Only purpose"}', CodeExplanation)
    assert ok is False
    assert instance is None

    # Case 3: validate_or_raise raises LLMValidationError
    with pytest.raises(LLMValidationError):
        validator.validate_or_raise("{}", CodeExplanation)


# ---------------------------------------------------------------------------
# 6. Service Protocols Runtime Checkable
# ---------------------------------------------------------------------------

def test_service_protocols_defined() -> None:
    """Verifies that all 4 service protocols exist and can be imported cleanly."""
    assert CodeExplanationServiceProtocol is not None
    assert BugDetectionServiceProtocol is not None
    assert BugDetectionEngineProtocol is not None
    assert TestGenerationServiceProtocol is not None
    assert CodeReviewServiceProtocol is not None
    assert AICodeReviewEngineProtocol is not None
