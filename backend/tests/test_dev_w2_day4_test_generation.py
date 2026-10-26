"""Unit and contract tests for Dev's Week 2 Day 4 TestGenerationService deliverable.

Validates:
1. Protocol implementation (TestGenerationServiceProtocol).
2. Framework-aware test generation for pytest, unittest, and jest.
3. Coverage across 'normal', 'edge_case', and 'failure_path' test scenarios.
4. Bounded self-repair loop on syntax errors and JSON validation failures.
5. Fail-closed security: unconfigured gateway (503) and disallowed provider (400).
6. Prompt isolation fencing and secret redaction.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from ai.interfaces import TestGenerationServiceProtocol
from ai.llm.schemas import LLMResponse, LLMValidationError
from ai.services.test_generation_service import TestGenerationService
from app.core.errors import APIError
from app.schemas.analysis import (
    AnalysisTarget,
    TestGenerationRequest,
    TestGenerationResponse,
    TestGenerationResult,
    TestScenario,
)

# Prevent pytest from treating schemas/protocols starting with 'Test' as test classes
TestGenerationResult.__test__ = False
TestGenerationRequest.__test__ = False
TestScenario.__test__ = False
TestGenerationResponse.__test__ = False
TestGenerationServiceProtocol.__test__ = False


def _make_dummy_request(target_path: str = "src/calculator.py") -> TestGenerationRequest:
    return TestGenerationRequest(
        target=AnalysisTarget(
            type="file",
            path=target_path,
        ),
    )


def _make_valid_test_payload(
    framework: str = "pytest",
    test_path: str = "tests/test_calculator.py",
) -> dict[str, Any]:
    if framework == "jest":
        code = (
            "describe('Calculator', () => {\n"
            "  test('normal: adds numbers', () => { expect(1 + 1).toBe(2); });\n"
            "  test('edge_case: zero addition', () => { expect(0 + 0).toBe(0); });\n"
            "  test('failure_path: throws on invalid input', () => {\n"
            "    expect(() => { throw new Error('invalid'); }).toThrow();\n"
            "  });\n"
            "});\n"
        )
    elif framework == "unittest":
        code = (
            "import unittest\n\n"
            "class TestCalculator(unittest.TestCase):\n"
            "    def test_normal_add(self):\n"
            "        self.assertEqual(1 + 1, 2)\n"
            "    def test_edge_zero(self):\n"
            "        self.assertEqual(0 + 0, 0)\n"
            "    def test_failure_invalid(self):\n"
            "        with self.assertRaises(ValueError):\n"
            "            raise ValueError('bad')\n"
        )
    else:  # pytest
        code = (
            "import pytest\n\n"
            "def test_normal_addition():\n"
            "    assert 1 + 1 == 2\n\n"
            "def test_edge_case_zero():\n"
            "    assert 0 + 0 == 0\n\n"
            "def test_failure_path_raises():\n"
            "    with pytest.raises(ValueError):\n"
            "        raise ValueError('boom')\n"
        )

    return {
        "test_content": code,
        "proposed_test_path": test_path,
        "detected_framework": framework,
        "covered_scenarios": [
            {
                "name": "test_normal",
                "category": "normal",
                "description": "Tests normal addition",
                "target_symbol": "add",
            },
            {
                "name": "test_edge",
                "category": "edge_case",
                "description": "Tests edge case zero addition",
                "target_symbol": "add",
            },
            {
                "name": "test_failure",
                "category": "failure_path",
                "description": "Tests failure path exception raising",
                "target_symbol": "add",
            },
        ],
        "assumptions_and_warnings": [],
        "syntax_valid": True,
        "validation_errors": [],
    }


@pytest.mark.asyncio
async def test_test_generation_service_satisfies_protocol():
    service = TestGenerationService(llm_gateway=MagicMock())
    assert isinstance(service, TestGenerationServiceProtocol)


@pytest.mark.asyncio
async def test_test_generation_service_all_scenarios_success():
    payload_dict = _make_valid_test_payload("pytest", "tests/test_calc.py")
    mock_gateway = MagicMock()
    mock_gateway.provider.provider_name = "gemini"
    mock_gateway.generate = AsyncMock(
        return_value=LLMResponse(
            content=json.dumps(payload_dict),
            model="gemini-flash-lite-latest",
        )
    )

    service = TestGenerationService(llm_gateway=mock_gateway)
    req = _make_dummy_request("src/calc.py")

    result = await service.generate_tests(
        repository_id=uuid4(),
        payload=req,
        code_content="def add(a, b): return a + b\n",
        detected_framework="pytest",
        proposed_test_path="tests/test_calc.py",
        fixtures=["tmp_path"],
    )

    assert result.detected_framework == "pytest"
    assert result.proposed_test_path == "tests/test_calc.py"
    assert result.syntax_valid is True
    assert len(result.covered_scenarios) == 3

    categories = {s.category for s in result.covered_scenarios}
    assert {"normal", "edge_case", "failure_path"}.issubset(categories)

    # Check that untrusted code was fenced
    call_args = mock_gateway.generate.call_args[0][0]
    user_prompt = call_args.messages[1].content
    assert "<<<REPO_DATA_" in user_prompt
    assert "def add(a, b)" in user_prompt


@pytest.mark.asyncio
async def test_test_generation_service_unittest_and_jest():
    mock_gateway = MagicMock()
    mock_gateway.provider.provider_name = "groq"

    # 1. Unittest
    unittest_dict = _make_valid_test_payload("unittest", "tests/test_calc_unittest.py")
    mock_gateway.generate = AsyncMock(
        return_value=LLMResponse(content=json.dumps(unittest_dict), model="llama-3.3-70b-versatile")
    )
    service = TestGenerationService(llm_gateway=mock_gateway)
    result_unittest = await service.generate_tests(
        repository_id=uuid4(),
        payload=_make_dummy_request(),
        detected_framework="unittest",
        proposed_test_path="tests/test_calc_unittest.py",
    )
    assert result_unittest.detected_framework == "unittest"
    assert result_unittest.syntax_valid is True

    # 2. Jest
    jest_dict = _make_valid_test_payload("jest", "tests/calc.test.ts")
    mock_gateway.generate = AsyncMock(
        return_value=LLMResponse(content=json.dumps(jest_dict), model="llama-3.3-70b-versatile")
    )
    result_jest = await service.generate_tests(
        repository_id=uuid4(),
        payload=_make_dummy_request("src/calc.ts"),
        detected_framework="jest",
        proposed_test_path="tests/calc.test.ts",
    )
    assert result_jest.detected_framework == "jest"
    assert result_jest.syntax_valid is True


@pytest.mark.asyncio
async def test_test_generation_service_syntax_repair_loop():
    broken_code = "def test_broken(:\n    assert True\n"
    broken_payload = _make_valid_test_payload("pytest")
    broken_payload["test_content"] = broken_code

    valid_payload = _make_valid_test_payload("pytest")

    mock_gateway = MagicMock()
    mock_gateway.provider.provider_name = "gemini"
    mock_gateway.generate = AsyncMock(
        side_effect=[
            LLMResponse(content=json.dumps(broken_payload), model="gemini-flash-lite-latest"),
            LLMResponse(content=json.dumps(valid_payload), model="gemini-flash-lite-latest"),
        ]
    )

    service = TestGenerationService(llm_gateway=mock_gateway)
    result = await service.generate_tests(
        repository_id=uuid4(),
        payload=_make_dummy_request(),
        detected_framework="pytest",
    )

    assert mock_gateway.generate.call_count == 2
    assert result.syntax_valid is True
    # The second request should contain repair prompt
    repair_req = mock_gateway.generate.call_args_list[1][0][0]
    repair_msg = repair_req.messages[-1].content
    assert "syntax/structural errors" in repair_msg


@pytest.mark.asyncio
async def test_test_generation_service_json_repair_loop_on_fences():
    valid_payload = _make_valid_test_payload("pytest")
    fenced_raw = f"```json\n{json.dumps(valid_payload)}\n```"

    mock_gateway = MagicMock()
    mock_gateway.provider.provider_name = "gemini"
    mock_gateway.generate = AsyncMock(
        return_value=LLMResponse(content=fenced_raw, model="gemini-flash-lite-latest")
    )

    service = TestGenerationService(llm_gateway=mock_gateway)
    result = await service.generate_tests(
        repository_id=uuid4(),
        payload=_make_dummy_request(),
        detected_framework="pytest",
    )

    assert mock_gateway.generate.call_count == 1
    assert result.syntax_valid is True
    assert len(result.covered_scenarios) == 3


@pytest.mark.asyncio
async def test_test_generation_service_exhaustion_raises():
    mock_gateway = MagicMock()
    mock_gateway.provider.provider_name = "gemini"
    mock_gateway.generate = AsyncMock(
        return_value=LLMResponse(content="Sorry, I cannot help with that.", model="gemini-flash-lite-latest")
    )

    service = TestGenerationService(llm_gateway=mock_gateway)
    with pytest.raises(LLMValidationError) as exc_info:
        await service.generate_tests(
            repository_id=uuid4(),
            payload=_make_dummy_request(),
        )

    assert "Invalid TestGenerationResult JSON after 2 attempts" in str(exc_info.value)
    assert mock_gateway.generate.call_count == 2


@pytest.mark.asyncio
async def test_test_generation_service_unconfigured_gateway_raises_503():
    service = TestGenerationService(llm_gateway=None)
    with pytest.raises(APIError) as exc_info:
        await service.generate_tests(
            repository_id=uuid4(),
            payload=_make_dummy_request(),
        )

    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_test_generation_service_disallowed_provider_raises_400():
    mock_gateway = MagicMock()
    mock_gateway.provider.provider_name = "openai"

    service = TestGenerationService(llm_gateway=mock_gateway)
    with pytest.raises(APIError) as exc_info:
        await service.generate_tests(
            repository_id=uuid4(),
            payload=_make_dummy_request(),
        )

    assert exc_info.value.status_code == 400
    assert "Only Gemini and Groq are allowed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_test_generation_service_redacts_secrets_in_prompt():
    raw_code = "SECRET_TOKEN = 'ghp_1234567890abcdef1234567890abcdef'\n"
    payload_dict = _make_valid_test_payload("pytest")

    mock_gateway = MagicMock()
    mock_gateway.provider.provider_name = "gemini"
    mock_gateway.generate = AsyncMock(
        return_value=LLMResponse(content=json.dumps(payload_dict), model="gemini-flash-lite-latest")
    )

    service = TestGenerationService(llm_gateway=mock_gateway)
    await service.generate_tests(
        repository_id=uuid4(),
        payload=_make_dummy_request(),
        code_content=raw_code,
    )

    user_prompt = mock_gateway.generate.call_args[0][0].messages[1].content
    assert "ghp_1234567890abcdef1234567890abcdef" not in user_prompt
    assert "[REDACTED]" in user_prompt
