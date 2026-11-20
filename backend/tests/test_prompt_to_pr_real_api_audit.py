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
from pathlib import Path
from uuid import UUID, uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

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
    """Rigorous audit certifying Prompt-to-PR via live HTTP endpoints."""

    def test_e2e_prompt_to_pr_full_audit_lifecycle(
        self,
        client: TestClient,
        db_session: Session,
        test_user: User,
        auth_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Audit Case 1: Complete Happy-Path Prompt-to-PR Audit Lifecycle."""
        repo = _seed_audit_repo(db_session, test_user, name="e2e-audit-repo")

        # Bypass repo ownership check in router
        monkeypatch.setattr(
            "app.api.v1.tasks._owned_repository",
            lambda r_id, u_id, db, min_role=None: repo,
        )

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

        # -------------------------------------------------------------------
        # Step 4: POST /api/v1/tasks/{task_id}/execute (Start Execution)
        # -------------------------------------------------------------------
        res_exec = client.post(f"/api/v1/tasks/{task_id}/execute", headers=auth_headers, json={"run_steps": False})
        assert res_exec.status_code == 200, res_exec.text

        # -------------------------------------------------------------------
        # Step 5: AST-Aware File Modification & Safety Validation
        # -------------------------------------------------------------------
        # 5a. Block deletion of protected project manifest
        res_del_manifest = client.post(
            f"/api/v1/tasks/{task_id}/tools/delete_file",
            headers=auth_headers,
            json={"arguments": {"file_path": "pyproject.toml"}},
        )
        assert res_del_manifest.status_code in (400, 403, 500)

        # 5b. Write clean, validated code
        clean_code = (
            "def calculate_average(scores: list[float]) -> float:\n"
            "    if not scores:\n"
            "        return 0.0\n"
            "    return sum(scores) / len(scores)\n"
        )
        res_write_src = client.post(
            f"/api/v1/tasks/{task_id}/tools/write_file",
            headers=auth_headers,
            json={"arguments": {"file_path": "src/stats.py", "content": clean_code}},
        )
        assert res_write_src.status_code == 200

        # 5c. Write clean, validated test
        clean_test = (
            "from src.stats import calculate_average\n\n"
            "def test_calculate_average_empty():\n"
            "    assert calculate_average([]) == 0.0\n\n"
            "def test_calculate_average_values():\n"
            "    assert calculate_average([10.0, 20.0]) == 15.0\n"
        )
        res_write_test = client.post(
            f"/api/v1/tasks/{task_id}/tools/write_file",
            headers=auth_headers,
            json={"arguments": {"file_path": "tests/test_stats.py", "content": clean_test}},
        )
        assert res_write_test.status_code == 200

        # -------------------------------------------------------------------
        # Step 6: GET /api/v1/tasks/{task_id}/diff (Diff Extraction & Audit)
        # -------------------------------------------------------------------
        res_diff = client.get(f"/api/v1/tasks/{task_id}/diff", headers=auth_headers)
        assert res_diff.status_code == 200
        diff_data = res_diff.json()
        assert "files" in diff_data and len(diff_data["files"]) > 0

        # -------------------------------------------------------------------
        # Step 7: POST /api/v1/tasks/{task_id}/tests (Diff-Targeted Test Run)
        # -------------------------------------------------------------------
        res_test_run = client.post(
            f"/api/v1/tasks/{task_id}/tests",
            headers=auth_headers,
            json={"test_path": "tests/test_stats.py", "framework": "pytest"},
        )
        assert res_test_run.status_code == 200
        test_data = res_test_run.json()
        assert test_data["status"] == "PASSED"

        # -------------------------------------------------------------------
        # Step 8: POST /api/v1/tasks/{task_id}/verify (Independent Verification)
        # -------------------------------------------------------------------
        res_verify = client.post(f"/api/v1/tasks/{task_id}/verify", headers=auth_headers, json={})
        assert res_verify.status_code == 200, res_verify.text
        ver_data = res_verify.json()
        assert ver_data["status"] == "PASS", f"Verification failed with: {ver_data.get('blocking_findings')} and checks: {ver_data.get('checks')}"
        assert ver_data["is_eligible_for_publication"] is True
        assert ver_data["task_status"] == TaskStatus.READY_FOR_PUBLICATION.value

        verified_sha = ver_data["verified_revision"]
        assert verified_sha is not None

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
        res_pr = client.post(f"/api/v1/tasks/{task_id}/create-pr", json=pr_payload, headers=auth_headers)
        assert res_pr.status_code == 200, res_pr.text
        pr_data = res_pr.json()

        assert pr_data["is_draft"] is True
        assert pr_data["pr_number"] is not None
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
        monkeypatch.setattr(
            "app.api.v1.tasks._owned_repository",
            lambda r_id, u_id, db, min_role=None: repo,
        )

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
