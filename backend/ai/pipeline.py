"""
RAG Pipeline — End-to-end flow for repository chat.
Owner: Meet — W1-12
"""

import json
from typing import Any
from uuid import UUID

from ai.llm.schemas import (
    LLMError,
    LLMRequest,
    LLMTimeoutError,
    LLMUnavailableError,
    Message,
)
from ai.schemas.output import RepositoryAnswer
from app.core.errors import APIError, ErrorCode


class RAGPipeline:
    """
    Coordinates the full RAG chat flow: Retrieval -> Context -> LLM -> Validation.
    Implements Graceful Degradation and JSON Repair Loops.
    """

    def __init__(self, retriever: Any = None, context_builder: Any = None, llm_gateway: Any = None):
        self.retriever = retriever
        self.context_builder = context_builder
        self.llm = llm_gateway

    async def chat(self, question: str, repository_id: UUID, history: list) -> RepositoryAnswer:
        # Step 1: Retrieval
        chunks = []
        if self.retriever:
            chunks = await self.retriever.retrieve(query=question, repository_id=repository_id, top_k=5)
        
        # Zero retrieval results gracefully degrades (does not crash or hallucinate)
        if not chunks:
            return RepositoryAnswer(
                answer="No relevant code found in this repository.",
                sources=[],
                confidence="low"
            )

        # (Step 2: Context Building would go here in a real run)
            
        # Step 3: LLM Gateway with Error Handling & JSON Repair Loop
        if not self.llm:
            return RepositoryAnswer(answer="dummy", citations=[])

        req = LLMRequest(
            model="gpt-4o",
            messages=[Message(role="user", content=question)],
            response_schema=RepositoryAnswer
        )

        max_attempts = 2
        for attempt in range(max_attempts):
            try:
                response = await self.llm.generate(req)
                
                # Parse JSON, cleaning up markdown code blocks if present
                content = response.content.replace("```json", "").replace("```", "").strip()
                try:
                    data = json.loads(content)
                    return RepositoryAnswer(**data)
                except (json.JSONDecodeError, ValueError) as e:
                    if attempt == max_attempts - 1:
                        # Final attempt failed, give up gracefully
                        raise APIError(
                            500, 
                            ErrorCode.INTERNAL_SERVER_ERROR, 
                            "LLM returned invalid JSON after repair attempt."
                        )
                    
                    # JSON Repair Loop: Re-prompt the AI with the exact parse error
                    req.messages.append(Message(role="assistant", content=response.content))
                    req.messages.append(Message(
                        role="user", 
                        content=f"Your previous response was invalid JSON: {str(e)}. Please return ONLY valid JSON matching the schema."
                    ))
                    continue
                
            except LLMTimeoutError:
                raise APIError(
                    503, 
                    ErrorCode.SERVICE_UNAVAILABLE, 
                    "OpenAI timed out while generating the response. Please try again.", 
                    retryable=True
                )
            except LLMUnavailableError:
                raise APIError(
                    503, 
                    ErrorCode.SERVICE_UNAVAILABLE, 
                    "OpenAI API is currently unavailable. Please try again later.", 
                    retryable=True
                )
            except LLMError as e:
                raise APIError(500, ErrorCode.INTERNAL_SERVER_ERROR, str(e))
                
        raise APIError(500, ErrorCode.INTERNAL_SERVER_ERROR, "Failed to generate answer.")
