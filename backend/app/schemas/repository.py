"""Public repository-management response models."""

from datetime import datetime
from uuid import UUID
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
    description: str | None = None
    framework: str | None = None
    file_count: int | None = None
    symbol_count: int | None = None
    chunk_count: int | None = None
    last_sync_error: str | None = None
    last_indexed_commit_sha: str | None = None


class RepositoryDependencyResponse(BaseModel):
    name: str
    version: str
    ecosystem: str


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
    importance_score: float | None = None


class RepositoryFileContentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    path: str
    language: str | None
    size_bytes: int
    line_count: int
    content: str
    symbols: list[CodeSymbolResponse] = Field(default_factory=list)


class PaginatedResponse(BaseModel):
    page: int
    page_size: int
    total: int
    items: list[RepositoryFileResponse] | list[CodeSymbolResponse]


class SyncJobResponse(BaseModel):
    job_id: str
    status: str = "QUEUED"


class SyncJobDetailResponse(BaseModel):
    """Progress and outcome of one repository synchronization job."""

    job_id: str
    repository_id: str
    status: str
    stage: str | None = None
    error_message: str | None = None
    commit_sha: str | None = None
    stats: dict | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_seconds: float | None = None


class BranchResponse(BaseModel):
    name: str
    sha: str
    protected: bool = False
    is_default: bool = False


class CommitResponse(BaseModel):
    sha: str
    message: str
    author_name: str | None = None
    author_login: str | None = None
    authored_at: str | None = None
    html_url: str | None = None


class PullRequestSummaryResponse(BaseModel):
    number: int | None = None
    title: str
    state: str
    draft: bool = False
    merged: bool = False
    author_login: str | None = None
    head_branch: str | None = None
    base_branch: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    html_url: str | None = None


class LanguageMetric(BaseModel):
    language: str
    files: int
    lines: int
    bytes: int


class RepositoryMetricsResponse(BaseModel):
    repository_id: str
    file_count: int
    total_lines: int
    total_bytes: int
    symbol_count: int
    chunk_count: int
    edge_count: int
    languages: list[LanguageMetric]
    symbols_by_kind: dict[str, int]
    top_symbols: list[CodeSymbolResponse]
    last_synced_at: datetime | None = None
    last_indexed_commit_sha: str | None = None


class RepositorySearchRequest(BaseModel):
    """A repository-scoped hybrid-search request (supports both query/top_k and q/limit aliases)."""

    model_config = ConfigDict(populate_by_name=True)

    query: str = Field(min_length=1, max_length=1_000, validation_alias="q")
    top_k: int = Field(default=8, ge=1, le=30, validation_alias="limit")

    def __init__(self, **data):
        if "query" in data and "q" not in data:
            data["q"] = data["query"]
        if "top_k" in data and "limit" not in data:
            data["limit"] = data["top_k"]
        super().__init__(**data)

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
    mode: Literal["normal", "agentic"] = Field(
        default="normal",
        description="Chat execution mode: 'normal' for fast standard RAG, 'agentic' for multi-step bounded investigation.",
    )
    conversation_id: UUID | None = Field(
        default=None,
        description=(
            "Server-side conversation to continue. When set, history is loaded from the server "
            "(the `history` field is ignored) and this exchange is saved to the conversation."
        ),
    )

    @field_validator("question")
    @classmethod
    def question_must_contain_non_whitespace(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must contain non-whitespace characters")
        return value


class ChatConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=500)


class ChatConversationRename(BaseModel):
    title: str = Field(min_length=1, max_length=500)


class ChatConversationSummary(BaseModel):
    id: str
    repository_id: str
    title: str
    message_count: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ChatMessageOut(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    sources: list[dict] = Field(default_factory=list)
    confidence: str | None = None
    status: str | None = None
    mode: str | None = None
    agent_metadata: dict | None = None
    created_at: datetime | None = None


class ChatConversationDetail(ChatConversationSummary):
    messages: list[ChatMessageOut] = Field(default_factory=list)


class ChatConversationList(BaseModel):
    items: list[ChatConversationSummary]
    total: int


# ---------------------------------------------------------------------------
# GitHub App discovery / connect schemas
# ---------------------------------------------------------------------------

class AvailableRepository(BaseModel):
    """A repository accessible via the user's GitHub App installation."""

    github_repo_id: str
    owner: str
    name: str
    full_name: str
    default_branch: str
    language: str | None
    is_connected: bool = False


class PaginatedAvailableRepositoryResponse(BaseModel):
    """Paginated list of repositories discoverable via GitHub App."""

    items: list[AvailableRepository]
    total: int
    page: int
    page_size: int
    total_pages: int


class ConnectRepositoryResponse(BaseModel):
    """Response after successfully connecting a repository."""

    repository_id: str
    job_id: str


class RepositoryAutomationSettingsResponse(BaseModel):
    github_repo_id: str
    auto_sync_enabled: bool = True
    pr_review_enabled: bool = False
    pr_review_drafts: bool = False
    last_indexed_commit_sha: str | None = None


class UpdateRepositoryAutomationSettingsRequest(BaseModel):
    auto_sync_enabled: bool | None = None
    pr_review_enabled: bool | None = None
    pr_review_drafts: bool | None = None
