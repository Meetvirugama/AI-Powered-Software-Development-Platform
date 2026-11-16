"""Locust load test suite for AI-Powered Software Development Platform (TST-N1..N3).

Usage:
    locust -f loadtests/locustfile.py --headless -u 20 -r 5 --run-time 1m --host http://localhost:8000
"""

from __future__ import annotations

import os
from locust import HttpUser, between, task


class PlatformUser(HttpUser):
    wait_time = between(0.1, 0.5)

    def on_start(self) -> None:
        self.auth_token = os.getenv("TEST_AUTH_TOKEN", "")
        self.headers = {"Authorization": f"Bearer {self.auth_token}"} if self.auth_token else {}

    @task(10)
    def test_health_live(self) -> None:
        """TST-N1: High-frequency liveness check (target p95 < 50ms)."""
        self.client.get("/health/live", name="/health/live")

    @task(5)
    def test_health_ready(self) -> None:
        """TST-N1: Operational readiness check."""
        self.client.get("/api/v1/health/ready", name="/api/v1/health/ready")

    @task(3)
    def test_list_repositories(self) -> None:
        """User browsing repository catalog."""
        self.client.get("/api/v1/repositories", headers=self.headers, name="/api/v1/repositories")
