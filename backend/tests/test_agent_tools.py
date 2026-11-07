"""
Tests for Central Tool Registry and Repository Tools (task.md §10, §22.4).

Verifies:
- Tool registry registration and read-only policy enforcement.
- search_code execution with simulated chunks.
- read_file_range execution with line-accurate reconstruction and path security.
- get_symbol execution with candidate lookup and definition excerpt.
- find_callers execution with caller graph resolution.
- Tool executor timeouts and error shielding.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from ai.agent.errors import AgentToolValidationError
from ai.agent.schemas import AgentToolContext
from ai.agent.tool_executor import ToolExecutor
from ai.agent.tool_registry import ToolRegistry, create_default_registry
from ai.agent.tools.find_callers import run_find_callers
from ai.agent.tools.get_symbol import run_get_symbol
from ai.agent.tools.read_file_range import run_read_file_range
from ai.agent.tools.search_code import run_search_code
from ai.llm.schemas import LLMToolCall
from ai.retrieval.base import CodeChunk

# ---------------------------------------------------------------------------
# Registry Tests
# ---------------------------------------------------------------------------


def test_registry_registers_core_tools() -> None:
    registry = create_default_registry()
    defs = registry.get_definitions()
    tool_names = {d.name for d in defs}

    assert "search_code" in tool_names
    assert "read_file_range" in tool_names
    assert "get_symbol" in tool_names
    assert "find_callers" in tool_names
    assert len(defs) == 4


def test_registry_rejects_duplicate_or_write_tools() -> None:
    registry = ToolRegistry()
    registry.register("search_code", "Search", {}, AsyncMock())

    with pytest.raises(AgentToolValidationError):
        registry.register("search_code", "Duplicate", {}, AsyncMock())

    with pytest.raises(AgentToolValidationError):
        registry.register("delete_file", "Delete", {}, AsyncMock())

    with pytest.raises(AgentToolValidationError):
        registry.register("execute_shell", "Exec", {}, AsyncMock())


# ---------------------------------------------------------------------------
# search_code Tool Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_code_tool() -> None:
    repo_id = uuid4()
    mock_chunk = CodeChunk(
        id=uuid4(),
        repository_id=repo_id,
        file_id=uuid4(),
        symbol_id=None,
        content="def refresh_token(): return 'new'",
        token_count=10,
        start_line=20,
        end_line=30,
        content_hash="hash123",
        score=0.92,
        file_path="auth/jwt.py",
    )

    mock_retriever = AsyncMock()
    mock_retriever.retrieve.return_value = [mock_chunk]

    ctx = AgentToolContext(
        repository_id=repo_id,
        retriever=mock_retriever,
    )

    res = await run_search_code("c1", {"query": "refresh token", "top_k": 3}, ctx)
    assert res.is_error is False
    assert res.result["total"] == 1
    assert res.result["results"][0]["file_path"] == "auth/jwt.py"
    assert len(res.evidence) == 1
    assert res.evidence[0].source_type == "retrieval"
    assert res.evidence[0].file_path == "auth/jwt.py"


# ---------------------------------------------------------------------------
# read_file_range Tool Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_file_range_tool() -> None:
    repo_id = uuid4()
    file_id = uuid4()

    mock_file = MagicMock()
    mock_file.id = file_id
    mock_file.path = "services/auth.py"
    mock_file.line_count = 100

    chunk = MagicMock()
    chunk.content = "line 1\nline 2\nline 3\nline 4\nline 5\n"
    chunk.start_line = 1
    chunk.end_line = 5
    chunk.metadata = {"chunk_type": "block"}

    mock_session = AsyncMock()

    # Configure run_db_query to return mock_file on first call and [chunk] on second
    async def mock_execute(stmt):
        return MagicMock()

    mock_session.execute = mock_execute

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "ai.agent.tools.read_file_range.run_db_query",
            AsyncMock(side_effect=[mock_file, [chunk]]),
        )

        ctx = AgentToolContext(
            repository_id=repo_id,
            db_session=mock_session,
        )

        res = await run_read_file_range(
            "c2",
            {"file_path": "services/auth.py", "start_line": 2, "end_line": 4},
            ctx,
        )
        assert res.is_error is False
        assert res.result["file_path"] == "services/auth.py"
        assert "line 2" in res.result["content"]
        assert len(res.evidence) == 1
        assert res.evidence[0].source_type == "file_read"


# ---------------------------------------------------------------------------
# get_symbol Tool Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_symbol_tool() -> None:
    repo_id = uuid4()
    sym_id = uuid4()
    file_id = uuid4()

    mock_sym = MagicMock()
    mock_sym.id = sym_id
    mock_sym.name = "refresh_access_token"
    mock_sym.kind = "function"
    mock_sym.signature = "def refresh_access_token(user_id: str) -> str"
    mock_sym.file_id = file_id
    mock_sym.start_line = 40
    mock_sym.end_line = 60

    chunk = MagicMock()
    chunk.content = "def refresh_access_token(user_id: str) -> str:\n    return 'refreshed'\n"
    chunk.start_line = 40
    chunk.end_line = 60
    chunk.metadata = {"chunk_type": "function"}

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "ai.agent.tools.get_symbol.run_db_query",
            AsyncMock(side_effect=[[(mock_sym, "auth/service.py")], [chunk]]),
        )

        ctx = AgentToolContext(
            repository_id=repo_id,
            db_session=AsyncMock(),
        )

        res = await run_get_symbol("c3", {"symbol_name": "refresh_access_token"}, ctx)
        assert res.is_error is False
        assert res.result["found"] is True
        assert res.result["symbol"]["name"] == "refresh_access_token"
        assert len(res.evidence) == 1
        assert res.evidence[0].source_type == "symbol"


# ---------------------------------------------------------------------------
# find_callers Tool Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_callers_tool() -> None:
    repo_id = uuid4()
    target_sym = MagicMock()
    target_sym.id = uuid4()
    target_sym.name = "verify_token"

    caller_row = (
        "calls",
        "login_handler",
        "function",
        15,
        35,
        "api/v1/auth.py",
        uuid4(),
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "ai.agent.tools.find_callers.run_db_query",
            AsyncMock(side_effect=[target_sym, [caller_row]]),
        )

        ctx = AgentToolContext(
            repository_id=repo_id,
            db_session=AsyncMock(),
        )

        res = await run_find_callers("c4", {"symbol_name": "verify_token"}, ctx)
        assert res.is_error is False
        assert res.result["total_callers_found"] == 1
        assert res.result["callers"][0]["caller_symbol"] == "login_handler"
        assert len(res.evidence) == 1
        assert res.evidence[0].source_type == "caller"


# ---------------------------------------------------------------------------
# Tool Executor Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_executor_handles_timeout() -> None:
    registry = ToolRegistry()

    async def slow_handler(*args):
        await asyncio.sleep(0.5)
        return MagicMock()

    registry.register("slow_tool", "Slow", {}, slow_handler)
    executor = ToolExecutor(registry, default_timeout_seconds=0.05)

    tc = LLMToolCall(id="c_slow", name="slow_tool", arguments={})
    ctx = AgentToolContext(repository_id=uuid4())

    res = await executor.execute(tc, ctx)
    assert res.is_error is True
    assert "exceeded" in res.error_message


@pytest.mark.asyncio
async def test_tool_executor_rejects_unknown_tool() -> None:
    registry = create_default_registry()
    executor = ToolExecutor(registry)

    tc = LLMToolCall(id="c_unknown", name="unregistered_tool", arguments={})
    ctx = AgentToolContext(repository_id=uuid4())

    res = await executor.execute(tc, ctx)
    assert res.is_error is True
    assert "not recognized" in res.error_message
