"""
RAG Pipeline — End-to-end flow for repository-aware chat.
Owner: Meet — W1-12

Day 7: Full integration — hybrid retrieval → context builder → prompt builder
         → LLM gateway → output validation → grounding validation → answer.

Flow:
    1. Hybrid retrieval (vector + lexical) via the injected retriever.
    2. ContextBuilder assembles code chunks, memory entries, and chat history
       into a token-budget-aware AgentContext.
    3. PromptBuilder serialises the AgentContext into a properly-structured
       message list (system/data separation rule enforced).
    4. LLMGateway generates the answer with retry and JSON-mode enforcement.
    5. JSON repair loop (up to 2 attempts) if the LLM returns malformed JSON.
    6. GroundingValidator removes hallucinated file/line citations.
    7. Return validated RepositoryAnswer.

team_rules.md rules enforced:
  - Repository content NEVER appears in the system prompt (PromptBuilder).
  - Every LLM call is logged via LLMGateway (not called directly here).
  - GroundingValidator runs before the answer reaches the caller.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from ai.context.builder import AgentContext, ChatMessage, ContextBuilder, MemoryEntry
from ai.llm.schemas import (
    LLMError,
    LLMRequest,
    LLMTimeoutError,
    LLMUnavailableError,
    Message,
)
from ai.schemas.grounding import GroundingValidator
from ai.schemas.output import RepositoryAnswer
from ai.schemas.prompt_builder import PromptBuilder
from app.core.errors import APIError, ErrorCode

logger = logging.getLogger(__name__)


class RAGPipeline:
    """
    Coordinates the full repository-aware RAG chat flow.

    Design decisions:
    - All dependencies are injected at construction time → fully testable.
    - Each step is a well-defined method → easy to mock in unit tests.
    - Graceful degradation: if retrieval returns zero chunks, return a safe
      "no relevant code found" response rather than hallucinating.
    - JSON repair loop: up to 2 LLM retries if the first response is malformed.
    - Grounding validation: hallucinated citations are removed before the answer
      is returned to the caller.

    Args:
        retriever:        Hybrid retriever (VectorRetriever | LexicalRetriever or any
                          object with ``async retrieve(query, repository_id, top_k)``.
        context_builder:  ContextBuilder instance (default: ContextBuilder()).
        llm_gateway:      LLMGateway instance.
        prompt_builder:   PromptBuilder instance (default: PromptBuilder()).
        grounding_validator: GroundingValidator instance (default: GroundingValidator()
                          with no DB session — citations pass through as grounded).
        max_context_tokens: Token budget forwarded to ContextBuilder (default 100_000).

    Usage::

        pipeline = RAGPipeline(
            retriever=HybridRetriever(...),
            llm_gateway=LLMGateway(provider=OpenAIProvider()),
        )
        answer = await pipeline.chat(
            question="Where is authentication implemented?",
            repository_id=repo_id,
            history=[],
        )
        # answer.sources → list[SourceReference] pointing to real files
    """

    _MAX_RETRIEVAL_TOP_K: int = 30   # Top-K per retriever path (for RRF input)
    _MAX_RERANKED_CHUNKS: int = 8    # Chunks passed to ContextBuilder after reranking
    _LLM_MODEL: str = "gpt-4o"
    _MAX_REPAIR_ATTEMPTS: int = 2    # JSON repair loop limit

    def __init__(
        self,
        retriever: Any = None,
        context_builder: ContextBuilder | None = None,
        llm_gateway: Any = None,
        prompt_builder: PromptBuilder | None = None,
        grounding_validator: GroundingValidator | None = None,
        max_context_tokens: int = 100_000,
    ) -> None:
        self.retriever = retriever
        self.context_builder = context_builder or ContextBuilder(max_context_tokens=max_context_tokens)
        self.llm = llm_gateway
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.grounding_validator = grounding_validator or GroundingValidator()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def chat(
        self,
        question: str,
        repository_id: UUID,
        history: list[ChatMessage | dict],
        memory: list[MemoryEntry] | None = None,
    ) -> RepositoryAnswer:
        """
        Answer a repository-scoped question using the full RAG pipeline.

        Steps:
            1. Hybrid retrieval → top-K code chunks.
            2. Graceful fallback if no chunks retrieved.
            3. ContextBuilder → token-bounded AgentContext.
            4. PromptBuilder → structured message list.
            5. LLM call with JSON repair loop (max 2 attempts).
            6. GroundingValidator → remove hallucinated citations.
            7. Return validated RepositoryAnswer.

        Args:
            question:      The user's natural-language question.
            repository_id: Scope retrieval and grounding to this repository.
            history:       Previous conversation turns (ChatMessage or plain dicts
                           with ``role`` / ``content`` keys).
            memory:        Optional project memory entries (rules, decisions, etc.).

        Returns:
            RepositoryAnswer with grounded citations and a confidence level.

        Raises:
            APIError(503, SERVICE_UNAVAILABLE, retryable=True)  — LLM timeout / down.
            APIError(500, INTERNAL_SERVER_ERROR)                 — unrecoverable LLM error.
        """
        memory = memory or []
        chat_history = self._normalise_history(history)

        # ---- Step 1: Retrieval -------------------------------------------
        chunks = await self._retrieve(question, repository_id)

        # ---- Step 2: Graceful fallback for zero retrieval ------------------
        if not chunks:
            logger.warning(
                "rag_pipeline_zero_results",
                extra={"repo_id": str(repository_id), "question": question[:100]},
            )
            return RepositoryAnswer(
                answer="No relevant code found in this repository for your question.",
                sources=[],
                confidence="low",
            )

        # ---- Step 3: Context assembly ------------------------------------
        ctx: AgentContext = self.context_builder.build(
            chunks=chunks,
            memory=memory,
            history=chat_history,
        )

        # ---- Step 4: Prompt construction ---------------------------------
        rendered_data = self.context_builder.render_repository_data(ctx)
        messages = self.prompt_builder.build_chat_prompt(
            context=rendered_data,
            question=question,
        )

        # ---- Step 5: LLM call with JSON repair loop ----------------------
        raw_answer = await self._generate_with_repair(messages, question)

        # ---- Step 6: Grounding validation --------------------------------
        validated = await self.grounding_validator.validate_sources(
            raw_answer, repository_id
        )

        logger.info(
            "rag_pipeline_complete",
            extra={
                "repo_id": str(repository_id),
                "chunks_used": len(ctx.code_chunks),
                "total_tokens": ctx.total_tokens,
                "sources_before": len(raw_answer.sources),
                "sources_after": len(validated.sources),
                "confidence": validated.confidence,
            },
        )

        return validated

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _retrieve(
        self,
        query: str,
        repository_id: UUID,
    ) -> list:
        """
        Run retrieval. Returns an empty list if no retriever is configured.

        The retriever may be a VectorRetriever, LexicalRetriever, HybridRetriever,
        or any mock object that implements the same async interface.
        """
        if self.retriever is None:
            logger.debug("rag_pipeline_no_retriever")
            return []

        try:
            return await self.retriever.retrieve(
                query=query,
                repository_id=repository_id,
                top_k=self._MAX_RETRIEVAL_TOP_K,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "rag_pipeline_retrieval_error",
                extra={"error": str(exc), "repo_id": str(repository_id)},
            )
            return []

    @staticmethod
    def _normalise_history(
        history: list[ChatMessage | dict],
    ) -> list[ChatMessage]:
        """Accept both ChatMessage dataclasses and plain dicts (API layer convenience)."""
        normalised: list[ChatMessage] = []
        for item in history:
            if isinstance(item, ChatMessage):
                normalised.append(item)
            elif isinstance(item, dict):
                normalised.append(
                    ChatMessage(role=item.get("role", "user"), content=item.get("content", ""))
                )
        return normalised

    async def _generate_with_repair(
        self,
        messages: list[Message],
        original_question: str,
    ) -> RepositoryAnswer:
        """
        Call the LLM and apply a JSON repair loop if the response is malformed.

        Attempts up to ``_MAX_REPAIR_ATTEMPTS`` times. On the final failure,
        raises APIError(500) so the caller can return a structured error to
        the API consumer.

        Raises:
            APIError(503) — on LLM timeout or unavailability (retryable).
            APIError(500) — on unrecoverable LLM errors.
        """
        if self.llm is None:
            # Fallback for tests that don't inject an LLM
            return RepositoryAnswer(
                answer="LLM gateway not configured.",
                sources=[],
                confidence="low",
            )

        req = LLMRequest(
            model=self._LLM_MODEL,
            messages=list(messages),
            response_schema=RepositoryAnswer,
        )

        last_parse_error: Exception | None = None

        for attempt in range(self._MAX_REPAIR_ATTEMPTS):
            try:
                response = await self.llm.generate(req)

                # Strip markdown code fences if the LLM wraps JSON in ```json ... ```
                content = response.content
                if content.startswith("```"):
                    content = content.split("```", 2)[-1]
                    if content.startswith("json"):
                        content = content[4:]
                    # Remove trailing ```
                    if "```" in content:
                        content = content.rsplit("```", 1)[0]
                content = content.strip()

                try:
                    data = json.loads(content)
                    return RepositoryAnswer(**data)

                except (json.JSONDecodeError, ValueError, TypeError) as parse_err:
                    last_parse_error = parse_err

                    if attempt == self._MAX_REPAIR_ATTEMPTS - 1:
                        # Final attempt — give up
                        logger.error(
                            "rag_pipeline_json_repair_exhausted",
                            extra={
                                "attempt": attempt + 1,
                                "error": str(parse_err),
                                "raw_response": content[:200],
                            },
                        )
                        raise APIError(
                            500,
                            ErrorCode.INTERNAL_SERVER_ERROR,
                            "LLM returned invalid JSON after repair attempt.",
                        )

                    # Inject repair prompt and retry
                    logger.warning(
                        "rag_pipeline_json_repair_attempt",
                        extra={"attempt": attempt + 1, "error": str(parse_err)},
                    )
                    req.messages.append(
                        Message(role="assistant", content=response.content)
                    )
                    req.messages.append(
                        Message(
                            role="user",
                            content=(
                                f"Your previous response was invalid JSON: {parse_err}. "
                                "Please return ONLY a valid JSON object matching the schema. "
                                "Do not wrap it in markdown code fences."
                            ),
                        )
                    )

            except LLMTimeoutError as exc:
                raise APIError(
                    503,
                    ErrorCode.SERVICE_UNAVAILABLE,
                    "OpenAI timed out while generating the response. Please try again.",
                    retryable=True,
                ) from exc

            except LLMUnavailableError as exc:
                raise APIError(
                    503,
                    ErrorCode.SERVICE_UNAVAILABLE,
                    "OpenAI API is currently unavailable. Please try again later.",
                    retryable=True,
                ) from exc

            except LLMError as exc:
                raise APIError(
                    500,
                    ErrorCode.INTERNAL_SERVER_ERROR,
                    str(exc),
                ) from exc

        # Should be unreachable — the loop always raises on the final attempt
        raise APIError(
            500,
            ErrorCode.INTERNAL_SERVER_ERROR,
            "Failed to generate answer after all repair attempts.",
        )
