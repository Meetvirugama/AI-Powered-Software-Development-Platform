"""Validation tests for Issue #216 (F35): CI/CD quality gates, security scanners, and hardened Dockerfile."""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "main_ai-powered-dev-platform-api.yml"
DOCKERFILE_PATH = REPO_ROOT / "Dockerfile"
DOCKERIGNORE_PATH = REPO_ROOT / ".dockerignore"
GITLEAKS_CONFIG_PATH = REPO_ROOT / ".gitleaks.toml"
ROOT_REQS_PATH = REPO_ROOT / "requirements.txt"
PROD_REQS_PATH = REPO_ROOT / "backend" / "requirements.txt"
DEV_REQS_PATH = REPO_ROOT / "backend" / "requirements-dev.txt"


def _load_workflow() -> dict:
    assert WORKFLOW_PATH.is_file(), f"Missing workflow file: {WORKFLOW_PATH}"
    data = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and "jobs" in data
    return data


def _extract_pkg_names(req_path: Path) -> set[str]:
    names: set[str] = set()
    for raw in req_path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-r"):
            continue
        pkg = re.split(r"[<>=!~;\[]", line, maxsplit=1)[0].strip().lower()
        if pkg:
            names.add(pkg)
    return names


class TestCICDWorkflowGates:
    """Verify CI/CD workflow enforces tests, coverage, Postgres, and security scanners."""

    def test_least_privilege_workflow_permissions(self) -> None:
        wf = _load_workflow()
        assert wf.get("permissions", {}).get("contents") == "read"

    def test_backend_lint_stage_enforces_ruff_and_bandit(self) -> None:
        wf = _load_workflow()
        lint_job = wf["jobs"]["backend-lint-and-static"]
        steps_blob = "\n".join(str(s.get("run", "")) for s in lint_job["steps"])
        assert "ruff check" in steps_blob
        assert "bandit -r backend/app" in steps_blob

    def test_backend_tests_stage_enforces_full_suite_and_71_coverage(self) -> None:
        wf = _load_workflow()
        test_job = wf["jobs"]["backend-tests"]
        steps_blob = "\n".join(str(s.get("run", "")) for s in test_job["steps"])
        assert "pytest backend/tests tests/e2e/" in steps_blob
        assert "--no-cov" not in steps_blob
        assert "--cov=app" in steps_blob
        assert "--cov-fail-under=71" in steps_blob

    def test_migration_stage_uses_pgvector_postgres_container(self) -> None:
        wf = _load_workflow()
        mig_job = wf["jobs"]["migration-validation"]
        pg_service = mig_job["services"]["postgres"]
        assert "pgvector/pgvector:pg16" in pg_service["image"]
        steps_blob = "\n".join(str(s.get("run", "")) for s in mig_job["steps"])
        assert "alembic upgrade head" in steps_blob
        assert "backend/tests/test_migration_smoke.py" in steps_blob

    def test_security_stage_runs_gitleaks_pip_audit_and_security_gate(self) -> None:
        wf = _load_workflow()
        sec_job = wf["jobs"]["security-scan"]
        checkout_step = next(s for s in sec_job["steps"] if str(s.get("uses", "")).startswith("actions/checkout@"))
        assert checkout_step.get("with", {}).get("fetch-depth") == 0

        uses_list = [str(s.get("uses", "")) for s in sec_job["steps"]]
        assert any(u.startswith("gitleaks/gitleaks-action@") for u in uses_list)

        runs_blob = "\n".join(str(s.get("run", "")) for s in sec_job["steps"])
        assert "pip-audit -r backend/requirements.txt" in runs_blob
        assert "python backend/scripts/security_gate.py --skip-db" in runs_blob

    def test_build_and_deploy_gating(self) -> None:
        wf = _load_workflow()
        build_job = wf["jobs"]["build-and-package"]
        required_gates = {
            "backend-lint-and-static",
            "backend-tests",
            "frontend-lint-and-types",
            "frontend-tests-and-build",
            "migration-validation",
            "security-scan",
        }
        assert required_gates.issubset(set(build_job["needs"]))

        builds_blob = "\n".join(str(s.get("run", "")) for s in build_job["steps"])
        assert "docker build" in builds_blob

        deploy_job = wf["jobs"]["deploy"]
        assert "build-and-package" in str(deploy_job["needs"])
        assert "refs/heads/main" in str(deploy_job.get("if", ""))


class TestDockerfileAndDependencyHardening:
    """Verify multi-stage digest-pinned Dockerfile and production-only dependencies."""

    def test_dockerfile_is_multistage_digest_pinned_and_non_root(self) -> None:
        content = DOCKERFILE_PATH.read_text(encoding="utf-8")
        from_lines = [line.strip() for line in content.splitlines() if line.strip().upper().startswith("FROM ")]
        assert len(from_lines) >= 2, "Expected multi-stage Dockerfile with at least 2 FROM stages"
        for from_line in from_lines:
            assert re.search(r"@sha256:[0-9a-f]{64}\b", from_line), f"Base image must be pinned by digest: {from_line}"

        assert re.search(r"\bAS\s+builder\b", content, re.IGNORECASE)
        assert re.search(r"\bAS\s+runtime\b", content, re.IGNORECASE)

        runtime_section = re.split(r"\bAS\s+runtime\b", content, maxsplit=1, flags=re.IGNORECASE)[1]
        for forbidden_compiler in ("build-essential", "libpq-dev", "gcc", "g++"):
            assert forbidden_compiler not in runtime_section, f"Compiler/dev package {forbidden_compiler} leaked into runtime stage"

        assert "USER appuser" in runtime_section
        assert "USER root" not in runtime_section
        assert "HEALTHCHECK" in runtime_section
        assert 'ENTRYPOINT ["/app/startup.sh"]' in runtime_section

    def test_dockerignore_excludes_secrets_tests_and_caches(self) -> None:
        assert DOCKERIGNORE_PATH.is_file()
        entries = {line.strip() for line in DOCKERIGNORE_PATH.read_text(encoding="utf-8").splitlines() if line.strip() and not line.strip().startswith("#")}
        for expected in (".git", ".env", ".env.*", "backend/tests/", "frontend/", "node_modules/"):
            assert expected in entries

    def test_production_requirements_exclude_dev_and_scanner_tools(self) -> None:
        root_reqs = ROOT_REQS_PATH.read_text(encoding="utf-8").strip()
        assert root_reqs == "-r backend/requirements.txt"

        prod_pkgs = _extract_pkg_names(PROD_REQS_PATH)
        dev_pkgs = _extract_pkg_names(DEV_REQS_PATH)

        forbidden_prod = {"pytest", "pytest-asyncio", "pytest-cov", "respx", "responses", "ruff", "bandit", "pip-audit"}
        assert prod_pkgs.isdisjoint(forbidden_prod), f"Dev/CI packages found in prod requirements: {prod_pkgs & forbidden_prod}"
        assert {"pytest", "ruff", "bandit", "pip-audit"}.issubset(dev_pkgs)

    def test_gitleaks_config_valid_toml_and_ruff_zero_undefined_names(self) -> None:
        assert GITLEAKS_CONFIG_PATH.is_file()
        parsed = tomllib.loads(GITLEAKS_CONFIG_PATH.read_text(encoding="utf-8"))
        assert parsed.get("extend", {}).get("useDefault") is True

        proc = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "backend/app", "--select", "E9,F63,F7,F82"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, f"Ruff static errors found:\n{proc.stdout}\n{proc.stderr}"
