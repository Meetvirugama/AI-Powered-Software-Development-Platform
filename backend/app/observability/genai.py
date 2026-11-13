"""
GenAI Semantic Tracing Conventions and Attribute Mapping.

Maps LLM Gateway inference events and agent tool calls to standard OpenTelemetry
GenAI semantic conventions (v1.28+) with versioned fallback compatibility.
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel

# Standard GenAI Semantic Attribute Keys (OTel Semantic Conventions)
GEN_AI_SYSTEM = "gen_ai.system"
GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
GEN_AI_RESPONSE_MODEL = "gen_ai.response.model"
GEN_AI_OPERATION_NAME = "gen_ai.operation.name"
GEN_AI_USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
GEN_AI_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
GEN_AI_RESPONSE_FINISH_REASONS = "gen_ai.response.finish_reasons"
GEN_AI_REQUEST_TEMPERATURE = "gen_ai.request.temperature"
GEN_AI_REQUEST_MAX_TOKENS = "gen_ai.request.max_tokens"
GEN_AI_USAGE_ESTIMATED_COST_USD = "gen_ai.usage.cost"

# Fallback & Resilience Attribute Keys
GEN_AI_FALLBACK_ATTEMPTED = "gen_ai.fallback.attempted"
GEN_AI_FALLBACK_INITIAL_PROVIDER = "gen_ai.fallback.initial_provider"
GEN_AI_FALLBACK_TARGET_PROVIDER = "gen_ai.fallback.target_provider"
GEN_AI_FALLBACK_REASON = "gen_ai.fallback.reason"

# Agent & Tool Semantic Keys
GEN_AI_AGENT_EXECUTION_ID = "gen_ai.agent.execution_id"
GEN_AI_TOOL_NAME = "gen_ai.tool.name"
GEN_AI_TOOL_CALL_COUNT = "gen_ai.tool.call_count"


def build_llm_span_attributes(
    *,
    provider: str,
    requested_model: str,
    effective_model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 2048,
    input_tokens: int = 0,
    output_tokens: int = 0,
    finish_reason: str | None = None,
    tool_calls_count: int = 0,
    estimated_cost_usd: float | None = None,
    fallback_attempted: bool = False,
    initial_provider: str | None = None,
    fallback_reason: str | None = None,
    operation_name: str = "generate",
) -> dict[str, Any]:
    """
    Construct standardized GenAI OpenTelemetry span attributes.
    """
    attrs: dict[str, Any] = {
        GEN_AI_SYSTEM: provider,
        GEN_AI_OPERATION_NAME: operation_name,
        GEN_AI_REQUEST_MODEL: requested_model,
        GEN_AI_RESPONSE_MODEL: effective_model or requested_model,
        GEN_AI_REQUEST_TEMPERATURE: temperature,
        GEN_AI_REQUEST_MAX_TOKENS: max_tokens,
        GEN_AI_USAGE_INPUT_TOKENS: input_tokens,
        GEN_AI_USAGE_OUTPUT_TOKENS: output_tokens,
        GEN_AI_TOOL_CALL_COUNT: tool_calls_count,
        GEN_AI_FALLBACK_ATTEMPTED: fallback_attempted,
    }

    if finish_reason:
        attrs[GEN_AI_RESPONSE_FINISH_REASONS] = [finish_reason]

    if estimated_cost_usd is not None and estimated_cost_usd > 0.0:
        attrs[GEN_AI_USAGE_ESTIMATED_COST_USD] = round(estimated_cost_usd, 6)

    if fallback_attempted:
        if initial_provider:
            attrs[GEN_AI_FALLBACK_INITIAL_PROVIDER] = initial_provider
        attrs[GEN_AI_FALLBACK_TARGET_PROVIDER] = provider
        if fallback_reason:
            attrs[GEN_AI_FALLBACK_REASON] = fallback_reason

    return attrs
