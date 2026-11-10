"""Project Memory Service providing episodic memory management & automated writers (Issue #217).

Implements:
1. Automated memory recording for task completions (Reflexion-style episodic summaries).
2. Automated memory recording for task failures (negative examples & error diagnoses).
3. Architectural convention and project rule persistence.
4. Episodic retrieval and lexical search across repository memories.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.secret_redaction import redact
from app.models.memory_entry import MemoryEntry, MemoryStatus, MemoryType
from app.repositories.memory_repository import MemoryRepository

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
        )

    def record_task_failure_memory(
        self,
        repository_id: uuid.UUID,
        task_id: uuid.UUID | str,
        title: str,
        failure_reason: str,
        repair_attempts_used: int = 0,
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
        )

    def record_architectural_rule(
        self,
        repository_id: uuid.UUID,
        rule_content: str,
        source: str = "user_pinned",
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
    ) -> MemoryEntry:
        """Create a new memory entry with input sanitization."""
        return self.repo.create_entry(
            repository_id=repository_id,
            type_=type_,
            content=redact(content),
            source=redact(source) if source else "manual",
            status=status,
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
    ) -> Optional[MemoryEntry]:
        """Update a memory entry scoped to the repository."""
        return self.repo.update_entry(
            entry_id=entry_id,
            repository_id=repository_id,
            content=redact(content) if content is not None else None,
            status=status,
            type_=type_,
            source=redact(source) if source is not None else None,
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
