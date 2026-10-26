"""
Unit and Integration Tests for Week 2 Day 7: Cross-Feature Context Verification, Revision Hardening & Quality Gate.
Owner: Meet — W2-15

Tests cover:
    1. test_shared_context_retrieval_all_four_features
    2. test_review_cache_key_collision_fix
    3. test_strict_vs_loose_revision_consistency
    4. test_assert_revision_consistency_fail_closed
    5. test_repository_cache_invalidation_by_revision_and_flush
    6. test_provider_policy_enforcement_case_insensitive
    7. test_feature_methods_enforce_provider_policy
    8. test_token_budget_audit_and_estimation
    9. test_hard_token_budget_truncation_limits
    10. test_missing_context_transparency_across_all_features
    11. test_lru_cache_eviction_and_metrics
    12. test_acceptance_scenarios_context_readiness
"""

from __future__ import annotations

import time
import pytest

from ai.context import (
    ALLOWED_AI_PROVIDERS,
    ContextLimits,
    ContextStatus,
    IntelligenceContext,
    ModifiedFile,
    RepositoryContextService,
    RepositoryFile,
    RevisionDriftError,
    SymbolContext,
    TargetSnippet,
    count_tokens,
)


class TestMeetDay7ContextVerification:
    """Week 2 Day 7 verification suite covering shared retrieval, revision consistency, and token bounding."""

    def test_shared_context_retrieval_all_four_features(self):
        """Verify unified facade retrieves valid token-bounded context across all four features."""
        service = RepositoryContextService()
        target = TargetSnippet(
            file_path="src/service.py",
            content="def calculate_total(items):\n    return sum(item.price for item in items)",
            start_line=1,
            end_line=2,
            symbol_name="calculate_total",
            revision="rev-main",
        )

        # 1. Feature 1: Code Explanation
        res_explain = service.get_explanation_context(
            "repo-day7",
            target=target,
            callers=[SymbolContext(name="checkout", kind="function", file_path="src/checkout.py", start_line=10, end_line=15)],
            use_cache=False,
        )
        assert res_explain.metadata["feature"] == "explain"
        assert res_explain.context.target.symbol_name == "calculate_total"
        assert res_explain.elapsed_ms >= 0

        # 2. Feature 2: Dedicated Bug Detection
        res_bug = service.get_bug_context(
            "repo-day7",
            target=target,
            caller_sites=[SymbolContext(name="api_handler", kind="function", file_path="src/api.py", start_line=50, end_line=60)],
            use_cache=False,
        )
        assert res_bug.metadata["feature"] == "bug_detection"
        assert len(res_bug.context.related_symbols) >= 1

        # 3. Feature 3: Framework-Aware Test Generation
        res_test = service.get_test_context(
            "repo-day7",
            target=target,
            framework="pytest",
            existing_test_files=[
                RepositoryFile(id="f1", path="tests/test_service.py", language="python", size_bytes=100, line_count=10)
            ],
            use_cache=False,
        )
        assert res_test.metadata["feature"] == "test_generation"
        assert any("pytest" in rule.lower() for rule in res_test.context.project_rules)

        # 4. Feature 4: Standalone Multi-File Review
        mod_files = [
            ModifiedFile(
                file_path="src/service.py",
                change_type="modified",
                diff_hunks=["@@ -1,2 +1,3 @@\n+    if not items: return 0"],
                modified_line_ranges=[(1, 3)],
                content="def calculate_total(items):\n    if not items: return 0\n    return sum(item.price for item in items)",
            )
        ]
        res_review = service.get_review_context(
            "repo-day7",
            modified_files=mod_files,
            base_revision="base-sha",
            head_revision="head-sha",
            use_cache=False,
        )
        assert res_review.metadata["feature"] == "code_review"
        assert res_review.context.revision == "base-sha..head-sha"

    def test_review_cache_key_collision_fix(self):
        """Verify that multi-file reviews with the same count but different files do not collide in cache."""
        service = RepositoryContextService()

        # Review 1: touches auth.py (1 file)
        diff_auth = [
            ModifiedFile(file_path="src/auth.py", change_type="modified", diff_hunks=["@@ -1 +1 @@\n-old\n+new"])
        ]
        res1 = service.get_review_context(
            "repo-collision",
            modified_files=diff_auth,
            base_revision="main",
            head_revision="feat1",
            use_cache=True,
        )
        assert res1.metadata["cached"] is False

        # Review 2: touches payment.py (also 1 file, same revisions)
        diff_payment = [
            ModifiedFile(file_path="src/payment.py", change_type="modified", diff_hunks=["@@ -5 +5 @@\n-pay\n+charge"])
        ]
        res2 = service.get_review_context(
            "repo-collision",
            modified_files=diff_payment,
            base_revision="main",
            head_revision="feat1",
            use_cache=True,
        )
        # Must NOT be a cache hit because files are different!
        assert res2.metadata["cached"] is False
        assert "payment.py" in res2.context.target.content

        # Subsequent call for diff_auth MUST hit cache
        res1_again = service.get_review_context(
            "repo-collision",
            modified_files=diff_auth,
            base_revision="main",
            head_revision="feat1",
            use_cache=True,
        )
        assert res1_again.metadata["cached"] is True
        assert "auth.py" in res1_again.context.target.content

    def test_strict_vs_loose_revision_consistency(self):
        """Test verification of source revision consistency across loose and strict modes."""
        target_a = TargetSnippet(file_path="core.py", content="x = 1", start_line=1, end_line=1, revision="commit-a")
        service = RepositoryContextService()
        ctx_a = service.get_explanation_context("r1", target=target_a, use_cache=False).context

        # 1. Matching revision returns True in both modes
        assert RepositoryContextService.verify_revision_consistency("commit-a", ctx_a, strict=False) is True
        assert RepositoryContextService.verify_revision_consistency("commit-a", ctx_a, strict=True) is True

        # 2. Mismatched revision returns False in both modes
        assert RepositoryContextService.verify_revision_consistency("commit-b", ctx_a, strict=False) is False
        assert RepositoryContextService.verify_revision_consistency("commit-b", ctx_a, strict=True) is False

        # 3. Context without revision
        target_norev = TargetSnippet(file_path="core.py", content="x = 1", start_line=1, end_line=1)
        ctx_norev = service.get_explanation_context("r1", target=target_norev, revision=None, use_cache=False).context

        # Non-strict permits unset revision
        assert RepositoryContextService.verify_revision_consistency("commit-a", ctx_norev, strict=False) is True
        # Strict mode fails closed when revision was expected but context has none
        assert RepositoryContextService.verify_revision_consistency("commit-a", ctx_norev, strict=True) is False

        # None expected revision permits None
        assert RepositoryContextService.verify_revision_consistency(None, ctx_norev, strict=False) is True
        assert RepositoryContextService.verify_revision_consistency(None, ctx_norev, strict=True) is True

    def test_assert_revision_consistency_fail_closed(self):
        """Verify assert_revision_consistency raises RevisionDriftError on drift."""
        target = TargetSnippet(file_path="api.py", content="y = 2", start_line=1, end_line=1, revision="rev-100")
        service = RepositoryContextService()
        ctx = service.get_explanation_context("r1", target=target, use_cache=False).context

        # Valid revision passes without error
        RepositoryContextService.assert_revision_consistency("rev-100", ctx, strict=True)

        # Divergent revision raises RevisionDriftError
        with pytest.raises(RevisionDriftError) as exc_info:
            RepositoryContextService.assert_revision_consistency("rev-200", ctx, strict=True)

        assert exc_info.value.expected_revision == "rev-200"
        assert exc_info.value.actual_revision == "rev-100"
        assert "api.py" in str(exc_info.value)

    def test_repository_cache_invalidation_by_revision_and_flush(self):
        """Verify invalidation of repository cache entries when revisions drift or whole repo is updated."""
        service = RepositoryContextService()
        t1 = TargetSnippet(file_path="f1.py", content="1", start_line=1, end_line=1, revision="rev-old")
        t2 = TargetSnippet(file_path="f2.py", content="2", start_line=1, end_line=1, revision="rev-new")
        t_other = TargetSnippet(file_path="other.py", content="3", start_line=1, end_line=1, revision="rev-old")

        # Ingest entries for repo-alpha and repo-beta
        service.get_explanation_context("repo-alpha", target=t1, use_cache=True)
        service.get_explanation_context("repo-alpha", target=t2, use_cache=True)
        service.get_explanation_context("repo-beta", target=t_other, use_cache=True)

        assert service.cache_metrics["cache_size"] == 3

        # Invalidate repo-alpha for new revision 'rev-new' (should only evict rev-old)
        evicted = service.invalidate_cache_for_repository("repo-alpha", new_revision="rev-new")
        assert evicted == 1
        assert service.cache_metrics["cache_size"] == 2

        # Invalidate all remaining repo-alpha entries
        evicted_all = service.invalidate_cache_for_repository("repo-alpha")
        assert evicted_all == 1

        # repo-beta remains untouched
        assert service.cache_metrics["cache_size"] == 1
        res_beta = service.get_explanation_context("repo-beta", target=t_other, use_cache=True)
        assert res_beta.metadata["cached"] is True

    def test_provider_policy_enforcement_case_insensitive(self):
        """Verify permitted providers (Gemini, Groq) and strict rejection of unauthorized providers."""
        # Allowed providers pass
        for allowed in ["gemini", "groq", "GEMINI", "Groq", "  gemini  "]:
            RepositoryContextService.validate_provider_policy(allowed)

        # Unauthorized providers raise ValueError
        unauthorized = ["openai", "anthropic", "cohere", "bedrock", "mistral", "", "   "]
        for p in unauthorized:
            with pytest.raises(ValueError, match="Unauthorized AI provider"):
                RepositoryContextService.validate_provider_policy(p)

    def test_feature_methods_enforce_provider_policy(self):
        """Verify feature methods validate ai_provider policy on invocation."""
        service = RepositoryContextService()
        target = TargetSnippet(file_path="test.py", content="pass", start_line=1, end_line=1)

        # Succeeded with permitted provider
        res = service.get_explanation_context("r1", target=target, ai_provider="gemini", use_cache=False)
        assert res.context.target.file_path == "test.py"

        # Fails with unauthorized provider
        with pytest.raises(ValueError, match="Unauthorized AI provider 'openai'"):
            service.get_explanation_context("r1", target=target, ai_provider="openai")

        with pytest.raises(ValueError, match="Unauthorized AI provider 'anthropic'"):
            service.get_bug_context("r1", target=target, ai_provider="anthropic")

        with pytest.raises(ValueError, match="Unauthorized AI provider 'azure'"):
            service.get_test_context("r1", target=target, ai_provider="azure")

        with pytest.raises(ValueError, match="Unauthorized AI provider 'bedrock'"):
            service.get_review_context("r1", modified_files=[], ai_provider="bedrock")

    def test_token_budget_audit_and_estimation(self):
        """Verify token budget auditing and rapid pre-flight estimation."""
        service = RepositoryContextService()
        target = TargetSnippet(
            file_path="src/parser.py",
            content="def parse_tokens(code):\n    return tokenize(code)",
            start_line=1,
            end_line=2,
            symbol_name="parse_tokens",
        )
        callers = [
            SymbolContext(
                name="run_pipeline",
                kind="function",
                file_path="src/main.py",
                start_line=10,
                end_line=20,
                content="def run_pipeline():\n    parse_tokens(src)",
            )
        ]

        # 1. Estimation
        est = RepositoryContextService.estimate_context_tokens(
            target_code=target.content,
            related_symbols=callers,
            repository_files=[
                RepositoryFile(id="1", path="a.py", language="python", size_bytes=50, line_count=5),
                RepositoryFile(id="2", path="b.py", language="python", size_bytes=80, line_count=8),
            ],
            project_rules=["Rule 1: Always check syntax"],
        )
        assert est > 0

        # 2. Audit
        res = service.get_explanation_context("r1", target=target, callers=callers, use_cache=False)
        audit = RepositoryContextService.audit_context_budget(res.context, limits=ContextLimits(max_tokens=4000))

        assert audit["within_budget"] is True
        assert audit["total_tokens"] > 0
        assert audit["target_tokens"] > 0
        assert audit["symbol_tokens"] > 0
        assert audit["symbol_count"] == 1
        assert 0.0 < audit["utilization_ratio"] < 1.0

    def test_hard_token_budget_truncation_limits(self):
        """Verify hard token ceilings clip context correctly without overflowing."""
        service = RepositoryContextService()

        # 1. Target code fits within budget (e.g. 50 tokens), but multiple symbols exceed budget
        target = TargetSnippet(file_path="mod.py", content="def small_fn():\n    return 42", start_line=1, end_line=2)
        symbols = [
            SymbolContext(
                name=f"caller_{i}",
                kind="caller",
                file_path=f"caller_{i}.py",
                start_line=1,
                end_line=10,
                content=f"def caller_{i}():\n    # heavy logic block\n    result = process({i}) * 100\n    return small_fn()",
            )
            for i in range(15)
        ]

        # Enforce budget of 150 tokens
        tight_limits = ContextLimits(max_tokens=150)
        res = service.get_explanation_context("r1", target=target, callers=symbols, limits=tight_limits, use_cache=False)

        assert res.context.total_tokens <= 150
        assert len(res.context.related_symbols) < len(symbols)
        assert len(res.context.missing_context) >= 1
        assert any("omitted due to token budget" in m.reason for m in res.context.missing_context)

        # 2. Oversized target snippet alone exceeds token budget
        large_content = "\n".join([f"line_{i} = calculate_value({i}) * 100" for i in range(250)])
        large_target = TargetSnippet(file_path="heavy.py", content=large_content, start_line=1, end_line=250)
        res_oversized = service.get_explanation_context("r1", target=large_target, limits=tight_limits, use_cache=False)

        assert res_oversized.context.status == ContextStatus.OVERSIZED
        assert res_oversized.context.related_symbols == []
        assert any("exceeds context budget" in m.reason for m in res_oversized.context.missing_context)

    def test_missing_context_transparency_across_all_features(self):
        """Verify explicit missing context tracking across all four features."""
        service = RepositoryContextService()
        target = TargetSnippet(
            file_path="orphan.py",
            content="def lonely_fn(): pass",
            start_line=1,
            end_line=1,
            symbol_name="lonely_fn",
        )

        # Explanation with no callers -> records missing caller context
        res_exp = service.get_explanation_context("r1", target=target, callers=None, use_cache=False)
        assert len(res_exp.context.missing_context) >= 1
        assert any("lonely_fn" in m.reason for m in res_exp.context.missing_context)

        # Bug context with no callers -> records missing caller sites
        res_bug = service.get_bug_context("r1", target=target, caller_sites=None, use_cache=False)
        assert len(res_bug.context.missing_context) >= 1

        # Test context without existing tests -> records missing existing test directory
        res_test = service.get_test_context("r1", target=target, existing_test_files=None, use_cache=False)
        assert len(res_test.context.missing_context) >= 1

        # Review context with empty files -> records missing target
        res_rev = service.get_review_context("r1", modified_files=[], use_cache=False)
        assert res_rev.context.status == ContextStatus.MISSING_TARGET
        assert len(res_rev.context.missing_context) >= 1

    def test_lru_cache_eviction_and_metrics(self):
        """Verify LRU cache limits and metric accounting."""
        service = RepositoryContextService(max_cache_size=3, cache_ttl_seconds=60.0)

        for i in range(5):
            t = TargetSnippet(file_path=f"file_{i}.py", content=f"var_{i} = {i}", start_line=1, end_line=1)
            service.get_explanation_context("r1", target=t, use_cache=True)

        metrics = service.cache_metrics
        assert metrics["cache_size"] == 3  # Capped at max_cache_size
        assert metrics["misses"] == 5
        assert metrics["hits"] == 0

        # Most recently added (file_4) should be present
        t4 = TargetSnippet(file_path="file_4.py", content="var_4 = 4", start_line=1, end_line=1)
        res4 = service.get_explanation_context("r1", target=t4, use_cache=True)
        assert res4.metadata["cached"] is True
        assert service.cache_metrics["hits"] == 1

    def test_acceptance_scenarios_context_readiness(self):
        """Verify context readiness for all Week 2 acceptance scenarios A through E."""
        service = RepositoryContextService()

        # Scenario A: Code Explanation with function scope & imports
        t_a = TargetSnippet(
            file_path="src/auth.py",
            content="def verify_jwt(token: str) -> bool:\n    return len(token) > 10",
            start_line=10,
            end_line=12,
            symbol_name="verify_jwt",
            revision="v1.0",
        )
        ctx_a = service.get_explanation_context("repo-qa", target=t_a, source_code="import jwt\nimport os", use_cache=False)
        assert ctx_a.context.is_complete is False  # Missing callers explicitly noted
        assert any("verify_jwt" in m.reason for m in ctx_a.context.missing_context)

        # Scenario B: Bug Detection with callers
        caller = SymbolContext(name="login_route", kind="caller", file_path="src/routes.py", start_line=40, end_line=45, content="verify_jwt(hdr)")
        ctx_b = service.get_bug_context("repo-qa", target=t_a, caller_sites=[caller], use_cache=False)
        assert ctx_b.context.is_complete is True

        # Scenario C: Test Generation with pytest framework
        ctx_c = service.get_test_context("repo-qa", target=t_a, framework="pytest", use_cache=False)
        assert any("pytest" in r.lower() for r in ctx_c.context.project_rules)

        # Scenario D: Multi-File Code Review with blast radius
        mod_files = [
            ModifiedFile(file_path="src/auth.py", change_type="modified", diff_hunks=["@@ -10,3 +10,4 @@\n+    if not token: raise ValueError()"]),
            ModifiedFile(file_path="src/routes.py", change_type="modified", diff_hunks=["@@ -42 +42 @@\n-verify_jwt(hdr)\n+verify_jwt(hdr.strip())"]),
        ]
        ctx_d = service.get_review_context("repo-qa", modified_files=mod_files, base_revision="v1.0", head_revision="v1.1", use_cache=False)
        assert ctx_d.context.total_tokens > 0
        assert ctx_d.context.status in (ContextStatus.COMPLETE, ContextStatus.PARTIAL)
