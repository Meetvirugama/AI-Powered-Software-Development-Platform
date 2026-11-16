"""TST-30: Frontend-Backend API Contract Verification Test.

Asserts that every apiClient call site extracted from frontend/src/services/*.ts
maps to an existing path and HTTP method in the backend FastAPI OpenAPI specification.
Target: 0 frontend calls to non-existent endpoints.
"""

from __future__ import annotations

import glob
import re
from pathlib import Path
from typing import Set, Tuple

import pytest
from app.main import app


def _extract_frontend_api_calls(project_root: Path) -> Set[Tuple[str, str]]:
    """Scan all frontend production TypeScript files for apiClient.<verb> calls."""
    fe_dir = project_root / "frontend" / "src"
    if not fe_dir.exists():
        pytest.skip("frontend/src directory not found")

    pattern = re.compile(r'apiClient\.(get|post|put|patch|delete)(?:<[^>]*>)?\s*\(\s*[`\'"]([^`\'"]+)[`\'"]')
    fe_calls: Set[Tuple[str, str]] = set()

    for ts_path in fe_dir.rglob("*.ts*"):
        rel_str = str(ts_path)
        if "test" in rel_str or "mock" in rel_str or "__tests__" in rel_str:
            continue
        try:
            content = ts_path.read_text(encoding="utf-8")
        except Exception:
            continue

        for match in pattern.finditer(content):
            verb = match.group(1).upper()
            raw_path = match.group(2).split("?")[0].strip()
            # Normalize template substitutions ${var} -> {}
            norm_path = re.sub(r"\$\{[^}]+\}", "{}", raw_path)
            # Prefix with /api/v1 if not present
            if not norm_path.startswith("/api/v1"):
                norm_path = "/api/v1" + (norm_path if norm_path.startswith("/") else "/" + norm_path)
            fe_calls.add((verb, norm_path))

    return fe_calls


def test_tst30_frontend_api_contract():
    """Verify that every frontend apiClient call maps to a registered OpenAPI route."""
    openapi = app.openapi()
    backend_operations: Set[Tuple[str, str]] = set()

    for path, methods in openapi.get("paths", {}).items():
        # Normalize OpenAPI path parameters {param} -> {}
        norm_path = re.sub(r"\{[^}]+\}", "{}", path)
        for method in methods:
            if method.upper() in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                backend_operations.add((method.upper(), norm_path))

    assert len(backend_operations) > 0, "Backend OpenAPI must contain registered operations"

    project_root = Path(__file__).resolve().parent.parent.parent
    fe_calls = _extract_frontend_api_calls(project_root)

    assert len(fe_calls) > 0, "Frontend must contain production apiClient calls"

    missing_endpoints = []
    for verb, norm_path in sorted(fe_calls):
        if (verb, norm_path) not in backend_operations:
            missing_endpoints.append(f"{verb} {norm_path}")

    assert not missing_endpoints, (
        f"TST-30 API Contract Drift: {len(missing_endpoints)} frontend call(s) target non-existent backend endpoints:\n"
        + "\n".join(f"  - {ep}" for ep in missing_endpoints)
    )
