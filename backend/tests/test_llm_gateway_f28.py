"""
Unit tests for Feature F28: LLM gateway, providers, prompts, validation, grounding.
Validates:
- Unified tool calling & streaming in LLMRequest and LLMResponse
- Strict response schema converters (Gemini & Groq)
- Explicit model aliasing (no silent remaps)
- Streaming via generate_stream() for Gemini, Groq, and LLMGateway
- LLMGateway fallback preservation
- Model-aware telemetry cost calibration
"""

from __future__ import annotations

import json
from typing import Any
import pytest
import respx
import httpx
from pydantic import BaseModel, Field

from backend.ai.llm.client import LLMGateway
from backend.ai.llm.gemini_provider import (
    GeminiProvider,
    build_strict_gemini_response_schema,
)
from backend.ai.llm.groq_provider import (
    GroqProvider,
    build_strict_groq_json_schema,
)
from backend.ai.llm.schemas import (
    LLMRequest,
    LLMResponse,
    LLMResponseChunk,
    LLMToolCall,
    LLMToolDefinition,
    Message,
    LLMUnavailableError,
)
from backend.app.core.telemetry import (
    StageExecutionTimer,
    get_token_pricing,
)


# ---------------------------------------------------------------------------
# Test Schemas
# ---------------------------------------------------------------------------

class SampleReviewItem(BaseModel):
    title: str = Field(description="Issue title")
    severity: str = Field(description="Severity rating", default="medium")
    line_number: int = Field(description="Line number", default=1)


class SampleReviewReport(BaseModel):
    summary: str
    items: list[SampleReviewItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Test 1: LLMRequest & LLMResponse Unified Primitives
# ---------------------------------------------------------------------------

def test_llm_request_primitives():
    tool = LLMToolDefinition(
        name="calculate",
        description="Run calculation",
        parameters={"type": "object", "properties": {"expr": {"type": "string"}}},
    )
    req = LLMRequest.create(
        model="gemini-flash-lite-latest",
        messages=[{"role": "user", "content": "hello"}],
        tools=[tool],
        tool_choice="auto",
        stream=True,
        response_schema_mode="strict",
        allow_fallback=False,
    )
    assert req.model == "gemini-flash-lite-latest"
    assert len(req.messages) == 1
    assert req.messages[0].role == "user"
    assert req.tools is not None and len(req.tools) == 1
    assert req.tools[0].name == "calculate"
    assert req.tool_choice == "auto"
    assert req.stream is True
    assert req.response_schema_mode == "strict"
    assert req.allow_fallback is False


def test_llm_response_coalescing_and_properties():
    # Content is None should safely coalesce to empty string
    resp = LLMResponse(
        content=None,  # type: ignore[arg-type]
        model="gemini-flash-lite-latest",
        input_tokens=100,
        output_tokens=50,
        tool_calls=[LLMToolCall(id="c1", name="fn", arguments={"a": 1})],
        finish_reason="tool_calls",
        provider="gemini",
    )
    assert resp.content == ""
    assert resp.is_final is False
    assert resp.total_tokens == 150
    assert resp.finish_reason == "tool_calls"
    assert resp.provider == "gemini"

    # Final response without tool calls
    resp_final = LLMResponse(
        content="All done",
        model="gemini-flash-lite-latest",
        input_tokens=50,
        output_tokens=20,
    )
    assert resp_final.content == "All done"
    assert resp_final.is_final is True


def test_llm_response_chunk_primitive():
    chunk = LLMResponseChunk(
        delta="partial text",
        index=0,
        finish_reason=None,
        model="gemini-flash-lite-latest",
        provider="gemini",
    )
    assert chunk.delta == "partial text"
    assert chunk.index == 0
    assert chunk.finish_reason is None


# ---------------------------------------------------------------------------
# Test 2: Strict Schema Converters
# ---------------------------------------------------------------------------

def test_gemini_strict_response_schema_builder():
    schema = build_strict_gemini_response_schema(SampleReviewReport)
    assert schema["type"] == "OBJECT"
    assert "properties" in schema
    assert "summary" in schema["properties"]
    assert schema["properties"]["summary"]["type"] == "STRING"
    assert "items" in schema["properties"]
    assert schema["properties"]["items"]["type"] == "ARRAY"
    items_schema = schema["properties"]["items"]["items"]
    assert items_schema["type"] == "OBJECT"
    assert "severity" in items_schema["properties"]


def test_groq_strict_json_schema_builder():
    format_payload = build_strict_groq_json_schema(SampleReviewReport)
    assert format_payload["type"] == "json_schema"
    json_schema = format_payload["json_schema"]
    assert json_schema["strict"] is True
    assert json_schema["name"] == "SampleReviewReport"
    ast = json_schema["schema"]
    assert ast.get("additionalProperties") is False
    assert "summary" in ast.get("required", [])
    assert "items" in ast.get("required", [])
    # Verify nested items in $defs have additionalProperties: False
    defs_item = ast["$defs"]["SampleReviewItem"]
    assert defs_item.get("additionalProperties") is False
    assert "title" in defs_item.get("required", [])


# ---------------------------------------------------------------------------
# Test 3: Explicit Model Aliasing (No Silent Remaps)
# ---------------------------------------------------------------------------

def test_gemini_explicit_model_resolution():
    provider = GeminiProvider(api_keys=["test-key"])
    # Default model should be gemini-flash-lite-latest
    assert provider.default_model == "gemini-flash-lite-latest"
    # Resolution of flash-lite should remain flash-lite, NOT silently remap to flash
    resolved = provider._resolve_model("gemini-flash-lite-latest")
    assert resolved == "gemini-flash-lite-latest"
    # Pro model
    assert provider._resolve_model("gemini-1.5-pro") == "gemini-1.5-pro"


def test_groq_explicit_model_resolution():
    provider = GroqProvider(api_key="test-key")
    # Flash lite should map to openai/gpt-oss-120b in Groq
    resolved = provider._resolve_model("gemini-flash-lite-latest")
    assert resolved == "openai/gpt-oss-120b"


# ---------------------------------------------------------------------------
# Test 4: Streaming via Gemini & Groq Providers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_gemini_provider_generate_stream():
    provider = GeminiProvider(api_keys=["test-key"])
    req = LLMRequest.create(
        model="gemini-flash-lite-latest",
        messages=[{"role": "user", "content": "stream test"}],
        stream=True,
    )

    sse_data = (
        'data: {"candidates": [{"content": {"parts": [{"text": "Hello "}]}}]}\n\n'
        'data: {"candidates": [{"content": {"parts": [{"text": "world!"}]}, "finishReason": "STOP"}], "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 2}}\n\n'
    )

    respx.post("https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:streamGenerateContent?alt=sse").mock(
        return_value=httpx.Response(200, text=sse_data)
    )

    chunks: list[LLMResponseChunk] = []
    async for chunk in provider.generate_stream(req):
        chunks.append(chunk)

    assert len(chunks) == 2
    assert chunks[0].delta == "Hello "
    assert chunks[0].index == 0
    assert chunks[0].finish_reason is None

    assert chunks[1].delta == "world!"
    assert chunks[1].index == 1
    assert chunks[1].finish_reason == "STOP"
    assert chunks[1].input_tokens == 5
    assert chunks[1].output_tokens == 2


@pytest.mark.asyncio
@respx.mock
async def test_groq_provider_generate_stream():
    provider = GroqProvider(api_key="test-key")
    req = LLMRequest.create(
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": "stream test"}],
        stream=True,
    )

    sse_data = (
        'data: {"choices": [{"delta": {"content": "Groq "}}]}\n\n'
        'data: {"choices": [{"delta": {"content": "streaming!"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 8, "completion_tokens": 4}}\n\n'
        "data: [DONE]\n\n"
    )

    respx.post("https://api.groq.com/openai/v1/chat/completions").mock(
        return_value=httpx.Response(200, text=sse_data)
    )

    chunks: list[LLMResponseChunk] = []
    async for chunk in provider.generate_stream(req):
        chunks.append(chunk)

    assert len(chunks) == 2
    assert chunks[0].delta == "Groq "
    assert chunks[0].index == 0
    assert chunks[1].delta == "streaming!"
    assert chunks[1].finish_reason == "stop"
    assert chunks[1].input_tokens == 8
    assert chunks[1].output_tokens == 4


# ---------------------------------------------------------------------------
# Test 5: LLMGateway generate_stream & Fallback Flags
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_llm_gateway_generate_stream():
    primary = GeminiProvider(api_keys=["test-key"])
    gateway = LLMGateway(primary=primary)

    sse_data = (
        'data: {"candidates": [{"content": {"parts": [{"text": "Gateway stream"}]}}]}\n\n'
        'data: {"candidates": [{"content": {"parts": [{"text": " completed"}]}, "finishReason": "STOP"}]}\n\n'
    )
    respx.post("https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:streamGenerateContent?alt=sse").mock(
        return_value=httpx.Response(200, text=sse_data)
    )

    req = LLMRequest.create(
        model="gemini-flash-lite-latest",
        messages=[{"role": "user", "content": "stream test"}],
        stream=True,
    )
    deltas = []
    async for chunk in gateway.generate_stream(req):
        deltas.append(chunk.delta)

    assert "".join(deltas) == "Gateway stream completed"


@pytest.mark.asyncio
@respx.mock
async def test_llm_gateway_fallback_disabled_when_disallowed():
    primary = GeminiProvider(api_keys=["test-key"])
    secondary = GroqProvider(api_key="groq-key")
    gateway = LLMGateway(primary=primary, secondary=secondary)

    # Primary fails with 503
    respx.post("https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent").mock(
        return_value=httpx.Response(503, text="Service Unavailable")
    )

    req = LLMRequest.create(
        model="gemini-flash-lite-latest",
        messages=[{"role": "user", "content": "test"}],
        allow_fallback=False,  # Disallow fallback
    )

    with pytest.raises(LLMUnavailableError):
        await gateway.generate(req)


# ---------------------------------------------------------------------------
# Test 6: Model-Aware Telemetry Cost Calibration
# ---------------------------------------------------------------------------

def test_telemetry_get_token_pricing():
    # Gemini Flash Lite: $0.075 / $0.30
    in_p, out_p = get_token_pricing("gemini", "gemini-flash-lite-latest")
    assert in_p == 0.075
    assert out_p == 0.30

    # Gemini 1.5 Pro: $1.25 / $5.00
    in_p, out_p = get_token_pricing("gemini", "gemini-1.5-pro")
    assert in_p == 1.25
    assert out_p == 5.00

    # Groq GPT-OSS-120b: $0.15 / $0.60
    in_p, out_p = get_token_pricing("groq", "openai/gpt-oss-120b")
    assert in_p == 0.15
    assert out_p == 0.60

    # Fallback to provider default
    in_p, out_p = get_token_pricing("gemini", "unknown-model")
    assert in_p == 0.075
    assert out_p == 0.30


def test_stage_execution_timer_model_aware_cost():
    timer = StageExecutionTimer("code_review")
    timer.add_tokens(1_000_000, 1_000_000, provider="gemini", model="gemini-1.5-pro")
    metrics = timer.finish()
    # 1M input @ 1.25 + 1M output @ 5.00 = $6.25
    assert round(metrics.estimated_cost_usd, 4) == 6.2500
    assert metrics.model == "gemini-1.5-pro"
    assert metrics.provider == "gemini"
