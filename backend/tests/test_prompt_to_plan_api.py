"""backend/tests/test_prompt_to_plan_api.py

Integration test for POST /api/v1/tasks/prompt-to-plan:
Universal natural-language intake -> Intent routing -> Plan generation -> PlanCritic audit.
"""

from __future__ import annotations

import uuid
import pytest
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.task import AgentTask, TaskStatus


def _seed_repo(db_session, user_id, name="test-repo", lang="python"):
    inst = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=user_id,
        installation_id=f"inst_{uuid.uuid4().hex[:8]}",
        account_login="testuser",
        permissions={"contents": "write", "pull_requests": "write"},
    )
    db_session.add(inst)
    db_session.flush()

    repo = Repository(
        id=uuid.uuid4(),
        user_id=user_id,
        installation_id=inst.id,
        github_repo_id=f"gh_{uuid.uuid4().hex[:8]}",
        owner="testuser",
        name=name,
        default_branch="main",
        language=lang,
        sync_status=SyncStatus.SYNCED,
    )
    db_session.add(repo)
    db_session.commit()
    return repo


def test_prompt_to_plan_happy_path(client, db_session, test_user, auth_headers):
    repo = _seed_repo(db_session, test_user.id, name="test-repo-happy", lang="python")

    payload = {
        "repository_id": str(repo.id),
        "prompt": "Fix critical SQL injection vulnerability in src/profile.py and add regression tests",
        "auto_create_task": True,
    }

    resp = client.post(
        "/api/v1/tasks/prompt-to-plan",
        json=payload,
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["task_id"] is not None
    assert data["repository_id"] == str(repo.id)
    assert data["ambiguity_detected"] is False

    # Check intent analysis
    intent = data["intent_analysis"]
    assert intent["primary_intent"] in ("security_fix", "bug_fix")
    assert "security" in intent["affected_layers"]

    # Check plan
    plan = data["plan"]
    assert len(plan["steps"]) >= 1

    # Check critic review
    critic = data["critic_review"]
    assert "is_approved" in critic
    assert critic["score"] >= 0.70


def test_prompt_to_plan_detects_ambiguity(client, db_session, test_user, auth_headers):
    repo = _seed_repo(db_session, test_user.id, name="test-repo-ambig", lang="typescript")

    payload = {
        "repository_id": str(repo.id),
        "prompt": "make it better",
        "auto_create_task": True,
    }

    resp = client.post(
        "/api/v1/tasks/prompt-to-plan",
        json=payload,
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["task_id"] is None
    assert data["ambiguity_detected"] is True
    assert len(data["clarifications"]) > 0


def test_regenerate_branch_plan_uses_last_indexed_commit(client, db_session, test_user, auth_headers):
    repo = _seed_repo(db_session, test_user.id)
    response = client.post(
        "/api/v1/tasks/prompt-to-plan",
        json={"repository_id": str(repo.id), "prompt": "Generate unit tests for validation services", "auto_create_task": True},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    task_id = response.json()["task_id"]
    revision = "a" * 40
    repo.last_indexed_commit_sha = revision
    db_session.commit()

    response = client.post(f"/api/v1/tasks/{task_id}/plan", json={}, headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["base_revision"] == revision
    assert response.json()["plan_version"] == 2
