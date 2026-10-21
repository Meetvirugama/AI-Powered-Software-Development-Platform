"""Week 2 Day 1 — AST Symbol Range Resolution, Source Location, and Import Tracking Tests.

Owner: Prit — Repository Engine Lead (W2-07)
Acceptance Criteria:
- Source ranges map accurately to source code for supported fixtures.
- Enclosing symbol resolution returns the tightest enclosing scope.
- Unsupported syntax and languages produce explicit results.
- Scanner never crashes on malformed files.
- Import tracking accurately maps symbols to modules, local files, and dependencies.
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from backend.scanner.detector import LanguageDetector
from backend.scanner.extractor import SymbolExtractor
from backend.scanner.import_tracker import ImportTracker
from backend.scanner.parser import Parser
from backend.scanner.source_location import ResolutionResult, SourceLocationResolver
from backend.scanner.symbols import FileInfo, SourceRange

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "ast_sample"


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
def import_tracker() -> ImportTracker:
    return ImportTracker()


# ---------------------------------------------------------------------------
# 1. Supported Language Audit & Parser Tests
# ---------------------------------------------------------------------------


def test_parser_supported_languages(parser: Parser):
    """Verify supported languages and explicit unsupported language handling."""
    assert parser.is_language_supported("Python")
    assert parser.is_language_supported("TypeScript")
    assert parser.is_language_supported("JavaScript")
    assert parser.is_language_supported("Java")
    assert parser.is_language_supported("Go")
    assert parser.is_language_supported("Rust")
    assert parser.is_language_supported("C")
    assert parser.is_language_supported("C++")

    # Unsupported language
    assert not parser.is_language_supported("Brainfuck")
    assert not parser.is_language_supported("UnknownLang")

    # Explicit parse result on unsupported language
    file_info = FileInfo(path="test.xyz", size_bytes=10, language="UnknownLang", is_binary=False)
    result = parser.parse_with_status(file_info, "VAR x = 1;")
    assert not result.success
    assert not result.is_supported
    assert "Unsupported language" in (result.error_message or "")


# ---------------------------------------------------------------------------
# 2. Python AST Range Mapping & Symbol Extraction
# ---------------------------------------------------------------------------


def test_python_ast_symbol_extraction_and_exact_ranges(
    extractor: SymbolExtractor,
    resolver: SourceLocationResolver,
):
    """Verify exact line numbers for classes, methods, functions, and imports in Python."""
    file_path = FIXTURES_DIR / "supported_python.py"
    content = file_path.read_text(encoding="utf-8")
    file_info = FileInfo(path="supported_python.py", size_bytes=len(content), language="Python", is_binary=False)

    symbols = extractor.extract(file_info, content)
    assert len(symbols) > 0

    sym_by_name = {s.name: s for s in symbols}

    # 1. Class AccountManager
    assert "AccountManager" in sym_by_name
    cls_sym = sym_by_name["AccountManager"]
    assert cls_sym.kind == "class"
    assert cls_sym.start_line == 8
    assert cls_sym.end_line == 20

    # 2. Methods inside AccountManager
    methods = [s for s in symbols if s.kind == "method" and s.parent_id == cls_sym.id]
    method_names = {m.name for m in methods}
    assert "get_display_name" in method_names
    assert "update_role" in method_names

    # 3. Exact line snippet extraction for method
    disp_method = [m for m in methods if m.name == "get_display_name"][0]
    assert disp_method.start_line == 14
    assert disp_method.end_line == 15
    snippet = resolver.extract_snippet(content, disp_method.start_line, disp_method.end_line)
    assert "def get_display_name(self) -> str:" in snippet
    assert 'return f"User: {self.name}"' in snippet

    # 4. Top-level functions
    assert "calculate_tax" in sym_by_name
    calc_func = sym_by_name["calculate_tax"]
    assert calc_func.kind == "function"
    assert calc_func.start_line == 23
    assert calc_func.end_line == 27


# ---------------------------------------------------------------------------
# 3. TypeScript & JavaScript AST Range Mapping
# ---------------------------------------------------------------------------


def test_typescript_ast_symbols_and_ranges(
    extractor: SymbolExtractor,
    resolver: SourceLocationResolver,
):
    """Verify TypeScript interfaces, classes, methods, and functions with ranges."""
    file_path = FIXTURES_DIR / "supported_typescript.ts"
    content = file_path.read_text(encoding="utf-8")
    file_info = FileInfo(path="supported_typescript.ts", size_bytes=len(content), language="TypeScript", is_binary=False)

    symbols = extractor.extract(file_info, content)
    assert len(symbols) > 0

    sym_by_name = {s.name: s for s in symbols}

    # Interface
    assert "UserProfile" in sym_by_name
    iface = sym_by_name["UserProfile"]
    assert iface.kind == "interface"
    assert iface.start_line == 6
    assert iface.end_line == 10

    # Class
    assert "ProfileService" in sym_by_name
    cls_sym = sym_by_name["ProfileService"]
    assert cls_sym.kind == "class"
    assert cls_sym.start_line == 12
    assert cls_sym.end_line == 22


def test_javascript_ast_symbols_and_ranges(
    extractor: SymbolExtractor,
    resolver: SourceLocationResolver,
):
    """Verify JavaScript functions and classes."""
    file_path = FIXTURES_DIR / "supported_javascript.js"
    content = file_path.read_text(encoding="utf-8")
    file_info = FileInfo(path="supported_javascript.js", size_bytes=len(content), language="JavaScript", is_binary=False)

    symbols = extractor.extract(file_info, content)
    assert len(symbols) > 0

    sym_by_name = {s.name: s for s in symbols}
    assert "startServer" in sym_by_name
    assert "RequestHandler" in sym_by_name


# ---------------------------------------------------------------------------
# 4. Enclosing Symbol & Scope Resolution Tests
# ---------------------------------------------------------------------------


def test_enclosing_symbol_lookup(
    extractor: SymbolExtractor,
    resolver: SourceLocationResolver,
):
    """Verify tightest enclosing symbol and scope chain for a line."""
    file_path = FIXTURES_DIR / "supported_python.py"
    content = file_path.read_text(encoding="utf-8")
    file_info = FileInfo(path="supported_python.py", size_bytes=len(content), language="Python", is_binary=False)
    symbols = extractor.extract(file_info, content)

    # Line 15 is inside get_display_name method (lines 14-15), inside AccountManager class (lines 8-20)
    enclosing = resolver.find_enclosing_symbol(symbols, 15)
    assert enclosing is not None
    assert enclosing.name == "get_display_name"
    assert enclosing.kind == "method"

    # Full scope hierarchy
    scope = resolver.find_enclosing_scope(symbols, 15)
    scope_names = [s.name for s in scope]
    assert "AccountManager" in scope_names
    assert "get_display_name" in scope_names
    assert scope_names[0] == "AccountManager"  # Outermost container first

    # Line outside any symbol (e.g. line 6 between constant and class)
    assert resolver.find_enclosing_symbol(symbols, 6) is None


# ---------------------------------------------------------------------------
# 5. Target Snippet Resolution Tests (Meet's Interface Contract)
# ---------------------------------------------------------------------------


def test_resolve_target_by_symbol_name(resolver: SourceLocationResolver):
    """Resolve target code snippet using symbol name."""
    file_path = FIXTURES_DIR / "supported_python.py"
    content = file_path.read_text(encoding="utf-8")

    result = resolver.resolve_target(
        file_path="supported_python.py",
        content=content,
        symbol_name="calculate_tax",
        language="Python",
    )

    assert result.success
    assert result.range is not None
    assert result.range.start_line == 23
    assert result.range.end_line == 27
    assert "def calculate_tax(amount: float, rate: float = 0.1) -> float:" in result.range.content


def test_resolve_target_by_qualified_symbol_name(resolver: SourceLocationResolver):
    """Resolve method via Class.method qualified name."""
    file_path = FIXTURES_DIR / "supported_python.py"
    content = file_path.read_text(encoding="utf-8")

    result = resolver.resolve_target(
        file_path="supported_python.py",
        content=content,
        symbol_name="AccountManager.update_role",
        language="Python",
    )

    assert result.success
    assert result.range is not None
    assert result.range.symbol_name == "update_role"
    assert "def update_role(self, role: str) -> bool:" in result.range.content


def test_resolve_target_by_line_range(resolver: SourceLocationResolver):
    """Resolve target code snippet using explicit line range."""
    file_path = FIXTURES_DIR / "supported_python.py"
    content = file_path.read_text(encoding="utf-8")

    result = resolver.resolve_target(
        file_path="supported_python.py",
        content=content,
        start_line=14,
        end_line=15,
        language="Python",
    )

    assert result.success
    assert result.range is not None
    assert result.range.start_line == 14
    assert result.range.end_line == 15
    assert result.enclosing_symbol is not None
    assert result.enclosing_symbol.name == "get_display_name"


def test_resolve_target_out_of_bounds(resolver: SourceLocationResolver):
    """Line range out of bounds returns explicit error code LINE_OUT_OF_BOUNDS."""
    file_path = FIXTURES_DIR / "supported_python.py"
    content = file_path.read_text(encoding="utf-8")

    result = resolver.resolve_target(
        file_path="supported_python.py",
        content=content,
        start_line=999,
        end_line=1050,
        language="Python",
    )

    assert not result.success
    assert result.error_code == "LINE_OUT_OF_BOUNDS"


def test_resolve_target_nonexistent_symbol(resolver: SourceLocationResolver):
    """Non-existent symbol returns explicit error code SYMBOL_NOT_FOUND."""
    file_path = FIXTURES_DIR / "supported_python.py"
    content = file_path.read_text(encoding="utf-8")

    result = resolver.resolve_target(
        file_path="supported_python.py",
        content=content,
        symbol_name="non_existent_function",
        language="Python",
    )

    assert not result.success
    assert result.error_code == "SYMBOL_NOT_FOUND"


def test_resolve_target_unsupported_language(resolver: SourceLocationResolver):
    """Unsupported language returns explicit is_supported=False and UNSUPPORTED_LANGUAGE."""
    file_path = FIXTURES_DIR / "unsupported_lang.xyz"
    content = file_path.read_text(encoding="utf-8")

    result = resolver.resolve_target(
        file_path="unsupported_lang.xyz",
        content=content,
        symbol_name="main",
        language="UnsupportedXYZ",
    )

    assert not result.success
    assert not result.is_supported
    assert result.error_code == "UNSUPPORTED_LANGUAGE"


# ---------------------------------------------------------------------------
# 6. Parser Error Resilience Tests
# ---------------------------------------------------------------------------


def test_malformed_syntax_graceful_handling(
    extractor: SymbolExtractor,
    parser: Parser,
):
    """Files with malformed syntax do not crash parser, detect syntax errors, and extract valid symbols."""
    file_path = FIXTURES_DIR / "malformed_syntax.py"
    content = file_path.read_text(encoding="utf-8")
    file_info = FileInfo(path="malformed_syntax.py", size_bytes=len(content), language="Python", is_binary=False)

    # 1. Parser status records syntax error without crashing
    parse_result = parser.parse_with_status(file_info, content)
    assert parse_result.success
    assert parse_result.has_syntax_errors

    # 2. Extractor does not crash and pulls valid class after error
    symbols = extractor.extract(file_info, content)
    sym_names = [s.name for s in symbols]
    assert "ValidClassAfterError" in sym_names


# ---------------------------------------------------------------------------
# 7. Import Tracking and Mapping Tests
# ---------------------------------------------------------------------------


def test_python_import_tracking(import_tracker: ImportTracker):
    """Verify import parsing, stdlib/third-party categorization, and local path resolution."""
    file_path = FIXTURES_DIR / "supported_python.py"
    content = file_path.read_text(encoding="utf-8")
    file_info = FileInfo(path="supported_python.py", size_bytes=len(content), language="Python", is_binary=False)

    known_files = ["supported_python.py", "local_module.py"]
    import_map = import_tracker.parse_imports(file_info, content, known_files=known_files)

    assert len(import_map.imports) >= 3

    # 1. os -> Python stdlib
    assert "os" in import_map.by_name
    os_imp = import_map.by_name["os"]
    assert os_imp.is_standard_library
    assert not os_imp.is_relative

    # 2. typing -> Python stdlib
    assert "List" in import_map.by_name
    list_imp = import_map.by_name["List"]
    assert list_imp.is_standard_library

    # 3. Helper from .local_module -> local relative import
    assert "Helper" in import_map.by_name
    helper_imp = import_map.by_name["Helper"]
    assert helper_imp.is_relative
    assert helper_imp.resolved_path == "local_module.py"
    assert "local_module.py" in import_map.local_dependencies


def test_typescript_import_tracking(import_tracker: ImportTracker):
    """Verify TypeScript named imports and external dependencies."""
    file_path = FIXTURES_DIR / "supported_typescript.ts"
    content = file_path.read_text(encoding="utf-8")
    file_info = FileInfo(path="supported_typescript.ts", size_bytes=len(content), language="TypeScript", is_binary=False)

    known_files = ["supported_typescript.ts", "local_module.ts"]
    import_map = import_tracker.parse_imports(file_info, content, known_files=known_files)

    assert "Observable" in import_map.by_name
    obs_imp = import_map.by_name["Observable"]
    assert obs_imp.is_third_party
    assert obs_imp.module == "rxjs"
    assert "rxjs" in import_map.external_dependencies

    assert "Helper" in import_map.by_name
    helper_imp = import_map.by_name["Helper"]
    assert helper_imp.is_relative


def test_javascript_require_tracking(import_tracker: ImportTracker):
    """Verify CommonJS require statements tracking."""
    file_path = FIXTURES_DIR / "supported_javascript.js"
    content = file_path.read_text(encoding="utf-8")
    file_info = FileInfo(path="supported_javascript.js", size_bytes=len(content), language="JavaScript", is_binary=False)

    import_map = import_tracker.parse_imports(file_info, content)
    assert "path" in import_map.by_name
    path_imp = import_map.by_name["path"]
    assert path_imp.is_standard_library

    assert "format_string" in import_map.by_name
    fmt_imp = import_map.by_name["format_string"]
    assert fmt_imp.is_relative
