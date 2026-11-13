"""Internal Runner Service Application.

Owner: AI Platform Security Architecture — Issue #200 / F20
Reference: Docs/security/sandbox/04-runner-service-design.md
"""

from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.secret_redaction import redact
from app.schemas.workspace import WorkspaceCommandResult
from runner.schemas import (
    RunnerCreateWorkspaceRequest,
    RunnerCreateWorkspaceResponse,
    RunnerDiffResponse,
    RunnerExecuteRequest,
    RunnerFileReadResponse,
    RunnerFileWriteRequest,
    RunnerFileWriteResponse,
    RunnerStatusResponse,
)
from sandbox.backend import SandboxBackend
from sandbox.container_backend import ContainerBackend
from sandbox.exceptions import (
    SandboxSecurityError,
    WorkspaceCommandError,
    WorkspaceError,
    WorkspacePathEscapeError,
    WorkspacePolicyViolationError,
)
from sandbox.local_backend import LocalSubprocessBackend

logger = logging.getLogger(__name__)

_FORBIDDEN_BASE_REPO_PREFIXES = (
    "/etc",
    "/proc",
    "/sys",
    "/root",
    "/dev",
    "/boot",
    "/var/run",
    "/private/etc",
    "/private/var/run",
)


def _validate_base_repo_path(raw_path: str | None) -> Path | None:
    if not raw_path:
        return None
    raw_base = Path(raw_path)
    if ".." in raw_base.parts or raw_base.is_symlink():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Forbidden base_repo_path: traversal or symlink not allowed.",
        )
    resolved = raw_base.resolve()
    for prefix in _FORBIDDEN_BASE_REPO_PREFIXES:
        pref_path = Path(prefix)
        if resolved == pref_path or resolved.is_relative_to(pref_path):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Forbidden base_repo_path: system directory '{prefix}' is prohibited.",
            )
    return resolved


def get_runner_secret() -> str:
    """Retrieve the expected secret token for authenticating runner requests."""
    secret = getattr(settings, "runner_auth_secret", None) or os.environ.get("RUNNER_AUTH_SECRET", "")
    return secret.strip() if secret else ""


def verify_runner_auth(
    request: Request,
    x_runner_token: str | None = Header(default=None, alias="X-Runner-Token"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> str:
    """Authenticate internal API calls using constant-time comparison."""
    expected = get_runner_secret()
    if not expected:
        # Fail closed by default even in development. Permit unauthenticated development
        # access only behind an explicit opt-in setting AND when binding/connecting to a loopback address.
        allow_unauth = (
            getattr(settings, "runner_allow_unauthenticated_dev", False)
            or os.environ.get("RUNNER_ALLOW_UNAUTHENTICATED_DEV", "").strip().lower() in ("true", "1")
        )
        client_host = request.client.host if (request and request.client) else None
        is_loopback = client_host in ("127.0.0.1", "::1", "localhost", "testclient")
        if (
            not getattr(settings, "is_production", False)
            and getattr(settings, "app_env", "") == "development"
            and allow_unauth
            and is_loopback
        ):
            return "dev-unauthenticated"
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Runner service is missing RUNNER_AUTH_SECRET configuration.",
        )

    provided = ""
    if x_runner_token:
        provided = x_runner_token.strip()
    elif authorization:
        parts = authorization.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            provided = parts[1].strip()

    if not provided or not secrets.compare_digest(provided, expected):
        logger.warning("runner_unauthorized_access_attempt")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing runner authentication token.",
        )
    return provided


def create_runner_app(backend: SandboxBackend | None = None) -> FastAPI:
    """Construct and configure the Runner Service FastAPI application."""
    runner_app = FastAPI(
        title="Agentic Software Development Platform — Secure Runner Service",
        version="1.0.0",
        docs_url=None if getattr(settings, "is_production", False) else "/docs",
        redoc_url=None,
    )

    # Initialize execution backend
    if backend is not None:
        exec_backend = backend
    else:
        # Default to ContainerBackend; fallback to LocalSubprocessBackend strictly in dev
        try:
            exec_backend = ContainerBackend()
        except Exception as exc:
            if not getattr(settings, "is_production", False):
                logger.warning(f"Container backend unavailable, using local dev backend: {exc}")
                exec_backend = LocalSubprocessBackend()
            else:
                raise

    @runner_app.get("/health")
    def health_check() -> dict[str, Any]:
        """Health check endpoint reporting runner readiness and gVisor status."""
        gvisor = getattr(exec_backend, "gvisor_available", False)
        return {
            "status": "healthy",
            "service": "secure-runner-service",
            "backend": exec_backend.backend_type,
            "gvisor_verified": gvisor,
            "environment": getattr(settings, "app_env", "development"),
        }

    @runner_app.post(
        "/internal/v1/workspaces",
        response_model=RunnerCreateWorkspaceResponse,
        dependencies=[Depends(verify_runner_auth)],
    )
    def create_workspace_endpoint(
        payload: RunnerCreateWorkspaceRequest,
    ) -> RunnerCreateWorkspaceResponse:
        try:
            base_path = _validate_base_repo_path(payload.base_repo_path)
            ws_path = exec_backend.create_workspace(payload.task_id, base_path)
            return RunnerCreateWorkspaceResponse(
                success=True,
                task_id=payload.task_id,
                workspace_path=str(ws_path),
                backend=exec_backend.backend_type,
            )
        except HTTPException:
            raise
        except (WorkspacePathEscapeError, SandboxSecurityError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=redact(str(exc)))
        except Exception as exc:
            logger.error(f"Workspace creation failed: {exc}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=redact(str(exc)))

    @runner_app.post(
        "/internal/v1/workspaces/{task_id}/exec",
        response_model=WorkspaceCommandResult,
        dependencies=[Depends(verify_runner_auth)],
    )
    def execute_command_endpoint(
        task_id: str,
        payload: RunnerExecuteRequest,
    ) -> WorkspaceCommandResult:
        try:
            cwd_path = Path(payload.cwd) if payload.cwd else None
            return exec_backend.execute(
                task_id=task_id,
                command=payload.command,
                arguments=payload.arguments,
                cwd=cwd_path,
                timeout_seconds=payload.timeout_seconds,
                custom_env=payload.custom_env,
                network_enabled=payload.network_enabled,
            )
        except (WorkspacePolicyViolationError, SandboxSecurityError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=redact(str(exc)))
        except Exception as exc:
            logger.error(f"Command execution failed: {exc}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=redact(str(exc)))

    @runner_app.get(
        "/internal/v1/workspaces/{task_id}/files",
        response_model=RunnerFileReadResponse,
        dependencies=[Depends(verify_runner_auth)],
    )
    def read_file_endpoint(
        task_id: str,
        path: str = Query(..., min_length=1, description="Workspace-relative file path"),
    ) -> RunnerFileReadResponse:
        try:
            content = exec_backend.read_file(task_id, path)
            return RunnerFileReadResponse(success=True, path=path, content=content)
        except WorkspacePathEscapeError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=redact(str(exc)))
        except WorkspaceError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=redact(str(exc)))
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=redact(str(exc)))

    @runner_app.put(
        "/internal/v1/workspaces/{task_id}/files",
        response_model=RunnerFileWriteResponse,
        dependencies=[Depends(verify_runner_auth)],
    )
    def write_file_endpoint(
        task_id: str,
        payload: RunnerFileWriteRequest,
    ) -> RunnerFileWriteResponse:
        try:
            exec_backend.write_file(task_id, payload.path, payload.content)
            return RunnerFileWriteResponse(
                success=True,
                path=payload.path,
                bytes_written=len(payload.content.encode("utf-8")),
            )
        except WorkspacePathEscapeError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=redact(str(exc)))
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=redact(str(exc)))

    @runner_app.get(
        "/internal/v1/workspaces/{task_id}/diff",
        response_model=RunnerDiffResponse,
        dependencies=[Depends(verify_runner_auth)],
    )
    def get_diff_endpoint(task_id: str) -> RunnerDiffResponse:
        try:
            diff_text = exec_backend.get_diff(task_id)
            return RunnerDiffResponse(success=True, task_id=task_id, diff=diff_text)
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=redact(str(exc)))

    @runner_app.get(
        "/internal/v1/workspaces/{task_id}/status",
        response_model=RunnerStatusResponse,
        dependencies=[Depends(verify_runner_auth)],
    )
    def get_status_endpoint(task_id: str) -> RunnerStatusResponse:
        try:
            status_data = exec_backend.get_status(task_id)
            return RunnerStatusResponse(
                success=True,
                task_id=task_id,
                backend=exec_backend.backend_type,
                status=status_data.get("status", "UNKNOWN"),
                gvisor_verified=status_data.get("gvisor_verified", False),
                details=status_data,
            )
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=redact(str(exc)))

    @runner_app.delete(
        "/internal/v1/workspaces/{task_id}",
        dependencies=[Depends(verify_runner_auth)],
    )
    def destroy_workspace_endpoint(task_id: str) -> dict[str, Any]:
        try:
            exec_backend.destroy_workspace(task_id)
            return {"success": True, "task_id": task_id, "status": "DESTROYED"}
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=redact(str(exc)))

    return runner_app


app = create_runner_app()
