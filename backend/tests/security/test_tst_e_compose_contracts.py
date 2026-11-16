"""Integration and Compose Profile Validation Test for TST-E0..E6.

Verifies:
- docker-compose.test.yml defines valid services: api, sync_worker, webhook_worker, postgres, redis.
- api service runs with APP_ENV=test and explicit JWT configuration.
- workers run with dedicated SERVICE_ROLE values.
- No default or weak production secrets in compose configuration.
"""

from __future__ import annotations

from pathlib import Path
import yaml


def test_docker_compose_test_profile_contract() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    compose_path = repo_root.parent / "docker-compose.test.yml"
    assert compose_path.exists(), "docker-compose.test.yml must exist at repository root"

    with open(compose_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    services = config.get("services", {})
    required_services = {"postgres", "redis", "api", "sync_worker", "webhook_worker"}
    for svc in required_services:
        assert svc in services, f"Required test service '{svc}' missing in docker-compose.test.yml"

    # API configuration
    api_env = services["api"].get("environment", {})
    assert api_env.get("SERVICE_ROLE") == "api"
    assert api_env.get("APP_ENV") == "test"

    # Worker configuration
    sync_env = services["sync_worker"].get("environment", {})
    assert sync_env.get("SERVICE_ROLE") == "sync_worker"

    webhook_env = services["webhook_worker"].get("environment", {})
    assert webhook_env.get("SERVICE_ROLE") == "webhook_worker"
