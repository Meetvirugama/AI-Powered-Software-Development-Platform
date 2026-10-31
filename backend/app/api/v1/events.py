"""Server-Sent Events (SSE) router for real-time frontend updates."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.auth import _get_token
from app.core.database import get_db
from app.core.redis import get_redis, get_redis_async
from app.core.security import decode_access_token
from app.repositories.repository_repository import RepositoryRepository

logger = logging.getLogger(__name__)

router = APIRouter(tags=["events"])


def _resolve_optional_user_id(request: Request) -> UUID | None:
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
        if jti and get_redis().exists(f"auth:blocklist:{jti}"):
            return None
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
        # Fail closed on malformed JSON
        return False

    if not isinstance(parsed, dict):
        # Fail closed on non-dict payload
        return False

    data_obj = parsed.get("data")
    event_user_id = (
        parsed.get("user_id")
        or (data_obj.get("user_id") if isinstance(data_obj, dict) else None)
    )

    # If the event is explicitly scoped to a user, strictly match caller_user_id
    if event_user_id is not None:
        if not caller_user_id:
            return False
        if str(event_user_id) != str(caller_user_id):
            return False

    # If the event is scoped to a repository, verify caller ownership
    if isinstance(data_obj, dict) and "repository_id" in data_obj:
        if caller_user_id is None and owned_repo_ids is None:
            return False
        if owned_repo_ids is not None:
            if str(data_obj["repository_id"]) not in owned_repo_ids:
                if event_user_id is not None and str(event_user_id) == str(caller_user_id):
                    return True
                return False

    # For general events with no repository or user scope, require authenticated user
    # unless it is explicitly a public system notice
    if caller_user_id is None:
        is_public = parsed.get("is_public") is True or parsed.get("type") in {"system.notice", "connected"}
        if not is_public:
            return False

    return True


def _is_event_authorized_for_user(
    raw_data: str,
    owned_repo_ids: set[str] | None,
    caller_user_id: str | None = None,
) -> bool:
    """Ensure repository-scoped and user-scoped events are only delivered to the authorized owner."""
    if owned_repo_ids is None and caller_user_id is None:
        return False
    return _should_deliver_event(raw_data, caller_user_id, owned_repo_ids)


@router.get("/events", summary="Subscribe to real-time platform events (SSE)")
async def stream_events(
    request: Request,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream real-time repository and platform events scoped to the authenticated user."""
    user_uuid = _resolve_optional_user_id(request)
    caller_user_id = str(user_uuid) if user_uuid is not None else getattr(request.state, "user_id", None)
    owned_repo_ids: set[str] | None = None
    if user_uuid is not None and hasattr(db, "execute"):
        try:
            repos = RepositoryRepository(db).list_by_user(user_uuid)
            owned_repo_ids = {str(r.id) for r in repos if hasattr(r, "id")}
        except Exception:
            owned_repo_ids = None

    async def event_generator():
        connected_payload = json.dumps(
            {"type": "connected", "data": {"authenticated": caller_user_id is not None}}
        )
        yield f"data: {connected_payload}\n\n"

        redis = None
        pubsub = None
        try:
            redis = await get_redis_async()
            pubsub = redis.pubsub()
            await pubsub.subscribe("platform_events")
        except Exception as exc:
            logger.warning("sse_redis_connection_failed: %s", exc)

        last_ping = time.time()

        try:
            while True:
                if await request.is_disconnected():
                    break

                if pubsub is not None:
                    try:
                        message = await pubsub.get_message(
                            ignore_subscribe_messages=True,
                            timeout=1.0,
                        )
                        if message and message.get("type") == "message":
                            raw_data = message.get("data")
                            if isinstance(raw_data, bytes):
                                raw_data = raw_data.decode("utf-8")
                            if isinstance(raw_data, str) and _should_deliver_event(
                                raw_data, caller_user_id, owned_repo_ids
                            ):
                                yield f"data: {raw_data}\n\n"
                    except Exception as poll_exc:
                        logger.debug("sse_poll_error: %s", poll_exc)

                if time.time() - last_ping > 15:
                    yield ": ping\n\n"
                    last_ping = time.time()

                await asyncio.sleep(0.5)

        except asyncio.CancelledError:
            pass
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe("platform_events")
                    await pubsub.close()
                except Exception:
                    pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
