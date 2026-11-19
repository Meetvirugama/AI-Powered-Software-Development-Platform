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


def test_prompt_to_plan_happy_path(client, db_session, test_user, auth_headers, monkeypatch):
    repo = _seed_repo(db_session, test_user.id, name="test-repo-happy", lang="python")

    monkeypatch.setattr(
        "app.api.v1.tasks._owned_repository",
        lambda r_id, u_id, db, min_role=None: repo,
    )

    payload = {
        "repository_id": str(repo.id),
        "prompt": "Fix critical SQL injection vulnerability in user profile endpoint and add regression tests",
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


def test_prompt_to_plan_detects_ambiguity(client, db_session, test_user, auth_headers, monkeypatch):
    repo = _seed_repo(db_session, test_user.id, name="test-repo-ambig", lang="typescript")

    monkeypatch.setattr(
        "app.api.v1.tasks._owned_repository",
        lambda r_id, u_id, db, min_role=None: repo,
    )

    payload = {
        "repository_id": str(repo.id),
        "prompt": "make it better",
        "auto_create_task": False,
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
