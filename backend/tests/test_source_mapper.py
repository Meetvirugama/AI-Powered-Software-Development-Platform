"""Unit and integration tests for Prit — Week 2 Day 5: Review Source Mapping.

Deliverable: Review source-mapping integration.

Covers:
1. Resolve changed lines to available source ranges and symbols.
2. Supply AST context when supported (syntactic node types, scopes, AST rules).
3. Preserve file identity and line locations (inclusive bounds, renames, revisions).
4. Report mapping limitations explicitly (unsupported languages, module-level lines,
   deleted/binary files, syntax errors, line out of bounds).
5. Downstream integrations with AnalysisSourceReference and ModifiedFile.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import pytest

from scanner.source_mapper import (
    FileSourceMapping,
    HunkASTContext,
    HunkMapping,
    MappingLimitation,
    ReviewSourceMapper,
    ReviewSourceMapResult,
    SymbolSummary,
)
from scanner.symbols import SourceRange

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "ast_sample"


@pytest.fixture
def mapper() -> ReviewSourceMapper:
    return ReviewSourceMapper()


@pytest.fixture
def python_content() -> str:
    path = FIXTURES_DIR / "supported_python.py"
    return path.read_text(encoding="utf-8")


@pytest.fixture
def defect_python_content() -> str:
    path = FIXTURES_DIR / "defect_sample.py"
    return path.read_text(encoding="utf-8")


@pytest.fixture
def typescript_content() -> str:
    path = FIXTURES_DIR / "supported_typescript.ts"
    return path.read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════
# 1. Diff Parsing Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestDiffParsing:
    def test_parse_unified_diff_single_file(self, mapper: ReviewSourceMapper):
        diff = (
            "--- a/backend/calculator.py\n"
            "+++ b/backend/calculator.py\n"
            "@@ -10,4 +10,6 @@ def add(a, b):\n"
            "     # existing context\n"
            "-    return a + b\n"
            "+    if not a: return 0\n"
            "+    return a + b\n"
        )
        raw_files = mapper.parse_unified_diff(diff)
        assert len(raw_files) == 1
        rf = raw_files[0]
        assert rf.old_path == "backend/calculator.py"
        assert rf.new_path == "backend/calculator.py"
        assert len(rf.hunks) == 1
        h = rf.hunks[0]
        assert h.old_start == 10
        assert h.old_count == 4
        assert h.new_start == 10
        assert h.new_count == 6
        assert 11 in h.added_line_numbers
        assert 12 in h.added_line_numbers

    def test_parse_unified_diff_multi_file_with_modes(self, mapper: ReviewSourceMapper):
        diff = (
            "diff --git a/src/new_mod.py b/src/new_mod.py\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/src/new_mod.py\n"
            "@@ -0,0 +1,5 @@\n"
            "+def init():\n"
            "+    pass\n"
            "diff --git a/docs/old.md b/docs/old.md\n"
            "deleted file mode 100644\n"
            "--- a/docs/old.md\n"
            "+++ /dev/null\n"
            "@@ -1,2 +0,0 @@\n"
            "-old doc\n"
            "diff --git a/data/bin.dat b/data/bin.dat\n"
            "Binary files a/data/bin.dat and b/data/bin.dat differ\n"
        )
        raw_files = mapper.parse_unified_diff(diff)
        assert len(raw_files) == 3

        f1 = raw_files[0]
        assert f1.new_path == "src/new_mod.py"
        assert f1.change_type == "added"
        assert f1.old_path is None

        f2 = raw_files[1]
        assert f2.old_path == "docs/old.md"
        assert f2.change_type == "deleted"
        assert f2.new_path is None

        f3 = raw_files[2]
        assert f3.new_path == "data/bin.dat"
        assert f3.is_binary is True

    def test_parse_empty_or_whitespace_diff(self, mapper: ReviewSourceMapper):
        assert mapper.parse_unified_diff("") == []
        assert mapper.parse_unified_diff("   \n\n  ") == []


# ═══════════════════════════════════════════════════════════════════════════
# 2. Source Range & Symbol Resolution Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestSourceRangeAndSymbolResolution:
    def test_map_changes_inside_function_symbol(
        self, mapper: ReviewSourceMapper, python_content: str
    ):
        """Line modified inside calculate_tax resolves to function and its range."""
        # calculate_tax in supported_python.py is lines 23..27
        res = mapper.map_file_changes(
            file_path="supported_python.py",
            content=python_content,
            modified_ranges=[(24, 25)],
        )
        assert res.file_path == "supported_python.py"
        assert res.is_supported is True
        assert len(res.hunks) == 1
        h = res.hunks[0]
        assert h.change_scope == "inside_symbol"
        assert h.enclosing_symbol is not None
        assert h.enclosing_symbol.name == "calculate_tax"
        assert h.enclosing_symbol.kind == "function"
        assert h.symbol_range is not None
        assert h.symbol_range.start_line == 23
        assert h.symbol_range.end_line == 27
        assert len(res.affected_symbols) >= 1
        assert any(s.name == "calculate_tax" for s in res.affected_symbols)

    def test_map_changes_inside_method_qualified_name(
        self, mapper: ReviewSourceMapper, python_content: str
    ):
        """Method change inside AccountManager resolves qualified name AccountManager.update_role."""
        # AccountManager class in supported_python.py has update_role at lines 17..20
        res = mapper.map_file_changes(
            file_path="supported_python.py",
            content=python_content,
            modified_ranges=[(18, 19)],
        )
        assert len(res.hunks) == 1
        h = res.hunks[0]
        assert h.enclosing_symbol is not None
        assert h.enclosing_symbol.name == "update_role"
        assert h.enclosing_symbol.kind == "method"
        assert h.enclosing_class == "AccountManager"
        assert h.qualified_symbol_name == "AccountManager.update_role"
        assert h.symbol_range is not None
        assert h.symbol_range.start_line == 17
        assert h.symbol_range.end_line == 20

    def test_map_signature_change_scope(
        self, mapper: ReviewSourceMapper, python_content: str
    ):
        """Modifying the exact declaration line flags change_scope as signature_change."""
        # Line 23 is 'def calculate_tax(amount: float, rate: float = 0.1) -> float:'
        res = mapper.map_file_changes(
            file_path="supported_python.py",
            content=python_content,
            modified_ranges=[(23, 23)],
        )
        assert len(res.hunks) == 1
        h = res.hunks[0]
        assert h.change_scope == "signature_change"
        assert h.enclosing_symbol is not None
        assert h.enclosing_symbol.name == "calculate_tax"

    def test_map_changes_spanning_multiple_symbols(
        self, mapper: ReviewSourceMapper, python_content: str
    ):
        """Hunk spanning across two functions sets change_scope to spans_symbols."""
        # calculate_tax (23..27) and fetch_user_data (30..32)
        res = mapper.map_file_changes(
            file_path="supported_python.py",
            content=python_content,
            modified_ranges=[(26, 31)],
        )
        assert len(res.hunks) == 1
        h = res.hunks[0]
        assert h.change_scope == "spans_symbols"
        assert len(h.overlapping_symbols) >= 2
        overlap_names = {s.name for s in h.overlapping_symbols}
        assert "calculate_tax" in overlap_names
        assert "fetch_user_data" in overlap_names

    def test_map_line_to_symbol_helper(
        self, mapper: ReviewSourceMapper, python_content: str
    ):
        """Single line mapping helper returns symbol summary and source range."""
        sym, s_range, limitations = mapper.map_line_to_symbol(
            file_path="supported_python.py",
            line_number=24,
            content=python_content,
        )
        assert sym is not None
        assert sym.name == "calculate_tax"
        assert s_range is not None
        assert s_range.start_line == 23
        assert s_range.end_line == 27
        assert limitations == []


# ═══════════════════════════════════════════════════════════════════════════
# 3. AST Context & Structural Defect Integration Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestASTContextEnrichment:
    def test_ast_context_extracts_node_types_and_scopes(
        self, mapper: ReviewSourceMapper, python_content: str
    ):
        """HunkASTContext provides syntactic node types, scope path, and snippet."""
        ast_ctx = mapper.supply_ast_context(
            content=python_content,
            language="Python",
            start_line=17,
            end_line=20,
            file_path="supported_python.py",
        )
        assert isinstance(ast_ctx, HunkASTContext)
        assert "FunctionDef" in ast_ctx.node_types
        assert "module" in ast_ctx.scope_path
        assert "AccountManager" in ast_ctx.scope_path
        assert "update_role" in ast_ctx.scope_path
        assert "update_role" in (ast_ctx.surrounding_snippet or "")

    def test_ast_context_detects_structural_defects_on_changed_lines(
        self, mapper: ReviewSourceMapper, defect_python_content: str
    ):
        """Review mapping evaluates ASTBugAnalyzer specifically on changed line bounds."""
        # defect_sample.py has unclosed file open (AST-RES-001) at lines 19..23
        res = mapper.map_file_changes(
            file_path="defect_sample.py",
            content=defect_python_content,
            modified_ranges=[(19, 23)],
        )
        assert len(res.hunks) == 1
        h = res.hunks[0]
        assert h.ast_context is not None
        rule_ids = {d["rule_id"] for d in h.ast_context.structural_defects}
        assert "AST-RES-001" in rule_ids

    def test_ast_context_syntax_error_detection(self, mapper: ReviewSourceMapper):
        malformed = "def broken(\n    return 1"
        ast_ctx = mapper.supply_ast_context(
            content=malformed,
            language="Python",
            start_line=1,
            end_line=2,
        )
        assert ast_ctx.has_syntax_errors is True
        assert ast_ctx.syntax_error_message is not None


# ═══════════════════════════════════════════════════════════════════════════
# 4. Explicit Mapping Limitations & Error Handling
# ═══════════════════════════════════════════════════════════════════════════


class TestMappingLimitations:
    def test_module_level_code_limitation(
        self, mapper: ReviewSourceMapper, python_content: str
    ):
        """Lines at top of file (imports) produce MODULE_LEVEL_CODE limitation."""
        # Lines 1..5 in supported_python.py are imports and constants
        res = mapper.map_file_changes(
            file_path="supported_python.py",
            content=python_content,
            modified_ranges=[(1, 4)],
        )
        assert len(res.hunks) == 1
        h = res.hunks[0]
        assert h.change_scope == "module_level"
        assert h.enclosing_symbol is None
        assert any(l.limitation_type == "MODULE_LEVEL_CODE" for l in h.limitations)

    def test_unsupported_language_limitation(self, mapper: ReviewSourceMapper):
        """Unsupported languages preserve file identity and lines with UNSUPPORTED_LANGUAGE limitation."""
        content = "title: Documentation\nversion: 1.0\n"
        res = mapper.map_file_changes(
            file_path="config.yaml",
            content=content,
            modified_ranges=[(1, 2)],
        )
        assert res.file_path == "config.yaml"
        assert res.is_supported is False
        assert any(l.limitation_type == "UNSUPPORTED_LANGUAGE" for l in res.limitations)
        assert len(res.hunks) == 1
        assert res.hunks[0].new_start_line == 1

    def test_deleted_file_limitation(self, mapper: ReviewSourceMapper):
        """Deleted file records FILE_DELETED limitation."""
        res = mapper.map_file_changes(
            file_path="legacy.py",
            content="",
            change_type="deleted",
        )
        assert res.change_type == "deleted"
        assert any(l.limitation_type == "FILE_DELETED" for l in res.limitations)

    def test_line_out_of_bounds_limitation(
        self, mapper: ReviewSourceMapper, python_content: str
    ):
        """Hunk exceeding total file length records LINE_OUT_OF_BOUNDS limitation."""
        total = len(python_content.splitlines())
        res = mapper.map_file_changes(
            file_path="supported_python.py",
            content=python_content,
            modified_ranges=[(total + 50, total + 60)],
        )
        h = res.hunks[0]
        assert any(l.limitation_type == "LINE_OUT_OF_BOUNDS" for l in h.limitations)

    def test_syntax_error_file_limitation(self, mapper: ReviewSourceMapper):
        """Partial syntax error file sets has_syntax_errors and SYNTAX_ERROR limitation."""
        malformed = (
            "def valid_one():\n"
            "    return True\n"
            "def broken(\n"
            "    # unclosed syntax\n"
        )
        res = mapper.map_file_changes(
            file_path="malformed.py",
            content=malformed,
            modified_ranges=[(1, 2)],
        )
        assert res.has_syntax_errors is True
        assert any(l.limitation_type == "SYNTAX_ERROR" for l in res.limitations)


# ═══════════════════════════════════════════════════════════════════════════
# 5. Full End-to-End Unified Diff Mapping & Conversions
# ═══════════════════════════════════════════════════════════════════════════


class TestEndToEndMappingAndConversions:
    def test_map_unified_diff_with_virtual_files(
        self, mapper: ReviewSourceMapper, python_content: str
    ):
        diff = (
            "diff --git a/supported_python.py b/supported_python.py\n"
            "--- a/supported_python.py\n"
            "+++ b/supported_python.py\n"
            "@@ -24,3 +24,4 @@ def calculate_tax():\n"
            "     # context\n"
            "+    if amount < 0: raise ValueError()\n"
            "     return amount * rate\n"
        )
        result = mapper.map_unified_diff(
            diff_text=diff,
            repo_files={"supported_python.py": python_content},
            base_revision="c1",
            head_revision="c2",
            commit_sha="a1b2c3d4",
        )
        assert result.success is True
        assert result.total_files == 1
        assert result.total_hunks == 1
        assert result.commit_sha == "a1b2c3d4"
        assert result.base_revision == "c1"
        assert result.head_revision == "c2"

        fm = result.files[0]
        assert fm.file_path == "supported_python.py"
        assert fm.hunks[0].enclosing_symbol.name == "calculate_tax"

        # Check serialization
        d = result.to_dict()
        assert d["total_files"] == 1
        assert d["files"][0]["file_path"] == "supported_python.py"

    def test_to_source_references_conversion(
        self, mapper: ReviewSourceMapper, python_content: str
    ):
        """Converts into AnalysisSourceReference format with inclusive lines."""
        diff = (
            "--- a/supported_python.py\n"
            "+++ b/supported_python.py\n"
            "@@ -10,3 +10,4 @@\n"
            "+# added comment\n"
        )
        result = mapper.map_unified_diff(
            diff_text=diff,
            repo_files={"supported_python.py": python_content},
            head_revision="main_rev",
        )
        refs = result.to_source_references()
        assert len(refs) == 1
        ref = refs[0]
        assert ref.file_path == "supported_python.py"
        assert ref.start_line == 10
        assert ref.end_line >= 10
        assert ref.revision == "main_rev"

    def test_to_modified_files_conversion(
        self, mapper: ReviewSourceMapper, python_content: str
    ):
        """Converts directly into Meet's ModifiedFile dataclass for review context."""
        diff = (
            "--- a/supported_python.py\n"
            "+++ b/supported_python.py\n"
            "@@ -10,3 +10,4 @@\n"
            "+# added line\n"
        )
        result = mapper.map_unified_diff(
            diff_text=diff,
            repo_files={"supported_python.py": python_content},
        )
        mod_files = result.to_modified_files()
        assert len(mod_files) == 1
        mf = mod_files[0]
        assert mf.file_path == "supported_python.py"
        assert mf.change_type == "modified"
        assert len(mf.modified_line_ranges) >= 1

    def test_map_commit_changes_helper(
        self, mapper: ReviewSourceMapper, python_content: str
    ):
        """Integrates with Parth's CommitFileChange format."""
        patch = (
            "@@ -23,4 +23,5 @@\n"
            "+        # audit log\n"
            "         return user\n"
        )
        commit_files = [
            {"filename": "supported_python.py", "patch": patch, "status": "modified"}
        ]
        result = mapper.map_commit_changes(
            commit_files=commit_files,
            repo_files={"supported_python.py": python_content},
            commit_sha="c123456",
        )
        assert result.success is True
        assert result.total_files == 1
        assert result.files[0].hunks[0].enclosing_symbol.name == "calculate_tax"

    def test_typescript_mapping(
        self, mapper: ReviewSourceMapper, typescript_content: str
    ):
        """Resolves symbols in TypeScript files using tree-sitter."""
        diff = (
            "--- a/app.ts\n"
            "+++ b/app.ts\n"
            "@@ -8,3 +8,4 @@\n"
            "+    console.log(data);\n"
        )
        result = mapper.map_unified_diff(
            diff_text=diff,
            repo_files={"app.ts": typescript_content},
        )
        assert result.success is True
        assert len(result.files) == 1
        fm = result.files[0]
        assert fm.is_supported is True
        assert len(fm.hunks) == 1
