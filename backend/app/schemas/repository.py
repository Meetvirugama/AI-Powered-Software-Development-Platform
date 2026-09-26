"""Public repository-management response models."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class RepositorySearchRequest(BaseModel):
    """A repository-scoped hybrid-search request."""

    query: str = Field(min_length=1, max_length=1_000)
    top_k: int = Field(default=8, ge=1, le=30)

    @field_validator("query")
    @classmethod
    def query_must_contain_non_whitespace(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query must contain non-whitespace characters")
        return value


class RepositorySearchResult(BaseModel):
    """A code chunk returned by the RAG retrieval pipeline."""

    id: str
    file_path: str
    start_line: int
    end_line: int
    content: str
    score: float


class RepositorySearchResponse(BaseModel):
    """Hybrid-search results in descending relevance order."""

    query: str
    results: list[RepositorySearchResult]


class ChatHistoryMessage(BaseModel):
    """A prior user or assistant turn supplied with a repository chat request."""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20_000)

    @field_validator("content")
    @classmethod
    def content_must_contain_non_whitespace(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("content must contain non-whitespace characters")
        return value


class RepositoryChatRequest(BaseModel):
    """Question and optional conversation context for repository-aware chat."""

    question: str = Field(min_length=1, max_length=4_000)
    history: list[ChatHistoryMessage] = Field(default_factory=list, max_length=50)

    @field_validator("question")
    @classmethod
    def question_must_contain_non_whitespace(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must contain non-whitespace characters")
        return value
