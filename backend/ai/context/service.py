"""
Repository Context Service — Week 2 Day 6 (Shared Intelligence Integration).
Owner: Meet — W2-15 / Shared Intelligence Integration & Hardening

Provides a unified repository context management engine across all 4 developer intelligence features:
1. Code Explanation
2. Bug Detection
3. Framework-Aware Test Generation
4. Standalone AI Code Review

Guarantees:
- Single retrieval and context contract across all features (DRY)
- LRU context caching to avoid repeated database/file retrieval
- Source revision consistency verification (fail-closed on revision drift)
- Token budget allocation & Gemini/Groq-only provider policy enforcement
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from ai.context.bug_context import BugContextExtractor, extract_bug_context
from ai.context.builder import (
    ContextBuilder,
    ContextLimits,
    ContextStatus,
    IntelligenceContext,
    IntelligenceContextRequest,
    IntelligenceContextResponse,
    MissingContextInfo,
    RepositoryFile,
    SymbolContext,
    TargetSnippet,
    count_tokens,
)
from ai.context.explanation import ExplanationContextEnricher, enrich_explanation_context
from ai.context.review_context import (
    ModifiedFile,
    ReviewBlastRadius,
    ReviewContextBuilder,
    build_multi_file_review_context,
)
from ai.context.test_context import TestContextBuilder, build_test_generation_context

logger = logging.getLogger(__name__)

# Permitted LLM providers under architectural security policy
ALLOWED_AI_PROVIDERS = frozenset({"gemini", "groq"})


class RevisionDriftError(ValueError):
    """Raised when repository context detects revision drift or unauthorized divergence."""

    def __init__(self, expected_revision: str, actual_revision: str | None, details: str = ""):
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision
        self.details = details
        msg = f"Revision drift detected: expected '{expected_revision}', found '{actual_revision}'."
        if details:
            msg += f" {details}"
        super().__init__(msg)


@dataclass
class CacheEntry:
    """Cached intelligence context with creation timestamp, revision hash, and repository ID."""

    context: IntelligenceContext
    created_at: float
    revision: str | None
    repository_id: str = ""


class RepositoryContextService:
    """Unified shared intelligence context facade with caching, revision integrity, and provider policy validation."""

    def __init__(
        self,
        builder: ContextBuilder | None = None,
        max_cache_size: int = 128,
        cache_ttl_seconds: float = 300.0,
    ):
        self.builder = builder or ContextBuilder()
        self.max_cache_size = max_cache_size
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cache: dict[str, CacheEntry] = {}
        self._hits: int = 0
        self._misses: int = 0

    @property
    def cache_metrics(self) -> dict[str, Any]:
        """Return diagnostic metrics on context caching efficiency."""
        total = self._hits + self._misses
        hit_rate = (self._hits / total) if total > 0 else 0.0
        return {
            "hits": self._hits,
            "misses": self._misses,
            "total_requests": total,
            "hit_rate": round(hit_rate, 4),
            "cache_size": len(self._cache),
        }

    def clear_cache(self) -> None:
        """Flush the context cache."""
        self._cache.clear()
        self._hits = 0
        self._misses = 0

    def invalidate_cache_for_repository(
        self,
        repository_id: str,
        new_revision: str | None = None,
    ) -> int:
        """
        Evict cached entries for a given repository.
        If new_revision is provided, invalidates entries whose revision does not match new_revision.
        If new_revision is None, invalidates all entries for repository_id.
        Returns the number of evicted entries.
        """
        keys_to_delete = [
            k
            for k, entry in self._cache.items()
            if entry.repository_id == repository_id
            and (new_revision is None or entry.revision != new_revision)
        ]
        for k in keys_to_delete:
            del self._cache[k]

        logger.info(
            "repository_cache_invalidated",
            extra={
                "repository_id": repository_id,
                "evicted": len(keys_to_delete),
                "new_revision": new_revision,
            },
        )
        return len(keys_to_delete)

    @staticmethod
    def validate_provider_policy(provider_name: str) -> None:
        """
        Enforce project architecture policy: only Gemini and Groq are permitted.
        Raises ValueError if unauthorized provider (e.g. OpenAI) is requested.
        """
        norm_name = (provider_name or "").strip().lower()
        if norm_name not in ALLOWED_AI_PROVIDERS:
            raise ValueError(
                f"Unauthorized AI provider '{provider_name}'. Architectural policy restricts developer intelligence to: {sorted(ALLOWED_AI_PROVIDERS)}"
            )

    @staticmethod
    def verify_revision_consistency(
        expected_revision: str | None,
        context: IntelligenceContext,
        *,
        strict: bool = False,
    ) -> bool:
        """
        Verify that all elements in the context match the expected source revision.
        In non-strict mode: returns True if either expected_revision or context.revision is unset.
        In strict mode: expected_revision must be provided and must match context.revision
        and target_snippet.revision (if set).
        """
        if not expected_revision:
            return not strict or context.revision is None

        if strict and not context.revision:
            return False

        if context.revision and context.revision != expected_revision:
            return False

        if context.target and context.target.revision:
            if context.target.revision != expected_revision:
                return False

        return True

    @classmethod
    def assert_revision_consistency(
        cls,
        expected_revision: str | None,
        context: IntelligenceContext,
        *,
        strict: bool = True,
    ) -> None:
        """
        Fail-closed assertion ensuring revision consistency.
        Raises RevisionDriftError if any drift is detected.
        """
        if not cls.verify_revision_consistency(expected_revision, context, strict=strict):
            actual = context.revision or (context.target.revision if context.target else None)
            target_path = context.target.file_path if context.target else "unknown"
            raise RevisionDriftError(
                expected_revision=str(expected_revision),
                actual_revision=actual,
                details=f"Context target: {target_path}",
            )

    @staticmethod
    def audit_context_budget(
        context: IntelligenceContext,
        limits: ContextLimits | None = None,
    ) -> dict[str, Any]:
        """
        Audit the token consumption and bounding compliance of an assembled IntelligenceContext.
        Provides breakdown across target code, symbols, rules, chunks, and missing context.
        """
        budget = limits.max_tokens if limits else context.token_budget
        target_tokens = count_tokens(context.target.content) if context.target else 0
        symbol_tokens = sum(count_tokens(s.content) for s in context.related_symbols)
        rule_tokens = sum(count_tokens(r) for r in context.project_rules)
        chunk_tokens = sum(count_tokens(getattr(c, "content", "")) for c in context.relevant_chunks)

        within_budget = context.total_tokens <= budget
        utilization = round((context.total_tokens / budget), 4) if budget > 0 else 0.0

        return {
            "total_tokens": context.total_tokens,
            "token_budget": budget,
            "within_budget": within_budget,
            "utilization_ratio": utilization,
            "status": context.status.value if hasattr(context.status, "value") else str(context.status),
            "target_tokens": target_tokens,
            "symbol_tokens": symbol_tokens,
            "rule_tokens": rule_tokens,
            "chunk_tokens": chunk_tokens,
            "symbol_count": len(context.related_symbols),
            "missing_context_count": len(context.missing_context),
            "is_complete": context.is_complete,
            "revision": context.revision,
        }

    @staticmethod
    def estimate_context_tokens(
        target_code: str,
        related_symbols: Sequence[SymbolContext] | None = None,
        repository_files: Sequence[RepositoryFile] | None = None,
        project_rules: Sequence[str] | None = None,
    ) -> int:
        """
        Rapid token pre-flight estimator before executing full multi-source assembly.
        """
        total = count_tokens(target_code or "")
        if related_symbols:
            total += sum(count_tokens(s.content or s.name) for s in related_symbols)
        if repository_files:
            total += len(repository_files) * 5
        if project_rules:
            total += sum(count_tokens(r) for r in project_rules)
        return total

    def _cache_key(
        self,
        feature_name: str,
        repository_id: str,
        file_path: str,
        start_line: int,
        end_line: int,
        symbol_name: str | None,
        revision: str | None,
    ) -> str:
        raw = f"{feature_name}:{repository_id}:{file_path}:{start_line}:{end_line}:{symbol_name}:{revision}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _lookup_cache(self, key: str, expected_revision: str | None) -> IntelligenceContext | None:
        entry = self._cache.get(key)
        if not entry:
            self._misses += 1
            return None

        # Check expiration
        now = time.time()
        if now - entry.created_at > self.cache_ttl_seconds:
            del self._cache[key]
            self._misses += 1
            return None

        # Check revision consistency
        if expected_revision and entry.revision and entry.revision != expected_revision:
            del self._cache[key]
            self._misses += 1
            return None

        self._hits += 1
        return entry.context

    def _store_cache(
        self,
        key: str,
        context: IntelligenceContext,
        revision: str | None,
        repository_id: str = "",
    ) -> None:
        if len(self._cache) >= self.max_cache_size:
            # Evict oldest entry
            oldest_key = min(self._cache, key=lambda k: self._cache[k].created_at)
            del self._cache[oldest_key]

        self._cache[key] = CacheEntry(
            context=context,
            created_at=time.time(),
            revision=revision,
            repository_id=repository_id,
        )

    # ------------------------------------------------------------------
    # Feature 1: Code Explanation Context
    # ------------------------------------------------------------------
    def get_explanation_context(
        self,
        repository_id: str,
        target: TargetSnippet,
        source_code: str | None = None,
        callers: Sequence[SymbolContext] | None = None,
        imported_types: Sequence[SymbolContext] | None = None,
        related_symbols: Sequence[SymbolContext] | None = None,
        repository_files: Sequence[RepositoryFile] | None = None,
        limits: ContextLimits | None = None,
        revision: str | None = None,
        ai_provider: str | None = None,
        use_cache: bool = True,
    ) -> IntelligenceContextResponse:
        if ai_provider:
            self.validate_provider_policy(ai_provider)

        t0 = time.time()
        rev = revision or target.revision
        ckey = self._cache_key(
            "explain", repository_id, target.file_path, target.start_line, target.end_line, target.symbol_name, rev
        )

        if use_cache:
            cached = self._lookup_cache(ckey, rev)
            if cached:
                return IntelligenceContextResponse(
                    context=cached,
                    elapsed_ms=(time.time() - t0) * 1000,
                    metadata={"cached": True, "feature": "explain"},
                )

        ctx = enrich_explanation_context(
            target=target,
            source_code=source_code,
            callers=callers,
            imported_types=imported_types,
            related_symbols=related_symbols,
            repository_files=repository_files,
            limits=limits,
            revision=rev,
        )

        if use_cache and ctx.is_complete:
            self._store_cache(ckey, ctx, rev, repository_id=repository_id)

        elapsed = (time.time() - t0) * 1000
        return IntelligenceContextResponse(
            context=ctx,
            elapsed_ms=elapsed,
            metadata={"cached": False, "feature": "explain"},
        )

    # ------------------------------------------------------------------
    # Feature 2: Dedicated Bug Detection Context
    # ------------------------------------------------------------------
    def get_bug_context(
        self,
        repository_id: str,
        target: TargetSnippet,
        source_code: str | None = None,
        caller_sites: Sequence[SymbolContext] | None = None,
        related_types: Sequence[SymbolContext] | None = None,
        repository_files: Sequence[RepositoryFile] | None = None,
        limits: ContextLimits | None = None,
        revision: str | None = None,
        ai_provider: str | None = None,
        use_cache: bool = True,
    ) -> IntelligenceContextResponse:
        if ai_provider:
            self.validate_provider_policy(ai_provider)

        t0 = time.time()
        rev = revision or target.revision
        ckey = self._cache_key(
            "bug", repository_id, target.file_path, target.start_line, target.end_line, target.symbol_name, rev
        )

        if use_cache:
            cached = self._lookup_cache(ckey, rev)
            if cached:
                return IntelligenceContextResponse(
                    context=cached,
                    elapsed_ms=(time.time() - t0) * 1000,
                    metadata={"cached": True, "feature": "bug_detection"},
                )

        ctx = extract_bug_context(
            target=target,
            source_code=source_code,
            caller_sites=caller_sites,
            related_types=related_types,
            repository_files=repository_files,
            limits=limits,
            revision=rev,
        )

        if use_cache and ctx.is_complete:
            self._store_cache(ckey, ctx, rev, repository_id=repository_id)

        elapsed = (time.time() - t0) * 1000
        return IntelligenceContextResponse(
            context=ctx,
            elapsed_ms=elapsed,
            metadata={"cached": False, "feature": "bug_detection"},
        )

    # ------------------------------------------------------------------
    # Feature 3: Framework-Aware Test Generation Context
    # ------------------------------------------------------------------
    def get_test_context(
        self,
        repository_id: str,
        target: TargetSnippet,
        framework: str = "pytest",
        existing_test_files: Sequence[RepositoryFile] | None = None,
        sample_test_code: str | None = None,
        mockable_dependencies: Sequence[SymbolContext] | None = None,
        fixture_definitions: Sequence[str] | None = None,
        repository_files: Sequence[RepositoryFile] | None = None,
        limits: ContextLimits | None = None,
        revision: str | None = None,
        ai_provider: str | None = None,
        use_cache: bool = True,
    ) -> IntelligenceContextResponse:
        if ai_provider:
            self.validate_provider_policy(ai_provider)

        t0 = time.time()
        rev = revision or target.revision
        ckey = self._cache_key(
            f"test_{framework}", repository_id, target.file_path, target.start_line, target.end_line, target.symbol_name, rev
        )

        if use_cache:
            cached = self._lookup_cache(ckey, rev)
            if cached:
                return IntelligenceContextResponse(
                    context=cached,
                    elapsed_ms=(time.time() - t0) * 1000,
                    metadata={"cached": True, "feature": "test_generation"},
                )

        ctx = build_test_generation_context(
            target=target,
            framework=framework,
            existing_test_files=existing_test_files,
            sample_test_code=sample_test_code,
            mockable_dependencies=mockable_dependencies,
            fixture_definitions=fixture_definitions,
            repository_files=repository_files,
            limits=limits,
            revision=rev,
        )

        if use_cache and ctx.is_complete:
            self._store_cache(ckey, ctx, rev, repository_id=repository_id)

        elapsed = (time.time() - t0) * 1000
        return IntelligenceContextResponse(
            context=ctx,
            elapsed_ms=elapsed,
            metadata={"cached": False, "feature": "test_generation"},
        )

    # ------------------------------------------------------------------
    # Feature 4: Standalone Multi-File Review Context
    # ------------------------------------------------------------------
    def get_review_context(
        self,
        repository_id: str,
        modified_files: Sequence[ModifiedFile],
        base_revision: str | None = None,
        head_revision: str | None = None,
        symbol_graph: Sequence[SymbolContext] | None = None,
        repository_files: Sequence[RepositoryFile] | None = None,
        limits: ContextLimits | None = None,
        ai_provider: str | None = None,
        use_cache: bool = True,
    ) -> IntelligenceContextResponse:
        if ai_provider:
            self.validate_provider_policy(ai_provider)

        t0 = time.time()
        rev = f"{base_revision}..{head_revision}"
        # Compute deterministic files digest to avoid collisions across distinct diffs with identical file count
        files_sig = "|".join(
            f"{mf.file_path}:{mf.change_type}:{len(mf.diff_hunks)}"
            for mf in sorted(modified_files, key=lambda m: m.file_path)
        )
        files_hash = hashlib.sha256(files_sig.encode("utf-8")).hexdigest()[:16]
        ckey = self._cache_key(
            "review", repository_id, f"multi-diff:{files_hash}", 1, len(modified_files), None, rev
        )

        if use_cache:
            cached = self._lookup_cache(ckey, rev)
            if cached:
                return IntelligenceContextResponse(
                    context=cached,
                    elapsed_ms=(time.time() - t0) * 1000,
                    metadata={"cached": True, "feature": "code_review"},
                )

        ctx = build_multi_file_review_context(
            modified_files=modified_files,
            base_revision=base_revision,
            head_revision=head_revision,
            symbol_graph=symbol_graph,
            repository_files=repository_files,
            limits=limits,
        )

        if use_cache and ctx.is_complete:
            self._store_cache(ckey, ctx, rev, repository_id=repository_id)

        elapsed = (time.time() - t0) * 1000
        return IntelligenceContextResponse(
            context=ctx,
            elapsed_ms=elapsed,
            metadata={"cached": False, "feature": "code_review"},
        )


# Global singleton instance for easy cross-module consumption
shared_context_service = RepositoryContextService()
