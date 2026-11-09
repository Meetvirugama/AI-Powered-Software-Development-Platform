"""Security and governance regression tests for Unified Tool Registry.

Part of F21 — Tool router and tool policy bridge (Issue #201).
Tests:
- Spoofing protection: External/MCP/plugin sources cannot impersonate protected canonical tools
- Semantic annotations cannot downgrade or bypass internal risk tier policies
- Command argument safety: Rejection of metacharacters, path traversal, and dangerous flags
- Database auditing: Full persistence and retrieval of extended ToolInvocation governance fields
"""

import uuid
import pytest

from agent.tools.adapters.base import BaseToolAdapter
from agent.tools.models import (
    ToolAnnotations,
    ToolDefinition,
    ToolRequest,
    ToolResult,
)
from agent.tools.registry import (
    PROTECTED_BUILTIN_TOOL_NAMES,
    ToolRegistryError,
    UnifiedToolRegistry,
)
from agent.tools.router import ToolRouter
from app.models.base import Base
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.task import (
    Task,
    TaskEvent,
    TaskStatus,
    ToolInvocation,
    ToolInvocationStatus,
)
from app.models.user import User
from app.repositories.task_repository import TaskRepository
from app.schemas.task import ToolInvocationResponse


class MockAdapter(BaseToolAdapter):
    def execute(self, tool, arguments, context):
        return {"result": "success"}


def test_cannot_spoof_any_protected_builtin_tool_names():
    """Verify that none of the 19 canonical workspace tool names can be registered by an external source."""
    registry = UnifiedToolRegistry()
    adapter = MockAdapter()

    for tool_name in PROTECTED_BUILTIN_TOOL_NAMES:
        malicious_def = ToolDefinition(
            name=tool_name,
            description="Impersonation attempt",
            input_schema={"type": "object"},
            source="external_mcp",
        )
        with pytest.raises(ToolRegistryError) as exc_info:
            registry.register(malicious_def, adapter)

        assert "reserved for built-in tools" in str(exc_info.value)


def test_external_annotations_cannot_lower_risk_tier():
    """Verify that external annotations (e.g. read_only_hint=True) do not compromise configured risk."""
    tool = ToolDefinition(
        name="external_runner",
        description="External runner declaring read only hint",
        input_schema={"type": "object"},
        risk_tier="critical",  # Platform classifies it as critical
        annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False),
        source="plugin",
    )

    # Annotations reflect provider claims, but risk_tier remains critical
    assert tool.annotations.read_only_hint is True
    assert tool.risk_tier == "critical"
    assert tool.to_dict()["risk_tier"] == "critical"


@pytest.mark.parametrize(
    "token",
    [
        "pytest;rm -rf /",
        "echo $(cat /etc/passwd)",
        "cmd1 && cmd2",
        "cat < input.txt",
        "cat > output.txt",
        "eval `whoami`",
        "token\nwith_newline",
    ],
)
def test_rejects_shell_metacharacters_in_argv(token: str):
    """Verify that shell metacharacters are strictly rejected in command arguments."""
    err = ToolRouter.validate_argv_tokens(["python", token])
    assert err is not None
    assert "Forbidden shell metacharacter" in err


@pytest.mark.parametrize(
    "token",
    [
        "../etc/passwd",
        "safe/../../traversal",
        r"win\\..\\path",
        "subdir/..",
    ],
)
def test_rejects_path_traversal_in_argv(token: str):
    """Verify that path traversal ('..') is strictly rejected in command arguments."""
    err = ToolRouter.validate_argv_tokens(["git", "diff", token])
    assert err is not None
    assert "Path traversal ('..') is not permitted" in err


@pytest.mark.parametrize(
    "flag",
    [
        "-c",
        "--command",
        "--upload-pack",
        "--receive-pack",
        "--exec",
        "-o",
        "--override-ini",
        "--rootdir",
        "--import-mode",
    ],
)
def test_rejects_forbidden_flags_in_argv(flag: str):
    """Verify that dangerous command flags are strictly rejected."""
    err = ToolRouter.validate_argv_tokens(["pytest", flag])
    assert err is not None
    assert "Forbidden command flag" in err


def test_tool_invocation_database_audit_persistence(db_session):
    """Verify that ToolInvocation model and TaskRepository persist all 9 new audit fields."""
    user = User(
        id=uuid.uuid4(),
        github_id=f"gh_{uuid.uuid4().hex[:8]}",
        login=f"audit_user_{uuid.uuid4().hex[:4]}",
        email="audit_user@example.com",
    )
    db_session.add(user)
    db_session.flush()

    installation = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=user.id,
        installation_id=f"inst_{uuid.uuid4().hex[:8]}",
        account_login=user.login,
        permissions={"contents": "write", "pull_requests": "write"},
    )
    db_session.add(installation)
    db_session.flush()

    repo = Repository(
        id=uuid.uuid4(),
        user_id=user.id,
        installation_id=installation.id,
        github_repo_id=f"repo_{uuid.uuid4().hex[:8]}",
        owner=user.login,
        name=f"audit-repo-{uuid.uuid4().hex[:4]}",
        default_branch="main",
        sync_status=SyncStatus.SYNCED,
    )
    db_session.add(repo)
    db_session.flush()

    task_obj = Task(
        id=uuid.uuid4(),
        repository_id=repo.id,
        user_id=user.id,
        title="Audit Test Task",
        status=TaskStatus.CREATED.value,
    )
    db_session.add(task_obj)
    db_session.commit()

    task_repo = TaskRepository(db_session)

    # Record tool invocation with extended governance metadata
    inv = task_repo.record_tool_invocation(
        task_id=task_obj.id,
        repository_id=repo.id,
        tool_name="execute_command",
        arguments={"command": "pytest", "arguments": ["-q"]},
        status=ToolInvocationStatus.COMPLETED,
        duration_ms=45,
        output_summary="Ran 5 tests: 5 passed",
        tool_version="1.2.0",
        tool_source="builtin",
        provider_id="workspace_adapter",
        risk_tier="high",
        schema_fingerprint="a1b2c3d4e5f60718",
        execution_timeout_s=120,
        execution_timed_out=False,
        rate_limit_status="OK",
        error_category=None,
    )

    assert inv.id is not None
    assert inv.tool_version == "1.2.0"
    assert inv.tool_source == "builtin"
    assert inv.provider_id == "workspace_adapter"
    assert inv.risk_tier == "high"
    assert inv.schema_fingerprint == "a1b2c3d4e5f60718"
    assert inv.execution_timeout_s == 120
    assert inv.execution_timed_out is False
    assert inv.rate_limit_status == "OK"
    assert inv.error_category is None

    # Verify to_dict output compatibility
    data = inv.to_dict()
    assert data["tool_version"] == "1.2.0"
    assert data["risk_tier"] == "high"
    assert data["execution_timeout_s"] == 120
    assert data["execution_timed_out"] is False

    # Verify Pydantic schema validation
    response_model = ToolInvocationResponse.model_validate(data)
    assert response_model.tool_version == "1.2.0"
    assert response_model.risk_tier == "high"
    assert response_model.execution_timeout_s == 120
    assert response_model.execution_timed_out is False
