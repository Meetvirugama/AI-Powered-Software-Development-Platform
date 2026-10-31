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
    WorkspaceTestExecutionRequest,
    WorkspaceToolPolicyRequest,
    WorkspaceToolPolicyResult,
)
from sandbox.exceptions import (
    WorkspaceError,
    WorkspacePathEscapeError,
    WorkspacePolicyViolationError,
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

CANONICAL_WORKSPACE_TOOLS: tuple[str, ...] = (
    TOOL_READ_FILE,
    TOOL_WRITE_FILE,
    TOOL_PATCH_FILE,
    TOOL_DELETE_FILE,
    TOOL_LIST_FILES,
    TOOL_EXECUTE_COMMAND,
    TOOL_RUN_TESTS,
    TOOL_RECORD_REPAIR,
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

        # Check workspace status
        meta = self._workspace_manager.get_workspace(task_id)
        if not meta:
            return WorkspaceToolPolicyResult(
                is_permitted=False,
                tool_name=clean_name,
                sanitized_arguments=dict(arguments),
                violation_reason=f"No workspace found for task '{task_id}'.",
            )

        if meta.status != WorkspaceStatus.IN_USE:
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

        except (WorkspacePathEscapeError, WorkspacePolicyViolationError, WorkspaceError) as exc:
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

        if not task_id:
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
    ]

    for name, desc, params in tool_specs:
        defn = ToolDefinition(name=name, description=desc, parameters=params)
        # Wrap handler to bind bridge
        tool_router.register(defn, bridge.execute_tool)

    return bridge
