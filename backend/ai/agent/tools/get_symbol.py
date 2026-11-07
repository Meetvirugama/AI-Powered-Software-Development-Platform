"""
Repository Tool: get_symbol (task.md §10.3).

Inspects a specific function, class, or method symbol definition in the repository.
Returns signature, kind, file path, line range, and source snippet.
"""

from __future__ import annotations

import logging
from typing import Any

from app.models.code_chunk import CodeChunk as DBCodeChunk
from app.models.code_symbol import CodeSymbol as DBCodeSymbol
from app.models.repository_file import RepositoryFile as DBRepoFile
from indexer.chunker import reconstruct_file_from_chunks
from sqlalchemy import select

from ai.agent.db import run_db_query
from ai.agent.errors import AgentToolExecutionError
from ai.agent.policy import sanitize_relative_path, validate_symbol_name
from ai.agent.schemas import AgentEvidenceItem, AgentToolContext, AgentToolResult

logger = logging.getLogger(__name__)

TOOL_NAME = "get_symbol"
TOOL_DESCRIPTION = (
    "Inspect a function, class, or method symbol definition in the repository. "
    "Returns definition signature, file location, line range, and relevant implementation excerpt."
)
TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "symbol_name": {
            "type": "string",
            "description": "Exact name of the symbol (e.g. 'refresh_access_token', 'AuthService').",
        },
        "file_path": {
            "type": "string",
            "description": "Optional repository-relative file path to resolve ambiguity if multiple symbols share the name.",
        },
    },
    "required": ["symbol_name"],
}


async def run_get_symbol(
    call_id: str,
    arguments: dict[str, Any],
    context: AgentToolContext,
) -> AgentToolResult:
    """Retrieve code symbol definition and source excerpt."""
    raw_name = arguments.get("symbol_name", "")
    raw_path = arguments.get("file_path")

    clean_name = validate_symbol_name(raw_name)
    clean_path = sanitize_relative_path(raw_path) if raw_path else None

    if context.db_session is None:
        return AgentToolResult(
            call_id=call_id,
            tool_name=TOOL_NAME,
            result={"symbol_name": clean_name, "found": False, "message": "Database session unavailable."},
            is_error=False,
        )

    try:
        stmt = (
            select(DBCodeSymbol, DBRepoFile.path)
            .join(DBRepoFile, DBCodeSymbol.file_id == DBRepoFile.id)
            .where(
                DBCodeSymbol.repository_id == context.repository_id,
                DBCodeSymbol.name == clean_name,
            )
        )
        if clean_path:
            stmt = stmt.where(DBRepoFile.path == clean_path)

        rows = await run_db_query(context.db_session, stmt, scalar_one=False)

        if not rows:
            return AgentToolResult(
                call_id=call_id,
                tool_name=TOOL_NAME,
                result={
                    "symbol_name": clean_name,
                    "found": False,
                    "message": f"Symbol '{clean_name}' not found in indexed repository symbols.",
                },
                is_error=False,
            )

        # Primary candidate
        primary_row = rows[0]
        sym = primary_row[0] if isinstance(primary_row, tuple) else primary_row
        file_path = primary_row[1] if isinstance(primary_row, tuple) else ""

        # Fetch chunks to get source excerpt
        stmt_chunks = (
            select(DBCodeChunk)
            .where(
                DBCodeChunk.repository_id == context.repository_id,
                DBCodeChunk.file_id == sym.file_id,
            )
            .order_by(DBCodeChunk.start_line)
        )
        chunks = await run_db_query(context.db_session, stmt_chunks, scalar_one=False)

        excerpt = ""
        if chunks:
            excerpt = reconstruct_file_from_chunks(
                chunks,
                start_line=sym.start_line,
                end_line=min(sym.end_line, sym.start_line + 150),
            )

        evidence = [
            AgentEvidenceItem(
                repository_id=str(context.repository_id),
                source_type="symbol",
                file_path=file_path,
                start_line=sym.start_line,
                end_line=sym.end_line,
                symbol_name=sym.name,
                content=excerpt,
                file_id=str(sym.file_id),
                tool_name=TOOL_NAME,
            )
        ]

        candidate_list: list[dict[str, Any]] = []
        for r in rows:
            s_item = r[0] if isinstance(r, tuple) else r
            p_item = r[1] if isinstance(r, tuple) else ""
            candidate_list.append({
                "symbol_id": str(s_item.id),
                "name": s_item.name,
                "kind": s_item.kind,
                "signature": s_item.signature,
                "file_path": p_item,
                "start_line": s_item.start_line,
                "end_line": s_item.end_line,
            })

        return AgentToolResult(
            call_id=call_id,
            tool_name=TOOL_NAME,
            result={
                "found": True,
                "symbol": candidate_list[0],
                "all_matches": candidate_list if len(candidate_list) > 1 else None,
                "source_excerpt": excerpt,
            },
            evidence=evidence,
            is_error=False,
        )

    except Exception as exc:
        logger.error("agent_tool_get_symbol_failed", extra={"error": str(exc), "symbol": clean_name})
        raise AgentToolExecutionError(f"Failed to lookup symbol '{clean_name}': {exc}") from exc
