"""
Unit tests for LLM Gateway — Day 2 requirements.
Owner: Meet — W1-12

Tests:
    1. test_retry_on_429            — mock OpenAI returning 429 then 200; verify 3 attempts max.
    2. test_llm_response_type       — verify gateway always returns LLMResponse, never a raw dict.
    3. test_retry_exhaustion_raises — 429 on all attempts raises LLMRateLimitError.
    4. test_structured_output_validated — response_schema triggers JSON validation.
    5. test_token_counts_populated  — input_tokens / output_tokens extracted correctly.
    6. test_timeout_raises          — httpx timeout → LLMTimeoutError.

Run with:
    pytest backend/tests/test_llm_gateway.py -v
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _groq_success_payload(content: str = "Hello!", model: str = "llama-3.3-70b-versatile") -> dict[str, Any]:
    """Minimal Groq chat completion wire response structure."""
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        },
    }


def _make_http_response(status_code: int, json_body: dict | None = None) -> MagicMock:
    """Create a mock httpx.Response-like object."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.text = ""
    mock_resp.json.return_value = json_body or {}
    return mock_resp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def llm_request():
    from ai.llm.schemas import LLMRequest, Message

    return LLMRequest(
        model="gpt-4o",
        messages=[Message(role="user", content="Where is authentication?")],
        temperature=0.0,
        max_tokens=512,
    )


@pytest.fixture()
def provider_and_gateway():
    """Return a real GroqProvider with a fake API key + its LLMGateway wrapper."""
    from ai.llm.client import LLMGateway
    from ai.llm.groq_provider import GroqProvider

    provider = GroqProvider(api_keys=["gsk-test-key"])
    gateway = LLMGateway(provider=provider)
    return provider, gateway


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRetryOn429:
    """Gateway retries on 429 with exponential backoff."""

    @pytest.mark.asyncio
    async def test_retry_on_429_then_success(self, llm_request, provider_and_gateway):
        """
        Scenario: First call returns 429, second returns 200.
        Expected: Gateway succeeds (returns LLMResponse) after 1 retry.
        """
        _, gateway = provider_and_gateway
        success_payload = _groq_success_payload("Auth is in auth_service.py")

        responses = [
            _make_http_response(429),
            _make_http_response(200, success_payload),
        ]

        with (
            patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=responses),
            patch("asyncio.sleep", new_callable=AsyncMock),  # skip real sleep
        ):
            from ai.llm.schemas import LLMResponse

            result = await gateway.generate(llm_request)

            assert isinstance(result, LLMResponse), (
                "Gateway must always return a typed LLMResponse, not a raw dict."
            )
            assert result.content == "Auth is in auth_service.py"

    @pytest.mark.asyncio
    async def test_retry_triggered_exactly_on_429(self, llm_request, provider_and_gateway):
        """
        Verify that the HTTP client is called more than once when 429 is received,
        confirming retry behaviour is active.
        """
        _, gateway = provider_and_gateway
        success_payload = _groq_success_payload()

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_http_response(429)
            return _make_http_response(200, success_payload)

        with (
            patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=side_effect),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            await gateway.generate(llm_request)

        assert call_count == 2, f"Expected 2 HTTP calls (1 retry), got {call_count}"

    @pytest.mark.asyncio
    async def test_retry_exhaustion_raises_rate_limit_error(self, llm_request, provider_and_gateway):
        """
        Scenario: All 3 attempts return 429.
        Expected: LLMRateLimitError is raised.
        """
        from ai.llm.schemas import LLMRateLimitError

        _, gateway = provider_and_gateway
        three_429s = [_make_http_response(429)] * 3

        with (
            patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=three_429s),
            patch("asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(LLMRateLimitError),
        ):
            await gateway.generate(llm_request)


class TestLLMResponseType:
    """Gateway always returns a typed LLMResponse — never a raw dict."""

    @pytest.mark.asyncio
    async def test_response_is_llm_response_instance(self, llm_request, provider_and_gateway):
        """Core contract: generate() must return LLMResponse, not dict, str, or Any."""
        from ai.llm.schemas import LLMResponse

        _, gateway = provider_and_gateway
        payload = _groq_success_payload("The answer is 42.")

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=_make_http_response(200, payload)):
            result = await gateway.generate(llm_request)

        assert isinstance(result, LLMResponse), (
            f"Expected LLMResponse, got {type(result).__name__}"
        )

    @pytest.mark.asyncio
    async def test_token_counts_populated(self, llm_request, provider_and_gateway):
        """Token counts must be extracted from OpenAI usage field."""
        _, gateway = provider_and_gateway
        payload = _groq_success_payload()
        payload["usage"] = {"prompt_tokens": 123, "completion_tokens": 77, "total_tokens": 200}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=_make_http_response(200, payload)):
            result = await gateway.generate(llm_request)

        assert result.input_tokens == 123
        assert result.output_tokens == 77

    @pytest.mark.asyncio
    async def test_latency_ms_is_positive(self, llm_request, provider_and_gateway):
        """Latency should always be a positive number."""
        _, gateway = provider_and_gateway
        payload = _groq_success_payload()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=_make_http_response(200, payload)):
            result = await gateway.generate(llm_request)

        assert result.latency_ms >= 0


class TestStructuredOutput:
    """response_schema triggers JSON mode and validation."""

    @pytest.mark.asyncio
    async def test_valid_structured_output_passes(self, provider_and_gateway):
        """Valid JSON matching schema passes validation and is returned."""
        from ai.llm.schemas import LLMRequest, LLMResponse, Message

        class MySchema(BaseModel):
            answer: str
            confidence: float

        json_content = json.dumps({"answer": "It's in auth.py", "confidence": 0.95})
        payload = _groq_success_payload(content=json_content)

        _, gateway = provider_and_gateway
        request = LLMRequest(
            model="gpt-4o",
            messages=[Message(role="user", content="Where?")],
            response_schema=MySchema,
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=_make_http_response(200, payload)):
            result = await gateway.generate(request)

        assert isinstance(result, LLMResponse)
        assert json_content == result.content

    @pytest.mark.asyncio
    async def test_invalid_json_raises_validation_error(self, provider_and_gateway):
        """Non-JSON content when schema is set raises LLMValidationError."""
        from ai.llm.schemas import LLMRequest, LLMValidationError, Message

        class MySchema(BaseModel):
            answer: str

        bad_payload = _groq_success_payload(content="not valid JSON !!!")
        _, gateway = provider_and_gateway
        request = LLMRequest(
            model="gpt-4o",
            messages=[Message(role="user", content="Where?")],
            response_schema=MySchema,
        )

        with (
            patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=_make_http_response(200, bad_payload)),
            pytest.raises(LLMValidationError),
        ):
            await gateway.generate(request)

    @pytest.mark.asyncio
    async def test_schema_mismatch_raises_validation_error(self, provider_and_gateway):
        """JSON that doesn't match schema (missing required field) raises LLMValidationError."""
        from ai.llm.schemas import LLMRequest, LLMValidationError, Message

        class MySchema(BaseModel):
            answer: str
            confidence: float  # required

        bad_json = json.dumps({"answer": "something"})  # missing confidence
        bad_payload = _groq_success_payload(content=bad_json)

        _, gateway = provider_and_gateway
        request = LLMRequest(
            model="gpt-4o",
            messages=[Message(role="user", content="Where?")],
            response_schema=MySchema,
        )

        with (
            patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=_make_http_response(200, bad_payload)),
            pytest.raises(LLMValidationError),
        ):
            await gateway.generate(request)


class TestTimeoutHandling:
    """httpx.TimeoutException → LLMTimeoutError."""

    @pytest.mark.asyncio
    async def test_timeout_raises_llm_timeout_error(self, llm_request, provider_and_gateway):
        import httpx
        from ai.llm.schemas import LLMTimeoutError

        _, gateway = provider_and_gateway

        with (
            patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=httpx.TimeoutException("timed out")),
            patch("asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(LLMTimeoutError),
        ):
            await gateway.generate(llm_request)


# ===========================================================================
# SDE-3 Enhancements
# ===========================================================================


class TestSDE3GatewayFeatures:
    """Tests for SDE-3 production additions: fallback provider, message coercion, response helpers."""

    def test_message_coercion_and_serialization(self):
        from ai.llm.schemas import Message

        msg = Message.from_dict({"role": "user", "content": "hello"})
        assert msg.role == "user"
        assert msg.to_dict() == {"role": "user", "content": "hello"}

        msg_any = Message.from_any({"role": "assistant", "content": "world"})
        assert msg_any.role == "assistant"
        assert Message.from_any(msg_any) is msg_any

    def test_llm_request_create_convenience(self):
        from ai.llm.schemas import LLMRequest

        req = LLMRequest.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Hi"},
            ],
            temperature=0.5,
        )
        assert len(req.messages) == 2
        assert req.messages[0].role == "system"
        assert req.temperature == 0.5

    def test_llm_response_total_tokens_and_parse(self):
        from ai.llm.schemas import LLMResponse, LLMValidationError

        class AnswerSchema(BaseModel):
            topic: str
            confidence: float

        resp = LLMResponse(
            content='```json\n{"topic": "security", "confidence": 0.98}\n```',
            model="gpt-4o",
            input_tokens=100,
            output_tokens=50,
            latency_ms=120.5,
        )
        assert resp.total_tokens == 150
        parsed = resp.parse_json()
        assert parsed["topic"] == "security"

        structured = resp.parse_schema(AnswerSchema)
        assert structured.topic == "security"
        assert structured.confidence == 0.98

        bad_resp = LLMResponse(
            content="non-json output",
            model="gpt-4o",
            input_tokens=10,
            output_tokens=10,
            latency_ms=50.0,
        )
        with pytest.raises(LLMValidationError):
            bad_resp.parse_schema(AnswerSchema)

    @pytest.mark.asyncio
    async def test_gateway_fallback_provider_on_primary_outage(self, llm_request):
        from ai.llm.client import LLMGateway
        from ai.llm.schemas import LLMResponse, LLMUnavailableError

        primary_mock = AsyncMock()
        primary_mock.provider_name = "primary-mock"
        primary_mock.generate.side_effect = LLMUnavailableError("Primary 503 down")

        fallback_mock = AsyncMock()
        fallback_mock.provider_name = "fallback-mock"
        fallback_mock.generate.return_value = LLMResponse(
            content="Fallback answer",
            model="fallback-model",
            input_tokens=20,
            output_tokens=10,
            latency_ms=45.0,
        )

        gateway = LLMGateway(provider=primary_mock, fallback_provider=fallback_mock)
        result = await gateway.generate(llm_request)

        assert result.content == "Fallback answer"
        assert primary_mock.generate.call_count == 1
        assert fallback_mock.generate.call_count == 1

    @pytest.mark.asyncio
    async def test_gateway_validation_errors(self):
        from ai.llm.client import LLMGateway
        from ai.llm.schemas import LLMRequest

        mock_provider = AsyncMock()
        mock_provider.provider_name = "mock"

        gateway = LLMGateway(provider=mock_provider)

        with pytest.raises(TypeError, match="Expected LLMRequest"):
            await gateway.generate("not-a-request")  # type: ignore[arg-type]

        empty_req = LLMRequest(model="gpt-4o", messages=[])
        with pytest.raises(ValueError, match="at least one Message"):
            await gateway.generate(empty_req)

    @pytest.mark.asyncio
    async def test_gateway_async_context_manager(self, provider_and_gateway):
        _, gateway = provider_and_gateway
        async with gateway as gw:
            assert gw.provider_name == "groq"

