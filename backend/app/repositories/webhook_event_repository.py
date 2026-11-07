"""Repository for durable GitHub webhook event persistence, atomic worker claims, and lifecycle management."""

from __future__ import annotations

import logging
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import false, func, or_, select
from sqlalchemy.orm import Session

from app.core.secret_redaction import redact
from app.models.webhook_event import GitHubWebhookEvent, WebhookEventStatus

logger = logging.getLogger(__name__)

def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _sanitize_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Recursively redact secrets and omit sensitive keys from webhook payload before DB storage."""
    if not payload:
        return {}
    sanitized: dict[str, Any] = {}
    for k, v in payload.items():
        if k in ("token", "access_token", "secret", "client_secret", "private_key", "password"):
            sanitized[k] = "[REDACTED]"
        elif isinstance(v, dict):
            sanitized[k] = _sanitize_payload(v)
        elif isinstance(v, list):
            sanitized[k] = [
                _sanitize_payload(item) if isinstance(item, dict)
                else (redact(item) if isinstance(item, str) else item)
                for item in v
            ]
        elif isinstance(v, str):
            sanitized[k] = redact(v)
        else:
            sanitized[k] = v
    return sanitized


def compute_backoff_seconds(attempts: int, base: float = 5.0, max_backoff: float = 3600.0) -> int:
    """Calculate exponential backoff with full jitter in seconds."""
    backoff = min(max_backoff, base * (2 ** max(0, attempts - 1)))
    jitter = random.uniform(0.5, 1.5)
    return max(1, int(backoff * jitter))


class WebhookEventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_delivery_id(self, delivery_id: str) -> Optional[GitHubWebhookEvent]:
        stmt = select(GitHubWebhookEvent).where(GitHubWebhookEvent.delivery_id == delivery_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def get_by_id(self, event_id: uuid.UUID) -> Optional[GitHubWebhookEvent]:
        return self.session.get(GitHubWebhookEvent, event_id)

    def create_event(
        self,
        delivery_id: str,
        event_type: str,
        action: str | None = None,
        installation_id: str | None = None,
        repository_id: uuid.UUID | None = None,
        github_repo_id: str | None = None,
        payload: dict[str, Any] | None = None,
        max_attempts: int = 5,
    ) -> tuple[GitHubWebhookEvent, bool]:
        """
        Durably persist a webhook event.
        Returns (event, created): created is True if new, False if already existed.
        """
        existing = self.get_by_delivery_id(delivery_id)
        if existing:
            return existing, False

        now = datetime.now(timezone.utc)
        safe_payload = _sanitize_payload(payload)
        event = GitHubWebhookEvent(
            id=uuid.uuid4(),
            delivery_id=delivery_id,
            event_type=event_type,
            action=action,
            installation_id=installation_id,
            repository_id=repository_id,
            github_repo_id=github_repo_id,
            payload=safe_payload,
            status=WebhookEventStatus.PENDING,
            attempts=0,
            max_attempts=max_attempts,
            available_at=now,
            created_at=now,
            updated_at=now,
        )
        self.session.add(event)
        self.session.commit()
        self.session.refresh(event)
        return event, True

    def claim_next_event(self, lease_seconds: int = 300) -> Optional[GitHubWebhookEvent]:
        """
        Atomically claim the next eligible pending/retry event or recover an expired lease.
        Uses PostgreSQL SELECT ... FOR UPDATE SKIP LOCKED (with SQLite fallback).
        """
        now = datetime.now(timezone.utc)
        stmt = (
            select(GitHubWebhookEvent)
            .where(
                or_(
                    (GitHubWebhookEvent.status == WebhookEventStatus.PENDING)
                    & (GitHubWebhookEvent.available_at <= now),
                    (GitHubWebhookEvent.status == WebhookEventStatus.RETRY)
                    & (GitHubWebhookEvent.available_at <= now),
                    (GitHubWebhookEvent.status == WebhookEventStatus.PROCESSING)
                    & (GitHubWebhookEvent.lease_expires_at.is_not(None))
                    & (GitHubWebhookEvent.lease_expires_at <= now),
                )
            )
            .order_by(GitHubWebhookEvent.created_at.asc())
            .limit(1)
        )

        # Support FOR UPDATE SKIP LOCKED if supported by database dialect
        try:
            bind = self.session.get_bind()
            dialect_name = getattr(getattr(bind, "dialect", None), "name", "")
        except Exception:
            dialect_name = ""
        if dialect_name == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)

        event = self.session.execute(stmt).scalar_one_or_none()
        if not event:
            return None

        if event.status == WebhookEventStatus.PROCESSING and event.attempts >= event.max_attempts:
            event.status = WebhookEventStatus.DEAD_LETTER
            event.processed_at = now
            event.lease_expires_at = None
            event.last_error = "Lease expired after max attempts (worker crash suspected)."
            event.updated_at = now
            self.session.commit()
            return None

        event.status = WebhookEventStatus.PROCESSING
        event.claimed_at = now
        event.lease_expires_at = now + timedelta(seconds=lease_seconds)
        event.attempts += 1
        event.updated_at = now
        self.session.commit()
        self.session.refresh(event)
        return event

    def mark_succeeded(
        self,
        event_id: uuid.UUID,
        expected_claimed_at: datetime | None = None,
    ) -> Optional[GitHubWebhookEvent]:
        event = self.session.get(GitHubWebhookEvent, event_id)
        if not event:
            return None
        if expected_claimed_at is not None and event.claimed_at != expected_claimed_at:
            logger.warning("webhook_fencing_token_mismatch_succeeded", extra={"event_id": str(event_id)})
            return None
        now = datetime.now(timezone.utc)
        event.status = WebhookEventStatus.SUCCEEDED
        event.processed_at = now
        event.lease_expires_at = None
        event.updated_at = now
        self.session.commit()
        return event

    def mark_retry(
        self,
        event_id: uuid.UUID,
        error_message: str,
        backoff_seconds: int | None = None,
        base_backoff_seconds: int | None = None,
        expected_claimed_at: datetime | None = None,
    ) -> Optional[GitHubWebhookEvent]:
        event = self.session.get(GitHubWebhookEvent, event_id)
        if not event:
            return None
        if expected_claimed_at is not None and event.claimed_at != expected_claimed_at:
            logger.warning("webhook_fencing_token_mismatch_retry", extra={"event_id": str(event_id)})
            return None
        now = datetime.now(timezone.utc)
        safe_error = redact(str(error_message))[:2000]
        if event.attempts >= event.max_attempts:
            return self.mark_dead_letter(
                event_id,
                f"Exhausted max retries ({event.max_attempts}): {safe_error}",
                expected_claimed_at=expected_claimed_at,
            )

        eff_backoff = backoff_seconds if backoff_seconds is not None else base_backoff_seconds
        delay = eff_backoff if eff_backoff is not None else compute_backoff_seconds(event.attempts)
        event.status = WebhookEventStatus.RETRY
        event.available_at = now + timedelta(seconds=delay)
        event.lease_expires_at = None
        event.last_error = safe_error
        event.updated_at = now
        self.session.commit()
        return event

    def mark_dead_letter(
        self,
        event_id: uuid.UUID,
        error_message: str,
        expected_claimed_at: datetime | None = None,
    ) -> Optional[GitHubWebhookEvent]:
        event = self.session.get(GitHubWebhookEvent, event_id)
        if not event:
            return None
        if expected_claimed_at is not None and event.claimed_at != expected_claimed_at:
            logger.warning("webhook_fencing_token_mismatch_dead_letter", extra={"event_id": str(event_id)})
            return None
        now = datetime.now(timezone.utc)
        event.status = WebhookEventStatus.DEAD_LETTER
        event.processed_at = now
        event.lease_expires_at = None
        event.last_error = redact(str(error_message))[:2000]
        event.updated_at = now
        self.session.commit()
        return event

    def replay_event(self, event_id: uuid.UUID) -> GitHubWebhookEvent:
        """Safely reset a failed or dead-letter event to PENDING."""
        event = self.session.get(GitHubWebhookEvent, event_id)
        if not event:
            raise ValueError(f"Webhook event {event_id} not found.")

        now = datetime.now(timezone.utc)
        if event.status in (WebhookEventStatus.PENDING, WebhookEventStatus.SUCCEEDED):
            raise ValueError(f"Cannot replay an event with status '{event.status.value}'. Only failed, retry, or dead-letter events can be replayed.")

        if event.status == WebhookEventStatus.PROCESSING:
            lease_exp = event.lease_expires_at
            if lease_exp:
                if lease_exp.tzinfo is None:
                    lease_exp = lease_exp.replace(tzinfo=timezone.utc)
                if lease_exp > now:
                    raise ValueError("Cannot replay an event that is actively PROCESSING.")

        event.status = WebhookEventStatus.PENDING
        event.available_at = now
        event.lease_expires_at = None
        event.attempts = 0
        event.last_error = None
        event.replay_count += 1
        event.last_replayed_at = now
        event.updated_at = now
        self.session.commit()
        self.session.refresh(event)
        return event

    def list_events(
        self,
        status: WebhookEventStatus | None = None,
        event_type: str | None = None,
        repository_id: uuid.UUID | None = None,
        repository_ids: list[uuid.UUID] | None = None,
        installation_ids: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[GitHubWebhookEvent], int]:
        stmt = select(GitHubWebhookEvent)
        count_stmt = select(func.count(GitHubWebhookEvent.id))

        if status:
            stmt = stmt.where(GitHubWebhookEvent.status == status)
            count_stmt = count_stmt.where(GitHubWebhookEvent.status == status)
        if event_type:
            stmt = stmt.where(GitHubWebhookEvent.event_type == event_type)
            count_stmt = count_stmt.where(GitHubWebhookEvent.event_type == event_type)
        if repository_id:
            stmt = stmt.where(GitHubWebhookEvent.repository_id == repository_id)
            count_stmt = count_stmt.where(GitHubWebhookEvent.repository_id == repository_id)
        elif repository_ids is not None or installation_ids is not None:
            scope_conditions = []
            if repository_ids:
                scope_conditions.append(GitHubWebhookEvent.repository_id.in_(repository_ids))
            if installation_ids:
                scope_conditions.append(GitHubWebhookEvent.installation_id.in_(installation_ids))
            if scope_conditions:
                stmt = stmt.where(or_(*scope_conditions))
                count_stmt = count_stmt.where(or_(*scope_conditions))
            else:
                stmt = stmt.where(false())
                count_stmt = count_stmt.where(false())

        total = self.session.execute(count_stmt).scalar() or 0
        events = list(
            self.session.execute(
                stmt.order_by(GitHubWebhookEvent.created_at.desc()).limit(limit).offset(offset)
            )
            .scalars()
            .all()
        )
        return events, total
