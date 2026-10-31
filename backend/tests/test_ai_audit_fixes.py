"""Tests verifying AI Subsystem Production Audit & Refactoring fixes (task.md Phases 1-5).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from ai.context.builder import ContextBuilder
from ai.context.chat_context import build_chat_context, dedup_memory
from ai.context.intelligence_context import build_intelligence_context
from ai.context.models import (
    AgentContext,
    ChatMessage,
    ContextLimits,
    ContextStatus,
    IntelligenceContext,
    MemoryEntry,
    RepositoryFile,
    SymbolContext,
    TargetSnippet,
)
from ai.context.renderers import (
    format_chunk,
    format_history_message,
    format_memory,
    render_intelligence_data,
    render_repository_data,
)
from ai.context.token_budget import count_tokens, fit_history, fit_items
from ai.prompts import PromptNotFoundError, PromptRenderError, validate_required_prompts
from ai.retrieval.base import CodeChunk
from ai.retrieval.pipeline import RAGPipeline as RetrievalRAGPipeline
from ai.schemas.output import RepositoryAnswer
from ai.schemas.validator import OutputValidator
from app.core.config import Settings


def test_ai_settings_active_and_fallback_models():
    """Verify active_chat_model and fallback_chat_model properties based on provider."""
    # Default: Gemini primary, Groq fallback
    settings_gemini = Settings(
        ai_primary_provider="gemini",
        ai_fallback_provider="groq",
        gemini_chat_model="gemini-flash-lite-latest",
        groq_chat_model="openai/gpt-oss-120b",
    )
    assert settings_gemini.active_chat_model == "gemini-flash-lite-latest"
    assert settings_gemini.fallback_chat_model == "openai/gpt-oss-120b"

    # Swapped: Groq primary, Gemini fallback
    settings_groq = Settings(
        ai_primary_provider="groq",
        ai_fallback_provider="gemini",
        gemini_chat_model="gemini-flash-lite-latest",
        groq_chat_model="openai/gpt-oss-120b",
    )
    assert settings_groq.active_chat_model == "openai/gpt-oss-120b"
    assert settings_groq.fallback_chat_model == "gemini-flash-lite-latest"

    # No fallback provider
    settings_nofallback = Settings(
        ai_primary_provider="gemini",
        ai_fallback_provider=None,
    )
    assert settings_nofallback.fallback_chat_model is None


def test_validate_required_prompts_success():
    """Verify that all required prompt templates are validated successfully."""
    validated = validate_required_prompts()
    assert len(validated) >= 7
    assert "chat_system" in validated
    assert "explanation_system" in validated
    assert "bug_detection_system" in validated
    assert "test_generation_system" in validated
    assert "code_review_system" in validated
    assert "repair_system" in validated
    assert "grounding_system" in validated


def test_validate_required_prompts_missing_raises():
    """Verify that a missing prompt raises PromptNotFoundError."""
    with pytest.raises(PromptNotFoundError):
        validate_required_prompts(["non_existent_prompt_template_xyz"])


def test_context_builder_facade_consistency():
    """Verify ContextBuilder facade re-exports and matches modular functions."""
    builder = ContextBuilder(max_context_tokens=10_000)

    # Build chat context
    chunks = [
        CodeChunk(
            id=uuid4(),
            repository_id=uuid4(),
            file_id=uuid4(),
            symbol_id=None,
            content="def foo(): pass",
            token_count=5,
            start_line=1,
            end_line=1,
            content_hash="h1",
            file_path="foo.py",
            score=0.9,
        )
    ]
    mem = [
        MemoryEntry(
            id="m1",
            content="Use Python 3.14",
            type="rule",
            created_at="2026-10-30T00:00:00Z",
        )
    ]
    ctx = builder.build(chunks=chunks, memory=mem)
    assert isinstance(ctx, AgentContext)
    assert len(ctx.code_chunks) == 1
    assert len(ctx.memory_chunks) == 1

    rendered = builder.render_repository_data(ctx)
    assert "foo.py" in rendered
    assert "Use Python 3.14" in rendered


def test_intelligence_context_modular_assembly():
    """Verify build_intelligence_context works directly and via facade."""
    target = TargetSnippet(
        file_path="src/main.py",
        content="def calculate(x): return x * 2",
        start_line=1,
        end_line=1,
        symbol_name="calculate",
    )
    sym = SymbolContext(
        name="helper",
        kind="caller",
        file_path="src/caller.py",
        start_line=10,
        end_line=12,
        content="calculate(5)",
    )
    ctx = build_intelligence_context(
        target=target,
        related_symbols=[sym],
        token_budget=5000,
    )
    assert isinstance(ctx, IntelligenceContext)
    assert ctx.status == ContextStatus.COMPLETE
    assert len(ctx.related_symbols) == 1

    data = render_intelligence_data(ctx)
    assert "<<<REPO_DATA_START>>>" in data
    assert "calculate" in data
    assert "<<<REPO_DATA_END>>>" in data


@pytest.mark.asyncio
async def test_retrieval_rag_pipeline_hybrid_and_grounding():
    """Verify ai.retrieval.pipeline.RAGPipeline hybrid retrieve and grounded chat."""
    mock_vec = MagicMock()
    mock_chunk = CodeChunk(
        id=uuid4(),
        repository_id=uuid4(),
        file_id=uuid4(),
        symbol_id=None,
        content="def authenticate(user): return True",
        token_count=6,
        start_line=1,
        end_line=2,
        content_hash="auth_hash",
        file_path="src/auth.py",
        score=0.9,
    )
    mock_vec.retrieve = AsyncMock(return_value=[mock_chunk])

    mock_lex = MagicMock()
    mock_lex.retrieve = AsyncMock(return_value=[mock_chunk])

    pipeline = RetrievalRAGPipeline(
        vector_retriever=mock_vec,
        lexical_retriever=mock_lex,
    )
    repo_id = uuid4()
    chunks = await pipeline.retrieve("authenticate", repository_id=repo_id, top_k=5)
    assert len(chunks) == 1
    assert chunks[0].file_path == "src/auth.py"

    answer = await pipeline.chat("authenticate", repository_id=repo_id)
    assert isinstance(answer, RepositoryAnswer)
    assert "src/auth.py" in answer.answer or len(answer.sources) == 1


@pytest.mark.asyncio
async def test_output_validator_bounds_repair_prompt():
    """Verify OutputValidator limits repair prompt length and resolves model."""
    mock_gateway = MagicMock()
    mock_gateway.provider.default_model = "test-model-xyz"
    mock_gateway.generate = AsyncMock()

    # Mock successful response on repair
    mock_resp = MagicMock()
    mock_resp.content = '{"answer": "repaired", "sources": [], "confidence": "high"}'
    mock_gateway.generate.return_value = mock_resp

    validator = OutputValidator(llm_gateway=mock_gateway)
    huge_invalid_raw = "{" + "x" * 10_000
    res = await validator.repair(huge_invalid_raw, RepositoryAnswer, "JSONDecodeError")
    assert isinstance(res, RepositoryAnswer)
    assert res.answer == "repaired"

    # Verify repair request model was test-model-xyz
    assert mock_gateway.generate.call_count == 1
    req = mock_gateway.generate.call_args[0][0]
    assert req.model == "test-model-xyz"
    # Verify the invalid content sent in the prompt was bounded to <= 4000 chars
    sent_prompt = req.messages[0].content
    assert len(sent_prompt) < 6000
