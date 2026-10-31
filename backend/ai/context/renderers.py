"""Context rendering and formatting into untrusted prompt sections.
Owner: Meet — W1-12
"""

from __future__ import annotations

from typing import Any

from .models import AgentContext, ChatMessage, IntelligenceContext, MemoryEntry


def format_chunk(chunk: Any) -> str:
    """Render a CodeChunk into the REPOSITORY DATA section."""
    if isinstance(chunk, str):
        return chunk
    file_path = getattr(chunk, "file_path", "unknown")
    start_line = getattr(chunk, "start_line", 0)
    end_line = getattr(chunk, "end_line", 0)

    content = getattr(chunk, "content", str(chunk))
    header = f"--- {file_path} (lines {start_line}–{end_line}) ---"
    return f"{header}\n{content}"


def format_memory(entry: MemoryEntry) -> str:
    """Render a MemoryEntry into the MEMORY section."""
    entry_type = (entry.type or "NOTE").upper()
    return f"[{entry_type}] {entry.content}"


def format_history_message(msg: ChatMessage) -> str:
    """Render a ChatMessage into text for budgeting."""
    role = (msg.role or "USER").upper()
    return f"{role}: {msg.content}"


def render_repository_data(ctx: AgentContext) -> str:
    """
    Render the REPOSITORY DATA and MEMORY sections as a plain string.

    This text is injected into the user message — never the system message.
    """
    sections: list[str] = []

    # ---- Repository files & structure -----------------------------------
    if ctx.related_files:
        total_lines = sum(f.line_count for f in ctx.related_files)
        file_lines = [
            "REPOSITORY OVERVIEW & FILE INVENTORY:",
            "-------------------------------------",
            f"Total files: {len(ctx.related_files)}",
            f"Total lines: {total_lines}",
            "Files in repository:",
        ]
        for f in ctx.related_files[:100]:
            file_lines.append(f"- {f.path} ({f.language or 'unknown'}, {f.line_count} lines)")
        if len(ctx.related_files) > 100:
            file_lines.append(f"... and {len(ctx.related_files) - 100} more files")
        sections.append("\n".join(file_lines))

    # ---- Code chunks ----------------------------------------------------
    if ctx.code_chunks:
        chunk_texts = "\n\n".join(format_chunk(c) for c in ctx.code_chunks)
        sections.append(
            "REPOSITORY DATA:\n"
            "----------------\n"
            f"{chunk_texts}"
        )

    # ---- Memory ---------------------------------------------------------
    if ctx.memory_chunks:
        memory_texts = "\n".join(format_memory(m) for m in ctx.memory_chunks)
        sections.append(
            "MEMORY:\n"
            "-------\n"
            f"{memory_texts}"
        )

    return "\n\n".join(sections)


def render_history_section(ctx: AgentContext) -> str:
    """Render recent conversation history as formatted text turns."""
    if not ctx.recent_history:
        return ""
    return "\n".join(format_history_message(m) for m in ctx.recent_history)


def render_related_files_section(ctx: AgentContext) -> str:
    """Render repository file hierarchy summary if present."""
    if not ctx.related_files:
        return ""
    lines = ["RELATED FILES:", "--------------"]
    for f in ctx.related_files:
        lines.append(f"- {f.path} ({f.language or 'unknown'}, {f.line_count} lines)")
    return "\n".join(lines)


def render_intelligence_data(ctx: IntelligenceContext) -> str:
    """Render the complete intelligence context into structured prompt data sections with untrusted boundaries."""
    sections = [
        "<<<REPO_DATA_START>>>",
        "TARGET CODE UNDER ANALYSIS:\n"
        "---------------------------\n"
        f"File: {ctx.target.file_path} (lines {ctx.target.start_line}–{ctx.target.end_line})\n"
        f"Symbol: {ctx.target.symbol_name or 'N/A'}\n\n"
        f"{ctx.target.content}"
    ]

    if ctx.related_symbols:
        sym_lines = ["RELATED SYMBOLS & CALLERS:", "-------------------------"]
        for s in ctx.related_symbols:
            sym_lines.append(f"- {s.kind} {s.name} in {s.file_path}:{s.start_line}-{s.end_line}")
            if s.content:
                sym_lines.append(f"  {s.content.strip()[:200]}")
        sections.append("\n".join(sym_lines))

    if ctx.relevant_chunks:
        chunk_texts = "\n\n".join(format_chunk(c) for c in ctx.relevant_chunks)
        sections.append(f"RELEVANT CODE CONTEXT:\n----------------------\n{chunk_texts}")

    if ctx.repository_files:
        file_lines = ["REPOSITORY FILES OVERVIEW:", "-------------------------"]
        for f in ctx.repository_files[:50]:
            file_lines.append(f"- {f.path} ({f.language}, {f.line_count} lines)")
        sections.append("\n".join(file_lines))

    if ctx.project_rules:
        rule_lines = ["PROJECT RULES & CONVENTIONS:", "----------------------------"]
        for r in ctx.project_rules:
            rule_lines.append(f"- {r}")
        sections.append("\n".join(rule_lines))

    if ctx.missing_context:
        missing_lines = ["MISSING CONTEXT & NOTICES:", "-------------------------"]
        for m in ctx.missing_context:
            missing_lines.append(f"- [{m.file_path}] {m.reason}")
        sections.append("\n".join(missing_lines))

    sections.append("<<<REPO_DATA_END>>>")
    return "\n\n".join(sections)

