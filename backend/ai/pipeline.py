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
import re
import time
from typing import Any, Protocol, Self, runtime_checkable
from uuid import UUID

from app.core.errors import APIError, ErrorCode

from ai.context.builder import AgentContext, ChatMessage, ContextBuilder, MemoryEntry
from ai.llm.schemas import (
    LLMError,
    LLMRateLimitError,
    LLMRequest,
    LLMResponse,
    LLMTimeoutError,
    LLMUnavailableError,
    Message,
)
from ai.schemas.grounding import GroundingValidator
from ai.schemas.output import RepositoryAnswer
from ai.schemas.prompt_builder import PromptBuilder

logger = logging.getLogger(__name__)


@runtime_checkable
class RetrieverProtocol(Protocol):
    """Protocol for retriever components compatible with RAGPipeline."""

    async def retrieve(
        self,
        query: str,
        repository_id: UUID,
        top_k: int = 30,
        **kwargs: Any,
    ) -> list[Any]: ...


@runtime_checkable
class LLMGatewayProtocol(Protocol):
    """Protocol for LLM gateways compatible with RAGPipeline."""

    async def generate(self, request: LLMRequest) -> LLMResponse: ...


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
    - Observability: tracks latency per pipeline phase (retrieval, LLM inference).

    Args:
        retriever:        Hybrid retriever or any object implementing ``retrieve(...)``.
        context_builder:  ContextBuilder instance (default: ContextBuilder()).
        llm_gateway:      LLMGateway instance (or duck-typed object with ``generate(...)``).
        prompt_builder:   PromptBuilder instance (default: PromptBuilder()).
        grounding_validator: GroundingValidator instance (default: GroundingValidator()
                          with no DB session — citations pass through as grounded).
        max_context_tokens: Token budget forwarded to ContextBuilder (default 100_000).
        model:            Default model identifier for LLM inference (default: 'gpt-4o').
        max_retrieval_top_k: Maximum candidate chunks fetched per retrieval turn.
        max_repair_attempts: Maximum attempts to repair invalid JSON responses.

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
        # answer.sources → list[SourceReference] pointing to verified real files
    """

    _DEFAULT_TOP_K: int = 30
    _DEFAULT_MODEL: str = "gemini-flash-lite-latest"
    _DEFAULT_MAX_REPAIR_ATTEMPTS: int = 2

    def __init__(
        self,
        retriever: Any = None,
        context_builder: ContextBuilder | None = None,
        llm_gateway: Any = None,
        prompt_builder: PromptBuilder | None = None,
        grounding_validator: GroundingValidator | None = None,
        max_context_tokens: int = 100_000,
        model: str = _DEFAULT_MODEL,
        max_retrieval_top_k: int = _DEFAULT_TOP_K,
        max_repair_attempts: int = _DEFAULT_MAX_REPAIR_ATTEMPTS,
    ) -> None:
        self.retriever = retriever
        self.context_builder = context_builder or ContextBuilder(max_context_tokens=max_context_tokens)
        self.llm = llm_gateway
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.grounding_validator = grounding_validator or GroundingValidator()
        self._model = model
        self._max_retrieval_top_k = max_retrieval_top_k
        self._max_repair_attempts = max_repair_attempts

    # ------------------------------------------------------------------
    # Properties & Configuration
    # ------------------------------------------------------------------

    @property
    def model(self) -> str:
        """Active inference model name."""
        return self._model

    @property
    def max_retrieval_top_k(self) -> int:
        """Candidate retrieval limit."""
        return self._max_retrieval_top_k

    @property
    def max_repair_attempts(self) -> int:
        """Maximum JSON repair loop attempts."""
        return self._max_repair_attempts

    # Backwards compatibility attributes
    @property
    def _MAX_RETRIEVAL_TOP_K(self) -> int:
        return self._max_retrieval_top_k

    @property
    def _LLM_MODEL(self) -> str:
        return self._model

    @property
    def _MAX_REPAIR_ATTEMPTS(self) -> int:
        return self._max_repair_attempts

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def chat(
        self,
        question: str,
        repository_id: UUID | str,
        history: list[ChatMessage | dict],
        memory: list[MemoryEntry] | None = None,
        model: str | None = None,
        system_instruction: str | None = None,
    ) -> RepositoryAnswer:
        """
        Answer a repository-scoped question using the full RAG pipeline.

        Steps:
            1. Validate inputs and normalize conversation history.
            2. Hybrid retrieval → candidate code chunks.
            3. Graceful fallback if no chunks retrieved.
            4. ContextBuilder → token-bounded AgentContext.
            5. PromptBuilder → structured message list.
            6. LLM call with JSON repair loop (max 2 attempts).
            7. GroundingValidator → remove hallucinated citations.
            8. Return validated RepositoryAnswer.

        Args:
            question:      The user's natural-language question.
            repository_id: Scope retrieval and grounding to this repository.
            history:       Previous conversation turns (ChatMessage or plain dicts
                           with ``role`` / ``content`` keys).
            memory:        Optional project memory entries (rules, decisions, etc.).
            model:         Optional model override for this inference request.
            system_instruction: Optional override for system prompt instructions.

        Returns:
            RepositoryAnswer with grounded citations and a confidence level.

        Raises:
            APIError(503, SERVICE_UNAVAILABLE, retryable=True)  — LLM timeout / down / rate limit.
            APIError(500, INTERNAL_SERVER_ERROR)                 — unrecoverable LLM error.
        """
        start_time = time.monotonic()
        cleaned_question = (question or "").strip()
        repo_uuid = self._coerce_uuid(repository_id)
        memory = memory or []
        chat_history = self._normalise_history(history)
        selected_model = model or self._model

        # Guard against empty query
        if not cleaned_question:
            return RepositoryAnswer(
                answer="Please provide a valid question about the repository.",
                sources=[],
                confidence="low",
            )

        # ---- Step 1: Retrieval -------------------------------------------
        retrieval_start = time.monotonic()
        chunks = await self._retrieve(cleaned_question, repo_uuid)
        retrieval_latency_ms = (time.monotonic() - retrieval_start) * 1000

        # ---- Step 2: Graceful fallback for zero retrieval ------------------
        if not chunks:
            logger.warning(
                "rag_pipeline_zero_results",
                extra={
                    "repo_id": str(repo_uuid),
                    "question": cleaned_question[:100],
                    "retrieval_latency_ms": round(retrieval_latency_ms, 2),
                },
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
            question=cleaned_question,
        )

        # ---- Step 5: LLM call with JSON repair loop ----------------------
        llm_start = time.monotonic()
        raw_answer = await self._generate_with_repair(
            messages=messages,
            original_question=cleaned_question,
            model=selected_model,
        )
        llm_latency_ms = (time.monotonic() - llm_start) * 1000

        # ---- Step 6: Grounding validation --------------------------------
        validated = await self.grounding_validator.validate_sources(
            raw_answer, repo_uuid
        )

        total_latency_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "rag_pipeline_complete",
            extra={
                "repo_id": str(repo_uuid),
                "chunks_used": len(ctx.code_chunks),
                "total_tokens": getattr(ctx, "total_tokens", 0),
                "chunk_tokens": getattr(ctx, "chunk_tokens", 0),
                "memory_tokens": getattr(ctx, "memory_tokens", 0),
                "history_tokens": getattr(ctx, "history_tokens", 0),
                "sources_before": len(raw_answer.sources),
                "sources_after": len(validated.sources),
                "confidence": validated.confidence,
                "retrieval_latency_ms": round(retrieval_latency_ms, 2),
                "llm_latency_ms": round(llm_latency_ms, 2),
                "total_latency_ms": round(total_latency_ms, 2),
            },
        )

        return validated

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _coerce_uuid(value: UUID | str) -> UUID:
        """Coerce string or UUID to verified UUID instance."""
        if isinstance(value, UUID):
            return value
        try:
            return UUID(str(value))
        except (ValueError, AttributeError, TypeError):
            logger.warning("rag_pipeline_invalid_uuid", extra={"raw_value": str(value)})
            # Fallback UUID for non-standard inputs in mock scenarios
            import hashlib
            raw_str = str(value) if value is not None else "00000000"
            return UUID(hashlib.md5(raw_str.encode("utf-8")).hexdigest())

    async def retrieve(
        self,
        query: str,
        repository_id: UUID | str,
        top_k: int = 30,
    ) -> list[Any]:
        """
        Public retrieval endpoint matching RetrievalPipeline contract.
        Supports hybrid retrieval across pgvector and lexical FTS.
        """
        repo_uuid = self._coerce_uuid(repository_id)
        if self.retriever is None:
            logger.debug("rag_pipeline_no_retriever")
            return []

        try:
            return await self.retriever.retrieve(
                query=query,
                repository_id=repo_uuid,
                top_k=top_k,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "rag_pipeline_retrieval_error",
                extra={"error": str(exc), "repo_id": str(repo_uuid)},
            )
            return []

    async def _retrieve(
        self,
        query: str,
        repository_id: UUID,
    ) -> list[Any]:
        """Internal retrieval delegating to public retrieve()."""
        return await self.retrieve(query, repository_id, top_k=self._max_retrieval_top_k)

    @staticmethod
    def _normalise_history(
        history: list[ChatMessage | dict | Any],
    ) -> list[ChatMessage]:
        """Accept ChatMessage dataclasses, dicts, or duck-typed objects."""
        normalised: list[ChatMessage] = []
        for item in history:
            if isinstance(item, ChatMessage):
                normalised.append(item)
            elif isinstance(item, dict):
                normalised.append(
                    ChatMessage(
                        role=item.get("role", "user"),
                        content=item.get("content", ""),
                    )
                )
            elif hasattr(item, "role") and hasattr(item, "content"):
                normalised.append(
                    ChatMessage(
                        role=getattr(item, "role", "user"),
                        content=getattr(item, "content", ""),
                    )
                )
        return normalised

    @staticmethod
    def _clean_json_content(raw: str) -> str:
        """
        Strip markdown code fences and surrounding prose from LLM JSON responses.

        Handles:
        - ```json { ... } ```
        - ``` { ... } ```
        - Leading / trailing prose around the fence
        - Raw JSON without fences
        """
        content = raw.strip()
        # Regex search for ```json ... ``` or ``` ... ```
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
        if match:
            return match.group(1).strip()

        # Fallback manual fence removal if fence wasn't properly closed
        if content.startswith("```"):
            lines = content.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].rstrip().endswith("```"):
                lines = lines[:-1]
            return "\n".join(lines).strip()

        return content

    async def _generate_with_repair(
        self,
        messages: list[Message],
        original_question: str,
        model: str | None = None,
    ) -> RepositoryAnswer:
        """
        Call the LLM and apply a self-healing JSON repair loop if output is malformed.

        Attempts up to ``_max_repair_attempts`` times. On final failure, raises
        APIError(500) so the caller can return a structured error to the API consumer.

        Raises:
            APIError(503) — on LLM timeout, rate limit, or unavailability (retryable).
            APIError(500) — on unrecoverable LLM errors.
        """
        if self.llm is None:
            # Fallback for tests or environments without an injected LLM gateway
            return RepositoryAnswer(
                answer="LLM gateway not configured.",
                sources=[],
                confidence="low",
            )

        target_model = model or self._model
        req = LLMRequest(
            model=target_model,
            messages=list(messages),
            response_schema=RepositoryAnswer,
        )

        for attempt in range(self._max_repair_attempts):
            try:
                response = await self.llm.generate(req)
                content = self._clean_json_content(getattr(response, "content", ""))

                try:
                    data = json.loads(content)
                    return RepositoryAnswer(**data)

                except (json.JSONDecodeError, ValueError, TypeError) as parse_err:
                    if attempt == self._max_repair_attempts - 1:
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
                    "LLM provider timed out while generating the response. Please try again.",
                    retryable=True,
                ) from exc

            except (LLMUnavailableError, LLMRateLimitError) as exc:
                is_rate_limit = isinstance(exc, LLMRateLimitError)
                msg = (
                    "Rate limit exceeded while querying LLM provider. Please retry shortly."
                    if is_rate_limit
                    else "LLM provider is currently unavailable. Please try again later."
                )
                raise APIError(
                    503,
                    ErrorCode.SERVICE_UNAVAILABLE,
                    msg,
                    retryable=True,
                ) from exc

            except LLMError as exc:
                raise APIError(
                    500,
                    ErrorCode.INTERNAL_SERVER_ERROR,
                    str(exc),
                ) from exc

        # Defensive fallback — should be unreachable as final attempt raises APIError(500)
        raise APIError(
            500,
            ErrorCode.INTERNAL_SERVER_ERROR,
            "Failed to generate answer after all repair attempts.",
        )

    # ------------------------------------------------------------------
    # Resource Lifecycle Management
    # ------------------------------------------------------------------

    async def aclose(self) -> None:
        """Gracefully close any resources held by retriever or LLM gateway."""
        if hasattr(self.llm, "aclose") and callable(self.llm.aclose):
            await self.llm.aclose()
        if hasattr(self.retriever, "aclose") and callable(self.retriever.aclose):
            await self.retriever.aclose()

    async def __aenter__(self: Self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        await self.aclose()
