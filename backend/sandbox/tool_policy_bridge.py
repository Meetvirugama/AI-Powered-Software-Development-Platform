"""Tool Policy Bridge & Agent Tool Registration.

Owner: Prit Zania (with Devu) — Week 3 Day 3 Deliverable (Docs/week3.md §6 F33, F34, §8 Day 3, line 1487)
Reference: Docs/week3.md §6 (F34 Tool Router & Policy Enforcement), backend/agent/tools/router.py

Responsibilities:
1. Defines canonical ToolDefinitions and parameter JSON schemas for safe workspace operations.
2. Validates tool arguments against schema definitions and WorkspacePathGuard boundary checks.
3. Enforces execution status policy (workspace must be IN_USE; unapproved tasks blocked).
4. Routes validated tool invocations to WorkspaceManager methods.
5. Sanitizes outputs and formats standardized ToolResult records.
6. Integrates seamlessly with Devu's ToolRouter via register_workspace_tools().
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from agent.tools.router import ToolDefinition, ToolRequest, ToolResult, ToolRouter
from app.core.secret_redaction import redact
from app.schemas.workspace import (
    WorkspaceCommandRequest,
    WorkspaceStatus,
    WorkspaceCommitRequest,
    WorkspaceDraftPRRequest,
    WorkspacePushRequest,
    WorkspaceTestExecutionRequest,
    WorkspaceToolPolicyRequest,
    WorkspaceToolPolicyResult,
)
from sandbox.constants import (
    DEFAULT_MAX_ORPHAN_AGE_SECONDS,
    PROTECTED_BRANCHES,
    RECOVERY_STALE_TIMEOUT_SECONDS,
)
from sandbox.exceptions import (
    WorkspaceError,
    WorkspacePathEscapeError,
    WorkspacePolicyViolationError,
    WorkspaceProtectedBranchError,
    WorkspacePublicationUnauthorizedError,
    WorkspaceStateError,
)
from sandbox.path_guard import WorkspacePathGuard
from sandbox.workspace_manager import WorkspaceManager

logger = logging.getLogger(__name__)


# Canonical Tool Names
TOOL_READ_FILE = "read_file"
TOOL_WRITE_FILE = "write_file"
TOOL_PATCH_FILE = "patch_file"
TOOL_DELETE_FILE = "delete_file"
TOOL_LIST_FILES = "list_files"
TOOL_EXECUTE_COMMAND = "execute_command"
TOOL_RUN_TESTS = "run_tests"
TOOL_RECORD_REPAIR = "record_repair_attempt"
TOOL_INSPECT_DIFF = "inspect_git_diff"
TOOL_VALIDATE_DIFF = "validate_task_diff"
TOOL_COMMIT_CHANGES = "commit_task_changes"
TOOL_PUSH_BRANCH = "push_task_branch"
TOOL_CREATE_DRAFT_PR = "create_draft_pr"
# Week 3 Day 6 — Reliability, Security & Failure Recovery tools (Docs/week3.md §8 Day 6)
TOOL_RECOVER_WORKSPACE = "recover_workspace"
TOOL_CHECK_STALE_REVISION = "check_stale_revision"
TOOL_VERIFY_DIFF_IMMUTABILITY = "verify_diff_immutability"
TOOL_CLEANUP_ORPHANED = "cleanup_orphaned_workspaces"
TOOL_VALIDATE_INVARIANTS = "validate_workspace_invariants"
TOOL_CHECK_DISK_BUDGET = "check_disk_budget"

CANONICAL_WORKSPACE_TOOLS: tuple[str, ...] = (
    TOOL_READ_FILE,
    TOOL_WRITE_FILE,
    TOOL_PATCH_FILE,
    TOOL_DELETE_FILE,
    TOOL_LIST_FILES,
    TOOL_EXECUTE_COMMAND,
    TOOL_RUN_TESTS,
    TOOL_RECORD_REPAIR,
    TOOL_INSPECT_DIFF,
    TOOL_VALIDATE_DIFF,
    TOOL_COMMIT_CHANGES,
    TOOL_PUSH_BRANCH,
    TOOL_CREATE_DRAFT_PR,
    TOOL_RECOVER_WORKSPACE,
    TOOL_CHECK_STALE_REVISION,
    TOOL_VERIFY_DIFF_IMMUTABILITY,
    TOOL_CLEANUP_ORPHANED,
    TOOL_VALIDATE_INVARIANTS,
    TOOL_CHECK_DISK_BUDGET,
)


class WorkspaceToolPolicyBridge:
    """Policy engine and routing bridge connecting ToolRouter with WorkspaceManager."""

    def __init__(self, workspace_manager: WorkspaceManager) -> None:
        self._workspace_manager = workspace_manager

    def validate_policy(
        self,
        tool_name: str,
        task_id: str,
        arguments: Mapping[str, Any],
    ) -> WorkspaceToolPolicyResult:
        """Evaluate security policies before tool execution."""
        clean_name = (tool_name or "").strip()
        if clean_name not in CANONICAL_WORKSPACE_TOOLS:
            return WorkspaceToolPolicyResult(
                is_permitted=False,
                tool_name=clean_name,
                sanitized_arguments=dict(arguments),
                violation_reason=f"Tool '{clean_name}' is not an authorized workspace tool.",
            )

        # Global administrative tools (recovery, orphan cleanup) do not require task-level checks
        if clean_name in (TOOL_RECOVER_WORKSPACE, TOOL_CLEANUP_ORPHANED):
            return WorkspaceToolPolicyResult(
                is_permitted=True,
                tool_name=clean_name,
                sanitized_arguments=dict(arguments),
            )

        # Check workspace status
        meta = self._workspace_manager.get_workspace(task_id)
        if not meta:
            return WorkspaceToolPolicyResult(
                is_permitted=False,
                tool_name=clean_name,
                sanitized_arguments=dict(arguments),
                violation_reason=f"No workspace found for task '{task_id}'.",
            )

        # Reliability and inspection tools are allowed outside IN_USE (e.g. READY, STOPPED, FAILED)
        day6_inspection_tools = (
            TOOL_VALIDATE_INVARIANTS,
            TOOL_CHECK_STALE_REVISION,
            TOOL_VERIFY_DIFF_IMMUTABILITY,
            TOOL_CHECK_DISK_BUDGET,
        )
        if clean_name not in day6_inspection_tools and meta.status != WorkspaceStatus.IN_USE:
            return WorkspaceToolPolicyResult(
                is_permitted=False,
                tool_name=clean_name,
                sanitized_arguments=dict(arguments),
                violation_reason=(
                    f"Workspace is in status '{meta.status.value}', expected '{WorkspaceStatus.IN_USE.value}'. "
                    "Tool execution is only permitted during active execution."
                ),
            )

        # Validate arguments based on tool type
        workspace_root = self._workspace_manager.get_workspace_path(task_id)
        sanitized_args = dict(arguments)

        try:
            if clean_name in (TOOL_READ_FILE, TOOL_DELETE_FILE):
                raw_path = str(arguments.get("file_path", "")).strip()
                if not raw_path:
                    raise WorkspacePolicyViolationError("Missing required argument: 'file_path'")
                WorkspacePathGuard.resolve_within_workspace(workspace_root, raw_path)

            elif clean_name == TOOL_WRITE_FILE:
                raw_path = str(arguments.get("file_path", "")).strip()
                if not raw_path:
                    raise WorkspacePolicyViolationError("Missing required argument: 'file_path'")
                if "content" not in arguments:
                    raise WorkspacePolicyViolationError("Missing required argument: 'content'")
                WorkspacePathGuard.resolve_within_workspace(workspace_root, raw_path)

            elif clean_name == TOOL_PATCH_FILE:
                raw_path = str(arguments.get("file_path", "")).strip()
                target = arguments.get("target_content")
                replacement = arguments.get("replacement_content")
                if not raw_path or not target or replacement is None:
                    raise WorkspacePolicyViolationError(
                        "Tool 'patch_file' requires 'file_path', 'target_content', and 'replacement_content'."
                    )
                WorkspacePathGuard.resolve_within_workspace(workspace_root, raw_path)

            elif clean_name == TOOL_LIST_FILES:
                subpath = str(arguments.get("subpath", "")).strip()
                if subpath:
                    WorkspacePathGuard.resolve_within_workspace(workspace_root, subpath)

            elif clean_name == TOOL_EXECUTE_COMMAND:
                cmd = str(arguments.get("command", "")).strip()
                raw_args = arguments.get("arguments", [])
                if not cmd:
                    raise WorkspacePolicyViolationError("Missing required argument: 'command'")
                self._workspace_manager.command_runner.validate_command(cmd, raw_args)

            elif clean_name == TOOL_RUN_TESTS:
                test_path = arguments.get("test_path")
                if test_path:
                    WorkspacePathGuard.resolve_within_workspace(workspace_root, str(test_path).strip())
                raw_args = arguments.get("arguments", [])
                if raw_args:
                    self._workspace_manager.command_runner.validate_command("pytest", raw_args)

            elif clean_name == TOOL_RECORD_REPAIR:
                patch_summary = arguments.get("patch_summary")
                if not patch_summary:
                    raise WorkspacePolicyViolationError("Missing required argument: 'patch_summary'")

            elif clean_name == TOOL_COMMIT_CHANGES:
                message = str(arguments.get("message", "")).strip()
                if not message:
                    raise WorkspacePolicyViolationError("Missing required argument: 'message'")
                branch = str(arguments.get("branch_name", "")).strip().removeprefix("refs/heads/").lower()
                if branch and branch in PROTECTED_BRANCHES:
                    raise WorkspaceProtectedBranchError(f"Cannot commit directly to protected branch '{branch}' (ADR-010).")

            elif clean_name == TOOL_PUSH_BRANCH:
                branch = str(arguments.get("branch_name", "")).strip().removeprefix("refs/heads/").lower()
                if not branch:
                    raise WorkspacePolicyViolationError("Missing required argument: 'branch_name'")
                if branch in PROTECTED_BRANCHES:
                    raise WorkspaceProtectedBranchError(f"Cannot push directly to protected branch '{branch}' (ADR-010).")
                if not arguments.get("publication_authorized", False):
                    raise WorkspacePublicationUnauthorizedError(
                        "Push blocked: explicit human publication authorization is required (ADR-010, Docs/week3.md §6 F37)."
                    )

            elif clean_name == TOOL_CREATE_DRAFT_PR:
                title = str(arguments.get("title", "")).strip()
                head_branch = str(arguments.get("head_branch", "")).strip().removeprefix("refs/heads/").lower()
                if not title:
                    raise WorkspacePolicyViolationError("Missing required argument: 'title'")
                if not head_branch:
                    raise WorkspacePolicyViolationError("Missing required argument: 'head_branch'")
                if head_branch in PROTECTED_BRANCHES:
                    raise WorkspaceProtectedBranchError(f"Head branch '{head_branch}' cannot be a protected branch.")
                if not arguments.get("publication_authorized", False):
                    raise WorkspacePublicationUnauthorizedError(
                        "Draft PR creation blocked: explicit human publication authorization is required (ADR-010)."
                    )

        except (WorkspacePathEscapeError, WorkspacePolicyViolationError, WorkspaceProtectedBranchError, WorkspacePublicationUnauthorizedError, WorkspaceError) as exc:
            return WorkspaceToolPolicyResult(
                is_permitted=False,
                tool_name=clean_name,
                sanitized_arguments=sanitized_args,
                violation_reason=str(exc),
            )

        return WorkspaceToolPolicyResult(
            is_permitted=True,
            tool_name=clean_name,
            sanitized_arguments=sanitized_args,
        )

    def execute_tool(
        self,
        request: ToolRequest,
        agent_state: Any,
    ) -> ToolResult:
        """Execute a tool request through policy verification and workspace delegation."""
        # Extract task_id from agent_state or arguments
        task_id = ""
        if hasattr(agent_state, "task_id"):
            task_id = str(agent_state.task_id)
        elif isinstance(agent_state, dict) and "task_id" in agent_state:
            task_id = str(agent_state["task_id"])
        elif "task_id" in request.arguments:
            task_id = str(request.arguments["task_id"])

        if not task_id and request.tool_name not in (TOOL_RECOVER_WORKSPACE, TOOL_CLEANUP_ORPHANED):
            return ToolResult(
                success=False,
                error="Policy violation: task_id could not be resolved from agent state or arguments.",
            )

        # Policy check
        policy_res = self.validate_policy(request.tool_name, task_id, request.arguments)
        if not policy_res.is_permitted:
            logger.warning(
                "tool_policy_denied",
                extra={
                    "tool": request.tool_name,
                    "task_id": task_id,
                    "reason": policy_res.violation_reason,
                },
            )
            return ToolResult(
                success=False,
                error=f"Security policy violation: {policy_res.violation_reason}",
            )

        args = request.arguments
        tool_name = request.tool_name

        try:
            if tool_name == TOOL_READ_FILE:
                res = self._workspace_manager.read_file(task_id, args["file_path"])
                return ToolResult(
                    success=res.success,
                    output=res.content if res.success else None,
                    error=res.error,
                )

            elif tool_name == TOOL_WRITE_FILE:
                create_parents = args.get("create_parents", True)
                res = self._workspace_manager.write_file(
                    task_id,
                    args["file_path"],
                    args["content"],
                    create_parents=create_parents,
                )
                return ToolResult(
                    success=res.success,
                    output={"bytes_written": res.bytes_written, "created": res.created}
                    if res.success
                    else None,
                    error=res.error,
                )

            elif tool_name == TOOL_PATCH_FILE:
                res = self._workspace_manager.patch_file(
                    task_id,
                    args["file_path"],
                    args["target_content"],
                    args["replacement_content"],
                )
                return ToolResult(
                    success=res.success,
                    output={"occurrences_replaced": res.occurrences_replaced}
                    if res.success
                    else None,
                    error=res.error,
                )

            elif tool_name == TOOL_DELETE_FILE:
                deleted = self._workspace_manager.delete_file(task_id, args["file_path"])
                return ToolResult(
                    success=True,
                    output={"deleted": deleted, "file_path": args["file_path"]},
                )

            elif tool_name == TOOL_LIST_FILES:
                files = self._workspace_manager.list_files(task_id, args.get("subpath", ""))
                return ToolResult(success=True, output=files)

            elif tool_name == TOOL_EXECUTE_COMMAND:
                cmd_req = WorkspaceCommandRequest(
                    task_id=task_id,
                    command=args["command"],
                    arguments=args.get("arguments", []),
                    timeout_seconds=args.get("timeout_seconds"),
                    environment=args.get("environment", {}),
                )
                cmd_res = self._workspace_manager.execute_command(cmd_req)
                return ToolResult(
                    success=cmd_res.success,
                    output={
                        "exit_code": cmd_res.exit_code,
                        "stdout": cmd_res.stdout,
                        "stderr": cmd_res.stderr,
                        "duration_ms": cmd_res.duration_ms,
                        "timed_out": cmd_res.timed_out,
                    },
                    error=cmd_res.error,
                )

            elif tool_name == TOOL_RUN_TESTS:
                test_req = WorkspaceTestExecutionRequest(
                    task_id=task_id,
                    framework=args.get("framework"),
                    test_path=args.get("test_path"),
                    arguments=args.get("arguments", []),
                    timeout_seconds=args.get("timeout_seconds"),
                    environment=args.get("environment", {}),
                )
                test_res = self._workspace_manager.run_tests(test_req)
                return ToolResult(
                    success=test_res.success,
                    output={
                        "status": test_res.status.value,
                        "classification": test_res.classification.value,
                        "is_repair_eligible": test_res.is_repair_eligible,
                        "passed_count": test_res.passed_count,
                        "failed_count": test_res.failed_count,
                        "skipped_count": test_res.skipped_count,
                        "error_count": test_res.error_count,
                        "total_count": test_res.total_count,
                        "duration_ms": test_res.duration_ms,
                        "failed_test_names": test_res.failed_test_names,
                        "failure_details": test_res.failure_details,
                        "stdout": test_res.stdout,
                        "stderr": test_res.stderr,
                        "timed_out": test_res.timed_out,
                        "framework": test_res.framework,
                    },
                    error=test_res.error,
                )

            elif tool_name == TOOL_RECORD_REPAIR:
                record = self._workspace_manager.record_repair_attempt(
                    task_id=task_id,
                    patch_summary=args["patch_summary"],
                    patch_content=args.get("patch_content"),
                    test_status_before=args.get("test_status_before"),
                    test_status_after=args.get("test_status_after"),
                    success=args.get("success", False),
                )
                return ToolResult(
                    success=True,
                    output={
                        "attempt_number": record.attempt_number,
                        "patch_summary": record.patch_summary,
                        "patch_hash": record.patch_hash,
                        "success": record.success,
                        "timestamp": record.timestamp,
                    },
                )

            elif tool_name == TOOL_INSPECT_DIFF:
                diff_res = self._workspace_manager.get_workspace_diff(task_id, args.get("base_revision"))
                return ToolResult(
                    success=True,
                    output={
                        "total_files_changed": diff_res.total_files_changed,
                        "insertions": diff_res.insertions,
                        "deletions": diff_res.deletions,
                        "is_empty": diff_res.is_empty,
                        "base_revision": diff_res.base_revision,
                        "files": [f.model_dump() for f in diff_res.files],
                        "raw_diff": diff_res.raw_diff,
                    },
                )

            elif tool_name == TOOL_VALIDATE_DIFF:
                val_res = self._workspace_manager.validate_workspace_diff(
                    task_id,
                    allowed_files=args.get("allowed_files"),
                    allow_critical_deletions=args.get("allow_critical_deletions", False),
                )
                return ToolResult(
                    success=val_res.is_valid,
                    output={
                        "is_valid": val_res.is_valid,
                        "verified_revision": val_res.verified_revision,
                        "modified_files": val_res.modified_files,
                        "unapproved_files": val_res.unapproved_files,
                        "deleted_critical_files": val_res.deleted_critical_files,
                        "secret_findings": [f.model_dump() for f in val_res.secret_findings],
                        "blocking_findings": val_res.blocking_findings,
                        "warnings": val_res.warnings,
                    },
                    error="; ".join(val_res.blocking_findings) if not val_res.is_valid else None,
                )

            elif tool_name == TOOL_COMMIT_CHANGES:
                commit_req = WorkspaceCommitRequest(
                    task_id=task_id,
                    message=args["message"],
                    branch_name=args.get("branch_name"),
                    author_name=args.get("author_name", "Agent"),
                    author_email=args.get("author_email", "agent@ai-platform.local"),
                    files=args.get("files"),
                )
                commit_res = self._workspace_manager.commit_task_changes(commit_req)
                return ToolResult(
                    success=commit_res.success,
                    output={
                        "commit_sha": commit_res.commit_sha,
                        "branch": commit_res.branch,
                        "message": commit_res.message,
                        "files_committed": commit_res.files_committed,
                    },
                    error=commit_res.error,
                )

            elif tool_name == TOOL_PUSH_BRANCH:
                push_req = WorkspacePushRequest(
                    task_id=task_id,
                    branch_name=args["branch_name"],
                    remote_name=args.get("remote_name", "origin"),
                    publication_authorized=args.get("publication_authorized", False),
                    remote_url=args.get("remote_url"),
                )
                push_res = self._workspace_manager.push_task_branch(push_req)
                return ToolResult(
                    success=push_res.success,
                    output={
                        "branch": push_res.branch,
                        "pushed_sha": push_res.pushed_sha,
                        "remote_name": push_res.remote_name,
                    },
                    error=push_res.error,
                )

            elif tool_name == TOOL_CREATE_DRAFT_PR:
                pr_req = WorkspaceDraftPRRequest(
                    task_id=task_id,
                    title=args["title"],
                    body=args.get("body"),
                    head_branch=args["head_branch"],
                    base_branch=args.get("base_branch", "main"),
                    draft=True,
                    repository_owner=args.get("repository_owner"),
                    repository_name=args.get("repository_name"),
                    publication_authorized=args.get("publication_authorized", False),
                )
                pr_res = self._workspace_manager.create_draft_pr(pr_req)
                return ToolResult(
                    success=pr_res.success,
                    output={
                        "pr_number": pr_res.pr_number,
                        "pr_url": pr_res.pr_url,
                        "head_branch": pr_res.head_branch,
                        "base_branch": pr_res.base_branch,
                        "is_draft": pr_res.is_draft,
                        "summary": pr_res.summary,
                    },
                    error=pr_res.error,
                )

            elif tool_name == TOOL_RECOVER_WORKSPACE:
                target_task_id = args.get("task_id") or task_id
                if target_task_id:
                    rec = self._workspace_manager.reconcile_workspace(target_task_id)
                    return ToolResult(
                        success=True,
                        output=rec.model_dump(),
                    )
                else:
                    recovery_res = self._workspace_manager.recover_workspaces(
                        stale_timeout_seconds=args.get("stale_timeout_seconds", RECOVERY_STALE_TIMEOUT_SECONDS)
                    )
                    return ToolResult(
                        success=True,
                        output=recovery_res.model_dump(),
                    )

            elif tool_name == TOOL_CHECK_STALE_REVISION:
                stale_res = self._workspace_manager.detect_stale_base_revision(
                    task_id=task_id,
                    remote_name=args.get("remote_name", "origin"),
                    base_branch=args.get("base_branch", "main"),
                )
                return ToolResult(
                    success=True,
                    output=stale_res.model_dump(),
                )

            elif tool_name == TOOL_VERIFY_DIFF_IMMUTABILITY:
                imm_res = self._workspace_manager.verify_diff_immutability(
                    task_id=task_id,
                    expected_hash=args.get("expected_hash"),
                )
                return ToolResult(
                    success=imm_res.is_immutable,
                    output=imm_res.model_dump(),
                    error=imm_res.error_message if not imm_res.is_immutable else None,
                )

            elif tool_name == TOOL_CLEANUP_ORPHANED:
                cleanup_res = self._workspace_manager.cleanup_orphaned_workspaces(
                    max_age_seconds=args.get("max_age_seconds", DEFAULT_MAX_ORPHAN_AGE_SECONDS),
                    dry_run=args.get("dry_run", False),
                )
                return ToolResult(
                    success=True,
                    output=cleanup_res.model_dump(),
                )

            elif tool_name == TOOL_VALIDATE_INVARIANTS:
                inv_res = self._workspace_manager.validate_workspace_invariants(task_id=task_id)
                return ToolResult(
                    success=inv_res.is_valid,
                    output=inv_res.model_dump(),
                    error="; ".join(inv_res.violations) if not inv_res.is_valid else None,
                )

            elif tool_name == TOOL_CHECK_DISK_BUDGET:
                disk_res = self._workspace_manager.check_disk_budget(
                    task_id=task_id,
                    max_bytes=args.get("max_bytes"),
                    max_files=args.get("max_files"),
                )
                return ToolResult(
                    success=not disk_res.is_exceeded,
                    output=disk_res.model_dump(),
                    error=disk_res.error_message if disk_res.is_exceeded else None,
                )

            return ToolResult(success=False, error=f"Unhandled tool: {tool_name}")

        except Exception as exc:
            logger.error("tool_execution_unhandled_error", extra={"tool": tool_name, "error": str(exc)})
            return ToolResult(success=False, error=redact(f"Tool execution failed: {exc}"))


# Explicitly mark execute_tool as policy-guarded because WorkspaceToolPolicyBridge enforces strict policies
WorkspaceToolPolicyBridge.execute_tool._is_policy_guarded = True


def register_workspace_tools(
    tool_router: ToolRouter,
    workspace_manager: WorkspaceManager,
) -> WorkspaceToolPolicyBridge:
    """Register all canonical workspace tools with the agent ToolRouter."""
    bridge = WorkspaceToolPolicyBridge(workspace_manager)

    tool_specs: list[tuple[str, str, dict[str, Any]]] = [
        (
            TOOL_READ_FILE,
            "Safely read a file's content within the task's isolated workspace sandbox.",
            {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Repository-relative file path to read.",
                    }
                },
                "required": ["file_path"],
            },
        ),
        (
            TOOL_WRITE_FILE,
            "Safely write or overwrite a file within the task's isolated workspace sandbox.",
            {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Repository-relative file path to write.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full file content to write.",
                    },
                    "create_parents": {
                        "type": "boolean",
                        "description": "Whether to automatically create missing parent directories.",
                        "default": True,
                    },
                },
                "required": ["file_path", "content"],
            },
        ),
        (
            TOOL_PATCH_FILE,
            "Safely apply an exact text replacement patch to a file in the workspace.",
            {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Repository-relative file path to patch.",
                    },
                    "target_content": {
                        "type": "string",
                        "description": "Exact text substring to find and replace.",
                    },
                    "replacement_content": {
                        "type": "string",
                        "description": "Replacement text substring.",
                    },
                },
                "required": ["file_path", "target_content", "replacement_content"],
            },
        ),
        (
            TOOL_DELETE_FILE,
            "Safely delete a file located inside the task's isolated workspace.",
            {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Repository-relative file path to delete.",
                    }
                },
                "required": ["file_path"],
            },
        ),
        (
            TOOL_LIST_FILES,
            "List repository-relative files within the workspace or a given subpath.",
            {
                "type": "object",
                "properties": {
                    "subpath": {
                        "type": "string",
                        "description": "Optional subdirectory relative path to list.",
                        "default": "",
                    }
                },
            },
        ),
        (
            TOOL_EXECUTE_COMMAND,
            "Execute an allowlisted command (e.g. pytest, git, npm) inside the workspace.",
            {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Executable command name (e.g. git, pytest, python).",
                    },
                    "arguments": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Positional command arguments.",
                    },
                    "timeout_seconds": {
                        "type": "integer",
                        "description": "Command execution timeout in seconds.",
                        "default": 60,
                    },
                },
                "required": ["command"],
            },
        ),
        (
            TOOL_RUN_TESTS,
            "Execute repository tests inside the task workspace sandbox with resource limits.",
            {
                "type": "object",
                "properties": {
                    "test_path": {
                        "type": "string",
                        "description": "Optional specific test file or directory path.",
                    },
                    "framework": {
                        "type": "string",
                        "description": "Optional explicit framework (pytest, unittest, jest).",
                    },
                    "arguments": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Additional positional test runner arguments.",
                    },
                    "timeout_seconds": {
                        "type": "integer",
                        "description": "Test execution timeout in seconds (default: 60, max: 300).",
                        "default": 60,
                    },
                },
            },
        ),
        (
            TOOL_RECORD_REPAIR,
            "Record a self-repair attempt against the task-level 3-attempt ceiling.",
            {
                "type": "object",
                "properties": {
                    "patch_summary": {
                        "type": "string",
                        "description": "Summary of code changes applied during this repair attempt.",
                    },
                    "patch_content": {
                        "type": "string",
                        "description": "Optional raw patch content to detect duplicate cycles.",
                    },
                    "success": {
                        "type": "boolean",
                        "description": "Whether the repair attempt produced passing tests.",
                        "default": False,
                    },
                },
                "required": ["patch_summary"],
            },
        ),
        (
            TOOL_INSPECT_DIFF,
            "Inspect unified and per-file diffs of modifications made inside the task workspace sandbox.",
            {
                "type": "object",
                "properties": {
                    "base_revision": {
                        "type": "string",
                        "description": "Base git revision to compare against (defaults to HEAD).",
                    },
                },
            },
        ),
        (
            TOOL_VALIDATE_DIFF,
            "Validate sandbox diff against allowed scope, secret leaks, and critical manifest deletions.",
            {
                "type": "object",
                "properties": {
                    "allowed_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Allowed file paths. If omitted, uses files declared in task execution plan.",
                    },
                    "allow_critical_deletions": {
                        "type": "boolean",
                        "description": "Whether deletion of critical project manifests is explicitly allowed.",
                        "default": False,
                    },
                },
            },
        ),
        (
            TOOL_COMMIT_CHANGES,
            "Create a clean git commit of verified task workspace changes with task metadata.",
            {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Git commit message describing task changes.",
                    },
                    "branch_name": {
                        "type": "string",
                        "description": "Target branch name to commit to (must not be a protected branch).",
                    },
                    "author_name": {
                        "type": "string",
                        "description": "Commit author name.",
                        "default": "Agent",
                    },
                    "author_email": {
                        "type": "string",
                        "description": "Commit author email.",
                        "default": "agent@ai-platform.local",
                    },
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific repository files to stage. If omitted, stages all changed files.",
                    },
                },
                "required": ["message"],
            },
        ),
        (
            TOOL_PUSH_BRANCH,
            "Push task feature branch to remote origin. Requires explicit human publication authorization.",
            {
                "type": "object",
                "properties": {
                    "branch_name": {
                        "type": "string",
                        "description": "Target feature branch to push (cannot be a protected branch).",
                    },
                    "remote_name": {
                        "type": "string",
                        "description": "Git remote name.",
                        "default": "origin",
                    },
                    "publication_authorized": {
                        "type": "boolean",
                        "description": "Explicit human publication authorization token flag (must be True to push).",
                        "default": False,
                    },
                    "remote_url": {
                        "type": "string",
                        "description": "Optional custom remote repository URL.",
                    },
                },
                "required": ["branch_name"],
            },
        ),
        (
            TOOL_CREATE_DRAFT_PR,
            "Generate and prepare a draft pull request with structured task summary. Auto-merge is strictly forbidden.",
            {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Draft pull request title.",
                    },
                    "head_branch": {
                        "type": "string",
                        "description": "Source feature branch name (cannot be protected).",
                    },
                    "body": {
                        "type": "string",
                        "description": "Custom PR description body. If omitted, auto-generates structured task summary.",
                    },
                    "base_branch": {
                        "type": "string",
                        "description": "Target base branch to merge into.",
                        "default": "main",
                    },
                    "repository_owner": {
                        "type": "string",
                        "description": "Repository owner or organization name.",
                    },
                    "repository_name": {
                        "type": "string",
                        "description": "Repository name.",
                    },
                    "publication_authorized": {
                        "type": "boolean",
                        "description": "Explicit human publication authorization token flag.",
                        "default": False,
                    },
                },
                "required": ["title", "head_branch"],
            },
        ),
        (
            TOOL_RECOVER_WORKSPACE,
            "Scan workspaces and recover from worker crashes, interrupted tasks, and orphan states.",
            {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "Optional specific task_id to reconcile.",
                    },
                    "stale_timeout_seconds": {
                        "type": "integer",
                        "description": "Seconds without activity before a running workspace is considered stale and recovered.",
                    },
                },
            },
        ),
        (
            TOOL_CHECK_STALE_REVISION,
            "Verify that the workspace base branch has not diverged from the remote tracking branch.",
            {
                "type": "object",
                "properties": {
                    "remote_name": {
                        "type": "string",
                        "description": "Remote name to fetch (default 'origin').",
                        "default": "origin",
                    },
                    "base_branch": {
                        "type": "string",
                        "description": "Base branch to compare against (default 'main').",
                        "default": "main",
                    },
                },
            },
        ),
        (
            TOOL_VERIFY_DIFF_IMMUTABILITY,
            "Verify that no workspace files have mutated since the independent verification step.",
            {
                "type": "object",
                "properties": {
                    "expected_hash": {
                        "type": "string",
                        "description": "Expected SHA-256 hash of the git diff output from the verification gate.",
                    },
                },
            },
        ),
        (
            TOOL_CLEANUP_ORPHANED,
            "Clean up orphaned workspace directories exceeding the maximum orphan age threshold.",
            {
                "type": "object",
                "properties": {
                    "max_age_seconds": {
                        "type": "integer",
                        "description": "Maximum age in seconds before an untracked workspace is deleted (default 86400).",
                        "default": 86400,
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "If true, simulates cleanup without removing directories.",
                        "default": False,
                    },
                },
            },
        ),
        (
            TOOL_VALIDATE_INVARIANTS,
            "Audit structural, disk, process, and security invariants for the workspace.",
            {
                "type": "object",
                "properties": {},
            },
        ),
        (
            TOOL_CHECK_DISK_BUDGET,
            "Check workspace disk usage and file counts against allocated quotas.",
            {
                "type": "object",
                "properties": {
                    "max_bytes": {
                        "type": "integer",
                        "description": "Maximum allowed workspace disk bytes.",
                    },
                    "max_files": {
                        "type": "integer",
                        "description": "Maximum allowed file count.",
                    },
                },
            },
        ),
    ]

    for name, desc, params in tool_specs:
        defn = ToolDefinition(name=name, description=desc, parameters=params)
        # Wrap handler to bind bridge
        tool_router.register(defn, bridge.execute_tool)

    return bridge
