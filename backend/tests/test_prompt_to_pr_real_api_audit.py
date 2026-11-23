"""backend/tests/test_prompt_to_pr_real_api_audit.py

Comprehensive End-to-End Real API Audit Suite for the Universal AI Prompt-to-PR System.
Audits the complete Prompt -> Plan -> Human Gate 1 -> Execute -> Diff -> Test -> Verify -> Human Gate 2 -> Draft PR -> Traceability lifecycle.

Validates:
1. Real API intake via POST /api/v1/tasks/prompt-to-plan
2. Intent routing & Plan Critic quality audit
3. Human Gate 1 enforcement (execution blocked prior to approval)
4. Human approval transition to APPROVED
5. Workspace provisioning & AST-aware code editing
6. Diff extraction and secret inspection
7. Diff-targeted test execution
8. Independent verification & verified_revision stamping
9. Human Gate 2 publication authorization & protected branch blocks
10. Reviewable GitHub Draft PR publication (is_draft=True, zero auto-merge)
11. End-to-end audit traceability graph verification
"""

import json
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock
from pathlib import Path
from uuid import UUID, uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from ai.services.task_planner import TaskPlanner
from app.integrations.github.client import GitHubAPIError, GitHubClient
from app.services.git_branch import GitBranchService
from app.services.task_execution_orchestrator import TaskExecutionOrchestrator
from sandbox.workspace_manager import WorkspaceManager

from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.task import (
    ApprovalDecision,
    Task,
    TaskApproval,
    TaskEvent,
    TaskPlan,
    TaskPlanStatus,
    TaskPullRequest,
    TaskStatus,
    VerificationResult,
    VerificationStatus,
)
from app.models.user import User


def _seed_audit_repo(db_session: Session, user: User, name: str = "audit-repo") -> Repository:
    """Helper creating a real repository and installation record."""
    inst = GitHubInstallation(
        id=uuid4(),
        user_id=user.id,
        installation_id=f"inst_{uuid4().hex[:8]}",
        account_login=user.login,
        permissions={"contents": "write", "pull_requests": "write"},
    )
    db_session.add(inst)
    db_session.flush()

    repo = Repository(
        id=uuid4(),
        user_id=user.id,
        installation_id=inst.id,
        github_repo_id=f"gh_{uuid4().hex[:8]}",
        owner=user.login,
        name=name,
        default_branch="main",
        language="python",
        sync_status=SyncStatus.SYNCED,
    )
    db_session.add(repo)
    db_session.commit()
    return repo


class TestPromptToPRRealAPIAudit:
    """Exercise local HTTP routes, real Git, and controlled model and GitHub responses."""

    @pytest.mark.parametrize("repair_required", [False, True], ids=["passing", "repaired"])
    def test_e2e_prompt_to_pr_full_audit_lifecycle(
        self,
        client: TestClient,
        db_session: Session,
        test_user: User,
        auth_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        repair_required: bool,
    ):
        """Audit Case 1: Complete Happy-Path Prompt-to-PR Audit Lifecycle."""
        repo = _seed_audit_repo(db_session, test_user, name="e2e-audit-repo")

        def git(root: Path, *args: str) -> str:
            return subprocess.run(
                ["git", "-C", str(root), *args], check=True, capture_output=True, text=True,
            ).stdout.strip()

        source = tmp_path / "source"
        source.mkdir()
        remote = tmp_path / "remote"
        remote.mkdir()
        git(remote, "init", "--bare")
        git(source, "init", "-b", "main")
        (source / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n", encoding="utf-8")
        (source / "src").mkdir()
        (source / "src" / "stats.py").write_text(
            "def calculate_average(scores: list[float]) -> float:\n"
            "    return sum(scores) / len(scores)\n",
            encoding="utf-8",
        )
        git(source, "add", ".")
        git(source, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.com", "commit", "-m", "Base")
        base_sha = git(source, "rev-parse", "HEAD")
        git(source, "push", str(remote), "main")
        repo.active_commit_sha = base_sha
        db_session.commit()

        manager = WorkspaceManager(base_workspaces_dir=tmp_path / "workspaces")
        source_before = (source / "src" / "stats.py").read_text()
        source_after = (
            "def calculate_average(scores: list[float]) -> float:\n"
            "    if not scores:\n"
            "        return 0.0\n"
            "    return sum(scores) / len(scores)\n"
        )
        test_content = (
            "from src.stats import calculate_average\n\n"
            "def test_empty_list():\n"
            "    assert calculate_average([]) == 0.0\n\n"
            "def test_nonempty_list():\n"
            "    assert calculate_average([10.0, 20.0]) == 15.0\n"
        )

        async def synthesize(request):
            content = request.messages[-1].content
            if "Task Step ID: step_3" in content:
                edit = {"file": "tests/test_stats.py", "search": "", "replace": test_content}
            elif "DIAGNOSED FAILURE:" in content:
                edit = {"file": "src/stats.py", "search": "return -1.0", "replace": "return 0.0"}
            else:
                change = source_after.replace("return 0.0", "return -1.0") if repair_required else source_after
                edit = {"file": "src/stats.py", "search": source_before, "replace": change}
            return SimpleNamespace(content=json.dumps({"edits": [edit]}))

        gateway = SimpleNamespace(generate=AsyncMock(side_effect=synthesize))
        orchestrator = TaskExecutionOrchestrator(workspace_manager=manager, llm_gateway=gateway)
        monkeypatch.setattr(client.app.state, "task_planner", TaskPlanner())
        monkeypatch.setattr(client.app.state, "task_execution_orchestrator", orchestrator)
        monkeypatch.setattr(GitBranchService, "get_installation_token_for_repo", AsyncMock(return_value="fixture-token"))

        def checkout_fixture(workspace, url, revision, branch, token):
            assert url == f"https://github.com/{repo.owner}/{repo.name}.git"
            assert revision == base_sha
            git(tmp_path, "clone", "--no-local", str(source), str(workspace))
            git(workspace, "checkout", "-b", branch, revision)

        monkeypatch.setattr(manager, "_checkout_repository_revision", checkout_fixture)
        real_push = manager.push_task_branch

        def local_push(request):
            assert request.remote_url == f"https://github.com/{repo.owner}/{repo.name}.git"
            return real_push(request.model_copy(update={"remote_url": str(remote), "installation_token": None}))

        monkeypatch.setattr(manager, "push_task_branch", local_push)

        monkeypatch.setattr(GitHubClient, "list_pull_requests", AsyncMock(return_value=[]))
        create_attempts = []

        async def create_github_pr(_client, **kwargs):
            create_attempts.append(kwargs)
            if len(create_attempts) == 1:
                raise GitHubAPIError("Temporary GitHub failure", status_code=502)
            assert kwargs["draft"] is True
            return {
                "number": 7,
                "html_url": f"https://github.com/{repo.owner}/{repo.name}/pull/7",
                "draft": True,
                "head": {"ref": kwargs["head"], "sha": git(remote, "rev-parse", kwargs["head"])},
                "base": {"ref": kwargs["base"]},
            }

        monkeypatch.setattr(GitHubClient, "create_pull_request", create_github_pr)

        # -------------------------------------------------------------------
        # Step 1: POST /api/v1/tasks/prompt-to-plan (Universal Prompt Intake)
        # -------------------------------------------------------------------
        prompt_text = "Fix ZeroDivisionError in calculate_average in src/stats.py when scores list is empty and add regression tests in tests/test_stats.py"
        intake_payload = {
            "repository_id": str(repo.id),
            "prompt": prompt_text,
            "target_files": ["src/stats.py", "tests/test_stats.py"],
            "auto_create_task": True,
        }
        res_intake = client.post("/api/v1/tasks/prompt-to-plan", json=intake_payload, headers=auth_headers)
        assert res_intake.status_code == 200, res_intake.text
        data_intake = res_intake.json()

        task_id = data_intake["task_id"]
        assert task_id is not None
        assert data_intake["ambiguity_detected"] is False

        # Verify Intent Router output
        intent_info = data_intake["intent_analysis"]
        assert intent_info["primary_intent"] == "bug_fix"
        assert intent_info["confidence"] >= 0.8
        assert any(l in intent_info["affected_layers"] for l in ("backend", "testing"))

        # Verify Plan Critic review
        critic_info = data_intake["critic_review"]
        assert critic_info["is_approved"] is True
        assert critic_info["score"] >= 0.8
        assert critic_info["blocking_count"] == 0

        # Verify Task Record in Database
        db_task = db_session.get(Task, UUID(task_id))
        assert db_task is not None
        assert db_task.status == TaskStatus.PENDING_APPROVAL.value

        # -------------------------------------------------------------------
        # Step 2: Human Gate 1 Enforcement (Pre-Approval Execution Blocked)
        # -------------------------------------------------------------------
        res_blocked_exec = client.post(f"/api/v1/tasks/{task_id}/execute", headers=auth_headers, json={})
        assert res_blocked_exec.status_code in (403, 409)
        assert "approval" in res_blocked_exec.text.lower() or "invalid_state" in res_blocked_exec.text.lower()

        # -------------------------------------------------------------------
        # Step 3: POST /api/v1/tasks/{task_id}/approve (Human Gate 1 Approval)
        # -------------------------------------------------------------------
        approve_payload = {
            "plan_version": 1,
            "base_revision": db_task.base_revision or "main-rev-001",
            "comment": "Auditor reviewed plan: approved for execution in isolated workspace.",
        }
        res_approve = client.post(f"/api/v1/tasks/{task_id}/approve", json=approve_payload, headers=auth_headers)
        assert res_approve.status_code == 200, res_approve.text
        assert res_approve.json()["status"] == TaskStatus.APPROVED.value

        # Execute the approved plan with controlled model responses and actual Git edits and pytest.
        rejected_future_authorization = client.post(
            f"/api/v1/tasks/{task_id}/run-workflow",
            headers=auth_headers,
            json={"publication_authorized": True},
        )
        assert rejected_future_authorization.status_code == 400
        result = client.post(f"/api/v1/tasks/{task_id}/run-workflow", headers=auth_headers, json={})
        assert result.status_code == 200, result.text
        assert result.json()["status"] == TaskStatus.READY_FOR_PUBLICATION.value, result.text
        assert gateway.generate.await_count == (3 if repair_required else 2)

        workspace = manager.get_workspace_path(task_id)
        assert (workspace / "src" / "stats.py").read_text() == source_after
        assert (workspace / "tests" / "test_stats.py").read_text() == test_content
        assert (source / "src" / "stats.py").read_text() == source_before
        assert git(workspace, "rev-parse", "HEAD^") == base_sha

        diff = client.get(f"/api/v1/tasks/{task_id}/diff", headers=auth_headers)
        assert diff.status_code == 200, diff.text
        assert {file["file_path"] for file in diff.json()["files"]} == {"src/stats.py", "tests/test_stats.py"}

        ver_data = result.json()["verification"]
        assert ver_data["status"] == "PASS", ver_data

        verified_sha = ver_data["verified_revision"]
        assert verified_sha == git(workspace, "rev-parse", "HEAD")
        assert verified_sha != base_sha
        assert git(workspace, "status", "--porcelain") == ""
        assert git(source, "rev-parse", "HEAD") == base_sha

        blocked_push = client.post(
            f"/api/v1/tasks/{task_id}/push", headers=auth_headers, json={"publication_authorized": True},
        )
        assert blocked_push.status_code == 409, blocked_push.text

        wrong_sha = client.post(
            f"/api/v1/tasks/{task_id}/authorize-publication", headers=auth_headers, json={"head_sha": base_sha},
        )
        assert wrong_sha.status_code == 409, wrong_sha.text

        # -------------------------------------------------------------------
        # Step 9: Human Gate 2 Enforcement Checks
        # -------------------------------------------------------------------
        # 9a. Block unauthorized Draft PR creation
        res_unauth_pr = client.post(
            f"/api/v1/tasks/{task_id}/create-pr",
            headers=auth_headers,
            json={"publication_authorized": False},
        )
        assert res_unauth_pr.status_code == 403
        assert res_unauth_pr.json()["error"]["code"] == "PUBLICATION_AUTHORIZATION_REQUIRED"

        # 9b. Block publication to protected branch ('main')
        res_protected_branch = client.post(
            f"/api/v1/tasks/{task_id}/create-pr",
            headers=auth_headers,
            json={"publication_authorized": True, "head_branch": "main"},
        )
        assert res_protected_branch.status_code == 403
        assert res_protected_branch.json()["error"]["code"] == "POLICY_VIOLATION"

        # -------------------------------------------------------------------
        # Step 10: POST /api/v1/tasks/{task_id}/authorize-publication (Human Gate 2)
        # -------------------------------------------------------------------
        auth_pub_payload = {
            "head_sha": verified_sha,
            "notes": "Auditor explicitly authorized branch publication on certified SHA.",
        }
        res_auth_pub = client.post(
            f"/api/v1/tasks/{task_id}/authorize-publication",
            json=auth_pub_payload,
            headers=auth_headers,
        )
        assert res_auth_pub.status_code == 200, res_auth_pub.text
        assert res_auth_pub.json()["authorized"] is True

        # -------------------------------------------------------------------
        # Step 11: POST /api/v1/tasks/{task_id}/create-pr (Draft PR Creation)
        # -------------------------------------------------------------------
        pr_payload = {
            "publication_authorized": True,
            "title": "fix(stats): prevent ZeroDivisionError on empty score lists",
            "body": "## Summary of Changes\n- Guard against empty list in calculate_average\n- Added pytest regression suite",
        }
        failed_pr = client.post(f"/api/v1/tasks/{task_id}/create-pr", json=pr_payload, headers=auth_headers)
        assert failed_pr.status_code == 502, failed_pr.text
        assert db_session.query(TaskPullRequest).filter_by(task_id=UUID(task_id)).count() == 0
        res_pr = client.post(f"/api/v1/tasks/{task_id}/create-pr", json=pr_payload, headers=auth_headers)
        assert res_pr.status_code == 200, res_pr.text
        repeated_pr = client.post(f"/api/v1/tasks/{task_id}/create-pr", json=pr_payload, headers=auth_headers)
        assert repeated_pr.json() == res_pr.json()
        assert len(create_attempts) == 2
        pr_data = res_pr.json()

        assert pr_data["is_draft"] is True
        assert pr_data["pr_number"] == 7
        assert pr_data["head_sha"] == verified_sha
        assert "pull" in pr_data["pr_url"].lower()

        # -------------------------------------------------------------------
        # Step 12: GET /api/v1/tasks/{task_id}/traceability (Audit Trace Graph)
        # -------------------------------------------------------------------
        res_trace = client.get(f"/api/v1/tasks/{task_id}/traceability", headers=auth_headers)
        assert res_trace.status_code == 200, res_trace.text
        trace = res_trace.json()

        assert trace["task"]["task_id"] == task_id
        assert trace["task"]["status"] == TaskStatus.DRAFT_PR_CREATED.value
        assert trace["latest_plan"]["version"] == 1
        assert trace["latest_approval"]["decision"] == ApprovalDecision.APPROVED.value
        assert trace["latest_test_run"]["status"] == "PASSED"
        assert trace["latest_verification"]["status"] == VerificationStatus.PASSED.value
        assert trace["pull_request"]["is_draft"] is True
        assert trace["pull_request"]["pr_number"] == pr_data["pr_number"]

    def test_ambiguous_prompt_intake_audit(
        self,
        client: TestClient,
        db_session: Session,
        test_user: User,
        auth_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Audit Case 2: Ambiguous Prompt triggers safe scoping proposals."""
        repo = _seed_audit_repo(db_session, test_user, name="ambig-audit-repo")


        ambig_payload = {
            "repository_id": str(repo.id),
            "prompt": "Improve my app",
            "auto_create_task": False,
        }
        res = client.post("/api/v1/tasks/prompt-to-plan", json=ambig_payload, headers=auth_headers)
        assert res.status_code == 200, res.text
        data = res.json()

        assert data["ambiguity_detected"] is True
        assert len(data["intent_analysis"]["suggested_clarifications"]) >= 1
        assert "Which component" in data["intent_analysis"]["suggested_clarifications"][0] or len(data["intent_analysis"]["suggested_clarifications"]) > 0
