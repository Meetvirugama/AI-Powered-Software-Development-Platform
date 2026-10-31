"""Unit tests for Dev's Week 2 Day 2 CodeExplanationService engine.

Owner: Dev — W2, Day 2 Deliverable (Tested explanation service and prompt)
Reference: Docs/week2.md §6 (CodeExplanationService Requirements)

Acceptance Criteria:
- Explanation includes purpose, logic flow, key symbols, inputs/outputs, dependencies, assumptions.
- Prompt template enforces distinct facts vs inferences and no invented callers.
- Invalid AI output is repaired or raises LLMValidationError (no silent empty results).
- Unconfigured LLM gateway raises HTTP 503.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from ai.context.builder import ContextBuilder, TargetSnippet
from ai.interfaces import CodeExplanationServiceProtocol
from ai.llm.schemas import LLMResponse, LLMValidationError
from ai.services.explanation_service import CodeExplanationService
from app.core.errors import APIError
from app.schemas.analysis import AnalysisOptions, AnalysisTarget, CodeExplanation, ExplainCodeRequest
from tests.fixtures.w2_schema_examples import VALID_CODE_EXPLANATION_DICT


@pytest.fixture
def sample_explain_request() -> ExplainCodeRequest:
    return ExplainCodeRequest(
        target=AnalysisTarget(
            type="file",
            path="backend/app/core/retry.py",
            start_line=15,
            end_line=30,
        ),
        options=AnalysisOptions(max_context_tokens=1000),
    )


@pytest.fixture
def mock_llm_gateway() -> MagicMock:
    gateway = MagicMock()
    gateway.generate = AsyncMock()
    return gateway


@pytest.mark.asyncio
async def test_code_explanation_service_all_6_sections(
    mock_llm_gateway: MagicMock,
    sample_explain_request: ExplainCodeRequest,
) -> None:
    """Verifies that the service returns all 6 required explanation sections."""
    mock_llm_gateway.generate.return_value = LLMResponse(
        content=json.dumps(VALID_CODE_EXPLANATION_DICT),
        model="gemini-flash-lite-latest",
        usage={"prompt_tokens": 100, "completion_tokens": 80, "total_tokens": 180},
    )

    service = CodeExplanationService(llm_gateway=mock_llm_gateway)
    repo_id = uuid4()

    snippet = TargetSnippet(
        file_path="backend/app/core/retry.py",
        content="def calculate_backoff(): pass",
        start_line=15,
        end_line=30,
        symbol_name="calculate_backoff",
        language="python",
    )
    context = ContextBuilder().build_intelligence_context(target=snippet, token_budget=1000)

    result = await service.explain(repo_id, sample_explain_request, context=context)

    assert isinstance(result, CodeExplanation)
    # 1. Purpose
    assert "backoff" in result.purpose.lower()
    # 2. Logic Flow
    assert len(result.logic_flow) == 4
    # 3. Key Symbols
    assert len(result.key_symbols) == 2
    assert result.key_symbols[0].name == "calculate_backoff"
    # 4. Inputs and Outputs
    assert "attempt" in result.inputs_and_outputs
    # 5. Dependencies
    assert "random.uniform" in result.dependencies
    # 6. Assumptions and Limitations
    assert len(result.assumptions_and_limitations) == 2
    assert result.confidence == "high"


@pytest.mark.asyncio
async def test_code_explanation_service_repairs_malformed_fences(
    mock_llm_gateway: MagicMock,
    sample_explain_request: ExplainCodeRequest,
) -> None:
    """Verifies that markdown-fenced responses parse and self-heal cleanly."""
    fenced_raw = f"```json\n{json.dumps(VALID_CODE_EXPLANATION_DICT)}\n```"
    mock_llm_gateway.generate.return_value = LLMResponse(
        content=fenced_raw,
        model="gemini-flash-lite-latest",
    )

    service = CodeExplanationService(llm_gateway=mock_llm_gateway)
    result = await service.explain(uuid4(), sample_explain_request)

    assert isinstance(result, CodeExplanation)
    assert result.confidence == "high"


@pytest.mark.asyncio
async def test_code_explanation_service_repair_loop_succeeds_on_second_attempt(
    mock_llm_gateway: MagicMock,
    sample_explain_request: ExplainCodeRequest,
) -> None:
    """Verifies that if attempt 1 returns invalid JSON, attempt 2 repair succeeds."""
    mock_llm_gateway.generate.side_effect = [
        LLMResponse(content="not a valid json object", model="gemini-flash-lite-latest"),
        LLMResponse(content=json.dumps(VALID_CODE_EXPLANATION_DICT), model="gemini-flash-lite-latest"),
    ]

    service = CodeExplanationService(llm_gateway=mock_llm_gateway)
    result = await service.explain(uuid4(), sample_explain_request)

    assert isinstance(result, CodeExplanation)
    assert mock_llm_gateway.generate.call_count == 2


@pytest.mark.asyncio
async def test_code_explanation_service_repair_exhaustion_raises(
    mock_llm_gateway: MagicMock,
    sample_explain_request: ExplainCodeRequest,
) -> None:
    """Acceptance: Invalid output after 2 attempts raises LLMValidationError (no silent empty output)."""
    mock_llm_gateway.generate.return_value = LLMResponse(
        content='{"invalid": "schema"}',
        model="gemini-flash-lite-latest",
    )

    service = CodeExplanationService(llm_gateway=mock_llm_gateway)
    with pytest.raises(LLMValidationError) as exc_info:
        await service.explain(uuid4(), sample_explain_request)

    assert "CodeExplanation" in str(exc_info.value)
    assert mock_llm_gateway.generate.call_count == 2


@pytest.mark.asyncio
async def test_code_explanation_service_unconfigured_gateway_raises_503(
    sample_explain_request: ExplainCodeRequest,
) -> None:
    """Unconfigured gateway fails closed with HTTP 503."""
    service = CodeExplanationService(llm_gateway=None)
    with pytest.raises(APIError) as exc_info:
        await service.explain(uuid4(), sample_explain_request)

    assert exc_info.value.status_code == 503


def test_code_explanation_service_implements_protocol() -> None:
    """Verifies runtime Protocol conformance."""
    service = CodeExplanationService(llm_gateway=MagicMock())
    assert isinstance(service, CodeExplanationServiceProtocol)
