"""Hybrid RAG retrieval and chat pipeline.
Owner: Meet — W1-12 / Keval Day 5 integration

Combines VectorRetriever, LexicalRetriever, RRFFusion, and CrossEncoderReranker
into an integrated pipeline consumed by API endpoints and tests.
"""

from __future__ import annotations

import logging
from typing import List, Optional
from uuid import UUID

from ai.schemas.grounding import GroundingValidator
from ai.schemas.output import RepositoryAnswer, SourceReference
from .base import CodeChunk
from .fusion import RRFFusion
from .lexical import LexicalRetriever
from .reranker import CrossEncoderReranker
from .vector import VectorRetriever

logger = logging.getLogger(__name__)


class RAGPipeline:
    """Orchestrates hybrid retrieval (vector + lexical + RRF + reranking)

    and grounded question answering over indexed code repositories.
    """

    def __init__(
        self,
        vector_retriever: Optional[VectorRetriever] = None,
        lexical_retriever: Optional[LexicalRetriever] = None,
        fusion: Optional[RRFFusion] = None,
        reranker: Optional[CrossEncoderReranker] = None,
        grounding_validator: Optional[GroundingValidator] = None,
    ) -> None:
        self.vector_retriever = vector_retriever
        self.lexical_retriever = lexical_retriever
        self.fusion = fusion or RRFFusion()
        self.reranker = reranker or CrossEncoderReranker()
        self.grounding_validator = grounding_validator

    async def retrieve(
        self,
        query: str,
        repository_id: UUID,
        top_k: int = 5,
    ) -> List[CodeChunk]:
        """Hybrid retrieve top-k code chunks for a query string."""
        clean_query = query.strip()
        if not clean_query:
            return []

        candidate_lists: List[List[CodeChunk]] = []

        if self.vector_retriever is not None:
            try:
                vec_results = await self.vector_retriever.retrieve(
                    query=clean_query,
                    repository_id=repository_id,
                    top_k=30,
                )
                if vec_results:
                    candidate_lists.append(vec_results)
            except Exception as exc:
                logger.warning("Vector retrieval error: %s", exc)

        if self.lexical_retriever is not None:
            try:
                lex_results = await self.lexical_retriever.retrieve(
                    query=clean_query,
                    repository_id=repository_id,
                    top_k=30,
                )
                if lex_results:
                    candidate_lists.append(lex_results)
            except Exception as exc:
                logger.warning("Lexical retrieval error: %s", exc)

        if not candidate_lists:
            return []

        if len(candidate_lists) == 1:
            fused = candidate_lists[0]
        else:
            fused = self.fusion.fuse(*candidate_lists, top_n=30)

        if not fused:
            return []

        try:
            return self.reranker.rerank(query=clean_query, chunks=fused, top_n=top_k)
        except Exception as exc:
            logger.warning("Cross-encoder reranking error: %s", exc)
            return fused[:top_k]

    async def chat(
        self,
        question: str,
        repository_id: UUID,
        history: Optional[list] = None,
    ) -> RepositoryAnswer:
        """Answer repository question grounded in retrieved code chunks."""
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
