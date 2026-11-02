"""API tool policy for POST /api/v1/tasks/{task_id}/tools/{tool_name}.

Owner: Sukun (Security) — Week 3 Day 3 (Docs/security/week3_threat_model.md, F34 / F37).

Why this exists:
Workspace tools are registered as "policy guarded", so ToolRouter skips its own
command-template and argv checks for them and only the WorkspaceToolPolicyBridge
runs. The bridge trusts some arguments that only server code should set
(`publication_authorized`, `remote_url`, `task_id`, `environment`) and lets any
allowlisted binary run with any arguments (for example `python -c ...` or
`cat /etc/passwd`). This module is the extra check for calls that come from
API users (and, later, from model-written tool calls).
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from agent.tools.router import ToolRouter
from app.core.errors import ErrorCode

# Tools that must never be reachable through the generic per-task tool API.
API_BLOCKED_TOOLS: dict[str, str] = {
    "push_task_branch": (
        "Pushing is not available through the tool API. Publication must go through the "
        "publish flow after verification and explicit publish approval."
    ),
    "create_draft_pr": (
        "Draft PR creation is not available through the tool API. Publication must go through "
        "the publish flow after verification and explicit publish approval."
    ),
    "recover_workspace": "Workspace recovery is a system operation and is not available per task.",
    "cleanup_orphaned_workspaces": "Workspace cleanup is a system operation and is not available per task.",
}

# Arguments only trusted server code may set: a caller must never be able to claim
# publication approval, choose a git remote, target another task or inject env vars.
API_FORBIDDEN_ARGUMENT_KEYS: frozenset[str] = frozenset(
    {"publication_authorized", "remote_url", "remote_name", "task_id", "environment"}
)

_ABSOLUTE_PATH_RE = re.compile(r"^(?:/|\\|~|[A-Za-z]:[\\/])")


def argv_safety_error(argv: Sequence[str]) -> str | None:
    """Reuse ToolRouter token rules and also reject absolute and home paths."""
    token_error = ToolRouter.validate_argv_tokens(list(argv))
    if token_error:
        return token_error
    for token in argv:
        value = token.split("=", 1)[1] if token.startswith("-") and "=" in token else token
        if _ABSOLUTE_PATH_RE.match(token) or _ABSOLUTE_PATH_RE.match(value):
            return f"Absolute or home paths are not permitted in command arguments: {token!r}"
    return None


def matches_command_template(argv: Sequence[str], templates: Sequence[Sequence[str]]) -> bool:
    """True when argv equals a template, or starts with a template ending in '*'."""
    for template in templates:
        if not template:
            continue
        if list(argv) == list(template):
            return True
        if template[-1] == "*":
            prefix = list(template[:-1])
            if len(argv) >= len(prefix) and list(argv[: len(prefix)]) == prefix:
                return True
    return False


def api_tool_policy_violation(
    tool_name: str,
    arguments: Mapping[str, Any],
    command_templates: Sequence[Sequence[str]],
) -> tuple[ErrorCode, str] | None:
    """Return (error_code, reason) when an API tool call must be refused, otherwise None.

    `command_templates` are the approved argv templates for `execute_command`
    (DEFAULT_COMMAND_ALLOWLIST["execute_command"] in the task orchestrator).
    """
    if tool_name in API_BLOCKED_TOOLS:
        return ErrorCode.POLICY_VIOLATION, API_BLOCKED_TOOLS[tool_name]

    forbidden = sorted(str(key) for key in arguments if str(key) in API_FORBIDDEN_ARGUMENT_KEYS)
    if forbidden:
        return (
            ErrorCode.POLICY_VIOLATION,
            f"These arguments cannot be set by API callers: {', '.join(forbidden)}",
        )

    if tool_name in ("execute_command", "run_tests"):
        raw_args = arguments.get("arguments", []) or []
        if not isinstance(raw_args, list) or not all(isinstance(item, str) for item in raw_args):
            return ErrorCode.POLICY_VIOLATION, "Command arguments must be a list of strings."

        if tool_name == "execute_command":
            argv = [str(arguments.get("command", "")).strip(), *raw_args]
            error = argv_safety_error(argv)
            if error:
                return ErrorCode.COMMAND_NOT_ALLOWED, error
            if not matches_command_template(argv, command_templates):
                return (
                    ErrorCode.COMMAND_NOT_ALLOWED,
                    f"Command is not in the approved command allowlist: {' '.join(argv)[:200]}",
                )
        elif raw_args:
            error = argv_safety_error(raw_args)
            if error:
                return ErrorCode.COMMAND_NOT_ALLOWED, error

    return None
