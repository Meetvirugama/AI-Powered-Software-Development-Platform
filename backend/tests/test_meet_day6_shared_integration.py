"""
Unit tests for Week 2 Day 6: Shared Intelligence Integration & Hardening.
Owner: Meet — W2-15

Tests cover:
    1. test_unified_facade_all_four_features
    2. test_context_caching_and_hit_rate
    3. test_cache_invalidation_on_revision_mismatch
    4. test_cache_ttl_expiration
    5. test_lru_cache_eviction_when_full
    6. test_provider_policy_allows_gemini_and_groq
    7. test_provider_policy_rejects_unauthorized_providers
    8. test_revision_consistency_verification
"""

from __future__ import annotations

import time
import pytest
from ai.context import (
    ALLOWED_AI_PROVIDERS,
    ContextLimits,
    ModifiedFile,
    RepositoryContextService,
    SymbolContext,
    TargetSnippet,
)


class TestDay6SharedIntegration:
    def test_unified_facade_all_four_features(self):
        service = RepositoryContextService()
        target = TargetSnippet(file_path="src/main.py", content="def start(): pass", start_line=1, end_line=1)

        # 1. Explain
        res_explain = service.get_explanation_context("repo-1", target=target, use_cache=False)
        assert res_explain.metadata["feature"] == "explain"
        assert res_explain.elapsed_ms >= 0

        # 2. Bug
        res_bug = service.get_bug_context("repo-1", target=target, use_cache=False)
        assert res_bug.metadata["feature"] == "bug_detection"

        # 3. Test
        res_test = service.get_test_context("repo-1", target=target, framework="pytest", use_cache=False)
        assert res_test.metadata["feature"] == "test_generation"

        # 4. Review
        mod_files = [ModifiedFile(file_path="src/main.py", content="def start(): pass")]
        res_review = service.get_review_context("repo-1", modified_files=mod_files, use_cache=False)
        assert res_review.metadata["feature"] == "code_review"

    def test_context_caching_and_hit_rate(self):
        service = RepositoryContextService()
        target = TargetSnippet(file_path="src/calc.py", content="def add(a, b): return a + b", start_line=1, end_line=1)

        # First call -> miss
        res1 = service.get_explanation_context("repo-1", target=target, use_cache=True)
        assert res1.metadata["cached"] is False

        # Second call -> hit
        res2 = service.get_explanation_context("repo-1", target=target, use_cache=True)
        assert res2.metadata["cached"] is True

        metrics = service.cache_metrics
        assert metrics["hits"] == 1
        assert metrics["misses"] == 1
        assert metrics["hit_rate"] == 0.5

    def test_cache_invalidation_on_revision_mismatch(self):
        service = RepositoryContextService()
        target1 = TargetSnippet(file_path="a.py", content="x = 1", start_line=1, end_line=1, revision="rev-1")
        target2 = TargetSnippet(file_path="a.py", content="x = 1", start_line=1, end_line=1, revision="rev-2")

        # Cache with rev-1
        service.get_explanation_context("repo-1", target=target1, use_cache=True)

        # Lookup with rev-2 -> miss due to revision mismatch
        res = service.get_explanation_context("repo-1", target=target2, use_cache=True)
        assert res.metadata["cached"] is False

    def test_cache_ttl_expiration(self):
        service = RepositoryContextService(cache_ttl_seconds=0.05)
        target = TargetSnippet(file_path="b.py", content="y = 2", start_line=1, end_line=1)

        service.get_explanation_context("repo-1", target=target, use_cache=True)
        time.sleep(0.06)

        # After TTL -> miss
        res = service.get_explanation_context("repo-1", target=target, use_cache=True)
        assert res.metadata["cached"] is False

    def test_lru_cache_eviction_when_full(self):
        service = RepositoryContextService(max_cache_size=2)
        t1 = TargetSnippet(file_path="f1.py", content="1", start_line=1, end_line=1)
        t2 = TargetSnippet(file_path="f2.py", content="2", start_line=1, end_line=1)
        t3 = TargetSnippet(file_path="f3.py", content="3", start_line=1, end_line=1)

        service.get_explanation_context("repo-1", target=t1, use_cache=True)
        service.get_explanation_context("repo-1", target=t2, use_cache=True)
        assert len(service._cache) == 2

        # Ingest 3rd -> evicts oldest (f1)
        service.get_explanation_context("repo-1", target=t3, use_cache=True)
        assert len(service._cache) == 2

    def test_provider_policy_allows_gemini_and_groq(self):
        RepositoryContextService.validate_provider_policy("gemini")
        RepositoryContextService.validate_provider_policy("groq")
        RepositoryContextService.validate_provider_policy("GEMINI")
        RepositoryContextService.validate_provider_policy("Groq")

    def test_provider_policy_rejects_unauthorized_providers(self):
        with pytest.raises(ValueError, match="Unauthorized AI provider 'openai'"):
            RepositoryContextService.validate_provider_policy("openai")

        with pytest.raises(ValueError, match="Unauthorized AI provider 'anthropic'"):
            RepositoryContextService.validate_provider_policy("anthropic")

    def test_revision_consistency_verification(self):
        target = TargetSnippet(file_path="core.py", content="val = 1", start_line=1, end_line=1, revision="commit-a")
        ctx = RepositoryContextService().get_explanation_context("r1", target=target, use_cache=False).context

        assert RepositoryContextService.verify_revision_consistency("commit-a", ctx) is True
        assert RepositoryContextService.verify_revision_consistency("commit-b", ctx) is False
        assert RepositoryContextService.verify_revision_consistency(None, ctx) is True
