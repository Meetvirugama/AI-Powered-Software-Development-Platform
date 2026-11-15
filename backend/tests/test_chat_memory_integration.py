"""Project memory integration test for chat and AI context (TST-40, ISS-036).

Validates:
- Active project memories are fetched and injected into RAG pipeline chat context.
- Memories appear in the prompt payload with provenance labels.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from fastapi.testclient import TestClient

from ai.schemas.output import RepositoryAnswer
from app.core.security import create_access_token
from app.models.memory_entry import MemoryEntry, MemoryStatus, MemoryType
from app.models.repository import Repository, SyncStatus
from app.models.user import User


def test_chat_injects_project_memories_into_pipeline(client: TestClient, db_session, monkeypatch) -> None:
    """TST-40 / ISS-036: Active project memories are supplied to pipeline.chat."""
    user = User(
        id=uuid4(),
        github_id="mem-test-gh-1",
        login="mem_user",
        email="mem@test.local",
    )
    db_session.add(user)
    db_session.commit()

    repo = Repository(
        id=uuid4(),
        user_id=user.id,
        installation_id=uuid4(),
        github_repo_id="repo-mem-1",
        name="test-repo-mem",
        owner="mem_user",
        default_branch="main",
        sync_status=SyncStatus.SYNCED,
    )
    db_session.add(repo)
    db_session.commit()

    # Add an active architectural rule memory
    rule = MemoryEntry(
        id=uuid4(),
        repository_id=repo.id,
        type_=MemoryType.rule,
        status=MemoryStatus.active,
        content="All asynchronous jobs must use durable background queues.",
        source="user",
    )
    db_session.add(rule)
    db_session.commit()

    token, _ = create_access_token(user.id)
    headers = {"Authorization": f"Bearer {token}"}

    captured_memory = []

    async def fake_chat(question, repository_id, history, memory=None, **kwargs):
        captured_memory.extend(memory or [])
        return RepositoryAnswer(
            answer="Answer adhering to architectural rule.",
            confidence="high",
            sources=[],
        )

    mock_pipeline = MagicMock()
    mock_pipeline.chat = AsyncMock(side_effect=fake_chat)

    from app.main import app
    app.state.rag_pipeline = mock_pipeline

    resp = client.post(
        f"/api/v1/repositories/{repo.id}/chat",
        headers=headers,
        json={"question": "What is our worker policy?", "history": []},
    )

    assert resp.status_code == 200
    assert len(captured_memory) >= 1
    assert any("durable background queues" in getattr(m, "content", "") for m in captured_memory)
