"""
Unit tests for Week 2 Day 5: Feature 4 (Multi-File Review Context & Blast Radius).
Owner: Meet — W2-14

Tests cover:
    1. test_parse_diff_hunks
    2. test_calculate_blast_radius_isolated_low_risk
    3. test_calculate_blast_radius_multiple_callers_high_risk
    4. test_build_review_context_fair_token_allocation
    5. test_empty_modified_files_returns_missing_target
    6. test_base_head_revisions_preserved
    7. test_functional_build_multi_file_review_context_helper
    8. test_render_multi_file_review_context
"""

from __future__ import annotations

import pytest
from ai.context import (
    ContextBuilder,
    ContextLimits,
    ContextStatus,
    ModifiedFile,
    ReviewBlastRadius,
    ReviewContextBuilder,
    SymbolContext,
    build_multi_file_review_context,
)


class TestDay5ReviewContext:
    def test_parse_diff_hunks(self):
        diff = (
            "--- a/src/calc.py\n"
            "+++ b/src/calc.py\n"
            "@@ -10,4 +10,6 @@ def calculate():\n"
            "-    return a + b\n"
            "+    if not a: return 0\n"
            "+    return a + b\n"
            "@@ -25,2 +27,3 @@ def divide():\n"
            "+    # check div\n"
            "     return a / b\n"
        )
        hunks = ReviewContextBuilder.parse_diff_hunks(diff)
        assert len(hunks) == 2
        assert hunks[0][0] == 10  # start_line
        assert hunks[1][0] == 27

    def test_calculate_blast_radius_isolated_low_risk(self):
        mod_files = [ModifiedFile(file_path="src/isolated.py", content="x = 1")]
        # No cross-file callers
        blast = ReviewContextBuilder.calculate_blast_radius(mod_files, symbol_graph=[])
        assert blast.risk_level == "low"
        assert len(blast.affected_files) == 0

    def test_calculate_blast_radius_multiple_callers_high_risk(self):
        mod_files = [ModifiedFile(file_path="src/models/user.py", content="class User: pass")]
        # Callers in other downstream files
        callers = [
            SymbolContext(name="auth_user", kind="caller", file_path=f"src/api/auth_{i}.py", start_line=1, end_line=5)
            for i in range(5)
        ]
        blast = ReviewContextBuilder.calculate_blast_radius(mod_files, symbol_graph=callers)
        assert blast.risk_level == "high"
        assert len(blast.affected_files) == 5

    def test_build_review_context_fair_token_allocation(self):
        files = [
            ModifiedFile(
                file_path=f"src/file_{i}.py",
                change_type="modified",
                diff_hunks=["+ code change line " * 20],
            )
            for i in range(4)
        ]
        limits = ContextLimits(max_tokens=1000)
        ctx = build_multi_file_review_context(
            modified_files=files,
            base_revision="v1.0.0",
            head_revision="v1.1.0",
            limits=limits,
        )
        assert ctx.status in (ContextStatus.COMPLETE, ContextStatus.PARTIAL)
        assert ctx.total_tokens <= 1000
        assert "v1.0.0..v1.1.0" in ctx.target.revision

    def test_empty_modified_files_returns_missing_target(self):
        ctx = build_multi_file_review_context(modified_files=[])
        assert ctx.status == ContextStatus.MISSING_TARGET
        assert ctx.has_missing_context is True
        assert any("No modified files" in m.reason for m in ctx.missing_context)

    def test_base_head_revisions_preserved(self):
        mod = [ModifiedFile(file_path="a.py", diff_hunks=["+ test"])]
        ctx = build_multi_file_review_context(
            modified_files=mod,
            base_revision="abc",
            head_revision="def",
        )
        assert ctx.revision == "abc..def"

    def test_functional_build_multi_file_review_context_helper(self):
        mod = [ModifiedFile(file_path="b.py", content="hello")]
        ctx = build_multi_file_review_context(modified_files=mod)
        assert "b.py" in ctx.target.content

    def test_render_multi_file_review_context(self):
        mod = [ModifiedFile(file_path="pkg/core.py", diff_hunks=["@@ -1 +1 @@\n-old\n+new"])]
        ctx = build_multi_file_review_context(
            modified_files=mod,
            base_revision="main",
            head_revision="feature",
        )
        rendered = ContextBuilder().render_intelligence_data(ctx)
        assert "<<<REPO_DATA_START>>>" in rendered
        assert "pkg/core.py" in rendered
        assert "<<<REPO_DATA_END>>>" in rendered
