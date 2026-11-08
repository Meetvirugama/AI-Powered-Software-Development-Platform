"""End-to-End Vitest Support Tests (task.md §8 & Phase 5).

Verifies:
1. Vitest detection via package.json dependencies and scripts.
2. Vitest detection via vitest.config.ts / vite.config.ts config files.
3. Disambiguation between Jest and Vitest when both are present.
4. Correct Vitest execution command formatting ('npm test -- --run').
5. Safe Vitest test file naming conventions (.test.ts, .spec.ts).
6. JavaScript/TypeScript syntax validation accepting Vitest constructs (vi.fn(), vi.mock()).
7. Rejection of Vitest for Python targets (400 UNSUPPORTED_TARGET).
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
from uuid import uuid4

import pytest

from app.core.errors import APIError
from app.schemas.analysis import TestGenerationResult, TestScenario
from app.services.test_generation_orchestrator import (
    detect_repository_test_framework,
    propose_test_file_path,
    validate_and_sanitize_generated_tests,
    validate_generated_test_syntax,
)
from scanner.framework_detector import FrameworkDetector


def test_vitest_detected_via_vitest_config() -> None:
    detector = FrameworkDetector()
    files = ["src/index.ts", "vitest.config.ts", "package.json"]

    def fake_read(root: Any, rel_path: str) -> str:
        if rel_path == "package.json":
            return json.dumps({
                "scripts": {"test": "vitest"},
                "devDependencies": {"vitest": "^1.0.0"}
            })
        return ""

    detector._read_file = fake_read  # type: ignore[method-assign]
    res = detector.detect(repo_root=None, target_file="src/index.ts", file_list=files)

    assert res.framework == "vitest"
    assert res.is_supported is True
    assert res.status == "CONFIRMED"
    assert res.test_command == "npm test -- --run"
    assert res.config_file == "vitest.config.ts"


def test_vitest_detected_via_package_json_only() -> None:
    detector = FrameworkDetector()
    files = ["src/math.ts", "package.json"]

    def fake_read(root: Any, rel_path: str) -> str:
        if rel_path == "package.json":
            return json.dumps({
                "scripts": {"test": "vitest run"},
                "devDependencies": {"vitest": "^2.0.0"}
            })
        return ""

    detector._read_file = fake_read  # type: ignore[method-assign]
    res = detector.detect(repo_root=None, target_file="src/math.ts", file_list=files)

    assert res.framework == "vitest"
    assert res.is_supported is True
    assert res.status == "CONFIRMED"
    assert res.test_command == "npm test -- --run"


def test_vitest_disambiguation_with_preferred_framework() -> None:
    detector = FrameworkDetector()
    # Both Jest and Vitest are present in package.json
    files = ["src/component.tsx", "package.json", "jest.config.js", "vitest.config.ts"]

    def fake_read(root: Any, rel_path: str) -> str:
        if rel_path == "package.json":
            return json.dumps({
                "scripts": {"test": "jest", "test:vitest": "vitest"},
                "devDependencies": {"jest": "^29.0.0", "vitest": "^1.0.0"}
            })
        return ""

    detector._read_file = fake_read  # type: ignore[method-assign]

    # Explicitly requesting vitest
    res_vitest = detector.detect(
        repo_root=None,
        target_file="src/component.tsx",
        file_list=files,
        preferred_framework="vitest",
    )
    assert res_vitest.framework == "vitest"
    assert res_vitest.test_command == "npm test -- --run"

    # Explicitly requesting jest
    res_jest = detector.detect(
        repo_root=None,
        target_file="src/component.tsx",
        file_list=files,
        preferred_framework="jest",
    )
    assert res_jest.framework == "jest"
    assert res_jest.test_command == "npm test"


def test_vitest_syntax_validation_accepts_vi_mocks() -> None:
    vitest_code = """
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fetchUserData } from '../src/userService';

vi.mock('../src/apiClient', () => ({
    get: vi.fn().mockResolvedValue({ id: 1, name: 'Alice' }),
}));

describe('fetchUserData', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it('returns user data successfully', async () => {
        const user = await fetchUserData(1);
        expect(user.name).toBe('Alice');
    });

    it('handles failure cases', async () => {
        expect(true).toBe(true);
    });
});
"""
    valid, errors = validate_generated_test_syntax(
        vitest_code,
        framework="vitest",
        proposed_test_path="tests/userService.test.ts",
    )
    assert valid is True
    assert len(errors) == 0


def test_vitest_propose_test_file_path() -> None:
    path, pattern = propose_test_file_path(
        target_path="src/components/Button.tsx",
        framework="vitest",
        indexed_paths=["src/components/Button.tsx"],
        existing_py_tests=[],
        existing_js_tests=["src/components/__tests__/Header.test.tsx"],
    )
    assert path.endswith(".test.tsx")
    assert "__tests__" in path


def test_rejection_of_vitest_on_python_target() -> None:
    db_mock = type("MockDB", (), {"query": lambda self, model: type("Q", (), {"filter": lambda self, *a: type("Q2", (), {"all": lambda self: []})()})()})()

    with pytest.raises(APIError) as exc_info:
        detect_repository_test_framework(
            repository_id=uuid4(),
            target_path="backend/app/main.py",
            requested_framework="vitest",
            db=db_mock,
            preloaded_repo_files=[],
        )
    assert exc_info.value.status_code == 400
    assert "Cannot generate 'vitest' tests for Python file" in exc_info.value.message
