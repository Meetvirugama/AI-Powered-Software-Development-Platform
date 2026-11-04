"""Tests for Phase 4: AI Investigation, Counterevidence Validation & Priority Scoring.

Verifies:
1. BugPriorityService: Multi-factor formula calculation, score bounds, weights.
2. BugValidationService: Calibrated evidence levels (PROVEN, STRONG, SUSPECTED, NEEDS_CONTEXT),
   counterevidence guard detection and refutation.
3. BugFindingValidator: Grounding, line boundary clipping, secret redaction, hallucination filtering.
4. BugInvestigator: Two-pass investigation packet assembly and finding calibration.
"""

from unittest.mock import AsyncMock

import pytest

from ai.context.builder import ContextStatus, IntelligenceContext, TargetSnippet
from ai.services.bug_finding_validator import BugFindingValidator
from ai.services.bug_investigator import BugInvestigator
from app.schemas.analysis import AnalysisOptions, AnalysisSourceReference, AnalysisTarget, BugDetectionRequest, BugFinding
from app.services.bug_candidate_discovery import BugCandidate
from app.services.bug_graph_context_service import BugGraphSlice
from app.services.bug_priority_service import BugPriorityService
from app.services.bug_validation_service import BugValidationService


def test_priority_service_formula_calculation():
    """Verify BugPriorityService computes formula P = 0.35S + 0.25R + 0.20E + 0.10B + 0.10C."""
    service = BugPriorityService()

    # Critical security defect with high reachability and exploitability
    crit = service.calculate_priority(
        severity="CRITICAL",
        evidence_level="STRONG",
        has_callers=True,
        is_security=True,
        is_sanitized=False,
        caller_count=6,
    )
    assert 80 <= crit.priority_score <= 100
    assert crit.severity_score == 100.0
    assert crit.exploitability_score == 90.0

    # Low severity cosmetic issue
    low = service.calculate_priority(
        severity="LOW",
        evidence_level="SUSPECTED",
        has_callers=False,
        is_security=False,
        is_sanitized=False,
        caller_count=0,
    )
    assert low.priority_score < 50
    assert low.severity_score == 25.0


def test_priority_service_sanitizer_lowers_exploitability():
    """Verify that sanitized vulnerabilities receive lower exploitability and priority."""
    service = BugPriorityService()

    unsanitized = service.calculate_priority(
        severity="HIGH",
        is_security=True,
        is_sanitized=False,
        caller_count=3,
    )

    sanitized = service.calculate_priority(
        severity="HIGH",
        is_security=True,
        is_sanitized=True,
        caller_count=3,
    )

    assert unsanitized.exploitability_score > sanitized.exploitability_score
    assert unsanitized.priority_score > sanitized.priority_score


def test_validation_service_evidence_levels():
    """Verify BugValidationService assigns PROVEN, STRONG, SUSPECTED, and NEEDS_CONTEXT."""
    service = BugValidationService()

    # 1. Deterministic static rule -> PROVEN
    res_static = service.validate_candidate(
        title="Syntax error",
        category="syntax_error",
        evidence="invalid syntax at line 10",
        source_type="STATIC",
    )
    assert res_static.evidence_level == "PROVEN"
    assert not res_static.is_refuted

    # 2. Taint flow with multi-hop trace -> STRONG
    res_taint = service.validate_candidate(
        title="SQL injection",
        category="security",
        evidence="Untrusted query param reaches execute()",
        source_type="TAINT",
        has_dependency_trace=True,
    )
    assert res_taint.evidence_level == "STRONG"

    # 3. AI suspicion with missing context -> NEEDS_CONTEXT
    res_missing = service.validate_candidate(
        title="Possible missing import",
        category="logic_error",
        evidence="Unresolved symbol foo",
        source_type="AI",
        missing_context=["external_pkg.py"],
    )
    assert res_missing.evidence_level == "NEEDS_CONTEXT"

    # 4. Null check with defensive guard -> Refuted
    res_guarded = service.validate_candidate(
        title="Null pointer dereference on user",
        category="null_safety",
        evidence="user.name accessed",
        source_type="AI",
        guards=["if user is None: return"],
    )
    assert res_guarded.is_refuted is True
    assert len(res_guarded.counterevidence) >= 1
    assert "Defensive guard detected" in res_guarded.counterevidence[0]


def test_finding_validator_grounding_and_secret_redaction():
    """Verify BugFindingValidator grounds paths and redacts sensitive credentials."""
    validator = BugFindingValidator()

    raw_finding = BugFinding(
        id="finding-test-1",
        category="security",
        severity="HIGH",
        title="Found exposed token",
        description="Private key AKIA1234567890EXAMPLE in target",
        evidence="client_secret = 'ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456'",
        source_reference=AnalysisSourceReference(
            file_path="relative/path/users.py",
            start_line=200,
            end_line=205,
        ),
    )

    validated = validator.validate_and_sanitize(
        raw_finding,
        target_file_path="src/users.py",
        total_lines=150,
        known_files=["src/users.py", "src/auth.py"],
    )

    assert validated is not None
    # Path grounded to known target
    assert validated.source_reference.file_path == "src/users.py"
    # End line bounded by total_lines
    assert validated.source_reference.end_line <= 150
    # Secret redacted
    assert "ghp_" not in validated.evidence
    assert "[REDACTED" in validated.evidence or "***" in validated.evidence


@pytest.mark.asyncio
async def test_bug_investigator_packet_and_calibration():
    """Verify BugInvestigator builds investigation packet and calibrates findings."""
    investigator = BugInvestigator()

    candidate = BugCandidate(
        candidate_id="cand-001",
        rule_id="TAINT-SQL-001",
        file_path="app/users.py",
        start_line=15,
        end_line=15,
        category="security",
        severity="HIGH",
        evidence="Untrusted query param reaches database execute",
        source_type="TAINT",
    )

    prog_slice = BugGraphSlice(
        target_symbol_id=None,
        target_symbol_name="search_users",
        target_file_path="app/users.py",
        dependency_trace=["routes/user.py:10", "app/users.py:15"],
    )

    packet = investigator.build_investigation_packet(
        candidate=candidate,
        target_code="cursor.execute(sql)",
        target_file_path="app/users.py",
        start_line=15,
        end_line=15,
        program_slice=prog_slice,
        guards=["if not sql: return"],
        rules=["Use parameterized queries"],
    )

    assert packet.target_file_path == "app/users.py"
    assert len(packet.dependency_trace) == 2
    assert len(packet.counterevidence_points) == 1

    req = BugDetectionRequest(
        target=AnalysisTarget(path="app/users.py", start_line=15, end_line=15),
        options=AnalysisOptions(max_context_tokens=4000),
        include_ai=False,
    )
    context = IntelligenceContext(
        target=TargetSnippet(file_path="app/users.py", content="cursor.execute(sql)", start_line=15, end_line=15),
        status=ContextStatus.COMPLETE,
        total_tokens=100,
    )

    calibrated = await investigator.investigate_and_verify(
        request=req,
        context=context,
        program_slice=prog_slice,
        candidates=[candidate],
    )

    assert len(calibrated) == 1
    finding = calibrated[0]
    assert finding.priority_score is not None
    assert finding.priority_score > 60
    assert finding.evidence_level in ("STRONG", "PROVEN")
    assert len(finding.dependency_trace) == 2
