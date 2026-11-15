"""Tool definitions, registration, and policy-enforced routing for agent tools.

F21 Unified Tool Registry Architecture (Issue #201).
Integrates:
- UnifiedToolRegistry: SemVer resolution, collision prevention, metadata contracts
- SchemaValidator: Draft 2020-12 JSON Schema validation, precompiled caches, depth limits
- ToolRateLimiter: Sliding-window rate limiting per task/user/provider
- BuiltinWorkspaceAdapter: Zero TypeError retry fallback, signature inspection
- Output Sanitization: Common post-execution boundary (output schema, secret redaction, bounding)
"""

from __future__ import annotations

import concurrent.futures
import contextlib
from dataclasses import dataclass, field
import inspect
import json
import logging
import math
import re
import time
from typing import Any, Callable

from agent.tools.adapters.builtin import BuiltinWorkspaceAdapter
from agent.tools.models import (
    ToolAnnotations,
    ToolDefinition,
    ToolRateLimit,
    ToolRequest,
    ToolResult,
)
from agent.tools.rate_limiter import RateLimitDecision, ToolRateLimiter
from agent.tools.registry import UnifiedToolRegistry
from agent.tools.schema_validator import SchemaValidator
from ai.security.taint_policy import TaintPolicyEngine

logger = logging.getLogger(__name__)


class ToolRouter:
    """Registers tools, enforces schemas, rate limits, authorizations, and bounds outputs."""

    SECRET_PATTERNS = (
        re.compile(
            r"""(?i)(["']?(?:api[_-]?key|access[_-]?token|secret|password)["']?\s*[:=]\s*["']?)([^\s,"';}]+)"""
        ),
        re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
        re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    )

    SHELL_METACHAR_PATTERN = re.compile(r"[;&|`$><\n\r\x00]")
    FORBIDDEN_FLAGS = frozenset({
        "-c",
        "--command",
        "--upload-pack",
        "--receive-pack",
        "--exec",
        "-o",
        "--override-ini",
        "--rootdir",
        "--import-mode",
    })

    def __init__(
        self,
        policy_engine: Any = None,
        policy_context_factory: Callable[[Any, ToolRequest], Any] | None = None,
        command_allowlist: dict[str, list[list[str]]] | None = None,
        max_output_chars: int = 10000,
        registry: UnifiedToolRegistry | None = None,
        rate_limiter: ToolRateLimiter | None = None,
        schema_validator: SchemaValidator | None = None,
    ) -> None:
        if max_output_chars < 1:
            raise ValueError("max_output_chars must be positive")

        self._policy_engine = policy_engine
        self._policy_context_factory = policy_context_factory
        self._command_allowlist = command_allowlist or {}
        self._max_output_chars = max_output_chars

        # Subsystems
        self.schema_validator = schema_validator or SchemaValidator()
        self.registry = registry or UnifiedToolRegistry(schema_validator=self.schema_validator)
        self.rate_limiter = rate_limiter or ToolRateLimiter(fallback_to_memory=True)

        # Backward-compatibility maps
        self._tools: dict[str, ToolDefinition] = {}
        self._handlers: dict[str, Callable[..., Any]] = {}
        self._builtin_adapter = BuiltinWorkspaceAdapter()

    def register(
        self,
        definition: ToolDefinition | Any,
        handler: Callable[..., Any],
        adapter: Any = None,
    ) -> None:
        """Register a tool, its metadata schema, and its execution handler."""
        if not definition.name or not isinstance(definition.name, str):
            raise ValueError("Tool name must be a non-empty string")

        if definition.name in self._tools or self.registry.has_tool(definition.name):
            raise ValueError(f"Tool already registered: {definition.name}")

        params = getattr(definition, "input_schema", None) or getattr(definition, "parameters", None)
        if not isinstance(params, dict):
            raise ValueError("Tool parameters must be a JSON Schema object")

        if params.get("type") != "object":
            raise ValueError("Tool parameter schema must have type 'object'")

        if not callable(handler):
            raise ValueError("Tool handler must be callable")

        # Normalize to rich ToolDefinition if needed
        if not isinstance(definition, ToolDefinition):
            rich_def = ToolDefinition(
                name=definition.name,
                description=definition.description,
                input_schema=params,
                output_schema=getattr(definition, "output_schema", None),
                annotations=getattr(definition, "annotations", ToolAnnotations()),
                risk_tier=getattr(definition, "risk_tier", "medium"),
                version=getattr(definition, "version", "1.0.0"),
                source=getattr(definition, "source", "builtin"),
                timeout_s=getattr(definition, "timeout_s", 60.0),
                rate_limit=getattr(definition, "rate_limit", None),
            )
        else:
            rich_def = definition

        # Track in backward-compatibility dictionaries
        self._tools[rich_def.name] = rich_def
        self._handlers[rich_def.name] = handler

        # Register in UnifiedToolRegistry
        self.registry.register(
            tool=rich_def,
            adapter=adapter,
            handler=handler,
        )

    def get_tools(self) -> list[ToolDefinition]:
        """Return all registered tool definitions."""
        return self.registry.list_tools()

    def _validate_arguments(
        self,
        arguments: dict[str, Any],
        schema: dict[str, Any],
    ) -> str | None:
        """Validate request arguments against tool schema."""
        if not isinstance(arguments, dict):
            return "Tool arguments must be an object"

        if schema.get("type") != "object":
            return "Tool parameter schema must declare type 'object'"

        return self.schema_validator.validate_arguments(arguments, schema)

    @classmethod
    def validate_argv_tokens(cls, argv: list[str]) -> str | None:
        """Validate command argv tokens against metacharacters, path traversal, and forbidden flags."""
        for token in argv:
            if not isinstance(token, str) or not token.strip():
                return "Command argv tokens must be non-empty strings"
            if cls.SHELL_METACHAR_PATTERN.search(token):
                return f"Forbidden shell metacharacter in command argument: {token!r}"
            normalized = token.replace("\\", "/")
            if ".." in normalized.split("/"):
                return f"Path traversal ('..') is not permitted in command arguments: {token!r}"
            flag_head = token.split("=", 1)[0].strip()
            if flag_head in cls.FORBIDDEN_FLAGS:
                return f"Forbidden command flag: {flag_head}"
        return None

    def _validate_command(
        self,
        tool_name: str,
        arguments: dict,
    ) -> str | None:
        """Validate argv against approved command templates and safety constraints."""
        if "command" in arguments:
            return "Shell command strings are not permitted; use argv"

        if "argv" not in arguments:
            return None

        argv = arguments["argv"]

        if (
            not isinstance(argv, list)
            or not argv
            or not all(isinstance(item, str) and item for item in argv)
        ):
            return "Command argv must be a non-empty list of strings"

        token_err = self.validate_argv_tokens(argv)
        if token_err:
            return token_err

        allowed = self._command_allowlist.get(tool_name, [])

        if not allowed:
            return f"No approved command templates for tool: {tool_name}"

        for template in allowed:
            if not isinstance(template, list) or not template:
                continue
            if argv == template:
                return None
            if template[-1] == "*" and len(argv) >= len(template) - 1:
                prefix = template[:-1]
                if argv[: len(prefix)] == prefix:
                    return None

        return "Command is not in the approved command allowlist"

    def _authorize(
        self,
        request: ToolRequest,
        agent_state: Any,
    ) -> str | None:
        """Check authorization with policy engine. Any failure or absence denies access."""
        if self._policy_engine is None:
            return "Policy engine unavailable; execution denied"

        if isinstance(self._policy_engine, TaintPolicyEngine):
            task_id = (
                agent_state.get("task_id")
                if isinstance(agent_state, dict)
                else getattr(agent_state, "task_id", None)
            )
            repository_id = (
                agent_state.get("repository_id")
                if isinstance(agent_state, dict)
                else getattr(agent_state, "repository_id", None)
            )
            prov_ids = list(getattr(request, "provenance_ids", []) or [])
            if getattr(request, "provenance", None):
                prov_ids.append(request.provenance.provenance_id)

            target_files: list[str] = []
            if "file_path" in request.arguments:
                target_files.append(str(request.arguments["file_path"]))
            elif "path" in request.arguments:
                target_files.append(str(request.arguments["path"]))
            elif "files" in request.arguments and isinstance(request.arguments["files"], list):
                target_files.extend(str(f) for f in request.arguments["files"])

            res = self._policy_engine.evaluate(
                action_type=request.tool_name,
                arguments=request.arguments,
                target_files=target_files,
                provenance_ids=prov_ids,
                task_id=task_id,
                repository_id=repository_id,
            )
            if not res.is_allowed:
                return f"Policy denied tool execution: {res.reason}"
            return None

        if self._policy_context_factory is None:
            return "Policy context unavailable; execution denied"

        try:
            context = self._policy_context_factory(agent_state, request)
            if context is None:
                return "Policy context unavailable; execution denied"

            decision = self._policy_engine.check(
                tool=request.tool_name,
                agent_state=agent_state,
                context=context,
            )

            if decision is None:
                return "Policy returned no decision; execution denied"

            decision_value = getattr(decision, "value", decision)
            decision_name = getattr(decision, "name", decision_value)

            if str(decision_value).upper() == "ALLOW":
                return None

            return f"Policy denied tool execution: {decision_name}"

        except Exception:
            return "Policy evaluation failed; execution denied"

    @classmethod
    def _redact_string(cls, value: str) -> str:
        """Redact common secrets and credentials from output."""
        from app.core.secret_redaction import redact

        result = redact(value)
        for index, pattern in enumerate(cls.SECRET_PATTERNS):
            if index == 0:
                result = pattern.sub(r"\1[REDACTED]", result)
            else:
                result = pattern.sub("[REDACTED]", result)
        return result

    def _sanitize_output(self, output: Any) -> Any:
        """Redact secrets and bound total output length."""
        try:
            serialized = json.dumps(output, default=str)
        except (TypeError, ValueError):
            serialized = repr(output)

        sanitized = self._redact_string(serialized)

        if len(sanitized) > self._max_output_chars:
            sanitized = (
                sanitized[: self._max_output_chars]
                + "... [OUTPUT TRUNCATED]"
            )

        try:
            return json.loads(sanitized)
        except (json.JSONDecodeError, TypeError):
            return sanitized

    def _post_process_output(
        self,
        raw_result: Any,
        output_schema: dict[str, Any] | None,
        duration_ms: int,
    ) -> ToolResult:
        """Common post-execution boundary: normalize, schema-validate, redact, and bound."""
        if isinstance(raw_result, ToolResult):
            success = raw_result.success
            output = raw_result.output
            error = raw_result.error
            error_cat = raw_result.error_category
        else:
            success = True
            output = raw_result
            error = None
            error_cat = None

        if success and output_schema is not None:
            schema_err = self.schema_validator.validate_output(output, output_schema)
            if schema_err:
                return ToolResult(
                    success=False,
                    error=f"Output validation failed: {schema_err}",
                    error_category="OUTPUT_SCHEMA_ERROR",
                    duration_ms=duration_ms,
                )

        if success:
            sanitized_output = self._sanitize_output(output)
            return ToolResult(
                success=True,
                output=sanitized_output,
                duration_ms=duration_ms,
            )
        else:
            sanitized_error = self._sanitize_output(error) if error else "Tool execution failed"
            return ToolResult(
                success=False,
                error=sanitized_error if isinstance(sanitized_error, str) else str(sanitized_error),
                error_category=error_cat or "EXECUTION_ERROR",
                duration_ms=duration_ms,
            )

    def route(
        self,
        request: ToolRequest,
        agent_state: Any = None,
        policy_engine: Any = None,
    ) -> ToolResult:
        """Execute the standardized tool routing and authorization pipeline."""
        start_time = time.perf_counter()

        if not isinstance(request, ToolRequest):
            return ToolResult(
                success=False,
                error="Invalid tool request",
                error_category="INVALID_REQUEST",
            )

        # 1. Lookup tool definition
        entry = self.registry.get_entry(request.tool_name, version=request.version)
        definition = entry.definition if entry else self._tools.get(request.tool_name)

        if definition is None:
            return ToolResult(
                success=False,
                error=f"Unknown tool: {request.tool_name}",
                error_category="NOT_FOUND_ERROR",
            )

        if entry and not entry.enabled:
            return ToolResult(
                success=False,
                error=f"Tool is disabled: {request.tool_name}",
                error_category="DISABLED_ERROR",
            )

        # 2. Input Schema Validation
        schema = definition.input_schema or getattr(definition, "parameters", {})
        validation_error = self._validate_arguments(request.arguments, schema)
        if validation_error:
            return ToolResult(
                success=False,
                error=validation_error,
                error_category="SCHEMA_VALIDATION_ERROR",
            )

        # 3. Rate Limiting Check (Must never reach handler if rate limited)
        task_id = (
            agent_state.get("task_id")
            if isinstance(agent_state, dict)
            else getattr(agent_state, "task_id", None)
        )
        user_id = (
            agent_state.get("user_id")
            if isinstance(agent_state, dict)
            else getattr(agent_state, "user_id", None)
        )
        rate_decision = self.rate_limiter.check(
            tool_name=request.tool_name,
            rate_limit=definition.rate_limit,
            task_id=task_id,
            user_id=user_id,
            provider_id=definition.source,
        )
        if not rate_decision.allowed:
            return ToolResult(
                success=False,
                error=rate_decision.reason or "Rate limit exceeded",
                error_category="RATE_LIMIT_ERROR",
                rate_limited=True,
            )

        # 4. Handler Retrieval
        handler = self._handlers.get(request.tool_name)
        if handler is None and entry and entry.handler:
            handler = entry.handler

        # 5. Policy & Command Validation (if not internally policy guarded)
        is_policy_guarded = handler is not None and getattr(handler, "_is_policy_guarded", False) is True

        if not is_policy_guarded:
            command_err = self._validate_command(request.tool_name, request.arguments)
            if command_err:
                return ToolResult(
                    success=False,
                    error=command_err,
                    error_category="POLICY_ERROR",
                )

            if policy_engine is not None and self._policy_engine is None:
                self._policy_engine = policy_engine

            auth_err = self._authorize(request, agent_state)
            if auth_err:
                return ToolResult(
                    success=False,
                    error=auth_err,
                    error_category="POLICY_ERROR",
                )

        if handler is None and (not entry or not entry.adapter):
            return ToolResult(
                success=False,
                error=(
                    "Tool execution is not enabled until policy checks "
                    "and argument validation are integrated."
                ),
                error_category="NOT_FOUND_ERROR",
            )

        # 6. Execute Handler (Strict signature inspection — no TypeError retry)
        def _invoke_handler() -> Any:
            if entry and entry.adapter:
                return entry.adapter.execute(definition, request.arguments, agent_state)

            assert handler is not None
            sig = inspect.signature(handler)
            params = list(sig.parameters.values())

            # Check if handler expects (request, context/agent_state)
            is_req_ctx = (
                is_policy_guarded
                or (params and params[0].name in ("request", "req", "tool_request"))
                or (len(params) == 2 and not any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params))
            )

            if is_req_ctx:
                return handler(request, agent_state)
            return handler(**request.arguments)

        sse_uid = str(user_id or "system")
        sse_tid = str(task_id or "task-default")
        try:
            from app.services.sse_redis_streams import emit_sse_event_nonblocking, publish_tool_progress
            emit_sse_event_nonblocking(
                publish_tool_progress(
                    user_id=sse_uid,
                    channel="platform_events",
                    task_id=sse_tid,
                    call_id=f"{request.tool_name}-{int(start_time * 1000)}",
                    tool_name=request.tool_name,
                    stage="started",
                    progress_pct=0.0,
                )
            )
        except Exception:
            pass

        try:
            from app.observability.agent import trace_tool_invocation
            tracer_ctx = trace_tool_invocation(
                tool_name=request.tool_name,
                task_id=task_id,
                metadata={"source": getattr(definition, "source", "unknown") if definition else "unknown"},
            )
        except Exception:
            tracer_ctx = contextlib.nullcontext()

        try:
            with tracer_ctx:
                timeout_s = getattr(definition, "timeout_s", 60.0)
                # Enforce execution timeout via ThreadPoolExecutor when configured
                if timeout_s and timeout_s > 0:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(_invoke_handler)
                        try:
                            raw_result = future.result(timeout=timeout_s)
                        except concurrent.futures.TimeoutError:
                            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
                            return ToolResult(
                                success=False,
                                error=f"Tool execution timed out after {timeout_s}s",
                                error_category="TIMEOUT_ERROR",
                                duration_ms=elapsed_ms,
                                timed_out=True,
                            )
                else:
                    raw_result = _invoke_handler()

                elapsed_ms = int((time.perf_counter() - start_time) * 1000)

                # 7. Common Output Boundary
                final_res = self._post_process_output(
                    raw_result=raw_result,
                    output_schema=definition.output_schema,
                    duration_ms=elapsed_ms,
                )
                try:
                    from app.services.sse_redis_streams import emit_sse_event_nonblocking, publish_tool_progress
                    emit_sse_event_nonblocking(
                        publish_tool_progress(
                            user_id=sse_uid,
                            channel="platform_events",
                            task_id=sse_tid,
                            call_id=f"{request.tool_name}-{int(start_time * 1000)}",
                            tool_name=request.tool_name,
                            stage="completed" if final_res.success else "failed",
                            progress_pct=100.0 if final_res.success else None,
                            message=final_res.error,
                        )
                    )
                except Exception:
                    pass
                return final_res

        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error("Tool execution failed for '%s': %s", request.tool_name, exc, exc_info=True)
            return ToolResult(
                success=False,
                error="Tool execution failed",
                error_category="EXECUTION_ERROR",
                duration_ms=elapsed_ms,
            )
