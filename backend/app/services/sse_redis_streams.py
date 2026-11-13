from __future__ import annotations

import asyncio
import collections
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Tuple

from app.core.secret_redaction import redact_obj

logger = logging.getLogger(__name__)

_STREAM_ID_RE = re.compile(r"^(?:0|0-0|\d+-\d+|\$)$")
_SAFE_IDENTIFIER_RE = re.compile(r"^[a-zA-Z0-9_.:-]{1,128}$")
_SAFE_EVENT_TYPE_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")

DEFAULT_STREAM_MAXLEN = 1000
DEFAULT_MAX_CHANNELS = 512
DEFAULT_BLOCK_MS = 5000
DEFAULT_BATCH_COUNT = 100

SUPPORTED_SSE_EVENT_TYPES = frozenset(
    {
        "sse.stream.connected",
        "sse.stream.gap_detected",
        "task.status.updated",
        "task.step.updated",
        "chat.stream.started",
        "chat.token",
        "chat.stream.chunk",
        "chat.stream.completed",
        "chat.stream.error",
        "tool.invocation.started",
        "tool.invocation.progress",
        "tool.invocation.completed",
        "tool.invocation.failed",
        "tool.approval.requested",
        "tool.approval.resolved",
        "mcp.notification",
        "mcp.progress",
        "mcp.elicitation.requested",
        "mcp.elicitation.resolved",
    }
)


def parse_stream_id_tuple(stream_id: str) -> Tuple[int, int]:
    """Parse '<ms>-<seq>' into an exact integer tuple without 64-bit float precision loss."""
    if stream_id in ("0", "0-0"):
        return (0, 0)
    parts = stream_id.split("-", 1)
    if len(parts) != 2:
        raise ValueError(f"Malformed stream ID: {stream_id!r}")
    ms, seq = int(parts[0]), int(parts[1])
    if ms < 0 or seq < 0:
        raise ValueError(f"Negative stream ID components not allowed: {stream_id!r}")
    return (ms, seq)


def compare_stream_ids(lhs: str, rhs: str) -> int:
    """Compare two '<ms>-<seq>' Redis Stream IDs (-1 if lhs < rhs, 0 if equal, +1 if lhs > rhs)."""
    l_tuple = parse_stream_id_tuple(lhs)
    r_tuple = parse_stream_id_tuple(rhs)
    if l_tuple < r_tuple:
        return -1
    if l_tuple > r_tuple:
        return 1
    return 0


def normalize_stream_cursor(raw_cursor: Optional[str]) -> str:
    """Validate and normalize a client-supplied Last-Event-ID header or query cursor."""
    if raw_cursor is None:
        return "$"
    cleaned = raw_cursor.strip()
    if not cleaned:
        return "$"
    if not _STREAM_ID_RE.match(cleaned):
        raise ValueError(f"Invalid Last-Event-ID cursor format: {cleaned!r}")
    if cleaned == "0":
        return "0-0"
    if cleaned != "$":
        parse_stream_id_tuple(cleaned)
    return cleaned


@dataclass(frozen=True)
class SSEEnvelope:
    """Immutable, CR/LF-injection-safe SSE frame stored in Redis Streams or fallback ring buffer."""

    stream_id: str
    event_type: str
    channel: str
    user_id: str
    payload: Dict[str, Any]
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def __post_init__(self) -> None:
        if not _SAFE_EVENT_TYPE_RE.match(self.event_type):
            raise ValueError(f"Unsafe SSE event_type rejected: {self.event_type!r}")
        if "\n" in self.stream_id or "\r" in self.stream_id:
            raise ValueError(f"Unsafe SSE stream_id rejected: {self.stream_id!r}")

    def to_sse_frame(self) -> str:
        body = {
            "id": self.stream_id,
            "type": self.event_type,
            "channel": self.channel,
            "timestamp_ms": self.created_at_ms,
            "data": redact_obj(self.payload),
        }
        serialized = (
            json.dumps(body, separators=(",", ":"), ensure_ascii=False)
            .replace("\n", "\\n")
            .replace("\r", "\\r")
        )
        return f"id: {self.stream_id}\nevent: {self.event_type}\ndata: {serialized}\n\n"


class _InMemoryStreamRingBuffer:
    """Bounded LRU-channel + bounded per-channel ring buffer fallback when Redis is unavailable."""

    def __init__(
        self,
        maxlen: int = DEFAULT_STREAM_MAXLEN,
        max_channels: int = DEFAULT_MAX_CHANNELS,
    ) -> None:
        self._maxlen = maxlen
        self._max_channels = max_channels
        self._streams: "collections.OrderedDict[str, Deque[SSEEnvelope]]" = (
            collections.OrderedDict()
        )
        self._condition = asyncio.Condition()
        self._last_ms = 0
        self._last_seq = 0

    def _next_stream_id(self, ring: Optional[Deque[SSEEnvelope]] = None) -> str:
        now_ms = int(time.time() * 1000)
        floor_ms, floor_seq = self._last_ms, self._last_seq
        if ring:
            tip_ms, tip_seq = parse_stream_id_tuple(ring[-1].stream_id)
            if (tip_ms, tip_seq) > (floor_ms, floor_seq):
                floor_ms, floor_seq = tip_ms, tip_seq
        if now_ms > floor_ms:
            self._last_ms, self._last_seq = now_ms, 0
        else:
            self._last_ms, self._last_seq = floor_ms, floor_seq + 1
        return f"{self._last_ms}-{self._last_seq}"

    def _get_or_create_ring(self, stream_key: str) -> Deque[SSEEnvelope]:
        ring = self._streams.get(stream_key)
        if ring is not None:
            self._streams.move_to_end(stream_key)
            return ring
        while len(self._streams) >= self._max_channels:
            self._streams.popitem(last=False)
        ring = collections.deque(maxlen=self._maxlen)
        self._streams[stream_key] = ring
        return ring

    async def xadd(
        self,
        stream_key: str,
        *,
        event_type: str,
        channel: str,
        user_id: str,
        payload: Dict[str, Any],
        explicit_id: Optional[str] = None,
    ) -> SSEEnvelope:
        async with self._condition:
            ring = self._get_or_create_ring(stream_key)
            stream_id = explicit_id or self._next_stream_id(ring)
            if explicit_id:
                exp_ms, exp_seq = parse_stream_id_tuple(explicit_id)
                if (exp_ms, exp_seq) > (self._last_ms, self._last_seq):
                    self._last_ms, self._last_seq = exp_ms, exp_seq
            envelope = SSEEnvelope(
                stream_id=stream_id,
                event_type=event_type,
                channel=channel,
                user_id=user_id,
                payload=redact_obj(payload),
            )
            ring.append(envelope)
            self._condition.notify_all()
            return envelope

    async def xread_after(
        self,
        stream_key: str,
        cursor: str,
        *,
        count: int = DEFAULT_BATCH_COUNT,
        block_ms: int = DEFAULT_BLOCK_MS,
    ) -> Tuple[List[SSEEnvelope], str]:
        async with self._condition:
            ring = self._streams.get(stream_key)
            resolved_cursor = (ring[-1].stream_id if ring else "0-0") if cursor == "$" else cursor

            def _collect() -> List[SSEEnvelope]:
                current_ring = self._streams.get(stream_key)
                if not current_ring:
                    return []
                out: List[SSEEnvelope] = []
                oldest = current_ring[0]
                if (
                    resolved_cursor not in ("0-0", "$")
                    and compare_stream_ids(resolved_cursor, oldest.stream_id) < 0
                ):
                    out.append(
                        SSEEnvelope(
                            stream_id=oldest.stream_id,
                            event_type="sse.stream.gap_detected",
                            channel=oldest.channel,
                            user_id=oldest.user_id,
                            payload={
                                "requested_cursor": resolved_cursor,
                                "oldest_available_cursor": oldest.stream_id,
                            },
                        )
                    )
                for env in current_ring:
                    if compare_stream_ids(env.stream_id, resolved_cursor) > 0:
                        out.append(env)
                        if len(out) >= count:
                            break
                return out

            batch = _collect()
            if not batch and block_ms > 0:
                try:
                    await asyncio.wait_for(
                        self._condition.wait(), timeout=max(0.005, block_ms / 1000.0)
                    )
                except asyncio.TimeoutError:
                    pass
                batch = _collect()

            next_cursor = batch[-1].stream_id if batch else resolved_cursor
            return batch, next_cursor


class RedisStreamEventBroker:
    """Tenant-scoped SSE event broker backed by Redis Streams (`XADD`/`XREAD`) + ring fallback."""

    def __init__(
        self,
        redis_client: Optional[Any] = None,
        *,
        maxlen: int = DEFAULT_STREAM_MAXLEN,
        max_channels: int = DEFAULT_MAX_CHANNELS,
    ) -> None:
        self._redis = redis_client
        self._maxlen = maxlen
        self._fallback = _InMemoryStreamRingBuffer(maxlen=maxlen, max_channels=max_channels)

    @staticmethod
    def build_stream_key(user_id: str, channel: str) -> str:
        if not user_id or not _SAFE_IDENTIFIER_RE.match(user_id):
            raise ValueError(f"Invalid user_id for SSE stream key: {user_id!r}")
        if not channel or not _SAFE_IDENTIFIER_RE.match(channel):
            raise ValueError(f"Invalid channel for SSE stream key: {channel!r}")
        return f"sse:stream:{user_id}:{channel}"

    async def publish(
        self,
        *,
        user_id: str,
        channel: str,
        event_type: str,
        payload: Dict[str, Any],
    ) -> SSEEnvelope:
        stream_key = self.build_stream_key(user_id, channel)
        created_at_ms = int(time.time() * 1000)
        safe_payload = redact_obj(payload)
        if self._redis is not None:
            try:
                raw_fields = {
                    "event_type": event_type,
                    "channel": channel,
                    "user_id": user_id,
                    "created_at_ms": str(created_at_ms),
                    "payload": json.dumps(safe_payload, separators=(",", ":"), ensure_ascii=False),
                }
                raw_id = await self._redis.xadd(
                    stream_key, raw_fields, maxlen=self._maxlen, approximate=True
                )
                stream_id = raw_id.decode("utf-8") if isinstance(raw_id, bytes) else str(raw_id)
                await self._fallback.xadd(
                    stream_key,
                    event_type=event_type,
                    channel=channel,
                    user_id=user_id,
                    payload=safe_payload,
                    explicit_id=stream_id,
                )
                return SSEEnvelope(
                    stream_id=stream_id,
                    event_type=event_type,
                    channel=channel,
                    user_id=user_id,
                    payload=safe_payload,
                    created_at_ms=created_at_ms,
                )
            except Exception as exc:
                logger.warning("Redis XADD failed on %s (%s); using fallback", stream_key, exc)

        return await self._fallback.xadd(
            stream_key,
            event_type=event_type,
            channel=channel,
            user_id=user_id,
            payload=safe_payload,
        )

    async def read_batch(
        self,
        *,
        user_id: str,
        channel: str,
        cursor: str,
        count: int = DEFAULT_BATCH_COUNT,
        block_ms: int = DEFAULT_BLOCK_MS,
    ) -> Tuple[List[SSEEnvelope], str]:
        stream_key = self.build_stream_key(user_id, channel)
        normalized_cursor = normalize_stream_cursor(cursor)
        if self._redis is not None:
            try:
                if normalized_cursor == "$":
                    tip = await self._redis.xrevrange(stream_key, count=1)
                    normalized_cursor = (
                        (
                            tip[0][0].decode("utf-8")
                            if isinstance(tip[0][0], bytes)
                            else str(tip[0][0])
                        )
                        if tip
                        else "0-0"
                    )
                envelopes: List[SSEEnvelope] = []
                if normalized_cursor != "0-0":
                    oldest = await self._redis.xrange(stream_key, count=1)
                    if oldest:
                        oldest_id = (
                            oldest[0][0].decode("utf-8")
                            if isinstance(oldest[0][0], bytes)
                            else str(oldest[0][0])
                        )
                        if compare_stream_ids(normalized_cursor, oldest_id) < 0:
                            envelopes.append(
                                SSEEnvelope(
                                    stream_id=oldest_id,
                                    event_type="sse.stream.gap_detected",
                                    channel=channel,
                                    user_id=user_id,
                                    payload={
                                        "requested_cursor": normalized_cursor,
                                        "oldest_available_cursor": oldest_id,
                                    },
                                )
                            )
                response = await self._redis.xread(
                    streams={stream_key: normalized_cursor}, count=count, block=block_ms
                )
                next_cursor = normalized_cursor
                for _stream_name, messages in response or []:
                    for raw_id, fields in messages:
                        msg_id = (
                            raw_id.decode("utf-8") if isinstance(raw_id, bytes) else str(raw_id)
                        )
                        decoded = {
                            (k.decode("utf-8") if isinstance(k, bytes) else str(k)): (
                                v.decode("utf-8") if isinstance(v, bytes) else str(v)
                            )
                            for k, v in fields.items()
                        }
                        envelopes.append(
                            SSEEnvelope(
                                stream_id=msg_id,
                                event_type=decoded.get("event_type", "task.status.updated"),
                                channel=decoded.get("channel", channel),
                                user_id=decoded.get("user_id", user_id),
                                payload=json.loads(decoded.get("payload", "{}")),
                                created_at_ms=int(
                                    decoded.get("created_at_ms", int(time.time() * 1000))
                                ),
                            )
                        )
                        next_cursor = msg_id
                return envelopes, next_cursor
            except Exception as exc:
                logger.warning("Redis XREAD failed on %s (%s); using fallback", stream_key, exc)

        return await self._fallback.xread_after(
            stream_key, normalized_cursor, count=count, block_ms=block_ms
        )


_GLOBAL_SSE_BROKER = RedisStreamEventBroker()


def get_sse_broker() -> RedisStreamEventBroker:
    return _GLOBAL_SSE_BROKER


async def publish_chat_token(
    *,
    user_id: str,
    channel: str,
    session_id: str,
    message_id: str,
    token: str,
    index: int,
    done: bool = False,
    broker: Optional[RedisStreamEventBroker] = None,
) -> SSEEnvelope:
    active = broker or _GLOBAL_SSE_BROKER
    return await active.publish(
        user_id=user_id,
        channel=channel,
        event_type="chat.stream.completed" if done else "chat.token",
        payload={
            "session_id": session_id,
            "message_id": message_id,
            "token": token,
            "index": index,
            "done": done,
        },
    )


async def publish_tool_progress(
    *,
    user_id: str,
    channel: str,
    task_id: str,
    call_id: str,
    tool_name: str,
    stage: str,
    progress_pct: Optional[float] = None,
    message: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    broker: Optional[RedisStreamEventBroker] = None,
) -> SSEEnvelope:
    active = broker or _GLOBAL_SSE_BROKER
    event_map = {
        "started": "tool.invocation.started",
        "progress": "tool.invocation.progress",
        "completed": "tool.invocation.completed",
        "failed": "tool.invocation.failed",
    }
    return await active.publish(
        user_id=user_id,
        channel=channel,
        event_type=event_map.get(stage, "tool.invocation.progress"),
        payload={
            "task_id": task_id,
            "call_id": call_id,
            "tool_name": tool_name,
            "stage": stage,
            "progress_pct": progress_pct,
            "message": message,
            "metadata": metadata or {},
        },
    )


async def publish_mcp_notification(
    *,
    user_id: str,
    channel: str,
    server_name: str,
    method: str,
    params: Dict[str, Any],
    kind: str = "notification",
    broker: Optional[RedisStreamEventBroker] = None,
) -> SSEEnvelope:
    active = broker or _GLOBAL_SSE_BROKER
    kind_map = {
        "notification": "mcp.notification",
        "progress": "mcp.progress",
        "elicitation": "mcp.elicitation.requested",
        "elicitation_resolved": "mcp.elicitation.resolved",
    }
    return await active.publish(
        user_id=user_id,
        channel=channel,
        event_type=kind_map.get(kind, "mcp.notification"),
        payload={"server_name": server_name, "method": method, "params": params},
    )


def emit_sse_event_nonblocking(coro: Any) -> None:
    """Schedule an SSE publish coroutine safely from either async or sync contexts."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(coro)
    except RuntimeError:
        try:
            asyncio.run(coro)
        except Exception:
            pass
    except Exception:
        pass
