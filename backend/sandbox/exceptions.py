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


# Week 3 Day 5 — Verification, Commit, Push and Draft PR Exceptions (Docs/week3.md §6 F36, F37)
class WorkspaceDiffError(WorkspaceError):
    """Raised when extracting or parsing a unified git diff from the workspace fails."""


class WorkspaceDiffValidationError(WorkspaceError):
    """Raised when workspace changes violate diff boundary, critical file, or allowed file rules."""


class WorkspaceSecretLeakDetectedError(WorkspaceDiffValidationError):
    """Raised when sensitive tokens, private keys, or credentials are found in diff or commit."""


class WorkspaceProtectedBranchError(WorkspaceError):
    """Raised when an operation attempts to commit to or push directly to a protected/default branch."""


class WorkspaceCommitError(WorkspaceError):
    """Raised when staging or committing validated changes on the task branch fails."""


class WorkspacePublicationUnauthorizedError(WorkspaceError):
    """Raised when git push or Draft PR publication is attempted without explicit human authorization."""


class WorkspacePushError(WorkspaceError):
    """Raised when git push to remote repository encounters a network, permission, or ref failure."""


class WorkspaceDraftPRError(WorkspaceError):
    """Raised when opening or formatting a GitHub Draft Pull Request fails."""

