"""Unit and integration tests for Project Memory Service & Automated Writers (Issue #217).

Verifies:
1. MemoryRepository CRUD operations, repository boundary enforcement, and text/type search.
2. ProjectMemoryService automated writers for task completion, task failure, and architectural rules.
3. Multi-tenant repository isolation for memory entries.
4. HTTP API endpoints for memory management and automated writers.
"""

from __future__ import annotations

import uuid
import pytest
from sqlalchemy.orm import Session

from app.models.github_installation import GitHubInstallation
from app.models.memory_entry import MemoryEntry, MemoryStatus, MemoryType
from app.models.repository import Repository, SyncStatus
from app.models.user import User
from app.repositories.memory_repository import MemoryRepository
from app.services.memory_service import ProjectMemoryService


@pytest.fixture
def memory_test_setup(db_session: Session):
    """Seed test users, installations, and isolated repositories."""
    u1 = User(
        id=uuid.uuid4(),
        github_id="gh_217_1",
        email="mem_user1@example.com",
        login="mem_user1",
        avatar_url="",
    )
    u2 = User(
        id=uuid.uuid4(),
        github_id="gh_217_2",
        email="mem_user2@example.com",
        login="mem_user2",
        avatar_url="",
    )
    db_session.add_all([u1, u2])
    db_session.flush()

    inst1 = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=u1.id,
        installation_id="217001",
        account_login=u1.login,
        permissions={},
    )
    inst2 = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=u2.id,
        installation_id="217002",
        account_login=u2.login,
        permissions={},
    )
    db_session.add_all([inst1, inst2])
    db_session.flush()

    repo1 = Repository(
        id=uuid.uuid4(),
        user_id=u1.id,
        installation_id=inst1.id,
        github_repo_id="21701",
        owner=u1.login,
        name="project-memory-alpha",
        default_branch="main",
        sync_status=SyncStatus.SYNCED,
    )
    repo2 = Repository(
        id=uuid.uuid4(),
        user_id=u2.id,
        installation_id=inst2.id,
        github_repo_id="21702",
        owner=u2.login,
        name="project-memory-beta",
        default_branch="main",
        sync_status=SyncStatus.SYNCED,
    )
    db_session.add_all([repo1, repo2])
    db_session.commit()

    return {"u1": u1, "u2": u2, "repo1": repo1, "repo2": repo2}


def test_memory_repository_crud_and_search(db_session: Session, memory_test_setup: dict):
    """Test MemoryRepository creation, retrieval, updates, deletions, and filtering."""
    repo = memory_test_setup["repo1"]
    mem_repo = MemoryRepository(db_session)

    # 1. Create entry
    entry = mem_repo.create_entry(
        repository_id=repo.id,
        type_=MemoryType.rule,
        content="Always use parameterized SQL queries to prevent SQL injection.",
        source="architectural_guideline",
        status=MemoryStatus.active,
    )
    assert entry.id is not None
    assert entry.type_ == MemoryType.rule
    assert "parameterized SQL" in entry.content

    # 2. Get by ID
    found = mem_repo.get_by_id(entry.id, repository_id=repo.id)
    assert found is not None
    assert found.id == entry.id

    # 3. Update entry
    updated = mem_repo.update_entry(
        entry.id,
        repository_id=repo.id,
        content="Always use parameterized SQL queries or ORM expressions.",
        status=MemoryStatus.active,
    )
    assert updated is not None
    assert "ORM expressions" in updated.content

    # 4. Search entries
    items, total = mem_repo.search_entries(
        repository_id=repo.id,
        query="parameterized",
        type_=MemoryType.rule,
        status=MemoryStatus.active,
    )
    assert total == 1
    assert items[0].id == entry.id

    # 5. Delete entry
    deleted = mem_repo.delete_entry(entry.id, repository_id=repo.id)
    assert deleted is True
    assert mem_repo.get_by_id(entry.id, repository_id=repo.id) is None


def test_automated_memory_writers(db_session: Session, memory_test_setup: dict):
    """Test ProjectMemoryService automated writers for task completion, failure, and rules."""
    repo = memory_test_setup["repo1"]
    service = ProjectMemoryService(db_session)
    task_id = uuid.uuid4()

    # 1. Record task completion
    completion_entry = service.record_task_completion_memory(
        repository_id=repo.id,
        task_id=task_id,
        title="Add JWT Token Revocation Blocklist",
        verification_summary="All 15 verification security tests passed in sandbox runner.",
        repair_attempts_used=1,
        files_changed=["backend/app/auth.py", "backend/app/redis.py"],
    )
    assert completion_entry.type_ == MemoryType.task_summary
    assert completion_entry.source == f"task:{task_id}"
    assert completion_entry.status == MemoryStatus.active
    assert "Add JWT Token Revocation Blocklist" in completion_entry.content
    assert "Repair attempts used: 1" in completion_entry.content
    assert "backend/app/auth.py" in completion_entry.content

    # 2. Record task failure
    fail_task_id = uuid.uuid4()
    failure_entry = service.record_task_failure_memory(
        repository_id=repo.id,
        task_id=fail_task_id,
        title="Implement distributed lock without TTL",
        failure_reason="Deadlock occurred under stress testing; missing expiration TTL.",
        repair_attempts_used=3,
    )
    assert failure_entry.type_ == MemoryType.failure
    assert failure_entry.source == f"task:{fail_task_id}"
    assert "Deadlock occurred" in failure_entry.content
    assert "Repair attempts exhausted: 3" in failure_entry.content

    # 3. Record architectural rule
    rule_entry = service.record_architectural_rule(
        repository_id=repo.id,
        rule_content="All Redis locks must specify an explicit TTL.",
        source="postmortem_review",
    )
    assert rule_entry.type_ == MemoryType.rule
    assert rule_entry.source == "postmortem_review"
    assert "explicit TTL" in rule_entry.content


def test_multi_tenant_repository_isolation(db_session: Session, memory_test_setup: dict):
    """Ensure memories created in repo1 are never visible or accessible in repo2."""
    repo1 = memory_test_setup["repo1"]
    repo2 = memory_test_setup["repo2"]
    service = ProjectMemoryService(db_session)

    entry1 = service.record_architectural_rule(
        repository_id=repo1.id,
        rule_content="Confidential proprietary encryption scheme.",
    )

    # Repo 2 search must return 0 items
    items, total = service.search_project_memory(repo2.id)
    assert total == 0
    assert len(items) == 0

    # Repo 2 lookup by ID must return None
    cross_lookup = service.get_memory(entry1.id, repository_id=repo2.id)
    assert cross_lookup is None

    # Cross-repo deletion must fail
    assert service.delete_memory(entry1.id, repository_id=repo2.id) is False


def test_api_memory_endpoints(client, db_session: Session, memory_test_setup: dict, monkeypatch):
    """Test full HTTP API lifecycle for Project Memory management."""
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-12345-secure-32bytes!")
    from app.core.config import get_settings
    get_settings.cache_clear()
    from app.core.security import create_access_token

    u1 = memory_test_setup["u1"]
    repo1 = memory_test_setup["repo1"]
    token, _ = create_access_token(user_id=str(u1.id))
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create memory entry
    resp_create = client.post(
        f"/api/v1/repositories/{repo1.id}/memories",
        headers=headers,
        json={
            "type": "decision",
            "content": "Use Postgres JSONB instead of MongoDB for unstructured telemetry.",
            "source": "architecture_review_meeting",
            "status": "active",
        },
    )
    assert resp_create.status_code == 201
    entry_data = resp_create.json()
    entry_id = entry_data["id"]
    assert entry_data["type"] == "decision"
    assert "Postgres JSONB" in entry_data["content"]

    # 2. List & search memory entries
    resp_list = client.get(
        f"/api/v1/repositories/{repo1.id}/memories?query=Postgres",
        headers=headers,
    )
    assert resp_list.status_code == 200
    list_data = resp_list.json()
    assert list_data["total"] >= 1
    assert any(item["id"] == entry_id for item in list_data["items"])

    # 3. Get specific entry
    resp_get = client.get(
        f"/api/v1/repositories/{repo1.id}/memories/{entry_id}",
        headers=headers,
    )
    assert resp_get.status_code == 200
    assert resp_get.json()["id"] == entry_id

    # 4. Patch entry
    resp_patch = client.patch(
        f"/api/v1/repositories/{repo1.id}/memories/{entry_id}",
        headers=headers,
        json={"status": "archived"},
    )
    assert resp_patch.status_code == 200
    assert resp_patch.json()["status"] == "archived"

    # 5. Automated task completion endpoint
    task_id = str(uuid.uuid4())
    resp_comp = client.post(
        f"/api/v1/repositories/{repo1.id}/memories/automated/task-completion",
        headers=headers,
        json={
            "task_id": task_id,
            "title": "Migrate authentication to Argon2",
            "verification_summary": "All password hash tests passed.",
            "repair_attempts_used": 0,
            "files_changed": ["backend/auth.py"],
        },
    )
    assert resp_comp.status_code == 201
    comp_data = resp_comp.json()
    assert comp_data["type"] == "task_summary"
    assert f"task:{task_id}" in comp_data["source"]

    # 6. Automated task failure endpoint
    fail_task_id = str(uuid.uuid4())
    resp_fail = client.post(
        f"/api/v1/repositories/{repo1.id}/memories/automated/task-failure",
        headers=headers,
        json={
            "task_id": fail_task_id,
            "title": "Upgrade database driver",
            "failure_reason": "Incompatible binary protocol on SQLite.",
            "repair_attempts_used": 2,
        },
    )
    assert resp_fail.status_code == 201
    fail_data = resp_fail.json()
    assert fail_data["type"] == "failure"

    # 7. Pin rule endpoint
    resp_rule = client.post(
        f"/api/v1/repositories/{repo1.id}/memories/rules",
        headers=headers,
        json={
            "rule": "Never write raw passwords to logs.",
            "source": "security_policy",
        },
    )
    assert resp_rule.status_code == 201
    rule_data = resp_rule.json()
    assert rule_data["type"] == "rule"

    # 8. Delete entry
    resp_del = client.delete(
        f"/api/v1/repositories/{repo1.id}/memories/{entry_id}",
        headers=headers,
    )
    assert resp_del.status_code == 204

    # Verify 404 after deletion
    resp_deleted = client.get(
        f"/api/v1/repositories/{repo1.id}/memories/{entry_id}",
        headers=headers,
    )
    assert resp_deleted.status_code == 404
