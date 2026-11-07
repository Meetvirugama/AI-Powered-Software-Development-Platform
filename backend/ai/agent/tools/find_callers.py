"""
Repository Tool: find_callers (task.md §10.4).

Finds functions, methods, or callers that invoke a specified target symbol.
Inspects incoming symbol edges ('calls', 'invokes') from the repository graph.
"""

from __future__ import annotations

import logging
from typing import Any

from app.models.code_symbol import CodeSymbol as DBCodeSymbol
from app.models.repository_file import RepositoryFile as DBRepoFile
from app.models.symbol_edge import SymbolEdge as DBSymbolEdge
from sqlalchemy import select

from ai.agent.db import run_db_query
from ai.agent.errors import AgentToolExecutionError
from ai.agent.policy import sanitize_relative_path, validate_symbol_name
from ai.agent.schemas import AgentEvidenceItem, AgentToolContext, AgentToolResult

logger = logging.getLogger(__name__)

TOOL_NAME = "find_callers"
TOOL_DESCRIPTION = (
    "Find functions, methods, or classes in the repository that call or invoke a given symbol. "
    "Essential for understanding blast radius, caller control flow, and token/auth propagation."
)
TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "symbol_name": {
            "type": "string",
            "description": "Name of the target function or method being invoked.",
        },
        "file_path": {
            "type": "string",
            "description": "Optional repository-relative file path where the target symbol is defined.",
        },
        "limit": {
            "type": "integer",
            "description": "Maximum number of callers to return (1-20, default 8).",
            "default": 8,
        },
    },
    "required": ["symbol_name"],
}


async def run_find_callers(
    call_id: str,
    arguments: dict[str, Any],
    context: AgentToolContext,
) -> AgentToolResult:
    """Find caller symbols via incoming symbol graph edges."""
    raw_name = arguments.get("symbol_name", "")
    raw_path = arguments.get("file_path")
    raw_limit = arguments.get("limit", 8)

    clean_name = validate_symbol_name(raw_name)
    clean_path = sanitize_relative_path(raw_path) if raw_path else None
    try:
        limit = max(1, min(int(raw_limit), 20))
    except (ValueError, TypeError):
        limit = 8

    if context.db_session is None:
        return AgentToolResult(
            call_id=call_id,
            tool_name=TOOL_NAME,
            result={"symbol_name": clean_name, "callers": [], "message": "Database session unavailable."},
            is_error=False,
        )

    try:
        # Step 1: Find target symbol
        stmt_sym = (
            select(DBCodeSymbol)
            .join(DBRepoFile, DBCodeSymbol.file_id == DBRepoFile.id)
            .where(
                DBCodeSymbol.repository_id == context.repository_id,
                DBCodeSymbol.name == clean_name,
            )
        )
        if clean_path:
            stmt_sym = stmt_sym.where(DBRepoFile.path == clean_path)

        target_sym = await run_db_query(context.db_session, stmt_sym, scalar_one=True)

        if target_sym is None:
            return AgentToolResult(
                call_id=call_id,
                tool_name=TOOL_NAME,
                result={
                    "symbol_name": clean_name,
                    "callers": [],
                    "message": f"Target symbol '{clean_name}' not found in repository.",
                },
                is_error=False,
            )

        # Step 2: Query incoming caller edges
        stmt_edges = (
            select(
                DBSymbolEdge.edge_type,
                DBCodeSymbol.name,
                DBCodeSymbol.kind,
                DBCodeSymbol.start_line,
                DBCodeSymbol.end_line,
                DBRepoFile.path,
                DBCodeSymbol.file_id,
            )
            .join(DBCodeSymbol, DBSymbolEdge.source_symbol_id == DBCodeSymbol.id)
            .join(DBRepoFile, DBCodeSymbol.file_id == DBRepoFile.id)
            .where(
                DBSymbolEdge.repository_id == context.repository_id,
                DBSymbolEdge.target_symbol_id == target_sym.id,
                DBSymbolEdge.edge_type.in_(["calls", "invokes"]),
            )
            .limit(limit)
        )

        rows = await run_db_query(context.db_session, stmt_edges, scalar_one=False)

        callers: list[dict[str, Any]] = []
        evidence: list[AgentEvidenceItem] = []

        for row in rows:
            edge_type, c_name, c_kind, s_line, e_line, f_path, file_id = row
            callers.append({
                "caller_symbol": c_name,
                "kind": c_kind,
                "file_path": f_path,
                "start_line": s_line,
                "end_line": e_line,
                "edge_type": edge_type,
            })

            evidence.append(
                AgentEvidenceItem(
                    repository_id=str(context.repository_id),
                    source_type="caller",
                    file_path=f_path,
                    start_line=s_line,
                    end_line=e_line,
                    symbol_name=c_name,
                    content=f"Caller '{c_name}' ({c_kind}) invokes '{clean_name}' at {f_path}:{s_line}-{e_line}",
                    file_id=str(file_id),
                    tool_name=TOOL_NAME,
                )
            )

        return AgentToolResult(
            call_id=call_id,
            tool_name=TOOL_NAME,
            result={
                "target_symbol": clean_name,
                "callers": callers,
                "total_callers_found": len(callers),
            },
            evidence=evidence,
            is_error=False,
        )

    except Exception as exc:
        logger.error("agent_tool_find_callers_failed", extra={"error": str(exc), "symbol": clean_name})
        raise AgentToolExecutionError(f"Failed to find callers for symbol '{clean_name}': {exc}") from exc
