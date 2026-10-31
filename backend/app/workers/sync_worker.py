"""
Worker entrypoint for background sync jobs.
Connects the Redis `sync_jobs` queue to the processor as a standalone process.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.redis import close_redis, close_redis_async, get_redis_async
from app.integrations.github.service import GitHubService
from app.services.sync_worker import process_sync_job, sync_worker_loop

logger = logging.getLogger(__name__)

__all__ = ["process_sync_job", "sync_worker_loop", "run_worker", "main"]


async def run_worker() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info("Starting standalone sync worker process...")

    redis = await get_redis_async()
    github_service = None
    try:
        github_service = GitHubService(redis=redis, settings=settings)
        logger.info("github_service_ready for sync worker")
    except Exception as exc:
        logger.warning("sync_worker_github_service_init_failed", extra={"error": str(exc)})

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _handle_signal():
        logger.info("Shutdown signal received. Stopping worker loop...")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            pass

    worker_task = asyncio.create_task(sync_worker_loop(github_service))

    # Wait until stop event is set or worker task terminates
    done, pending = await asyncio.wait(
        [worker_task, asyncio.create_task(stop_event.wait())],
        return_when=asyncio.FIRST_COMPLETED,
    )

    if not worker_task.done():
        logger.info("Cancelling worker task gracefully...")
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass

    try:
        close_redis()
        await close_redis_async()
    except Exception:
        pass

    logger.info("Standalone sync worker process stopped.")


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
