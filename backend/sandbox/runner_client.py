"""HTTP Client for Dedicated Runner Service.

Owner: AI Platform Security Architecture — Issue #200 / F20
Reference: Docs/security/sandbox/03-target-architecture.md, 04-runner-service-design.md
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings
from app.schemas.workspace import WorkspaceCommandResult

from sandbox.backend import SandboxBackend
from sandbox.exceptions import (
    RunnerAuthenticationError,
    RunnerUnavailableError,
    SandboxSecurityError,
    WorkspaceCommandError,
    WorkspaceError,
)

logger = logging.getLogger(__name__)


class RunnerClient(SandboxBackend):
    """Client implementing SandboxBackend by delegating to a remote Runner Service."""

    def __init__(
        self,
        base_url: str | None = None,
        auth_secret: str | None = None,
        timeout: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = (
            base_url or getattr(settings, "runner_base_url", None) or "http://localhost:8080"
        ).rstrip("/")
        self._auth_secret = auth_secret or getattr(settings, "runner_auth_secret", "") or ""
        self._timeout = timeout or getattr(settings, "runner_request_timeout", 60.0)
        self._transport = transport
        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=self._timeout,
            transport=self._transport,
            headers={
                "X-Runner-Token": self._auth_secret,
                "Authorization": f"Bearer {self._auth_secret}",
                "Content-Type": "application/json",
            },
        )

    @property
    def backend_type(self) -> str:
        return "runner"

    def _handle_http_error(self, exc: Exception, action: str) -> None:
        """Map HTTP and connection exceptions to sandbox architecture error types."""
        if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout)):
            logger.error(f"Runner service unreachable during {action}: {exc}")
            raise RunnerUnavailableError(
                f"Runner service at '{self._base_url}' is unreachable during {action}: {exc}. "
                "Production execution fails closed; no uncontained fallback is permitted."
            ) from exc
        if isinstance(exc, httpx.HTTPStatusError):
            code = exc.response.status_code
            text = exc.response.text
            if code == 401:
                raise RunnerAuthenticationError(f"Runner authentication failed (401): {text}") from exc
            if code == 400:
                raise SandboxSecurityError(f"Runner rejected request as invalid/unsafe (400): {text}") from exc
            raise WorkspaceError(f"Runner returned error HTTP {code}: {text}") from exc
        raise WorkspaceError(f"Unexpected error communicating with runner during {action}: {exc}") from exc

    def create_workspace(
        self,
        task_id: str,
        base_repo_path: Path | None = None,
    ) -> Path:
        try:
            resp = self._client.post(
                "/internal/v1/workspaces",
                json={
                    "task_id": task_id,
                    "base_repo_path": str(base_repo_path) if base_repo_path else None,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return Path(data["workspace_path"])
        except Exception as exc:
            self._handle_http_error(exc, "create_workspace")
            return Path(f"/sandbox/workspaces/{task_id}")

    def execute(
        self,
        task_id: str,
        command: str,
        arguments: Sequence[str] | None = None,
        cwd: Path | None = None,
        timeout_seconds: int | None = None,
        custom_env: Mapping[str, str] | None = None,
        network_enabled: bool = False,
    ) -> WorkspaceCommandResult:
        try:
            resp = self._client.post(
                f"/internal/v1/workspaces/{task_id}/exec",
                json={
                    "command": command,
                    "arguments": list(arguments or []),
                    "cwd": str(cwd) if cwd else None,
                    "timeout_seconds": timeout_seconds or 30,
                    "custom_env": dict(custom_env or {}),
                    "network_enabled": network_enabled,
                },
            )
            resp.raise_for_status()
            return WorkspaceCommandResult.model_validate(resp.json())
        except Exception as exc:
            self._handle_http_error(exc, "execute")
            # Should not reach here due to exception raise
            raise WorkspaceCommandError(f"Execution failed: {exc}") from exc

    def read_file(self, task_id: str, relative_path: str) -> str:
        try:
            resp = self._client.get(
                f"/internal/v1/workspaces/{task_id}/files",
                params={"path": relative_path},
            )
            resp.raise_for_status()
            return resp.json()["content"]
        except Exception as exc:
            self._handle_http_error(exc, "read_file")
            return ""

    def write_file(self, task_id: str, relative_path: str, content: str) -> None:
        try:
            resp = self._client.put(
                f"/internal/v1/workspaces/{task_id}/files",
                json={"path": relative_path, "content": content},
            )
            resp.raise_for_status()
        except Exception as exc:
            self._handle_http_error(exc, "write_file")

    def get_diff(self, task_id: str) -> str:
        try:
            resp = self._client.get(f"/internal/v1/workspaces/{task_id}/diff")
            resp.raise_for_status()
            return resp.json().get("diff", "")
        except Exception as exc:
            self._handle_http_error(exc, "get_diff")
            return ""

    def destroy_workspace(self, task_id: str) -> None:
        try:
            resp = self._client.delete(f"/internal/v1/workspaces/{task_id}")
            resp.raise_for_status()
        except Exception as exc:
            self._handle_http_error(exc, "destroy_workspace")

    def get_status(self, task_id: str) -> dict[str, Any]:
        try:
            resp = self._client.get(f"/internal/v1/workspaces/{task_id}/status")
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            self._handle_http_error(exc, "get_status")
            return {"status": "UNKNOWN"}

    def get_resource_usage(self, task_id: str) -> dict[str, Any]:
        status_data = self.get_status(task_id)
        return status_data.get("details", {})
