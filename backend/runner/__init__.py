"""Dedicated Runner Service Package for Untrusted Code Execution.

Owner: AI Platform Security Architecture — Issue #200 / F20
Reference: Docs/security/sandbox/04-runner-service-design.md
"""

from runner.main import app, create_runner_app

__all__ = ["app", "create_runner_app"]
