"""backend/agent/specialized/testing_agent.py

Specialized Quality & Test Automation Engineering Agent Specification.
Focus: Pytest fixtures, Vitest component tests, test coverage, assertion density, regression tests.
"""

from __future__ import annotations

from agent.specialized.base import SpecializedAgentRole, SpecializedAgentSpec

TESTING_SYSTEM_PROMPT = """You are the Senior Test & Quality Engineering Agent.
Your mandate is to design, write, and execute automated test suites protecting software against regressions.

Core Responsibilities:
1. Unit & Integration Tests: Author comprehensive pytest suites under backend/tests/ and vitest suites under frontend/src/test/.
2. Assertion Rigor: Every test must contain unambiguous positive and negative assertions.
3. Hermetic Testing: Use test fixtures, monkeypatching, and in-memory mock databases; never depend on live external APIs.
4. Edge Cases: Explicitly test boundary values, null inputs, path traversal, and unauthorized access attempts.
5. Invariants: Tests must pass cleanly with 100% reliability (0 flaky tests).
"""

def create_testing_agent_spec() -> SpecializedAgentSpec:
    return SpecializedAgentSpec(
        role=SpecializedAgentRole.TESTING,
        name="TestingAgent",
        system_prompt=TESTING_SYSTEM_PROMPT,
        allowed_file_patterns=[
            "backend/tests/*",
            "frontend/src/test/*",
            "frontend/src/**/*.test.tsx",
            "frontend/src/**/*.test.ts",
            "tests/*",
        ],
        forbidden_file_patterns=[".env*", "*.pem", "*.key"],
        allowed_tools=[
            "read_file",
            "write_file",
            "patch_file",
            "delete_file",
            "list_files",
            "execute_command",
            "run_tests",
            "inspect_diff",
        ],
        quality_gate_rules=[
            "All new test files execute cleanly via pytest or vitest.",
            "Zero unhandled exception tracebacks during test execution.",
            "Test execution passes within timeout ceilings (120s ceiling).",
        ],
    )
