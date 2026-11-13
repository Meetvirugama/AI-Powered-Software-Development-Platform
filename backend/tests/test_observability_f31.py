"""
Comprehensive Unit Tests for Feature F31 (Issue #212 & task4.md):
Distributed Tracing, LLM Observability & Agent Execution Monitoring.
"""

from __future__ import annotations

import json
import logging
import pytest
from unittest.mock import MagicMock
import httpx
import respx

from opentelemetry import trace
from opentelemetry.trace import StatusCode

from app.core.logging import (
    JsonFormatter,
    agent_execution_id_context,
    analysis_run_id_context,
    request_id_context,
)
from app.observability.agent import trace_agent_execution, trace_tool_invocation
from app.observability.genai import (
    GEN_AI_FALLBACK_ATTEMPTED,
    GEN_AI_OPERATION_NAME,
    GEN_AI_REQUEST_MODEL,
    GEN_AI_RESPONSE_MODEL,
    GEN_AI_SYSTEM,
    GEN_AI_USAGE_INPUT_TOKENS,
    GEN_AI_USAGE_OUTPUT_TOKENS,
    build_llm_span_attributes,
)
from app.observability.langfuse_adapter import LangfuseAdapter
from app.observability.metrics import ObservabilityMetrics, get_observability_metrics
from app.observability.telemetry import (
    TelemetryManager,
    setup_telemetry,
    shutdown_telemetry,
)
from ai.llm.client import LLMGateway
from ai.llm.gemini_provider import GeminiProvider
from ai.llm.groq_provider import GroqProvider
from ai.llm.schemas import LLMRequest, LLMResponse, Message, LLMUnavailableError


@pytest.fixture(autouse=True)
def clean_telemetry():
    shutdown_telemetry()
    yield
    shutdown_telemetry()


# ---------------------------------------------------------------------------
# 1. OpenTelemetry Foundation Tests
# ---------------------------------------------------------------------------

def test_telemetry_manager_initialization():
    mgr = TelemetryManager(
        service_name="test-platform",
        service_version="2.0.0",
        environment="test",
        enabled=True,
        use_in_memory_exporter=True,
    )
    assert mgr.setup() is True
    assert mgr.is_initialized is True
    assert mgr.in_memory_exporter is not None
    assert mgr.tracer_provider is not None

    tracer = mgr.tracer_provider.get_tracer("test_tracer")
    with tracer.start_as_current_span("test_span") as span:
        span.set_attribute("custom.key", "custom_value")

    spans = mgr.in_memory_exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "test_span"
    assert spans[0].attributes["custom.key"] == "custom_value"
    assert spans[0].resource.attributes["service.name"] == "test-platform"
    assert spans[0].resource.attributes["service.version"] == "2.0.0"

    mgr.shutdown()
    assert mgr.is_initialized is False


def test_telemetry_manager_disabled_behavior():
    mgr = TelemetryManager(enabled=False, use_in_memory_exporter=False)
    assert mgr.setup() is False
    assert mgr.is_initialized is False


# ---------------------------------------------------------------------------
# 2. Structured Logging Trace Enrichment Tests
# ---------------------------------------------------------------------------

def test_json_formatter_enriches_with_trace_and_context_ids():
    mgr = setup_telemetry(use_in_memory_exporter=True)
    formatter = JsonFormatter()

    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Sample log message",
        args=(),
        exc_info=None,
    )

    # Set context vars
    req_token = request_id_context.set("req-12345")
    run_token = analysis_run_id_context.set("run-67890")
    agent_token = agent_execution_id_context.set("agent-abcdef")

    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("active_trace_span") as span:
        ctx = span.get_span_context()
        expected_trace_id = format(ctx.trace_id, "032x")
        expected_span_id = format(ctx.span_id, "016x")

        output = formatter.format(record)
        data = json.loads(output)

        assert data["request_id"] == "req-12345"
        assert data["analysis_run_id"] == "run-67890"
        assert data["agent_execution_id"] == "agent-abcdef"
        assert data["trace_id"] == expected_trace_id
        assert data["span_id"] == expected_span_id
        assert data["message"] == "Sample log message"

    request_id_context.reset(req_token)
    analysis_run_id_context.reset(run_token)
    agent_execution_id_context.reset(agent_token)
    shutdown_telemetry()


# ---------------------------------------------------------------------------
# 3. GenAI Semantic Tracing Tests
# ---------------------------------------------------------------------------

def test_build_llm_span_attributes():
    attrs = build_llm_span_attributes(
        provider="gemini",
        requested_model="gemini-flash-lite-latest",
        effective_model="gemini-flash-lite-latest",
        temperature=0.2,
        max_tokens=2048,
        input_tokens=150,
        output_tokens=60,
        finish_reason="STOP",
        tool_calls_count=2,
        fallback_attempted=True,
        initial_provider="groq",
        fallback_reason="RateLimitError",
        estimated_cost_usd=0.00005,
    )

    assert attrs[GEN_AI_SYSTEM] == "gemini"
    assert attrs[GEN_AI_OPERATION_NAME] == "generate"
    assert attrs[GEN_AI_REQUEST_MODEL] == "gemini-flash-lite-latest"
    assert attrs[GEN_AI_RESPONSE_MODEL] == "gemini-flash-lite-latest"
    assert attrs[GEN_AI_USAGE_INPUT_TOKENS] == 150
    assert attrs[GEN_AI_USAGE_OUTPUT_TOKENS] == 60
    assert attrs[GEN_AI_FALLBACK_ATTEMPTED] is True
    assert attrs["gen_ai.fallback.initial_provider"] == "groq"
    assert attrs["gen_ai.fallback.target_provider"] == "gemini"
    assert attrs["gen_ai.fallback.reason"] == "RateLimitError"
    assert attrs["gen_ai.usage.cost"] == 0.00005


@pytest.mark.asyncio
@respx.mock
async def test_llm_gateway_creates_genai_span():
    mgr = setup_telemetry(use_in_memory_exporter=True)

    provider = GeminiProvider(api_keys=["test-key"])
    gateway = LLMGateway(provider=provider)

    mock_resp = {
        "candidates": [
            {
                "content": {"parts": [{"text": "Hello, world!"}]},
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 20,
            "candidatesTokenCount": 10,
        },
    }
    respx.post("https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent").mock(
        return_value=httpx.Response(200, json=mock_resp)
    )

    req = LLMRequest.create(
        model="gemini-flash-lite-latest",
        messages=[{"role": "user", "content": "hello"}],
    )
    resp = await gateway.generate(req)
    assert resp.content == "Hello, world!"

    spans = mgr.in_memory_exporter.get_finished_spans()
    assert any(s.name == "gen_ai.generate" for s in spans)
    gen_span = next(s for s in spans if s.name == "gen_ai.generate")
    assert gen_span.attributes[GEN_AI_SYSTEM] == "gemini"
    assert gen_span.attributes[GEN_AI_REQUEST_MODEL] == "gemini-flash-lite-latest"
    assert gen_span.attributes[GEN_AI_USAGE_INPUT_TOKENS] == 20
    assert gen_span.attributes[GEN_AI_USAGE_OUTPUT_TOKENS] == 10
    assert gen_span.status.status_code == StatusCode.OK

    shutdown_telemetry()


@pytest.mark.asyncio
@respx.mock
async def test_llm_gateway_span_records_fallback():
    mgr = setup_telemetry(use_in_memory_exporter=True)

    primary = GeminiProvider(api_keys=["test-key"])
    secondary = GroqProvider(api_keys=["groq-key"])
    gateway = LLMGateway(primary=primary, secondary=secondary)

    # Primary returns 503
    respx.post("https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent").mock(
        return_value=httpx.Response(503, text="Service Unavailable")
    )
    # Secondary succeeds
    respx.post("https://api.groq.com/openai/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": "Fallback success"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 15, "completion_tokens": 5},
        })
    )

    req = LLMRequest.create(
        model="gemini-flash-lite-latest",
        messages=[{"role": "user", "content": "hi"}],
    )
    resp = await gateway.generate(req)
    assert resp.content == "Fallback success"

    spans = mgr.in_memory_exporter.get_finished_spans()
    gen_span = next(s for s in spans if s.name == "gen_ai.generate")
    assert gen_span.attributes[GEN_AI_FALLBACK_ATTEMPTED] is True
    assert gen_span.attributes["gen_ai.fallback.initial_provider"] == "gemini"
    assert gen_span.attributes["gen_ai.fallback.target_provider"] == "groq"

    shutdown_telemetry()


# ---------------------------------------------------------------------------
# 4. Autonomous Agent and Tool Tracing Tests
# ---------------------------------------------------------------------------

def test_trace_agent_and_tool_execution():
    mgr = setup_telemetry(use_in_memory_exporter=True)

    with trace_agent_execution(
        execution_id="agent-run-101",
        task_id="task-42",
        analysis_run_id="run-99",
    ) as agent_span:
        assert agent_span.is_recording()

        with trace_tool_invocation(
            tool_name="workspace.read_file",
            execution_id="agent-run-101",
            task_id="task-42",
            metadata={"path": "main.py"},
        ) as tool_span:
            assert tool_span.is_recording()

    spans = mgr.in_memory_exporter.get_finished_spans()
    assert len(spans) == 2

    tool_s = next(s for s in spans if s.name == "tool:workspace.read_file")
    agent_s = next(s for s in spans if s.name == "agent.execution")

    assert tool_s.attributes["tool.name"] == "workspace.read_file"
    assert tool_s.attributes["tool.status"] == "success"
    assert tool_s.parent.span_id == agent_s.context.span_id

    assert agent_s.attributes["agent.execution.id"] == "agent-run-101"
    assert agent_s.attributes["agent.status"] == "completed"

    shutdown_telemetry()


def test_trace_tool_invocation_records_error():
    mgr = setup_telemetry(use_in_memory_exporter=True)

    with pytest.raises(RuntimeError, match="disk error"):
        with trace_tool_invocation(tool_name="command.run"):
            raise RuntimeError("disk error")

    spans = mgr.in_memory_exporter.get_finished_spans()
    assert len(spans) == 1
    tool_s = spans[0]
    assert tool_s.attributes["tool.status"] == "error"
    assert tool_s.status.status_code == StatusCode.ERROR

    shutdown_telemetry()


# ---------------------------------------------------------------------------
# 5. Langfuse Adapter Tests
# ---------------------------------------------------------------------------

def test_langfuse_adapter_noop_when_disabled():
    adapter = LangfuseAdapter(enabled=False)
    assert adapter.is_active is False
    # Calling methods must be completely safe no-ops
    adapter.record_generation(
        trace_id="trace-123",
        model="gemini-flash-lite-latest",
        provider="gemini",
        input_tokens=100,
        output_tokens=50,
    )
    adapter.record_tool_call(trace_id="trace-123", tool_name="bash", duration_ms=120)
    adapter.flush()
    adapter.shutdown()


def test_langfuse_adapter_records_with_mock_client():
    mock_client = MagicMock()
    adapter = LangfuseAdapter(
        enabled=True,
        capture_prompts=False,
        capture_responses=False,
        client=mock_client,
    )
    assert adapter.is_active is True

    adapter.record_generation(
        trace_id="trace-abc",
        name="llm.generate",
        model="gemini-flash-lite-latest",
        provider="gemini",
        input_tokens=100,
        output_tokens=50,
        latency_ms=250.0,
        finish_reason="STOP",
        prompt="Sensitive user prompt",
        completion="Model completion",
    )

    mock_client.generation.assert_called_once()
    kwargs = mock_client.generation.call_args.kwargs
    assert kwargs["trace_id"] == "trace-abc"
    assert kwargs["model"] == "gemini-flash-lite-latest"
    # Privacy safeguard: input and output are None because capture_prompts=False
    assert kwargs["input"] is None
    assert kwargs["output"] is None
    assert kwargs["usage"] == {"input": 100, "output": 50, "total": 150}

    # Tool invocation recording
    adapter.record_tool_call(
        trace_id="trace-abc",
        tool_name="grep",
        duration_ms=45.0,
    )
    mock_client.span.assert_called_once()
    assert mock_client.span.call_args.kwargs["name"] == "tool:grep"


def test_langfuse_adapter_privacy_opt_in():
    mock_client = MagicMock()
    adapter = LangfuseAdapter(
        enabled=True,
        capture_prompts=True,
        capture_responses=True,
        client=mock_client,
    )
    adapter.record_generation(
        trace_id="trace-abc",
        model="gpt-4o",
        provider="groq",
        prompt="Public code",
        completion="Generated test",
    )
    kwargs = mock_client.generation.call_args.kwargs
    assert kwargs["input"] == "Public code"
    assert kwargs["output"] == "Generated test"


# ---------------------------------------------------------------------------
# 6. Metrics Recording Tests
# ---------------------------------------------------------------------------

def test_metrics_recorder():
    metrics_recorder = get_observability_metrics()
    # Must record without raising any exception
    metrics_recorder.record_llm_request(
        provider="gemini",
        model="gemini-flash-lite-latest",
        duration_s=0.25,
        input_tokens=100,
        output_tokens=50,
        success=True,
        fallback_occurred=True,
        initial_provider="groq",
    )
    metrics_recorder.record_agent_execution(status="completed", duration_s=1.5)
    metrics_recorder.record_tool_invocation(tool_name="file_read", duration_s=0.05, success=True)
