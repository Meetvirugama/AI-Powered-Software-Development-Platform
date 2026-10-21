"""
Unit tests for Week 2 Day 2: Context Enrichment for Feature 1 (Code Explanation).
Owner: Meet — W2-11

Tests cover:
    1. test_enrich_with_callers_and_imported_types
    2. test_extract_imports_python
    3. test_extract_imports_typescript
    4. test_generate_source_references
    5. test_leaf_function_records_missing_callers
    6. test_token_budget_bounds_explanation_context
    7. test_functional_enrich_explanation_context_helper
    8. test_render_enriched_explanation_context
"""

from __future__ import annotations

import pytest
from ai.context import (
    ContextBuilder,
    ContextLimits,
    ContextStatus,
    ExplanationContextEnricher,
    RepositoryFile,
    SymbolContext,
    TargetSnippet,
    enrich_explanation_context,
)


class TestDay2ExplanationContext:
    def test_enrich_with_callers_and_imported_types(self):
        enricher = ExplanationContextEnricher()
        target = TargetSnippet(
            file_path="backend/services/payment.py",
            content="def process_charge(amount: int, token: str) -> Charge:\n    return stripe.Charge.create(amount=amount, source=token)",
            start_line=20,
            end_line=25,
            symbol_name="process_charge",
            language="python",
        )
        callers = [
            SymbolContext(
                name="checkout_endpoint",
                kind="caller",
                file_path="backend/api/checkout.py",
                start_line=50,
                end_line=60,
                content="res = process_charge(cart.total, tok)",
            )
        ]
        imported_types = [
            SymbolContext(
                name="Charge",
                kind="type",
                file_path="backend/models/payment.py",
                start_line=5,
                end_line=15,
                content="class Charge(BaseModel): id: str; amount: int",
            )
        ]
        files = [
            RepositoryFile(id="1", path="backend/services/payment.py", language="python", size_bytes=500, line_count=40),
            RepositoryFile(id="2", path="backend/api/checkout.py", language="python", size_bytes=800, line_count=70),
        ]

        ctx = enricher.enrich_context(
            target=target,
            callers=callers,
            imported_types=imported_types,
            repository_files=files,
            token_budget=5000,
        )

        assert ctx.status == ContextStatus.COMPLETE
        assert len(ctx.related_symbols) == 2
        names = {s.name for s in ctx.related_symbols}
        assert "checkout_endpoint" in names
        assert "Charge" in names
        assert len(ctx.repository_files) == 2

    def test_extract_imports_python(self):
        source = (
            "import os\n"
            "from typing import Any, Optional\n"
            "from backend.models import User, Order\n"
            "# comment\n"
            "def foo():\n"
            "    pass\n"
        )
        imports = ExplanationContextEnricher.extract_imports(source, "python")
        assert "import os" in imports
        assert "from typing import Any, Optional" in imports
        assert "from backend.models import User, Order" in imports

    def test_extract_imports_typescript(self):
        source = (
            "import React, { useState } from 'react';\n"
            "import { Button } from '@/components/ui/button';\n"
            "const lodash = require('lodash');\n"
            "export const Component = () => null;\n"
        )
        imports = ExplanationContextEnricher.extract_imports(source, "typescript")
        assert "import React, { useState } from 'react';" in imports
        assert "import { Button } from '@/components/ui/button';" in imports
        assert "const lodash = require('lodash');" in imports

    def test_generate_source_references(self):
        target = TargetSnippet(file_path="app/main.py", content="x = 1", start_line=10, end_line=12)
        sym = SymbolContext(name="init_app", kind="caller", file_path="app/server.py", start_line=1, end_line=5)
        ctx = ContextBuilder().build_intelligence_context(target=target, related_symbols=[sym])
        refs = ExplanationContextEnricher.generate_source_references(ctx)
        assert "app/main.py:10-12" in refs
        assert "app/server.py:1-5 (caller:init_app)" in refs

    def test_leaf_function_records_missing_callers(self):
        enricher = ExplanationContextEnricher()
        target = TargetSnippet(
            file_path="utils/math.py",
            content="def add(a: int, b: int) -> int: return a + b",
            start_line=1,
            end_line=2,
            symbol_name="add",
            language="python",
        )
        ctx = enricher.enrich_context(target=target, callers=[])
        assert ctx.status == ContextStatus.PARTIAL
        assert len(ctx.missing_context) == 1
        assert "No callers found" in ctx.missing_context[0].reason

    def test_token_budget_bounds_explanation_context(self):
        enricher = ExplanationContextEnricher()
        target = TargetSnippet(
            file_path="core.py",
            content="def run(): pass",
            start_line=1,
            end_line=1,
            symbol_name="run",
        )
        callers = [
            SymbolContext(
                name=f"caller_{i}",
                kind="caller",
                file_path=f"caller_{i}.py",
                start_line=1,
                end_line=10,
                content="data " * 100,
            )
            for i in range(10)
        ]
        limits = ContextLimits(max_tokens=200, max_symbols=5)
        ctx = enricher.enrich_context(target=target, callers=callers, limits=limits)
        assert ctx.total_tokens <= 200
        assert len(ctx.related_symbols) <= 5
        assert ctx.has_missing_context is True

    def test_functional_enrich_explanation_context_helper(self):
        target = TargetSnippet(file_path="a.py", content="x = 1", start_line=1, end_line=1)
        ctx = enrich_explanation_context(target=target, token_budget=1000)
        assert ctx.target.file_path == "a.py"

    def test_render_enriched_explanation_context(self):
        target = TargetSnippet(
            file_path="backend/app.py",
            content="def bootstrap(): start()",
            start_line=10,
            end_line=15,
            symbol_name="bootstrap",
        )
        callers = [
            SymbolContext(name="main", kind="caller", file_path="backend/main.py", start_line=1, end_line=5)
        ]
        ctx = enrich_explanation_context(target=target, callers=callers)
        rendered = ContextBuilder().render_intelligence_data(ctx)
        assert "<<<REPO_DATA_START>>>" in rendered
        assert "bootstrap" in rendered
        assert "main" in rendered
        assert "<<<REPO_DATA_END>>>" in rendered
