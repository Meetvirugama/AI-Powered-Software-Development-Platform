"""
Tests for Normalized LLM Tool Calling Layer (Phase 1 / Issue #188).

Validates:
- Message primitives with system, user, assistant, and tool turns.
- LLMToolDefinition wire conversion (Gemini and OpenAI/Groq).
- GeminiProvider tool calling with mocked HTTP transport.
- GroqProvider tool calling with mocked HTTP transport.
- LLMGateway routing, telemetry, and fallback.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import httpx
import pytest
from ai.llm.client import LLMGateway
from ai.llm.gemini_provider import GeminiProvider
from ai.llm.groq_provider import GroqProvider
from ai.llm.schemas import (
    LLMRateLimitError,
    LLMToolCall,
    LLMToolDefinition,
    LLMToolRequest,
    LLMToolResponse,
    LLMToolResult,
    Message,
)

# ---------------------------------------------------------------------------
# 1. Schema Unit Tests
# ---------------------------------------------------------------------------


def test_tool_definition_wire_conversions() -> None:
    tool = LLMToolDefinition(
        name="search_code",
        description="Search repository code chunks.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search phrase"},
                "top_k": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    )

    gemini_dict = tool.to_gemini_dict()
    assert gemini_dict["name"] == "search_code"
    assert gemini_dict["description"] == "Search repository code chunks."
    assert "query" in gemini_dict["parameters"]["properties"]

    openai_dict = tool.to_openai_dict()
    assert openai_dict["type"] == "function"
    assert openai_dict["function"]["name"] == "search_code"
    assert "query" in openai_dict["function"]["parameters"]["properties"]


def test_message_tool_turns_serialization() -> None:
    # 1. Normal user turn
    user_msg = Message.user("Why did login fail?")
    assert user_msg.role == "user"
    assert user_msg.content == "Why did login fail?"
    d = user_msg.to_dict()
    assert d == {"role": "user", "content": "Why did login fail?"}

    # 2. Assistant turn with tool calls
    tc = LLMToolCall(id="call_123", name="search_code", arguments={"query": "auth_login"})
    asst_msg = Message.assistant(content="Searching code...", tool_calls=[tc])
    assert asst_msg.role == "assistant"
    assert len(asst_msg.tool_calls or []) == 1
    d_asst = asst_msg.to_dict()
    assert d_asst["tool_calls"][0]["name"] == "search_code"

    # Roundtrip from dict
    reconstructed = Message.from_dict(d_asst)
    assert reconstructed.role == "assistant"
    assert reconstructed.tool_calls is not None
    assert reconstructed.tool_calls[0].name == "search_code"
    assert reconstructed.tool_calls[0].arguments["query"] == "auth_login"

    # 3. Tool result turn
    tr = LLMToolResult(
        tool_call_id="call_123",
        name="search_code",
        result={"found": 1, "path": "auth.py"},
    )
    tool_msg = Message.tool_result("call_123", "search_code", tr.to_content_str())
    assert tool_msg.role == "tool"
    assert tool_msg.tool_call_id == "call_123"
    assert tool_msg.name == "search_code"
    assert "auth.py" in tool_msg.content


def test_tool_response_properties() -> None:
    # Final response (no tool calls)
    resp_final = LLMToolResponse(
        content="Here is the explanation.",
        tool_calls=[],
        model="gemini-flash-lite-latest",
        input_tokens=100,
        output_tokens=50,
    )
    assert resp_final.is_final is True
    assert resp_final.total_tokens == 150

    # Tool invocation response
    resp_tool = LLMToolResponse(
        content="",
        tool_calls=[LLMToolCall(id="c1", name="search_code", arguments={"query": "test"})],
        model="gemini-flash-lite-latest",
        input_tokens=120,
        output_tokens=30,
    )
    assert resp_tool.is_final is False
    assert resp_tool.total_tokens == 150


# ---------------------------------------------------------------------------
# 2. GeminiProvider Tool Calling Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gemini_generate_with_tools_emits_tool_calls() -> None:
    mock_resp_json = {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [
                        {
                            "functionCall": {
                                "name": "search_code",
                                "args": {"query": "refresh token failure"},
                            }
                        }
                    ],
                },
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 250,
            "candidatesTokenCount": 45,
        },
    }

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.is_closed = False
    mock_response = httpx.Response(200, json=mock_resp_json, request=httpx.Request("POST", "http://test"))
    mock_client.post.return_value = mock_response

    provider = GeminiProvider(api_keys=["test-key-123"], client=mock_client)
    req = LLMToolRequest.create(
        model="gemini-flash-lite-latest",
        messages=[Message.user("Where does token refresh fail?")],
        tools=[
            LLMToolDefinition(
                name="search_code",
                description="Search code",
                parameters={"type": "object", "properties": {"query": {"type": "string"}}},
            )
        ],
    )

    resp = await provider.generate_with_tools(req)
    assert resp.is_final is False
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "search_code"
    assert resp.tool_calls[0].arguments == {"query": "refresh token failure"}
    assert resp.input_tokens == 250
    assert resp.output_tokens == 45
    assert resp.provider == "gemini"


@pytest.mark.asyncio
async def test_gemini_generate_with_tools_final_answer() -> None:
    mock_resp_json = {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [{"text": "Token refresh fails because expiry isn't checked."}],
                },
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {"promptTokenCount": 400, "candidatesTokenCount": 60},
    }

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.is_closed = False
    mock_response = httpx.Response(200, json=mock_resp_json, request=httpx.Request("POST", "http://test"))
    mock_client.post.return_value = mock_response

    provider = GeminiProvider(api_keys=["test-key-123"], client=mock_client)
    req = LLMToolRequest.create(
        model="gemini-flash-lite-latest",
        messages=[
            Message.user("Where does token refresh fail?"),
            Message.assistant(
                tool_calls=[LLMToolCall(id="c1", name="search_code", arguments={"query": "token"})]
            ),
            Message.tool_result("c1", "search_code", json.dumps({"content": "expiry check bug"})),
        ],
        tools=[],
    )

    resp = await provider.generate_with_tools(req)
    assert resp.is_final is True
    assert "Token refresh fails" in resp.content
    assert len(resp.tool_calls) == 0


@pytest.mark.asyncio
async def test_gemini_generate_with_tools_rate_limit_rotation() -> None:
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.is_closed = False

    resp_429 = httpx.Response(429, json={"error": "Rate limit"}, request=httpx.Request("POST", "http://test"))
    resp_200 = httpx.Response(
        200,
        json={
            "candidates": [
                {"content": {"parts": [{"text": "Resolved after rotation"}]}, "finishReason": "STOP"}
            ],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 10},
        },
        request=httpx.Request("POST", "http://test"),
    )
    mock_client.post.side_effect = [resp_429, resp_200]

    provider = GeminiProvider(api_keys=["key-1", "key-2"], client=mock_client)
    req = LLMToolRequest.create(
        model="gemini-flash-lite-latest",
        messages=[Message.user("Hello")],
    )

    resp = await provider.generate_with_tools(req)
    assert resp.content == "Resolved after rotation"
    assert mock_client.post.call_count == 2


# ---------------------------------------------------------------------------
# 3. GroqProvider Tool Calling Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_groq_generate_with_tools_emits_tool_calls() -> None:
    mock_resp_json = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "groq_call_456",
                            "type": "function",
                            "function": {
                                "name": "read_file_range",
                                "arguments": '{"file_path": "auth.py", "start_line": 10, "end_line": 40}',
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 180, "completion_tokens": 35},
    }

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.is_closed = False
    mock_response = httpx.Response(200, json=mock_resp_json, request=httpx.Request("POST", "http://test"))
    mock_client.post.return_value = mock_response

    provider = GroqProvider(api_keys=["groq-test-key"], client=mock_client)
    req = LLMToolRequest.create(
        model="openai/gpt-oss-120b",
        messages=[Message.user("Read auth implementation.")],
        tools=[
            LLMToolDefinition(
                name="read_file_range",
                description="Read lines",
                parameters={"type": "object", "properties": {"file_path": {"type": "string"}}},
            )
        ],
    )

    resp = await provider.generate_with_tools(req)
    assert resp.is_final is False
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "read_file_range"
    assert resp.tool_calls[0].id == "groq_call_456"
    assert resp.tool_calls[0].arguments["file_path"] == "auth.py"
    assert resp.tool_calls[0].arguments["start_line"] == 10
    assert resp.input_tokens == 180
    assert resp.output_tokens == 35
    assert resp.provider == "groq"


@pytest.mark.asyncio
async def test_groq_generate_with_tools_final_answer() -> None:
    mock_resp_json = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "The auth flow checks the bearer token validity.",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 300, "completion_tokens": 50},
    }

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.is_closed = False
    mock_response = httpx.Response(200, json=mock_resp_json, request=httpx.Request("POST", "http://test"))
    mock_client.post.return_value = mock_response

    provider = GroqProvider(api_keys=["groq-test-key"], client=mock_client)
    req = LLMToolRequest.create(
        model="openai/gpt-oss-120b",
        messages=[
            Message.user("Explain auth"),
            Message.assistant(
                tool_calls=[LLMToolCall(id="tc1", name="read_file_range", arguments={"file_path": "auth.py"})]
            ),
            Message.tool_result("tc1", "read_file_range", "def verify_token(): pass"),
        ],
    )

    resp = await provider.generate_with_tools(req)
    assert resp.is_final is True
    assert "checks the bearer token" in resp.content
    assert len(resp.tool_calls) == 0


# ---------------------------------------------------------------------------
# 4. LLMGateway Tool Calling & Fallback Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_gateway_tool_calling_success() -> None:
    mock_provider = AsyncMock(spec=GeminiProvider)
    mock_provider.provider_name = "gemini"
    mock_provider.default_model = "gemini-flash-lite-latest"
    mock_resp = LLMToolResponse(
        content="Primary answer",
        tool_calls=[],
        model="gemini-flash-lite-latest",
        input_tokens=50,
        output_tokens=25,
        provider="gemini",
    )
    mock_provider.generate_with_tools.return_value = mock_resp

    gateway = LLMGateway(provider=mock_provider)
    req = LLMToolRequest.create(
        model="gemini-flash-lite-latest",
        messages=[Message.user("Hello")],
    )

    resp = await gateway.generate_with_tools(req)
    assert resp.content == "Primary answer"
    assert resp.provider == "gemini"
    mock_provider.generate_with_tools.assert_called_once()


@pytest.mark.asyncio
async def test_llm_gateway_tool_calling_fallback_on_transient_error() -> None:
    primary = AsyncMock(spec=GeminiProvider)
    primary.provider_name = "gemini"
    primary.default_model = "gemini-flash-lite-latest"
    primary.generate_with_tools.side_effect = LLMRateLimitError("Gemini 429", provider="gemini")

    fallback = AsyncMock(spec=GroqProvider)
    fallback.provider_name = "groq"
    fallback.default_model = "openai/gpt-oss-120b"
    fallback_resp = LLMToolResponse(
        content="Fallback answer",
        tool_calls=[],
        model="openai/gpt-oss-120b",
        input_tokens=60,
        output_tokens=30,
        provider="groq",
    )
    fallback.generate_with_tools.return_value = fallback_resp

    gateway = LLMGateway(provider=primary, fallback_provider=fallback)
    req = LLMToolRequest.create(
        model="gemini-flash-lite-latest",
        messages=[Message.user("Hello")],
    )

    resp = await gateway.generate_with_tools(req)
    assert resp.content == "Fallback answer"
    assert resp.provider == "groq"
    primary.generate_with_tools.assert_called_once()
    fallback.generate_with_tools.assert_called_once()
