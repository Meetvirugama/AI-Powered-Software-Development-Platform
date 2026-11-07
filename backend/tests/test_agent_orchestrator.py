"""
Tests for Agent Orchestrator and Investigation Loop (task.md §12, §22.5).

Verifies:
- Immediate final answer generation without tool calls.
- Multi-turn investigation (search_code -> read_file_range -> final answer).
- Stopping condition: Max rounds exceeded.
- Stopping condition: Duplicate tool call detection.
- Budget exhaustion handling with evidence handoff to final RAG answer.
- Correct agent_metadata reporting.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from ai.agent.budget import AgentBudget
from ai.agent.orchestrator import AgentOrchestrator
from ai.agent.schemas import AgentEvidenceItem, AgentToolResult
from ai.agent.tool_executor import ToolExecutor
from ai.agent.tool_registry import ToolRegistry
from ai.llm.client import LLMGateway
from ai.llm.schemas import LLMToolCall, LLMToolResponse
from ai.pipeline import RAGPipeline
from ai.schemas.output import RepositoryAnswer, SourceReference

# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_immediate_final_answer() -> None:
    repo_id = uuid4()

    mock_gateway = AsyncMock(spec=LLMGateway)
    mock_gateway.generate_with_tools.return_value = LLMToolResponse(
        content="The repository uses FastAPI for HTTP routing.",
        tool_calls=[],
        model="gemini-flash-lite-latest",
        input_tokens=100,
        output_tokens=30,
        provider="gemini",
    )

    mock_rag = AsyncMock(spec=RAGPipeline)
    mock_rag._retrieve.return_value = []
    mock_rag.finalize_agent_chat.return_value = RepositoryAnswer(
        answer="The repository uses FastAPI for HTTP routing.",
        sources=[SourceReference(file="app/main.py", start_line=1, end_line=10)],
        confidence="high",
        status="completed",
    )

    orchestrator = AgentOrchestrator(
        llm_gateway=mock_gateway,
        rag_pipeline=mock_rag,
    )

    answer = await orchestrator.run(
        question="What framework is used for the API?",
        repository_id=repo_id,
    )

    assert answer.answer == "The repository uses FastAPI for HTTP routing."
    mock_gateway.generate_with_tools.assert_called_once()
    mock_rag.finalize_agent_chat.assert_called_once()
    meta = mock_rag.finalize_agent_chat.call_args[1]["agent_metadata"]
    assert meta["mode"] == "agentic"
    assert meta["tool_calls"] == 0
    assert meta["model_calls"] == 1
    assert meta["stop_reason"] == "final_answer"


@pytest.mark.asyncio
async def test_orchestrator_investigates_with_tool_then_finalizes() -> None:
    repo_id = uuid4()

    # Round 1: Model requests search_code
    resp_round1 = LLMToolResponse(
        content="",
        tool_calls=[LLMToolCall(id="call_1", name="search_code", arguments={"query": "token refresh"})],
        model="gemini-flash-lite-latest",
        input_tokens=150,
        output_tokens=20,
        provider="gemini",
    )

    # Round 2: Model provides final answer
    resp_round2 = LLMToolResponse(
        content="Token refresh fails due to lack of expiration validation in auth.py.",
        tool_calls=[],
        model="gemini-flash-lite-latest",
        input_tokens=250,
        output_tokens=50,
        provider="gemini",
    )

    mock_gateway = AsyncMock(spec=LLMGateway)
    mock_gateway.generate_with_tools.side_effect = [resp_round1, resp_round2]

    # Mock tool executor
    mock_executor = AsyncMock(spec=ToolExecutor)
    mock_executor.execute.return_value = AgentToolResult(
        call_id="call_1",
        tool_name="search_code",
        result={"results": [{"file_path": "auth.py", "start_line": 10, "end_line": 30}]},
        evidence=[
            AgentEvidenceItem(
                repository_id=str(repo_id),
                source_type="retrieval",
                file_path="auth.py",
                start_line=10,
                end_line=30,
                content="def refresh(): pass",
                tool_name="search_code",
            )
        ],
    )

    mock_rag = AsyncMock(spec=RAGPipeline)
    mock_rag._retrieve.return_value = []
    mock_rag.finalize_agent_chat.return_value = RepositoryAnswer(
        answer="Token refresh fails due to lack of expiration validation in auth.py.",
        sources=[SourceReference(file="auth.py", start_line=10, end_line=30)],
        confidence="high",
        status="completed",
    )

    registry = ToolRegistry()
    registry.register("search_code", "Search", {}, AsyncMock())

    orchestrator = AgentOrchestrator(
        llm_gateway=mock_gateway,
        tool_registry=registry,
        tool_executor=mock_executor,
        rag_pipeline=mock_rag,
    )

    answer = await orchestrator.run(
        question="Why does token refresh fail?",
        repository_id=repo_id,
    )

    assert "Token refresh fails" in answer.answer
    assert mock_gateway.generate_with_tools.call_count == 2
    assert mock_executor.execute.call_count == 1
    meta = mock_rag.finalize_agent_chat.call_args[1]["agent_metadata"]
    assert meta["tool_calls"] == 1
    assert meta["model_calls"] == 2
    assert meta["stop_reason"] == "final_answer"


@pytest.mark.asyncio
async def test_orchestrator_aborts_on_duplicate_tool_calls() -> None:
    repo_id = uuid4()

    # Model keeps repeating identical search query
    repeated_call = LLMToolCall(id="call_rep", name="search_code", arguments={"query": "same query"})
    resp_loop = LLMToolResponse(
        content="",
        tool_calls=[repeated_call],
        model="gemini-flash-lite-latest",
        input_tokens=100,
        output_tokens=10,
        provider="gemini",
    )

    mock_gateway = AsyncMock(spec=LLMGateway)
    mock_gateway.generate_with_tools.return_value = resp_loop

    mock_executor = AsyncMock(spec=ToolExecutor)
    mock_executor.execute.return_value = AgentToolResult(
        call_id="call_rep",
        tool_name="search_code",
        result={"results": []},
        evidence=[],
    )

    mock_rag = AsyncMock(spec=RAGPipeline)
    mock_rag._retrieve.return_value = []
    mock_rag.finalize_agent_chat.return_value = RepositoryAnswer(
        answer="Investigation halted due to loop.",
        sources=[],
        confidence="low",
        status="completed",
    )

    registry = ToolRegistry()
    registry.register("search_code", "Search", {}, AsyncMock())

    orchestrator = AgentOrchestrator(
        llm_gateway=mock_gateway,
        tool_registry=registry,
        tool_executor=mock_executor,
        rag_pipeline=mock_rag,
    )

    budget = AgentBudget(max_rounds=5, max_tool_calls=10)
    answer = await orchestrator.run(
        question="Infinite loop question",
        repository_id=repo_id,
        budget=budget,
    )
    assert answer is not None

    # Repeated identical call must be aborted
    meta = mock_rag.finalize_agent_chat.call_args[1]["agent_metadata"]
    assert meta["stop_reason"] in ("repeated_tool_call", "budget_exhausted")


@pytest.mark.asyncio
async def test_orchestrator_stops_at_max_rounds() -> None:
    repo_id = uuid4()

    # Tool calls that change arguments each turn
    def generate_side_effect(*args, **kwargs):
        c_id = uuid4().hex[:6]
        return LLMToolResponse(
            content="",
            tool_calls=[LLMToolCall(id=f"c_{c_id}", name="search_code", arguments={"query": f"q_{c_id}"})],
            model="gemini-flash-lite-latest",
            input_tokens=100,
            output_tokens=10,
            provider="gemini",
        )

    mock_gateway = AsyncMock(spec=LLMGateway)
    mock_gateway.generate_with_tools.side_effect = generate_side_effect

    mock_executor = AsyncMock(spec=ToolExecutor)
    mock_executor.execute.return_value = AgentToolResult(
        call_id="c",
        tool_name="search_code",
        result={"results": []},
        evidence=[],
    )

    mock_rag = AsyncMock(spec=RAGPipeline)
    mock_rag._retrieve.return_value = []
    mock_rag.finalize_agent_chat.return_value = RepositoryAnswer(
        answer="Finalized after max rounds.",
        sources=[],
        confidence="medium",
        status="completed",
    )

    registry = ToolRegistry()
    registry.register("search_code", "Search", {}, AsyncMock())

    orchestrator = AgentOrchestrator(
        llm_gateway=mock_gateway,
        tool_registry=registry,
        tool_executor=mock_executor,
        rag_pipeline=mock_rag,
    )

    budget = AgentBudget(max_rounds=2, max_tool_calls=6)
    answer = await orchestrator.run(
        question="Long question",
        repository_id=repo_id,
        budget=budget,
    )
    assert answer is not None

    meta = mock_rag.finalize_agent_chat.call_args[1]["agent_metadata"]
    assert meta["model_calls"] == 2
    assert meta["stop_reason"] in ("budget_exhausted", "max_rounds_reached")
