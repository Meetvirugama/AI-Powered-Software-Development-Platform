"""
Repository Tool: read_file_range (task.md §10.2).

Inspects a specific line range within an indexed repository file.
Enforces path traversal protection, maximum 150-line spans, byte truncation, and secret redaction.
"""

from __future__ import annotations

import logging
from typing import Any

from app.models.code_chunk import CodeChunk as DBCodeChunk
from app.models.repository_file import RepositoryFile as DBRepoFile
from indexer.chunker import reconstruct_file_from_chunks
from sqlalchemy import select

from ai.agent.db import run_db_query
from ai.agent.errors import AgentToolExecutionError
from ai.agent.policy import sanitize_relative_path, validate_line_range
from ai.agent.schemas import AgentEvidenceItem, AgentToolContext, AgentToolResult

logger = logging.getLogger(__name__)

TOOL_NAME = "read_file_range"
TOOL_DESCRIPTION = (
    "Read a specific line range from an indexed repository file. "
    "Use this after search_code or get_symbol to inspect implementation details."
)
TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "file_path": {
            "type": "string",
            "description": "Repository-relative file path (e.g. 'backend/app/api/v1/auth.py').",
        },
        "start_line": {
            "type": "integer",
            "description": "Starting line number (1-indexed, inclusive).",
        },
        "end_line": {
            "type": "integer",
            "description": "Ending line number (inclusive, maximum 150 lines from start_line).",
        },
    },
    "required": ["file_path", "start_line", "end_line"],
}


async def run_read_file_range(
    call_id: str,
    arguments: dict[str, Any],
    context: AgentToolContext,
) -> AgentToolResult:
    """Execute line-bounded file reading using indexed repository chunks."""
    raw_path = arguments.get("file_path", "")
    raw_start = arguments.get("start_line", 1)
    raw_end = arguments.get("end_line", 1)

    clean_path = sanitize_relative_path(raw_path)
    start_line, end_line = validate_line_range(raw_start, raw_end)

    if context.db_session is None:
        return AgentToolResult(
            call_id=call_id,
            tool_name=TOOL_NAME,
            result={"file_path": clean_path, "content": None, "message": "Database session unavailable."},
            is_error=False,
        )

    try:
        # Step 1: Locate the file record in the repository
        stmt = select(DBRepoFile).where(
            DBRepoFile.repository_id == context.repository_id,
            DBRepoFile.path == clean_path,
        )
        file_record = await run_db_query(context.db_session, stmt, scalar_one=True)

        # Fallback suffix check if exact match fails
        if file_record is None and "/" in clean_path:
            suffix = "/" + clean_path.split("/", 1)[1]
            stmt_suffix = select(DBRepoFile).where(
                DBRepoFile.repository_id == context.repository_id,
                DBRepoFile.path.endswith(suffix),
            )
            file_record = await run_db_query(context.db_session, stmt_suffix, scalar_one=True)

        if file_record is None:
            return AgentToolResult(
                call_id=call_id,
                tool_name=TOOL_NAME,
                result={
                    "file_path": clean_path,
                    "content": None,
                    "message": f"File '{clean_path}' not found in indexed repository files.",
                },
                is_error=False,
            )

        # Step 2: Fetch indexed chunks for this file
        stmt_chunks = (
            select(DBCodeChunk)
            .where(
                DBCodeChunk.repository_id == context.repository_id,
                DBCodeChunk.file_id == file_record.id,
            )
            .order_by(DBCodeChunk.start_line)
        )
        chunks = await run_db_query(context.db_session, stmt_chunks, scalar_one=False)

        if not chunks:
            return AgentToolResult(
                call_id=call_id,
                tool_name=TOOL_NAME,
                result={
                    "file_path": file_record.path,
                    "content": "",
                    "message": f"No indexed content available for file '{file_record.path}'.",
                },
                is_error=False,
            )

        # Step 3: Reconstruct text for requested line range without overlap duplication
        reconstructed = reconstruct_file_from_chunks(
            chunks,
            start_line=start_line,
            end_line=end_line,
        )

        evidence = [
            AgentEvidenceItem(
                repository_id=str(context.repository_id),
                source_type="file_read",
                file_path=file_record.path,
                start_line=start_line,
                end_line=end_line,
                content=reconstructed,
                file_id=str(file_record.id),
                tool_name=TOOL_NAME,
            )
        ]

        return AgentToolResult(
            call_id=call_id,
            tool_name=TOOL_NAME,
            result={
                "file_path": file_record.path,
                "start_line": start_line,
                "end_line": end_line,
                "content": reconstructed,
                "total_file_lines": file_record.line_count,
            },
            evidence=evidence,
            is_error=False,
        )

    except Exception as exc:
        logger.error("agent_tool_read_file_range_failed", extra={"error": str(exc), "file": clean_path})
        raise AgentToolExecutionError(f"Failed to read file range: {exc}") from exc
