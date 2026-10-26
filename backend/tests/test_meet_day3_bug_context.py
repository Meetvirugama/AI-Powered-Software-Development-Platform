"""
Unit tests for Week 2 Day 3: Feature 2 (Dedicated Bug Detection Context).
Owner: Meet — W2-12

Tests cover:
    1. test_extract_bug_context_with_caller_sites_and_types
    2. test_extract_error_handling_blocks_python
    3. test_extract_error_handling_blocks_typescript
    4. test_detect_external_library_calls
    5. test_external_library_adds_missing_context_notice
    6. test_zero_callers_flags_warning_in_missing_context
    7. test_token_bounding_on_bug_context
    8. test_functional_extract_bug_context_helper
"""

from __future__ import annotations

import pytest
from ai.context import (
    BugContextExtractor,
    ContextBuilder,
    ContextLimits,
    ContextStatus,
    SymbolContext,
    TargetSnippet,
    extract_bug_context,
)


class TestDay3BugContext:
    def test_extract_bug_context_with_caller_sites_and_types(self):
        extractor = BugContextExtractor()
        target = TargetSnippet(
            file_path="backend/services/order.py",
            content="def calc_discount(total: float, code: str) -> float:\n    return total * COUPONS[code]",
            start_line=30,
            end_line=32,
            symbol_name="calc_discount",
            language="python",
        )
        callers = [
            SymbolContext(
                name="apply_coupon_endpoint",
                kind="caller",
                file_path="backend/api/order.py",
                start_line=10,
                end_line=20,
                content="disc = calc_discount(cart.total, payload.code)",
            )
        ]
        types = [
            SymbolContext(
                name="OrderPayload",
                kind="type",
                file_path="backend/schemas/order.py",
                start_line=1,
                end_line=10,
                content="class OrderPayload(BaseModel): total: float; code: str",
            )
        ]

        ctx = extractor.extract_context(
            target=target,
            caller_sites=callers,
            related_types=types,
            token_budget=5000,
        )

        assert len(ctx.related_symbols) == 2
        names = {s.name for s in ctx.related_symbols}
        assert "apply_coupon_endpoint" in names
        assert "OrderPayload" in names
        assert ctx.total_tokens > 0

    def test_extract_error_handling_blocks_python(self):
        source = (
            "def outer():\n"
            "    try:\n"
            "        val = risky()\n"
            "    except ValueError:\n"
            "        val = 0\n"
            "    if val is None:\n"
            "        return False\n"
        )
        guards = BugContextExtractor.extract_error_handling_blocks(source, 1, 7, "python")
        assert any("try:" in g and "except" in g for g in guards)
        assert any("if val is None:" in g for g in guards)

    def test_extract_error_handling_blocks_typescript(self):
        source = (
            "function outer() {\n"
            "    try { risky(); } catch (err) { handleError(err); }\n"
            "    if (!user) { return; }\n"
            "}\n"
        )
        guards = BugContextExtractor.extract_error_handling_blocks(source, 1, 4, "typescript")
        assert any("try" in g and "catch" in g for g in guards)
        assert any("if (!user)" in g for g in guards)

    def test_detect_external_library_calls(self):
        code = (
            "def process():\n"
            "    resp = stripe.PaymentIntent.create(amount=100)\n"
            "    cache = redis_client.get('key')\n"
            "    logger.info('done')\n"
        )
        calls = BugContextExtractor.extract_external_calls(code)
        assert "stripe" in calls
        assert "redis_client" in calls
        assert "logger" not in calls  # filtered out standard builtin

    def test_external_library_adds_missing_context_notice(self):
        target = TargetSnippet(
            file_path="src/billing.py",
            content="def charge(): return stripe.Charge.create()",
            start_line=1,
            end_line=2,
            symbol_name="charge",
        )
        ctx = extract_bug_context(target=target, caller_sites=[])
        assert ctx.status == ContextStatus.PARTIAL
        assert any("stripe" in m.reason for m in ctx.missing_context)

    def test_zero_callers_flags_warning_in_missing_context(self):
        target = TargetSnippet(
            file_path="src/parser.py",
            content="def parse(): pass",
            start_line=1,
            end_line=1,
            symbol_name="parse",
        )
        ctx = extract_bug_context(target=target, caller_sites=[])
        assert any("Zero caller sites" in m.reason for m in ctx.missing_context)

    def test_token_bounding_on_bug_context(self):
        target = TargetSnippet(file_path="a.py", content="x = 1", start_line=1, end_line=1)
        callers = [
            SymbolContext(name=f"c_{i}", kind="caller", file_path="c.py", start_line=1, end_line=5, content="pad " * 50)
            for i in range(10)
        ]
        limits = ContextLimits(max_tokens=100)
        ctx = extract_bug_context(target=target, caller_sites=callers, limits=limits)
        assert ctx.total_tokens <= 100
        assert ctx.has_missing_context is True

    def test_functional_extract_bug_context_helper(self):
        target = TargetSnippet(file_path="x.py", content="pass", start_line=1, end_line=1)
        ctx = extract_bug_context(target=target)
        assert ctx.target.file_path == "x.py"
