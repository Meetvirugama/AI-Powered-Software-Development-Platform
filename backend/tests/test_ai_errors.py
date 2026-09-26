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
    pipeline = RAGPipeline()
    
    with patch("ai.pipeline.LLMGateway.generate", new_callable=AsyncMock) as mock_generate:
        mock_generate.side_effect = LLMTimeoutError("Request timed out after 30s")
        
        with pytest.raises(APIError) as exc_info:
            await pipeline.chat("How does auth work?", uuid4(), [])
            
        assert exc_info.value.code == ErrorCode.SERVICE_UNAVAILABLE
        assert "timeout" in exc_info.value.message.lower()
        assert exc_info.value.retryable is True

@pytest.mark.asyncio
async def test_llm_unavailable_retries_then_fails_gracefully():
    """Test that when OpenAI is down, it gracefully returns a retryable APIError."""
    pipeline = RAGPipeline()
    
    with patch("ai.pipeline.LLMGateway.generate", new_callable=AsyncMock) as mock_generate:
        mock_generate.side_effect = LLMUnavailableError("OpenAI is down")
        
        with pytest.raises(APIError) as exc_info:
            await pipeline.chat("How does auth work?", uuid4(), [])
            
        assert exc_info.value.code == ErrorCode.SERVICE_UNAVAILABLE
        assert "unavailable" in exc_info.value.message.lower()
        assert exc_info.value.retryable is True

@pytest.mark.asyncio
async def test_zero_retrieval_results_returns_no_context_message():
    """Test that when DB search returns 0 results, it returns a safe fallback message."""
    pipeline = RAGPipeline()
    
    with patch("ai.pipeline.LexicalRetriever.retrieve", new_callable=AsyncMock) as mock_retrieve:
        mock_retrieve.return_value = []
        
        response = await pipeline.chat("How does auth work?", uuid4(), [])
        
        assert isinstance(response, RepositoryAnswer)
        assert "no relevant code found" in response.answer.lower()
        assert len(response.citations) == 0

@pytest.mark.asyncio
async def test_invalid_json_triggers_repair_loop():
    """Test that invalid JSON triggers a retry, and succeeds if the 2nd attempt is valid."""
    pipeline = RAGPipeline()
    
    with patch("ai.pipeline.LLMGateway.generate", new_callable=AsyncMock) as mock_generate:
        # First call returns broken JSON, second call returns valid JSON
        mock_generate.side_effect = [
            AsyncMock(content="```json\n{ bad json \n```"), 
            AsyncMock(content='{"answer": "Auth is handled via JWT", "citations": []}')
        ]
        
        with patch("ai.pipeline.LexicalRetriever.retrieve", new_callable=AsyncMock) as mock_retrieve:
            # Fake some retrieved code chunks
            mock_retrieve.return_value = ["fake_chunk"]
            
            response = await pipeline.chat("How does auth work?", uuid4(), [])
            
            # Assert that the AI was called exactly 2 times (proving the repair loop worked)
            assert mock_generate.call_count == 2
            assert response.answer == "Auth is handled via JWT"
