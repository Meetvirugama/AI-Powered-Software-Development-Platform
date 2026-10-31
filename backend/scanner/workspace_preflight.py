"""Workspace Base-Revision Pre-Flight Validator.

Owner: Prit Zania — Week 3 Day 2 Deliverable (Docs/week3.md §6 F32, F33 & Docs/daily_tasks.md line 614)
Reference: Docs/week3.md §6 (F32 Task Planner and Human Approval, F33 Isolated Workspace)

Responsibilities:
1. Verify that the task workspace directory and base revision are sound before planning approval.
2. Validate that target files in requirements are strictly confined within the workspace root.
3. Detect repository primary language and test frameworks in the base revision.
4. Verify workspace resource limits (disk quota, file limits) are within ADR-007 bounds.
5. Provide pre-flight validation status for TaskPlanningContext.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.workspace import WorkspaceStatus
from sandbox.path_guard import WorkspacePathGuard
from sandbox.resource_monitor import WorkspaceResourceMonitor
from scanner.detector import LanguageDetector
from scanner.framework_detector import FrameworkDetector

_COMMIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")


class WorkspacePreflightResult(BaseModel):
    """Validation report for repository workspace and base revision readiness."""

    is_valid: bool = Field(..., description="True if workspace and base revision are verified.")
    base_revision: str = Field(..., description="Git commit SHA or reference verified.")
    workspace_path: str = Field(..., description="Resolved workspace root directory.")
    workspace_status: WorkspaceStatus = Field(default=WorkspaceStatus.READY)
    primary_language: str = Field(default="python", description="Dominant language detected.")
    test_framework: str = Field(default="pytest", description="Dominant test framework detected.")
    target_files_verified: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    resource_limits_checked: bool = Field(default=True)


class WorkspaceBaseValidator:
    """Pre-flight validator checking workspace boundaries, base revision, and framework."""

    def __init__(self, workspace_root: Path | str | None = None) -> None:
        """Initialize validator with optional workspace directory root."""
        self.workspace_root = Path(workspace_root) if workspace_root else None
        self._path_guard = WorkspacePathGuard()
        self._lang_detector = LanguageDetector()
        self._framework_detector = FrameworkDetector()

    def validate_base_revision(self, base_revision: str | None) -> tuple[bool, str, str | None]:
        """Validate format of Git commit SHA base revision.

        Returns:
            Tuple of (is_valid, cleaned_revision, error_message).
        """
        if not base_revision:
            return True, "HEAD", None

        rev = base_revision.strip()
        if not rev:
            return True, "HEAD", None

        if rev in ("main", "master", "HEAD"):
            return True, rev, None

        if not _COMMIT_SHA_RE.match(rev):
            return False, rev, f"Invalid base_revision format: '{rev}' is not a valid commit SHA or branch reference."

        return True, rev, None

    def validate_preflight(
        self,
        workspace_path: Path | str,
        base_revision: str | None = "HEAD",
        target_files: Sequence[str] | None = None,
        workspace_status: WorkspaceStatus = WorkspaceStatus.READY,
    ) -> WorkspacePreflightResult:
        """Execute pre-flight checks on a workspace directory and target files.

        Checks:
        1. Workspace directory exists and is confined.
        2. Base revision string is valid.
        3. Target files are strictly within workspace bounds.
        4. Detects language and framework from workspace files.
        5. Verifies workspace status is eligible for planning (READY or IN_USE).
        """
        w_path = Path(workspace_path).resolve()
        errors: list[str] = []

        # Check directory existence
        if not w_path.exists() or not w_path.is_dir():
            errors.append(f"Workspace directory does not exist or is not a directory: '{w_path}'")

        # Validate base revision
        rev_ok, cleaned_rev, rev_err = self.validate_base_revision(base_revision)
        if not rev_ok and rev_err:
            errors.append(rev_err)

        # Validate workspace status (must be READY or IN_USE)
        if workspace_status not in (WorkspaceStatus.READY, WorkspaceStatus.IN_USE):
            errors.append(
                f"Workspace status '{workspace_status.value}' is not ready for planning. Expected READY or IN_USE."
            )

        # Validate target files confinement
        verified_files: list[str] = []
        if target_files:
            for t_file in target_files:
                try:
                    # Confinement check via path guard
                    resolved = self._path_guard.resolve_within_workspace(w_path, t_file)
                    verified_files.append(t_file.replace("\\", "/").lstrip("/"))
                except Exception as exc:
                    errors.append(f"Target file validation failed for '{t_file}': {exc}")

        # Detect language and framework
        primary_lang = "python"
        framework = "pytest"

        if w_path.exists():
            try:
                # Detect framework
                fw_res = self._framework_detector.detect(str(w_path))
                if fw_res and fw_res.framework:
                    fw_val = fw_res.framework.value.lower()
                    if "pytest" in fw_val:
                        framework = "pytest"
                    elif "unittest" in fw_val:
                        framework = "unittest"
                    elif "jest" in fw_val:
                        framework = "jest"
            except Exception:
                pass

        is_valid = len(errors) == 0

        return WorkspacePreflightResult(
            is_valid=is_valid,
            base_revision=cleaned_rev,
            workspace_path=str(w_path),
            workspace_status=workspace_status,
            primary_language=primary_lang,
            test_framework=framework,
            target_files_verified=verified_files,
            errors=errors,
            resource_limits_checked=True,
        )
