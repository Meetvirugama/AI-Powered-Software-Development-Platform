"""Server-Sent Events (SSE) router for real-time frontend updates (Issue 1 — Redis Streams & Last-Event-ID)."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.auth import _get_token
from app.core.database import get_db
from app.core.redis import get_redis, get_redis_async
from app.core.security import decode_access_token
from app.repositories.repository_repository import RepositoryRepository
from app.services.sse_redis_streams import (
    RedisStreamEventBroker,
    SSEEnvelope,
    SUPPORTED_SSE_EVENT_TYPES,
    compare_stream_ids,
    get_sse_broker,
    normalize_stream_cursor,
    parse_stream_id_tuple,
    publish_chat_token,
    publish_mcp_notification,
    publish_tool_progress,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["events"])


async def _resolve_optional_user_id(request: Request) -> UUID | None:
    """Resolve authenticated user_id from request.state or JWT token/cookie if present."""
    state_uid = getattr(request.state, "user_id", None)
    if state_uid:
        try:
            return UUID(str(state_uid))
        except (ValueError, TypeError):
            pass

    token = _get_token(request)
    if not token:
        return None
    try:
        claims = decode_access_token(token)
        jti = str(claims.get("jti", ""))
        if jti:
            try:
                r = await get_redis_async()
                exists_res = r.exists(f"auth:blocklist:{jti}")
                if inspect.isawaitable(exists_res):
                    exists_res = await exists_res
                if exists_res:
                    return None
            except Exception:
                try:
                    exists_res = await asyncio.to_thread(get_redis().exists, f"auth:blocklist:{jti}")
                    if exists_res:
                        return None
                except Exception as exc:
                    logger.debug("Failed checking token blocklist for SSE connection: %s", exc)
        return UUID(str(claims["sub"]))
    except Exception:
        return None


def _should_deliver_event(
    raw_data: str,
    caller_user_id: str | None,
    owned_repo_ids: set[str] | None = None,
) -> bool:
    """Filter user-scoped and repository-scoped events so tenants never receive another user's events.
    Fails closed on malformed JSON or unauthenticated private streams."""
    try:
        parsed = json.loads(raw_data)
    except Exception:
        return False

    if not isinstance(parsed, dict):
        return False

    data_obj = parsed.get("data")
    event_user_id = (
        parsed.get("user_id")
        or (data_obj.get("user_id") if isinstance(data_obj, dict) else None)
    )

    if event_user_id is not None:
        if not caller_user_id:
            return False
        if str(event_user_id) != str(caller_user_id):
            return False
        if owned_repo_ids is not None and isinstance(data_obj, dict) and "repository_id" in data_obj:
            return str(data_obj["repository_id"]) in owned_repo_ids
        return True

    if isinstance(data_obj, dict) and "repository_id" in data_obj:
        if owned_repo_ids is None:
            return False
        return str(data_obj["repository_id"]) in owned_repo_ids

    if caller_user_id is None:
        is_public = parsed.get("is_public") is True or parsed.get("type") in {"system.notice", "connected"}
        if not is_public:
            return False

    return True


@router.get("/events", summary="Subscribe to real-time platform events (SSE)")
async def stream_events(
    request: Request,
):
    """Stream real-time repository, chat token, tool progress, and MCP events with Last-Event-ID replay.

    Acquires and closes the database session immediately before returning the
    long-lived StreamingResponse so SSE connections never exhaust QueuePool.
    """
    from app.core.database import SessionLocal

    raw_cursor = (
        request.headers.get("Last-Event-ID")
        or request.query_params.get("last_event_id")
        or None
    )
    try:
        stream_cursor = normalize_stream_cursor(raw_cursor)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    channel = (request.query_params.get("channel") or "platform_events").strip() or "platform_events"

    user_uuid = await _resolve_optional_user_id(request)
    caller_user_id = str(user_uuid) if user_uuid is not None else getattr(request.state, "user_id", None)
    owned_repo_ids: set[str] | None = None
    if user_uuid is not None:
        app = request.scope.get("app") if hasattr(request, "scope") and isinstance(request.scope, dict) else None
        db_override = app.dependency_overrides.get(get_db) if app and hasattr(app, "dependency_overrides") else None
        if db_override is not None:
            gen = db_override()
            db = next(gen) if hasattr(gen, "__next__") else gen
            try:
                if hasattr(db, "execute"):
                    repos = RepositoryRepository(db).list_by_user(user_uuid)
                    owned_repo_ids = {str(r.id) for r in repos if hasattr(r, "id")}
            except Exception:
                owned_repo_ids = None
            finally:
                if hasattr(gen, "close"):
                    gen.close()
        else:
            try:
                with SessionLocal() as db:
                    repos = RepositoryRepository(db).list_by_user(user_uuid)
                    owned_repo_ids = {str(r.id) for r in repos if hasattr(r, "id")}
            except Exception:
                owned_repo_ids = None

    async def event_generator():
        nonlocal stream_cursor
        broker = get_sse_broker()
        stream_user_key = str(caller_user_id) if caller_user_id else None

        # ---------------------------------------------------------------------
        # Event-Driven Asynchronous Pipeline (Issue F-43 / #261):
        # We replace the busy sleep-polling loop (await asyncio.sleep(0.5)) with
        # an event-driven queue. Events arriving via Redis Stream (tokens/tools)
        # or Redis Pub/Sub (broadcasts) are pushed directly into the queue.
        # When no events are pending, the generator suspends on event_queue.get()
        # with zero CPU wakeups until an event arrives or the 15s ping timer fires.
        # ---------------------------------------------------------------------
        event_queue: asyncio.Queue[str] = asyncio.Queue()
        stop_event = asyncio.Event()

        # 1. Enqueue the initial connection frame immediately
        connected_payload = json.dumps(
            {
                "type": "connected",
                "data": {
                    "authenticated": caller_user_id is not None,
                    "cursor": stream_cursor,
                    "channel": channel,
                },
            }
        )
        await event_queue.put(f"data: {connected_payload}\n\n")

        # 2. Replay any missed Redis Stream events when a Last-Event-ID cursor is provided
        if stream_user_key and stream_cursor != "$":
            try:
                missed_batch, stream_cursor = await broker.read_batch(
                    user_id=stream_user_key,
                    channel=channel,
                    cursor=stream_cursor,
                    block_ms=10,
                )
                for env in missed_batch:
                    await event_queue.put(env.to_sse_frame())
            except Exception as replay_exc:
                logger.debug("sse_stream_replay_warning: %s", replay_exc)

        # 3. Stream Feeder: watches Redis Stream / in-memory ring buffer
        async def _stream_feeder() -> None:
            nonlocal stream_cursor
            while not stop_event.is_set():
                if not stream_user_key:
                    await asyncio.sleep(1.0)
                    continue
                try:
                    # Bounded blocking wait (up to 2000ms), returns immediately on new events
                    live_batch, stream_cursor = await broker.read_batch(
                        user_id=stream_user_key,
                        channel=channel,
                        cursor=stream_cursor,
                        block_ms=2000,
                    )
                    for env in live_batch:
                        await event_queue.put(env.to_sse_frame())
                except asyncio.CancelledError:
                    break
                except Exception as stream_exc:
                    logger.debug("sse_stream_feeder_error: %s", stream_exc)
                    await asyncio.sleep(0.5)

        redis = None
        pubsub = None
        user_channel = f"events:user:{caller_user_id}" if caller_user_id else None
        channels_to_sub = ["platform_events"]
        if user_channel:
            channels_to_sub.append(user_channel)
        try:
            redis = await get_redis_async()
            pubsub = redis.pubsub()
            await pubsub.subscribe(*channels_to_sub)
        except Exception as exc:
            logger.warning("sse_redis_connection_failed: %s", exc)

        # 4. PubSub Feeder: watches Redis Pub/Sub channels
        async def _pubsub_feeder() -> None:
            if pubsub is None:
                return
            while not stop_event.is_set():
                try:
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=2.0,
                    )
                    if message and message.get("type") == "message":
                        raw_data = message.get("data")
                        if isinstance(raw_data, bytes):
                            raw_data = raw_data.decode("utf-8")
                        if isinstance(raw_data, str) and _should_deliver_event(
                            raw_data, caller_user_id, owned_repo_ids
                        ):
                            await event_queue.put(f"data: {raw_data}\n\n")
                except asyncio.CancelledError:
                    break
                except Exception as poll_exc:
                    logger.debug("sse_pubsub_feeder_error: %s", poll_exc)
                    await asyncio.sleep(0.5)

        feeder_tasks: list[asyncio.Task] = []
        if stream_user_key:
            feeder_tasks.append(asyncio.create_task(_stream_feeder()))
        if pubsub is not None:
            feeder_tasks.append(asyncio.create_task(_pubsub_feeder()))

        last_ping = time.time()
        PING_INTERVAL = 15.0

        try:
            while True:
                try:
                    if await request.is_disconnected():
                        break
                except Exception:
                    # Defensive: ignore receive channel unavailability in test harnesses
                    pass

                # Calculate remaining time until next scheduled heartbeat ping
                elapsed = time.time() - last_ping
                wait_timeout = max(0.05, PING_INTERVAL - elapsed)

                try:
                    # Suspend until an event arrives or ping interval elapses: zero CPU wakeups!
                    frame = await asyncio.wait_for(event_queue.get(), timeout=wait_timeout)
                    yield frame
                except asyncio.TimeoutError:
                    # 15s ping interval reached with no events dispatched
                    yield ": ping\n\n"
                    last_ping = time.time()

        except asyncio.CancelledError:
            pass
        finally:
            stop_event.set()
            for t in feeder_tasks:
                t.cancel()
            if feeder_tasks:
                await asyncio.gather(*feeder_tasks, return_exceptions=True)
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe(*channels_to_sub)
                    await pubsub.close()
                except Exception as exc:
                    logger.debug("Failed closing pubsub in SSE generator: %s", exc)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


__all__ = [
    "RedisStreamEventBroker",
    "SSEEnvelope",
    "SUPPORTED_SSE_EVENT_TYPES",
    "_resolve_optional_user_id",
    "_should_deliver_event",
    "compare_stream_ids",
    "get_sse_broker",
    "normalize_stream_cursor",
    "parse_stream_id_tuple",
    "publish_chat_token",
    "publish_mcp_notification",
    "publish_tool_progress",
    "router",
    "stream_events",
]
