"""Pydantic schemas for the internal Runner Service REST API."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field, field_validator

from app.core.config import PROJECT_ROOT


class RunnerCreateWorkspaceRequest(BaseModel):
    task_id: str = Field(..., min_length=1, description="Unique task identifier.")
    base_repo_path: str | None = Field(default=None, description="Optional path to seed repo files.")

    @field_validator("base_repo_path")
    @classmethod
    def validate_base_repo_path(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        if not cleaned:
            return None

        if ".." in cleaned:
            raise ValueError(f"Directory traversal detected in base_repo_path: '{v}'")

        resolved = Path(cleaned).resolve()
        allowed_roots = [
            PROJECT_ROOT.resolve(),
            (PROJECT_ROOT / ".workspaces").resolve(),
            (PROJECT_ROOT / "repos").resolve(),
            Path("/sandbox/workspaces").resolve(),
            Path("/tmp/workspaces").resolve(),
        ]

        is_allowed = any(
            resolved == root or resolved.is_relative_to(root)
            for root in allowed_roots
        )
        if not is_allowed:
            raise ValueError(
                f"base_repo_path '{v}' resolves outside allowed runner repository directories."
            )

        if resolved.is_symlink():
            target = resolved.readlink()
            target_resolved = (resolved.parent / target).resolve()
            if not any(
                target_resolved == root or target_resolved.is_relative_to(root)
                for root in allowed_roots
            ):
                raise ValueError(
                    f"base_repo_path symlink target resolves outside allowed repository directories."
                )

        return str(resolved)


class RunnerCreateWorkspaceResponse(BaseModel):
    success: bool
    task_id: str
    workspace_path: str
    backend: str = "container"


class RunnerExecuteRequest(BaseModel):
    command: str = Field(..., min_length=1, description="Bare executable command name.")
    arguments: list[str] = Field(default_factory=list, description="Command arguments.")
    cwd: str | None = Field(default=None, description="Relative or absolute sub-path in workspace.")
    timeout_seconds: int = Field(default=30, ge=1, le=300, description="Execution timeout budget.")
    custom_env: dict[str, str] = Field(default_factory=dict, description="Safe environment overrides.")
    network_enabled: bool = Field(default=False, description="Whether network egress is permitted (Phase A vs Phase B).")


class RunnerFileReadResponse(BaseModel):
    success: bool
    path: str
    content: str


class RunnerFileWriteRequest(BaseModel):
    path: str = Field(..., min_length=1, description="Workspace-relative file path.")
    content: str = Field(default="", description="File content to write.")


class RunnerFileWriteResponse(BaseModel):
    success: bool
    path: str
    bytes_written: int


class RunnerDiffResponse(BaseModel):
    success: bool
    task_id: str
    diff: str


class RunnerStatusResponse(BaseModel):
    success: bool
    task_id: str
    backend: str
    status: str
    gvisor_verified: bool = False
    details: dict[str, Any] = Field(default_factory=dict)
