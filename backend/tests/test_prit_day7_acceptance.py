"""Week 2 Day 7 — Final AST, Source-Range, Framework-Detection & Parser Failure Handling Acceptance Suite.

Owner: Prit Zania — Repository Engine Lead (W2-Day7)
Deliverable: Final Acceptance Verification, Supported-Language Limitations & Parser Failure Handling.

Covers:
1. Final AST and Source-Range Fidelity across Python, TypeScript, and JavaScript.
2. Final Framework and Convention Detection (pytest, unittest, jest, vitest, ambiguous manifests).
3. Comprehensive Parser Failure Handling (zero-crash resilience, malformed syntax, 0-byte empty files,
   lone surrogates/encoding, path traversal guards, unsupported languages).
4. Direct Integration with Downstream Developer Intelligence Features (Explanation, Bugs, Tests, Review).
5. Verification of Mandatory Acceptance Scenarios A–E Scanner Invariants.
"""

from __future__ import annotations

import os
from pathlib import Path
import pytest

from scanner.ast_rules import ASTBugAnalyzer, ASTBugFinding, ASTRuleAnalysisResult
from scanner.detector import LanguageDetector
from scanner.extractor import SymbolExtractor
from scanner.framework_detector import (
    FrameworkDetectionResult,
    FrameworkDetector,
    SUPPORTED_FRAMEWORKS,
)
from scanner.parser import Parser
from scanner.source_location import ResolutionResult, SourceLocationResolver
from scanner.source_mapper import (
    FileSourceMapping,
    HunkMapping,
    MappingLimitation,
    ReviewSourceMapper,
    ReviewSourceMapResult,
    SymbolSummary,
)
from scanner.symbols import FileInfo, ParseResult, SourceRange, Symbol
from scanner.target_selector import TargetSelectionResult, TargetSelector

FIXTURES_DIR = Path(__file__).parent / "fixtures"
AST_FIXTURES = FIXTURES_DIR / "ast_sample"
FRAMEWORK_FIXTURES = FIXTURES_DIR / "framework_samples"
PYTHON_FIXTURES = FIXTURES_DIR / "python_sample"
TS_FIXTURES = FIXTURES_DIR / "typescript_sample"
NODE_FIXTURES = FIXTURES_DIR / "nodejs_sample"


@pytest.fixture
def parser() -> Parser:
    return Parser()


@pytest.fixture
def extractor(parser: Parser) -> SymbolExtractor:
    return SymbolExtractor(parser=parser)


@pytest.fixture
def resolver(extractor: SymbolExtractor, parser: Parser) -> SourceLocationResolver:
    return SourceLocationResolver(extractor=extractor, parser=parser)


@pytest.fixture
def selector(
    parser: Parser,
    extractor: SymbolExtractor,
    resolver: SourceLocationResolver,
) -> TargetSelector:
    return TargetSelector(parser=parser, extractor=extractor, resolver=resolver)


@pytest.fixture
def framework_detector() -> FrameworkDetector:
    return FrameworkDetector()


@pytest.fixture
def source_mapper() -> ReviewSourceMapper:
    return ReviewSourceMapper()


@pytest.fixture
def ast_analyzer() -> ASTBugAnalyzer:
    return ASTBugAnalyzer()


# ═══════════════════════════════════════════════════════════════════════════
# 1. Final AST and Source-Range Fidelity Across All Languages
# ═══════════════════════════════════════════════════════════════════════════


class TestFinalASTAndSourceRangeFidelity:
    """Verifies 1-indexed inclusive line ranges, container hierarchies,
    and snippet extraction across Python, TypeScript, and JavaScript."""

    def test_python_source_range_and_container_invariants(
        self, extractor: SymbolExtractor, resolver: SourceLocationResolver
    ):
        path = AST_FIXTURES / "supported_python.py"
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()
        file_info = FileInfo("supported_python.py", len(content), "Python", False)

        symbols = extractor.extract(file_info, content)
        assert len(symbols) >= 5

        # Check line number invariants for every symbol
        for sym in symbols:
            assert sym.start_line >= 1, f"Symbol {sym.name} has invalid start_line: {sym.start_line}"
            assert sym.end_line >= sym.start_line, f"Symbol {sym.name} end_line < start_line"
            assert sym.end_line <= len(lines), f"Symbol {sym.name} end_line exceeds total lines"

        # Check class container hierarchy: c.start <= m.start <= m.end <= c.end
        classes = [s for s in symbols if s.kind == "class"]
        methods = [s for s in symbols if s.kind == "method"]
        assert len(classes) >= 1
        assert len(methods) >= 2

        for method in methods:
            parent = next((c for c in classes if c.id == method.parent_id), None)
            assert parent is not None, f"Method {method.name} missing parent class"
            assert parent.start_line <= method.start_line, (
                f"Parent {parent.name} start_line > method {method.name} start_line"
            )
            assert parent.end_line >= method.end_line, (
                f"Parent {parent.name} end_line < method {method.name} end_line"
            )

        # Verify snippet extraction matches exact slice
        first_func = next(s for s in symbols if s.kind == "function")
        snippet = resolver.extract_snippet(content, first_func.start_line, first_func.end_line)
        expected = "\n".join(lines[first_func.start_line - 1 : first_func.end_line])
        assert snippet == expected

    def test_typescript_classes_methods_and_interfaces(
        self, extractor: SymbolExtractor
    ):
        path = AST_FIXTURES / "supported_typescript.ts"
        content = path.read_text(encoding="utf-8")
        file_info = FileInfo("supported_typescript.ts", len(content), "TypeScript", False)

        symbols = extractor.extract(file_info, content)
        kinds = {s.kind for s in symbols}
        assert "class" in kinds
        assert "method" in kinds
        assert "interface" in kinds

        # Verify interface bounds
        interface_sym = next(s for s in symbols if s.kind == "interface")
        assert interface_sym.name == "UserProfile"
        assert interface_sym.start_line >= 1
        assert interface_sym.end_line >= interface_sym.start_line

        # Verify class and method enclosing invariants
        cls_sym = next(s for s in symbols if s.kind == "class" and s.name == "ProfileService")
        cls_methods = [s for s in symbols if s.kind == "method" and s.parent_id == cls_sym.id]
        assert len(cls_methods) >= 1
        for m in cls_methods:
            assert cls_sym.start_line <= m.start_line <= m.end_line <= cls_sym.end_line

    def test_javascript_classes_functions_and_require_imports(
        self, extractor: SymbolExtractor
    ):
        path = AST_FIXTURES / "supported_javascript.js"
        content = path.read_text(encoding="utf-8")
        file_info = FileInfo("supported_javascript.js", len(content), "JavaScript", False)

        symbols = extractor.extract(file_info, content)
        kinds = {s.kind for s in symbols}
        assert "class" in kinds
        assert "method" in kinds
        assert "function" in kinds
        assert "import" in kinds

        # CommonJS require statements extracted as imports
        req_imports = [s for s in symbols if s.kind == "import"]
        assert len(req_imports) >= 1

    def test_qualified_and_ambiguous_symbol_resolution(
        self, selector: TargetSelector
    ):
        path = AST_FIXTURES / "ambiguous_sample.py"
        content = path.read_text(encoding="utf-8")

        # 1. Unqualified ambiguous symbol resolution flags is_ambiguous=True
        unqualified = selector.select_target(
            file_path="ambiguous_sample.py",
            content=content,
            target_type="symbol",
            symbol_name="format_data",
            language="Python",
        )
        assert unqualified.success is True
        assert unqualified.is_ambiguous is True
        assert len(unqualified.candidates) >= 2
        assert unqualified.ambiguity_note is not None

        # 2. Qualified symbol resolution disambiguates precisely
        qualified = selector.select_target(
            file_path="ambiguous_sample.py",
            content=content,
            target_type="symbol",
            symbol_name="SecondaryProcessor.format_data",
            language="Python",
        )
        assert qualified.success is True
        assert qualified.is_ambiguous is False
        assert qualified.enclosing_symbol is not None
        assert qualified.enclosing_symbol.name == "SecondaryProcessor"


# ═══════════════════════════════════════════════════════════════════════════
# 2. Final Framework and Convention Detection Verification
# ═══════════════════════════════════════════════════════════════════════════


class TestFinalFrameworkAndConventionDetection:
    """Verifies framework detection across pytest, unittest, jest, vitest,
    and ambiguous manifests, along with path proposals and fixture extraction."""

    def test_pytest_framework_conventions_and_fixtures(
        self, framework_detector: FrameworkDetector
    ):
        pytest_root = FRAMEWORK_FIXTURES / "pytest_repo"
        result = framework_detector.detect(repo_root=pytest_root)

        assert result.framework == "pytest"
        assert result.language == "Python"
        assert result.is_supported is True
        assert result.status == "CONFIRMED"
        assert result.test_command == "pytest"
        assert result.naming_pattern == "prefix:test_"
        assert "pytest.ini" in (result.config_file or "")

        # Fixture extraction from conftest.py
        assert len(result.fixtures) >= 2
        assert "db_session" in result.fixtures
        assert "configure_environment" in result.fixtures

        # Proposed test path
        proposed = result.propose_test_path("backend/services/auth_service.py")
        assert proposed.endswith("test_auth_service.py")
        assert "\\" not in proposed

    def test_unittest_framework_detection(
        self, framework_detector: FrameworkDetector
    ):
        unittest_root = FRAMEWORK_FIXTURES / "unittest_repo"
        result = framework_detector.detect(repo_root=unittest_root)

        assert result.framework == "unittest"
        assert result.language == "Python"
        assert result.is_supported is True
        assert result.status == "CONFIRMED"
        assert result.test_command == "python -m unittest"
        assert result.naming_pattern == "prefix:test_"

        proposed = result.propose_test_path("app/utils/math.py")
        assert proposed.endswith("test_math.py")
        assert "\\" not in proposed

    def test_jest_framework_detection(
        self, framework_detector: FrameworkDetector
    ):
        jest_root = FRAMEWORK_FIXTURES / "jest_repo"
        result = framework_detector.detect(repo_root=jest_root)

        assert result.framework == "jest"
        assert result.language == "TypeScript"
        assert result.is_supported is True
        assert result.status == "CONFIRMED"
        assert result.test_command == "npm test"

        # Proposed test path follows TypeScript spec/test conventions
        proposed = result.propose_test_path("src/components/Header.tsx")
        assert proposed.endswith(".test.ts") or proposed.endswith(".test.tsx")
        assert "\\" not in proposed

    def test_vitest_unsupported_framework_detection(
        self, framework_detector: FrameworkDetector
    ):
        vitest_root = FRAMEWORK_FIXTURES / "vitest_repo"
        result = framework_detector.detect(repo_root=vitest_root)

        assert result.framework == "vitest"
        assert result.is_supported is False
        assert result.status == "UNSUPPORTED_FRAMEWORK"
        assert any("Vitest" in w or "vitest" in w for w in result.warnings)

    def test_ambiguous_runners_manifest_detection(
        self, framework_detector: FrameworkDetector
    ):
        ambiguous_root = FRAMEWORK_FIXTURES / "ambiguous_repo"
        result = framework_detector.detect(repo_root=ambiguous_root)

        assert result.is_ambiguous is True
        assert result.status == "AMBIGUOUS"
        assert len(result.candidate_frameworks) >= 2
        assert "jest" in result.candidate_frameworks
        assert "vitest" in result.candidate_frameworks
        assert result.ambiguity_reason is not None


# ═══════════════════════════════════════════════════════════════════════════
# 3. Comprehensive Parser Failure Handling & Zero-Crash Resilience
# ═══════════════════════════════════════════════════════════════════════════


class TestComprehensiveParserFailureHandling:
    """Verifies that malformed syntax, 0-byte files, lone surrogates,
    unsupported languages, and boundary violations never crash the platform."""

    def test_malformed_syntax_zero_crash_contract(
        self, parser: Parser, extractor: SymbolExtractor, selector: TargetSelector, ast_analyzer: ASTBugAnalyzer
    ):
        path = AST_FIXTURES / "malformed_syntax.py"
        content = path.read_text(encoding="utf-8")
        file_info = FileInfo("malformed_syntax.py", len(content), "Python", False)

        # 1. Parser reports syntax error status without exception
        parse_res = parser.parse_with_status(file_info, content)
        assert parse_res.has_syntax_errors is True
        assert parse_res.is_supported is True

        # 2. Extractor still recovers cleanly formed symbols
        symbols = extractor.extract(file_info, content)
        assert len(symbols) >= 1
        assert any(s.name == "ValidClassAfterError" for s in symbols)

        # 3. Target selector returns SYNTAX_WARNING status
        sel_result = selector.select_target(
            file_path="malformed_syntax.py",
            content=content,
            target_type="symbol",
            symbol_name="ValidClassAfterError",
            language="Python",
        )
        assert sel_result.success is True
        assert sel_result.has_syntax_errors is True

        # 4. AST Bug Analyzer captures AST-SYNTAX-ERROR
        rule_result = ast_analyzer.analyze_code(content, file_path="malformed_syntax.py", language="Python")
        assert rule_result.has_syntax_errors is True
        assert any(f.rule_id == "AST-SYNTAX-ERROR" for f in rule_result.findings)

    def test_empty_files_and_zero_byte_content(
        self, parser: Parser, extractor: SymbolExtractor, selector: TargetSelector, resolver: SourceLocationResolver
    ):
        empty_content = ""
        file_info = FileInfo("empty.py", 0, "Python", False)

        # Parser
        parse_res = parser.parse_with_status(file_info, empty_content)
        assert parse_res.success is True
        assert parse_res.has_syntax_errors is False

        # Extractor returns empty list
        symbols = extractor.extract(file_info, empty_content)
        assert symbols == []

        # Snippet extraction returns empty string without IndexError
        snippet = resolver.extract_snippet(empty_content, 1, 10)
        assert snippet == ""

        # Target selection reports 0 lines
        target_res = selector.select_target(
            file_path="empty.py",
            content=empty_content,
            target_type="file",
            language="Python",
        )
        assert target_res.total_file_lines == 0
        assert target_res.content == ""

    def test_lone_surrogates_and_unicode_resilience(
        self, parser: Parser, extractor: SymbolExtractor, ast_analyzer: ASTBugAnalyzer
    ):
        # String with lone surrogate character '\ud800' which crashes unhandled bytes(..., 'utf8')
        problematic_content = "def test_surrogate():\n    msg = '\ud800'\n    return msg\n"
        file_info = FileInfo("surrogate.py", len(problematic_content), "Python", False)

        # Must parse without UnicodeEncodeError
        parse_res = parser.parse_with_status(file_info, problematic_content)
        assert parse_res is not None

        # Extractor extracts symbols without crash
        symbols = extractor.extract(file_info, problematic_content)
        assert len(symbols) >= 1

        # ASTBugAnalyzer evaluates without Unicode crash
        rule_res = ast_analyzer.analyze_code(problematic_content, file_path="surrogate.py", language="Python")
        assert rule_res is not None

    def test_unsupported_language_graceful_rejection(
        self, parser: Parser, selector: TargetSelector, resolver: SourceLocationResolver
    ):
        path = AST_FIXTURES / "unsupported_lang.xyz"
        content = path.read_text(encoding="utf-8")
        file_info = FileInfo("unsupported_lang.xyz", len(content), "UnsupportedXYZ", False)

        # Parser explicitly reports is_supported=False
        parse_res = parser.parse_with_status(file_info, content)
        assert parse_res.success is False
        assert parse_res.is_supported is False
        assert "Unsupported language" in (parse_res.error_message or "")

        # SourceLocationResolver returns UNSUPPORTED_LANGUAGE
        res_result = resolver.resolve_target(
            file_path="unsupported_lang.xyz",
            content=content,
            language="UnsupportedXYZ",
            symbol_name="main",
        )
        assert res_result.is_supported is False
        assert res_result.error_code == "UNSUPPORTED_LANGUAGE"

        # TargetSelector reports UNSUPPORTED_LANGUAGE
        target_res = selector.select_target(
            file_path="unsupported_lang.xyz",
            content=content,
            target_type="symbol",
            symbol_name="main",
            language="UnsupportedXYZ",
        )
        assert target_res.is_supported is False
        assert target_res.error_code == "UNSUPPORTED_LANGUAGE"

    def test_path_traversal_guards(
        self, ast_analyzer: ASTBugAnalyzer, framework_detector: FrameworkDetector
    ):
        # Attempting path traversal outside repo root
        traversal_path = "../../etc/shadow"
        result = ast_analyzer.analyze_file(
            file_path=traversal_path,
            repo_root=AST_FIXTURES,
        )
        assert result.success is False
        assert "Path traversal detected" in (result.error_message or "")

        # Framework detector safe reader blocks traversal
        content = framework_detector._read_file(AST_FIXTURES, "../../secret.env")
        assert content == ""

    def test_line_out_of_bounds_contract(
        self, resolver: SourceLocationResolver, selector: TargetSelector
    ):
        content = "def single_line(): pass\n"
        # Requesting line 100 on a 1-line file
        res = resolver.resolve_target(
            file_path="sample.py",
            content=content,
            start_line=100,
            end_line=120,
            language="Python",
        )
        assert res.success is False
        assert res.error_code == "LINE_OUT_OF_BOUNDS"

        sel_res = selector.select_target(
            file_path="sample.py",
            content=content,
            target_type="range",
            start_line=100,
            end_line=120,
            language="Python",
        )
        assert sel_res.success is False
        assert sel_res.error_code == "LINE_OUT_OF_BOUNDS"


# ═══════════════════════════════════════════════════════════════════════════
# 4. Integration with Downstream Developer Intelligence Features
# ═══════════════════════════════════════════════════════════════════════════


class TestDownstreamFeatureIntegrationContracts:
    """Verifies that the scanner's outputs seamlessly integrate into
    Explanation, Bug Detection, Test Generation, and AI Code Review."""

    def test_code_explanation_target_snippet_bridge(self, selector: TargetSelector):
        path = AST_FIXTURES / "supported_python.py"
        content = path.read_text(encoding="utf-8")

        result = selector.select_target(
            file_path="supported_python.py",
            content=content,
            target_type="symbol",
            symbol_name="calculate_tax",
            language="Python",
        )
        assert result.success is True

        # Convert to TargetSnippet used by Meet's IntelligenceContext
        target_snippet = result.to_target_snippet(language="python")
        assert target_snippet is not None
        assert target_snippet.file_path == "supported_python.py"
        assert target_snippet.symbol_name == "calculate_tax"
        assert target_snippet.start_line == 23
        assert target_snippet.end_line == 27
        assert "def calculate_tax" in target_snippet.content

    def test_bug_detection_engine_structural_findings_bridge(self, ast_analyzer: ASTBugAnalyzer):
        path = AST_FIXTURES / "defect_sample.py"
        content = path.read_text(encoding="utf-8")

        result = ast_analyzer.analyze_code(content, file_path="defect_sample.py", language="Python")
        assert result.success is True
        assert len(result.findings) >= 6

        # Convert to Devu's StaticFinding dictionary format
        static_findings = ast_analyzer.to_static_findings(result.findings)
        assert len(static_findings) == len(result.findings)
        for sf in static_findings:
            assert sf["scanner"] == "ast_rules"
            assert "line_number" in sf
            assert "message" in sf
            assert "metadata" in sf
            assert "category" in sf["metadata"]
            assert "end_line" in sf["metadata"]
            assert "remediation" in sf["metadata"]
            assert "evidence" in sf["metadata"]

    def test_test_generation_framework_profile_bridge(self, framework_detector: FrameworkDetector):
        pytest_root = FRAMEWORK_FIXTURES / "pytest_repo"
        result = framework_detector.detect(repo_root=pytest_root)

        profile = result.to_dict()
        assert profile["framework"] == "pytest"
        assert profile["is_supported"] is True
        assert profile["test_command"] == "pytest"
        assert profile["naming_pattern"] == "prefix:test_"
        assert "db_session" in profile["fixtures"]

        test_path = result.propose_test_path("backend/api/auth.py")
        assert test_path.endswith("test_auth.py")

    def test_ai_code_review_source_mapper_bridge(self, source_mapper: ReviewSourceMapper):
        diff_text = """diff --git a/supported_python.py b/supported_python.py
index 1111111..2222222 100644
--- a/supported_python.py
+++ b/supported_python.py
@@ -24,2 +24,3 @@ def calculate_tax(amount: float, rate: float = 0.1) -> float:
     if amount <= 0:
+        # audit log
         return 0.0
"""
        py_content = (AST_FIXTURES / "supported_python.py").read_text(encoding="utf-8")

        map_result: ReviewSourceMapResult = source_mapper.map_unified_diff(
            diff_text=diff_text,
            repo_files={"supported_python.py": py_content},
            head_revision="feat-branch",
        )

        assert map_result.success is True
        assert len(map_result.files) == 1
        file_map = map_result.files[0]
        assert file_map.file_path == "supported_python.py"
        assert len(file_map.hunks) == 1

        hunk = file_map.hunks[0]
        assert hunk.enclosing_symbol is not None
        assert hunk.enclosing_symbol.name == "calculate_tax"
        assert hunk.enclosing_symbol.kind == "function"

        # Convert to AnalysisSourceReference objects for Dev's review findings pipeline
        source_refs = map_result.to_source_references()
        assert len(source_refs) >= 1
        ref = source_refs[0]
        assert ref.file_path == "supported_python.py"
        assert ref.symbol_name == "calculate_tax"


# ═══════════════════════════════════════════════════════════════════════════
# 5. Verification of Mandatory Acceptance Scenarios A–E Scanner Invariants
# ═══════════════════════════════════════════════════════════════════════════


class TestAcceptanceScenariosScannerInvariants:
    """Verifies that the scanner strictly enforces the invariants
    stipulated in Week 2 Section 12 Acceptance Scenarios A through E."""

    def test_scenario_a_code_explanation_invariants(self, selector: TargetSelector):
        # Scenario A: Real source file, select class/function, verify exact line bounds and symbols
        path = AST_FIXTURES / "supported_python.py"
        content = path.read_text(encoding="utf-8")

        res = selector.select_target(
            file_path="supported_python.py",
            content=content,
            target_type="symbol",
            symbol_name="AccountManager",
            language="Python",
        )
        assert res.success is True
        assert res.symbol_kind == "class"
        assert len(res.child_symbols) >= 2
        assert all(cs.start_line >= res.start_line for cs in res.child_symbols)
        assert all(cs.end_line <= res.end_line for cs in res.child_symbols)

    def test_scenario_b_bug_detection_invariants(self, ast_analyzer: ASTBugAnalyzer):
        # Scenario B: Open defect fixture, detect known defect, test clean fixture zero findings
        defect_content = (AST_FIXTURES / "defect_sample.py").read_text(encoding="utf-8")
        defect_res = ast_analyzer.analyze_code(defect_content, file_path="defect_sample.py", language="Python")
        assert defect_res.success is True
        rule_ids = {f.rule_id for f in defect_res.findings}
        assert "AST-RES-001" in rule_ids  # resource leak
        assert "AST-EXC-001" in rule_ids  # bare except
        assert "AST-ARG-001" in rule_ids  # mutable default
        assert "AST-BOUND-001" in rule_ids  # len() indexing off-by-one

        # Clean fixture returns zero false alarms
        clean_content = (AST_FIXTURES / "supported_python.py").read_text(encoding="utf-8")
        clean_res = ast_analyzer.analyze_code(clean_content, file_path="supported_python.py", language="Python")
        assert clean_res.success is True
        assert len(clean_res.findings) == 0

    def test_scenario_c_test_generation_invariants(self, framework_detector: FrameworkDetector):
        # Scenario C: Supported test framework convention detection
        pytest_root = FRAMEWORK_FIXTURES / "pytest_repo"
        res = framework_detector.detect(repo_root=pytest_root)
        assert res.framework in SUPPORTED_FRAMEWORKS
        assert res.test_command is not None
        assert res.propose_test_path("backend/worker.py").endswith("test_worker.py")

    def test_scenario_d_code_review_invariants(self, source_mapper: ReviewSourceMapper):
        # Scenario D: Diff review without autonomous task, structured report tied to revision
        diff_text = """--- a/supported_python.py
+++ b/supported_python.py
@@ -14,3 +14,4 @@ class AccountManager:
     def get_display_name(self) -> str:
+        # logging
         return f"User: {self.name}"
"""
        py_content = (AST_FIXTURES / "supported_python.py").read_text(encoding="utf-8")
        res = source_mapper.map_unified_diff(
            diff_text=diff_text,
            repo_files={"supported_python.py": py_content},
            commit_sha="abc1234",
        )
        assert res.success is True
        assert res.commit_sha == "abc1234"
        assert len(res.files) == 1
        assert res.files[0].change_type == "modified"
        assert res.files[0].language == "Python"

    def test_scenario_e_security_and_failure_invariants(
        self, selector: TargetSelector, resolver: SourceLocationResolver, parser: Parser
    ):
        # Scenario E: Non-existent file, invalid range, malformed input fail explicitly
        # 1. Non-existent symbol
        missing_res = selector.select_target(
            file_path="app.py",
            content="def foo(): pass",
            target_type="symbol",
            symbol_name="nonexistent_function",
            language="Python",
        )
        assert missing_res.success is False
        assert missing_res.error_code == "SYMBOL_NOT_FOUND"

        # 2. Invalid negative line bounds
        invalid_bounds = resolver.resolve_target(
            file_path="app.py",
            content="def foo(): pass",
            start_line=-5,
            end_line=2,
            language="Python",
        )
        assert invalid_bounds.success is False
        assert invalid_bounds.error_code == "LINE_OUT_OF_BOUNDS"
