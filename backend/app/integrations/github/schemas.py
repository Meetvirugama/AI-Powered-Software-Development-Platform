"""Pydantic schemas for GitHub source integration requests and responses.

These schemas define the contracts consumed by the four Week 2 analysis
features (Code Explanation, Bug Detection, Test Generation, AI Code Review)
and by the Repository Explorer UI.

Line ranges use **inclusive** boundaries: start_line=10, end_line=20 means
lines 10 through 20 are included.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class FileTargetType(str, enum.Enum):
    """Supported target types for source retrieval."""
    FILE = "file"
    DIRECTORY = "directory"


class DiffStatus(str, enum.Enum):
    """Status of a file within a diff."""
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    RENAMED = "renamed"
    UNCHANGED = "unchanged"


# ---------------------------------------------------------------------------
# Source Reference — shared across all four analysis features
# ---------------------------------------------------------------------------

class SourceReference(BaseModel):
    """Uniquely identifies a piece of source code within a repository.

    This is the shared contract described in Section 4.2 of the Week 2 plan.
    All line ranges are **inclusive** (start_line and end_line are both included).
    """
    model_config = ConfigDict(from_attributes=True)

    repository_id: str
    file_path: str
    start_line: Optional[int] = Field(
        default=None,
        ge=1,
        description="First included line (1-indexed, inclusive).",
    )
    end_line: Optional[int] = Field(
        default=None,
        ge=1,
        description="Last included line (1-indexed, inclusive).",
    )
    revision: Optional[str] = Field(
        default=None,
        description="Git SHA or branch name at the time of retrieval.",
    )
    commit_sha: Optional[str] = Field(
        default=None,
        description="Exact Git commit SHA for immutable revision identification.",
    )
    symbol_name: Optional[str] = Field(
        default=None,
        description="Optional symbol (function/class) name for targeted retrieval.",
    )

    @field_validator("end_line")
    @classmethod
    def end_after_start(cls, v: int | None, info) -> int | None:
        start = info.data.get("start_line")
        if v is not None and start is not None and v < start:
            raise ValueError("end_line must be >= start_line")
        return v


# ---------------------------------------------------------------------------
# File content retrieval
# ---------------------------------------------------------------------------

class FileContentRequest(BaseModel):
    """Request to retrieve file content from an authorized repository."""
    path: str = Field(
        ...,
        min_length=1,
        description="Relative path within the repository (e.g. 'src/main.py').",
    )
    ref: Optional[str] = Field(
        default=None,
        description="Git ref (branch, tag, SHA). Defaults to the repository's default branch.",
    )
    start_line: Optional[int] = Field(default=None, ge=1)
    end_line: Optional[int] = Field(default=None, ge=1)

    @field_validator("path")
    @classmethod
    def reject_path_traversal(cls, v: str) -> str:
        """Reject paths that attempt directory traversal."""
        normalized = v.replace("\\", "/")
        if ".." in normalized.split("/"):
            raise ValueError("Path traversal is not allowed.")
        if normalized.startswith("/"):
            raise ValueError("Absolute paths are not allowed.")
        return normalized

    @field_validator("end_line")
    @classmethod
    def end_line_after_start(cls, v: int | None, info) -> int | None:
        start = info.data.get("start_line")
        if v is not None and start is not None and v < start:
            raise ValueError("end_line must be >= start_line")
        return v


class FileContentResponse(BaseModel):
    """Response containing the content of a repository file."""
    model_config = ConfigDict(from_attributes=True)

    path: str
    content: str
    encoding: str = "utf-8"
    size_bytes: int
    line_count: int
    language: Optional[str] = None
    sha: Optional[str] = Field(
        default=None,
        description="Git blob SHA for cache validation.",
    )
    commit_sha: Optional[str] = Field(
        default=None,
        description="Exact Git commit SHA corresponding to the retrieved revision.",
    )
    ref: Optional[str] = Field(
        default=None,
        description="The resolved ref (branch/tag/SHA) used for retrieval.",
    )
    is_binary: bool = Field(
        default=False,
        description="True if the file contains binary content.",
    )
    from_cache: bool = Field(
        default=False,
        description="True if the content was served from the revision-safe cache.",
    )
    truncated: bool = Field(
        default=False,
        description="True when the content was truncated to stay within size limits.",
    )
    source_reference: Optional[SourceReference] = None


# ---------------------------------------------------------------------------
# Directory / file tree listing
# ---------------------------------------------------------------------------

class TreeEntry(BaseModel):
    """A single entry in a repository's file tree."""
    path: str
    type: str = Field(description="'blob' (file) or 'tree' (directory)")
    size: Optional[int] = None
    sha: Optional[str] = None


class FileTreeResponse(BaseModel):
    """Response containing the file tree of a repository."""
    ref: Optional[str] = None
    sha: Optional[str] = None
    entries: list[TreeEntry]
    truncated: bool = False


# ---------------------------------------------------------------------------
# Commit metadata
# ---------------------------------------------------------------------------

class CommitAuthor(BaseModel):
    """Author or committer identity."""
    name: str
    email: Optional[str] = None
    date: Optional[datetime] = None


class CommitFileChange(BaseModel):
    """A file changed in a commit."""
    filename: str
    status: DiffStatus
    additions: int = 0
    deletions: int = 0
    changes: int = 0
    patch: Optional[str] = None


class CommitDetail(BaseModel):
    """Metadata for a single commit."""
    sha: str
    message: str
    author: CommitAuthor
    committer: Optional[CommitAuthor] = None
    date: Optional[datetime] = None
    parents: list[str] = Field(default_factory=list)
    files: list[CommitFileChange] = Field(default_factory=list)
    stats: Optional[dict] = None


class CommitListRequest(BaseModel):
    """Request to list commits for a repository."""
    ref: Optional[str] = Field(default=None, description="Branch, tag or SHA.")
    path: Optional[str] = Field(default=None, description="Filter commits by file path.")
    per_page: int = Field(default=30, ge=1, le=100)
    page: int = Field(default=1, ge=1)


class CommitListResponse(BaseModel):
    """Paginated list of commits."""
    commits: list[CommitDetail]
    total: Optional[int] = None
    page: int
    per_page: int


# ---------------------------------------------------------------------------
# Pull-request diff retrieval
# ---------------------------------------------------------------------------

class PullRequestInfo(BaseModel):
    """Metadata about a pull request."""
    number: int
    title: str
    state: str
    draft: bool = False
    author: Optional[str] = None
    base_ref: Optional[str] = None
    head_ref: Optional[str] = None
    base_sha: Optional[str] = None
    head_sha: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    merged_at: Optional[datetime] = None
    body: Optional[str] = None


class PullRequestFile(BaseModel):
    """A file changed in a pull request."""
    filename: str
    status: DiffStatus
    additions: int = 0
    deletions: int = 0
    changes: int = 0
    patch: Optional[str] = None
    previous_filename: Optional[str] = None
    sha: Optional[str] = None
    contents_url: Optional[str] = None


class PullRequestDiffResponse(BaseModel):
    """Full diff information for a pull request."""
    pull_request: PullRequestInfo
    files: list[PullRequestFile]
    total_additions: int = 0
    total_deletions: int = 0
    total_changes: int = 0


class PullRequestListRequest(BaseModel):
    """Request to list pull requests for a repository."""
    state: str = Field(default="open", pattern="^(open|closed|all)$")
    per_page: int = Field(default=30, ge=1, le=100)
    page: int = Field(default=1, ge=1)


# ---------------------------------------------------------------------------
# Agent branch creation (Day 3)
# ---------------------------------------------------------------------------

class AgentBranchRequest(BaseModel):
    """Request schema for creating an agent execution branch."""
    task_id: str = Field(..., min_length=1, description="Task ID transitioning to EXECUTING")
    base_branch: Optional[str] = Field(default=None, description="Optional base branch (defaults to repo default)")


class AgentBranchResponse(BaseModel):
    """Response schema for agent branch creation/reuse."""
    branch_name: str
    base_branch: str
    base_sha: str
    status: str


# ---------------------------------------------------------------------------
# Day 4: Commit Staging
# ---------------------------------------------------------------------------

class CommitStagingRequest(BaseModel):
    """Request to stage workspace agent changes into a local Git commit."""
    workspace_path: str = Field(..., description="Absolute or relative path to agent workspace")
    commit_message: str = Field(..., min_length=1, description="Commit message")
    task_id: Optional[UUID | str] = Field(default=None, description="Task ID for branch validation")
    files: Optional[list[str]] = Field(default=None, description="Specific relative file paths to stage")
    author_name: str = Field(default="Agent", description="Git author name")
    author_email: str = Field(default="agent@ai-platform.local", description="Git author email")
    allow_empty: bool = Field(default=False, description="Allow empty commit if no changes exist")


class CommitStagingResponse(BaseModel):
    """Result of a local workspace commit."""
    commit_sha: str
    branch: str
    message: str
    files_changed: list[str]
    insertions: int = 0
    deletions: int = 0
    pushed: bool = False  # Always False in Week 2


# ---------------------------------------------------------------------------
# Day 5: PR Metadata Preparation
# ---------------------------------------------------------------------------

class PRMetadata(BaseModel):
    """PR Metadata collected for Week 3 GitHub PR opening (week2.md Day 5)."""
    task_id: UUID
    branch: str
    base_branch: str = "main"
    changed_files: list[str]
    commit_message: str
    test_summary: str
    verification_summary: str
    repository_id: Optional[UUID] = None
    pr_number: Optional[int] = None
    pr_url: Optional[str] = None
    status: str = "prepared"


# ---------------------------------------------------------------------------
# Week 3 Day 2: Diff Line Ranges & Branch Isolation for Blast Radius
# ---------------------------------------------------------------------------

class LineRange(BaseModel):
    """Inclusive 1-indexed line range affected by a diff hunk.

    Used by AST symbol mappers (Prit Day 2) to match diff hunks with symbols:
    code_symbols.start_line <= range.end_line AND code_symbols.end_line >= range.start_line.
    """
    start_line: int = Field(..., ge=1, description="First modified line in new file (1-indexed, inclusive)")
    end_line: int = Field(..., ge=1, description="Last modified line in new file (1-indexed, inclusive)")
    change_type: str = Field(default="modified", description="Type of change: added, modified, deleted")

    @field_validator("end_line")
    @classmethod
    def end_ge_start(cls, v: int, info) -> int:
        start = info.data.get("start_line")
        if start is not None and v < start:
            raise ValueError("end_line must be >= start_line")
        return v


class FileDiffRange(BaseModel):
    """File-level diff details with exact modified line ranges for AST symbol mapping."""
    file_path: str = Field(..., description="Target file path relative to repo root")
    status: DiffStatus = Field(default=DiffStatus.MODIFIED, description="Diff change status")
    diff_ranges: list[LineRange] = Field(default_factory=list, description="List of inclusive line ranges modified")
    additions: int = 0
    deletions: int = 0
    patch: Optional[str] = None


class TaskDiffRanges(BaseModel):
    """Collection of modified files and line ranges for an agent task, consumed by BlastRadiusEngine."""
    task_id: UUID
    repository_id: Optional[UUID] = None
    base_branch: str = "main"
    head_branch: str = ""
    files: list[FileDiffRange] = Field(default_factory=list)
    total_files_changed: int = 0
    total_additions: int = 0
    total_deletions: int = 0


class BranchIsolationCheck(BaseModel):
    """Validation result for agent branch isolation before task plan approval (Day 2 approval gate)."""
    task_id: UUID
    repository_id: UUID
    branch_name: str
    base_branch: str
    is_isolated: bool
    base_sha: Optional[str] = None
    conflicts_with_protected: bool = False
    error_message: Optional[str] = None



