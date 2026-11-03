r"""Path Traversal Guard & Filesystem Boundary Confinement.

Owner: Prit Zania — Week 3 Day 1 Deliverable (Docs/week3.md §6 F33, §8 Day 1)
Reference: Docs/security/week2_security_checklist.md, ADR-007

Provides robust defense-in-depth against:
- Directory climbing (../)
- Windows backslash and UNC share traversals (..\ or \\server\share)
- Absolute POSIX and Windows drive paths (/etc/passwd, C:\Windows)
- Null bytes (\x00) and ASCII control characters
- Symbolic link traps resolving outside the workspace sandbox
- Access or tampering with .git/ internals, .env secrets, or SSH keys
- Host platform repo mutation (_REPO_ROOT, backend, frontend)
"""

from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath

from app.core.input_security import UnsafePathError, is_within, validate_repo_relative_path
from sandbox.constants import (
    DANGEROUS_PATH_SEGMENTS,
    PROTECTED_SYSTEM_PREFIXES,
)
from sandbox.exceptions import WorkspacePathEscapeError

_REPO_ROOT = Path(__file__).resolve().parents[2]
_UNC_PATH_RE = re.compile(r"^\\\\[^\\]+\\[^\\]+")
_DRIVE_LETTER_RE = re.compile(r"^[A-Za-z]:")


class WorkspacePathGuard:
    """Security guard ensuring all workspace operations remain strictly confined."""

    @staticmethod
    def validate_workspace_root(workspace_path: str | Path) -> Path:
        """Validate that a proposed workspace directory is safe and isolated.

        Ensures:
        - Path is not empty and has no null bytes.
        - Path does not climb out via '..'.
        - Path does not point to protected OS directories (/etc, /bin, C:\\Windows).
        - Path does not point directly to the host application repository.
        """
        raw_str = str(workspace_path or "").strip()
        if not raw_str or "\x00" in raw_str:
            raise WorkspacePathEscapeError("Workspace path must not be empty or contain null bytes.")

        if _UNC_PATH_RE.match(raw_str):
            raise WorkspacePathEscapeError(f"UNC network paths are forbidden: '{raw_str}'")

        # Normalize slashes for traversal check
        normalized = raw_str.replace("\\", "/")
        if any(part == ".." for part in normalized.split("/")):
            raise WorkspacePathEscapeError("Path traversal ('..') is not permitted in workspace root.")

        resolved = Path(raw_str).resolve()
        resolved_str = resolved.as_posix()

        # Reject system prefixes
        for prefix in PROTECTED_SYSTEM_PREFIXES:
            clean_prefix = Path(prefix).resolve().as_posix() if Path(prefix).exists() else prefix.replace("\\", "/")
            if resolved_str == clean_prefix or resolved_str.startswith(clean_prefix + "/"):
                raise WorkspacePathEscapeError(
                    f"Workspace root points to a protected system directory: '{raw_str}'"
                )

        # Reject direct host application repository roots
        if resolved == _REPO_ROOT or resolved == (_REPO_ROOT / "backend") or resolved == (_REPO_ROOT / "frontend"):
            raise WorkspacePathEscapeError(
                "Workspace root cannot point directly to the host platform repository."
            )

        return resolved

    @classmethod
    def resolve_within_workspace(
        cls,
        workspace_root: str | Path,
        relative_path: str,
        allow_git_dir: bool = False,
    ) -> Path:
        """Resolve a relative path strictly within the workspace sandbox root.

        Args:
            workspace_root: Base path of the task's isolated workspace directory.
            relative_path: Repository-relative target file path.
            allow_git_dir: If False, access to .git metadata or internals is strictly forbidden.

        Returns:
            Resolved absolute Path guaranteed to lie within workspace_root.

        Raises:
            WorkspacePathEscapeError: If the path is malformed, attempts escape,
                                     or targets protected files.
        """
        root_path = cls.validate_workspace_root(workspace_root)

        # Preliminary syntactic check for null bytes, UNC shares, and drives
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise WorkspacePathEscapeError("File path must be a non-empty string.")

        if "\x00" in relative_path:
            raise WorkspacePathEscapeError("File path contains illegal null bytes.")

        if _UNC_PATH_RE.match(relative_path):
            raise WorkspacePathEscapeError(f"UNC network paths are forbidden: '{relative_path}'")

        # Enforce repo-relative syntax via shared input security
        try:
            clean_rel = validate_repo_relative_path(relative_path)
        except UnsafePathError as exc:
            raise WorkspacePathEscapeError(f"Invalid path syntax '{relative_path}': {exc}") from exc

        # Check for forbidden files (e.g. .git, .env, SSH private keys)
        if not allow_git_dir:
            parts = PurePosixPath(clean_rel).parts
            if any(p.lower() == ".git" or p.lower().startswith(".git") for p in parts):
                raise WorkspacePathEscapeError(
                    f"Direct access to .git metadata or hooks is forbidden: '{relative_path}'"
                )
            if any(p.lower() == ".env" or p.lower().startswith(".env.") for p in parts):
                raise WorkspacePathEscapeError(
                    f"Direct access to environment secrets is forbidden: '{relative_path}'"
                )
            if DANGEROUS_PATH_SEGMENTS.search(clean_rel):
                raise WorkspacePathEscapeError(
                    f"Path targets protected security credentials: '{relative_path}'"
                )

        # Resolve candidate path
        candidate = (root_path / clean_rel).resolve()

        # Enforce boundary containment
        if not is_within(root_path, candidate):
            raise WorkspacePathEscapeError(
                f"Path '{relative_path}' resolves outside the workspace sandbox '{root_path}'."
            )

        return candidate
