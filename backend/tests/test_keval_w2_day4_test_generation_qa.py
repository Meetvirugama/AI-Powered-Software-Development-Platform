"""Acceptance and QA tests for Framework-Aware Test Generation (Week 2 Day 4).

Owner: Keval (QA Lead)
Reference: Docs/week2.md §8 & §12 (Scenario C)
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
import pytest

from ai.llm.schemas import LLMResponse
from app.schemas.analysis import (
    AnalysisOptions,
    AnalysisSourceReference,
    AnalysisTarget,
    TestGenerationRequest,
    TestGenerationResult,
    TestScenario,
)
from app.services.test_generation_orchestrator import (
    LLMTestGenerationService,
    check_generated_test_path,
    propose_test_file_path,
    validate_generated_test_syntax,
)
from scanner.framework_detector import FrameworkDetector

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "defect_fixtures"


@pytest.fixture
def mock_gateway():
    gw = MagicMock()
    gw.generate = AsyncMock()
    gw.provider = MagicMock(provider_name="gemini")
    return gw


def test_framework_detection_python_pytest():
    """Verify FrameworkDetector detects pytest in Python repositories with pytest config."""
    detector = FrameworkDetector()
    files = [
        "pytest.ini",
        "app/services/pricing.py",
        "tests/test_pricing.py",
    ]
    res = detector.detect(file_list=files, target_file="app/services/pricing.py")
    assert res.framework == "pytest"
    assert res.language == "Python"
    assert res.is_supported is True
    assert "pytest" in (res.test_command or "")

    proposed = res.propose_test_path("app/services/pricing.py")
    assert proposed.startswith("tests/")
    assert proposed.endswith("test_pricing.py")


def test_framework_detection_javascript_jest():
    """Verify FrameworkDetector detects Jest when package.json or jest.config is present."""
    detector = FrameworkDetector()
    files = [
        "package.json",
        "jest.config.js",
        "src/utils/calc.ts",
    ]
    res = detector.detect(file_list=files, target_file="src/utils/calc.ts")
    assert res.framework == "jest"
    assert res.language in ("TypeScript", "JavaScript")
    assert res.is_supported is True

    proposed = res.propose_test_path("src/utils/calc.ts")
    assert "calc.test.ts" in proposed or "__tests__" in proposed


def test_validate_generated_test_syntax_python():
    """Verify syntax and assertion validation for Python test suites."""
    # Valid Python test with assertions
    valid_py = (
        "import pytest\n"
        "from app.services.pricing import PricingService\n\n"
        "def test_pricing_normal():\n"
        "    service = PricingService()\n"
        "    assert service.calculate_total(100, 0.1) == 90.0\n\n"
        "def test_pricing_invalid_discount():\n"
        "    service = PricingService()\n"
        "    with pytest.raises(ValueError):\n"
        "        service.calculate_total(100, -0.5)\n"
    )
    ok, errors = validate_generated_test_syntax(valid_py, "pytest", "tests/test_pricing.py")
    assert ok is True
    assert len(errors) == 0

    # Invalid Python: syntax error
    invalid_py = "def test_broken():\n    assert (1 + 2\n"
    ok, errors = validate_generated_test_syntax(invalid_py, "pytest", "tests/test_broken.py")
    assert ok is False
    assert any("syntax error" in e.lower() for e in errors)

    # Missing assertions
    no_assert_py = (
        "def test_no_assertions():\n"
        "    x = 10\n"
        "    y = 20\n"
    )
    ok, errors = validate_generated_test_syntax(no_assert_py, "pytest", "tests/test_none.py")
    assert ok is False
    assert any("assert" in e.lower() for e in errors)


def test_validate_generated_test_syntax_jest():
    """Verify structural and assertion validation for Jest test suites."""
    valid_jest = (
        'describe("PricingService", () => {\n'
        '  test("calculates discounted total", () => {\n'
        '    expect(calculateTotal(100, 0.1)).toBe(90);\n'
        '  });\n'
        '});\n'
    )
    ok, errors = validate_generated_test_syntax(valid_jest, "jest", "src/__tests__/pricing.test.ts")
    assert ok is True
    assert len(errors) == 0

    # Missing expect assertions
    no_expect_jest = (
        'test("does nothing", () => {\n'
        '  const a = 1 + 2;\n'
        '});\n'
    )
    ok, errors = validate_generated_test_syntax(no_expect_jest, "jest", "src/__tests__/test.ts")
    assert ok is False
    assert any("expect" in e.lower() for e in errors)


@pytest.mark.asyncio
async def test_generate_tests_ai_service_with_scenarios_and_assertions(mock_gateway):
    """Verify test generation service produces structured output with 3 test scenario classes."""
    generated_code = (
        "import pytest\n"
        "from app.services.pricing import PricingService\n\n"
        "def test_calculate_total_standard():\n"
        "    s = PricingService()\n"
        "    assert s.calculate_total(100.0, 0.1) == 90.0\n\n"
        "def test_calculate_total_zero_subtotal():\n"
        "    s = PricingService()\n"
        "    assert s.calculate_total(0.0, 0.2) == 0.0\n\n"
        "def test_calculate_total_negative_subtotal():\n"
        "    s = PricingService()\n"
        "    with pytest.raises(ValueError):\n"
        "        s.calculate_total(-10.0, 0.1)\n"
    )

    mock_result = {
        "detected_framework": "pytest",
        "proposed_test_path": "tests/test_pricing_service.py",
        "test_content": generated_code,
        "covered_scenarios": [
            {
                "name": "test_calculate_total_standard",
                "category": "normal",
                "description": "Standard 10% discount calculation.",
            },
            {
                "name": "test_calculate_total_zero_subtotal",
                "category": "edge_case",
                "description": "Zero subtotal boundary condition.",
            },
            {
                "name": "test_calculate_total_negative_subtotal",
                "category": "failure_path",
                "description": "Negative subtotal raises ValueError.",
            },
        ],
        "assumptions_and_warnings": [],
        "syntax_valid": True,
        "validation_errors": [],
        "sources": [
            {
                "file_path": "untested_service.py",
                "start_line": 1,
                "end_line": 35,
            }
        ],
    }

    mock_gateway.generate.return_value = LLMResponse(
        content=json.dumps(mock_result),
        model="gemini-flash-latest",
    )

    svc = LLMTestGenerationService(mock_gateway)
    req = TestGenerationRequest(
        target=AnalysisTarget(type="file", path="untested_service.py"),
        framework="pytest",
    )

    result = await svc.generate_tests(
        uuid4(),
        req,
        code_content="class PricingService: pass",
        detected_framework="pytest",
        proposed_test_path="tests/test_pricing_service.py",
    )

    assert isinstance(result, TestGenerationResult)
    assert result.detected_framework == "pytest"
    assert result.syntax_valid is True
    assert len(result.covered_scenarios) == 3
    categories = {s.category for s in result.covered_scenarios}
    assert "normal" in categories
    assert "edge_case" in categories
    assert "failure_path" in categories
    assert "def test_calculate_total_standard" in result.test_content


def test_generate_tests_security_rejects_unsafe_paths():
    """Verify unsafe path traversal attempts in proposed test paths are blocked."""
    from app.core.input_security import UnsafePathError, validate_repo_relative_path

    unsafe_traversals = [
        "../../etc/shadow",
        "../test.py",
        "/etc/passwd",
        "tests/../../root_file.py",
    ]
    for path in unsafe_traversals:
        with pytest.raises(UnsafePathError):
            validate_repo_relative_path(path)

    # Disallowed locations for generated tests (hidden or invalid names)
    disallowed_test_paths = [
        ".github/workflows/test.py",
        "tests/.git/test_exploit.py",
        "tests/conftest.py",  # reserved auto-run file
        "tests/invalid_name.txt",  # non-test filename
    ]
    for path in disallowed_test_paths:
        warning = check_generated_test_path(path, "pytest")
        assert warning is not None

