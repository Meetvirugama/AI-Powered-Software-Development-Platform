"""Exceptions for Sandbox and Isolated Workspace Management.

Owner: Prit Zania — Week 3 Day 1 Deliverable (Docs/week3.md §6 F33, §8 Day 1)
"""

from __future__ import annotations


class WorkspaceError(Exception):
    """Base exception for workspace and sandbox operations."""


class WorkspaceCreationError(WorkspaceError):
    """Raised when an isolated workspace cannot be provisioned or initialized."""


class WorkspacePathEscapeError(WorkspaceError):
    """Raised when a path attempts traversal or points outside the isolated workspace."""


class WorkspaceFileError(WorkspaceError):
    """Raised when a file operation (read/write/patch/delete) fails within the workspace."""


class WorkspaceLimitExceededError(WorkspaceError):
    """Raised when a workspace quota or resource budget is exceeded."""


class WorkspaceCleanupError(WorkspaceError):
    """Raised when decommissioning or cleaning a workspace fails."""


class WorkspaceStateError(WorkspaceError):
    """Raised when an illegal lifecycle state transition is attempted."""
