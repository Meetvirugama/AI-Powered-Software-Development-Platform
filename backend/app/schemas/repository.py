"""Public repository-management response models."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RepositoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    github_repo_id: str
    owner: str
    name: str
    full_name: str
    default_branch: str
    language: str | None
    sync_status: str
    last_synced_at: datetime | None


class RepositoryFileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    path: str
    language: str | None
    size_bytes: int
    line_count: int
    content_hash: str
    last_indexed_at: datetime | None


class CodeSymbolResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    file_id: str
    name: str
    kind: str
    start_line: int
    end_line: int
    signature: str | None
    parent_id: str | None


class PaginatedResponse(BaseModel):
    page: int
    page_size: int
    total: int
    items: list[RepositoryFileResponse] | list[CodeSymbolResponse]


class SyncJobResponse(BaseModel):
    job_id: str
    status: str = "QUEUED"
