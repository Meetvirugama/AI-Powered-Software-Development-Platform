"""Week 2 Day 6 — AST and Framework Reliability Verification Suite.

Owner: Prit — Repository Engine Lead (W2-Day6)
Deliverable: Parser and framework test report verification.

Covers:
1. Source-range tests against all supported fixtures (Python, TypeScript, JavaScript).
2. Function and class selection (exact line bounds, container hierarchies, ambiguous disambiguation).
3. Framework detection across all sample repositories (pytest, unittest, jest, vitest, ambiguous).
4. Malformed syntax, empty files, and unsupported language contracts (zero-crash resilience).
5. Cross-component 1-indexed line and POSIX path mapping consistency.
"""

from __future__ import annotations

import os
from pathlib import Path
import pytest

from scanner.ast_rules import ASTBugAnalyzer
from scanner.detector import LanguageDetector
from scanner.extractor import SymbolExtractor
from scanner.framework_detector import (
    FrameworkDetectionResult,
    FrameworkDetector,
    SUPPORTED_FRAMEWORKS,
)
from scanner.parser import Parser
from scanner.source_location import ResolutionResult, SourceLocationResolver
from scanner.source_mapper import ReviewSourceMapper, ReviewSourceMapResult
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
# 1. Source-Range Tests Across Supported Fixtures
# ═══════════════════════════════════════════════════════════════════════════


class TestSourceRangeFidelityAcrossFixtures:
    """Verifies that symbol ranges across Python, TypeScript, and JavaScript fixtures
    strictly adhere to 1-indexed inclusive line bounds and contain exact content."""

    def test_python_fixture_source_ranges(
        self, extractor: SymbolExtractor, resolver: SourceLocationResolver
    ):
        path = AST_FIXTURES / "supported_python.py"
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()
        file_info = FileInfo("supported_python.py", len(content), "Python", False)

        symbols = extractor.extract(file_info, content)
        assert len(symbols) > 0

        for sym in symbols:
            # Invariant 1: 1-indexed line numbers
            assert sym.start_line >= 1, f"Symbol {sym.name} has invalid start_line: {sym.start_line}"
            assert sym.end_line >= sym.start_line, f"Symbol {sym.name} end_line < start_line"
            assert sym.end_line <= len(lines), f"Symbol {sym.name} end_line exceeds total lines"

            # Invariant 2: Snippet extraction fidelity
            snippet = resolver.extract_snippet(content, sym.start_line, sym.end_line)
            expected = "\n".join(lines[sym.start_line - 1 : sym.end_line])
            assert snippet == expected

    def test_typescript_fixture_source_ranges(
        self, extractor: SymbolExtractor, resolver: SourceLocationResolver
    ):
        path = AST_FIXTURES / "supported_typescript.ts"
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()
        file_info = FileInfo("supported_typescript.ts", len(content), "TypeScript", False)

        symbols = extractor.extract(file_info, content)
        assert len(symbols) > 0

        for sym in symbols:
            assert sym.start_line >= 1
            assert sym.end_line >= sym.start_line
            assert sym.end_line <= len(lines)

            snippet = resolver.extract_snippet(content, sym.start_line, sym.end_line)
            expected = "\n".join(lines[sym.start_line - 1 : sym.end_line])
            assert snippet == expected

    def test_javascript_fixture_source_ranges(
        self, extractor: SymbolExtractor, resolver: SourceLocationResolver
    ):
        path = AST_FIXTURES / "supported_javascript.js"
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()
        file_info = FileInfo("supported_javascript.js", len(content), "JavaScript", False)

        symbols = extractor.extract(file_info, content)
        assert len(symbols) > 0

        for sym in symbols:
            assert sym.start_line >= 1
            assert sym.end_line >= sym.start_line
            assert sym.end_line <= len(lines)

            snippet = resolver.extract_snippet(content, sym.start_line, sym.end_line)
            expected = "\n".join(lines[sym.start_line - 1 : sym.end_line])
            assert snippet == expected

    def test_python_sample_repository_files_ranges(
        self, extractor: SymbolExtractor, resolver: SourceLocationResolver
    ):
        """Audit real repository sample files in python_sample directory."""
        py_files = [f for f in PYTHON_FIXTURES.glob("*.py") if f.name != "ignored.py"]
        assert len(py_files) >= 5

        for py_file in py_files:
            content = py_file.read_text(encoding="utf-8")
            if not content.strip():
                continue
            lines = content.splitlines()
            file_info = FileInfo(py_file.name, len(content), "Python", False)
            symbols = extractor.extract(file_info, content)

            for sym in symbols:
                assert sym.start_line >= 1
                assert sym.end_line >= sym.start_line
                assert sym.end_line <= len(lines)


# ═══════════════════════════════════════════════════════════════════════════
# 2. Function and Class Selection Verification
# ═══════════════════════════════════════════════════════════════════════════


class TestFunctionAndClassSelection:
    """Verifies function and class selection, container nesting, method extraction,
    and ambiguous symbol disambiguation."""

    def test_class_selection_includes_child_methods(self, selector: TargetSelector):
        path = AST_FIXTURES / "supported_python.py"
        content = path.read_text(encoding="utf-8")

        result = selector.select_target(
            file_path="supported_python.py",
            content=content,
            target_type="symbol",
            symbol_name="AccountManager",
            language="Python",
        )

        assert result.success is True
        assert result.symbol_kind == "class"
        assert result.symbol_name == "AccountManager"
        assert len(result.child_symbols) >= 3

        child_names = [s.name for s in result.child_symbols]
        assert "__init__" in child_names
        assert "get_display_name" in child_names
        assert "update_role" in child_names

        # Class boundaries strictly enclose all child methods
        for child in result.child_symbols:
            assert result.start_line <= child.start_line
            assert child.end_line <= result.end_line

    def test_method_selection_resolves_enclosing_class(self, selector: TargetSelector):
        path = AST_FIXTURES / "supported_python.py"
        content = path.read_text(encoding="utf-8")

        result = selector.select_target(
            file_path="supported_python.py",
            content=content,
            target_type="symbol",
            symbol_name="AccountManager.update_role",
            language="Python",
        )

        assert result.success is True
        assert result.symbol_name == "update_role"
        assert result.symbol_kind == "method"
        assert result.enclosing_symbol is not None
        assert result.enclosing_symbol.name == "AccountManager"
        assert result.enclosing_symbol.kind == "class"

    def test_typescript_class_and_method_selection(self, selector: TargetSelector):
        path = AST_FIXTURES / "supported_typescript.ts"
        content = path.read_text(encoding="utf-8")

        # Class selection
        class_res = selector.select_target(
            file_path="supported_typescript.ts",
            content=content,
            target_type="symbol",
            symbol_name="ProfileService",
            language="TypeScript",
        )
        assert class_res.success is True
        assert class_res.symbol_kind == "class"
        assert any(m.name == "getUserProfile" for m in class_res.child_symbols)

        # Method selection via qualified name
        method_res = selector.select_target(
            file_path="supported_typescript.ts",
            content=content,
            target_type="symbol",
            symbol_name="ProfileService.getUserProfile",
            language="TypeScript",
        )
        assert method_res.success is True
        assert method_res.symbol_name == "getUserProfile"
        assert method_res.symbol_kind == "method"
        assert method_res.enclosing_symbol is not None
        assert method_res.enclosing_symbol.name == "ProfileService"

    def test_javascript_class_and_method_selection(self, selector: TargetSelector):
        path = AST_FIXTURES / "supported_javascript.js"
        content = path.read_text(encoding="utf-8")

        # Class selection
        class_res = selector.select_target(
            file_path="supported_javascript.js",
            content=content,
            target_type="symbol",
            symbol_name="RequestHandler",
            language="JavaScript",
        )
        assert class_res.success is True
        assert class_res.symbol_kind == "class"
        assert any(m.name == "handleRequest" for m in class_res.child_symbols)

        # Method selection via qualified name
        method_res = selector.select_target(
            file_path="supported_javascript.js",
            content=content,
            target_type="symbol",
            symbol_name="RequestHandler.handleRequest",
            language="JavaScript",
        )
        assert method_res.success is True
        assert method_res.symbol_name == "handleRequest"
        assert method_res.symbol_kind == "method"
        assert method_res.enclosing_symbol is not None
        assert method_res.enclosing_symbol.name == "RequestHandler"

    def test_ambiguous_symbol_disambiguation_heuristics(self, selector: TargetSelector):
        """Verify ambiguous symbol resolution attaches candidate alternatives and note."""
        path = AST_FIXTURES / "ambiguous_sample.py"
        content = path.read_text(encoding="utf-8")

        # Plain search for 'format_data' (exists in module, PrimaryProcessor, SecondaryProcessor)
        result = selector.select_target(
            file_path="ambiguous_sample.py",
            content=content,
            target_type="symbol",
            symbol_name="format_data",
            language="Python",
        )

        assert result.success is True
        assert result.is_ambiguous is True
        assert "Ambiguous symbol" in (result.ambiguity_note or "")
        assert "3 definitions found" in (result.ambiguity_note or "")

        # Qualified disambiguation selects exact target
        p1 = selector.select_target(
            file_path="ambiguous_sample.py",
            content=content,
            target_type="symbol",
            symbol_name="PrimaryProcessor.format_data",
            language="Python",
        )
        assert p1.success is True
        assert p1.is_ambiguous is False
        assert p1.enclosing_symbol is not None
        assert p1.enclosing_symbol.name == "PrimaryProcessor"

        p2 = selector.select_target(
            file_path="ambiguous_sample.py",
            content=content,
            target_type="symbol",
            symbol_name="SecondaryProcessor.format_data",
            language="Python",
        )
        assert p2.success is True
        assert p2.is_ambiguous is False
        assert p2.enclosing_symbol is not None
        assert p2.enclosing_symbol.name == "SecondaryProcessor"


# ═══════════════════════════════════════════════════════════════════════════
# 3. Framework Detection Verification
# ═══════════════════════════════════════════════════════════════════════════


class TestFrameworkDetectionReliability:
    """Verifies framework detection, convention discovery, and test path proposal
    across all sample repositories."""

    def test_detect_pytest_repo(self, framework_detector: FrameworkDetector):
        repo_dir = FRAMEWORK_FIXTURES / "pytest_repo"
        result = framework_detector.detect(repo_root=repo_dir)

        assert result.framework == "pytest"
        assert result.language == "Python"
        assert result.is_supported is True
        assert result.status == "CONFIRMED"
        assert result.test_command == "pytest"
        assert result.test_directory == "tests"
        assert result.naming_pattern == "prefix:test_"
        assert "db_session" in result.fixtures

        # Propose test path
        proposed = result.propose_test_path("app/services/auth.py")
        assert proposed.replace("\\", "/") == "tests/app/services/test_auth.py"
        assert "\\" not in proposed

    def test_detect_unittest_repo(self, framework_detector: FrameworkDetector):
        repo_dir = FRAMEWORK_FIXTURES / "unittest_repo"
        result = framework_detector.detect(repo_root=repo_dir)

        assert result.framework == "unittest"
        assert result.language == "Python"
        assert result.is_supported is True
        assert result.status == "CONFIRMED"
        assert result.test_command == "python -m unittest"
        assert result.test_directory == "tests"

        proposed = result.propose_test_path("models/user.py")
        assert proposed.replace("\\", "/") == "tests/models/test_user.py"

    def test_detect_jest_repo(self, framework_detector: FrameworkDetector):
        repo_dir = FRAMEWORK_FIXTURES / "jest_repo"
        result = framework_detector.detect(repo_root=repo_dir)

        assert result.framework == "jest"
        assert result.language in ("TypeScript", "JavaScript")
        assert result.is_supported is True
        assert result.status == "CONFIRMED"
        assert result.test_command == "npm test"

        proposed = result.propose_test_path("src/components/Button.tsx")
        assert proposed.endswith(".test.ts") or proposed.endswith(".test.tsx")
        assert "\\" not in proposed

    def test_detect_vitest_repo_unsupported_status(
        self, framework_detector: FrameworkDetector
    ):
        repo_dir = FRAMEWORK_FIXTURES / "vitest_repo"
        result = framework_detector.detect(repo_root=repo_dir)

        assert result.framework == "vitest"
        assert result.is_supported is False
        assert result.status == "UNSUPPORTED_FRAMEWORK"
        assert any("vitest" in w.lower() for w in result.warnings)

    def test_detect_ambiguous_repo_multiple_frameworks(
        self, framework_detector: FrameworkDetector
    ):
        repo_dir = FRAMEWORK_FIXTURES / "ambiguous_repo"
        result = framework_detector.detect(repo_root=repo_dir)

        assert result.is_ambiguous is True
        assert result.status == "AMBIGUOUS"
        assert len(result.candidate_frameworks) >= 2
        assert "Multiple test runners" in (result.ambiguity_reason or "")

    def test_propose_test_path_normalizes_posix_slashes(
        self, framework_detector: FrameworkDetector
    ):
        """Ensure propose_test_path never emits Windows backslashes on any input."""
        res = FrameworkDetectionResult(
            framework="pytest",
            language="Python",
            is_supported=True,
            status="CONFIRMED",
            test_directory="backend/tests",
            naming_pattern="prefix:test_",
        )

        test_inputs = [
            "backend/scanner/parser.py",
            "backend\\scanner\\parser.py",
            "src/utils/math.py",
            "src\\utils\\math.py",
            "models.py",
        ]

        for inp in test_inputs:
            proposed = res.propose_test_path(inp)
            assert "\\" not in proposed, f"Proposed path contained backslash: {proposed}"
            assert proposed.startswith("backend/tests")


# ═══════════════════════════════════════════════════════════════════════════
# 4. Malformed Syntax and Unsupported Construct Resilience
# ═══════════════════════════════════════════════════════════════════════════


class TestMalformedSyntaxAndResilience:
    """Verifies that parsers, extractors, analyzers, and mappers never crash
    on malformed syntax, syntax errors, empty files, or unsupported languages."""

    def test_parser_with_malformed_syntax_file(self, parser: Parser):
        path = AST_FIXTURES / "malformed_syntax.py"
        content = path.read_text(encoding="utf-8")
        file_info = FileInfo("malformed_syntax.py", len(content), "Python", False)

        result = parser.parse_with_status(file_info, content)
        assert result.success is True
        assert result.has_syntax_errors is True
        assert result.error_message is not None

    def test_symbol_extractor_survives_malformed_syntax(self, extractor: SymbolExtractor):
        path = AST_FIXTURES / "malformed_syntax.py"
        content = path.read_text(encoding="utf-8")
        file_info = FileInfo("malformed_syntax.py", len(content), "Python", False)

        symbols = extractor.extract(file_info, content)
        # Should extract valid class and method declared after the syntax error
        names = [s.name for s in symbols]
        assert "ValidClassAfterError" in names
        assert "valid_method" in names

    def test_target_selector_survives_malformed_syntax(self, selector: TargetSelector):
        path = AST_FIXTURES / "malformed_syntax.py"
        content = path.read_text(encoding="utf-8")

        result = selector.select_target(
            file_path="malformed_syntax.py",
            content=content,
            target_type="symbol",
            symbol_name="ValidClassAfterError",
            language="Python",
        )
        assert result.success is True
        assert result.has_syntax_errors is True
        assert result.symbol_name == "ValidClassAfterError"

    def test_ast_bug_analyzer_handles_syntax_error(self, ast_analyzer: ASTBugAnalyzer):
        path = AST_FIXTURES / "malformed_syntax.py"
        content = path.read_text(encoding="utf-8")

        result = ast_analyzer.analyze_code(content, file_path="malformed_syntax.py")
        assert result.success is True
        assert result.has_syntax_errors is True
        assert any(f.rule_id == "AST-SYNTAX-ERROR" for f in result.findings)

    def test_review_source_mapper_handles_syntax_error(
        self, source_mapper: ReviewSourceMapper
    ):
        path = AST_FIXTURES / "malformed_syntax.py"
        content = path.read_text(encoding="utf-8")

        diff = (
            "--- a/malformed_syntax.py\n"
            "+++ b/malformed_syntax.py\n"
            "@@ -2,3 +2,3 @@\n"
            "-def broken_syntax_function(x, y):\n"
            "+def broken_syntax_function(x, y, z):\n"
            "     return x + %%% invalid syntax\n"
        )

        res = source_mapper.map_unified_diff(diff_text=diff, repo_files={"malformed_syntax.py": content})
        assert res.success is True
        assert len(res.files) == 1
        # Limitations include SYNTAX_ERROR
        file_map = res.files[0]
        lim_types = [lim.limitation_type for lim in file_map.limitations]
        assert "SYNTAX_ERROR" in lim_types

    def test_empty_file_handling(
        self,
        parser: Parser,
        extractor: SymbolExtractor,
        resolver: SourceLocationResolver,
        selector: TargetSelector,
    ):
        file_info = FileInfo("empty.py", 0, "Python", False)
        parse_res = parser.parse_with_status(file_info, "")
        assert parse_res.success is True

        symbols = extractor.extract(file_info, "")
        assert symbols == []

        snippet = resolver.extract_snippet("", 1, 10)
        assert snippet == ""

        select_res = selector.select_target("empty.py", "", target_type="file")
        assert select_res.success is False
        assert select_res.error_code == "EMPTY_FILE"
        assert select_res.total_file_lines == 0

    def test_unsupported_language_contracts(
        self,
        parser: Parser,
        resolver: SourceLocationResolver,
        selector: TargetSelector,
        source_mapper: ReviewSourceMapper,
    ):
        path = AST_FIXTURES / "unsupported_lang.xyz"
        content = path.read_text(encoding="utf-8")
        file_info = FileInfo("unsupported_lang.xyz", len(content), "UnsupportedXYZ", False)

        # 1. Parser contract
        parse_res = parser.parse_with_status(file_info, content)
        assert parse_res.is_supported is False

        # 2. SourceLocationResolver contract
        res_res = resolver.resolve_target("unsupported_lang.xyz", content, symbol_name="main", language="UnsupportedXYZ")
        assert res_res.is_supported is False
        assert res_res.error_code == "UNSUPPORTED_LANGUAGE"

        # 3. TargetSelector contract
        sel_res = selector.select_target("unsupported_lang.xyz", content, target_type="symbol", symbol_name="main", language="UnsupportedXYZ")
        assert sel_res.is_supported is False
        assert sel_res.error_code == "UNSUPPORTED_LANGUAGE"

        # 4. ReviewSourceMapper contract
        diff = (
            "--- a/unsupported_lang.xyz\n"
            "+++ b/unsupported_lang.xyz\n"
            "@@ -1,2 +1,2 @@\n"
            "-ROUTINE main() {\n"
            "+ROUTINE main_entry() {\n"
        )
        map_res = source_mapper.map_unified_diff(diff_text=diff, repo_files={"unsupported_lang.xyz": content})
        assert map_res.success is True
        assert len(map_res.files) == 1
        assert map_res.files[0].is_supported is False
        assert any(l.limitation_type == "UNSUPPORTED_LANGUAGE" for l in map_res.files[0].limitations)

    def test_line_out_of_bounds_contract(
        self, resolver: SourceLocationResolver, selector: TargetSelector
    ):
        content = "x = 1\ny = 2\n"
        res = resolver.resolve_target("test.py", content, start_line=999, end_line=1005, language="Python")
        assert res.success is False
        assert res.error_code == "LINE_OUT_OF_BOUNDS"
        assert "out of bounds" in (res.error_message or "").lower()

        sel = selector.select_target("test.py", content, target_type="range", start_line=999, end_line=1005)
        assert sel.success is False
        assert sel.error_code == "LINE_OUT_OF_BOUNDS"


# ═══════════════════════════════════════════════════════════════════════════
# 5. Cross-Component Line and File Mapping Consistency
# ═══════════════════════════════════════════════════════════════════════════


class TestCrossComponentConsistency:
    """Verifies that symbols, ranges, selections, and diff mappings maintain
    100% agreement on 1-indexed line numbers and POSIX path conventions."""

    def test_line_indexing_agreement_across_components(
        self,
        extractor: SymbolExtractor,
        resolver: SourceLocationResolver,
        selector: TargetSelector,
        source_mapper: ReviewSourceMapper,
        ast_analyzer: ASTBugAnalyzer,
    ):
        path = AST_FIXTURES / "supported_python.py"
        content = path.read_text(encoding="utf-8")
        file_info = FileInfo("supported_python.py", len(content), "Python", False)

        # 1. Extractor
        symbols = extractor.extract(file_info, content)
        tax_sym = next(s for s in symbols if s.name == "calculate_tax")

        # 2. Resolver
        tax_range = resolver.resolve_symbol_range(symbols, "calculate_tax", content, "supported_python.py")
        assert tax_range is not None

        # 3. Selector
        tax_select = selector.select_target(
            "supported_python.py", content, target_type="symbol", symbol_name="calculate_tax"
        )
        assert tax_select.success is True

        # Invariant: Extractor, Resolver, and Selector agree on lines
        assert tax_sym.start_line == tax_range.start_line == tax_select.start_line == 23
        assert tax_sym.end_line == tax_range.end_line == tax_select.end_line == 27

        # 4. ReviewSourceMapper diff hunk intersecting calculate_tax
        diff = (
            "--- a/supported_python.py\n"
            "+++ b/supported_python.py\n"
            "@@ -24,2 +24,3 @@\n"
            "     if amount < 0:\n"
            "+        # audit validation\n"
            "         raise ValueError('Amount must be positive')\n"
        )
        map_res = source_mapper.map_unified_diff(diff_text=diff, repo_files={"supported_python.py": content})
        assert map_res.success is True
        hunk = map_res.files[0].hunks[0]
        assert hunk.enclosing_symbol is not None
        assert hunk.enclosing_symbol.name == "calculate_tax"
        assert hunk.enclosing_symbol.start_line == 23
        assert hunk.enclosing_symbol.end_line == 27
