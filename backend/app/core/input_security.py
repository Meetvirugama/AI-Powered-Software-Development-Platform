"""Input security helpers for repository file paths.
Owner: Sukun — W1, Day 5 (Input Security)

Every file path that comes from outside the process is untrusted:
  - paths sent by API clients (query/path parameters)
  - paths discovered while walking a cloned repository
  - paths cited by the LLM or stored in chunk/symbol metadata

Rule: a repository path must be *relative*, must not climb out of the
repository workspace, and must resolve (after following symlinks) to a
location inside that workspace.

The core functions are stdlib-only so the scanner can use them without
importing FastAPI. ``require_safe_repo_path`` converts a failure into the
public ``400 INVALID_REQUEST`` error envelope for API routes.
"""

from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath

MAX_PATH_LENGTH = 1024

# Windows drive letters (C:\, C:/) and UNC-style roots are absolute too.
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
# NUL and other ASCII control characters never belong in a repository path.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class UnsafePathError(ValueError):
    """Raised when a path could escape the repository workspace."""


def validate_repo_relative_path(path: str) -> str:
    """Validate an untrusted repository-relative path and return it normalised.

    Accepts ``src/app/main.py`` and ``./src//app/main.py`` (→ ``src/app/main.py``).
    Rejects absolute paths, ``..`` segments, backslashes, control characters,
    empty paths and overly long paths.

    Raises:
        UnsafePathError: if the path is unsafe.
    """
    if not isinstance(path, str) or not path.strip():
        raise UnsafePathError("Path must be a non-empty string.")
    if len(path) > MAX_PATH_LENGTH:
        raise UnsafePathError("Path is too long.")
    if _CONTROL_CHARS.search(path):
        raise UnsafePathError("Path contains control characters.")
    if "\\" in path:
        # Backslashes are separators on Windows workers: ..\..\etc\passwd
        raise UnsafePathError("Path must use forward slashes.")
    if path.startswith("/") or path.startswith("~") or _DRIVE_PREFIX.match(path):
        raise UnsafePathError("Path must be relative to the repository root.")

    parts = [part for part in PurePosixPath(path).parts if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise UnsafePathError("Path must not contain '..' segments.")
    if not parts:
        raise UnsafePathError("Path must point to a file inside the repository.")

    return "/".join(parts)


def resolve_within_root(root: str | os.PathLike[str], relative_path: str) -> Path:
    """Return the absolute path of ``relative_path`` inside ``root``.

    Validates the path syntactically, then resolves symlinks and checks that
    the real location is still under the real repository root. This catches a
    repository that contains a symlink such as ``docs/keys -> /root/.ssh``.

    Raises:
        UnsafePathError: if the path is unsafe or resolves outside ``root``.
    """
    clean = validate_repo_relative_path(relative_path)
    real_root = Path(root).resolve()
    candidate = (real_root / clean).resolve()
    if not is_within(real_root, candidate):
        raise UnsafePathError("Path resolves outside the repository workspace.")
    return candidate


def is_within(root: Path, candidate: Path) -> bool:
    """True when ``candidate`` is ``root`` or a descendant of it (both resolved)."""
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def require_safe_repo_path(path: str) -> str:
    """API boundary helper: validate ``path`` or raise ``400 INVALID_REQUEST``.

    Use this in any route that accepts a repository file path::

        @router.get("/{repository_id}/files/content")
        def file_content(repository_id: UUID, path: str = Query(...)):
            safe_path = require_safe_repo_path(path)
            ...
    """
    # Imported lazily so the scanner can use this module without FastAPI.
    from app.core.errors import APIError, ErrorCode

    try:
        return validate_repo_relative_path(path)
    except UnsafePathError as exc:
        # The message is generic on purpose: never echo the attacker's path.
        raise APIError(400, ErrorCode.INVALID_REQUEST, f"Invalid file path: {exc}") from exc
