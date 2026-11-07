"""
Repository Tool: search_code (task.md §10.1).

Searches repository code chunks using the existing HybridRetriever service.
Enforces query sanitization, repository scoping, result limits, and evidence collection.
"""

from __future__ import annotations

import logging
from typing import Any

from ai.agent.errors import AgentToolExecutionError
from ai.agent.policy import validate_search_query
from ai.agent.schemas import AgentEvidenceItem, AgentToolContext, AgentToolResult

logger = logging.getLogger(__name__)

TOOL_NAME = "search_code"
TOOL_DESCRIPTION = (
    "Search repository code chunks to find relevant functions, classes, and logic. "
    "Input a semantic or keyword query describing the code logic you are investigating."
)
TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Search query describing the function, logic, or bug to locate.",
        },
        "top_k": {
            "type": "integer",
            "description": "Number of candidate results to return (1-10, default 5).",
            "default": 5,
        },
    },
    "required": ["query"],
}


async def run_search_code(
    call_id: str,
    arguments: dict[str, Any],
    context: AgentToolContext,
) -> AgentToolResult:
    """Execute hybrid repository code search."""
    raw_query = arguments.get("query", "")
    raw_top_k = arguments.get("top_k", 5)

    query, top_k = validate_search_query(raw_query, raw_top_k)

    if context.retriever is None or not hasattr(context.retriever, "retrieve"):
        return AgentToolResult(
            call_id=call_id,
            tool_name=TOOL_NAME,
            result={"results": [], "total": 0, "message": "Retriever is currently unavailable."},
            is_error=False,
        )

    try:
        chunks = await context.retriever.retrieve(
            query=query,
            repository_id=context.repository_id,
            top_k=top_k,
        )
    except Exception as exc:
        logger.error("agent_tool_search_code_failed", extra={"error": str(exc), "query": query})
        raise AgentToolExecutionError(f"Search retrieval failed: {exc}") from exc

    formatted_results: list[dict[str, Any]] = []
    evidence_items: list[AgentEvidenceItem] = []

    for c in chunks[:top_k]:
        file_path = getattr(c, "file_path", "") or ""
        start_line = int(getattr(c, "start_line", 1) or 1)
        end_line = int(getattr(c, "end_line", 1) or 1)
        content = str(getattr(c, "content", "") or "")
        score = float(getattr(c, "score", 0.0) or 0.0)
        chunk_id_str = str(getattr(c, "id", ""))

        formatted_results.append({
            "chunk_id": chunk_id_str,
            "file_path": file_path,
            "start_line": start_line,
            "end_line": end_line,
            "score": round(score, 4),
            "content": content,
        })

        evidence_items.append(
            AgentEvidenceItem(
                repository_id=str(context.repository_id),
                source_type="retrieval",
                file_path=file_path,
                start_line=start_line,
                end_line=end_line,
                content=content,
                chunk_id=chunk_id_str,
                score=score,
                tool_name=TOOL_NAME,
            )
        )

    return AgentToolResult(
        call_id=call_id,
        tool_name=TOOL_NAME,
        result={"results": formatted_results, "total": len(formatted_results)},
        evidence=evidence_items,
        is_error=False,
    )
