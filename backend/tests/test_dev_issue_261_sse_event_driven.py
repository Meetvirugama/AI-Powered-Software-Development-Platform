import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from starlette.applications import Starlette
from starlette.requests import Request

from app.api.v1.events import stream_events
from app.services.sse_redis_streams import get_sse_broker, publish_chat_token


def _make_dummy_request(
    user_id: str | None = None,
    headers: dict[str, str] | None = None,
    query_params: dict[str, str] | None = None,
) -> Request:
    """Helper to construct a mock Starlette Request with minimal scope and attached app."""
    app = Starlette()
    scope = {
        "type": "http",
        "app": app,
        "method": "GET",
        "path": "/api/v1/events",
        "headers": [(k.lower().encode("utf-8"), v.encode("utf-8")) for k, v in (headers or {}).items()],
        "query_string": "&".join(f"{k}={v}" for k, v in (query_params or {}).items()).encode("utf-8"),
    }

    async def _mock_receive():
        await asyncio.Event().wait()
        return {"type": "http.disconnect"}

    req = Request(scope, receive=_mock_receive)
    if user_id:
        req.state.user_id = user_id
    return req


@pytest.mark.asyncio
async def test_sse_event_driven_immediate_delivery():
    """Verify that events published via broker are dispatched immediately (<100ms) without 500ms polling latency."""
    user_id = str(uuid4())
    req = _make_dummy_request(user_id=user_id)

    # Disable redis pubsub for this test to focus on stream feeder
    with patch("app.api.v1.events.get_redis_async", side_effect=ConnectionError("No Redis")):
        response = await stream_events(req)
        gen = response.body_iterator

        # First frame must be 'connected'
        init_frame = await anext(gen)
        assert "connected" in init_frame

        # Publish an event into broker
        start_time = time.perf_counter()
        await publish_chat_token(
            user_id=user_id,
            channel="platform_events",
            session_id="session-123",
            message_id="msg-456",
            token="Hello world!",
            index=0,
        )

        # Receive frame from stream
        frame = await asyncio.wait_for(anext(gen), timeout=1.0)
        elapsed = time.perf_counter() - start_time

        # Verification: Event must arrive promptly (< 200ms, well below old 500ms+ sleep jitter)
        assert elapsed < 0.2, f"Event delivery took {elapsed:.3f}s, expected < 0.2s"
        assert "chat.token" in frame
        assert "Hello world!" in frame

        await gen.aclose()


@pytest.mark.asyncio
async def test_sse_last_event_id_replay():
    """Verify that Last-Event-ID replays missed events before listening for live ones."""
    user_id = str(uuid4())

    # Pre-populate 3 events
    env1 = await publish_chat_token(
        user_id=user_id, channel="platform_events", session_id="s1", message_id="m1", token="Token 1", index=0
    )
    env2 = await publish_chat_token(
        user_id=user_id, channel="platform_events", session_id="s1", message_id="m1", token="Token 2", index=1
    )
    env3 = await publish_chat_token(
        user_id=user_id, channel="platform_events", session_id="s1", message_id="m1", token="Token 3", index=2
    )

    req = _make_dummy_request(
        user_id=user_id,
        headers={"Last-Event-ID": env1.stream_id},
    )

    with patch("app.api.v1.events.get_redis_async", side_effect=ConnectionError("No Redis")):
        response = await stream_events(req)
        gen = response.body_iterator

        frame_init = await anext(gen)
        assert "connected" in frame_init

        # Replayed events should be env2 and env3
        frame_r1 = await anext(gen)
        assert "Token 2" in frame_r1
        frame_r2 = await anext(gen)
        assert "Token 3" in frame_r2

        await gen.aclose()


@pytest.mark.asyncio
async def test_sse_feeder_tasks_cleanup_on_close():
    """Verify background feeder tasks are cleanly cancelled when generator is closed."""
    user_id = str(uuid4())
    req = _make_dummy_request(user_id=user_id)

    with patch("app.api.v1.events.get_redis_async", side_effect=ConnectionError("No Redis")):
        response = await stream_events(req)
        gen = response.body_iterator

        # Receive initial frame
        await anext(gen)

        # Close generator (simulating client disconnect)
        await gen.aclose()

        # Allow loop to process cancellation
        await asyncio.sleep(0.05)

        # Tasks created by stream_events must be terminated
        remaining_feeder_tasks = [
            t for t in asyncio.all_tasks()
            if not t.done() and "_stream_feeder" in t.get_name()
        ]
        assert len(remaining_feeder_tasks) == 0


@pytest.mark.asyncio
async def test_sse_heartbeat_ping():
    """Verify heartbeat ping is yielded on timeout when no events arrive."""
    user_id = str(uuid4())
    req = _make_dummy_request(user_id=user_id)

    # Patch time.time before stream_events is called so last_ping and elapsed share the mock timeline
    current_time = 100.0

    def mock_time():
        nonlocal current_time
        return current_time

    with patch("app.api.v1.events.get_redis_async", side_effect=ConnectionError("No Redis")), \
         patch("time.time", side_effect=mock_time):
        response = await stream_events(req)
        gen = response.body_iterator

        # 1. First frame is 'connected'
        init_frame = await anext(gen)
        assert "connected" in init_frame

        # 2. Advance mock clock beyond PING_INTERVAL (15.0s)
        current_time = 120.0

        # Generator should timeout on event_queue.get() and yield heartbeat ping
        ping_frame = await asyncio.wait_for(anext(gen), timeout=1.0)
        assert ping_frame == ": ping\n\n"

        await gen.aclose()


@pytest.mark.asyncio
async def test_sse_pubsub_feeder_delivery():
    """Verify pubsub messages are ingested by pubsub feeder and yielded to client."""
    user_id = str(uuid4())
    req = _make_dummy_request(user_id=user_id)

    mock_pubsub = AsyncMock()
    # Return one message then simulate wait
    mock_pubsub.get_message.side_effect = [
        {
            "type": "message",
            "data": json.dumps({"type": "system.notice", "is_public": True, "data": {"message": "System broadcast"}}),
        },
        asyncio.CancelledError(),
    ]
    mock_pubsub.subscribe = AsyncMock()
    mock_pubsub.unsubscribe = AsyncMock()
    mock_pubsub.close = AsyncMock()

    mock_redis = AsyncMock()
    mock_redis.pubsub = MagicMock(return_value=mock_pubsub)

    with patch("app.api.v1.events.get_redis_async", return_value=mock_redis):
        response = await stream_events(req)
        gen = response.body_iterator

        await anext(gen)  # connected frame

        frame = await asyncio.wait_for(anext(gen), timeout=1.0)
        assert "System broadcast" in frame

        await gen.aclose()


@pytest.mark.asyncio
async def test_sse_tenant_isolation_filter():
    """Verify events targeting other users are dropped by the pubsub filter."""
    user_a = str(uuid4())
    user_b = str(uuid4())
    req = _make_dummy_request(user_id=user_a)

    mock_pubsub = AsyncMock()
    # Message for user_b should be dropped; message for user_a should be delivered
    mock_pubsub.get_message.side_effect = [
        {
            "type": "message",
            "data": json.dumps({"type": "task.status.updated", "user_id": user_b, "data": {"status": "secret_b"}}),
        },
        {
            "type": "message",
            "data": json.dumps({"type": "task.status.updated", "user_id": user_a, "data": {"status": "visible_a"}}),
        },
        asyncio.CancelledError(),
    ]
    mock_pubsub.subscribe = AsyncMock()
    mock_pubsub.unsubscribe = AsyncMock()
    mock_pubsub.close = AsyncMock()

    mock_redis = AsyncMock()
    mock_redis.pubsub = MagicMock(return_value=mock_pubsub)

    with patch("app.api.v1.events.get_redis_async", return_value=mock_redis):
        response = await stream_events(req)
        gen = response.body_iterator

        await anext(gen)  # connected frame

        # Only user_a's event should be yielded; user_b's event must never appear
        frame = await asyncio.wait_for(anext(gen), timeout=1.0)
        assert "visible_a" in frame
        assert "secret_b" not in frame

        await gen.aclose()

