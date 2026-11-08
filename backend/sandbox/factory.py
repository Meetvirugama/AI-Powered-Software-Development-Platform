"""Sandbox Backend Factory for Secure Execution Architecture.

Owner: AI Platform Security Architecture — Issue #200 / F20
Reference: Docs/security/sandbox/03-target-architecture.md
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings

from sandbox.backend import SandboxBackend
from sandbox.container_backend import ContainerBackend
from sandbox.exceptions import SandboxConfigurationError, SandboxSecurityError
from sandbox.local_backend import LocalSubprocessBackend
from sandbox.runner_client import RunnerClient

logger = logging.getLogger(__name__)


class SandboxFactory:
    """Factory responsible for instantiating and selecting the appropriate execution backend."""

    @classmethod
    def get_backend(
        cls,
        backend_type: str | None = None,
        **backend_kwargs: Any,
    ) -> SandboxBackend:
        """Resolve and instantiate a validated SandboxBackend instance.

        Enforces production fail-closed security policies:
        - In APP_ENV=production, 'local' is strictly rejected.
        - Unrecognized or missing configurations fail closed.

        Args:
            backend_type: Explicit backend override ('local', 'container', 'runner').
            backend_kwargs: Keyword arguments forwarded to backend constructor.

        Returns:
            Configured and initialized SandboxBackend instance.

        Raises:
            SandboxSecurityError: If an insecure backend is requested in production.
            SandboxConfigurationError: If the backend configuration is invalid or unrecognized.
        """
        app_env = getattr(settings, "app_env", "development").strip().lower()
        is_prod = getattr(settings, "is_production", False) or app_env in ("production", "prod")

        # Determine effective backend type
        raw_type = backend_type or getattr(settings, "sandbox_backend", None)
        if not raw_type:
            raw_type = "runner" if is_prod else "local"

        target_type = raw_type.strip().lower()

        # Strict production enforcement: Local host execution is forbidden
        if is_prod and target_type in ("local", "subprocess", "localsubprocess"):
            logger.critical(
                "production_sandbox_security_violation_attempted",
                extra={"requested_backend": target_type, "app_env": app_env},
            )
            raise SandboxSecurityError(
                f"SECURITY POLICY VIOLATION: LocalSubprocessBackend is strictly forbidden "
                f"in production (APP_ENV='{app_env}'). "
                f"You must configure SANDBOX_BACKEND='container' or 'runner'."
            )

        if target_type in ("local", "subprocess", "localsubprocess"):
            return LocalSubprocessBackend(**backend_kwargs)

        if target_type in ("container", "docker"):
            return ContainerBackend(**backend_kwargs)

        if target_type in ("runner", "remote", "client"):
            return RunnerClient(**backend_kwargs)

        raise SandboxConfigurationError(
            f"Unsupported or invalid sandbox backend type '{target_type}'. "
            f"Valid options are: 'local' (dev only), 'container', 'runner'."
        )
