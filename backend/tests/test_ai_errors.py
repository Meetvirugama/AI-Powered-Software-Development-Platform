import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.core.errors import APIError, ErrorCode
from ai.schemas.output import RepositoryAnswer

# We are testing the RAGPipeline which we will build in ai.pipeline
# If this import fails, it means we need to build the pipeline (Step 2!)
from ai.pipeline import RAGPipeline
from ai.llm.schemas import LLMTimeoutError, LLMUnavailableError

@pytest.mark.asyncio
async def test_llm_timeout_returns_structured_error():
    """Test that an LLM timeout gracefully returns an APIError (503 Service Unavailable)."""
    mock_llm = AsyncMock()
    mock_llm.generate.side_effect = LLMTimeoutError()
    pipeline = RAGPipeline(llm_gateway=mock_llm, retriever=AsyncMock())
    
    with pytest.raises(APIError) as exc_info:
        await pipeline.chat("How does auth work?", uuid4(), [])
        
    assert exc_info.value.code == ErrorCode.SERVICE_UNAVAILABLE
    assert "timed out" in exc_info.value.message.lower()
    assert exc_info.value.retryable is True

@pytest.mark.asyncio
async def test_llm_unavailable_retries_then_fails_gracefully():
    """Test that when OpenAI is down, it gracefully returns a retryable APIError."""
    mock_llm = AsyncMock()
    mock_llm.generate.side_effect = LLMUnavailableError("OpenAI is down")
    pipeline = RAGPipeline(llm_gateway=mock_llm, retriever=AsyncMock())
    
    with pytest.raises(APIError) as exc_info:
        await pipeline.chat("How does auth work?", uuid4(), [])
        
    assert exc_info.value.code == ErrorCode.SERVICE_UNAVAILABLE
    assert "unavailable" in exc_info.value.message.lower()
    assert exc_info.value.retryable is True

@pytest.mark.asyncio
async def test_zero_retrieval_results_returns_no_context_message():
    """Test that when DB search returns 0 results, it returns a safe fallback message."""
    mock_retriever = AsyncMock()
    mock_retriever.retrieve.return_value = []
    pipeline = RAGPipeline(retriever=mock_retriever)
    
    response = await pipeline.chat("How does auth work?", uuid4(), [])
    
    assert isinstance(response, RepositoryAnswer)
    assert "no relevant code found" in response.answer.lower()
    assert len(response.sources) == 0

@pytest.mark.asyncio
async def test_invalid_json_triggers_repair_loop():
    """Test that invalid JSON triggers a retry, and succeeds if the 2nd attempt is valid."""
    mock_llm = AsyncMock()
    # First call returns broken JSON, second call returns valid JSON
    mock_llm.generate.side_effect = [
        AsyncMock(content="```json\n{ bad json \n```"), 
        AsyncMock(content='{"answer": "Auth is handled via JWT", "sources": [], "confidence": "high"}')
    ]
    
    mock_retriever = AsyncMock()
    mock_retriever.retrieve.return_value = ["fake_chunk"]
    
    pipeline = RAGPipeline(llm_gateway=mock_llm, retriever=mock_retriever)
    response = await pipeline.chat("How does auth work?", uuid4(), [])
    
    # Assert that the AI was called exactly 2 times (proving the repair loop worked)
    assert mock_llm.generate.call_count == 2
    assert response.answer == "Auth is handled via JWT"
