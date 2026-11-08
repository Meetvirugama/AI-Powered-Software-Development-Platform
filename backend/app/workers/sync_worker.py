"""
Worker entrypoint for background sync jobs.
Connects the Redis `sync_jobs` queue to the processor as a standalone process.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import socket
import sys
import time
import uuid
from typing import Any

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.redis import close_redis, close_redis_async, get_redis_async
from app.integrations.github.service import GitHubService
from app.services.sync_worker import RepositoryBusyError, process_sync_job, sync_worker_loop

logger = logging.getLogger(__name__)

__all__ = [
    "RepositoryBusyError",
    "process_sync_job",
    "sync_worker_loop",
    "run_worker",
    "main",
    "generate_worker_id",
    "_worker_heartbeat_loop",
]


def generate_worker_id() -> str:
    """Generate a stable, unique worker identifier."""
    hostname = socket.gethostname() or "unknown-host"
    short_uuid = uuid.uuid4().hex[:8]
    return f"sync-worker-{hostname}-{short_uuid}"


async def _worker_heartbeat_loop(
    redis: Any,
    worker_id: str,
    stop_event: asyncio.Event,
    interval: float = 15.0,
    ttl: int = 45,
) -> None:
    """Publish periodic worker heartbeat to Redis."""
    key = f"worker:heartbeat:{worker_id}"
    started_at = time.time()
    pid = os.getpid()
    hostname = socket.gethostname()

    while not stop_event.is_set():
        try:
            payload = json.dumps(
                {
                    "worker_id": worker_id,
                    "hostname": hostname,
                    "pid": pid,
                    "started_at": started_at,
                    "last_heartbeat": time.time(),
                    "ttl_seconds": ttl,
                }
            )
            if hasattr(redis, "set"):
                await redis.set(key, payload, ex=ttl)
        except Exception as exc:
            logger.warning(
                "worker_heartbeat_error",
                extra={"worker_id": worker_id, "error": str(exc)},
            )

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            pass

    # Cleanup heartbeat key on clean exit
    try:
        if hasattr(redis, "delete"):
            await redis.delete(key)
    except Exception:
        pass


async def run_worker(worker_id: str | None = None) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    if not worker_id:
        worker_id = generate_worker_id()

    logger.info("starting_standalone_sync_worker", extra={"worker_id": worker_id})

    redis = await get_redis_async()
    github_service = None
    try:
        github_service = GitHubService(redis=redis, settings=settings)
        logger.info("github_service_ready for sync worker", extra={"worker_id": worker_id})
    except Exception as exc:
        logger.warning(
            "sync_worker_github_service_init_failed",
            extra={"worker_id": worker_id, "error": str(exc)},
        )

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _handle_signal():
        logger.info("shutdown_signal_received", extra={"worker_id": worker_id})
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            pass

    # Start worker heartbeat loop
    heartbeat_task = asyncio.create_task(
        _worker_heartbeat_loop(
            redis=redis,
            worker_id=worker_id,
            stop_event=stop_event,
            interval=float(settings.sync_worker_heartbeat_interval_seconds),
            ttl=int(settings.sync_worker_heartbeat_interval_seconds * 3),
        )
    )

    worker_task = asyncio.create_task(
        sync_worker_loop(
            app_or_service=github_service,
            worker_id=worker_id,
            stop_event=stop_event,
        )
    )

    stop_wait_task = asyncio.create_task(stop_event.wait())
    done, pending = await asyncio.wait(
        [worker_task, stop_wait_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    stop_event.set()

    for task in pending:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    if not worker_task.done():
        logger.info("cancelling_worker_task_gracefully", extra={"worker_id": worker_id})
        worker_task.cancel()
        try:
            await worker_task
        except (asyncio.CancelledError, Exception):
            pass

    if not heartbeat_task.done():
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except (asyncio.CancelledError, Exception):
            pass

    try:
        close_redis()
        await close_redis_async()
    except Exception:
        pass

    logger.info("standalone_sync_worker_stopped", extra={"worker_id": worker_id})


def main():
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        logger.exception("sync_worker_fatal_error: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
