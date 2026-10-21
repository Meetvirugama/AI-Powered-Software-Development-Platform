"""
Unit tests for Week 2 Day 4: Feature 3 (Framework-Aware Test Generation Context).
Owner: Meet — W2-13

Tests cover:
    1. test_infer_candidate_test_paths_pytest
    2. test_infer_candidate_test_paths_jest
    3. test_detect_mockable_calls_db_and_http
    4. test_build_test_context_with_fixtures_and_mocks
    5. test_build_test_context_with_sample_existing_test
    6. test_missing_test_file_records_candidate_notice
    7. test_source_revision_preserved_in_test_context
    8. test_token_bounding_on_test_context
"""

from __future__ import annotations

import pytest
from ai.context import (
    ContextLimits,
    ContextStatus,
    RepositoryFile,
    SymbolContext,
    TargetSnippet,
    TestContextBuilder,
    build_test_generation_context,
)


class TestDay4TestContext:
    def test_infer_candidate_test_paths_pytest(self):
        paths = TestContextBuilder.infer_candidate_test_paths("backend/app/services/auth.py", "pytest")
        assert "backend/app/services/test_auth.py" in paths
        assert "backend/tests/services/test_auth.py" in paths or "backend/tests/test_auth.py" in paths

    def test_infer_candidate_test_paths_jest(self):
        paths = TestContextBuilder.infer_candidate_test_paths("frontend/src/components/Header.tsx", "jest")
        assert "frontend/src/components/Header.test.tsx" in paths
        assert "src/__tests__/Header.test.ts" in paths

    def test_detect_mockable_calls_db_and_http(self):
        code = (
            "async def handle_checkout(cart_id: str):\n"
            "    user = db.query(User).filter_by(id=cart_id).first()\n"
            "    resp = await httpx.post('https://api.stripe.com/v1/charges')\n"
            "    redis.set(cart_id, 'processed')\n"
            "    return resp.json()\n"
        )
        mocks = TestContextBuilder.detect_mockable_calls(code)
        assert "db.query" in mocks
        assert "httpx.post" in mocks
        assert "redis.set" in mocks

    def test_build_test_context_with_fixtures_and_mocks(self):
        target = TargetSnippet(
            file_path="backend/app/auth.py",
            content="def hash_password(pwd: str) -> str: return bcrypt.hash(pwd)",
            start_line=10,
            end_line=12,
            symbol_name="hash_password",
            language="python",
            revision="git@commit123",
        )
        mock_dep = SymbolContext(
            name="bcrypt",
            kind="dependency",
            file_path="external/bcrypt",
            start_line=1,
            end_line=1,
            content="class bcrypt: def hash(pwd): pass",
        )
        fixtures = ["db_session: yields clean test database session", "test_user: User(id=1)"]

        ctx = build_test_generation_context(
            target=target,
            framework="pytest",
            mockable_dependencies=[mock_dep],
            fixture_definitions=fixtures,
            token_budget=5000,
        )

        assert ctx.status == ContextStatus.PARTIAL  # no pre-existing test file notice
        assert ctx.revision == "git@commit123"
        assert len(ctx.related_symbols) == 1
        assert ctx.related_symbols[0].name == "bcrypt"
        rules_text = " ".join(ctx.project_rules)
        assert "Configured Test Framework: pytest" in rules_text
        assert "db_session" in rules_text

    def test_build_test_context_with_sample_existing_test(self):
        target = TargetSnippet(file_path="src/calc.py", content="def add(a, b): return a + b", start_line=1, end_line=1)
        existing_test = "def test_subtract(): assert subtract(4, 2) == 2"

        ctx = build_test_generation_context(
            target=target,
            framework="pytest",
            sample_test_code=existing_test,
        )

        assert any(s.name == "existing_test_pattern" for s in ctx.related_symbols)

    def test_missing_test_file_records_candidate_notice(self):
        target = TargetSnippet(file_path="app/invoice.py", content="def calc(): pass", start_line=1, end_line=1)
        ctx = build_test_generation_context(target=target, existing_test_files=[])
        assert ctx.has_missing_context is True
        assert any("No pre-existing test file found" in m.reason for m in ctx.missing_context)

    def test_source_revision_preserved_in_test_context(self):
        target = TargetSnippet(file_path="x.py", content="pass", start_line=1, end_line=1, revision="rev-456")
        ctx = build_test_generation_context(target=target)
        assert ctx.revision == "rev-456"

    def test_token_bounding_on_test_context(self):
        target = TargetSnippet(file_path="x.py", content="pass", start_line=1, end_line=1)
        deps = [
            SymbolContext(name=f"dep_{i}", kind="service", file_path="d.py", start_line=1, end_line=1, content="mock " * 100)
            for i in range(10)
        ]
        limits = ContextLimits(max_tokens=150)
        ctx = build_test_generation_context(target=target, mockable_dependencies=deps, limits=limits)
        assert ctx.total_tokens <= 150
        assert len(ctx.related_symbols) < 10
