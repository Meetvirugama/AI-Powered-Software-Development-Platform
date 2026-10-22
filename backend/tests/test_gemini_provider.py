"""
Unit tests for GeminiProvider and GeminiEmbeddingProvider.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from ai.embeddings.gemini_provider import GeminiEmbeddingProvider
from ai.embeddings.client import RateLimitError, AuthenticationError
from ai.llm.gemini_provider import GeminiProvider
from ai.llm.schemas import LLMRequest, Message, LLMRateLimitError


class TestGeminiProvider:
    def test_init_validation(self):
        with pytest.raises(ValueError, match="at least one non-empty API key"):
            GeminiProvider(api_keys=[])

    def test_key_rotation(self):
        provider = GeminiProvider(api_keys=["key1", "key2"])
        assert provider._next_key() == "key1"
        assert provider._next_key() == "key2"
        assert provider._next_key() == "key1"

    def test_model_alias_resolution(self):
        provider = GeminiProvider(api_keys=["test-key"])
        payload, model = provider._build_payload(
            LLMRequest(model="gemini-flash-lite-latest", messages=[Message(role="user", content="Hi")])
        )
        assert model == "gemini-flash-latest"

    @pytest.mark.asyncio
    async def test_generate_success(self):
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "Hello from Gemini!"}]
                    },
                    "finishReason": "STOP"
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 10,
                "candidatesTokenCount": 5,
                "totalTokenCount": 15
            }
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        provider = GeminiProvider(api_keys=["test-key"], client=mock_client)

        req = LLMRequest(
            model="gemini-flash-lite-latest",
            messages=[Message(role="user", content="Hi")],
        )
        res = await provider.generate(req)
        assert res.content == "Hello from Gemini!"
        assert provider.provider_name == "gemini"
        assert res.total_tokens == 15

    @pytest.mark.asyncio
    async def test_generate_rate_limit_rotates_and_retries(self):
        resp_429 = MagicMock(spec=httpx.Response)
        resp_429.status_code = 429
        resp_429.text = "Quota exceeded"

        mock_client = AsyncMock()
        mock_client.post.return_value = resp_429
        provider = GeminiProvider(api_keys=["key1", "key2"], client=mock_client)

        req = LLMRequest(
            model="gemini-flash-lite-latest",
            messages=[Message(role="user", content="Hi")],
        )
        with pytest.raises(LLMRateLimitError):
            await provider.generate(req)

        assert mock_client.post.call_count == 3


class TestGeminiEmbeddingProvider:
    def test_init_dimensions(self):
        provider = GeminiEmbeddingProvider(api_keys=["test-key"], dimensions=768)
        assert provider.embedding_dimensions == 768
        assert provider.provider_name == "gemini"

    @pytest.mark.asyncio
    async def test_embed_batch_success(self):
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "embeddings": [
                {"values": [0.1] * 768},
                {"values": [0.2] * 768},
            ]
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        provider = GeminiEmbeddingProvider(api_keys=["test-key"], dimensions=768, client=mock_client)

        vecs = await provider.embed_batch(["text 1", "text 2"])
        assert len(vecs) == 2
        assert len(vecs[0]) == 768
        assert len(vecs[1]) == 768

    @pytest.mark.asyncio
    async def test_embed_empty(self):
        provider = GeminiEmbeddingProvider(api_keys=["test-key"])
        vecs = await provider.embed_batch([])
        assert vecs == []
