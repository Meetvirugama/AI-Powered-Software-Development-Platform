"""Unit and integration tests for AST Rule Integration and Bug Analysis.

Owner: Prit — Repository Engine Lead (W2-Day3)
Fulfills Week 2 Day 3: AST Rule Integration test coverage and acceptance criteria.
"""

import os
from pathlib import Path

import pytest

from scanner.ast_rules import (
    ASTBugAnalyzer,
    ASTBugFinding,
    ASTRuleAnalysisResult,
    BaseASTRule,
    DEFAULT_RULES,
    DeadCodeRule,
    DynamicExecutionRule,
    IdenticalBranchesRule,
    IterationMutationRule,
    MutableDefaultArgumentRule,
    NullDereferenceComparisonRule,
    OffByOneIndexingRule,
    SelfComparisonAssignmentRule,
    SwallowedExceptionRule,
    UnclosedResourceRule,
)
from scanner.symbols import SourceRange
from scanner.target_selector import TargetSelector

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "ast_sample"


@pytest.fixture
def analyzer() -> ASTBugAnalyzer:
    return ASTBugAnalyzer()


@pytest.fixture
def defect_code() -> str:
    path = FIXTURES_DIR / "defect_sample.py"
    return path.read_text(encoding="utf-8")


@pytest.fixture
def clean_code() -> str:
    path = FIXTURES_DIR / "supported_python.py"
    return path.read_text(encoding="utf-8")


@pytest.fixture
def malformed_code() -> str:
    path = FIXTURES_DIR / "malformed_syntax.py"
    return path.read_text(encoding="utf-8")


class TestASTRulesOnDefectFixture:
    """Verify detection of deterministic defects across all supported categories."""

    def test_detects_unclosed_resource(self, analyzer: ASTBugAnalyzer, defect_code: str):
        result = analyzer.analyze_code(defect_code, file_path="defect_sample.py")
        res_findings = [f for f in result.findings if f.rule_id == "AST-RES-001"]
        assert len(res_findings) >= 1
        finding = res_findings[0]
        assert finding.category == "resource_leak"
        assert finding.severity == "high"
        assert "open" in finding.message
        assert finding.line_number > 0
        assert finding.end_line >= finding.line_number
        assert "with" in finding.remediation.lower()

    def test_detects_swallowed_exception(self, analyzer: ASTBugAnalyzer, defect_code: str):
        result = analyzer.analyze_code(defect_code, file_path="defect_sample.py")
        exc_findings = [f for f in result.findings if f.rule_id == "AST-EXC-001"]
        assert len(exc_findings) >= 1
        finding = exc_findings[0]
        assert finding.category == "unhandled_exception"
        assert "except" in finding.evidence
        assert "pass" in finding.message.lower() or "silences" in finding.message.lower()

    def test_detects_mutable_default_argument(self, analyzer: ASTBugAnalyzer, defect_code: str):
        result = analyzer.analyze_code(defect_code, file_path="defect_sample.py")
        arg_findings = [f for f in result.findings if f.rule_id == "AST-ARG-001"]
        assert len(arg_findings) >= 2  # items=[] and config={}
        rule_ids = {f.rule_id for f in arg_findings}
        assert "AST-ARG-001" in rule_ids
        for f in arg_findings:
            assert f.category == "logic_error"
            assert "mutable default" in f.message.lower()
            assert "None" in f.remediation

    def test_detects_null_dereference_and_none_comparison(self, analyzer: ASTBugAnalyzer, defect_code: str):
        result = analyzer.analyze_code(defect_code, file_path="defect_sample.py")
        null_findings = [f for f in result.findings if f.rule_id == "AST-NULL-001"]
        assert len(null_findings) >= 2
        
        # Check equality comparison check (user == None)
        eq_finding = next((f for f in null_findings if "==" in f.message or "is None" in f.message), None)
        assert eq_finding is not None
        assert eq_finding.severity == "low"

        # Check dereference inside if None block (user.profile)
        deref_finding = next((f for f in null_findings if f.severity == "critical"), None)
        assert deref_finding is not None
        assert "dereferenced" in deref_finding.message.lower()

    def test_detects_iteration_mutation(self, analyzer: ASTBugAnalyzer, defect_code: str):
        result = analyzer.analyze_code(defect_code, file_path="defect_sample.py")
        iter_findings = [f for f in result.findings if f.rule_id == "AST-ITER-001"]
        assert len(iter_findings) >= 1
        finding = iter_findings[0]
        assert finding.category == "off_by_one"
        assert "records" in finding.message
        assert ".remove()" in finding.message
        assert "copy" in finding.remediation.lower()

    def test_detects_identical_branches_and_duplicate_conditions(self, analyzer: ASTBugAnalyzer, defect_code: str):
        result = analyzer.analyze_code(defect_code, file_path="defect_sample.py")
        logic_findings = [f for f in result.findings if f.rule_id == "AST-LOGIC-001"]
        assert len(logic_findings) >= 1
        categories = {f.category for f in logic_findings}
        assert "logic_error" in categories

    def test_detects_dead_code_after_return(self, analyzer: ASTBugAnalyzer, defect_code: str):
        result = analyzer.analyze_code(defect_code, file_path="defect_sample.py")
        dead_findings = [f for f in result.findings if f.rule_id == "AST-DEAD-001"]
        assert len(dead_findings) >= 1
        finding = dead_findings[0]
        assert finding.category == "logic_error"
        assert "unreachable" in finding.message.lower()

    def test_detects_dangerous_eval(self, analyzer: ASTBugAnalyzer, defect_code: str):
        result = analyzer.analyze_code(defect_code, file_path="defect_sample.py")
        sec_findings = [f for f in result.findings if f.rule_id == "AST-SEC-001"]
        assert len(sec_findings) >= 1
        finding = sec_findings[0]
        assert finding.category == "security"
        assert finding.severity == "critical"
        assert "eval" in finding.message

    def test_detects_self_comparison_and_assignment(self, analyzer: ASTBugAnalyzer, defect_code: str):
        result = analyzer.analyze_code(defect_code, file_path="defect_sample.py")
        self_findings = [f for f in result.findings if f.rule_id == "AST-LOGIC-002"]
        assert len(self_findings) >= 2  # score = score and score == score

    def test_detects_off_by_one_indexing(self, analyzer: ASTBugAnalyzer, defect_code: str):
        result = analyzer.analyze_code(defect_code, file_path="defect_sample.py")
        bound_findings = [f for f in result.findings if f.rule_id == "AST-BOUND-001"]
        assert len(bound_findings) >= 1
        finding = bound_findings[0]
        assert finding.category == "off_by_one"
        assert finding.severity == "high"
        assert "elements[len(elements)]" in finding.message or "IndexError" in finding.message


class TestCleanCodeAndSyntaxErrors:
    """Verify zero false positives on clean code and graceful reporting on syntax errors."""

    def test_clean_fixture_produces_zero_findings(self, analyzer: ASTBugAnalyzer, clean_code: str):
        result = analyzer.analyze_code(clean_code, file_path="supported_python.py")
        assert result.success is True
        assert len(result.findings) == 0
        assert result.has_syntax_errors is False
        assert result.parse_status == "OK"

    def test_syntax_error_reported_explicitly_without_crash(self, analyzer: ASTBugAnalyzer, malformed_code: str):
        result = analyzer.analyze_code(malformed_code, file_path="malformed_syntax.py")
        assert result.success is True
        assert result.has_syntax_errors is True
        assert result.parse_status == "SYNTAX_WARNING"
        syntax_findings = [f for f in result.findings if f.rule_id == "AST-SYNTAX-ERROR"]
        assert len(syntax_findings) >= 1
        finding = syntax_findings[0]
        assert finding.severity == "critical"
        assert finding.category == "syntax_error"
        assert finding.line_number == 3  # exact syntax error line in malformed_syntax.py


class TestTargetRangeAndSymbolScoping:
    """Verify AST analysis restricted to targeted source ranges and functions."""

    def test_scoping_to_specific_symbol(self, analyzer: ASTBugAnalyzer, defect_code: str):
        # Target only unclosed_resource_defect function
        result = analyzer.analyze_code(
            defect_code,
            file_path="defect_sample.py",
            target_symbol="unclosed_resource_defect",
        )
        assert result.success is True
        assert len(result.findings) == 1
        assert result.findings[0].rule_id == "AST-RES-001"
        assert result.findings[0].enclosing_symbol == "unclosed_resource_defect"

    def test_scoping_to_exact_line_range(self, analyzer: ASTBugAnalyzer, defect_code: str):
        # Line range targeting only dangerous_eval_defect
        target_range = SourceRange(
            file_path="defect_sample.py",
            start_line=74,
            end_line=78,
            symbol_name="dangerous_eval_defect",
        )
        result = analyzer.analyze_code(
            defect_code,
            file_path="defect_sample.py",
            target_range=target_range,
        )
        assert result.success is True
        assert len(result.findings) == 1
        assert result.findings[0].rule_id == "AST-SEC-001"

    def test_empty_content_returns_empty_result(self, analyzer: ASTBugAnalyzer):
        result = analyzer.analyze_code("", file_path="empty.py")
        assert result.success is True
        assert len(result.findings) == 0


class TestPathTraversalAndFileAnalysis:
    """Verify safe disk file analysis and path traversal guard."""

    def test_analyze_file_path_traversal_blocked(self, analyzer: ASTBugAnalyzer, tmp_path: Path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        result = analyzer.analyze_file("../../../secret.py", repo_root=str(repo_root))
        assert result.success is False
        assert "Path traversal" in (result.error_message or "")

    def test_analyze_file_not_found(self, analyzer: ASTBugAnalyzer, tmp_path: Path):
        result = analyzer.analyze_file(str(tmp_path / "missing.py"))
        assert result.success is False
        assert "File not found" in (result.error_message or "")


class TestStaticFindingsAdapter:
    """Verify findings conversion for Devu's static reviewer and Yug's API integration."""

    def test_to_static_findings_format(self, analyzer: ASTBugAnalyzer, defect_code: str):
        result = analyzer.analyze_code(defect_code, file_path="defect_sample.py")
        static_findings = analyzer.to_static_findings(result.findings)
        assert len(static_findings) == len(result.findings)
        
        sample = static_findings[0]
        assert "rule_id" in sample
        assert "severity" in sample
        assert "message" in sample
        assert "file_path" in sample
        assert "line_number" in sample
        assert sample["scanner"] == "ast_rules"
        assert "metadata" in sample
        assert "remediation" in sample["metadata"]
        assert "evidence" in sample["metadata"]

    def test_to_dict_serialization(self, analyzer: ASTBugAnalyzer, defect_code: str):
        result = analyzer.analyze_code(defect_code, file_path="defect_sample.py")
        d = result.to_dict()
        assert d["success"] is True
        assert d["findings_count"] > 0
        assert isinstance(d["findings"], list)
        assert "rules_evaluated" in d

    def test_grouping_helpers(self, analyzer: ASTBugAnalyzer, defect_code: str):
        result = analyzer.analyze_code(defect_code, file_path="defect_sample.py")
        by_sev = result.findings_by_severity()
        assert "high" in by_sev
        assert "critical" in by_sev
        assert len(by_sev["high"]) > 0

        by_cat = result.findings_by_category()
        assert "resource_leak" in by_cat
        assert "security" in by_cat


class TestMultiLanguageASTRules:
    """Verify tree-sitter structural rules on JavaScript and unsupported language handling."""

    def test_javascript_defect_sample(self, analyzer: ASTBugAnalyzer):
        js_path = FIXTURES_DIR / "defect_sample.js"
        js_code = js_path.read_text(encoding="utf-8")
        result = analyzer.analyze_code(js_code, file_path="defect_sample.js", language="JavaScript")
        assert result.success is True
        rule_ids = {f.rule_id for f in result.findings}
        assert "AST-SEC-001" in rule_ids
        assert "AST-EXC-001" in rule_ids

    def test_unsupported_language_returns_explicit_status(self, analyzer: ASTBugAnalyzer):
        result = analyzer.analyze_code("custom syntax code", file_path="sample.xyz", language="UnknownLang")
        assert result.success is True
        assert result.parse_status == "UNSUPPORTED_LANGUAGE"
        assert "not supported" in (result.error_message or "").lower()

