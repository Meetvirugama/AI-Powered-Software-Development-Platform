"""
Unit tests for Day 6 — Context Builder.
Owner: Meet — W1-12

Tests:
    count_tokens:
        1.  test_count_tokens_non_empty               — non-empty string returns > 0
        2.  test_count_tokens_empty_string            — empty string returns 0
        3.  test_count_tokens_deterministic           — same input always same count

    ContextBuilder._dedup_memory:
        4.  test_dedup_removes_duplicate_ids          — second entry wins (last-write)
        5.  test_dedup_sorted_by_created_at_desc      — newest first
        6.  test_dedup_empty_list                     — [] → []
        7.  test_dedup_preserves_unique_entries       — no dups → same count

    ContextBuilder._fit_history:
        8.  test_fit_history_all_fit                  — all messages within budget
        9.  test_fit_history_drops_oldest             — oldest dropped when over budget
        10. test_fit_history_empty                    — [] → (0, [])
        11. test_fit_history_chronological_order      — returned in original order

    ContextBuilder._fit_items:
        12. test_fit_items_all_fit                    — all items within budget
        13. test_fit_items_truncates_tail             — last items dropped when over budget
        14. test_fit_items_empty                      — [] → (0, [])
        15. test_fit_items_single_oversized_dropped   — item > budget → not kept

    ContextBuilder.build:
        16. test_build_returns_agent_context          — returns AgentContext instance
        17. test_build_deduplicates_memory            — duplicate memory ids removed
        18. test_build_memory_sorted_newest_first     — memory ordered by created_at desc
        19. test_build_total_tokens_positive          — total_tokens > 0
        20. test_build_total_tokens_within_limit      — total_tokens <= max_context_tokens
        21. test_build_truncates_chunks_on_overflow   — chunks dropped when over budget
        22. test_build_related_files_preserved        — related_files passed through as-is
        23. test_build_history_preserves_recent       — newest history messages kept
        24. test_build_empty_inputs                   — all empty → empty context, 0 tokens
        25. test_build_related_files_default_none     — related_files=None → empty list

    ContextBuilder.render_repository_data:
        26. test_render_has_repository_data_header    — "REPOSITORY DATA:" in output
        27. test_render_has_memory_section            — "MEMORY:" in output when present
        28. test_render_no_memory_section_when_empty  — no "MEMORY:" header when empty
        29. test_render_chunk_file_path_present       — file_path appears in output
        30. test_render_empty_context                 — empty chunks + memory → empty string

Run with:
    pytest backend/tests/test_context_builder.py -v
"""

from __future__ import annotations

import uuid

import pytest
from ai.context.builder import (
    AgentContext,
    ChatMessage,
    ContextBuilder,
    IntelligenceContext,
    MemoryEntry,
    RepositoryFile,
    SymbolContext,
    TargetSnippet,
    _format_chunk,
    count_tokens,
)
from ai.retrieval.base import CodeChunk

# ===========================================================================
# Helpers / factories
# ===========================================================================


def _make_chunk(
    file_path: str = "src/auth.py",
    content: str = "def authenticate(user, pw): ...",
    start_line: int = 1,
    end_line: int = 10,
    score: float = 0.9,
) -> CodeChunk:
    return CodeChunk(
        id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        file_id=uuid.uuid4(),
        symbol_id=None,
        content=content,
        token_count=len(content.split()),
        start_line=start_line,
        end_line=end_line,
        content_hash="abc123",
        score=score,
        file_path=file_path,
    )


def _make_memory(
    id: str = "mem-1",
    content: str = "Use SQLAlchemy for all DB access.",
    type: str = "architecture",
    created_at: str = "2024-01-01T00:00:00Z",
) -> MemoryEntry:
    return MemoryEntry(id=id, content=content, type=type, created_at=created_at)


def _make_message(role: str = "user", content: str = "Hello") -> ChatMessage:
    return ChatMessage(role=role, content=content)


def _make_file(path: str = "src/auth.py") -> RepositoryFile:
    return RepositoryFile(
        id=str(uuid.uuid4()),
        path=path,
        language="python",
        size_bytes=1024,
        line_count=50,
    )


# ===========================================================================
# 1–3: count_tokens
# ===========================================================================


class TestCountTokens:
    def test_count_tokens_non_empty(self):
        assert count_tokens("hello world") > 0

    def test_count_tokens_empty_string(self):
        assert count_tokens("") == 0

    def test_count_tokens_deterministic(self):
        text = "def authenticate(user: str, password: str) -> bool: ..."
        assert count_tokens(text) == count_tokens(text)


# ===========================================================================
# 4–7: _dedup_memory
# ===========================================================================


class TestDedupMemory:
    def test_dedup_removes_duplicate_ids(self):
        entries = [
            _make_memory(id="m1", content="first"),
            _make_memory(id="m1", content="second"),  # same id — wins
        ]
        result = ContextBuilder._dedup_memory(entries)
        assert len(result) == 1
        assert result[0].content == "second"

    def test_dedup_sorted_by_created_at_desc(self):
        entries = [
            _make_memory(id="m1", created_at="2024-01-01T00:00:00Z"),
            _make_memory(id="m2", created_at="2024-03-01T00:00:00Z"),
            _make_memory(id="m3", created_at="2024-02-01T00:00:00Z"),
        ]
        result = ContextBuilder._dedup_memory(entries)
        dates = [e.created_at for e in result]
        assert dates == sorted(dates, reverse=True)

    def test_dedup_empty_list(self):
        assert ContextBuilder._dedup_memory([]) == []

    def test_dedup_preserves_unique_entries(self):
        entries = [
            _make_memory(id="m1"),
            _make_memory(id="m2"),
            _make_memory(id="m3"),
        ]
        result = ContextBuilder._dedup_memory(entries)
        assert len(result) == 3


# ===========================================================================
# 8–11: _fit_history
# ===========================================================================


class TestFitHistory:
    def test_fit_history_all_fit(self):
        messages = [_make_message(content="Hello"), _make_message(content="World")]
        tokens, kept = ContextBuilder._fit_history(messages, budget=10_000)
        assert kept == messages
        assert tokens > 0

    def test_fit_history_drops_oldest(self):
        # One very long message + one short; budget only fits one
        long_msg = _make_message(content="x " * 5000)
        short_msg = _make_message(content="Hi")
        # Process newest first → short_msg fits, long_msg does not
        _tokens, kept = ContextBuilder._fit_history(
            [long_msg, short_msg], budget=50
        )
        assert kept == [short_msg]

    def test_fit_history_empty(self):
        tokens, kept = ContextBuilder._fit_history([], budget=10_000)
        assert tokens == 0
        assert kept == []

    def test_fit_history_chronological_order(self):
        messages = [
            _make_message(role="user", content="First question"),
            _make_message(role="assistant", content="First answer"),
            _make_message(role="user", content="Second question"),
        ]
        _, kept = ContextBuilder._fit_history(messages, budget=10_000)
        assert kept == messages  # original order preserved


# ===========================================================================
# 12–15: _fit_items
# ===========================================================================


class TestFitItems:
    def test_fit_items_all_fit(self):
        chunks = [_make_chunk(content="short") for _ in range(3)]
        tokens, kept = ContextBuilder._fit_items(chunks, 10_000, _format_chunk)
        assert kept == chunks
        assert tokens > 0

    def test_fit_items_truncates_tail(self):
        big_content = "word " * 2000  # ~2000 tokens
        chunks = [_make_chunk(content=big_content) for _ in range(5)]
        _tokens, kept = ContextBuilder._fit_items(chunks, 4_000, _format_chunk)
        assert len(kept) < 5  # some dropped

    def test_fit_items_empty(self):
        tokens, kept = ContextBuilder._fit_items([], 10_000, _format_chunk)
        assert tokens == 0
        assert kept == []

    def test_fit_items_single_oversized_dropped(self):
        huge_chunk = _make_chunk(content="token " * 10_000)
        tokens, kept = ContextBuilder._fit_items([huge_chunk], 10, _format_chunk)
        assert kept == []
        assert tokens == 0


# ===========================================================================
# 16–25: ContextBuilder.build
# ===========================================================================


class TestContextBuilderBuild:
    def setup_method(self):
        self.builder = ContextBuilder(max_context_tokens=100_000)

    def test_build_returns_agent_context(self):
        ctx = self.builder.build(chunks=[], memory=[], history=[])
        assert isinstance(ctx, AgentContext)

    def test_build_deduplicates_memory(self):
        memory = [
            _make_memory(id="dup", content="first"),
            _make_memory(id="dup", content="second"),
        ]
        ctx = self.builder.build(chunks=[], memory=memory, history=[])
        assert len(ctx.memory_chunks) == 1
        assert ctx.memory_chunks[0].content == "second"

    def test_build_memory_sorted_newest_first(self):
        memory = [
            _make_memory(id="m1", created_at="2024-01-01T00:00:00Z"),
            _make_memory(id="m2", created_at="2024-06-01T00:00:00Z"),
            _make_memory(id="m3", created_at="2024-03-01T00:00:00Z"),
        ]
        ctx = self.builder.build(chunks=[], memory=memory, history=[])
        dates = [e.created_at for e in ctx.memory_chunks]
        assert dates == sorted(dates, reverse=True)

    def test_build_total_tokens_positive(self):
        chunks = [_make_chunk(content="def foo(): pass")]
        memory = [_make_memory(content="Use SQLAlchemy.")]
        ctx = self.builder.build(chunks=chunks, memory=memory, history=[])
        assert ctx.total_tokens > 0

    def test_build_total_tokens_within_limit(self):
        builder = ContextBuilder(max_context_tokens=5_000)
        # Lots of content — builder must truncate
        chunks = [_make_chunk(content="code " * 500) for _ in range(20)]
        ctx = builder.build(chunks=chunks, memory=[], history=[])
        assert ctx.total_tokens <= 5_000

    def test_build_truncates_chunks_on_overflow(self):
        builder = ContextBuilder(max_context_tokens=200)
        chunks = [_make_chunk(content="token " * 500) for _ in range(5)]
        ctx = builder.build(chunks=chunks, memory=[], history=[])
        # With 200 token limit and 500-token chunks, we expect truncation
        assert len(ctx.code_chunks) < 5

    def test_build_related_files_preserved(self):
        files = [_make_file("src/auth.py"), _make_file("src/routes.py")]
        ctx = self.builder.build(chunks=[], memory=[], history=[], related_files=files)
        assert ctx.related_files == files

    def test_build_history_preserves_recent(self):
        # Budget: overhead=500, so history budget = 1000-500 = 500 tokens.
        # "old "*200 ≈ 600 tokens → doesn't fit. "Hi" ≈ 1 token → fits.
        builder = ContextBuilder(max_context_tokens=1_000)
        messages = [
            _make_message(content="old " * 200),
            _make_message(content="Hi"),   # newest — should be kept
        ]
        ctx = builder.build(chunks=[], memory=[], history=messages)
        contents = [m.content for m in ctx.recent_history]
        assert "Hi" in contents

    def test_build_empty_inputs(self):
        ctx = self.builder.build(chunks=[], memory=[], history=[])
        assert ctx.code_chunks == []
        assert ctx.memory_chunks == []
        assert ctx.recent_history == []
        assert ctx.related_files == []
        # total_tokens == overhead only
        assert ctx.total_tokens == ContextBuilder._OVERHEAD_TOKENS

    def test_build_related_files_default_none(self):
        ctx = self.builder.build(chunks=[], memory=[], history=[])
        assert ctx.related_files == []


# ===========================================================================
# 26–30: render_repository_data
# ===========================================================================


class TestRenderRepositoryData:
    def setup_method(self):
        self.builder = ContextBuilder()

    def _build_with(self, chunks=None, memory=None) -> AgentContext:
        return self.builder.build(
            chunks=chunks or [],
            memory=memory or [],
            history=[],
        )

    def test_render_has_repository_data_header(self):
        ctx = self._build_with(chunks=[_make_chunk()])
        rendered = self.builder.render_repository_data(ctx)
        assert "REPOSITORY DATA:" in rendered

    def test_render_has_memory_section(self):
        ctx = self._build_with(memory=[_make_memory()])
        rendered = self.builder.render_repository_data(ctx)
        assert "MEMORY:" in rendered

    def test_render_no_memory_section_when_empty(self):
        ctx = self._build_with(chunks=[_make_chunk()], memory=[])
        rendered = self.builder.render_repository_data(ctx)
        assert "MEMORY:" not in rendered

    def test_render_chunk_file_path_present(self):
        chunk = _make_chunk(file_path="backend/auth/service.py")
        ctx = self._build_with(chunks=[chunk])
        rendered = self.builder.render_repository_data(ctx)
        assert "backend/auth/service.py" in rendered

    def test_render_empty_context(self):
        ctx = self._build_with(chunks=[], memory=[])
        rendered = self.builder.render_repository_data(ctx)
        assert rendered == ""


# ===========================================================================
# 31–40: SDE-3 Robustness & Production Features
# ===========================================================================


class TestSDE3Features:
    def test_count_tokens_special_tokens_safe(self):
        # Untrusted repo or prompt text with special tokens must not raise ValueError
        special_text = "def test(): return '<|endoftext|>' and '<|fim_prefix|>'"
        assert count_tokens(special_text) > 0

    def test_context_builder_config_validation(self):
        with pytest.raises(ValueError, match="positive"):
            ContextBuilder(max_context_tokens=-1)
        with pytest.raises(ValueError, match="positive"):
            ContextBuilder(max_context_tokens=0)
        with pytest.raises(ValueError, match="negative"):
            ContextBuilder(overhead_tokens=-10)

    def test_build_with_none_arguments(self):
        builder = ContextBuilder(max_context_tokens=10_000)
        ctx = builder.build(chunks=None, memory=None, history=None, related_files=None)
        assert ctx.code_chunks == []
        assert ctx.memory_chunks == []
        assert ctx.recent_history == []
        assert ctx.related_files == []
        assert ctx.is_empty is True
        assert ctx.total_tokens == builder.overhead_tokens

    def test_build_normalizes_dict_history(self):
        builder = ContextBuilder(max_context_tokens=10_000)
        raw_history = [
            {"role": "user", "content": "How does auth work?"},
            {"role": "assistant", "content": "Auth uses JWTs."},
        ]
        ctx = builder.build(chunks=[], memory=[], history=raw_history)
        assert len(ctx.recent_history) == 2
        assert ctx.recent_history[0].role == "user"
        assert ctx.recent_history[1].role == "assistant"

    def test_token_breakdown_metadata(self):
        builder = ContextBuilder(max_context_tokens=50_000)
        chunks = [_make_chunk(content="def foo(): pass")]
        memory = [_make_memory(content="Architecture note")]
        history = [_make_message(content="Hello")]
        ctx = builder.build(chunks=chunks, memory=memory, history=history)

        assert ctx.chunk_tokens > 0
        assert ctx.memory_tokens > 0
        assert ctx.history_tokens > 0
        assert ctx.overhead_tokens == 500
        assert ctx.total_tokens == (
            ctx.overhead_tokens
            + ctx.history_tokens
            + ctx.memory_tokens
            + ctx.chunk_tokens
        )

        summary = ctx.summary()
        assert summary["code_chunks_count"] == 1
        assert summary["memory_chunks_count"] == 1
        assert summary["recent_history_count"] == 1
        assert summary["total_tokens"] == ctx.total_tokens

    def test_domain_serialization(self):
        msg = ChatMessage(role="user", content="Hi")
        assert msg.to_dict() == {"role": "user", "content": "Hi"}
        msg_from_dict = ChatMessage.from_dict({"role": "assistant", "content": "Hello"})
        assert msg_from_dict.role == "assistant"

        mem = _make_memory(id="m-1", content="Note", type="rule", created_at="2024-01-01T00:00:00Z")
        mem_dict = mem.to_dict()
        assert mem_dict["id"] == "m-1"
        assert MemoryEntry.from_dict(mem_dict).id == "m-1"

        rf = _make_file(path="main.py")
        rf_dict = rf.to_dict()
        assert rf_dict["path"] == "main.py"
        assert RepositoryFile.from_dict(rf_dict).path == "main.py"

    def test_additional_renderers(self):
        builder = ContextBuilder()
        ctx = builder.build(
            chunks=[_make_chunk(file_path="src/main.py")],
            memory=[_make_memory(type="rule", content="Follow PEP 8")],
            history=[_make_message(role="user", content="Hello")],
            related_files=[_make_file(path="src/main.py")],
        )

        history_render = builder.render_history_section(ctx)
        assert "USER: Hello" in history_render

        files_render = builder.render_related_files_section(ctx)
        assert "RELATED FILES:" in files_render
        assert "src/main.py" in files_render

    def test_dedup_memory_handles_non_string_and_missing_timestamps(self):
        mem1 = MemoryEntry(id=123, content="First", type="rule", created_at=None)  # type: ignore
        mem2 = MemoryEntry(id="123", content="Second", type="rule", created_at="2024-01-01T00:00:00Z")
        result = ContextBuilder._dedup_memory([mem1, mem2])
        assert len(result) == 1
        assert result[0].content == "Second"

    def test_intelligence_context_builder_and_render(self):
        builder = ContextBuilder()
        target = TargetSnippet(
            file_path="backend/app/auth.py",
            content="def login(): return 'token'",
            start_line=10,
            end_line=15,
            symbol_name="login",
            language="python",
        )
        symbols = [
            SymbolContext(
                name="verify_credentials",
                kind="caller",
                file_path="backend/app/api.py",
                start_line=20,
                end_line=25,
                content="verify_credentials(user, pwd)",
            )
        ]
        files = [RepositoryFile(id="1", path="backend/app/auth.py", language="python", size_bytes=100, line_count=30)]
        rules = ["Never log passwords"]

        ctx = builder.build_intelligence_context(
            target=target,
            related_symbols=symbols,
            repository_files=files,
            project_rules=rules,
            token_budget=5000,
        )

        assert ctx.target.symbol_name == "login"
        assert len(ctx.related_symbols) == 1
        assert ctx.total_tokens > 0
        assert ctx.token_budget == 5000
        assert "target" in ctx.to_dict()

        rendered = builder.render_intelligence_data(ctx)
        assert "TARGET CODE UNDER ANALYSIS:" in rendered
        assert "backend/app/auth.py" in rendered
        assert "RELATED SYMBOLS & CALLERS:" in rendered
        assert "verify_credentials" in rendered
        assert "PROJECT RULES & CONVENTIONS:" in rendered
        assert "Never log passwords" in rendered

