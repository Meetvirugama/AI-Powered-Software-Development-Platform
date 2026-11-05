"""Hybrid RAG retrieval and chat pipeline.
Owner: Meet — W1-12 / Keval Day 5 integration

Architecture Notice:
- Canonical RAG chat orchestration resides in `backend.ai.pipeline.RAGPipeline`.
- Canonical hybrid search and ranking resides in `backend.ai.retrieval.HybridRetriever`.
- This module provides the retrieval-oriented `RAGPipeline` facade for Day 5 and Week 1 E2E tests,
  delegating retrieval directly to `HybridRetriever`.
"""

from __future__ import annotations

import logging
from typing import Any, Self
from uuid import UUID

from ai.schemas.grounding import GroundingValidator
from ai.schemas.output import RepositoryAnswer, SourceReference

from .base import CodeChunk
from .fusion import RRFFusion
from .hybrid import HybridRetriever
from .lexical import LexicalRetriever
from .reranker import CrossEncoderReranker
from .vector import VectorRetriever

logger = logging.getLogger(__name__)

__all__ = ["RAGPipeline"]


class RAGPipeline:
    """Retrieval-oriented RAG pipeline coordinating hybrid search and grounded QA.

    For production end-to-end LLM chat generation, use ``ai.pipeline.RAGPipeline``.
    """

    def __init__(
        self,
        vector_retriever: VectorRetriever | None = None,
        lexical_retriever: LexicalRetriever | None = None,
        fusion: RRFFusion | None = None,
        reranker: CrossEncoderReranker | None = None,
        grounding_validator: GroundingValidator | None = None,
        llm_gateway: Any = None,
    ) -> None:
        self.vector_retriever = vector_retriever
        self.lexical_retriever = lexical_retriever
        self.fusion = fusion or RRFFusion()
        self.reranker = reranker or CrossEncoderReranker()
        self.grounding_validator = grounding_validator
        self.llm_gateway = llm_gateway

        self._hybrid_retriever: HybridRetriever | None = None
        if self.vector_retriever is not None or self.lexical_retriever is not None:
            self._hybrid_retriever = HybridRetriever(
                vector_retriever=self.vector_retriever,
                lexical_retriever=self.lexical_retriever,
                fusion=self.fusion,
                reranker=self.reranker,
            )

    @property
    def hybrid_retriever(self) -> HybridRetriever | None:
        """Configured or dynamically aligned HybridRetriever instance."""
        if self._hybrid_retriever is not None:
            if (
                self._hybrid_retriever.vector_retriever is not self.vector_retriever
                or self._hybrid_retriever.lexical_retriever is not self.lexical_retriever
            ):
                self._hybrid_retriever = HybridRetriever(
                    vector_retriever=self.vector_retriever,
                    lexical_retriever=self.lexical_retriever,
                    fusion=self.fusion,
                    reranker=self.reranker,
                )
            return self._hybrid_retriever

        if self.vector_retriever is not None or self.lexical_retriever is not None:
            self._hybrid_retriever = HybridRetriever(
                vector_retriever=self.vector_retriever,
                lexical_retriever=self.lexical_retriever,
                fusion=self.fusion,
                reranker=self.reranker,
            )
        return self._hybrid_retriever

    async def retrieve(
        self,
        query: str,
        repository_id: UUID,
        top_k: int = 5,
    ) -> list[CodeChunk]:
        """Hybrid retrieve top-k code chunks for a query string."""
        clean_query = query.strip()
        if not clean_query:
            return []

        retriever = self.hybrid_retriever
        if retriever is not None:
            return await retriever.retrieve(
                query=clean_query,
                repository_id=repository_id,
                top_k=top_k,
            )

        return []

    async def chat(
        self,
        question: str,
        repository_id: UUID,
        history: list | None = None,
    ) -> RepositoryAnswer:
        """Answer repository question grounded in retrieved code chunks."""
        # If an LLM gateway is configured, delegate to canonical RAGPipeline
        if self.llm_gateway is not None:
            from ai.pipeline import RAGPipeline as CanonicalRAGPipeline
            canonical = CanonicalRAGPipeline(
                retriever=self,
                llm_gateway=self.llm_gateway,
                grounding_validator=self.grounding_validator,
            )
            return await canonical.chat(
                question=question,
                repository_id=repository_id,
                history=history,
            )

        chunks = await self.retrieve(question, repository_id, top_k=5)

        if not chunks:
            return RepositoryAnswer(
                answer="I could not find any relevant information in the repository.",
                sources=[],
                confidence="low",
            )

        sources = [
            SourceReference(
                file=chunk.file_path,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                symbol=None,
            )
            for chunk in chunks
        ]

        distinct_files = sorted({c.file_path for c in chunks if c.file_path})
        files_str = ", ".join(distinct_files) if distinct_files else "the codebase"
        answer = RepositoryAnswer(
            answer=f"Relevant information was found in {files_str}.",
            sources=sources,
            confidence="high" if (chunks and chunks[0].score > 0.5) else "medium",
        )

        if self.grounding_validator is not None:
            answer = await self.grounding_validator.validate_sources(answer, repository_id)

        return answer

    async def aclose(self) -> None:
        """Close child retrieval resources."""
        if self._hybrid_retriever is not None:
            await self._hybrid_retriever.aclose()

    async def __aenter__(self: Self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        await self.aclose()

