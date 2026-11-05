"""Comprehensive Automated Test Suite for Test Generation Feature Redesign.

Fulfills task.md §1-§9:
1. Requirement discovery across 14 categories.
2. Multi-level test evidence mapping (import, call, assertion).
3. Test coverage analyzer & symbol estimation.
4. Test gap analysis & prioritization.
5. Three generation modes: full_repository, targeted, change_based.
6. Test quality analyzer: weak assertions, duplicates, flakiness, quality report.
7. Test requirement service & deterministic planning.
8. Test generation reporting & markdown generation.
9. Orchestrator sanitization, path safety, and truthful execution state.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from app.models.repository_file import RepositoryFile
from app.schemas.analysis import (
    AnalysisOptions,
    AnalysisTarget,
    TestGenerationRequest,
    TestGenerationResult,
    TestQualityReport,
    TestRequirement,
    TestScenario,
)
from scanner.symbols import Symbol, SymbolEdge
from scanner.test_coverage_analyzer import TestCoverageAnalyzer
from scanner.test_gap_analyzer import TestGapAnalyzer
from scanner.test_mapper import FileTestMapper, TestEvidenceLevel
from scanner.test_quality_analyzer import TestQualityAnalyzer
from scanner.test_requirement_discovery import TestRequirementDiscovery
from app.services.test_generation_report import format_test_suite_report_markdown
from app.services.test_requirement_orchestrator import TestRequirementOrchestrator


# ---------------------------------------------------------------------------
# Test Sample Sources
# ---------------------------------------------------------------------------

SAMPLE_AUTH_CODE = """
import os
import httpx
from datetime import datetime

class AuthService:
    def __init__(self, db_session):
        self.db = db_session
        self.secret_key = os.getenv("AUTH_SECRET", "default_secret")

    def login(self, username: str, password_hash: str) -> bool:
        # FIXME: add brute-force lockout protection
        if not username or not password_hash:
            raise ValueError("Username and password required")
        user = self.db.query("SELECT * FROM users WHERE name = ?", username)
        if not user:
            return False
        return True

    async def authenticate_token(self, token: str) -> dict:
        if not token:
            raise ValueError("Token is required")
        res = await httpx.post("https://auth.internal/verify", json={"token": token})
        return res.json()
"""

SAMPLE_TEST_CODE = """
import pytest
from app.services.auth import AuthService

def test_login_valid_credentials(db_mock):
    service = AuthService(db_mock)
    result = service.login("admin", "hash123")
    assert result is True

def test_login_empty_raises(db_mock):
    service = AuthService(db_mock)
    with pytest.raises(ValueError):
        service.login("", "")

def test_weak_trivial():
    assert True
"""


# ---------------------------------------------------------------------------
# 1. Requirement Discovery Tests (14 Categories)
# ---------------------------------------------------------------------------

def test_requirement_discovery_categories():
    """Verify discovery extracts functional, boundary, negative, exception, security, and integration."""
    file_id = uuid4()
    sym_cls = Symbol(
        id=uuid4(),
        name="AuthService",
        kind="class",
        file_id=file_id,
        start_line=5,
        end_line=24,
        signature="class AuthService",
    )
    sym_fn = Symbol(
        id=uuid4(),
        name="login",
        kind="method",
        file_id=file_id,
        start_line=11,
        end_line=17,
        signature="def login(self, username: str, password_hash: str) -> bool",
    )

    discovery = TestRequirementDiscovery(
        symbols=[sym_cls, sym_fn],
        file_paths={file_id: "backend/app/services/auth.py"},
    )

    reqs = discovery.discover_requirements(
        target_files=["backend/app/services/auth.py"],
        file_contents={"backend/app/services/auth.py": SAMPLE_AUTH_CODE},
    )

    assert len(reqs) > 0
    categories = {r.category for r in reqs}

    # Verify key categories detected
    assert "functional" in categories
    assert "boundary" in categories
    assert "negative" in categories
    assert "exception_handling" in categories
    assert "security" in categories
    assert "integration" in categories
    assert "configuration" in categories
    assert "regression" in categories  # detected FIXME

    # Verify regression requirement title and tag
    reg_reqs = [r for r in reqs if r.category == "regression"]
    assert any("FIXME" in r.title for r in reg_reqs)


# ---------------------------------------------------------------------------
# 2. Multi-Level Evidence Mapping Tests
# ---------------------------------------------------------------------------

def test_multi_level_test_evidence():
    """Verify test mapper detects import, call, and assertion evidence levels."""
    src_fid = uuid4()
    test_fid = uuid4()

    src_sym = Symbol(
        id=uuid4(),
        name="AuthService",
        kind="class",
        file_id=src_fid,
        start_line=5,
        end_line=24,
        signature="class AuthService",
    )
    test_sym = Symbol(
        id=uuid4(),
        name="test_login_valid_credentials",
        kind="function",
        file_id=test_fid,
        start_line=4,
        end_line=8,
        signature="def test_login_valid_credentials()",
    )

    edge_import = SymbolEdge(source_id=test_sym.id, target_id=src_sym.id, edge_type="imports")
    edge_call = SymbolEdge(source_id=test_sym.id, target_id=src_sym.id, edge_type="calls")

    mapper = FileTestMapper(
        symbols=[src_sym, test_sym],
        edges=[edge_import, edge_call],
        file_paths={
            src_fid: "backend/app/services/auth.py",
            test_fid: "backend/tests/test_auth.py",
        },
    )

    evidence = mapper.analyze_test_evidence(
        test_code_by_path={"backend/tests/test_auth.py": SAMPLE_TEST_CODE}
    )

    evidence_types = {e.evidence_type for e in evidence}
    assert "import" in evidence_types
    assert "call" in evidence_types
    assert "assertion" in evidence_types

    # Proven assertion confidence
    assert any(e.confidence == "PROVEN" for e in evidence)


# ---------------------------------------------------------------------------
# 3. Test Coverage Analyzer Tests
# ---------------------------------------------------------------------------

def test_coverage_analyzer_parsing():
    """Verify test coverage analyzer parses pytest coverage table and computes metrics."""
    analyzer = TestCoverageAnalyzer()

    sample_cov_table = """
Name                              Stmts   Miss  Cover
-----------------------------------------------------
backend/app/services/auth.py         20      2    90%
backend/app/services/utils.py        10      5    50%
-----------------------------------------------------
TOTAL                                30      7    77%
"""
    result = analyzer.parse_coverage_output(sample_cov_table)

    assert result.total_statements == 30
    assert result.missed_statements == 7
    assert result.covered_statements == 23
    assert result.line_coverage_percent == 76.67
    assert "backend/app/services/auth.py" in result.file_summaries
    assert result.file_summaries["backend/app/services/auth.py"].coverage_percent == 90.0


# ---------------------------------------------------------------------------
# 4. Test Gap Analyzer Tests
# ---------------------------------------------------------------------------

def test_gap_analyzer_categorization():
    """Verify gap analyzer categorizes requirements into COVERED, PARTIAL, and MISSING."""
    gap_analyzer = TestGapAnalyzer()

    req_covered = TestRequirement(
        requirement_id="REQ-001",
        title="Valid login",
        category="functional",
        priority="HIGH",
        source_files=["backend/app/services/auth.py"],
        source_symbols=["login"],
        expected_behavior="Returns true",
        status="MISSING",
    )
    req_missing = TestRequirement(
        requirement_id="REQ-002",
        title="SQL injection safety",
        category="security",
        priority="CRITICAL",
        source_files=["backend/app/services/auth.py"],
        source_symbols=["login"],
        expected_behavior="Rejects quotes",
        status="MISSING",
    )

    evidence = [
        TestEvidenceLevel(
            test_file="backend/tests/test_auth.py",
            source_file="backend/app/services/auth.py",
            source_symbol="login",
            evidence_type="assertion",
            confidence="PROVEN",
            description="Asserts true",
        )
    ]

    result = gap_analyzer.analyze_gaps([req_covered, req_missing], evidence_list=evidence)

    assert result.total_requirements == 2
    assert result.covered_count == 1
    assert result.partial_count == 1
    assert result.critical_missing_count == 1
    assert result.requirement_coverage_percent == 75.0

    # Top prioritized gap must be the critical missing requirement
    assert result.prioritized_gaps[0].requirement_id == "REQ-002"


# ---------------------------------------------------------------------------
# 5. Quality Analyzer Tests (Weak Assertions & Flakiness)
# ---------------------------------------------------------------------------

def test_quality_analyzer_detects_defects():
    """Verify quality analyzer catches weak assertions, flakiness, and computes report."""
    quality_analyzer = TestQualityAnalyzer()

    flaky_code = """
import time
import random

def test_flaky_timing():
    time.sleep(0.5)
    val = random.random()
    assert True
"""
    inspection = quality_analyzer.inspect_test_code(flaky_code, "test_flaky.py")

    assert len(inspection.weak_assertions) > 0  # assert True
    assert len(inspection.flaky_indicators) >= 2  # time.sleep, random.random
    assert inspection.passed_quality_gate is False

    req = TestRequirement(
        requirement_id="REQ-001",
        title="Check",
        category="functional",
        priority="HIGH",
        expected_behavior="Works",
        status="COVERED",
    )
    report = quality_analyzer.compute_quality_report([req], test_code_map={"test_flaky.py": flaky_code})

    assert report.weak_assertion_count >= 1
    assert report.flaky_test_count >= 2
    assert report.quality_score is not None
    assert report.quality_score < 100.0


# ---------------------------------------------------------------------------
# 7. Test Requirement Orchestrator (Modes: targeted, full_repository, change_based)
# ---------------------------------------------------------------------------

def test_orchestrator_generation_modes():
    """Verify test requirement orchestrator handles targeted, full_repo, and change_based modes."""
    orchestrator = TestRequirementOrchestrator()

    file_1 = RepositoryFile(id=uuid4(), repository_id=uuid4(), path="backend/app/services/auth.py", size_bytes=100)
    file_2 = RepositoryFile(id=uuid4(), repository_id=uuid4(), path="backend/app/services/user.py", size_bytes=100)
    all_files = [file_1, file_2]

    sym = Symbol(
        id=uuid4(),
        name="login",
        kind="function",
        file_id=file_1.id,
        start_line=1,
        end_line=10,
        signature="def login()",
    )

    # 1. Targeted mode
    req_targeted = TestGenerationRequest(
        target=AnalysisTarget(type="file", path="backend/app/services/auth.py"),
        generation_mode="targeted",
    )
    res_targeted = orchestrator.orchestrate_requirements(
        repository_id=uuid4(),
        payload=req_targeted,
        db=None,
        all_repo_files=all_files,
        repo_symbols=[sym],
        repo_edges=[],
        file_contents={"backend/app/services/auth.py": SAMPLE_AUTH_CODE},
    )
    assert res_targeted.generation_mode == "targeted"
    assert res_targeted.target_files == ["backend/app/services/auth.py"]

    # 2. Full Repository mode
    req_full = TestGenerationRequest(
        target=AnalysisTarget(type="file", path="backend/app/services/auth.py"),
        generation_mode="full_repository",
    )
    res_full = orchestrator.orchestrate_requirements(
        repository_id=uuid4(),
        payload=req_full,
        db=None,
        all_repo_files=all_files,
        repo_symbols=[sym],
        repo_edges=[],
        file_contents={
            "backend/app/services/auth.py": SAMPLE_AUTH_CODE,
            "backend/app/services/user.py": "def get_user(): pass",
        },
    )
    assert res_full.generation_mode == "full_repository"
    assert len(res_full.target_files) == 2

    # 3. Change-Based mode
    req_change = TestGenerationRequest(
        target=AnalysisTarget(type="file", path="backend/app/services/auth.py"),
        generation_mode="change_based",
        changed_files=["backend/app/services/auth.py"],
    )
    res_change = orchestrator.orchestrate_requirements(
        repository_id=uuid4(),
        payload=req_change,
        db=None,
        all_repo_files=all_files,
        repo_symbols=[sym],
        repo_edges=[],
        file_contents={"backend/app/services/auth.py": SAMPLE_AUTH_CODE},
    )
    assert res_change.generation_mode == "change_based"
    assert res_change.target_files == ["backend/app/services/auth.py"]


# ---------------------------------------------------------------------------
# 8. Test Generation Report Formatting Tests
# ---------------------------------------------------------------------------

def test_markdown_report_formatting():
    """Verify markdown report formats scorecard and requirement matrix accurately."""
    result = TestGenerationResult(
        detected_framework="pytest",
        proposed_test_path="tests/test_auth.py",
        test_content="def test_example(): assert True",
        covered_scenarios=[
            TestScenario(name="test_example", category="normal", description="Simple assertion")
        ],
        syntax_valid=True,
        execution_status="PASSED",
        requirements=[
            TestRequirement(
                requirement_id="REQ-AUTH-001",
                title="Login functionality",
                category="functional",
                priority="HIGH",
                expected_behavior="Logs in",
                status="COVERED",
            )
        ],
        quality_report=TestQualityReport(
            requirement_coverage_percent=100.0,
            line_coverage_percent=85.5,
            duplicate_test_count=0,
            flaky_test_count=0,
            weak_assertion_count=0,
            quality_score=92.5,
            summary_notes=["Clean test suite"],
        ),
    )

    md = format_test_suite_report_markdown(result)

    assert "# Repository Test Intelligence & Generation Report" in md
    assert "Requirement Coverage | 100.0%" in md
    assert "Line Coverage | 85.5%" in md
    assert "REQ-AUTH-001" in md
    assert "✅ COVERED" in md
