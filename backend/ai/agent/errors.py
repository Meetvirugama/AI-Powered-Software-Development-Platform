"""
Standardized Exception Hierarchy for Agentic Repository Chat.
(Phase 2 / Issue #188).
"""

from __future__ import annotations


class AgentException(Exception):
    """Base exception for all agent subsystem errors."""

    def __init__(self, message: str, code: str = "AGENT_ERROR", status_code: int = 500) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class AgentBudgetExceeded(AgentException):
    """Raised when an agent execution budget (tokens, rounds, time) is exhausted."""

    def __init__(self, message: str = "Agent execution budget exceeded.") -> None:
        super().__init__(message, code="AGENT_BUDGET_EXCEEDED", status_code=429)


class AgentMaxRoundsExceeded(AgentException):
    """Raised when the agent reaches the maximum permitted investigation rounds."""

    def __init__(self, message: str = "Agent maximum investigation rounds exceeded.") -> None:
        super().__init__(message, code="AGENT_MAX_ROUNDS_EXCEEDED", status_code=429)


class AgentToolNotFound(AgentException):
    """Raised when the model requests an unregistered or disallowed tool."""

    def __init__(self, tool_name: str) -> None:
        super().__init__(f"Tool '{tool_name}' is not registered or allowed.", code="AGENT_TOOL_NOT_FOUND", status_code=400)
        self.tool_name = tool_name


class AgentToolValidationError(AgentException):
    """Raised when tool arguments fail security or structural validation."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="AGENT_TOOL_VALIDATION_ERROR", status_code=400)


class AgentToolExecutionError(AgentException):
    """Raised when a tool encounters an unhandled runtime error."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="AGENT_TOOL_EXECUTION_ERROR", status_code=500)


class AgentRepositoryAccessDenied(AgentException):
    """Raised when repository ownership or access verification fails."""

    def __init__(self, message: str = "Repository access denied.") -> None:
        super().__init__(message, code="AGENT_REPOSITORY_ACCESS_DENIED", status_code=403)


class AgentProviderUnavailable(AgentException):
    """Raised when LLM providers are unreachable during agent execution."""

    def __init__(self, message: str = "LLM provider unavailable for agent execution.") -> None:
        super().__init__(message, code="AGENT_PROVIDER_UNAVAILABLE", status_code=503)


class AgentExecutionTimeout(AgentException):
    """Raised when total agent execution exceeds the configured deadline."""

    def __init__(self, message: str = "Agent execution deadline exceeded.") -> None:
        super().__init__(message, code="AGENT_EXECUTION_TIMEOUT", status_code=504)


class AgentInvalidToolCall(AgentException):
    """Raised when the model emits a malformed tool call."""

    def __init__(self, message: str = "Malformed or uninterpretable tool call.") -> None:
        super().__init__(message, code="AGENT_INVALID_TOOL_CALL", status_code=400)
