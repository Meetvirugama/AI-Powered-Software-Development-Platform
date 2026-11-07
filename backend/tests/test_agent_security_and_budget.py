"""
Security, Budget, and Concurrency Tests for Bounded Agentic Repository Chat.
Verifies Phase 6 requirements:
- Secret redaction in tool inputs and outputs
- Hard budget limits (tool calls, rounds, model calls, tokens, timeouts)
- Repeated tool call guardrails
- Isolated concurrent agent runs
"""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from ai.agent.budget import AgentBudget
from ai.agent.orchestrator import AgentOrchestrator
from ai.agent.policy import sanitize_and_redact
from ai.agent.tool_registry import create_default_registry
from ai.llm.schemas import LLMToolRequest, LLMToolResponse
from ai.schemas.output import RepositoryAnswer, SourceReference


@pytest.mark.asyncio
async def test_secret_redaction_in_tool_output():
    raw_output = (
        "Database credentials found: postgresql://admin:ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456@db:5432/prod\n"
        "AWS Secret: AKIAIOSFODNN7EXAMPLE\n"
        "Private Key:\n-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0\n-----END RSA PRIVATE KEY-----"
    )
    redacted = sanitize_and_redact(raw_output)
    assert "ghp_" not in redacted
    assert "AKIAIOSFODNN7EXAMPLE" not in redacted
    assert "BEGIN RSA PRIVATE KEY" not in redacted
    assert "[REDACTED" in redacted


@pytest.mark.asyncio
async def test_budget_enforces_tool_call_limit():
    budget = AgentBudget(max_tool_calls=3)
    assert budget.can_continue() is True
    assert budget.record_tool_call("tool1", {"a": 1}) is True
    assert budget.record_tool_call("tool2", {"b": 2}) is True
    assert budget.record_tool_call("tool3", {"c": 3}) is True
    assert budget.can_continue() is False


@pytest.mark.asyncio
async def test_budget_enforces_round_limit():
    budget = AgentBudget(max_rounds=2)
    assert budget.can_continue() is True
    budget.start_round()
    assert budget.can_continue() is True
    budget.start_round()
    assert budget.can_continue() is False


@pytest.mark.asyncio
async def test_budget_enforces_token_limits():
    budget = AgentBudget(max_input_tokens=1000, max_output_tokens=200)
    assert budget.can_continue() is True
    budget.record_model_call(input_tokens=800, output_tokens=150)
    assert budget.can_continue() is True
    budget.record_model_call(input_tokens=300, output_tokens=60)
    assert budget.can_continue() is False


@pytest.mark.asyncio
async def test_duplicate_tool_call_detection():
    budget = AgentBudget()
    # 1st call: allowed
    assert budget.record_tool_call("search_code", {"query": "auth_token"}) is True
    assert budget.is_repeated_call("search_code", {"query": "auth_token"}) is False
    # 2nd call: allowed (retry)
    assert budget.record_tool_call("search_code", {"query": "auth_token"}) is True
    assert budget.is_repeated_call("search_code", {"query": "auth_token"}) is True
    # 3rd call: rejected duplicate
    assert budget.record_tool_call("search_code", {"query": "auth_token"}) is False


@pytest.mark.asyncio
async def test_concurrent_agent_requests_isolation():
    """Verify concurrent agent executions do not leak state or budget between each other."""
    registry = create_default_registry()

    mock_llm_gateway = MagicMock()

    async def fake_generate(req: LLMToolRequest):
        user_msg = next((m.content for m in req.messages if m.role == "user"), "")
        return LLMToolResponse(
            content=f"Answer for {user_msg}",
            model="gemini-2.5-flash",
            provider="gemini",
            prompt_tokens=100,
            completion_tokens=50,
            tool_calls=[],
        )

    mock_llm_gateway.generate_with_tools = AsyncMock(side_effect=fake_generate)

    mock_rag_pipeline = MagicMock()

    async def fake_finalize(question, repository_id, evidence_chunks, history, agent_metadata):
        return RepositoryAnswer(
            answer=f"Final answer for {question}",
            sources=[SourceReference(file=f"{repository_id}/main.py", start_line=1, end_line=10)],
            confidence="high",
            status="completed",
            agent_metadata=agent_metadata,
        )

    mock_rag_pipeline.finalize_agent_chat = AsyncMock(side_effect=fake_finalize)
    mock_rag_pipeline._retrieve = AsyncMock(return_value=[])

    orchestrator = AgentOrchestrator(
        llm_gateway=mock_llm_gateway,
        tool_registry=registry,
        rag_pipeline=mock_rag_pipeline,
    )

    async def run_chat(repo_id, q_text):
        return await orchestrator.run(
            question=q_text,
            repository_id=repo_id,
        )

    repo_ids = [uuid.uuid4() for _ in range(5)]
    tasks = [
        run_chat(repo_ids[i], f"Question {i}")
        for i in range(5)
    ]
    results = await asyncio.gather(*tasks)

    for i, res in enumerate(results):
        assert f"Final answer for Question {i}" in res.answer
        assert res.agent_metadata is not None
        assert res.agent_metadata["mode"] == "agentic"
        assert res.agent_metadata["model_calls"] == 1
        assert res.sources[0].file == f"{repo_ids[i]}/main.py"
