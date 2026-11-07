"""Standalone worker entrypoint for durable GitHub webhook event processing.

Claims pending/retry webhook events, recovers expired leases, and dispatches to specialized handlers.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import Any

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.redis import close_redis, close_redis_async, get_redis_async
from app.integrations.github.service import GitHubService
from app.services.webhook_worker import (
    process_single_webhook_event,
    webhook_worker_loop,
    webhook_worker_run_once,
)

logger = logging.getLogger(__name__)

__all__ = [
    "process_single_webhook_event",
    "webhook_worker_run_once",
    "webhook_worker_loop",
    "run_worker",
    "main",
]


class _WorkerAppState:
    def __init__(self, github_service: Any = None) -> None:
        self.github_service = github_service


class _WorkerApp:
    def __init__(self, github_service: Any = None) -> None:
        self.state = _WorkerAppState(github_service=github_service)


async def run_worker() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info("Starting standalone webhook worker process...")

    redis = await get_redis_async()
    github_service = None
    try:
        github_service = GitHubService(redis=redis, settings=settings)
        logger.info("github_service_ready for webhook worker")
    except Exception as exc:
        logger.warning("webhook_worker_github_service_init_failed", extra={"error": str(exc)})

    app_proxy = _WorkerApp(github_service=github_service)
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _handle_signal():
        logger.info("Shutdown signal received. Stopping webhook worker loop...")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            pass

    worker_task = asyncio.create_task(
        webhook_worker_loop(app=app_proxy, stop_event=stop_event)
    )

    stop_wait_task = asyncio.create_task(stop_event.wait())
    done, pending = await asyncio.wait(
        [worker_task, stop_wait_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    for task in pending:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    if not worker_task.done():
        logger.info("Cancelling worker task gracefully...")
        worker_task.cancel()
        try:
            await worker_task
        except (asyncio.CancelledError, Exception):
            pass

    try:
        close_redis()
        await close_redis_async()
    except Exception:
        pass

    logger.info("Standalone webhook worker process stopped.")


def main():
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        logger.exception("webhook_worker_fatal_error: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
