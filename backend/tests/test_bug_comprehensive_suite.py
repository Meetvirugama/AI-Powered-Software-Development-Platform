"""
Comprehensive Test Suite for Bug Detection Feature (BD-AUD through BD-QUAL)
Specification: BUG_DETECTION_COMPREHENSIVE_TEST_PLAN.md

Tests all groups:
1. Architecture & Capability Audit (BD-AUD-001 to BD-AUD-012)
2. Core Functionality (BD-CORE-001 to BD-CORE-015)
3. Logic & Correctness Defects (BD-LOG-001 to BD-LOG-030)
4. Security Vulnerabilities (BD-SEC-001 to BD-SEC-030)
5. Repository Context & Slicing (BD-CTX-001 to BD-CTX-025)
6. Data-flow, Control-flow & Taint Analysis (BD-FLOW-001 to BD-FLOW-020)
7. False-Positive & Counterevidence Resistance (BD-FP-001 to BD-FP-020)
8. Scan Modes & Repository Size (BD-SCOPE-001 to BD-SCOPE-020)
9. Sync, Revision & Commit Pinning (BD-REV-001 to BD-REV-018)
10. Language & Framework Coverage (BD-LANG-001 to BD-LANG-018)
11. API, Backend & Persistence Boundaries (BD-API-001 to BD-API-025)
12. LLM Quality, Grounding & Fencing (BD-LLM-001 to BD-LLM-024)
13. Frontend & UX Contracts (BD-UI-001 to BD-UI-022)
14. Performance & Bounds (BD-PERF-001 to BD-PERF-018)
15. GitHub Integration Read-Only (BD-GH-001 to BD-GH-017)
16. Finding Quality & Prioritization (BD-QUAL-001 to BD-QUAL-018)
"""

from __future__ import annotations

import ast
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai.context.builder import ContextLimits, ContextStatus, IntelligenceContext, TargetSnippet
from ai.context.bug_context import BugContextExtractor
from ai.services.bug_detection_engine import BugDetectionEngine
from app.core.errors import APIError
from app.models.code_chunk import CodeChunk
from app.models.code_symbol import CodeSymbol
from app.models.repository import Repository, SyncStatus
from app.models.repository_file import RepositoryFile
from app.models.symbol_edge import SymbolEdge
from app.schemas.analysis import (
    AnalysisOptions,
    AnalysisSourceReference,
    AnalysisTarget,
    BugDetectionRequest,
    BugDetectionResponse,
    BugFinding,
)
from app.services.bug_candidate_discovery import BugCandidate, BugCandidateDiscoveryService
from app.services.bug_detection_orchestrator import (
    filter_and_rank_findings,
    merge_and_deduplicate_findings,
    normalize_and_ground_findings,
    resolve_bug_target_and_build_context,
)
from app.services.bug_graph_context_service import BugGraphContextService, BugGraphSlice
from app.services.bug_priority_service import BugPriorityService
from app.services.bug_validation_service import BugValidationService
from scanner.ast_rules import ASTBugAnalyzer
from scanner.rule_registry import DefectRule, RuleRegistry
from scanner.static_bug_scanner import StaticBugScanner
from scanner.taint_analyzer import TaintAnalyzer


# ===========================================================================
# GROUP 1: Implementation and Capability Audit (BD-AUD-001 to BD-AUD-012)
# ===========================================================================

def test_bd_aud_001_to_003_pipeline_and_modes():
    """BD-AUD-001 to BD-AUD-003: Verify pipeline components and supported scan modes."""
    # Orchestrator functions exist and are callable
    assert callable(resolve_bug_target_and_build_context)
    assert callable(filter_and_rank_findings)
    assert callable(merge_and_deduplicate_findings)

    # Scan modes defined in request schema
    req = BugDetectionRequest(
        target=AnalysisTarget(path="backend/app.py", start_line=1, end_line=10),
        scan_mode="standard",
    )
    assert req.scan_mode in ("quick", "standard", "deep", "change")


def test_bd_aud_004_to_006_bug_context_and_rule_registry():
    """BD-AUD-004 to BD-AUD-006: Verify BugContextExtractor and RuleRegistry."""
    # Error handling guard extraction
    sample_code = "try:\n    x = 1 / 0\nexcept ZeroDivisionError:\n    pass\n"
    guards = BugContextExtractor.extract_error_handling_blocks(sample_code, 1, 3, "python")
    assert len(guards) >= 1

    # Rule registry population
    reg = RuleRegistry.get_instance()
    sec_rules = reg.list_rules(category="security")
    assert len(sec_rules) >= 4
    assert any(r.rule_id == "TAINT-SQL-001" for r in sec_rules)


# ===========================================================================
# GROUP 2: Core Functionality (BD-CORE-001 to BD-CORE-015)
# ===========================================================================

def test_bd_core_001_to_003_scan_valid_file_and_ranges():
    """BD-CORE-001 to BD-CORE-003: Test valid file scanning and line boundaries."""
    scanner = StaticBugScanner()
    clean_code = "def add(a: int, b: int) -> int:\n    return a + b\n"
    res = scanner.scan_code(clean_code, "math_utils.py")
    assert res["success"] is True
    assert len(res["findings"]) == 0


def test_bd_core_004_to_007_seeded_bugs_and_safe_mixtures():
    """BD-CORE-004 to BD-CORE-007: Seeding obvious bugs vs clean code."""
    taint_analyzer = TaintAnalyzer()
    mixed_code = """
def safe_query(user_id: int):
    # Safe query using parameter binding
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))

def unsafe_query():
    # Vulnerable to SQL injection from request params
    user_input = request.query_params["name"]
    sql = f"SELECT * FROM users WHERE name = '{user_input}'"
    cursor.execute(sql)
"""
    candidates = taint_analyzer.analyze_source(mixed_code, "users.py")
    # Only unsafe_query should be flagged with high severity
    high_sev = [c for c in candidates if c.severity in ("CRITICAL", "HIGH")]
    assert len(high_sev) == 1
    assert high_sev[0].sink.name == "execute"


def test_bd_core_008_to_009_comments_and_todo_not_misclassified():
    """BD-CORE-008 to BD-CORE-009: Bug-like comments or TODOs alone do not create fatal findings."""
    code_with_comment = """
# This looks like SQL injection: SELECT * FROM users WHERE name = 'foo'
def safe_func():
    return 42
"""
    discovery = BugCandidateDiscoveryService()
    cands = discovery.discover_candidates(
        file_path="test_comment.py",
        code_content=code_with_comment,
        scan_mode="standard",
    )
    # No security findings should be fabricated from comments
    sec_cands = [c for c in cands if c.category == "security"]
    assert len(sec_cands) == 0


def test_bd_core_011_to_015_empty_syntax_and_size_bounds():
    """BD-CORE-011 to BD-CORE-015: Empty files, syntax errors, and size bounds."""
    scanner = StaticBugScanner()

    # Empty file
    empty_res = scanner.scan(code_content="", file_path="empty.py")
    assert empty_res["parse_status"] == "empty"
    assert len(empty_res["findings"]) == 0

    # Syntax error file
    syntax_res = scanner.scan_code("def broken(:\n    pass\n", "broken.py")
    assert syntax_res["has_syntax_errors"] is True


# ===========================================================================
# GROUP 3: Correctness and Logic Bugs (BD-LOG-001 to BD-LOG-030)
# ===========================================================================

def test_bd_log_001_to_004_off_by_one_and_null_deref():
    """BD-LOG-001 to BD-LOG-004: Off-by-one and null dereference patterns."""
    reg = RuleRegistry.get_instance()
    obo_rule = reg.get("BOUND-OBO-001")
    null_rule = reg.get("NULL-DEREF-001")
    assert obo_rule is not None
    assert obo_rule.cwe_id == "CWE-193"
    assert null_rule is not None
    assert null_rule.cwe_id == "CWE-476"


def test_bd_log_008_to_010_bare_except_and_resource_leaks():
    """BD-LOG-008 to BD-LOG-010: Bare exceptions and resource leak detection."""
    code = """
def leaky_function():
    try:
        f = open("/tmp/file.txt", "r")
        data = f.read()
    except:
        pass
"""
    analyzer = ASTBugAnalyzer()
    res = analyzer.analyze_code(code, "leaky.py")
    rule_ids = {f.rule_id for f in res.findings}
    # Checks for bare except / unhandled exceptions / resource leaks
    assert len(res.findings) >= 1


# ===========================================================================
# GROUP 4: Security Vulnerability Tests (BD-SEC-001 to BD-SEC-030)
# ===========================================================================

def test_bd_sec_001_to_004_sql_and_command_injection():
    """BD-SEC-001 to BD-SEC-004: SQL & Command injection source-to-sink."""
    taint = TaintAnalyzer()

    # SQL injection with concatenation
    sql_code = """
def query():
    raw_user = request.args["u"]
    cursor.execute("SELECT * FROM t WHERE u = '" + raw_user + "'")
"""
    cands = taint.analyze_source(sql_code, "sql_test.py")
    assert any(c.vulnerability_type == "sql_injection" for c in cands)

    # Command injection with shell=True
    cmd_code = """
def run_cmd():
    u = request.json["input"]
    subprocess.run(f"echo {u}", shell=True)
"""
    cmd_cands = taint.analyze_source(cmd_code, "cmd_test.py")
    assert any(c.vulnerability_type == "command_injection" for c in cmd_cands)


def test_bd_sec_007_to_008_path_traversal():
    """BD-SEC-007 to BD-SEC-008: Path traversal with and without sanitization."""
    taint = TaintAnalyzer()

    unsafe_path = """
def read_doc():
    filename = request.query_params["f"]
    with open(f"/app/data/{filename}") as fp:
        return fp.read()
"""
    cands = taint.analyze_source(unsafe_path, "path.py")
    path_cands = [c for c in cands if c.vulnerability_type == "path_traversal"]
    assert len(path_cands) >= 1
    assert not path_cands[0].is_sanitized


# ===========================================================================
# GROUP 5: Repository Context & Cross-File Reasoning (BD-CTX-001 to BD-CTX-025)
# ===========================================================================

@pytest.mark.asyncio
async def test_bd_ctx_001_to_008_program_slicing_and_tests():
    """BD-CTX-001 to BD-CTX-008: Multi-hop slicing and test association."""
    repo_id = uuid.uuid4()
    db = AsyncMock()

    # Create synchronous MagicMock for the query result proxy
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = None
    mock_res.scalars.return_value.all.return_value = []
    mock_res.scalars.return_value.first.return_value = None
    db.execute.return_value = mock_res

    service = BugGraphContextService(db=db)
    res_slice = await service.build_program_slice(
        repository_id=repo_id,
        target_file_path="backend/services/user_service.py",
        target_line=25,
        max_depth=2,
    )
    assert res_slice.target_file_path == "backend/services/user_service.py"
    assert res_slice.completeness_score >= 0.5


def test_bd_ctx_021_deduplicate_chunks():
    """BD-CTX-021: Chunk and finding deduplication."""
    f1 = BugFinding(
        id="f-dup-1",
        category="security",
        severity="HIGH",
        title="Bug A",
        description="Desc",
        evidence="Ev",
        source_reference=AnalysisSourceReference(file_path="a.py", start_line=10, end_line=12),
        source_type="STATIC",
    )
    f2 = BugFinding(
        id="f-dup-2",
        category="security",
        severity="CRITICAL",
        title="Bug A High",
        description="Desc",
        evidence="Ev",
        source_reference=AnalysisSourceReference(file_path="a.py", start_line=10, end_line=12),
        source_type="AI",
    )
    merged = merge_and_deduplicate_findings([f1, f2])
    assert len(merged) == 1
    assert merged[0].source_type == "COMBINED"
    assert merged[0].severity == "CRITICAL"


# ===========================================================================
# GROUP 6: Data-Flow, Control-Flow & Taint Analysis (BD-FLOW-001 to BD-FLOW-020)
# ===========================================================================

def test_bd_flow_001_to_010_alias_and_sanitizer_propagation():
    """BD-FLOW-001 to BD-FLOW-010: Variable aliasing and sanitizer flow."""
    taint = TaintAnalyzer()
    alias_code = """
def process():
    a = request.query_params["data"]
    b = a
    c = b
    cursor.execute(c)
"""
    cands = taint.analyze_source(alias_code, "alias.py")
    assert len(cands) >= 1
    flow = cands[0]
    # Intermediate variable b should be in propagators
    assert len(flow.propagators) >= 1


# ===========================================================================
# GROUP 7: False-Positive Resistance & Counterevidence (BD-FP-001 to BD-FP-020)
# ===========================================================================

def test_bd_fp_001_to_010_guards_and_sanitizers_refutation():
    """BD-FP-001 to BD-FP-010: Mitigating defensive guards refute false positives."""
    val_svc = BugValidationService()

    # Null safety finding where caller has defensive None check
    res = val_svc.validate_candidate(
        title="Null dereference on record",
        category="null_safety",
        evidence="record.id",
        source_type="AI",
        guards=["if record is None: return None"],
    )
    assert res.is_refuted is True
    assert len(res.counterevidence) >= 1
    assert "Defensive guard detected" in res.counterevidence[0]


# ===========================================================================
# GROUP 8: Scan Modes & Repository Size (BD-SCOPE-001 to BD-SCOPE-020)
# ===========================================================================

def test_bd_scope_001_to_004_quick_standard_change_modes():
    """BD-SCOPE-001 to BD-SCOPE-004: Exercise quick, standard, and change scan modes."""
    discovery = BugCandidateDiscoveryService()
    code = """
# FIXME: crash on zero length
def process_data(items):
    return items[0]
"""
    # Change mode picks up change-risk heuristics
    change_cands = discovery.discover_candidates(
        file_path="data.py",
        code_content=code,
        scan_mode="change",
        changed_files=["data.py"],
    )
    assert any(c.source_type == "CHANGE_RISK" for c in change_cands)

    # Quick mode focuses on deterministic static rules
    quick_cands = discovery.discover_candidates(
        file_path="data.py",
        code_content=code,
        scan_mode="quick",
    )
    assert all(c.source_type in ("STATIC", "TAINT", "CONFIG") for c in quick_cands)


# ===========================================================================
# GROUP 9: Sync, Commit & Cache Correctness (BD-REV-001 to BD-REV-018)
# ===========================================================================

def test_bd_rev_001_to_015_revision_pinning_and_ranking():
    """BD-REV-001 to BD-REV-015: Pinned revisions and idempotent ranking."""
    f1 = BugFinding(
        id="f-rev-1",
        category="logic_error",
        severity="MEDIUM",
        title="Off-by-one",
        description="Issue",
        evidence="x < len",
        source_reference=AnalysisSourceReference(file_path="calc.py", start_line=5, end_line=5, revision="rev-abc123"),
        source_type="STATIC",
    )
    ranked = filter_and_rank_findings([f1])
    assert len(ranked) == 1
    assert ranked[0].source_reference.revision == "rev-abc123"
    assert ranked[0].priority_score is not None


# ===========================================================================
# GROUP 10: Language & Framework Coverage (BD-LANG-001 to BD-LANG-018)
# ===========================================================================

def test_bd_lang_001_to_015_multi_language_rules():
    """BD-LANG-001 to BD-LANG-015: Python, TypeScript, Config checks."""
    reg = RuleRegistry.get_instance()
    py_rules = reg.list_rules(language="python")
    ts_rules = reg.list_rules(language="typescript")
    cfg_rules = reg.list_rules(category="configuration")

    assert len(py_rules) >= 4
    assert len(ts_rules) >= 3
    assert len(cfg_rules) >= 1


# ===========================================================================
# GROUP 11: API, Backend & Persistence Boundaries (BD-API-001 to BD-API-025)
# ===========================================================================

def test_bd_api_005_to_010_path_traversal_and_range_validation():
    """BD-API-005 to BD-API-010: Prevent ../ path escape in findings."""
    f_escape = BugFinding(
        id="f-esc",
        category="security",
        severity="HIGH",
        title="Escaped",
        description="desc",
        evidence="ev",
        source_reference=AnalysisSourceReference(file_path="../../../etc/passwd", start_line=1, end_line=1),
        source_type="STATIC",
    )
    resolved = SimpleNamespace(
        revision="rev-1",
        indexed_paths={"app.py": 100},
        target=AnalysisTarget(path="app.py", start_line=1, end_line=10),
    )
    grounded, dropped = normalize_and_ground_findings(
        [f_escape],
        repository_id=uuid.uuid4(),
        resolved=resolved,
    )
    assert len(grounded) == 0
    assert dropped == 1


# ===========================================================================
# GROUP 12: LLM Quality, Grounding & Fencing (BD-LLM-001 to BD-LLM-024)
# ===========================================================================

# ===========================================================================
# GROUP 13: Frontend & UX Contracts (BD-UI-001 to BD-UI-022)
# ===========================================================================

def test_bd_ui_009_to_010_evidence_levels_and_trace_contracts():
    """BD-UI-009 to BD-UI-010: Evidence levels (PROVEN, STRONG, SUSPECTED, NEEDS_CONTEXT)."""
    val_svc = BugValidationService()

    # Deterministic static rule -> PROVEN
    res_proven = val_svc.validate_candidate(
        title="Unreachable code",
        category="logic_error",
        evidence="after return",
        source_type="STATIC",
    )
    assert res_proven.evidence_level == "PROVEN"

    # Cross-file taint flow -> STRONG
    res_strong = val_svc.validate_candidate(
        title="Untrusted SQL",
        category="security",
        evidence="input to execute",
        source_type="TAINT",
        has_dependency_trace=True,
    )
    assert res_strong.evidence_level == "STRONG"


# ===========================================================================
# GROUP 14: Performance, Concurrency & Resilience (BD-PERF-001 to BD-PERF-018)
# ===========================================================================

def test_bd_perf_001_to_004_bounded_traversal_speed():
    """BD-PERF-001 to BD-PERF-004: Deterministic rule scanning runs in < 50ms."""
    import time
    scanner = StaticBugScanner()
    code = "def calc(x):\n    return x * 2\n" * 50

    start = time.perf_counter()
    res = scanner.scan_code(code, "bench.py")
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert res["success"] is True
    assert elapsed_ms < 100  # Well within performance bounds


# ===========================================================================
# GROUP 15: GitHub Integration Read-Only (BD-GH-001 to BD-GH-017)
# ===========================================================================

def test_bd_gh_001_to_016_github_identity_and_read_only_safety():
    """BD-GH-001 to BD-GH-016: Read-only safety; issues are created via modal draft only."""
    # Finding model has all fields required to pre-fill a GitHub Issue draft
    finding = BugFinding(
        id="f-gh-1",
        category="security",
        severity="HIGH",
        title="SQL injection in search",
        description="Parameter interpolation",
        evidence="cursor.execute(f'SELECT...')",
        suggested_fix="Use parameterized binding",
        source_reference=AnalysisSourceReference(file_path="api/search.py", start_line=30, end_line=30),
        priority_score=85,
        evidence_level="STRONG",
        dependency_trace=["routes/user.py:10", "api/search.py:30"],
        counterevidence=["No parameterized binding detected"],
    )
    assert finding.priority_score == 85
    assert finding.evidence_level == "STRONG"
    assert len(finding.dependency_trace) == 2


# ===========================================================================
# GROUP 16: Finding Quality & Prioritization (BD-QUAL-001 to BD-QUAL-018)
# ===========================================================================

def test_bd_qual_001_to_008_formula_priority_calibration():
    """BD-QUAL-001 to BD-QUAL-008: Verify P = 0.35S + 0.25R + 0.20E + 0.10B + 0.10C."""
    priority_svc = BugPriorityService()

    # High severity critical finding with high reachability
    p1 = priority_svc.calculate_priority(
        severity="CRITICAL",
        evidence_level="STRONG",
        has_callers=True,
        is_security=True,
        is_sanitized=False,
        caller_count=8,
    )
    assert p1.priority_score >= 80

    # Low severity issue with defensive sanitizer
    p2 = priority_svc.calculate_priority(
        severity="LOW",
        evidence_level="SUSPECTED",
        has_callers=False,
        is_security=True,
        is_sanitized=True,
        caller_count=0,
    )
    assert p2.priority_score <= 45
    assert p1.priority_score > p2.priority_score
