"""MCP Elicitation Service.

Part of F19 — Human approval gate (Issue #199).
Implements Model Context Protocol (MCP) Spec (2025-11-25) Form and URL Elicitation
with schema validation, SSRF protection, session isolation, and non-bypass guarantees.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import ipaddress
import logging
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

try:
    import jsonschema  # type: ignore[import-untyped]
except ImportError:
    jsonschema = None  # type: ignore[assignment]

from agent.tools.schema_validator import default_schema_validator
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.errors import APIError, ErrorCode
from app.core.secret_redaction import redact_obj
from app.models.task import AgentTask, TaskApproval

logger = logging.getLogger(__name__)


def _as_utc(dt: datetime | None) -> datetime | None:
    """Normalize datetime to timezone-aware UTC datetime."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


ALLOWED_FIELD_TYPES = {"string", "number", "integer", "boolean", "array", "object"}
BLOCKED_HOSTS = {
    "169.254.169.254",
    "100.100.100.200",
    "metadata.google.internal",
    "metadata.local",
    "instance-data",
    "0.0.0.0",
    "::",
}


def validate_mcp_url(url: str) -> str:
    """Validate MCP URL for scheme safety and SSRF prevention.

    Strictly enforces HTTPS (HTTP permitted only on localhost / 127.0.0.1 / ::1 for development).
    Blocks cloud metadata endpoints, link-local, private RFC1918, unspecified, reserved,
    multicast, non-localhost loopback, and IPv4-mapped IPv6 addresses.
    Rejects unsafe schemes such as javascript:, data:, file:, ftp:, embedded credentials,
    and control/newline characters.
    """
    if not url or not isinstance(url, str):
        raise APIError(400, ErrorCode.MCP_SECURITY_VIOLATION, "URL must be a non-empty string")

    stripped = url.strip()
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in stripped):
        raise APIError(400, ErrorCode.MCP_SECURITY_VIOLATION, "URL contains forbidden control characters")

    try:
        parsed = urlparse(stripped)
    except Exception as exc:
        raise APIError(400, ErrorCode.MCP_SECURITY_VIOLATION, f"Malformed URL: {exc}")

    if not parsed.scheme or not parsed.netloc:
        raise APIError(400, ErrorCode.MCP_SECURITY_VIOLATION, "Invalid URL structure: missing scheme or host")

    if parsed.username is not None or parsed.password is not None:
        raise APIError(400, ErrorCode.MCP_SECURITY_VIOLATION, "Embedded credentials in MCP URLs are forbidden")

    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname:
        raise APIError(400, ErrorCode.MCP_SECURITY_VIOLATION, "Invalid URL structure: missing hostname")

    is_dev_loopback = hostname in ("localhost", "127.0.0.1", "::1")

    if is_dev_loopback:
        if scheme not in ("http", "https"):
            raise APIError(
                400,
                ErrorCode.MCP_SECURITY_VIOLATION,
                f"Unsupported scheme '{scheme}' for localhost. Only http and https are permitted.",
            )
    else:
        if scheme != "https":
            raise APIError(
                400,
                ErrorCode.MCP_SECURITY_VIOLATION,
                f"Forbidden scheme '{scheme}'. Only https is allowed for external URLs.",
            )

    if hostname in BLOCKED_HOSTS or hostname.endswith(".internal") or hostname.endswith(".local"):
        raise APIError(
            403,
            ErrorCode.MCP_SECURITY_VIOLATION,
            f"Access to restricted cloud metadata or internal endpoint '{hostname}' is strictly forbidden.",
        )

    try:
        ip = ipaddress.ip_address(hostname)
        mapped = getattr(ip, "ipv4_mapped", None)
        check_ips = [ip, mapped] if mapped is not None else [ip]
        for candidate_ip in check_ips:
            if str(candidate_ip) in BLOCKED_HOSTS or candidate_ip.is_link_local:
                raise APIError(
                    403,
                    ErrorCode.MCP_SECURITY_VIOLATION,
                    f"Link-local or cloud metadata IP address '{hostname}' is blocked.",
                )
            if not is_dev_loopback and (
                candidate_ip.is_private
                or candidate_ip.is_loopback
                or candidate_ip.is_unspecified
                or candidate_ip.is_reserved
                or candidate_ip.is_multicast
            ):
                raise APIError(
                    403,
                    ErrorCode.MCP_SECURITY_VIOLATION,
                    f"Private, loopback, or reserved IP address '{hostname}' is blocked.",
                )
    except ValueError:
        pass

    return stripped


def validate_mcp_form_schema(schema: dict[str, Any]) -> None:
    """Validate that the MCP form schema contains safe, supported field definitions."""
    if not isinstance(schema, dict):
        raise APIError(400, ErrorCode.MCP_ELICITATION_ERROR, "Form schema must be a dictionary")

    schema_type = schema.get("type", "object")
    if schema_type != "object":
        raise APIError(400, ErrorCode.MCP_ELICITATION_ERROR, "Top-level form schema type must be 'object'")

    properties = schema.get("properties")
    if properties is not None and not isinstance(properties, dict):
        raise APIError(400, ErrorCode.MCP_ELICITATION_ERROR, "Schema 'properties' must be a dictionary")

    for prop_name, prop_def in (properties or {}).items():
        if not isinstance(prop_def, dict):
            raise APIError(
                400,
                ErrorCode.MCP_ELICITATION_ERROR,
                f"Property '{prop_name}' definition must be a dictionary",
            )
        ptype = prop_def.get("type")
        if ptype and ptype not in ALLOWED_FIELD_TYPES:
            raise APIError(
                400,
                ErrorCode.MCP_ELICITATION_ERROR,
                f"Unsupported field type '{ptype}' in property '{prop_name}'. Allowed: {sorted(ALLOWED_FIELD_TYPES)}",
            )


def validate_mcp_form_response(schema: dict[str, Any], data: dict[str, Any]) -> None:
    """Validate user response data against the form schema using jsonschema or SchemaValidator fallback."""
    if not isinstance(data, dict):
        raise APIError(400, ErrorCode.MCP_ELICITATION_ERROR, "Response data must be a dictionary")
    if jsonschema is not None:
        try:
            jsonschema.validate(instance=data, schema=schema)
            return
        except jsonschema.ValidationError as exc:
            raise APIError(400, ErrorCode.MCP_ELICITATION_ERROR, f"Form validation failed: {exc.message}")
        except Exception as exc:
            raise APIError(400, ErrorCode.MCP_ELICITATION_ERROR, f"Schema validation error: {exc}")

    err = default_schema_validator.validate_arguments(data, schema)
    if err is not None:
        raise APIError(400, ErrorCode.MCP_ELICITATION_ERROR, f"Form validation failed: {err}")


class MCPElicitationService:
    """Service managing MCP Form and URL Elicitations per MCP Spec 2025-11-25."""

    def __init__(self, default_ttl_seconds: int = 3600) -> None:
        self.default_ttl_seconds = default_ttl_seconds

    def request_form_elicitation(
        self,
        session: Session,
        task: AgentTask,
        session_id: str,
        prompt: str,
        schema: dict[str, Any],
        user_id: UUID | None = None,
        expires_in_seconds: int | None = None,
    ) -> TaskApproval:
        """Create a pending Form Elicitation request."""
        if not session_id or not isinstance(session_id, str):
            raise APIError(400, ErrorCode.BAD_REQUEST, "session_id is required")
        if not prompt or not isinstance(prompt, str):
            raise APIError(400, ErrorCode.BAD_REQUEST, "prompt is required")

        validate_mcp_form_schema(schema)
        now = datetime.now(timezone.utc)
        ttl = expires_in_seconds or self.default_ttl_seconds

        elicitation = TaskApproval(
            task_id=task.id,
            plan_id=getattr(task, "approved_plan_id", None),
            plan_version=getattr(task, "approved_plan_version", 1) or 1,
            user_id=user_id,
            plan_hash="",
            decision="PENDING",
            feedback=None,
            approval_type="mcp_elicitation",
            elicitation_type="form",
            session_id=session_id.strip(),
            elicitation_payload={"prompt": prompt.strip(), "schema": schema},
            status="pending",
            expires_at=now + timedelta(seconds=ttl),
        )
        session.add(elicitation)
        session.commit()
        session.refresh(elicitation)
        logger.info(
            "Created MCP Form Elicitation %s for task %s (session: %s)",
            elicitation.id,
            task.id,
            session_id,
        )
        try:
            from app.services.sse_redis_streams import emit_sse_event_nonblocking, publish_mcp_notification
            emit_sse_event_nonblocking(
                publish_mcp_notification(
                    user_id=str(user_id or getattr(task, "user_id", None) or "system"),
                    channel="platform_events",
                    server_name="mcp-platform-core",
                    method="elicitation/create",
                    params={"elicitation_id": str(elicitation.id), "type": "form", "session_id": session_id.strip()},
                    kind="elicitation",
                )
            )
        except Exception:
            pass
        return elicitation

    def request_url_elicitation(
        self,
        session: Session,
        task: AgentTask,
        session_id: str,
        url: str,
        purpose: str,
        user_id: UUID | None = None,
        expires_in_seconds: int | None = None,
    ) -> TaskApproval:
        """Create a pending URL Elicitation request."""
        if not session_id or not isinstance(session_id, str):
            raise APIError(400, ErrorCode.BAD_REQUEST, "session_id is required")
        if not purpose or not isinstance(purpose, str):
            raise APIError(400, ErrorCode.BAD_REQUEST, "purpose is required")

        validated_url = validate_mcp_url(url)
        now = datetime.now(timezone.utc)
        ttl = expires_in_seconds or self.default_ttl_seconds

        elicitation = TaskApproval(
            task_id=task.id,
            plan_id=getattr(task, "approved_plan_id", None),
            plan_version=getattr(task, "approved_plan_version", 1) or 1,
            user_id=user_id,
            plan_hash="",
            decision="PENDING",
            feedback=None,
            approval_type="mcp_elicitation",
            elicitation_type="url",
            session_id=session_id.strip(),
            elicitation_payload={"url": validated_url, "purpose": purpose.strip()},
            status="pending",
            expires_at=now + timedelta(seconds=ttl),
        )
        session.add(elicitation)
        session.commit()
        session.refresh(elicitation)
        logger.info(
            "Created MCP URL Elicitation %s for task %s (session: %s)",
            elicitation.id,
            task.id,
            session_id,
        )
        return elicitation

    def submit_response(
        self,
        session: Session,
        task_id: UUID,
        elicitation_id: UUID,
        session_id: str,
        action: str,
        data: dict[str, Any] | None = None,
        user_id: UUID | None = None,
    ) -> TaskApproval:
        """Submit a user response (submit or cancel) to a pending MCP elicitation."""
        elicitation = session.execute(
            select(TaskApproval).where(
                TaskApproval.task_id == task_id,
                TaskApproval.id == elicitation_id,
            )
        ).scalars().first()

        if not elicitation:
            raise APIError(404, ErrorCode.RESOURCE_NOT_FOUND, "Elicitation record not found")

        if elicitation.approval_type != "mcp_elicitation":
            raise APIError(400, ErrorCode.BAD_REQUEST, "Record is not an MCP elicitation")

        # Session boundary check: cross-session responses rejected
        if elicitation.session_id != session_id.strip():
            raise APIError(
                403,
                ErrorCode.FORBIDDEN,
                f"Session mismatch: elicitation belongs to session '{elicitation.session_id}'",
            )

        # Duplicate / terminal state check
        if elicitation.status != "pending":
            raise APIError(
                409,
                ErrorCode.CONFLICT,
                f"Elicitation cannot accept response in state '{elicitation.status}'",
            )

        now = datetime.now(timezone.utc)
        exp = _as_utc(elicitation.expires_at)
        if exp and exp < now:
            elicitation.status = "expired"
            elicitation.decision = "EXPIRED"
            session.commit()
            raise APIError(410, ErrorCode.APPROVAL_EXPIRED, "Elicitation request has expired")

        normalized_action = action.strip().lower()
        if normalized_action in ("submit", "confirm", "approve"):
            if elicitation.elicitation_type == "form":
                schema = (elicitation.elicitation_payload or {}).get("schema", {})
                validate_mcp_form_response(schema, data or {})
                elicitation.elicitation_response = redact_obj(data or {})
            elif elicitation.elicitation_type == "url":
                elicitation.elicitation_response = {"confirmed": True, "data": redact_obj(data or {})}
            else:
                elicitation.elicitation_response = redact_obj(data or {})

            elicitation.status = "consumed"
            elicitation.decision = "APPROVED"
            elicitation.consumed_at = now
            elicitation.user_id = user_id or elicitation.user_id
        elif normalized_action in ("cancel", "reject"):
            elicitation.status = "rejected"
            elicitation.decision = "REJECTED"
            elicitation.elicitation_response = {"cancelled": True}
            elicitation.user_id = user_id or elicitation.user_id
        else:
            raise APIError(
                400,
                ErrorCode.BAD_REQUEST,
                f"Invalid elicitation action '{action}'. Allowed: submit, cancel",
            )

        session.commit()
        session.refresh(elicitation)
        logger.info(
            "MCP Elicitation %s updated with action '%s' by user %s",
            elicitation.id,
            normalized_action,
            user_id,
        )
        return elicitation

    def cancel_elicitation(
        self,
        session: Session,
        task_id: UUID,
        elicitation_id: UUID,
        session_id: str,
        user_id: UUID | None = None,
    ) -> TaskApproval:
        """Cancel a pending MCP elicitation."""
        return self.submit_response(
            session=session,
            task_id=task_id,
            elicitation_id=elicitation_id,
            session_id=session_id,
            action="cancel",
            user_id=user_id,
        )

    def list_elicitations(
        self,
        session: Session,
        task_id: UUID,
        session_id: str | None = None,
        status: str | None = None,
    ) -> list[TaskApproval]:
        """List MCP elicitations for a task, optionally filtered by session_id and status."""
        query = select(TaskApproval).where(
            TaskApproval.task_id == task_id,
            TaskApproval.approval_type == "mcp_elicitation",
        )
        if session_id:
            query = query.where(TaskApproval.session_id == session_id.strip())
        if status:
            query = query.where(TaskApproval.status == status.lower())
        query = query.order_by(desc(TaskApproval.created_at))
        return list(session.execute(query).scalars().all())


# Singleton instance
mcp_elicitation_service = MCPElicitationService()
