"""backend/tests/test_code_editor_and_specialized_agents.py

Comprehensive test suite verifying Phase 3 Autonomous Code Modification Engine:
- AST-Aware pre-validation and safe patching (Python, JSON, TypeScript/JavaScript)
- Safe file deletion validator (manifests, inbound imports, CI workflows, test references)
- Specialized agent specs (Backend, Frontend, Database, Testing)
- AgentDispatcher routing by file, action type, and task intent
- WorkspaceManager AST patch integration
"""

import os
from pathlib import Path
import pytest
from uuid import uuid4

from agent.tools.code_editor import CodeEditor, SafeFileDeletionValidator
from agent.specialized.base import SpecializedAgentRole, SpecializedAgentSpec
from agent.specialized.backend_agent import create_backend_agent_spec
from agent.specialized.frontend_agent import create_frontend_agent_spec
from agent.specialized.database_agent import create_database_agent_spec
from agent.specialized.testing_agent import create_testing_agent_spec
from agent.specialized.dispatcher import AgentDispatcher
from ai.services.intent_router import TaskIntent
from sandbox.workspace_manager import WorkspaceManager
from app.schemas.workspace import WorkspaceCreateRequest


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    """Fixture creating a temporary mock repository workspace."""
    repo_dir = tmp_path / "mock_repo"
    repo_dir.mkdir()
    return repo_dir


class TestCodeEditorSyntaxValidation:
    """Tests certifying AST pre-validation for code modifications."""

    def test_valid_python_syntax(self, temp_workspace: Path):
        editor = CodeEditor(temp_workspace)
        valid_code = "def calculate(a: int, b: int) -> int:\n    return a + b\n"
        is_valid, err = editor.validate_code_syntax("service.py", valid_code)
        assert is_valid is True
        assert err is None

    def test_invalid_python_syntax_rejected(self, temp_workspace: Path):
        editor = CodeEditor(temp_workspace)
        invalid_code = "def calculate(a, b\n    return a + b"
        is_valid, err = editor.validate_code_syntax("service.py", invalid_code)
        assert is_valid is False
        assert "Python SyntaxError" in err

    def test_valid_json_syntax(self, temp_workspace: Path):
        editor = CodeEditor(temp_workspace)
        valid_json = '{"name": "demo", "version": "1.0.0"}'
        is_valid, err = editor.validate_code_syntax("config.json", valid_json)
        assert is_valid is True
        assert err is None

    def test_invalid_json_syntax_rejected(self, temp_workspace: Path):
        editor = CodeEditor(temp_workspace)
        invalid_json = '{"name": "demo", "version": }'
        is_valid, err = editor.validate_code_syntax("config.json", invalid_json)
        assert is_valid is False
        assert "JSON" in err and ("SyntaxError" in err or "decode error" in err)

    def test_valid_typescript_balanced_braces(self, temp_workspace: Path):
        editor = CodeEditor(temp_workspace)
        valid_ts = "export const Component = () => { return <div>Hello</div>; };"
        is_valid, err = editor.validate_code_syntax("Component.tsx", valid_ts)
        assert is_valid is True
        assert err is None

    def test_unbalanced_typescript_braces_rejected(self, temp_workspace: Path):
        editor = CodeEditor(temp_workspace)
        invalid_ts = "export const Component = () => { return <div>Hello</div>;"
        is_valid, err = editor.validate_code_syntax("Component.tsx", invalid_ts)
        assert is_valid is False
        assert "Unbalanced brace" in err or "delimiter" in err


class TestSafeFileDeletionValidator:
    """Tests certifying non-negotiable safe file deletion checks."""

    def test_cannot_delete_nonexistent_file(self, temp_workspace: Path):
        res = SafeFileDeletionValidator.evaluate_file_deletion(temp_workspace, "nonexistent.py")
        assert res.can_delete is False
        assert "does not exist" in res.blocking_reason

    def test_cannot_delete_project_manifests(self, temp_workspace: Path):
        manifest = temp_workspace / "pyproject.toml"
        manifest.write_text("[project]\nname = 'test'\n")
        res = SafeFileDeletionValidator.evaluate_file_deletion(temp_workspace, "pyproject.toml")
        assert res.can_delete is False
        assert "protected project manifest" in res.blocking_reason

    def test_cannot_delete_file_with_inbound_import(self, temp_workspace: Path):
        helper = temp_workspace / "helper.py"
        helper.write_text("def helper_fn():\n    return 42\n")

        consumer = temp_workspace / "consumer.py"
        consumer.write_text("from helper import helper_fn\nprint(helper_fn())\n")

        res = SafeFileDeletionValidator.evaluate_file_deletion(temp_workspace, "helper.py")
        assert res.can_delete is False
        assert "inbound import reference" in res.blocking_reason
        assert "consumer.py" in res.inbound_import_references

    def test_cannot_delete_file_referenced_in_ci(self, temp_workspace: Path):
        script = temp_workspace / "deploy_check.py"
        script.write_text("print('All good')\n")

        ci_dir = temp_workspace / ".github" / "workflows"
        ci_dir.mkdir(parents=True)
        ci_workflow = ci_dir / "build.yml"
        ci_workflow.write_text("name: CI\njobs:\n  run:\n    run: python deploy_check.py\n")

        res = SafeFileDeletionValidator.evaluate_file_deletion(temp_workspace, "deploy_check.py")
        assert res.can_delete is False
        assert "referenced in CI workflow" in res.blocking_reason

    def test_cannot_delete_file_referenced_in_tests(self, temp_workspace: Path):
        service = temp_workspace / "payment.py"
        service.write_text("def pay(): pass\n")

        test_dir = temp_workspace / "tests"
        test_dir.mkdir(parents=True)
        test_file = test_dir / "test_payment.py"
        test_file.write_text("import payment\ndef test_pay(): payment.pay()\n")

        res = SafeFileDeletionValidator.evaluate_file_deletion(temp_workspace, "payment.py")
        assert res.can_delete is False
        assert "referenced by active test suite" in res.blocking_reason

    def test_safely_delete_orphaned_file(self, temp_workspace: Path):
        orphan = temp_workspace / "orphan.py"
        orphan.write_text("def unused(): pass\n")

        res = SafeFileDeletionValidator.evaluate_file_deletion(temp_workspace, "orphan.py")
        assert res.can_delete is True
        assert res.blocking_reason is None


class TestSpecializedAgentsAndDispatcher:
    """Tests certifying specialized agent specifications and routing."""

    def test_agent_specs_invariants(self):
        be = create_backend_agent_spec()
        assert be.role == SpecializedAgentRole.BACKEND
        assert be.can_touch_file("backend/app/api/v1/tasks.py") is True
        assert be.can_touch_file(".env.production") is False

        fe = create_frontend_agent_spec()
        assert fe.role == SpecializedAgentRole.FRONTEND
        assert fe.can_touch_file("frontend/src/components/Task.tsx") is True
        assert fe.can_touch_file(".env") is False

        db = create_database_agent_spec()
        assert db.role == SpecializedAgentRole.DATABASE
        assert db.can_touch_file("backend/alembic/versions/001.py") is True
        assert db.can_touch_file("secret.key") is False

        te = create_testing_agent_spec()
        assert te.role == SpecializedAgentRole.TESTING
        assert te.can_touch_file("backend/tests/test_something.py") is True

    def test_dispatcher_routes_by_file(self):
        dispatcher = AgentDispatcher()
        assert dispatcher.dispatch_for_files(["frontend/src/App.tsx"]).role == SpecializedAgentRole.FRONTEND
        assert dispatcher.dispatch_for_files(["backend/alembic/versions/123.py"]).role == SpecializedAgentRole.DATABASE
        assert dispatcher.dispatch_for_files(["backend/tests/test_api.py"]).role == SpecializedAgentRole.TESTING
        assert dispatcher.dispatch_for_files(["backend/app/api/tasks.py"]).role == SpecializedAgentRole.BACKEND

    def test_dispatcher_routes_by_action_and_intent(self):
        dispatcher = AgentDispatcher()
        assert dispatcher.dispatch_for_step("run_tests").role == SpecializedAgentRole.TESTING
        assert dispatcher.dispatch_for_step("migrate").role == SpecializedAgentRole.DATABASE
        assert dispatcher.dispatch_for_step("edit", task_intent=TaskIntent.FRONTEND).role == SpecializedAgentRole.FRONTEND


class TestWorkspaceManagerASTIntegration:
    """Tests verifying WorkspaceManager AST validation during patch_file."""

    def test_workspace_patch_file_blocks_invalid_syntax(self, tmp_path: Path):
        wm = WorkspaceManager(base_workspaces_dir=tmp_path / "ws")
        task_id = "test-ast-patch"
        wm.create_workspace(WorkspaceCreateRequest(task_id=task_id, repository_id=str(uuid4()), base_revision="12345678"))

        # Write valid initial python file
        wm.write_file(task_id, "calc.py", "def add(x, y):\n    return x + y\n")

        # Attempt to patch with invalid syntax
        patch_res = wm.patch_file(
            task_id,
            "calc.py",
            target_content="return x + y",
            replacement_content="return x + (unclosed",
        )
        assert patch_res.success is False
        assert patch_res.ast_valid is False
        assert "AST syntax validation failed" in patch_res.error

        # Original file remains uncorrupted
        read_res = wm.read_file(task_id, "calc.py")
        assert read_res.content == "def add(x, y):\n    return x + y\n"

    def test_workspace_patch_file_succeeds_for_valid_syntax(self, tmp_path: Path):
        wm = WorkspaceManager(base_workspaces_dir=tmp_path / "ws")
        task_id = "test-ast-valid"
        wm.create_workspace(WorkspaceCreateRequest(task_id=task_id, repository_id=str(uuid4()), base_revision="12345678"))

        wm.write_file(task_id, "calc.py", "def add(x, y):\n    return x + y\n")
        patch_res = wm.patch_file(
            task_id,
            "calc.py",
            target_content="return x + y",
            replacement_content="return x + y + 1",
        )
        assert patch_res.success is True
        assert patch_res.ast_valid is True
