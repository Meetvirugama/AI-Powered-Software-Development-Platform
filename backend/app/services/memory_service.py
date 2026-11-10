"""Project Memory Service providing episodic memory management & automated writers (Issue #217).

Implements:
1. Automated memory recording for task completions (Reflexion-style episodic summaries).
2. Automated memory recording for task failures (negative examples & error diagnoses).
3. Architectural convention and project rule persistence.
4. Episodic retrieval, lexical search, and pgvector semantic retrieval.
5. Model Context Protocol (MCP) memory resource exposure (e.g., memory://repo/{id}/rules).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.secret_redaction import redact
from app.models.memory_entry import MemoryEntry, MemoryStatus, MemoryType
from app.repositories.memory_repository import MemoryRepository
from app.schemas.memory import MCPMemoryResource

logger = logging.getLogger(__name__)


class ProjectMemoryService:
    """Service layer managing episodic project memory, automated writers, and retrieval."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = MemoryRepository(db)

    # -----------------------------------------------------------------------
    # Automated Writers (Reflexion-Style Episodic Memory)
    # -----------------------------------------------------------------------

    def record_task_completion_memory(
        self,
        repository_id: uuid.UUID,
        task_id: uuid.UUID | str,
        title: str,
        verification_summary: str,
        repair_attempts_used: int = 0,
        files_changed: Optional[list[str]] = None,
        embedding: Optional[list[float]] = None,
    ) -> MemoryEntry:
        """Automatically write a task_summary entry upon successful task verification (Issue #217)."""
        clean_title = redact(title.strip())
        clean_summary = redact(verification_summary.strip())
        files_info = f" Modified files: {', '.join(files_changed)}." if files_changed else ""

        content = (
            f"Task '{clean_title}' completed successfully. "
            f"Verification: {clean_summary}. "
            f"Repair attempts used: {repair_attempts_used}.{files_info}"
        )
        source = f"task:{task_id}"

        logger.info(
            "recording_task_completion_memory",
            extra={"repository_id": str(repository_id), "task_id": str(task_id)},
        )

        return self.repo.create_entry(
            repository_id=repository_id,
            type_=MemoryType.task_summary,
            content=content,
            source=source,
            status=MemoryStatus.active,
            embedding=embedding,
        )

    def record_task_failure_memory(
        self,
        repository_id: uuid.UUID,
        task_id: uuid.UUID | str,
        title: str,
        failure_reason: str,
        repair_attempts_used: int = 0,
        embedding: Optional[list[float]] = None,
    ) -> MemoryEntry:
        """Automatically write a failure entry upon task failure or verification rejection (Issue #217)."""
        clean_title = redact(title.strip())
        clean_reason = redact(failure_reason.strip())

        content = (
            f"Task '{clean_title}' failed. "
            f"Failure diagnosis: {clean_reason}. "
            f"Repair attempts exhausted: {repair_attempts_used}."
        )
        source = f"task:{task_id}"

        logger.info(
            "recording_task_failure_memory",
            extra={"repository_id": str(repository_id), "task_id": str(task_id)},
        )

        return self.repo.create_entry(
            repository_id=repository_id,
            type_=MemoryType.failure,
            content=content,
            source=source,
            status=MemoryStatus.active,
            embedding=embedding,
        )

    def record_architectural_rule(
        self,
        repository_id: uuid.UUID,
        rule_content: str,
        source: str = "user_pinned",
        embedding: Optional[list[float]] = None,
    ) -> MemoryEntry:
        """Record or pin an architectural convention or code standard into repository memory."""
        clean_rule = redact(rule_content.strip())
        clean_source = redact(source.strip()) if source else "user_pinned"

        # Idempotency check: if exact active rule already exists, return it to prevent duplication
        existing_rules, _ = self.repo.search_entries(
            repository_id=repository_id,
            query=clean_rule,
            type_=MemoryType.rule,
            status=MemoryStatus.active,
            limit=10,
        )
        for r in existing_rules:
            if r.content.strip().lower() == clean_rule.lower():
                return r

        return self.repo.create_entry(
            repository_id=repository_id,
            type_=MemoryType.rule,
            content=clean_rule,
            source=clean_source,
            status=MemoryStatus.active,
            embedding=embedding,
        )

    # -----------------------------------------------------------------------
    # Memory Management & CRUD
    # -----------------------------------------------------------------------

    def create_memory(
        self,
        repository_id: uuid.UUID,
        type_: MemoryType | str,
        content: str,
        source: str = "manual",
        status: MemoryStatus | str = MemoryStatus.active,
        embedding: Optional[list[float]] = None,
    ) -> MemoryEntry:
        """Create a new memory entry with input sanitization and optional vector embedding."""
        return self.repo.create_entry(
            repository_id=repository_id,
            type_=type_,
            content=redact(content),
            source=redact(source) if source else "manual",
            status=status,
            embedding=embedding,
        )

    def get_memory(
        self,
        entry_id: uuid.UUID,
        repository_id: uuid.UUID,
    ) -> Optional[MemoryEntry]:
        """Retrieve a specific memory entry enforcing repository boundary checks."""
        return self.repo.get_by_id(entry_id, repository_id=repository_id)

    def update_memory(
        self,
        entry_id: uuid.UUID,
        repository_id: uuid.UUID,
        *,
        content: Optional[str] = None,
        status: Optional[MemoryStatus | str] = None,
        type_: Optional[MemoryType | str] = None,
        source: Optional[str] = None,
        embedding: Optional[list[float]] = None,
    ) -> Optional[MemoryEntry]:
        """Update a memory entry scoped to the repository."""
        return self.repo.update_entry(
            entry_id=entry_id,
            repository_id=repository_id,
            content=redact(content) if content is not None else None,
            status=status,
            type_=type_,
            source=redact(source) if source is not None else None,
            embedding=embedding,
        )

    def delete_memory(
        self,
        entry_id: uuid.UUID,
        repository_id: uuid.UUID,
    ) -> bool:
        """Delete a memory entry scoped to the repository."""
        return self.repo.delete_entry(entry_id, repository_id=repository_id)

    def search_project_memory(
        self,
        repository_id: uuid.UUID,
        *,
        query: Optional[str] = None,
        type_: Optional[MemoryType | str] = None,
        status: Optional[MemoryStatus | str] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> Tuple[List[MemoryEntry], int]:
        """Search repository memories with filtering and pagination."""
        return self.repo.search_entries(
            repository_id=repository_id,
            query=query,
            type_=type_,
            status=status,
            offset=offset,
            limit=limit,
        )

    def semantic_search_project_memory(
        self,
        repository_id: uuid.UUID,
        query_vector: List[float],
        *,
        type_: Optional[MemoryType | str] = None,
        status: Optional[MemoryStatus | str] = None,
        limit: int = 20,
        min_similarity: float = 0.0,
    ) -> List[Tuple[MemoryEntry, float]]:
        """Perform semantic cosine retrieval across repository memory embeddings."""
        return self.repo.semantic_search_entries(
            repository_id=repository_id,
            query_vector=query_vector,
            type_=type_,
            status=status,
            limit=limit,
            min_similarity=min_similarity,
        )

    # -----------------------------------------------------------------------
    # Model Context Protocol (MCP) Resource Exposure (F36 / Issue #217)
    # -----------------------------------------------------------------------

    def list_mcp_resources(self, repository_id: uuid.UUID) -> list[MCPMemoryResource]:
        """List all exposed MCP memory resources for this repository."""
        categories = [
            ("rules", "Project Architectural Rules", MemoryType.rule, "Pinned architectural rules and code conventions"),
            ("decisions", "Architecture & Technical Decisions", MemoryType.decision, "Architectural Decision Records (ADRs) and design choices"),
            ("task-summaries", "Episodic Task Summaries", MemoryType.task_summary, "Past completed task execution learnings and verification summaries"),
            ("failures", "Episodic Failure Diagnoses", MemoryType.failure, "Past failed tasks, root causes, and repair records"),
            ("all", "All Project Memories", None, "Complete active project memory ledger"),
        ]

        resources: list[MCPMemoryResource] = []
        for slug, title, m_type, desc in categories:
            res = self.resolve_mcp_resource(repository_id, slug)
            resources.append(res)
        return resources

    def resolve_mcp_resource(
        self,
        repository_id: uuid.UUID,
        resource_identifier: str,
    ) -> MCPMemoryResource:
        """Resolve and format an MCP memory resource by slug or full URI."""
        clean_slug = resource_identifier.strip().lower()
        if clean_slug.startswith(f"memory://repo/{repository_id}/"):
            clean_slug = clean_slug[len(f"memory://repo/{repository_id}/"):]
        elif "://" in clean_slug:
            clean_slug = clean_slug.split("/")[-1]

        slug_type_map: dict[str, tuple[str, MemoryType | None, str]] = {
            "rules": ("Project Architectural Rules", MemoryType.rule, "Active conventions and rules"),
            "decisions": ("Project Decisions", MemoryType.decision, "Architectural and technical decisions"),
            "task-summaries": ("Task Summaries", MemoryType.task_summary, "Completed task summaries"),
            "task_summaries": ("Task Summaries", MemoryType.task_summary, "Completed task summaries"),
            "failures": ("Task Failures", MemoryType.failure, "Recorded failures and negative feedback"),
            "all": ("All Project Memories", None, "Complete active repository memory ledger"),
        }

        meta = slug_type_map.get(clean_slug, ("Custom Memory Resource", None, "Project memory entries"))
        title, m_type, desc = meta
        uri = f"memory://repo/{repository_id}/{clean_slug}"

        entries, total = self.repo.search_entries(
            repository_id=repository_id,
            type_=m_type,
            status=MemoryStatus.active,
            limit=200,
        )

        lines: list[str] = [
            f"# {title}",
            f"> Repository: `{repository_id}` | Active Entries: {total}",
            f"> Description: {desc}",
            "",
        ]

        if not entries:
            lines.append("_No active memory entries recorded for this resource._")
        else:
            for idx, e in enumerate(entries, start=1):
                type_name = e.type_.value if hasattr(e.type_, "value") else str(e.type_)
                date_str = e.created_at.strftime("%Y-%m-%d %H:%M:%S") if e.created_at else ""
                lines.append(f"### {idx}. [{type_name.upper()}] {date_str} (Source: `{e.source}`)")
                lines.append(f"{e.content}")
                lines.append("")

        return MCPMemoryResource(
            uri=uri,
            name=title,
            mimeType="text/markdown",
            description=desc,
            text="\n".join(lines),
            entries_count=len(entries),
            metadata={
                "repository_id": str(repository_id),
                "resource_slug": clean_slug,
                "type_filter": m_type.value if m_type else "all",
            },
        )

