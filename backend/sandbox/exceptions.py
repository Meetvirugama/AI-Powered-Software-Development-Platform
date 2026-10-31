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


class WorkspaceAuthorizationError(WorkspaceError):
    """Raised when an unapproved task attempts to enter or execute in a workspace."""


class WorkspaceStaleApprovalError(WorkspaceError):
    """Raised when the base revision or plan has changed since approval."""


class WorkspaceCommandError(WorkspaceError):
    """Raised when sandboxed command execution fails or violates policy."""


class WorkspaceCommandTimeoutError(WorkspaceCommandError):
    """Raised when command execution exceeds the allotted timeout budget."""


class WorkspacePolicyViolationError(WorkspaceError):
    """Raised when an agent tool request violates security policy."""


class WorkspaceTestExecutionError(WorkspaceError):
    """Raised when test execution fails or encounters infrastructure errors."""


class WorkspaceUnsupportedFrameworkError(WorkspaceTestExecutionError):
    """Raised when an unsupported or missing test framework is requested."""


class WorkspaceRepairBudgetExhaustedError(WorkspaceError):
    """Raised when the maximum 3-attempt repair budget is exhausted per ADR-010."""


class WorkspaceDuplicateRepairPatchError(WorkspaceError):
    """Raised when an identical failed repair patch is repeatedly applied."""

