"""Week 2 Day 2 — Target Selector & Symbol Resolution Tests.

Owner: Prit — Repository Engine Lead (W2-Day2)
Verifies:
1. Target selector connection to AST and source location utilities.
2. Function and class resolution to exact 1-indexed inclusive source ranges.
3. Ambiguous symbol resolution and disambiguation heuristics.
4. Consistent line range interpretation and enclosing scope detection.
5. Parse failure resilience, syntax error warnings, and unsupported language contracts.
6. TargetSnippet conversion for Meet's IntelligenceContext.
"""

from __future__ import annotations

from pathlib import Path
import pytest

from backend.scanner.detector import LanguageDetector
from backend.scanner.extractor import SymbolExtractor
from backend.scanner.parser import Parser
from backend.scanner.source_location import SourceLocationResolver
from backend.scanner.target_selector import TargetSelectionResult, TargetSelector

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
def selector(
    parser: Parser,
    extractor: SymbolExtractor,
    resolver: SourceLocationResolver,
) -> TargetSelector:
    return TargetSelector(parser=parser, extractor=extractor, resolver=resolver)


# ---------------------------------------------------------------------------
# 1. Whole File Target Selection Tests
# ---------------------------------------------------------------------------


def test_select_target_whole_file(selector: TargetSelector):
    """Target selection with type='file' selects full content and discovers child symbols."""
    file_path = FIXTURES_DIR / "supported_python.py"
    content = file_path.read_text(encoding="utf-8")

    result = selector.select_target(
        file_path="supported_python.py",
        content=content,
        target_type="file",
        language="Python",
    )

    assert result.success
    assert result.target_type == "file"
    assert result.start_line == 1
    assert result.end_line == result.total_file_lines
    assert len(result.child_symbols) > 0
    assert "AccountManager" in [s.name for s in result.child_symbols]


# ---------------------------------------------------------------------------
# 2. Function and Class Symbol Resolution Tests
# ---------------------------------------------------------------------------


def test_resolve_function_symbol(selector: TargetSelector):
    """Resolving a top-level function yields exact start and end line ranges and snippet."""
    file_path = FIXTURES_DIR / "supported_python.py"
    content = file_path.read_text(encoding="utf-8")

    result = selector.select_target(
        file_path="supported_python.py",
        content=content,
        target_type="symbol",
        symbol_name="calculate_tax",
        language="Python",
    )

    assert result.success
    assert result.target_type == "symbol"
    assert result.symbol_name == "calculate_tax"
    assert result.symbol_kind == "function"
    assert result.start_line == 23
    assert result.end_line == 27
    assert "def calculate_tax(amount: float, rate: float = 0.1) -> float:" in result.content
    assert "return amount * rate" in result.content


def test_resolve_class_symbol(selector: TargetSelector):
    """Resolving a class yields its full range and lists its member methods as child symbols."""
    file_path = FIXTURES_DIR / "supported_python.py"
    content = file_path.read_text(encoding="utf-8")

    result = selector.select_target(
        file_path="supported_python.py",
        content=content,
        target_type="symbol",
        symbol_name="AccountManager",
        language="Python",
    )

    assert result.success
    assert result.target_type == "symbol"
    assert result.symbol_name == "AccountManager"
    assert result.symbol_kind == "class"
    assert result.start_line == 8
    assert result.end_line == 20
    assert "class AccountManager:" in result.content

    # Child methods
    child_names = [c.name for c in result.child_symbols]
    assert "get_display_name" in child_names
    assert "update_role" in child_names


def test_resolve_qualified_method_symbol(selector: TargetSelector):
    """Qualified name 'Class.method' resolves the method and identifies its enclosing class."""
    file_path = FIXTURES_DIR / "supported_python.py"
    content = file_path.read_text(encoding="utf-8")

    result = selector.select_target(
        file_path="supported_python.py",
        content=content,
        target_type="symbol",
        symbol_name="AccountManager.get_display_name",
        language="Python",
    )

    assert result.success
    assert result.symbol_name == "get_display_name"
    assert result.symbol_kind == "method"
    assert result.start_line == 14
    assert result.end_line == 15
    assert result.enclosing_symbol is not None
    assert result.enclosing_symbol.name == "AccountManager"


# ---------------------------------------------------------------------------
# 3. Ambiguous Symbol Resolution & Disambiguation Tests
# ---------------------------------------------------------------------------


def test_ambiguous_symbol_detection_without_hint(selector: TargetSelector):
    """When a symbol name exists in multiple scopes without qualification, detects ambiguity."""
    file_path = FIXTURES_DIR / "ambiguous_sample.py"
    content = file_path.read_text(encoding="utf-8")

    result = selector.select_target(
        file_path="ambiguous_sample.py",
        content=content,
        target_type="symbol",
        symbol_name="format_data",
        language="Python",
    )

    assert result.success
    assert result.is_ambiguous
    assert len(result.candidates) == 3
    assert result.ambiguity_note is not None
    assert "3 definitions found" in result.ambiguity_note
    # Defaults to top-level definition
    assert result.start_line == 3
    assert "Top-level format_data function." in result.content


def test_ambiguous_symbol_disambiguation_by_qualified_name(selector: TargetSelector):
    """Qualified names cleanly disambiguate between multiple definitions."""
    file_path = FIXTURES_DIR / "ambiguous_sample.py"
    content = file_path.read_text(encoding="utf-8")

    # Target PrimaryProcessor.format_data
    res_primary = selector.select_target(
        file_path="ambiguous_sample.py",
        content=content,
        target_type="symbol",
        symbol_name="PrimaryProcessor.format_data",
        language="Python",
    )
    assert res_primary.success
    assert res_primary.enclosing_symbol is not None
    assert res_primary.enclosing_symbol.name == "PrimaryProcessor"
    assert "Method format_data in PrimaryProcessor." in res_primary.content

    # Target SecondaryProcessor.format_data
    res_secondary = selector.select_target(
        file_path="ambiguous_sample.py",
        content=content,
        target_type="symbol",
        symbol_name="SecondaryProcessor.format_data",
        language="Python",
    )
    assert res_secondary.success
    assert res_secondary.enclosing_symbol is not None
    assert res_secondary.enclosing_symbol.name == "SecondaryProcessor"
    assert "Method format_data in SecondaryProcessor." in res_secondary.content


def test_ambiguous_symbol_disambiguation_by_cursor_proximity(selector: TargetSelector):
    """Providing cursor_line selects the candidate definition enclosing or nearest to the cursor."""
    file_path = FIXTURES_DIR / "ambiguous_sample.py"
    content = file_path.read_text(encoding="utf-8")

    # Cursor at line 15 is inside PrimaryProcessor.format_data
    result = selector.select_target(
        file_path="ambiguous_sample.py",
        content=content,
        target_type="symbol",
        symbol_name="format_data",
        cursor_line=15,
        language="Python",
    )

    assert result.success
    assert result.is_ambiguous
    assert result.enclosing_symbol is not None
    assert result.enclosing_symbol.name == "PrimaryProcessor"
    assert "Method format_data in PrimaryProcessor." in result.content
    assert "enclosing line 15" in (result.ambiguity_note or "")


# ---------------------------------------------------------------------------
# 4. Consistent Line Range Interpretation Tests
# ---------------------------------------------------------------------------


def test_range_selection_with_enclosing_symbol(selector: TargetSelector):
    """Range selection safely clamps lines and identifies enclosing callable/class."""
    file_path = FIXTURES_DIR / "supported_python.py"
    content = file_path.read_text(encoding="utf-8")

    # Lines 14..15 is get_display_name method
    result = selector.select_target(
        file_path="supported_python.py",
        content=content,
        target_type="range",
        start_line=14,
        end_line=15,
        language="Python",
    )

    assert result.success
    assert result.target_type == "range"
    assert result.start_line == 14
    assert result.end_line == 15
    assert result.symbol_name == "get_display_name"
    assert result.symbol_kind == "method"


def test_range_selection_exact_function_match(selector: TargetSelector):
    """When a range exactly matches a function declaration, it is detected as that function."""
    file_path = FIXTURES_DIR / "supported_python.py"
    content = file_path.read_text(encoding="utf-8")

    result = selector.select_target(
        file_path="supported_python.py",
        content=content,
        target_type="range",
        start_line=23,
        end_line=27,
        language="Python",
    )

    assert result.success
    assert result.symbol_name == "calculate_tax"
    assert result.symbol_kind == "function"


def test_range_selection_out_of_bounds_rejection(selector: TargetSelector):
    """Start line beyond total lines returns LINE_OUT_OF_BOUNDS error."""
    file_path = FIXTURES_DIR / "supported_python.py"
    content = file_path.read_text(encoding="utf-8")

    result = selector.select_target(
        file_path="supported_python.py",
        content=content,
        target_type="range",
        start_line=500,
        end_line=600,
        language="Python",
    )

    assert not result.success
    assert result.error_code == "LINE_OUT_OF_BOUNDS"


# ---------------------------------------------------------------------------
# 5. Parse Failure & Error Resilience Tests
# ---------------------------------------------------------------------------


def test_syntax_error_resilience(selector: TargetSelector):
    """File with syntax errors marks has_syntax_errors=True but resolves clean symbols."""
    file_path = FIXTURES_DIR / "malformed_syntax.py"
    content = file_path.read_text(encoding="utf-8")

    result = selector.select_target(
        file_path="malformed_syntax.py",
        content=content,
        target_type="symbol",
        symbol_name="ValidClassAfterError",
        language="Python",
    )

    assert result.success
    assert result.has_syntax_errors
    assert result.parse_status == "SYNTAX_WARNING"
    assert result.symbol_name == "ValidClassAfterError"
    assert result.symbol_kind == "class"


def test_unsupported_language_contract(selector: TargetSelector):
    """Unsupported language produces explicit UNSUPPORTED_LANGUAGE error for symbol selection."""
    file_path = FIXTURES_DIR / "unsupported_lang.xyz"
    content = file_path.read_text(encoding="utf-8")

    result = selector.select_target(
        file_path="unsupported_lang.xyz",
        content=content,
        target_type="symbol",
        symbol_name="main",
        language="UnsupportedXYZ",
    )

    assert not result.success
    assert not result.is_supported
    assert result.error_code == "UNSUPPORTED_LANGUAGE"


def test_nonexistent_symbol_with_suggestion(selector: TargetSelector):
    """Non-existent symbol returns explicit SYMBOL_NOT_FOUND and case-insensitive suggestion."""
    file_path = FIXTURES_DIR / "supported_python.py"
    content = file_path.read_text(encoding="utf-8")

    result = selector.select_target(
        file_path="supported_python.py",
        content=content,
        target_type="symbol",
        symbol_name="accountmanager",  # lowercase of AccountManager
        language="Python",
    )

    assert not result.success
    assert result.error_code == "SYMBOL_NOT_FOUND"
    assert "Did you mean 'AccountManager'?" in (result.error_message or "")


# ---------------------------------------------------------------------------
# 6. TargetSnippet Conversion Test (Meet's IntelligenceContext Contract)
# ---------------------------------------------------------------------------


def test_to_target_snippet_conversion(selector: TargetSelector):
    """TargetSelectionResult converts into TargetSnippet for developer intelligence features."""
    file_path = FIXTURES_DIR / "supported_python.py"
    content = file_path.read_text(encoding="utf-8")

    result = selector.select_target(
        file_path="supported_python.py",
        content=content,
        symbol_name="calculate_tax",
        language="Python",
    )

    snippet_obj = result.to_target_snippet(language="python")
    assert snippet_obj.file_path == "supported_python.py"
    assert snippet_obj.symbol_name == "calculate_tax"
    assert snippet_obj.start_line == 23
    assert snippet_obj.end_line == 27
    assert "def calculate_tax" in snippet_obj.content
