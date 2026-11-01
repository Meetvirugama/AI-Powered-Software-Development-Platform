
"""Tests for policy-enforced agent tool routing."""

from enum import Enum

import pytest

from backend.agent.tools.router import (
    ToolDefinition,
    ToolRequest,
    ToolRouter,
)


class Decision(Enum):
    ALLOW = "ALLOW"
    ASK = "ASK"
    DENY = "DENY"


class MockPolicyEngine:
    def __init__(self, decision=Decision.ALLOW, should_raise=False):
        self.decision = decision
        self.should_raise = should_raise
        self.calls = []

    def check(self, tool, agent_state, context):
        self.calls.append((tool, agent_state, context))
        if self.should_raise:
            raise RuntimeError("Policy service unavailable")
        return self.decision


def make_router(
    decision=Decision.ALLOW,
    should_raise=False,
    command_allowlist=None,
):
    policy = MockPolicyEngine(decision, should_raise)
    context_factory = lambda state, request: {
        "task_id": "test-task",
        "tool": request.tool_name,
    }

    router = ToolRouter(
        policy_engine=policy,
        policy_context_factory=context_factory,
        command_allowlist=command_allowlist,
    )

    executed = []

    def handler(**kwargs):
        executed.append(kwargs)
        return {"message": "success", "arguments": kwargs}

    router.register(
        ToolDefinition(
            name="read_file",
            description="Read a file",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        ),
        handler,
    )

    return router, policy, executed


def test_unknown_tool_is_rejected():
    router, _, executed = make_router()

    result = router.route(
        ToolRequest("unknown_tool", {}),
        agent_state={},
    )

    assert result.success is False
    assert "Unknown tool" in result.error
    assert executed == []


def test_missing_required_argument_is_rejected():
    router, _, executed = make_router()

    result = router.route(
        ToolRequest("read_file", {}),
        agent_state={},
    )

    assert result.success is False
    assert "Missing required argument" in result.error
    assert executed == []


def test_wrong_argument_type_is_rejected():
    router, _, executed = make_router()

    result = router.route(
        ToolRequest("read_file", {"path": 123}),
        agent_state={},
    )

    assert result.success is False
    assert "invalid type" in result.error or "must be of type" in result.error
    assert executed == []


def test_unexpected_argument_is_rejected():
    router, _, executed = make_router()

    result = router.route(
        ToolRequest(
            "read_file",
            {"path": "README.md", "extra": True},
        ),
        agent_state={},
    )

    assert result.success is False
    assert "Unexpected argument" in result.error
    assert executed == []


def test_missing_policy_engine_fails_closed():
    router = ToolRouter()
    executed = []

    router.register(
        ToolDefinition("read_file", "Read a file", {"type": "object"}),
        lambda **kwargs: executed.append(kwargs),
    )

    result = router.route(
        ToolRequest("read_file", {}),
        agent_state={},
    )

    assert result.success is False
    assert "Policy engine unavailable" in result.error
    assert executed == []


def test_missing_policy_context_factory_fails_closed():
    policy = MockPolicyEngine()
    router = ToolRouter(policy_engine=policy)
    executed = []

    router.register(
        ToolDefinition("read_file", "Read a file", {"type": "object"}),
        lambda **kwargs: executed.append(kwargs),
    )

    result = router.route(
        ToolRequest("read_file", {}),
        agent_state={},
    )

    assert result.success is False
    assert "Policy context unavailable" in result.error
    assert executed == []
    assert policy.calls == []


def test_policy_allow_executes_handler():
    router, policy, executed = make_router()

    result = router.route(
        ToolRequest("read_file", {"path": "README.md"}),
        agent_state={"user": "test"},
    )

    assert result.success is True
    assert result.output["message"] == "success"
    assert len(executed) == 1
    assert len(policy.calls) == 1
    assert policy.calls[0][0] == "read_file"


@pytest.mark.parametrize("decision", [Decision.ASK, Decision.DENY])
def test_ask_and_deny_never_execute_handler(decision):
    router, policy, executed = make_router(decision=decision)

    result = router.route(
        ToolRequest("read_file", {"path": "README.md"}),
        agent_state={},
    )

    assert result.success is False
    assert "Policy denied" in result.error
    assert executed == []
    assert len(policy.calls) == 1


def test_policy_exception_fails_closed():
    router, policy, executed = make_router(should_raise=True)

    result = router.route(
        ToolRequest("read_file", {"path": "README.md"}),
        agent_state={},
    )

    assert result.success is False
    assert "Policy evaluation failed" in result.error
    assert executed == []
    assert len(policy.calls) == 1


def test_invalid_arguments_are_rejected_before_policy_check():
    router, policy, executed = make_router()

    result = router.route(
        ToolRequest("read_file", {}),
        agent_state={},
    )

    assert result.success is False
    assert policy.calls == []
    assert executed == []


def test_unapproved_command_is_rejected():
    router, policy, executed = make_router(
        command_allowlist={
            "read_file": [["pytest", "-q"]],
        }
    )

    result = router.route(
        ToolRequest(
            "read_file",
            {"path": "README.md", "argv": ["python", "malicious.py"]},
        ),
        agent_state={},
    )

    assert result.success is False
    assert "Unexpected argument" in result.error
    assert executed == []
    assert policy.calls == []


def test_shell_command_string_is_rejected():
    router, _, executed = make_router()

    result = router.route(
        ToolRequest(
            "read_file",
            {"path": "README.md", "command": "rm -rf /"},
        ),
        agent_state={},
    )

    assert result.success is False
    assert "Unexpected argument" in result.error
    assert executed == []


def test_approved_argv_passes_command_allowlist():
    policy = MockPolicyEngine()
    executed = []

    router = ToolRouter(
        policy_engine=policy,
        policy_context_factory=lambda state, request: {"task": "test"},
        command_allowlist={
            "run_test": [["pytest", "-q"]],
        },
    )

    router.register(
        ToolDefinition(
            "run_test",
            "Run approved tests",
            {
                "type": "object",
                "properties": {
                    "argv": {
                        "type": "array",
                        "items": {"type": "string"},
                    }
                },
                "required": ["argv"],
                "additionalProperties": False,
            },
        ),
        lambda **kwargs: executed.append(kwargs) or "passed",
    )

    result = router.route(
        ToolRequest("run_test", {"argv": ["pytest", "-q"]}),
        agent_state={},
    )

    assert result.success is True
    assert executed == [{"argv": ["pytest", "-q"]}]


def test_unapproved_argv_never_executes():
    policy = MockPolicyEngine()
    executed = []

    router = ToolRouter(
        policy_engine=policy,
        policy_context_factory=lambda state, request: {"task": "test"},
        command_allowlist={
            "run_test": [["pytest", "-q"]],
        },
    )

    router.register(
        ToolDefinition(
            "run_test",
            "Run approved tests",
            {
                "type": "object",
                "properties": {
                    "argv": {
                        "type": "array",
                        "items": {"type": "string"},
                    }
                },
                "required": ["argv"],
                "additionalProperties": False,
            },
        ),
        lambda **kwargs: executed.append(kwargs),
    )

    result = router.route(
        ToolRequest("run_test", {"argv": ["pytest", "malicious.py"]}),
        agent_state={},
    )

    assert result.success is False
    assert "not in the approved command allowlist" in result.error
    assert executed == []
    assert policy.calls == []


def test_tool_output_is_truncated():
    router, _, _ = make_router()
    router._max_output_chars = 30

    result = router.route(
        ToolRequest("read_file", {"path": "README.md"}),
        agent_state={},
    )

    assert result.success is True
    assert len(str(result.output)) <= 80
    assert "OUTPUT TRUNCATED" in str(result.output)


def test_tool_output_secrets_are_redacted():
    router, _, _ = make_router()

    router._handlers["read_file"] = lambda **kwargs: {
        "api_key": "supersecret123",
        "message": "safe",
    }

    result = router.route(
        ToolRequest("read_file", {"path": "README.md"}),
        agent_state={},
    )

    assert result.success is True
    assert "supersecret123" not in str(result.output)
    assert "[REDACTED]" in str(result.output)


def test_policy_none_decision_fails_closed():
    router, _, executed = make_router()

    router._policy_engine.decision = None

    result = router.route(
        ToolRequest("read_file", {"path": "README.md"}),
        agent_state={},
    )

    assert result.success is False
    assert "no decision" in result.error
    assert executed == []
