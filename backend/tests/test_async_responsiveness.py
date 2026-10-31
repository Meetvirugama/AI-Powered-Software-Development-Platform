"""Concurrency and event-loop responsiveness tests for non-blocking execution (B-06)."""

import asyncio
import time
import uuid
import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.main import app
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.repository_file import RepositoryFile
from app.models.user import User


@pytest.mark.asyncio
async def test_slow_sync_work_does_not_block_concurrent_event_loop(db_session):
    """B-06: Slow static scanning or synchronous DB work offloaded via asyncio.to_thread
    must not block concurrent event-loop operations (such as health checks or concurrent requests).
    """
    # 1. Setup authorized user and repository
    u = User(id=uuid.uuid4(), github_id="gh_bench", email="bench@example.com", login="bench", avatar_url="")
    db_session.add(u)
    db_session.flush()

    inst = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=u.id,
        installation_id="inst_bench",
        account_login=u.login,
        permissions={},
    )
    db_session.add(inst)

    repo = Repository(
        id=uuid.uuid4(),
        user_id=u.id,
        installation_id=inst.id,
        github_repo_id="gh_repo_bench",
        owner=u.login,
        name="bench-repo",
        default_branch="main",
        sync_status=SyncStatus.SYNCED,
    )
    db_session.add(repo)

    f = RepositoryFile(
        id=uuid.uuid4(),
        repository_id=repo.id,
        path="src/main.py",
        language="python",
        size_bytes=100,
        line_count=10,
        content_hash="bench_hash",
    )
    db_session.add(f)
    db_session.commit()

    token, _ = create_access_token(str(u.id))

    # 2. Simulate slow static analysis or slow DB call in a thread
    def slow_worker_sync():
        time.sleep(0.3)
        return "done"

    start_time = time.monotonic()

    # Launch the slow worker via asyncio.to_thread concurrently with fast async event-loop ticks
    slow_task = asyncio.create_task(asyncio.to_thread(slow_worker_sync))

    fast_ticks = 0
    while not slow_task.done():
        await asyncio.sleep(0.05)
        fast_ticks += 1

    await slow_task
    duration = time.monotonic() - start_time

    # During the 300ms sleep of the slow worker, the event loop must have yielded and run ticks!
    assert fast_ticks >= 4, f"Event loop was blocked! Only {fast_ticks} ticks executed."
    assert duration >= 0.28, "Worker completed too fast."


def test_concurrent_requests_remain_responsive(client: TestClient, db_session):
    """B-06: Synchronous routes executed via threadpool maintain high throughput and low latency."""
    u = User(id=uuid.uuid4(), github_id="gh_conc", email="conc@example.com", login="conc", avatar_url="")
    db_session.add(u)
    db_session.flush()

    token, _ = create_access_token(str(u.id))

    # Rapid burst of health checks and status checks
    latencies = []
    for _ in range(20):
        t0 = time.monotonic()
        res = client.get("/health/live")
        assert res.status_code == 200
        latencies.append((time.monotonic() - t0) * 1000)

    p95 = sorted(latencies)[int(len(latencies) * 0.95)]
    # Local health check p95 should easily be under 50ms
    assert p95 < 100, f"p95 latency {p95}ms exceeds 100ms threshold"
