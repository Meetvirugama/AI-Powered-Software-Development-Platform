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
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Response, status
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.redis import close_redis, close_redis_async, get_redis_async
from app.integrations.github.service import GitHubService
from app.services.sync_worker import RepositoryBusyError, process_sync_job, sync_worker_loop

logger = logging.getLogger(__name__)

__all__ = [
    "RepositoryBusyError",
    "_worker_heartbeat_loop",
    "_worker_retention_maintenance_loop",
    "generate_worker_id",
    "main",
    "process_sync_job",
    "run_worker",
    "sync_worker_loop",
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
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "worker_heartbeat_error",
                extra={"worker_id": worker_id, "error": str(exc)},
            )

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except TimeoutError:
            pass

    # Cleanup heartbeat key on clean exit
    try:
        if hasattr(redis, "delete"):
            await redis.delete(key)
    except (OSError, RuntimeError) as exc:
        logger.debug("Heartbeat key deletion notice: %s", exc)


async def _worker_retention_maintenance_loop(
    stop_event: asyncio.Event,
    interval_seconds: float = 3600.0,
    retention_days: int = 30,
) -> None:
    """Periodic maintenance loop running retention purging on bounded schedule (OPT-21 · TST-26d)."""
    from app.services.analysis_run_history_service import AnalysisRunHistoryService

    history_service = AnalysisRunHistoryService()
    logger.info(
        "retention_maintenance_loop_started",
        extra={"interval_seconds": interval_seconds, "retention_days": retention_days},
    )

    while not stop_event.is_set():
        try:
            # 1. Purge analysis runs older than retention_days
            purged = await asyncio.to_thread(
                history_service.purge_expired_runs, retention_days=retention_days
            )
            if purged > 0:
                logger.info("retention_maintenance_purged_runs", extra={"purged_count": purged})

            # 2. Prune stuck/uncompleted pending runs older than 24h
            pruned = await asyncio.to_thread(
                history_service.prune_uncompleted_stale_runs, older_than_hours=24
            )
            if pruned > 0:
                logger.info(
                    "retention_maintenance_pruned_stale_runs", extra={"pruned_count": pruned}
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug("retention_maintenance_notice: %s", exc)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue


async def run_worker(worker_id: str | None = None, *, stop_event: asyncio.Event | None = None) -> None:
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
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "sync_worker_github_service_init_failed",
            extra={"worker_id": worker_id, "error": str(exc)},
        )

    loop = asyncio.get_running_loop()
    if stop_event is None:
        stop_event = asyncio.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_event.set)
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

    # Start periodic retention maintenance loop (OPT-21 · TST-26d)
    retention_task = asyncio.create_task(
        _worker_retention_maintenance_loop(
            stop_event=stop_event,
            interval_seconds=float(getattr(settings, "retention_purge_interval_seconds", 3600.0)),
            retention_days=int(getattr(settings, "retention_days", 30)),
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
    _done, pending = await asyncio.wait(
        [worker_task, stop_wait_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    stop_event.set()

    for task in pending:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, OSError, RuntimeError):
            pass

    if not worker_task.done():
        logger.info("cancelling_worker_task_gracefully", extra={"worker_id": worker_id})
        worker_task.cancel()
        try:
            await worker_task
        except (asyncio.CancelledError, OSError, RuntimeError):
            pass

    if not retention_task.done():
        retention_task.cancel()
        try:
            await retention_task
        except (asyncio.CancelledError, OSError, RuntimeError):
            pass

    if not heartbeat_task.done():
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except (asyncio.CancelledError, OSError, RuntimeError):
            pass

    try:
        close_redis()
        await close_redis_async()
    except (OSError, RuntimeError) as exc:
        logger.debug("Redis close notice: %s", exc)

    logger.info("standalone_sync_worker_stopped", extra={"worker_id": worker_id})
    if not worker_task.cancelled():
        worker_task.result()


@asynccontextmanager
async def _worker_lifespan(app: FastAPI):
    stop_event = asyncio.Event()
    app.state.worker_id = generate_worker_id()
    app.state.worker = asyncio.create_task(run_worker(app.state.worker_id, stop_event=stop_event))
    try:
        yield
    finally:
        stop_event.set()
        try:
            await app.state.worker
        except Exception:
            logger.exception("sync_worker_failed")


worker_app = FastAPI(lifespan=_worker_lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@worker_app.get("/health")
async def worker_health(response: Response) -> dict[str, str]:
    ready = False
    if not worker_app.state.worker.done():
        try:
            async with asyncio.timeout(2):
                redis = await get_redis_async()
                ready = bool(await redis.exists(f"worker:heartbeat:{worker_app.state.worker_id}"))
        except (OSError, TimeoutError, RuntimeError, RedisError):
            logger.debug("sync_worker_health_check_failed")
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if ready else "not_ready"}


def main():
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass
    except Exception:
        logger.exception("sync_worker_fatal_error")
        sys.exit(1)


if __name__ == "__main__":
    main()
