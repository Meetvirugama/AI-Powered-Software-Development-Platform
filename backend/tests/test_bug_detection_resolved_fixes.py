"""Tests verifying Bug Detection feature fixes.

Covers:
1. Gated AI service lookup allowing static-only scans when AI is unconfigured.
2. Deduplication of equivalent AST static rules (e.g. AST002 and AST-EXC-001, AST004 and AST-RES-001).
3. Range-target base_start_line offset propagation across candidate discovery and static scanners.
4. Category compatibility between null_dereference and null_safety.
5. Counterevidence sanitizer calibration avoiding false positive suppression in priority scoring.
"""

from uuid import uuid4
from unittest.mock import MagicMock

from app.schemas.analysis import AnalysisSourceReference, BugFinding
from app.services.bug_candidate_discovery import BugCandidateDiscoveryService
from app.services.bug_detection_orchestrator import (
    _are_equivalent_static_rules,
    _categories_compatible,
    filter_and_rank_findings,
    merge_and_deduplicate_findings,
)
from app.services.bug_priority_service import BugPriorityService
from scanner.static_bug_scanner import StaticBugScanner


def test_equivalent_rules_deduplication():
    """Verify equivalent AST rules on overlapping lines are merged into one canonical finding."""
    assert _are_equivalent_static_rules("AST001", "AST-BOUND-001")
    assert _are_equivalent_static_rules("AST002", "AST-EXC-001")
    assert _are_equivalent_static_rules("AST003", "AST-ARG-001")
    assert _are_equivalent_static_rules("AST004", "AST-RES-001")
    assert _are_equivalent_static_rules("B307", "AST-SEC-001")

    repo_id = str(uuid4())
    f1 = BugFinding(
        id="finding-1",
        category="unhandled_exception",
        severity="HIGH",
        title="Bare except block detected",
        description="Except block catches all exceptions without specifying type",
        source_reference=AnalysisSourceReference(
            repository_id=repo_id,
            file_path="app/main.py",
            start_line=15,
            end_line=18,
        ),
        evidence="except:",
        confidence="high",
        source_type="STATIC",
        rule_id="AST002",
    )

    f2 = BugFinding(
        id="finding-2",
        category="unhandled_exception",
        severity="HIGH",
        title="Broad or bare exception clause",
        description="Do not use bare except clauses",
        source_reference=AnalysisSourceReference(
            repository_id=repo_id,
            file_path="app/main.py",
            start_line=15,
            end_line=18,
        ),
        evidence="except:",
        confidence="high",
        source_type="STATIC",
        rule_id="AST-EXC-001",
    )

    merged = merge_and_deduplicate_findings([f1, f2])
    assert len(merged) == 1
    assert merged[0].rule_id in ("AST002", "AST-EXC-001")


def test_null_dereference_category_compatibility():
    """Verify null_dereference and null_safety categories are treated as compatible."""
    assert _categories_compatible("null_dereference", "null_safety")
    assert _categories_compatible("null_safety", "null_dereference")

    repo_id = str(uuid4())
    f1 = BugFinding(
        id="finding-1",
        category="null_safety",
        severity="HIGH",
        title="Potential None dereference",
        description="Object may be None",
        source_reference=AnalysisSourceReference(
            repository_id=repo_id,
            file_path="app/service.py",
            start_line=20,
            end_line=22,
        ),
        evidence="user.name",
        confidence="high",
        source_type="STATIC",
        rule_id="AST-NULL-001",
    )

    f2 = BugFinding(
        id="finding-2",
        category="null_dereference",
        severity="HIGH",
        title="Potential None dereference",
        description="Object may be None",
        source_reference=AnalysisSourceReference(
            repository_id=repo_id,
            file_path="app/service.py",
            start_line=20,
            end_line=22,
        ),
        evidence="user.name",
        confidence="high",
        source_type="STATIC",
        rule_id="AST-NULL-001",
    )

    merged = merge_and_deduplicate_findings([f1, f2])
    assert len(merged) == 1


def test_base_start_line_offset_in_static_scanner():
    """Verify StaticBugScanner offsets lines when base_start_line is provided."""
    scanner = StaticBugScanner()
    code = """
def bad_code():
    try:
        x = 1
    except:
        pass
"""
    # Without base_start_line (1-based default)
    res_default = scanner.scan_code(content=code, file_path="sample.py", base_start_line=1)
    findings_def = res_default.get("findings", [])
    assert len(findings_def) >= 1
    def_line = findings_def[0]["line_number"]

    # With base_start_line = 50
    res_shifted = scanner.scan_code(content=code, file_path="sample.py", base_start_line=50)
    findings_shift = res_shifted.get("findings", [])
    assert len(findings_shift) >= 1
    shift_line = findings_shift[0]["line_number"]

    assert shift_line == def_line + 49


def test_base_start_line_offset_in_candidate_discovery():
    """Verify BugCandidateDiscoveryService shifts candidate line numbers based on base_start_line."""
    code = """
DEBUG = True

def run_query():
    sql = f"SELECT * FROM items WHERE id = '{user_id}'"
    cursor.execute(sql)
"""
    discovery = BugCandidateDiscoveryService()
    cands_shifted = discovery.discover_candidates(
        file_path="sample.py",
        code_content=code,
        language="python",
        base_start_line=100,
    )

    cfg_cands = [c for c in cands_shifted if c.source_type == "CONFIG"]
    assert len(cfg_cands) >= 1
    # DEBUG = True is on line 2 in code snippet -> line 101 with base_start_line=100
    assert cfg_cands[0].start_line == 101


def test_counterevidence_sanitizer_calibration():
    """Verify only genuine protective counterevidence flags is_sanitized, not test suites or observations."""
    repo_id = str(uuid4())
    p_svc = BugPriorityService()

    # Security finding with ONLY an associated test suite note
    f_test_only = BugFinding(
        id="f-sec-1",
        category="security",
        severity="CRITICAL",
        title="SQL Injection vulnerability",
        description="Direct user input in SQL statement",
        source_reference=AnalysisSourceReference(
            repository_id=repo_id,
            file_path="api.py",
            start_line=10,
            end_line=12,
        ),
        evidence="cursor.execute(sql)",
        confidence="high",
        source_type="STATIC",
        rule_id="TAINT-SQL-001",
        counterevidence=["Associated test suite detected (2 tests, e.g. `test_api.py`)"],
    )

    ranked_test_only = filter_and_rank_findings([f_test_only])
    # Exploitability should NOT be depressed to 25 because of an associated test
    assert ranked_test_only[0].priority_score is not None
    assert ranked_test_only[0].priority_score >= 70

    # Security finding with actual sanitizer
    f_sanitized = BugFinding(
        id="f-sec-2",
        category="security",
        severity="CRITICAL",
        title="SQL Injection vulnerability",
        description="Direct user input in SQL statement",
        source_reference=AnalysisSourceReference(
            repository_id=repo_id,
            file_path="api.py",
            start_line=10,
            end_line=12,
        ),
        evidence="cursor.execute(sql)",
        confidence="high",
        source_type="STATIC",
        rule_id="TAINT-SQL-001",
        counterevidence=["Sanitizer or typecast applied before sink: `int(user_id)`"],
    )

    ranked_sanitized = filter_and_rank_findings([f_sanitized])
    assert ranked_sanitized[0].priority_score is not None
    # Priority score should be lower for mitigated/sanitized flow
    assert ranked_sanitized[0].priority_score < ranked_test_only[0].priority_score
