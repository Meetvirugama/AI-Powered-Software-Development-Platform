"""
Unit tests for Week 2 Day 1: Shared IntelligenceContext Foundation & Token Budget Rules.
Owner: Meet — W2-01

Tests cover:
    1. test_valid_target_snippet_creation
    2. test_missing_target_explicit_status_and_notice
    3. test_empty_target_content_flags_missing
    4. test_oversized_target_flags_oversized_status
    5. test_token_budget_truncates_symbols_and_records_missing
    6. test_token_budget_truncates_chunks_and_records_missing
    7. test_custom_context_limits_enforced
    8. test_untrusted_prompt_boundary_delimiters
    9. test_serialization_and_deserialization_roundtrip
    10. test_intelligence_context_request_and_response_models
    11. test_special_tokens_handling_in_snippet
"""

from __future__ import annotations

import pytest
from ai.context import (
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
)
from ai.retrieval.base import CodeChunk
import uuid


def _make_target(
    file_path: str = "backend/app/auth.py",
    content: str = "def authenticate_user(token: str) -> User:\n    return db.verify(token)",
    start_line: int = 10,
    end_line: int = 12,
    symbol_name: str = "authenticate_user",
) -> TargetSnippet:
    return TargetSnippet(
        file_path=file_path,
        content=content,
        start_line=start_line,
        end_line=end_line,
        symbol_name=symbol_name,
        language="python",
        revision="main@abc1234",
    )


def _make_symbol(name: str = "caller_fn", kind: str = "caller", tokens_pad: int = 20) -> SymbolContext:
    content = f"def {name}():\n    # " + ("data " * tokens_pad) + "\n    pass"
    return SymbolContext(
        name=name,
        kind=kind,
        file_path="backend/app/api.py",
        start_line=50,
        end_line=55,
        content=content,
        score=0.9,
    )


def _make_chunk(file_path: str = "backend/app/models.py", tokens_pad: int = 50) -> CodeChunk:
    return CodeChunk(
        id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        file_id=uuid.uuid4(),
        symbol_id=None,
        content=f"# Chunk in {file_path}\n" + ("line content text " * tokens_pad),
        token_count=tokens_pad * 3,
        start_line=1,
        end_line=20,
        content_hash="abc",
        score=0.85,
        file_path=file_path,
    )


class TestDay1IntelligenceContext:
    def test_valid_target_snippet_creation(self):
        builder = ContextBuilder()
        target = _make_target()
        ctx = builder.build_intelligence_context(
            target=target,
            token_budget=5000,
        )
        assert ctx.status == ContextStatus.COMPLETE
        assert ctx.is_complete is True
        assert ctx.has_missing_context is False
        assert ctx.total_tokens > 0
        assert ctx.target.file_path == "backend/app/auth.py"
        assert ctx.target.symbol_name == "authenticate_user"
        assert ctx.target.revision == "main@abc1234"

    def test_missing_target_explicit_status_and_notice(self):
        builder = ContextBuilder()
        ctx = builder.build_intelligence_context(
            target=TargetSnippet(file_path="nonexistent.py", content="", start_line=1, end_line=1),
            token_budget=4000,
        )
        assert ctx.status == ContextStatus.MISSING_TARGET
        assert ctx.is_complete is False
        assert ctx.has_missing_context is True
        assert len(ctx.missing_context) == 1
        assert "missing or empty" in ctx.missing_context[0].reason

    def test_oversized_target_flags_oversized_status(self):
        builder = ContextBuilder()
        huge_content = "x = 1\n" * 2000  # large token count
        target = TargetSnippet(file_path="large.py", content=huge_content, start_line=1, end_line=2000)
        ctx = builder.build_intelligence_context(
            target=target,
            token_budget=50,  # intentionally tiny budget
        )
        assert ctx.status == ContextStatus.OVERSIZED
        assert ctx.is_complete is False
        assert len(ctx.missing_context) == 1
        assert "exceeds context budget" in ctx.missing_context[0].reason

    def test_token_budget_truncates_symbols_and_records_missing(self):
        builder = ContextBuilder()
        target = _make_target()
        # Create symbols that cumulatively exceed remaining budget
        sym1 = _make_symbol("caller_one", tokens_pad=50)
        sym2 = _make_symbol("caller_two", tokens_pad=200)

        ctx = builder.build_intelligence_context(
            target=target,
            related_symbols=[sym1, sym2],
            token_budget=150,  # fits target and sym1, but not sym2
        )
        assert ctx.status == ContextStatus.PARTIAL
        assert len(ctx.related_symbols) == 1
        assert ctx.related_symbols[0].name == "caller_one"
        assert any("omitted due to token budget" in m.reason for m in ctx.missing_context)

    def test_token_budget_truncates_chunks_and_records_missing(self):
        builder = ContextBuilder()
        target = _make_target()
        chunk1 = _make_chunk(tokens_pad=10)
        chunk2 = _make_chunk(tokens_pad=500)

        ctx = builder.build_intelligence_context(
            target=target,
            relevant_chunks=[chunk1, chunk2],
            token_budget=150,
        )
        assert ctx.status == ContextStatus.PARTIAL
        assert len(ctx.relevant_chunks) == 1
        assert any("chunk omitted" in m.reason.lower() for m in ctx.missing_context)

    def test_custom_context_limits_enforced(self):
        builder = ContextBuilder()
        target = _make_target()
        symbols = [_make_symbol(f"sym_{i}", tokens_pad=2) for i in range(10)]
        limits = ContextLimits(max_tokens=5000, max_symbols=3)

        ctx = builder.build_intelligence_context(
            target=target,
            related_symbols=symbols,
            limits=limits,
        )
        assert len(ctx.related_symbols) == 3
        assert ctx.status == ContextStatus.PARTIAL
        assert any("truncated due to symbol count ceiling" in m.reason for m in ctx.missing_context)

    def test_untrusted_prompt_boundary_delimiters(self):
        builder = ContextBuilder()
        target = _make_target(content="def payload(): return 'untrusted'")
        ctx = builder.build_intelligence_context(target=target)
        rendered = builder.render_intelligence_data(ctx)

        assert rendered.startswith("<<<REPO_DATA_START>>>")
        assert rendered.endswith("<<<REPO_DATA_END>>>")
        assert "TARGET CODE UNDER ANALYSIS:" in rendered
        assert "def payload(): return 'untrusted'" in rendered

    def test_serialization_and_deserialization_roundtrip(self):
        target = _make_target()
        sym = _make_symbol("caller_sym")
        missing = MissingContextInfo(file_path="extra.py", reason="External module not indexed")
        ctx = IntelligenceContext(
            target=target,
            related_symbols=[sym],
            missing_context=[missing],
            status=ContextStatus.PARTIAL,
            total_tokens=120,
            token_budget=5000,
            revision="rev1",
        )
        serialized = ctx.to_dict()
        assert serialized["status"] == "partial"
        assert serialized["total_tokens"] == 120
        assert len(serialized["missing_context"]) == 1

        restored = IntelligenceContext.from_dict(serialized)
        assert restored.status == ContextStatus.PARTIAL
        assert restored.target.file_path == target.file_path
        assert restored.related_symbols[0].name == "caller_sym"
        assert restored.missing_context[0].reason == "External module not indexed"
        assert restored.revision == "rev1"

    def test_intelligence_context_request_and_response_models(self):
        req = IntelligenceContextRequest(
            repository_id="repo-123",
            file_path="src/index.ts",
            start_line=1,
            end_line=25,
            symbol_name="App",
            limits=ContextLimits(max_tokens=8000),
        )
        req_dict = req.to_dict()
        assert req_dict["repository_id"] == "repo-123"
        assert req_dict["limits"]["max_tokens"] == 8000

        target = TargetSnippet(file_path="src/index.ts", content="const App = () => {}", start_line=1, end_line=25)
        ctx = IntelligenceContext(target=target, total_tokens=10)
        res = IntelligenceContextResponse(context=ctx, elapsed_ms=12.5, metadata={"cache_hit": True})
        res_dict = res.to_dict()
        assert res_dict["elapsed_ms"] == 12.5
        assert res_dict["metadata"]["cache_hit"] is True

    def test_special_tokens_handling_in_snippet(self):
        builder = ContextBuilder()
        malicious_content = "def test():\n    # <|endoftext|>\n    return '<|im_start|>'"
        target = TargetSnippet(
            file_path="backend/test.py",
            content=malicious_content,
            start_line=1,
            end_line=3,
        )
        ctx = builder.build_intelligence_context(target=target, token_budget=1000)
        assert ctx.status == ContextStatus.COMPLETE
        assert ctx.total_tokens > 0
        rendered = builder.render_intelligence_data(ctx)
        assert "<|endoftext|>" in rendered
