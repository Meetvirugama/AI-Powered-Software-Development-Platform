"""Server-Sent Events (SSE) router for real-time frontend updates."""

from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.core.redis import get_redis_async

logger = logging.getLogger(__name__)

router = APIRouter(tags=["events"])


@router.get("/events", summary="Subscribe to real-time platform events (SSE)")
async def stream_events(request: Request) -> StreamingResponse:
    """Stream real-time repository and platform events to frontend clients."""

    async def event_generator():
        # Emit initial connection handshake
        yield f"data: {json.dumps({'type': 'connected', 'data': {}})}\n\n"

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
