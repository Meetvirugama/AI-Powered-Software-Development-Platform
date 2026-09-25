"""
Unit tests for the Embedding Service — Day 3 requirements.
Owner: Meet (implementation) / Keval (test infrastructure) — W1-12

Tests:
    1. test_embed_returns_correct_vector       — mock API returns 200, vector returned.
    2. test_retry_on_429                       — first call 429, second 200 → success.
    3. test_retry_exhaustion_raises            — all 3 calls 429 → EmbeddingError raised.
    4. test_dimension_mismatch_raises          — vector wrong length → EmbeddingError.
    5. test_embed_batch_splits_into_batches   — 250 texts split into 3 sub-batches.
    6. test_embed_batch_preserves_order        — output order matches input order.
    7. test_embed_batch_empty_list             — empty input → empty output, no API call.
    8. test_timeout_raises_embedding_error     — httpx timeout → EmbeddingError.

Run with:
    pytest backend/tests/test_embedding_service.py -v
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_embedding_response(
    vectors: list[list[float]],
    model: str = "text-embedding-3-small",
) -> dict[str, Any]:
    """Build a minimal OpenAI embeddings API response dict."""
    return {
        "object": "list",
        "data": [
            {"object": "embedding", "index": i, "embedding": vec}
            for i, vec in enumerate(vectors)
        ],
        "model": model,
        "usage": {"prompt_tokens": 10 * len(vectors), "total_tokens": 10 * len(vectors)},
    }


def _make_http_response(status_code: int, json_body: dict | None = None) -> MagicMock:
    """Create a mock httpx.Response-like object."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.text = ""
    mock_resp.json.return_value = json_body or {}
    return mock_resp


def _fake_vector(dims: int = 1536, value: float = 0.1) -> list[float]:
    return [value] * dims


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def provider_and_service():
    """Return an OpenAIEmbeddingProvider with a fake key and its EmbeddingService wrapper."""
    from ai.embeddings.openai_provider import OpenAIEmbeddingProvider
    from ai.embeddings.service import EmbeddingService

    provider = OpenAIEmbeddingProvider(api_key="sk-test-key", dimensions=1536)
    service = EmbeddingService(provider=provider)
    return provider, service


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEmbedSingle:
    """EmbeddingService.embed() — single-text embedding."""

    @pytest.mark.asyncio
    async def test_embed_returns_correct_vector(self, provider_and_service):
        """Happy path: API returns 200 with a valid vector."""
        _, service = provider_and_service
        expected_vec = _fake_vector()
        payload = _make_embedding_response([expected_vec])

        with patch(
            "httpx.AsyncClient.post",
            new_callable=AsyncMock,
            return_value=_make_http_response(200, payload),
        ):
            result = await service.embed("def hello(): pass")

        assert result == expected_vec, "Returned vector must exactly match the API response."

    @pytest.mark.asyncio
    async def test_retry_on_429_then_success(self, provider_and_service):
        """First call 429, second 200 → service succeeds after one retry."""
        _, service = provider_and_service
        vec = _fake_vector()
        payload = _make_embedding_response([vec])

        responses = [
            _make_http_response(429),
            _make_http_response(200, payload),
        ]

        with (
            patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=responses),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await service.embed("some code")

        assert result == vec

    @pytest.mark.asyncio
    async def test_retry_exhaustion_raises_embedding_error(self, provider_and_service):
        """All 3 attempts return 429 → EmbeddingError is raised."""
        from ai.embeddings.client import EmbeddingError

        _, service = provider_and_service
        three_429s = [_make_http_response(429)] * 3

        with (
            patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=three_429s),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            with pytest.raises(EmbeddingError) as exc_info:
                await service.embed("some code")

        assert exc_info.value.retryable is True, "Rate-limit error should be marked retryable."

    @pytest.mark.asyncio
    async def test_dimension_mismatch_raises_embedding_error(self, provider_and_service):
        """Provider returns a vector with wrong dimensions → EmbeddingError (non-retryable)."""
        from ai.embeddings.client import EmbeddingError

        _, service = provider_and_service
        wrong_dim_vec = _fake_vector(dims=512)  # provider expects 1536
        payload = _make_embedding_response([wrong_dim_vec])

        with patch(
            "httpx.AsyncClient.post",
            new_callable=AsyncMock,
            return_value=_make_http_response(200, payload),
        ):
            with pytest.raises(EmbeddingError) as exc_info:
                await service.embed("some code")

        assert exc_info.value.retryable is False, "Dimension mismatch must be non-retryable."
        assert "1536" in str(exc_info.value), "Error message should mention expected dimension."
        assert "512" in str(exc_info.value), "Error message should mention actual dimension."

    @pytest.mark.asyncio
    async def test_timeout_raises_embedding_error(self, provider_and_service):
        """httpx.TimeoutException → EmbeddingError (retryable)."""
        import httpx
        from ai.embeddings.client import EmbeddingError

        _, service = provider_and_service

        with (
            patch(
                "httpx.AsyncClient.post",
                new_callable=AsyncMock,
                side_effect=httpx.TimeoutException("timed out"),
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            with pytest.raises(EmbeddingError) as exc_info:
                await service.embed("some code")

        assert exc_info.value.retryable is True


class TestEmbedBatch:
    """EmbeddingService.embed_batch() — batching, ordering, parallelism."""

    @pytest.mark.asyncio
    async def test_embed_batch_empty_list_returns_empty(self, provider_and_service):
        """Empty input → empty output, no API call made."""
        _, service = provider_and_service

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            result = await service.embed_batch([])

        assert result == []
        mock_post.assert_not_called()

    @pytest.mark.asyncio
    async def test_embed_batch_preserves_order(self, provider_and_service):
        """Output vectors must be in the same order as the input texts."""
        _, service = provider_and_service

        texts = ["first", "second", "third"]
        vectors = [_fake_vector(value=float(i)) for i in range(len(texts))]
        payload = _make_embedding_response(vectors)

        with patch(
            "httpx.AsyncClient.post",
            new_callable=AsyncMock,
            return_value=_make_http_response(200, payload),
        ):
            result = await service.embed_batch(texts)

        assert len(result) == len(texts)
        for i, (expected, actual) in enumerate(zip(vectors, result)):
            assert actual == expected, f"Vector at index {i} does not match."

    @pytest.mark.asyncio
    async def test_embed_batch_splits_into_sub_batches_of_100(self, provider_and_service):
        """250 texts must produce 3 API calls (100 + 100 + 50)."""
        _, service = provider_and_service

        texts = [f"code_{i}" for i in range(250)]

        call_sizes: list[int] = []

        async def fake_post(url, *, json, headers, **kwargs):
            input_texts = json["input"]
            call_sizes.append(len(input_texts))
            vecs = [_fake_vector() for _ in input_texts]
            return _make_http_response(200, _make_embedding_response(vecs))

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=fake_post):
            result = await service.embed_batch(texts)

        assert len(result) == 250
        assert sorted(call_sizes) == [50, 100, 100], (
            f"Expected sub-batches of [100, 100, 50], got {sorted(call_sizes)}"
        )

    @pytest.mark.asyncio
    async def test_embed_batch_single_text(self, provider_and_service):
        """A single-item batch should succeed and return a list of one vector."""
        _, service = provider_and_service

        vec = _fake_vector()
        payload = _make_embedding_response([vec])

        with patch(
            "httpx.AsyncClient.post",
            new_callable=AsyncMock,
            return_value=_make_http_response(200, payload),
        ):
            result = await service.embed_batch(["single item"])

        assert result == [vec]
