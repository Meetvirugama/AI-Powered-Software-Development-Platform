"""Pydantic schemas for Project Memory management & automated writers (Issue #217)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.memory_entry import MemoryStatus, MemoryType


class MemoryEntryBase(BaseModel):
    type: MemoryType = Field(default=MemoryType.rule, description="Category of memory entry")
    content: str = Field(..., min_length=1, description="Content of the memory entry")
    source: str = Field(default="manual", description="Origin of the memory entry")
    status: MemoryStatus = Field(default=MemoryStatus.active, description="Lifecycle status")


class MemoryEntryCreate(MemoryEntryBase):
    pass


class MemoryEntryUpdate(BaseModel):
    content: Optional[str] = Field(default=None, min_length=1)
    status: Optional[MemoryStatus] = None
    type: Optional[MemoryType] = None
    source: Optional[str] = None


class MemoryEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    repository_id: UUID
    type: MemoryType = Field(..., serialization_alias="type")
    content: str
    source: str
    status: MemoryStatus
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_model(cls, entry: object) -> MemoryEntryResponse:
        return cls(
            id=getattr(entry, "id"),
            repository_id=getattr(entry, "repository_id"),
            type=getattr(entry, "type_"),
            content=getattr(entry, "content"),
            source=getattr(entry, "source"),
            status=getattr(entry, "status"),
            created_at=getattr(entry, "created_at"),
            updated_at=getattr(entry, "updated_at"),
        )


class PaginatedMemoryEntriesResponse(BaseModel):
    page: int
    page_size: int
    total: int
    items: list[MemoryEntryResponse]


class TaskCompletionMemoryRequest(BaseModel):
    """Payload to automatically record a task completion memory."""
    task_id: UUID
    title: str = Field(..., min_length=1)
    verification_summary: str = Field(..., min_length=1)
    repair_attempts_used: int = Field(default=0, ge=0)
    files_changed: Optional[list[str]] = None


class TaskFailureMemoryRequest(BaseModel):
    """Payload to automatically record a task failure memory."""
    task_id: UUID
    title: str = Field(..., min_length=1)
    failure_reason: str = Field(..., min_length=1)
    repair_attempts_used: int = Field(default=0, ge=0)


class ProjectRuleCreateRequest(BaseModel):
    """Payload to pin an architectural convention or project rule."""
    rule: str = Field(..., min_length=3)
    source: str = Field(default="user_pinned")
