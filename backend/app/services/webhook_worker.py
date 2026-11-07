"""Webhook Worker — Durable background processing of queued GitHub webhook events.

Workflow:
1. Atomically claim next available pending/retry event with `FOR UPDATE SKIP LOCKED`.
2. Dispatch event to specialized handler (Push, Installation, PR, Issues).
3. On handler success: mark event as SUCCEEDED.
4. On transient failure: calculate exponential backoff with jitter and mark as RETRY.
5. On fatal failure or when max_attempts is exceeded: mark as DEAD_LETTER.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from app.core.database import SessionLocal
from app.models.webhook_event import GitHubWebhookEvent, WebhookEventStatus
from app.repositories.webhook_event_repository import WebhookEventRepository
from app.services.webhook_handlers import (
    FatalWebhookError,
    RetryableWebhookError,
    WebhookEventDispatcher,
)

logger = logging.getLogger(__name__)


async def process_single_webhook_event(
    event_id: UUID,
    github_service: Any = None,
    dispatcher: WebhookEventDispatcher | None = None,
) -> bool:
    """Execute a single claimed webhook event."""
    if dispatcher is None:
        dispatcher = WebhookEventDispatcher()

    with SessionLocal() as db:
        event_repo = WebhookEventRepository(db)
        event = event_repo.get_by_id(event_id)
        if not event:
            logger.error("webhook_worker_event_not_found", extra={"event_id": str(event_id)})
            return False

        if event.status != WebhookEventStatus.PROCESSING:
            logger.warning(
                "webhook_worker_event_unexpected_status",
                extra={"event_id": str(event_id), "status": str(event.status)},
            )
            return False

        logger.info(
            "webhook_worker_processing_event",
            extra={
                "event_id": str(event.id),
                "event_type": event.event_type,
                "action": event.action,
                "attempt": event.attempts,
            },
        )

        claimed_at = event.claimed_at
        try:
            result = await dispatcher.dispatch(
                event=event,
                db=db,
                github_service=github_service,
            )
            event_repo.mark_succeeded(event.id, expected_claimed_at=claimed_at)
            logger.info(
                "webhook_worker_event_succeeded",
                extra={"event_id": str(event.id), "result": result},
            )
            return True

        except FatalWebhookError as fatal_err:
            db.rollback()
            logger.error(
                "webhook_worker_fatal_error",
                extra={"event_id": str(event.id), "error": str(fatal_err)},
            )
            event_repo.mark_dead_letter(event.id, error_message=str(fatal_err), expected_claimed_at=claimed_at)
            return False

        except RetryableWebhookError as retry_err:
            db.rollback()
            logger.warning(
                "webhook_worker_retryable_error",
                extra={"event_id": str(event.id), "attempt": event.attempts, "error": str(retry_err)},
            )
            if event.attempts >= event.max_attempts:
                logger.error(
                    "webhook_worker_max_attempts_exceeded",
                    extra={"event_id": str(event.id), "attempts": event.attempts},
                )
                event_repo.mark_dead_letter(
                    event.id,
                    error_message=f"Exceeded max attempts ({event.max_attempts}): {retry_err}",
                    expected_claimed_at=claimed_at,
                )
            else:
                event_repo.mark_retry(event.id, error_message=str(retry_err), expected_claimed_at=claimed_at)
            return False

        except Exception as unhandled_err:
            db.rollback()
            logger.exception(
                "webhook_worker_unhandled_error",
                extra={"event_id": str(event.id), "error": str(unhandled_err)},
            )
            if event.attempts >= event.max_attempts:
                event_repo.mark_dead_letter(
                    event.id,
                    error_message=f"Exceeded max attempts ({event.max_attempts}): {unhandled_err}",
                    expected_claimed_at=claimed_at,
                )
            else:
                event_repo.mark_retry(event.id, error_message=str(unhandled_err), expected_claimed_at=claimed_at)
            return False


async def webhook_worker_run_once(
    github_service: Any = None,
    dispatcher: WebhookEventDispatcher | None = None,
    lease_seconds: int = 300,
) -> bool:
    """Claim and process at most one pending webhook event."""
    with SessionLocal() as db:
        event_repo = WebhookEventRepository(db)
        claimed_event = event_repo.claim_next_event(lease_seconds=lease_seconds)

    if not claimed_event:
        return False

    await process_single_webhook_event(
        event_id=claimed_event.id,
        github_service=github_service,
        dispatcher=dispatcher,
    )
    return True


async def webhook_worker_loop(
    app: Any = None,
    stop_event: asyncio.Event | None = None,
    poll_interval: float = 1.0,
) -> None:
    """Long-running worker loop that polls and processes queued webhook events."""
    logger.info("webhook_worker_loop_started")
    dispatcher = WebhookEventDispatcher()

    while True:
        if stop_event and stop_event.is_set():
            logger.info("webhook_worker_loop_stopped_via_event")
            break

        github_service = getattr(app.state, "github_service", None) if app and hasattr(app, "state") else None

        try:
            processed = await webhook_worker_run_once(
                github_service=github_service,
                dispatcher=dispatcher,
            )
            if processed:
                # If an event was processed, drain immediately without delay
                continue

            await asyncio.sleep(poll_interval)

        except asyncio.CancelledError:
            logger.info("webhook_worker_loop_cancelled")
            break
        except Exception as exc:
            logger.error("webhook_worker_loop_iteration_error", extra={"error": str(exc)})
            await asyncio.sleep(poll_interval)
